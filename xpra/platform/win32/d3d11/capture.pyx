# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
DXGI Desktop Duplication capture backend.

Uses IDXGIOutputDuplication (Windows 8+) to capture the desktop,
using the D3D11 device shared with the GPU encoders (see `get_shared_device`).
Two textures are maintained:

  _gpu_tex  — D3D11_USAGE_DEFAULT, GPU-only.  Populated every refresh().

  _staging  — D3D11_USAGE_STAGING, CPU-readable.  Only populated by `download()`,
              when the pixels are actually needed in system memory.

Flow per frame:
  refresh()   -> AcquireNextFrame -> CopyResource(_gpu_tex, src) -> ReleaseFrame
  get_image() -> DXGIImageWrapper (neither GPU nor CPU copy yet)
  snapshot()  -> CopySubresourceRegion(pooled texture, _gpu_tex)  (for the GPU encoders)
  download()  -> CopySubresourceRegion(staging, texture) -> Map staging -> memcpy -> Unmap
"""

import time
from typing import Any
from threading import Lock

from libc.stdint cimport uintptr_t, uint8_t, uint32_t
from libc.string cimport memcpy
from cpython.bytes cimport PyBytes_FromStringAndSize, PyBytes_AS_STRING

from xpra.codecs.constants import CodecStateException
from xpra.platform.win32.d3d11.image import D3D11Texture
from xpra.log import Logger

log = Logger("shadow", "win32", "d3d11")

# how long `download()` waits for the GPU to finish copying to the staging texture:
MAP_TIMEOUT = 1.0


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
    #define XPRA_D3D11_MAP_FLAG_DO_NOT_WAIT    D3D11_MAP_FLAG_DO_NOT_WAIT

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

    /* ---- Immediate context of the (shared) device ---- */
    static void xpra_get_immediate_context(void *device, void **out_context)
    {
        ((ID3D11Device *)device)->lpVtbl->GetImmediateContext(
            (ID3D11Device *)device, (ID3D11DeviceContext **) out_context);
    }

    static void xpra_com_add_ref(void *obj)
    {
        ((IUnknown *)obj)->lpVtbl->AddRef((IUnknown *)obj);
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

    /* ---- GPU copy of an area, to the top-left corner of `dst` ---- */
    static void xpra_copy_region(void *context, void *dst, void *src,
                                 UINT x, UINT y, UINT width, UINT height)
    {
        D3D11_BOX box;
        box.left   = x;
        box.top    = y;
        box.front  = 0;
        box.right  = x + width;
        box.bottom = y + height;
        box.back   = 1;
        ((ID3D11DeviceContext *)context)->lpVtbl->CopySubresourceRegion(
            (ID3D11DeviceContext *)context,
            (ID3D11Resource *)dst, 0, 0, 0, 0,
            (ID3D11Resource *)src, 0, &box);
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

    /* ---- Create GPU-only (DEFAULT usage) texture for GPU encoder path ---- */
    static HRESULT xpra_create_gpu_tex(void *device, UINT w, UINT h,
                                        DXGI_FORMAT fmt, void **out_tex)
    {
        D3D11_TEXTURE2D_DESC desc = {0};
        desc.Width              = w;
        desc.Height             = h;
        desc.MipLevels          = 1;
        desc.ArraySize          = 1;
        desc.Format             = fmt;
        desc.SampleDesc.Count   = 1;
        desc.SampleDesc.Quality = 0;
        desc.Usage              = D3D11_USAGE_DEFAULT;
        desc.BindFlags          = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        desc.CPUAccessFlags     = 0;
        desc.MiscFlags          = 0;
        return ((ID3D11Device *)device)->lpVtbl->CreateTexture2D(
            (ID3D11Device *)device, &desc, NULL, (ID3D11Texture2D **)out_tex);
    }

    /* ---- Map staging texture ---- */
    static MapResult xpra_map_staging(void *context, void *staging, UINT flags)
    {
        D3D11_MAPPED_SUBRESOURCE mapped = {0};
        MapResult r;
        r.hr = ((ID3D11DeviceContext *)context)->lpVtbl->Map(
            (ID3D11DeviceContext *)context,
            (ID3D11Resource *)staging,
            0, D3D11_MAP_READ, flags, &mapped);
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
    unsigned int XPRA_D3D11_MAP_FLAG_DO_NOT_WAIT

    # helper functions
    void xpra_get_immediate_context(void *device, void **out_context)
    void xpra_com_add_ref(void *obj)
    int  xpra_get_output1(void *device, unsigned int output_idx, void **out_output1)
    int  xpra_duplicate_output(void *output1, void *device, void **out_dupl)
    DuplDesc xpra_get_dupl_desc(void *dupl)
    AcquireResult xpra_acquire_next_frame(void *dupl, unsigned int timeout_ms)
    int  xpra_release_frame(void *dupl)
    int  xpra_resource_to_texture(void *resource, void **out_texture)
    void xpra_copy_resource(void *context, void *dst, void *src)
    void xpra_copy_region(void *context, void *dst, void *src,
                          unsigned int x, unsigned int y, unsigned int width, unsigned int height)
    void xpra_flush(void *context)
    int  xpra_create_staging(void *device, unsigned int w, unsigned int h,
                              unsigned int fmt, void **out_staging)
    int  xpra_create_gpu_tex(void *device, unsigned int w, unsigned int h,
                              unsigned int fmt, void **out_tex)
    MapResult xpra_map_staging(void *context, void *staging, unsigned int flags)
    void xpra_unmap_staging(void *context, void *staging)
    void xpra_com_release(void *obj)

    ctypedef struct OutputPos:
        int x
        int y
    OutputPos xpra_get_output_pos(void *output1)


# DXGI format -> (pixel_format_string, bit_depth)
# DXGI_FORMAT values as integers to avoid cimport dependency on device.pyx
#
# `DuplicateOutput` always hands back `DXGI_FORMAT_B8G8R8A8_UNORM` (87),
# the other entries are only reachable if we ever switch to `DuplicateOutput1`.
#
# The 4th byte is always mapped to padding (`BGRX` / `RGBX`) and never to alpha:
# the desktop image is DWM's already composited output, which is opaque by
# construction, and DXGI does not define what this byte contains.
# Drivers do leave zeroes there (hardware overlays, protected content, ...),
# so exposing it as alpha would make those areas transparent.
_FORMAT_MAP: dict[int, tuple[str, int]] = {
    87:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8A8_UNORM - the only format `DuplicateOutput` returns
    88:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM
    91:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8A8_UNORM_SRGB
    93:  ("BGRX", 32),    # DXGI_FORMAT_B8G8R8X8_UNORM_SRGB
    28:  ("RGBX", 32),    # DXGI_FORMAT_R8G8B8A8_UNORM
}


cdef class DXGICapture:
    """
    DXGI Desktop Duplication capture backend for the xpra shadow server.
    Interface matches GDICapture: get_type/get_info/refresh/get_image/clean.
    """

    cdef void *_device      # ID3D11Device* — the shared device, we hold a reference
    cdef void *_context     # ID3D11DeviceContext*
    cdef void *_duplication # IDXGIOutputDuplication*
    cdef void *_gpu_tex     # ID3D11Texture2D* — D3D11_USAGE_DEFAULT, the latest frame
    cdef void *_staging     # ID3D11Texture2D* — D3D11_USAGE_STAGING, for CPU readback

    cdef object _pool           # the shared device's `TexturePool`, for snapshots
    cdef object _staging_lock   # `download()` runs from the encode threads

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
        self._pool = None
        self._staging_lock = Lock()

    def __repr__(self) -> str:
        return "DXGICapture(%dx%d %s output=%d)" % (
            self._width, self._height, self._pixel_format, self._output_index)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_context(self) -> None:
        cdef int hr

        from xpra.platform.win32.d3d11.device import get_shared_device
        device = get_shared_device()
        self._device = <void *> (<uintptr_t> device.get_ptr())
        xpra_com_add_ref(self._device)
        xpra_get_immediate_context(self._device, &self._context)
        self._pool = device.get_texture_pool()
        log("using shared D3D11 device=%#x, context=%#x", <uintptr_t> self._device, <uintptr_t> self._context)

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

        # GPU texture (DEFAULT usage) — populated every refresh(); never CPU-mapped.
        hr = xpra_create_gpu_tex(self._device,
                                  self._width, self._height, self._dxgi_format,
                                  &self._gpu_tex)
        if hr or not self._gpu_tex:
            raise RuntimeError("CreateTexture2D(gpu_tex) failed: %#x" % <unsigned int> hr)
        log("GPU texture created at %#x", <uintptr_t> self._gpu_tex)

        # Staging texture (STAGING usage) — CPU-readable; only populated by download().
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

    def get_adapter_luid(self) -> bytes:
        """ Identify the device holding the captured textures for GPU encoder selection. """
        from xpra.platform.win32.d3d11.device import D3D11Device
        with self._staging_lock:
            if not self._device:
                return b""
            return D3D11Device(<uintptr_t> self._device).get_luid()

    def get_info(self) -> dict[str, Any]:
        info = {
            "type":         "dxgi",
            "width":        self._width,
            "height":       self._height,
            "x":            self._output_x,
            "y":            self._output_y,
            "pixel-format": self._pixel_format,
            "depth":        self._depth,
            "output":       self._output_index,
        }
        if self._pool:
            info["snapshots"] = self._pool.get_info()
        return info

    def refresh(self) -> bool:
        """
        Acquire the next desktop frame.  On success, copies it GPU-side to the
        desktop texture and immediately releases the duplication frame.

        Returns True when new content was captured (caller should send damage).
        Returns False if the desktop has not changed.
        Raises CodecStateException on device-lost / access-lost errors,
        so that the shadow server re-creates its captures.
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
            raise CodecStateException("DXGI device lost: %#x" % <unsigned int> ar.hr)

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

        # GPU-side copy: desktop texture -> _gpu_tex (DEFAULT, GPU-only).
        # _staging is NOT touched here; it is only populated by download().
        xpra_copy_resource(self._context, self._gpu_tex, src_texture)
        xpra_com_release(src_texture)

        # Release the duplication frame immediately; _gpu_tex is now independent
        xpra_release_frame(self._duplication)
        xpra_flush(self._context)

        self._has_frame = 1
        return ar.accumulated_frames > 0

    def get_image(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0):
        """
        Return a DXGIImageWrapper for an area of the current frame.
        No copy happens here, see `snapshot()` and `download()`.
        """
        if not self._has_frame or not self._gpu_tex:
            return None

        if width == 0:
            width = self._width
        if height == 0:
            height = self._height

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

        from xpra.platform.win32.d3d11.image import DXGIImageWrapper
        return DXGIImageWrapper(x, y, width, height, self._pixel_format, self._depth, self)

    def snapshot(self, int x, int y, int width, int height) -> D3D11Texture | None:
        """
        Copy an area of the current frame to a texture of its own, without leaving the GPU.
        Must be called from the same thread as `refresh()`, which overwrites the desktop texture.
        The texture must be given back with `release_snapshot()`.
        """
        if not self._has_frame or not self._gpu_tex or not self._pool:
            return None
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > self._width or y + height > self._height:
            raise ValueError("invalid snapshot area %i,%i,%i,%i for %ix%i" % (
                x, y, width, height, self._width, self._height))
        cdef uintptr_t texture = self._pool.acquire(width, height, self._dxgi_format)
        if not texture:
            log("snapshot%s no texture available from %s", (x, y, width, height), self._pool)
            return None
        xpra_copy_region(self._context, <void *> texture, self._gpu_tex, x, y, width, height)
        xpra_flush(self._context)
        return D3D11Texture(texture, <uintptr_t> self._device, 0, 0, width, height)

    def release_snapshot(self, snapshot: D3D11Texture) -> None:
        """ can be called from any thread, and after `clean()` """
        self._pool.release(snapshot.texture, snapshot.width, snapshot.height, self._dxgi_format)

    def download(self, uintptr_t texture, int x, int y, int width, int height) -> bytes:
        """
        Copy an area of `texture` (or of the desktop texture if zero) to system memory.
        This can run from any thread: the device is shared and multithread protected,
        and the staging texture has a lock of its own.
        """
        if width <= 0 or height <= 0 or width > self._width or height > self._height:
            raise ValueError("invalid download size %ix%i" % (width, height))
        cdef MapResult mr
        cdef uint8_t *src
        cdef uint8_t *dst
        cdef uint32_t src_pitch
        cdef int bpp = self._depth // 8
        cdef int dst_stride = width * bpp
        cdef int row
        cdef bytes buf
        cdef void *src_texture
        with self._staging_lock:
            if not self._staging:
                raise RuntimeError("%s has been closed" % self)
            src_texture = <void *> texture
            if not src_texture:
                src_texture = self._gpu_tex
            xpra_copy_region(self._context, self._staging, src_texture, x, y, width, height)
            # don't wait for the GPU while holding the device lock,
            # the capture needs it on the UI thread:
            deadline = time.monotonic() + MAP_TIMEOUT
            while True:
                mr = xpra_map_staging(self._context, self._staging, XPRA_D3D11_MAP_FLAG_DO_NOT_WAIT)
                if mr.hr != XPRA_DXGI_ERROR_WAS_STILL_DRAWING:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("timeout waiting for the staging texture of %s" % self)
                time.sleep(0.0005)
            if mr.hr:
                raise RuntimeError("Map(staging) failed: %#x" % <unsigned int> mr.hr)
            try:
                # copy straight into a new bytes object:
                src = <uint8_t *> mr.pData
                src_pitch = mr.RowPitch
                buf = PyBytes_FromStringAndSize(NULL, dst_stride * height)
                dst = <uint8_t *> PyBytes_AS_STRING(buf)
                with nogil:
                    for row in range(height):
                        memcpy(dst + row * dst_stride, src + row * src_pitch, dst_stride)
            finally:
                xpra_unmap_staging(self._context, self._staging)
        return buf

    def clean(self) -> None:
        self._has_frame = 0
        with self._staging_lock:
            xpra_com_release(self._duplication)
            self._duplication = NULL
            xpra_com_release(self._staging)
            self._staging = NULL
            xpra_com_release(self._gpu_tex)
            self._gpu_tex = NULL
            xpra_com_release(self._context)
            self._context = NULL
            xpra_com_release(self._device)
            self._device = NULL
        # `self._pool` stays around for the snapshots that are still in use
        log("DXGICapture.clean() done")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def get_capture_instance(output_index: int = 0) -> DXGICapture:
    capture = DXGICapture(output_index)
    capture.init_context()
    return capture


def get_output_positions() -> dict[int, tuple[int, int]]:
    """ the desktop position of each output of the shared device's adapter """
    from xpra.platform.win32.d3d11.device import get_shared_device
    cdef void *device = <void *> (<uintptr_t> get_shared_device().get_ptr())
    cdef void *output1 = NULL
    cdef OutputPos pos
    positions = {}
    for output_index in range(8):
        output1 = NULL
        if xpra_get_output1(device, output_index, &output1) or not output1:
            break   # no more outputs on this adapter
        pos = xpra_get_output_pos(output1)
        xpra_com_release(output1)
        positions[output_index] = (pos.x, pos.y)
    return positions


def get_capture_for_monitor(x: int, y: int) -> DXGICapture | None:
    """
    Find and return a fully-initialised DXGICapture for the output whose
    desktop position matches (x, y).  Returns None if no output matches.
    Captures work in local (monitor-relative) coordinates.
    """
    # don't duplicate the other outputs just to find out where they are:
    # an output can only be duplicated once per process
    positions = get_output_positions()
    log("get_capture_for_monitor(%i, %i) output positions=%s", x, y, positions)
    for output_index, pos in positions.items():
        if pos != (x, y):
            continue
        capture = DXGICapture(output_index)
        try:
            capture.init_context()
        except RuntimeError:
            capture.clean()
            raise
        return capture
    return None


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
