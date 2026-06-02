# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam capture backend using DirectShow (Windows).

Builds a minimal DirectShow filter graph:
    Capture Device -> SampleGrabber -> NullRenderer

Frames are retrieved via ISampleGrabber.GetCurrentBuffer() on each read() call.
SampleGrabber and NullRenderer are provided by qedit.dll, which ships with all
supported Windows versions.
"""

import ctypes
import threading
from ctypes import POINTER, byref, c_long, c_int, c_wchar_p, c_ulong, c_void_p, c_ushort, c_longlong, c_ulonglong, Structure

import comtypes
import comtypes.client
from comtypes import IUnknown, GUID, HRESULT, COMMETHOD
from comtypes.automation import IDispatch

from xpra.codecs.image import ImageWrapper
from xpra.webcam.base import CameraDevice
from xpra.log import Logger

log = Logger("webcam")

DIRECTSHOW_READ_TIMEOUT = 3

# ── GUIDs ─────────────────────────────────────────────────────────────────────

CLSID_FilterGraph          = GUID("{E436EBB3-524F-11CE-9F53-0020AF0BA770}")
CLSID_CaptureGraphBuilder2 = GUID("{BF87B6E1-8C27-11D0-B3F0-00AA003761C5}")
CLSID_SampleGrabber        = GUID("{C1F400A0-3F08-11D3-9F0B-006008039E37}")
CLSID_NullRenderer         = GUID("{C1F400A4-3F08-11D3-9F0B-006008039E37}")

MEDIATYPE_Video      = GUID("{73646976-0000-0010-8000-00AA00389B71}")
FORMAT_VideoInfo     = GUID("{05589F80-C356-11CE-BF01-00AA0055595A}")
PIN_CATEGORY_CAPTURE = GUID("{FB6C4281-0353-11D1-905F-0000C0CC16BA}")

MEDIASUBTYPE_YUY2  = GUID("{32595559-0000-0010-8000-00AA00389B71}")
MEDIASUBTYPE_NV12  = GUID("{3231564E-0000-0010-8000-00AA00389B71}")
MEDIASUBTYPE_I420  = GUID("{30323449-0000-0010-8000-00AA00389B71}")
MEDIASUBTYPE_RGB24 = GUID("{E436EB7D-524F-11CE-9F53-0020AF0BA770}")
MEDIASUBTYPE_RGB32 = GUID("{E436EB7E-524F-11CE-9F53-0020AF0BA770}")

# Preference order for pixel format negotiation
PREFERRED_SUBTYPES = [
    MEDIASUBTYPE_YUY2,
    MEDIASUBTYPE_NV12,
    MEDIASUBTYPE_I420,
    MEDIASUBTYPE_RGB24,
    MEDIASUBTYPE_RGB32,
]

# DirectShow mediasubtype GUID string -> xpra pixel format string.
# RGB24/RGB32 frames from DirectShow have bottom-up row order and BGR/BGRX
# byte order; we flip them vertically in read().
DS_PIXEL_FORMATS: dict[str, str] = {
    str(MEDIASUBTYPE_YUY2):  "YUYV",
    str(MEDIASUBTYPE_NV12):  "NV12",
    str(MEDIASUBTYPE_I420):  "YUV420P",
    str(MEDIASUBTYPE_RGB24): "BGR",
    str(MEDIASUBTYPE_RGB32): "BGRX",
}

# Formats stored bottom-up by DirectShow; read() flips them to top-down
BOTTOM_UP_FORMATS = frozenset(("BGR", "BGRX"))

# Bits per pixel for planar/packed formats used in stride calculation
_BPP: dict[str, int] = {
    "YUYV":    16,
    "NV12":    12,
    "YUV420P": 12,
    "BGR":     24,
    "BGRX":    32,
}

# ── Structures ────────────────────────────────────────────────────────────────


class _RECT(Structure):
    _fields_ = [
        ("left",   c_long),
        ("top",    c_long),
        ("right",  c_long),
        ("bottom", c_long),
    ]


class _BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize",          c_ulong),
        ("biWidth",         c_long),
        ("biHeight",        c_long),
        ("biPlanes",        c_ushort),
        ("biBitCount",      c_ushort),
        ("biCompression",   c_ulong),
        ("biSizeImage",     c_ulong),
        ("biXPelsPerMeter", c_long),
        ("biYPelsPerMeter", c_long),
        ("biClrUsed",       c_ulong),
        ("biClrImportant",  c_ulong),
    ]


class _VIDEOINFOHEADER(Structure):
    _fields_ = [
        ("rcSource",        _RECT),
        ("rcTarget",        _RECT),
        ("dwBitRate",       c_ulong),
        ("dwBitErrorRate",  c_ulong),
        ("AvgTimePerFrame", c_longlong),
        ("bmiHeader",       _BITMAPINFOHEADER),
    ]


class _AM_MEDIA_TYPE(Structure):
    _fields_ = [
        ("majortype",            GUID),
        ("subtype",              GUID),
        ("bFixedSizeSamples",    c_int),
        ("bTemporalCompression", c_int),
        ("lSampleSize",          c_ulong),
        ("formattype",           GUID),
        ("pUnk",                 POINTER(IUnknown)),
        ("cbFormat",             c_ulong),
        ("pbFormat",             c_void_p),
    ]


# ── COM interface definitions ─────────────────────────────────────────────────
# Only the vtable slots we actually call are fully typed; placeholders use
# c_void_p so slot ordering stays correct for the slots we do invoke.


class IBaseFilter(IUnknown):
    _iid_ = GUID("{56A86895-0AD4-11CE-B03A-0020AF0BA770}")
    _methods_: list = []


class IPin(IUnknown):
    _iid_ = GUID("{56A86891-0AD4-11CE-B03A-0020AF0BA770}")
    _methods_: list = []


class IEnumFilters(IUnknown):
    _iid_ = GUID("{56A86893-0AD4-11CE-B03A-0020AF0BA770}")
    _methods_: list = []


class IFilterGraph(IUnknown):
    _iid_ = GUID("{56A8689F-0AD4-11CE-B03A-0020AF0BA770}")
    _methods_ = [
        COMMETHOD([], HRESULT, "AddFilter",
                  (["in"], POINTER(IBaseFilter), "pFilter"),
                  (["in"], c_wchar_p, "pName")),
        COMMETHOD([], HRESULT, "RemoveFilter",
                  (["in"], POINTER(IBaseFilter), "pFilter")),
        COMMETHOD([], HRESULT, "EnumFilters",
                  (["out"], POINTER(POINTER(IEnumFilters)), "ppEnum")),
        COMMETHOD([], HRESULT, "FindFilterByName",
                  (["in"], c_wchar_p, "pName"),
                  (["out"], POINTER(POINTER(IBaseFilter)), "ppFilter")),
        COMMETHOD([], HRESULT, "ConnectDirect",
                  (["in"], POINTER(IPin), "ppinOut"),
                  (["in"], POINTER(IPin), "ppinIn"),
                  (["in"], POINTER(_AM_MEDIA_TYPE), "pmt")),
        COMMETHOD([], HRESULT, "Reconnect",
                  (["in"], POINTER(IPin), "ppin")),
        COMMETHOD([], HRESULT, "Disconnect",
                  (["in"], POINTER(IPin), "ppin")),
        COMMETHOD([], HRESULT, "SetDefaultSyncSource"),
    ]


class IGraphBuilder(IFilterGraph):
    _iid_ = GUID("{56A868A9-0AD4-11CE-B03A-0020AF0BA770}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Connect",
                  (["in"], POINTER(IPin), "ppinOut"),
                  (["in"], POINTER(IPin), "ppinIn")),
        COMMETHOD([], HRESULT, "Render",
                  (["in"], POINTER(IPin), "ppinOut")),
        COMMETHOD([], HRESULT, "RenderFile",
                  (["in"], c_wchar_p, "lpcwstrFile"),
                  (["in"], c_wchar_p, "lpcwstrPlayList")),
        COMMETHOD([], HRESULT, "AddSourceFilter",
                  (["in"], c_wchar_p, "lpcwstrFileName"),
                  (["in"], c_wchar_p, "lpcwstrFilterName"),
                  (["out"], POINTER(POINTER(IBaseFilter)), "ppFilter")),
    ]


class ICaptureGraphBuilder2(IUnknown):
    _iid_ = GUID("{93E5A4E0-2D50-11D2-ABFA-00A0C9C6E38D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "SetFiltergraph",
                  (["in"], POINTER(IGraphBuilder), "pfg")),
        COMMETHOD([], HRESULT, "GetFiltergraph",
                  (["out"], POINTER(POINTER(IGraphBuilder)), "ppfg")),
        # SetOutputFileName – not used; keep slot intact
        COMMETHOD([], HRESULT, "SetOutputFileName",
                  (["in"], POINTER(GUID), "pType"),
                  (["in"], c_wchar_p, "lpstrFile"),
                  (["out"], POINTER(POINTER(IBaseFilter)), "ppf"),
                  (["out"], POINTER(c_void_p), "ppSink")),
        # FindInterface – not used
        COMMETHOD([], HRESULT, "FindInterface",
                  (["in"], POINTER(GUID), "pCategory"),
                  (["in"], POINTER(GUID), "pType"),
                  (["in"], POINTER(IBaseFilter), "pf"),
                  (["in"], GUID, "riid"),
                  (["out"], POINTER(c_void_p), "ppint")),
        COMMETHOD([], HRESULT, "RenderStream",
                  (["in"], POINTER(GUID), "pCategory"),
                  (["in"], POINTER(GUID), "pType"),
                  (["in"], POINTER(IUnknown), "pSource"),
                  (["in"], POINTER(IBaseFilter), "pfCompressor"),
                  (["in"], POINTER(IBaseFilter), "pfRenderer")),
        # ControlStream / AllocCapFile / CopyCaptureFile / FindPin – not used
        COMMETHOD([], HRESULT, "ControlStream",
                  (["in"], POINTER(GUID), "pCategory"),
                  (["in"], POINTER(GUID), "pType"),
                  (["in"], POINTER(IBaseFilter), "pFilter"),
                  (["in"], c_void_p, "pstart"),
                  (["in"], c_void_p, "pstop"),
                  (["in"], c_ushort, "wStartCookie"),
                  (["in"], c_ushort, "wStopCookie")),
        COMMETHOD([], HRESULT, "AllocCapFile",
                  (["in"], c_wchar_p, "lpstrFile"),
                  (["in"], c_ulonglong, "dwlSize")),
        COMMETHOD([], HRESULT, "CopyCaptureFile",
                  (["in"], c_wchar_p, "lpwstrOld"),
                  (["in"], c_wchar_p, "lpwstrNew"),
                  (["in"], c_int, "fAllowEscAbort"),
                  (["in"], c_void_p, "pCallback")),
        COMMETHOD([], HRESULT, "FindPin",
                  (["in"], POINTER(IUnknown), "pSource"),
                  (["in"], c_int, "pindir"),
                  (["in"], POINTER(GUID), "pCategory"),
                  (["in"], POINTER(GUID), "pType"),
                  (["in"], c_int, "fUnconnected"),
                  (["in"], c_int, "num"),
                  (["out"], POINTER(POINTER(IPin)), "ppPin")),
    ]


class ISampleGrabber(IUnknown):
    _iid_ = GUID("{6B652FFF-11FE-4FCE-92AD-0266B5D7C78F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "SetOneShot",
                  (["in"], c_int, "OneShot")),
        COMMETHOD([], HRESULT, "SetMediaType",
                  (["in"], POINTER(_AM_MEDIA_TYPE), "pType")),
        COMMETHOD([], HRESULT, "GetConnectedMediaType",
                  (["in", "out"], POINTER(_AM_MEDIA_TYPE), "pType")),
        COMMETHOD([], HRESULT, "SetBufferSamples",
                  (["in"], c_int, "BufferThem")),
        # pBuffer is long* per IDL, but treated as a raw byte buffer;
        # use c_void_p so callers can pass a ctypes array directly
        COMMETHOD([], HRESULT, "GetCurrentBuffer",
                  (["in", "out"], POINTER(c_long), "pBufferSize"),
                  (["in"], c_void_p, "pBuffer")),
        # GetCurrentSample – deprecated, keep slot
        COMMETHOD([], HRESULT, "GetCurrentSample",
                  (["out"], POINTER(c_void_p), "ppSample")),
        COMMETHOD([], HRESULT, "SetCallback",
                  (["in"], c_void_p, "pCallback"),
                  (["in"], c_long, "WhichMethodToCallback")),
    ]


class IMediaControl(IDispatch):
    """
    IMediaControl extends IDispatch.  comtypes inserts IDispatch's four
    vtable slots automatically (GetTypeInfoCount, GetTypeInfo, GetIDsOfNames,
    Invoke) before the entries below.
    """
    _iid_ = GUID("{56A868B1-0AD4-11CE-B03A-0020AF0BA770}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Run"),
        COMMETHOD([], HRESULT, "Pause"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "GetState",
                  (["in"], c_long, "msTimeout"),
                  (["out"], POINTER(c_int), "pfs")),
        # RenderFile / AddSourceFilter use BSTR; not called, placeholder types ok
        COMMETHOD([], HRESULT, "IMediaControl_RenderFile",
                  (["in"], c_void_p, "strFilename")),
        COMMETHOD([], HRESULT, "IMediaControl_AddSourceFilter",
                  (["in"], c_void_p, "strFilename"),
                  (["out"], POINTER(c_void_p), "ppUnk")),
        COMMETHOD([], HRESULT, "get_FilterCollection",
                  (["out"], POINTER(c_void_p), "ppUnk")),
        COMMETHOD([], HRESULT, "get_RegFilterCollection",
                  (["out"], POINTER(c_void_p), "ppUnk")),
        COMMETHOD([], HRESULT, "StopWhenReady"),
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hr_check(hr: int, op: str) -> None:
    if hr < 0:
        raise OSError(f"DirectShow {op} failed: HRESULT=0x{hr & 0xFFFFFFFF:08X}")


def _get_video_monikers() -> list:
    """Return a list of IMoniker objects for all DirectShow video input devices."""
    from xpra.platform.win32.comtypes_webcam import DeviceEnumerator, CLSID_VideoInputDeviceCategory
    from comtypes.client import CreateObject
    dev_enum = CreateObject(DeviceEnumerator)
    class_enum = dev_enum.CreateClassEnumerator(CLSID_VideoInputDeviceCategory, 0)
    monikers = []
    fetched = True
    while fetched:
        try:
            moniker, fetched = class_enum.RemoteNext(1)
            if fetched and moniker:
                monikers.append(moniker)
        except ValueError:
            break
    return monikers


def _bind_capture_filter(moniker) -> IBaseFilter:
    """Bind an IMoniker (from device enumeration) to IBaseFilter."""
    # RemoteBindToObject: (pbc=NULL, pmkToLeft=NULL, riid) -> IUnknown
    filter_unk = moniker.RemoteBindToObject(None, None, IBaseFilter._iid_)
    return filter_unk.QueryInterface(IBaseFilter)


def _request_format(grabber: ISampleGrabber, subtype: GUID) -> bool:
    """Ask ISampleGrabber to prefer a specific media subtype. Returns True on success."""
    mt = _AM_MEDIA_TYPE()
    mt.majortype = MEDIATYPE_Video
    mt.subtype = subtype
    try:
        hr = grabber.SetMediaType(byref(mt))
        return hr >= 0
    except Exception:
        return False


def _read_connected_format(grabber: ISampleGrabber) -> tuple[str, int, int, int]:
    """
    Query the media type that the SampleGrabber's input pin is connected with
    after the graph is built.  Returns (pixel_format, width, height, stride).
    """
    mt = _AM_MEDIA_TYPE()
    try:
        grabber.GetConnectedMediaType(byref(mt))
    except Exception as e:
        log("GetConnectedMediaType failed: %s", e)
        return "", 0, 0, 0

    pixel_format = DS_PIXEL_FORMATS.get(str(mt.subtype), "")
    width = height = stride = 0

    if mt.pbFormat and mt.cbFormat >= ctypes.sizeof(_VIDEOINFOHEADER):
        vih = ctypes.cast(mt.pbFormat, POINTER(_VIDEOINFOHEADER)).contents
        bih = vih.bmiHeader
        width = abs(bih.biWidth)
        # biHeight > 0 means bottom-up (common for RGB); store abs value
        height = abs(bih.biHeight)
        if bih.biBitCount:
            # stride aligned to 4-byte boundary
            stride = (width * bih.biBitCount // 8 + 3) & ~3

    # CoTaskMemFree the pbFormat blob to avoid a leak
    if mt.pbFormat:
        try:
            ctypes.windll.ole32.CoTaskMemFree(mt.pbFormat)
        except Exception:
            pass

    return pixel_format, width, height, stride


# ── Main class ────────────────────────────────────────────────────────────────

class DirectShowCamera(CameraDevice):
    """
    Webcam capture backend using DirectShow (Windows).

    Builds a filter graph ``Capture -> SampleGrabber -> NullRenderer`` with
    SampleGrabber operating in buffered (non-callback) mode.  Each call to
    read() calls GetCurrentBuffer() to snapshot the latest delivered frame.

    All COM objects are created on the thread that calls __init__ (STA assumed).
    read() and release() must be called from the same thread.
    """

    def __init__(self, device_index: int = 0) -> None:
        hr = ctypes.windll.ole32.CoInitialize(None)
        # S_OK (0) or S_FALSE (1) are both fine; RPC_E_CHANGED_MODE means the
        # thread is already MTA – DirectShow will still work in most cases.
        self._coinit_ok = hr in (0, 1)
        log("CoInitialize hr=0x%08X", hr & 0xFFFFFFFF)

        self._device_index = device_index
        self._graph: IGraphBuilder | None = None
        self._media_control: IMediaControl | None = None
        self._grabber: ISampleGrabber | None = None
        self._pixel_format = ""
        self._width = 0
        self._height = 0
        self._stride = 0
        self._lock = threading.Lock()
        self._setup()

    def _setup(self) -> None:
        log("DirectShowCamera._setup() device_index=%s", self._device_index)

        # Filter graph
        graph = comtypes.CoCreateInstance(CLSID_FilterGraph, interface=IGraphBuilder)
        log("graph=%s", graph)

        # Capture graph builder (helper for wiring capture graphs)
        cap_builder = comtypes.CoCreateInstance(CLSID_CaptureGraphBuilder2, interface=ICaptureGraphBuilder2)
        cap_builder.SetFiltergraph(graph)

        # Capture device filter
        monikers = _get_video_monikers()
        if self._device_index >= len(monikers):
            raise RuntimeError(
                f"DirectShow: device index {self._device_index} out of range "
                f"({len(monikers)} device(s) found)"
            )
        capture_filter = _bind_capture_filter(monikers[self._device_index])
        _hr_check(graph.AddFilter(capture_filter, "Capture"), "AddFilter(Capture)")
        log("capture_filter=%s", capture_filter)

        # Sample grabber filter
        grabber_filter = comtypes.CoCreateInstance(CLSID_SampleGrabber, interface=IBaseFilter)
        grabber = grabber_filter.QueryInterface(ISampleGrabber)

        # Negotiate an uncompressed pixel format
        chosen = None
        for subtype in PREFERRED_SUBTYPES:
            if _request_format(grabber, subtype):
                chosen = subtype
                log("DirectShowCamera: requested subtype %s", subtype)
                break
        if chosen is None:
            log("DirectShowCamera: no preferred subtype accepted; using default")

        grabber.SetBufferSamples(1)   # TRUE  – enable GetCurrentBuffer
        grabber.SetOneShot(0)         # FALSE – continuous delivery

        _hr_check(graph.AddFilter(grabber_filter, "SampleGrabber"), "AddFilter(SampleGrabber)")

        # Null renderer (absorbs rendered output)
        null_filter = comtypes.CoCreateInstance(CLSID_NullRenderer, interface=IBaseFilter)
        _hr_check(graph.AddFilter(null_filter, "NullRenderer"), "AddFilter(NullRenderer)")

        # Wire: Capture -> SampleGrabber -> NullRenderer
        cat = PIN_CATEGORY_CAPTURE
        mtype = MEDIATYPE_Video
        capture_unk = capture_filter.QueryInterface(IUnknown)
        _hr_check(
            cap_builder.RenderStream(byref(cat), byref(mtype), capture_unk, grabber_filter, null_filter),
            "RenderStream",
        )

        # Read back the negotiated format from the connected pin
        pixel_format, width, height, stride = _read_connected_format(grabber)
        if not pixel_format:
            pixel_format = "BGR"
        if not width or not height:
            width, height = 640, 480
        if not stride:
            bpp = _BPP.get(pixel_format, 24)
            stride = (width * bpp // 8 + 3) & ~3

        self._pixel_format = pixel_format
        self._width = width
        self._height = height
        self._stride = stride
        log("DirectShowCamera: %ix%i %s stride=%i", width, height, pixel_format, stride)

        # Start the graph
        media_control = graph.QueryInterface(IMediaControl)
        _hr_check(media_control.Run(), "IMediaControl.Run")

        self._graph = graph
        self._media_control = media_control
        self._grabber = grabber
        log("DirectShowCamera._setup() complete")

    def read(self) -> ImageWrapper | None:
        grabber = self._grabber
        if grabber is None:
            return None
        with self._lock:
            try:
                # First call with pBuffer=NULL returns the required byte count
                buf_size = c_long(0)
                hr = grabber.GetCurrentBuffer(byref(buf_size), None)
                if hr < 0 or buf_size.value <= 0:
                    log("DirectShowCamera.read(): GetCurrentBuffer(size) hr=0x%08X size=%i",
                        hr & 0xFFFFFFFF, buf_size.value)
                    return None

                n_bytes = buf_size.value
                buf = (ctypes.c_byte * n_bytes)()
                hr = grabber.GetCurrentBuffer(byref(buf_size), ctypes.cast(buf, c_void_p))
                if hr < 0:
                    log("DirectShowCamera.read(): GetCurrentBuffer(buf) hr=0x%08X", hr & 0xFFFFFFFF)
                    return None

                raw = bytes(buf)

                # Trim or reject if size doesn't match expected frame footprint
                w, h = self._width, self._height
                expected = self._stride * h
                if len(raw) > expected:
                    raw = raw[:expected]
                elif len(raw) < expected:
                    log("DirectShowCamera.read(): short buffer %i < %i", len(raw), expected)
                    return None

                # DirectShow RGB formats are stored bottom-up; flip to top-down
                if self._pixel_format in BOTTOM_UP_FORMATS:
                    rs = self._stride
                    raw = b"".join(raw[i * rs:(i + 1) * rs] for i in range(h - 1, -1, -1))

                image = ImageWrapper(0, 0, w, h, raw, self._pixel_format, 0, self._stride,
                                     planes=ImageWrapper.PACKED)
                log("%r.read()=%s", self, image)
                return image
            except Exception as e:
                log("DirectShowCamera.read() error: %s", e)
                return None

    def release(self) -> None:
        mc = self._media_control
        if mc is not None:
            try:
                mc.Stop()
            except Exception as e:
                log("DirectShowCamera.release() Stop error: %s", e)
        self._media_control = None
        self._grabber = None
        self._graph = None
        if self._coinit_ok:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

    @property
    def pixel_format(self) -> str:
        return self._pixel_format

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def __repr__(self) -> str:
        return f"DirectShowCamera({self._device_index})"
