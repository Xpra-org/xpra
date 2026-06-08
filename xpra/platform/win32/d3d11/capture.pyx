# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
DXGI Desktop Duplication capture backend.

Uses IDXGIOutputDuplication (Windows 8+) to capture the desktop into a
D3D11 staging texture which is then read back to CPU memory on demand.

Flow per frame:
  refresh() -> AcquireNextFrame -> CopyResource(staging) -> ReleaseFrame
  get_image() -> DXGIImageWrapper (no CPU copy yet)
  DXGIImageWrapper.may_download() -> Map staging -> memcpy -> Unmap
"""

import time
from typing import Any

from libc.stdint cimport uintptr_t, uint8_t, uint32_t
from libc.stddef cimport size_t
from libc.string cimport memcpy

from xpra.log import Logger

log = Logger("shadow", "win32", "d3d11")


# ---------------------------------------------------------------------------
# All COM / D3D11 / DXGI calls are wrapped in inline-C helpers.
# This avoids all vtable-layout declarations in Cython and sidesteps the
# absence of a device.pxd for cimport.
# ---------------------------------------------------------------------------

cdef extern from *:
    """
    #define COBJMACROS
    #include <windows.h>
    #include <d3d11.h>
    #include <dxgi1_2.h>
    #include <stdint.h>

    /* ---- GUIDs we need ---- */
    static const GUID _IID_IDXGIDevice = {
        0x54ec77fa,0x1377,0x44e6,{0x8c,0x32,0x88,0xfd,0x5f,0x44,0xc8,0x4c}};
    static const GUID _IID_IDXGIOutput1 = {
        0x00cddea8,0x939b,0x4b83,{0xa3,0x40,0xa6,0x85,0x22,0x66,0x66,0xcc}};
    static const GUID _IID_ID3D11Texture2D = {
        0x6f15aaf2,0xd208,0x4e89,{0x9a,0xb4,0x48,0x95,0x35,0xd3,0x4f,0x9c}};

    /* ---- Error codes ---- */
    #define XPRA_DXGI_ERROR_WAS_STILL_DRAWING  DXGI_ERROR_WAS_STILL_DRAWING
    #define XPRA_DXGI_ERROR_WAIT_TIMEOUT       DXGI_ERROR_WAIT_TIMEOUT
    #define XPRA_DXGI_ERROR_DEVICE_REMOVED     DXGI_ERROR_DEVICE_REMOVED
    #define XPRA_DXGI_ERROR_DEVICE_HUNG        DXGI_ERROR_DEVICE_HUNG
    #define XPRA_DXGI_ERROR_DEVICE_RESET       DXGI_ERROR_DEVICE_RESET
    #define XPRA_DXGI_ERROR_ACCESS_LOST        DXGI_ERROR_ACCESS_LOST

    /* ---- Result structures passed back to Cython as plain data ---- */
    typedef struct {
        HRESULT  hr;
        uint32_t accumulated_frames;
        void    *desktop_resource;   /* IDXGIResource*, caller releases */
    } AcquireResult;

    typedef struct {
        HRESULT  hr;
        uint32_t width;
        uint32_t height;
        uint32_t format;             /* DXGI_FORMAT */
    } DuplDesc;

    typedef struct {
        HRESULT  hr;
        void    *pData;
        uint32_t RowPitch;
    } MapResult;

    /* ---- Device creation ---- */
    static HRESULT xpra_create_device(void **out_device, void **out_context)
    {
        D3D_FEATURE_LEVEL fl;
        return D3D11CreateDevice(
            NULL,
            D3D_DRIVER_TYPE_HARDWARE,
            NULL,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            NULL, 0,
            D3D11_SDK_VERSION,
            (ID3D11Device **) out_device,
            &fl,
            (ID3D11DeviceContext **) out_context
        );
    }

    /* ---- Walk device -> adapter -> output -> IDXGIOutput1 ---- */
    static HRESULT xpra_get_output1(void *device, UINT output_idx, void **out_output1)
    {
        IDXGIDevice  *dxgi_dev  = NULL;
        IDXGIAdapter *adapter   = NULL;
        IDXGIOutput  *output    = NULL;
        IDXGIOutput1 *output1   = NULL;
        HRESULT hr;

        hr = ((ID3D11Device *)device)->lpVtbl->QueryInterface(
            (ID3D11Device *)device, &_IID_IDXGIDevice, (void **)&dxgi_dev);
        if (FAILED(hr)) return hr;

        hr = dxgi_dev->lpVtbl->GetAdapter(dxgi_dev, &adapter);
        dxgi_dev->lpVtbl->Release(dxgi_dev);
        if (FAILED(hr)) return hr;

        hr = adapter->lpVtbl->EnumOutputs(adapter, output_idx, &output);
        adapter->lpVtbl->Release(adapter);
        if (FAILED(hr)) return hr;

        hr = output->lpVtbl->QueryInterface(output, &_IID_IDXGIOutput1, (void **)&output1);
        output->lpVtbl->Release(output);
        if (FAILED(hr)) return hr;

        *out_output1 = output1;
        return S_OK;
    }

    /* ---- Create duplication ---- */
    static HRESULT xpra_duplicate_output(void *output1, void *device, void **out_dupl)
    {
        return ((IDXGIOutput1 *)output1)->lpVtbl->DuplicateOutput(
            (IDXGIOutput1 *)output1,
            (IUnknown *)device,
            (IDXGIOutputDuplication **)out_dupl
        );
    }

    /* ---- Get duplication descriptor ---- */
    static DuplDesc xpra_get_dupl_desc(void *dupl)
    {
        DXGI_OUTDUPL_DESC desc;
        DuplDesc r;
        ((IDXGIOutputDuplication *)dupl)->lpVtbl->GetDesc(
            (IDXGIOutputDuplication *)dupl, &desc);
        r.hr     = S_OK;
        r.width  = desc.ModeDesc.Width;
        r.height = desc.ModeDesc.Height;
        r.format = (uint32_t) desc.ModeDesc.Format;
        return r;
    }

    /* ---- AcquireNextFrame ---- */
    static AcquireResult xpra_acquire_next_frame(void *dupl, UINT timeout_ms)
    {
        DXGI_OUTDUPL_FRAME_INFO fi;
        IDXGIResource *res = NULL;
        AcquireResult r;
        r.hr = ((IDXGIOutputDuplication *)dupl)->lpVtbl->AcquireNextFrame(
            (IDXGIOutputDuplication *)dupl, timeout_ms, &fi, &res);
        r.accumulated_frames = (r.hr == S_OK) ? fi.AccumulatedFrames : 0;
        r.desktop_resource   = res;
        return r;
    }

    /* ---- ReleaseFrame ---- */
    static HRESULT xpra_release_frame(void *dupl)
    {
        return ((IDXGIOutputDuplication *)dupl)->lpVtbl->ReleaseFrame(
            (IDXGIOutputDuplication *)dupl);
    }

    /* ---- QI IDXGIResource -> ID3D11Texture2D, release resource ---- */
    static HRESULT xpra_resource_to_texture(void *resource, void **out_texture)
    {
        HRESULT hr = ((IDXGIResource *)resource)->lpVtbl->QueryInterface(
            (IDXGIResource *)resource, &_IID_ID3D11Texture2D, out_texture);
        ((IDXGIResource *)resource)->lpVtbl->Release((IDXGIResource *)resource);
        return hr;
    }

    /* ---- GPU copy ---- */
    static void xpra_copy_resource(void *context, void *dst, void *src)
    {
        ((ID3D11DeviceContext *)context)->lpVtbl->CopyResource(
            (ID3D11DeviceContext *)context,
            (ID3D11Resource *)dst,
            (ID3D11Resource *)src
        );
    }

    /* ---- Flush ---- */
    static void xpra_flush(void *context)
    {
        ((ID3D11DeviceContext *)context)->lpVtbl->Flush(
            (ID3D11DeviceContext *)context);
    }

    /* ---- Create staging texture ---- */
    static HRESULT xpra_create_staging(void *device, UINT w, UINT h,
                                        DXGI_FORMAT fmt, void **out_staging)
    {
        D3D11_TEXTURE2D_DESC desc = {0};
        desc.Width              = w;
        desc.Height             = h;
        desc.MipLevels          = 1;
        desc.ArraySize          = 1;
        desc.Format             = fmt;
        desc.SampleDesc.Count   = 1;
        desc.SampleDesc.Quality = 0;
        desc.Usage              = D3D11_USAGE_STAGING;
        desc.BindFlags          = 0;
        desc.CPUAccessFlags     = D3D11_CPU_ACCESS_READ;
        desc.MiscFlags          = 0;
        return ((ID3D11Device *)device)->lpVtbl->CreateTexture2D(
            (ID3D11Device *)device, &desc, NULL, (ID3D11Texture2D **)out_staging);
    }

    /* ---- Map staging texture ---- */
    static MapResult xpra_map_staging(void *context, void *staging)
    {
        D3D11_MAPPED_SUBRESOURCE mapped = {0};
        MapResult r;
        r.hr = ((ID3D11DeviceContext *)context)->lpVtbl->Map(
            (ID3D11DeviceContext *)context,
            (ID3D11Resource *)staging,
            0, D3D11_MAP_READ, 0, &mapped);
        r.pData    = mapped.pData;
        r.RowPitch = mapped.RowPitch;
        return r;
    }

    /* ---- Unmap staging texture ---- */
    static void xpra_unmap_staging(void *context, void *staging)
    {
        ((ID3D11DeviceContext *)context)->lpVtbl->Unmap(
            (ID3D11DeviceContext *)context,
            (ID3D11Resource *)staging,
            0);
    }

    /* ---- Generic COM Release ---- */
    static void xpra_com_release(void *obj)
    {
        if (obj) {
            /* All COM objects share the IUnknown layout */
            ((IUnknown *)obj)->lpVtbl->Release((IUnknown *)obj);
        }
    }

    /* ---- Desktop position of a DXGI output ---- */
    typedef struct { int x; int y; } OutputPos;

    static OutputPos xpra_get_output_pos(void *output1)
    {
        DXGI_OUTPUT_DESC desc;
        OutputPos pos = {0, 0};
        HRESULT hr = ((IDXGIOutput *)output1)->lpVtbl->GetDesc(
            (IDXGIOutput *)output1, &desc);
        if (SUCCEEDED(hr)) {
            pos.x = desc.DesktopCoordinates.left;
            pos.y = desc.DesktopCoordinates.top;
        }
        return pos;
    }

    /* ---- HRESULT helpers ---- */
    typedef struct { HRESULT hr; } HROnly;
    """

    # structs returned from C
    ctypedef struct AcquireResult:
        int      hr
        uint32_t accumulated_frames
        void    *desktop_resource

    ctypedef struct DuplDesc:
        int      hr
        uint32_t width
        uint32_t height
        uint32_t format

    ctypedef struct MapResult:
        int      hr
        void    *pData
        uint32_t RowPitch

    # error code constants
    int XPRA_DXGI_ERROR_WAS_STILL_DRAWING
    int XPRA_DXGI_ERROR_WAIT_TIMEOUT
    int XPRA_DXGI_ERROR_DEVICE_REMOVED
    int XPRA_DXGI_ERROR_DEVICE_HUNG
    int XPRA_DXGI_ERROR_DEVICE_RESET
    int XPRA_DXGI_ERROR_ACCESS_LOST

    # helper functions
    int  xpra_create_device(void **out_device, void **out_context)
    int  xpra_get_output1(void *device, unsigned int output_idx, void **out_output1)
    int  xpra_duplicate_output(void *output1, void *device, void **out_dupl)
    DuplDesc xpra_get_dupl_desc(void *dupl)
    AcquireResult xpra_acquire_next_frame(void *dupl, unsigned int timeout_ms)
    int  xpra_release_frame(void *dupl)
    int  xpra_resource_to_texture(void *resource, void **out_texture)
    void xpra_copy_resource(void *context, void *dst, void *src)
    void xpra_flush(void *context)
    int  xpra_create_staging(void *device, unsigned int w, unsigned int h,
                              unsigned int fmt, void **out_staging)
    MapResult xpra_map_staging(void *context, void *staging)
    void xpra_unmap_staging(void *context, void *staging)
    void xpra_com_release(void *obj)

    ctypedef struct OutputPos:
        int x
        int y
    OutputPos xpra_get_output_pos(void *output1)


# DXGI format -> (pixel_format_string, bit_depth)
# DXGI_FORMAT values as integers to avoid cimport dependency on device.pyx
_FORMAT_MAP: dict[int, tuple[str, int]] = {
    87:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM
    91:  ("BGRA", 32),    # DXGI_FORMAT_B8G8R8A8_UNORM_SRGB  (uncommon)
    87:  ("BGRX", 32),    # duplicate key; last wins — kept for clarity
    28:  ("RGBA", 32),    # DXGI_FORMAT_R8G8B8A8_UNORM
    26:  ("r210", 30),    # DXGI_FORMAT_R10G10B10A2_UNORM
    87:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM
    91:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM_SRGB
    # most common: 87 = BGRX, 88 = BGRA
    88:  ("BGRA", 32),    # DXGI_FORMAT_B8G8R8A8_UNORM (with alpha)
}
# Rebuild cleanly (the duplicate keys above were just for documentation)
_FORMAT_MAP = {
    87:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM
    88:  ("BGRA", 32),    # DXGI_FORMAT_B8G8R8A8_UNORM
    91:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM_SRGB
    28:  ("RGBA", 32),    # DXGI_FORMAT_R8G8B8A8_UNORM
    26:  ("r210", 30),    # DXGI_FORMAT_R10G10B10A2_UNORM
}


cdef class DXGICapture:
    """
    DXGI Desktop Duplication capture backend for the xpra shadow server.
    Interface matches GDICapture: get_type/get_info/refresh/get_image/clean.
    """

    cdef void *_device      # ID3D11Device*
    cdef void *_context     # ID3D11DeviceContext*
    cdef void *_duplication # IDXGIOutputDuplication*
    cdef void *_staging     # ID3D11Texture2D*

    cdef int      _width
    cdef int      _height
    cdef int      _depth
    cdef int      _has_frame
    cdef int      _output_index
    cdef int      _output_x      # left edge of this output in the virtual desktop
    cdef int      _output_y      # top edge of this output in the virtual desktop
    cdef uint32_t _dxgi_format
    cdef str      _pixel_format

    def __init__(self, output_index: int = 0):
        self._output_index = output_index
        self._output_x = 0
        self._output_y = 0
        self._has_frame = 0

    def __repr__(self) -> str:
        return "DXGICapture(%dx%d %s output=%d)" % (
            self._width, self._height, self._pixel_format, self._output_index)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_context(self) -> None:
        cdef int hr

        hr = xpra_create_device(&self._device, &self._context)
        if hr:
            raise RuntimeError("D3D11CreateDevice failed: %#x" % <unsigned int> hr)
        log("D3D11CreateDevice OK: device=%#x", <uintptr_t> self._device)

        cdef void *output1 = NULL
        hr = xpra_get_output1(self._device, self._output_index, &output1)
        if hr or not output1:
            raise RuntimeError("failed to get IDXGIOutput1 for output %d: %#x" % (
                self._output_index, <unsigned int> hr))

        cdef OutputPos pos = xpra_get_output_pos(output1)
        self._output_x = pos.x
        self._output_y = pos.y

        hr = xpra_duplicate_output(output1, self._device, &self._duplication)
        xpra_com_release(output1)
        if hr or not self._duplication:
            raise RuntimeError("DuplicateOutput failed: %#x" % <unsigned int> hr)

        cdef DuplDesc desc = xpra_get_dupl_desc(self._duplication)
        self._width      = desc.width
        self._height     = desc.height
        self._dxgi_format = desc.format

        fmt_info = _FORMAT_MAP.get(desc.format)
        if not fmt_info:
            raise RuntimeError("unsupported DXGI format: %d" % desc.format)
        self._pixel_format, self._depth = fmt_info

        log("DXGI output %d: %dx%d at (%d,%d) format=%d -> %s depth=%d",
            self._output_index, self._width, self._height,
            self._output_x, self._output_y,
            desc.format, self._pixel_format, self._depth)

        hr = xpra_create_staging(self._device,
                                  self._width, self._height, self._dxgi_format,
                                  &self._staging)
        if hr or not self._staging:
            raise RuntimeError("CreateTexture2D(staging) failed: %#x" % <unsigned int> hr)
        log("staging texture created at %#x", <uintptr_t> self._staging)

    # ------------------------------------------------------------------
    # Capture interface
    # ------------------------------------------------------------------

    def get_type(self) -> str:
        return "DXGI"

    def get_info(self) -> dict[str, Any]:
        return {
            "type":         "dxgi",
            "width":        self._width,
            "height":       self._height,
            "x":            self._output_x,
            "y":            self._output_y,
            "pixel-format": self._pixel_format,
            "depth":        self._depth,
            "output":       self._output_index,
        }

    def refresh(self) -> bool:
        """
        Acquire the next desktop frame.  On success, copies it GPU-side to the
        staging texture and immediately releases the duplication frame.

        Returns True when new content was captured (caller should send damage).
        Returns False if the desktop has not changed.
        Raises RuntimeError on device-lost / access-lost errors.
        """
        if not self._duplication:
            return False

        cdef AcquireResult ar = xpra_acquire_next_frame(self._duplication, 0)

        if ar.hr in (XPRA_DXGI_ERROR_WAS_STILL_DRAWING, XPRA_DXGI_ERROR_WAIT_TIMEOUT):
            return False   # no new frame ready

        if ar.hr in (XPRA_DXGI_ERROR_DEVICE_REMOVED,
                     XPRA_DXGI_ERROR_DEVICE_HUNG,
                     XPRA_DXGI_ERROR_DEVICE_RESET,
                     XPRA_DXGI_ERROR_ACCESS_LOST):
            raise RuntimeError("DXGI device lost: %#x" % <unsigned int> ar.hr)

        if ar.hr:
            log.warn("Warning: AcquireNextFrame failed: %#x", <unsigned int> ar.hr)
            return False

        if not ar.desktop_resource:
            xpra_release_frame(self._duplication)
            return False

        # QI IDXGIResource -> ID3D11Texture2D (releases resource on our behalf)
        cdef void *src_texture = NULL
        cdef int hr = xpra_resource_to_texture(ar.desktop_resource, &src_texture)
        if hr or not src_texture:
            xpra_release_frame(self._duplication)
            log.warn("Warning: failed to QI desktop resource as ID3D11Texture2D: %#x", <unsigned int> hr)
            return False

        # GPU-side copy: desktop texture -> our staging texture
        xpra_copy_resource(self._context, self._staging, src_texture)
        xpra_com_release(src_texture)

        # Release the duplication frame immediately; staging is now independent
        xpra_release_frame(self._duplication)
        xpra_flush(self._context)

        self._has_frame = 1
        return ar.accumulated_frames > 0

    def get_image(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0):
        """
        Return a DXGIImageWrapper for the current staged frame.
        No CPU copy happens here — it is deferred to may_download().
        """
        if not self._has_frame or not self._staging:
            return None

        if width == 0:
            width = self._width
        if height == 0:
            height = self._height

        # Shadow server passes global desktop coordinates; translate to output-local.
        x -= self._output_x
        y -= self._output_y

        # Clamp to output dimensions
        if x < 0:
            width += x
            x = 0
        if y < 0:
            height += y
            y = 0
        if x + width  > self._width:
            width  = self._width  - x
        if y + height > self._height:
            height = self._height - y
        if width <= 0 or height <= 0:
            return None

        cdef uintptr_t ctx_ptr     = <uintptr_t> self._context
        cdef uintptr_t staging_ptr = <uintptr_t> self._staging
        cdef int bpp               = self._depth // 8
        cdef int full_width        = self._width
        cdef int cap_x = x, cap_y = y, cap_w = width, cap_h = height

        pixel_format = self._pixel_format
        depth        = self._depth
        rowstride    = width * bpp

        def map_pixels():
            return _do_map(ctx_ptr, staging_ptr,
                           cap_x, cap_y, cap_w, cap_h,
                           full_width, bpp)

        def do_unmap():
            _do_unmap(ctx_ptr, staging_ptr)

        from xpra.platform.win32.d3d11.image import DXGIImageWrapper
        return DXGIImageWrapper(
            x, y, width, height,
            pixel_format, depth, rowstride,
            map_pixels, do_unmap,
            staging_ptr,
        )

    def clean(self) -> None:
        self._has_frame = 0
        xpra_com_release(self._duplication)
        self._duplication = NULL
        xpra_com_release(self._staging)
        self._staging = NULL
        xpra_com_release(self._context)
        self._context = NULL
        xpra_com_release(self._device)
        self._device = NULL
        log("DXGICapture.clean() done")


# ---------------------------------------------------------------------------
# Map / unmap helpers — called from DXGIImageWrapper closures
# ---------------------------------------------------------------------------

def _do_map(uintptr_t ctx_ptr, uintptr_t staging_ptr,
            int x, int y, int width, int height,
            int full_width, int bpp) -> bytes:
    """Map the staging texture and copy the requested rectangle to bytes."""
    cdef MapResult mr = xpra_map_staging(<void *> ctx_ptr, <void *> staging_ptr)
    if mr.hr:
        raise RuntimeError("Map(staging) failed: %#x" % <unsigned int> mr.hr)

    cdef uint8_t *src      = <uint8_t *> mr.pData
    cdef uint32_t src_pitch = mr.RowPitch
    cdef int dst_stride    = width * bpp
    cdef int nbytes        = dst_stride * height

    buf = bytearray(nbytes)
    cdef uint8_t [:] mv = buf
    cdef int row
    for row in range(height):
        memcpy(&mv[row * dst_stride],
               src + (y + row) * src_pitch + x * bpp,
               dst_stride)
    return bytes(buf)


def _do_unmap(uintptr_t ctx_ptr, uintptr_t staging_ptr) -> None:
    xpra_unmap_staging(<void *> ctx_ptr, <void *> staging_ptr)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def get_capture_instance(output_index: int = 0) -> DXGICapture:
    capture = DXGICapture(output_index)
    capture.init_context()
    return capture


def main(argv) -> int:
    import os
    from xpra.platform import program_context
    with program_context("DXGI-Capture", "DXGI Screen Capture"):
        from xpra.log import consume_verbose_argv
        consume_verbose_argv(argv, "d3d11")
        capture = get_capture_instance()
        print("Capture: %s" % capture)
        print("Info:    %s" % capture.get_info())
        for _ in range(10):
            if capture.refresh():
                break
            time.sleep(0.05)
        image = capture.get_image()
        if not image:
            print("ERROR: no image captured")
            capture.clean()
            return 1
        pixels = image.get_pixels()
        print("Image:   %s  pixels=%d bytes" % (image, len(pixels)))
        from xpra.codecs.image import to_pil_encoding
        data = to_pil_encoding(image, "png")
        from xpra.platform.paths import get_download_dir
        filename = os.path.join(get_download_dir(),
                                "dxgi-screenshot-%d.png" % time.time())
        with open(filename, "wb") as f:
            f.write(data)
        print("Saved:   %s" % filename)
        capture.clean()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
