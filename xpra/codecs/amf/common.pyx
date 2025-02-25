# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import CDLL, c_uint64, c_int, c_void_p, byref, POINTER

from libc.stddef cimport wchar_t
from libc.stdint cimport uint64_t, uintptr_t
from libc.string cimport memset

from xpra.codecs.amf.amf cimport (
    AMF_RESULT, AMF_OK,
    AMFFactory, AMFGuid, AMFTrace, AMFSurface, AMFPlane,
    AMFTraceWriter, AMFTraceWriterVtbl, AMF_TRACE_DEBUG, AMF_TRACE_INFO,
    amf_uint32, amf_uint16, amf_uint8, amf_int32,
    RESULT_STR,
)

from xpra.log import Logger

log = Logger("amf")
LIBNAME = "amfrt64"
try:
    amf = CDLL(LIBNAME)
except OSError as e:
    raise ImportError(f"AMF library {LIBNAME!r} not found: {e}") from None
assert amf

cdef extern from "Python.h":
    object PyUnicode_FromWideChar(wchar_t *w, Py_ssize_t size)
    wchar_t* PyUnicode_AsWideCharString(object unicode, Py_ssize_t *size)


cdef extern from "string.h":
    size_t wcslen(const wchar_t *str)


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
            fn = {
                "debug": log.debug,
                "info": log.info,
                "warning": log.warn,
                "error": log.error,
            }.get(category, fn)
            message_str = parts[1]
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


cdef get_version():
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
