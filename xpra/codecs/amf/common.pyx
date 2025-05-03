# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Tuple
from ctypes import CDLL, c_uint64, c_int, c_void_p, byref, POINTER

from xpra.common import noop
from xpra.log import Logger

from libc.stddef cimport wchar_t
from libc.stdint cimport uint64_t, uintptr_t
from libc.string cimport memset

from xpra.codecs.amf.amf cimport (
    AMF_RESULT, AMF_OK,
    AMFFactory, AMFGuid, AMFTrace, AMFSurface, AMFPlane, AMFData, AMFDataVtbl,
    AMFVariantInit,
    AMFTraceWriter, AMFTraceWriterVtbl, AMF_TRACE_DEBUG, AMF_TRACE_INFO,
    amf_uint32, amf_uint16, amf_uint8, amf_int32, amf_bool,
    AMFCaps, AMFIOCaps,
    AMF_FRAME_TYPE,
    AMF_SURFACE_FORMAT, AMF_MEMORY_TYPE,
    SURFACE_FORMAT_STR, MEMORY_TYPE_STR, DATA_TYPE_STR, FRAME_TYPE_STR,
    AMF_ACCELERATION_TYPE, ACCEL_TYPE_STR, PLANE_TYPE_STR,
    RESULT_STR,
)

cdef extern from "core/Factory.h":
    cdef const char* AMF_DLL_NAMEA


cdef extern from "Python.h":
    object PyUnicode_FromWideChar(wchar_t *w, Py_ssize_t size)
    wchar_t* PyUnicode_AsWideCharString(object unicode, Py_ssize_t *size)
    void PyMem_Free(void *ptr)


cdef extern from "string.h":
    size_t wcslen(const wchar_t *str)


log = Logger("amf")


cdef object load_library():
    libname = AMF_DLL_NAMEA.decode("latin1")
    options = [libname]
    import os
    import platform
    arch = platform.machine()   # ie: "x86_64"
    for lib_path in ("/opt/amdgpu-pro/lib64", f"/opt/amdgpu-pro/lib/{arch}-linux-gnu", os.environ.get("AMF_LIB_PATH", "")):
        if lib_path and os.path.exists(lib_path) and os.path.isdir(lib_path):
            options.append(os.path.join(lib_path, f"{libname}.so"))
    for option in options:
        try:
            return CDLL(option)
        except (OSError, ImportError) as e:
            log("CDLL({option!r})", exc_info=True)
    raise ImportError(f"AMF library {libname!r} not found")


amf = load_library()


cdef AMFFactory *factory
cdef int initialized = 0
cdef U_XPRA_TRACER = "xpra-tracer"

cdef wchar_t *XPRA_TRACER = PyUnicode_AsWideCharString(U_XPRA_TRACER, NULL)

cdef void trace_write(AMFTraceWriter* pThis, const wchar_t* scope, const wchar_t* message) noexcept nogil:
    with gil:
        scope_str = PyUnicode_FromWideChar(scope, -1) or ""
        message_str = (PyUnicode_FromWideChar(message, -1) or "").rstrip("\n\r")
        parts = message_str.split(": ", 1)
        # ie: "2025-02-25 17:46:29.642     1984 [AMFEncoderCoreH264]   Debug: AMFEncoderCoreH264Impl::Terminate()"
        # log.info(f"{scope_str=} {message_str=}")
        fn = log.info
        if len(parts) == 2:
            category = parts[0].split(" ")[-1].lower()
            message_str = parts[1]
            if (
                message_str.endswith("Switching to AllocBufferEx()")
                or message_str.startswith("Video core bandwidth calcs is not available")
                or message_str.startswith("***Found regpath, but key not found")
                or message_str.startswith("AMFEncoderCoreBaseImpl::QueryThroughput")
            ):
                fn = log.debug
            else:
                fn = {
                    "debug": log.debug,
                    "info": log.info,
                    "warning": log.warn,
                    "error": log.error,
                }.get(category, fn)
        fn(f"{scope_str}: {message_str}")

cdef void trace_flush(AMFTraceWriter* pThis) noexcept nogil:
    pass


cdef AMFTraceWriterVtbl xpra_trace_writer_functions
xpra_trace_writer_functions.Write = trace_write
xpra_trace_writer_functions.Flush = trace_flush

cdef AMFTraceWriter xpra_trace_writer
xpra_trace_writer.pVtbl = &xpra_trace_writer_functions

cdef AMFTrace *trace = NULL


cdef AMFFactory *get_factory():
    global initialized, factory
    cdef AMF_RESULT res = AMF_OK
    if not initialized:
        initialized = 1
        log("amf.common.get_factory() version=%s", get_version())
        version = get_c_version()
        AMFInit = amf.AMFInit
        AMFInit.argtypes = [c_uint64, c_void_p]
        res = AMFInit(version, <uintptr_t> &factory)
        log(f"AMFInit: {res=}")
        check(res, "AMF initialization")
        res = factory.pVtbl.GetTrace(factory, &trace)
        log(f"amf_encoder_init() GetTrace()={res}")
        if res == 0:
            assert trace != NULL
            log(f"Trace.GetGlobalLevel=%i", trace.pVtbl.GetGlobalLevel(trace))
            trace.pVtbl.RegisterWriter(trace, XPRA_TRACER, &xpra_trace_writer, 1)
            if log.is_debug_enabled():
                trace.pVtbl.SetGlobalLevel(trace, AMF_TRACE_DEBUG)
            else:
                trace.pVtbl.SetGlobalLevel(trace, AMF_TRACE_INFO)
    return factory


cdef void cleanup(self):
    global initialized
    log("amf.common.cleanup() initialized=%s", bool(initialized))
    if initialized:
        initialized = 0
        if trace:
            trace.pVtbl.UnregisterWriter(trace, XPRA_TRACER)


cdef tuple get_version():
    version = get_c_version()
    return version >> 48, (version >> 32) & 0xffff, (version >> 16) & 0xffff, version & 0xffff


cdef void check(AMF_RESULT res, message):
    log(f"check({res}, {message!r})")
    if res == 0:
        return
    error = error_str(res) or f"error {res}"
    raise RuntimeError(f"{message}: {error}")


cdef object error_str(AMF_RESULT result):
    if result == 0:
        return ""
    # try direct code lookup:
    err = RESULT_STR(result)
    if err:
        return err
    # fallback to API call:
    cdef AMFTrace *trace = NULL
    cdef AMF_RESULT res = factory.pVtbl.GetTrace(factory, &trace)
    if res != 0:
        return ""
    cdef const wchar_t *text = trace.pVtbl.GetResultText(trace, result)
    cdef size_t size = wcslen(text)
    return PyUnicode_FromWideChar(text, size)


cdef void set_guid(AMFGuid *guid,
                   amf_uint32 _data1, amf_uint16 _data2, amf_uint16 _data3,
                   amf_uint8 _data41, amf_uint8 _data42, amf_uint8 _data43, amf_uint8 _data44,
                   amf_uint8 _data45, amf_uint8 _data46, amf_uint8 _data47, amf_uint8 _data48):
    guid.data1 = _data1
    guid.data2 = _data2
    guid.data3 = _data3
    guid.data41 = _data41
    guid.data42 = _data42
    guid.data43 = _data43
    guid.data44 = _data44
    guid.data45 = _data45
    guid.data46 = _data46
    guid.data47 = _data47
    guid.data48 = _data48


cdef uint64_t get_c_version():
    version = c_uint64()
    AMFQueryVersion = amf.AMFQueryVersion
    AMFQueryVersion.argtypes = [POINTER(c_uint64)]
    AMFQueryVersion.restype = c_int
    res = AMFQueryVersion(byref(version))
    if res:
        return 0
    return int(version.value)


cdef void fill_nv12_surface(AMFSurface *surface, amf_uint8 Y, amf_uint8 U, amf_uint8 V):
    cdef AMFPlane *planeY = surface.pVtbl.GetPlaneAt(surface, 0)
    cdef amf_int32 widthY = planeY.pVtbl.GetWidth(planeY)
    cdef amf_int32 heightY = planeY.pVtbl.GetHeight(planeY)
    cdef amf_int32 lineY = planeY.pVtbl.GetHPitch(planeY)
    cdef amf_uint8 *Ydata = <amf_uint8 *> planeY.pVtbl.GetNative(planeY)
    cdef amf_int32 y
    cdef amf_uint8 *line
    for y in range(heightY):
        line = Ydata + y * lineY
        memset(line, Y, widthY)
    cdef AMFPlane *planeUV = surface.pVtbl.GetPlaneAt(surface, 1)
    cdef amf_int32 widthUV = planeUV.pVtbl.GetWidth(planeUV)
    cdef amf_int32 heightUV = planeUV.pVtbl.GetHeight(planeUV)
    cdef amf_int32 lineUV = planeUV.pVtbl.GetHPitch(planeUV)
    cdef amf_uint8 *UVdata = <amf_uint8 *> planeUV.pVtbl.GetNative(planeUV)
    cdef amf_int32 x
    for y in range(heightUV):
        line = UVdata + y * lineUV
        for x in range(widthUV):
            line[x] = U
            line[x+1] = V


cdef object get_caps(AMFCaps *caps, props: Dict):
    cdef AMFVariantStruct var
    cdef AMF_RESULT r

    def has_property(prop: str) -> bool:
        cdef wchar_t *wprop = PyUnicode_AsWideCharString(prop, NULL)
        try:
            return caps.pVtbl.HasProperty(caps, wprop)
        finally:
            PyMem_Free(wprop)

    def query_variant(prop: str) -> None:
        check(AMFVariantInit(&var), "AMF variant initialization")
        cdef wchar_t *wprop = PyUnicode_AsWideCharString(prop, NULL)
        check(caps.pVtbl.GetProperty(caps, wprop, &var), f"query {prop} caps")
        PyMem_Free(wprop)

    def get_int64(prop: str) -> int:
        query_variant(prop)
        return int(var.int64Value)

    def get_bool(prop: str) -> bool:
        query_variant(prop)
        return bool(var.boolValue)

    pycaps = {}
    cdef AMF_ACCELERATION_TYPE accel = caps.pVtbl.GetAccelerationType(caps)
    pycaps["acceleration"] = ACCEL_TYPE_STR(accel)

    getters: Dict[str, Callable] = {
        "max-bitrate": get_int64,
        "number-of-streams": get_int64,
        "max-profile": get_int64,
        "max-tier": get_int64,
        "max-level": get_int64,
        "b-frames": get_bool,
        "fixed-sliced-mode": get_bool,
        "hardware-instances": get_int64,
        "color-conversion": get_bool,
        "max-throughput": get_int64,
        "max-bitrate": get_int64,
        "pre-analysis": get_bool,
        "requested-throughput": get_int64,
        "roi": get_bool,
        "tile-output": get_bool,
        "width-alignment": get_int64,
        "height-alignment": get_int64,
    }
    for pyname, amfname in props.items():
        if not has_property(amfname):
            continue
        getter = getters.get(pyname, noop)
        log(f"getter({pyname})={getter}")
        if getter != noop:
            try:
                value = getter(amfname)
            except RuntimeError as e:
                log(f"failed to query {pyname}: {e}")
            else:
                pycaps[pyname] = value
    # add IO caps:
    cdef AMFIOCaps *iocaps = NULL
    check(caps.pVtbl.GetInputCaps(caps, &iocaps), f"retrieving encoder input caps")
    pycaps["input"] = get_io_caps(iocaps)
    check(caps.pVtbl.GetOutputCaps(caps, &iocaps), f"retrieving encoder output caps")
    pycaps["output"] = get_io_caps(iocaps)
    return pycaps


cdef object get_io_caps(AMFIOCaps *iocaps):
    caps = {
        "vertical-align": iocaps.pVtbl.GetVertAlign(iocaps),
    }
    cdef amf_int32 minval, maxval
    iocaps.pVtbl.GetWidthRange(iocaps, &minval, &maxval)
    caps["width-range"] = (minval, maxval)
    iocaps.pVtbl.GetHeightRange(iocaps, &minval, &maxval)
    caps["height-range"] = (minval, maxval)

    cdef amf_int32 count = iocaps.pVtbl.GetNumOfFormats(iocaps)
    cdef AMF_SURFACE_FORMAT surface_format
    cdef amf_bool native
    cdef AMF_RESULT r
    formats = []
    native_formats = []
    for i in range(count):
        r = iocaps.pVtbl.GetFormatAt(iocaps, i, &surface_format, &native)
        if r:
            continue
        name = SURFACE_FORMAT_STR(surface_format)
        if native:
            native_formats.append(name)
        else:
            formats.append(name)
    caps["native-formats"] = tuple(native_formats)
    caps["formats"] = tuple(formats)
    count = iocaps.pVtbl.GetNumOfMemoryTypes(iocaps)
    cdef AMF_MEMORY_TYPE memory_type
    memory_types = []
    native_memory_types = []
    for i in range(count):
        r = iocaps.pVtbl.GetMemoryTypeAt(iocaps, i, &memory_type, &native)
        if r:
            continue
        name = MEMORY_TYPE_STR(memory_type)
        if native:
            native_memory_types.append(name)
        else:
            memory_types.append(name)
    caps["native-memory-types"] = tuple(native_memory_types)
    caps["memory-types"] = tuple(memory_types)
    caps["interlaced-supported"] = bool(iocaps.pVtbl.IsInterlacedSupported(iocaps))
    return caps


cdef object get_plane_info(AMFPlane *plane):
    assert plane
    ptype = plane.pVtbl.GetType(plane)
    cdef const AMFPlaneVtbl *pfn = plane.pVtbl
    return {
        "type": PLANE_TYPE_STR(ptype),
        "native": <uintptr_t> pfn.GetNative(plane),
        "size": pfn.GetPixelSizeInBytes(plane),
        "offset-x": pfn.GetOffsetX(plane),
        "offset-y": pfn.GetOffsetY(plane),
        "width": pfn.GetWidth(plane),
        "height": pfn.GetHeight(plane),
        "h-pitch": pfn.GetHPitch(plane),
        "v-pitch": pfn.GetVPitch(plane),
        "is-tiled": pfn.IsTiled(plane),
    }


cdef object get_data_info(AMFData *data):
    assert data
    cdef const AMFDataVtbl *dfn = data.pVtbl
    return {
        "property-count": dfn.GetPropertyCount(data),
        "memory-type": MEMORY_TYPE_STR(dfn.GetMemoryType(data)),
        "data-type": DATA_TYPE_STR(dfn.GetDataType(data)),
    }


cdef object get_surface_info(AMFSurface *surface):
    assert surface
    cdef const AMFSurfaceVtbl *sfn = surface.pVtbl
    fmt = sfn.GetFormat(surface)
    cdef AMF_FRAME_TYPE ftype = sfn.GetFrameType(surface)
    return {
        "format": SURFACE_FORMAT_STR(fmt),
        "planes": sfn.GetPlanesCount(surface),
        "frame-type": FRAME_TYPE_STR(ftype),
    }
