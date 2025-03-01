# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stddef cimport wchar_t
from libc.stdint cimport uint8_t, uint16_t, uint32_t, int32_t, int64_t, uint64_t

ctypedef void *amf_handle
ctypedef long amf_long
ctypedef uint8_t amf_bool
ctypedef uint8_t amf_uint8
ctypedef uint16_t amf_uint16
ctypedef uint32_t amf_uint32
ctypedef int32_t amf_int32
ctypedef int64_t amf_int64
ctypedef int64_t amf_pts
ctypedef size_t amf_size
ctypedef void* AMFDataAllocatorCB
ctypedef void* AMFComponentOptimizationCallback


cdef extern from "Python.h":
    object PyUnicode_FromWideChar(wchar_t *w, Py_ssize_t size)


cdef extern from "string.h":
    size_t wcslen(const wchar_t *str)


cdef extern from "stdarg.h":
    ctypedef struct va_list:
        pass


cdef extern from "core/Result.h":
    enum AMF_RESULT:
        AMF_OK
        AMF_FAIL
        # common errors
        AMF_UNEXPECTED
        AMF_ACCESS_DENIED
        AMF_INVALID_ARG
        AMF_OUT_OF_RANGE
        AMF_OUT_OF_MEMORY
        AMF_INVALID_POINTER
        AMF_NO_INTERFACE
        AMF_NOT_IMPLEMENTED
        AMF_NOT_SUPPORTED
        AMF_NOT_FOUND
        AMF_ALREADY_INITIALIZED
        AMF_NOT_INITIALIZED
        AMF_INVALID_FORMAT
        AMF_WRONG_STATE
        AMF_FILE_NOT_OPEN
        # device common codes
        AMF_NO_DEVICE
        AMF_DIRECTX_FAILED
        AMF_OPENCL_FAILED
        AMF_GLX_FAILED
        AMF_XV_FAILED
        AMF_ALSA_FAILED
        # result codes
        AMF_EOF
        AMF_REPEAT
        AMF_INPUT_FULL
        AMF_RESOLUTION_CHANGED
        AMF_RESOLUTION_UPDATED
        # error codes
        AMF_INVALID_DATA_TYPE
        AMF_INVALID_RESOLUTION
        AMF_CODEC_NOT_SUPPORTED
        AMF_SURFACE_FORMAT_NOT_SUPPORTED
        AMF_SURFACE_MUST_BE_SHARED
        # component video decoder
        AMF_DECODER_NOT_PRESENT
        AMF_DECODER_SURFACE_ALLOCATION_FAILED
        AMF_DECODER_NO_FREE_SURFACES
        # component video encoder
        AMF_ENCODER_NOT_PRESENT
        # component dem
        AMF_DEM_ERROR
        AMF_DEM_PROPERTY_READONLY
        AMF_DEM_REMOTE_DISPLAY_CREATE_FAILED
        AMF_DEM_START_ENCODING_FAILED
        AMF_DEM_QUERY_OUTPUT_FAILED
        # component TAN
        AMF_TAN_CLIPPING_WAS_REQUIRED           # Resulting data was truncated to meet output type's value limits.
        AMF_TAN_UNSUPPORTED_VERSION             # Not supported version requested, solely for TANCreateContext().
        AMF_NEED_MORE_INPUT                     # returned by AMFComponent::SubmitInput did not produce a buffer because more input submissions are required.
        # device vulkan
        AMF_VULKAN_FAILED


cdef inline MEMORY_TYPE_STR(AMF_MEMORY_TYPE memory):
    return {
        AMF_MEMORY_UNKNOWN: "UNKNOWN",
        AMF_MEMORY_HOST: "HOST",
        AMF_MEMORY_DX9: "DX9",
        AMF_MEMORY_DX11: "DX11",
        AMF_MEMORY_OPENCL: "OPENCL",
        AMF_MEMORY_OPENGL: "OPENGL",
        AMF_MEMORY_XV: "XV",
        AMF_MEMORY_GRALLOC: "GRALLOC",
        AMF_MEMORY_COMPUTE_FOR_DX9: "COMPUTE_FOR_DX9",
        AMF_MEMORY_COMPUTE_FOR_DX11: "COMPUTE_FOR_DX11",
        AMF_MEMORY_VULKAN: "VULKAN",
        AMF_MEMORY_DX12: "DX12",
    }.get(memory, "unknown")


cdef inline RESULT_STR(AMF_RESULT res):
    return {
        AMF_OK: "OK",
        AMF_FAIL: "FAIL",
        AMF_UNEXPECTED: "UNEXPECTED",
        AMF_ACCESS_DENIED: "ACCESS_DENIED",
        AMF_INVALID_ARG: "INVALID_ARG",
        AMF_OUT_OF_RANGE: "OUT_OF_RANGE",
        AMF_OUT_OF_MEMORY: "OUT_OF_MEMORY",
        AMF_INVALID_POINTER: "INVALID_POINTER",
        AMF_NO_INTERFACE: "NO_INTERFACE",
        AMF_NOT_IMPLEMENTED: "NOT_IMPLEMENTED",
        AMF_NOT_SUPPORTED: "NOT_SUPPORTED",
        AMF_NOT_FOUND: "NOT_FOUND",
        AMF_ALREADY_INITIALIZED: "ALREADY_INITIALIZED",
        AMF_NOT_INITIALIZED: "NOT_INITIALIZED",
        AMF_INVALID_FORMAT: "INVALID_FORMAT",
        AMF_WRONG_STATE: "WRONG_STATE",
        AMF_FILE_NOT_OPEN: "FILE_NOT_OPEN",
        AMF_NO_DEVICE: "NO_DEVICE",
        AMF_DIRECTX_FAILED: "DIRECTX_FAILED",
        AMF_OPENCL_FAILED: "OPENCL_FAILED",
        AMF_GLX_FAILED: "GLX_FAILED",
        AMF_XV_FAILED: "XV_FAILED",
        AMF_ALSA_FAILED: "ALSA_FAILED",
        AMF_EOF: "EOF",
        AMF_REPEAT: "REPEAT",
        AMF_INPUT_FULL: "INPUT_FULL",
        AMF_RESOLUTION_CHANGED: "RESOLUTION_CHANGED",
        AMF_RESOLUTION_UPDATED: "RESOLUTION_UPDATED",
        AMF_INVALID_DATA_TYPE: "INVALID_DATA_TYPE",
        AMF_INVALID_RESOLUTION: "INVALID_RESOLUTION",
        AMF_CODEC_NOT_SUPPORTED: "CODEC_NOT_SUPPORTED",
        AMF_SURFACE_FORMAT_NOT_SUPPORTED: "SURFACE_FORMAT_NOT_SUPPORTED",
        AMF_SURFACE_MUST_BE_SHARED: "SURFACE_MUST_BE_SHARED",
        AMF_DECODER_NOT_PRESENT: "DECODER_NOT_PRESENT",
        AMF_DECODER_SURFACE_ALLOCATION_FAILED: "DECODER_SURFACE_ALLOCATION_FAILED",
        AMF_DECODER_NO_FREE_SURFACES: "DECODER_NO_FREE_SURFACES",
        AMF_ENCODER_NOT_PRESENT: "ENCODER_NOT_PRESENT",
        AMF_DEM_ERROR: "DEM_ERROR",
        AMF_DEM_PROPERTY_READONLY: "DEM_PROPERTY_READONLY",
        AMF_DEM_REMOTE_DISPLAY_CREATE_FAILED: "DEM_REMOTE_DISPLAY_CREATE_FAILED",
        AMF_DEM_START_ENCODING_FAILED: "DEM_START_ENCODING_FAILED",
        AMF_DEM_QUERY_OUTPUT_FAILED: "DEM_QUERY_OUTPUT_FAILED",
        AMF_TAN_CLIPPING_WAS_REQUIRED: "TAN_CLIPPING_WAS_REQUIRED",
        AMF_TAN_UNSUPPORTED_VERSION: "TAN_UNSUPPORTED_VERSION",
        AMF_NEED_MORE_INPUT: "NEED_MORE_INPUT",
        AMF_VULKAN_FAILED: "VULKAN_FAILED",
    }.get(res, "")


cdef extern from "core/Data.h":
    ctypedef enum AMF_DATA_TYPE:
        AMF_DATA_BUFFER         # 0
        AMF_DATA_SURFACE        # 1
        AMF_DATA_AUDIO_BUFFER   # 2
        AMF_DATA_USER           # 1000

    ctypedef enum AMF_MEMORY_TYPE:
        AMF_MEMORY_UNKNOWN          # 0
        AMF_MEMORY_HOST             # 1
        AMF_MEMORY_DX9              # 2
        AMF_MEMORY_DX11             # 3
        AMF_MEMORY_OPENCL           # 4
        AMF_MEMORY_OPENGL           # 5
        AMF_MEMORY_XV               # 6
        AMF_MEMORY_GRALLOC          # 7
        AMF_MEMORY_COMPUTE_FOR_DX9  # 8  deprecated, the same as AMF_MEMORY_OPENCL
        AMF_MEMORY_COMPUTE_FOR_DX11 # 9 deprecated, the same as AMF_MEMORY_OPENCL
        AMF_MEMORY_VULKAN           # 10
        AMF_MEMORY_DX12             # 11

    ctypedef amf_long (*DATA_ACQUIRE)(AMFData* pThis)
    ctypedef amf_long (*DATA_RELEASE)(AMFData* pThis)
    ctypedef AMF_RESULT (*DATA_QUERYINTERFACE)(AMFData* pThis, const AMFGuid *interfaceID, void** ppInterface)
    ctypedef amf_size (*DATA_GETPROPERTYCOUNT)(AMFData* pThis)
    ctypedef AMF_MEMORY_TYPE (*DATA_GETMEMORYTYPE)(AMFData* pThis)
    ctypedef AMF_DATA_TYPE (*DATA_GETDATATYPE)(AMFData* pThis)
    ctypedef AMF_RESULT (*DATA_CONVERT)(AMFData* pThis, AMF_MEMORY_TYPE type)
    ctypedef AMF_RESULT (*DATA_INTEROP)(AMFData* pThis, AMF_MEMORY_TYPE type)

    ctypedef struct AMFDataVtbl:
        DATA_ACQUIRE Acquire
        DATA_RELEASE Release
        DATA_QUERYINTERFACE QueryInterface
        DATA_GETPROPERTYCOUNT GetPropertyCount
        DATA_GETMEMORYTYPE GetMemoryType
        DATA_GETDATATYPE GetDataType
        DATA_CONVERT Convert
        DATA_INTEROP Interop

    ctypedef struct AMFData:
        const AMFDataVtbl *pVtbl


cdef extern from "core/Platform.h":
    ctypedef struct AMFSize:
        amf_int32 width
        amf_int32 height

    ctypedef struct AMFRate:
        amf_uint32 num
        amf_uint32 den

    ctypedef struct AMFGuid:
        amf_uint32 data1
        amf_uint16 data2
        amf_uint16 data3
        amf_uint8 data41
        amf_uint8 data42
        amf_uint8 data43
        amf_uint8 data44
        amf_uint8 data45
        amf_uint8 data46
        amf_uint8 data47
        amf_uint8 data48
    ctypedef struct AMFRect:
        amf_int32 left
        amf_int32 top
        amf_int32 right
        amf_int32 bottom


cdef extern from "core/Variant.h":
    ctypedef enum AMF_VARIANT_TYPE:
        AMF_VARIANT_EMPTY           # 0
        AMF_VARIANT_BOOL            # 1
        AMF_VARIANT_INT64           # 2
        AMF_VARIANT_DOUBLE          # 3
        AMF_VARIANT_RECT            # 4
        AMF_VARIANT_SIZE            # 5
        AMF_VARIANT_POINT           # 6
        AMF_VARIANT_RATE            # 7
        AMF_VARIANT_RATIO           # 8
        AMF_VARIANT_COLOR           # 9
        AMF_VARIANT_STRING          # 10  // value is char*
        AMF_VARIANT_WSTRING         # 11  // value is wchar_t*
        AMF_VARIANT_INTERFACE       # 12  // value is AMFInterface*
        AMF_VARIANT_FLOAT           # 13
        AMF_VARIANT_FLOAT_SIZE      # 14
        AMF_VARIANT_FLOAT_POINT2D   # 15
        AMF_VARIANT_FLOAT_POINT3D   # 16
        AMF_VARIANT_FLOAT_VECTOR4D  # 17


    ctypedef struct AMFVariantStruct:
        AMF_VARIANT_TYPE type
        AMFSize sizeValue
        AMFRate rateValue
        int64_t int64Value
        amf_bool boolValue

    AMF_RESULT AMFVariantInit(AMFVariantStruct* pDest)
    AMF_RESULT AMFVariantAssignInt64(AMFVariantStruct* pDest, amf_int64 value)
    AMF_RESULT AMFVariantAssignSize(AMFVariantStruct* pDest, const AMFSize &value)
    AMF_RESULT AMFVariantAssignRate(AMFVariantStruct* pDest, const AMFRate &value)
    AMF_RESULT AMFVariantClear(AMFVariantStruct* pDest)


cdef extern from "core/Plane.h":
    ctypedef enum AMF_PLANE_TYPE:
        AMF_PLANE_UNKNOWN       # 0
        AMF_PLANE_PACKED        # 1 for all packed formats: BGRA, YUY2, etc
        AMF_PLANE_Y             # 2
        AMF_PLANE_UV            # 3
        AMF_PLANE_U             # 4
        AMF_PLANE_V             # 5

    ctypedef amf_long (*PLANE_ACQUIRE)(AMFPlane* pThis)
    ctypedef amf_long (*PLANE_RELEASE)(AMFPlane* pThis)
    ctypedef AMF_RESULT (*PLANE_QUERYINTERFACE)(AMFPlane* pThis, const AMFGuid *interfaceID, void** ppInterface)

    ctypedef AMF_PLANE_TYPE (*PLANE_GETTYPE)(AMFPlane* pThis)
    ctypedef void* (*PLANE_GETNATIVE)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETPIXELSIZEINBYTES)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETOFFSETX)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETOFFSETY)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETWIDTH)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETHEIGHT)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETHPITCH)(AMFPlane* pThis)
    ctypedef amf_int32 (*PLANE_GETVPITCH)(AMFPlane* pThis)
    ctypedef amf_bool (*PLANE_ISTILED)(AMFPlane* pThis)

    ctypedef struct AMFPlaneVtbl:
        PLANE_ACQUIRE Acquire
        PLANE_RELEASE Release
        PLANE_QUERYINTERFACE QueryInterface

        PLANE_GETTYPE GetType
        PLANE_GETNATIVE GetNative
        PLANE_GETPIXELSIZEINBYTES GetPixelSizeInBytes
        PLANE_GETOFFSETX GetOffsetX
        PLANE_GETOFFSETY GetOffsetY
        PLANE_GETWIDTH GetWidth
        PLANE_GETHEIGHT GetHeight
        PLANE_GETHPITCH GetHPitch
        PLANE_GETVPITCH GetVPitch
        PLANE_ISTILED IsTiled

    ctypedef struct AMFPlane:
        const AMFPlaneVtbl *pVtbl


cdef extern from "core/Buffer.h":
    enum AMF_BUFFER_USAGE_BITS:
        AMF_BUFFER_USAGE_DEFAULT
        AMF_BUFFER_USAGE_NONE
        AMF_BUFFER_USAGE_CONSTANT
        AMF_BUFFER_USAGE_SHADER_RESOURCE
        AMF_BUFFER_USAGE_UNORDERED_ACCESS
        AMF_BUFFER_USAGE_TRANSFER_SRC
        AMF_BUFFER_USAGE_TRANSFER_DST
        AMF_BUFFER_USAGE_NOSYNC
        AMF_BUFFER_USAGE_DECODER_SRC

    ctypedef amf_long (*BUFFER_ACQUIRE)(AMFBuffer* pThis)
    ctypedef amf_long (*BUFFER_RELEASE)(AMFBuffer* pThis)
    ctypedef AMF_RESULT (*BUFFER_QUERYINTERFACE)(AMFBuffer* pThis, const AMFGuid *interfaceID, void** ppInterface)
    ctypedef AMF_RESULT (*BUFFER_SETPROPERTY)(AMFBuffer* pThis, const wchar_t *pName, AMFVariantStruct value)
    ctypedef AMF_RESULT (*BUFFER_GETPROPERTY)(AMFBuffer* pThis, const wchar_t *pName, AMFVariantStruct* pValue)
    ctypedef amf_bool (*BUFFER_HASPROPERTY)(AMFBuffer* pThis, const wchar_t *pName, AMFVariantStruct* pValue)
    ctypedef amf_size (*BUFFER_GETPROPERTYCOUNT)(AMFBuffer* pThis)
    ctypedef AMF_MEMORY_TYPE (*BUFFER_GETMEMORYTYPE)(AMFBuffer* pThis)
    ctypedef AMF_DATA_TYPE (*BUFFER_GETDATATYPE)(AMFBuffer* pThis)
    ctypedef amf_bool (*BUFFER_ISREUSABLE)(AMFBuffer* pThis)
    ctypedef void (*BUFFER_SETPTS)(AMFBuffer* pThis, amf_pts pts)
    ctypedef amf_pts (*BUFFER_GETPTS)(AMFBuffer* pThis)
    ctypedef void (*BUFFER_SETDURATION)(AMFBuffer* pThis, amf_pts duration)
    ctypedef amf_pts (*BUFFER_GETDURATION)(AMFBuffer* pThis)
    # AMFBuffer interface
    ctypedef AMF_RESULT (*BUFFER_SETSIZE)(AMFBuffer* pThis, amf_size newSize)
    ctypedef AMF_RESULT (*BUFFER_GETSIZE)(AMFBuffer* pThis)
    ctypedef void* (*BUFFER_GETNATIVE)(AMFBuffer* pThis)

    ctypedef struct AMFBufferVtbl:
        BUFFER_ACQUIRE Acquire
        BUFFER_RELEASE Release
        BUFFER_QUERYINTERFACE QueryInterface
        BUFFER_SETPROPERTY SetProperty
        BUFFER_GETPROPERTY GetProperty
        BUFFER_GETPROPERTYCOUNT GetPropertyCount
        BUFFER_GETMEMORYTYPE GetMemoryType
        BUFFER_GETDATATYPE GetDataType
        BUFFER_ISREUSABLE IsReusable
        BUFFER_SETPTS SetPts
        BUFFER_GETPTS GetPts
        BUFFER_SETDURATION SetDuration
        BUFFER_GETDURATION GetDuration
        BUFFER_SETSIZE SetSize
        BUFFER_GETSIZE GetSize
        BUFFER_GETNATIVE GetNative

    ctypedef struct AMFBuffer:
        const AMFBufferVtbl *pVtbl


cdef inline PLANE_TYPE_STR(AMF_PLANE_TYPE ptype):
    return {
        AMF_PLANE_UNKNOWN: "UNKNOWN",
        AMF_PLANE_PACKED: "PACKED",
        AMF_PLANE_Y: "Y",
        AMF_PLANE_UV: "UV",
        AMF_PLANE_U: "U",
        AMF_PLANE_V: "V",
    }.get(ptype, "unknown")


cdef extern from "core/Trace.h":
    cdef int AMF_TRACE_ERROR
    cdef int AMF_TRACE_WARNING
    cdef int AMF_TRACE_INFO
    cdef int AMF_TRACE_DEBUG
    cdef int AMF_TRACE_TRACE

    ctypedef void (*TRACEWRITE)(AMFTraceWriter* pThis, const wchar_t* scope, const wchar_t* message) noexcept nogil
    ctypedef void (*TRACEFLUSH)(AMFTraceWriter* pThis) noexcept nogil

    ctypedef struct AMFTraceWriterVtbl:
        TRACEWRITE Write
        TRACEFLUSH Flush

    ctypedef struct AMFTraceWriter:
        const AMFTraceWriterVtbl *pVtbl

    ctypedef void (*TRACEW)(AMFTrace* pThis, const wchar_t* src_path, amf_int32 line, amf_int32 level, const wchar_t* scope,amf_int32 countArgs, const wchar_t* format, ...)
    ctypedef void (*TRACE)(AMFTrace* pThis, const wchar_t* src_path, amf_int32 line, amf_int32 level, const wchar_t* scope, const wchar_t* message, va_list* pArglist)
    ctypedef amf_int32 (*SETGLOBALLEVEL)(AMFTrace* pThis, amf_int32 level)
    ctypedef amf_int32 (*GETGLOBALLEVEL)(AMFTrace* pThis)
    ctypedef const wchar_t* (*GETRESULTTEXT)(AMFTrace* pThis, AMF_RESULT res)
    ctypedef void (*REGISTERWRITER)(AMFTrace* pThis, const wchar_t* writerID, AMFTraceWriter* pWriter, amf_bool enable)
    ctypedef void (*UNREGISTERWRITER)(AMFTrace* pThis, const wchar_t* writerID)

    ctypedef struct AMFTraceVtbl:
        TRACEW TraceW
        TRACE Trace
        SETGLOBALLEVEL SetGlobalLevel
        GETGLOBALLEVEL GetGlobalLevel
        GETRESULTTEXT GetResultText
        REGISTERWRITER RegisterWriter
        UNREGISTERWRITER UnregisterWriter

    ctypedef struct AMFTrace:
        const AMFTraceVtbl *pVtbl


cdef extern from "core/Surface.h":
    ctypedef enum AMF_FRAME_TYPE:
        AMF_FRAME_STEREO_FLAG
        AMF_FRAME_LEFT_FLAG
        AMF_FRAME_RIGHT_FLAG
        AMF_FRAME_BOTH_FLAG
        AMF_FRAME_INTERLEAVED_FLAG
        AMF_FRAME_FIELD_FLAG
        AMF_FRAME_EVEN_FLAG
        AMF_FRAME_ODD_FLAG

        # values
        AMF_FRAME_UNKNOWN
        AMF_FRAME_PROGRESSIVE

        AMF_FRAME_INTERLEAVED_EVEN_FIRST
        AMF_FRAME_INTERLEAVED_ODD_FIRST
        AMF_FRAME_FIELD_SINGLE_EVEN
        AMF_FRAME_FIELD_SINGLE_ODD

        AMF_FRAME_STEREO_LEFT
        AMF_FRAME_STEREO_RIGHT
        AMF_FRAME_STEREO_BOTH

        AMF_FRAME_INTERLEAVED_EVEN_FIRST_STEREO_LEFT
        AMF_FRAME_INTERLEAVED_EVEN_FIRST_STEREO_RIGHT
        AMF_FRAME_INTERLEAVED_EVEN_FIRST_STEREO_BOTH

        AMF_FRAME_INTERLEAVED_ODD_FIRST_STEREO_LEFT
        AMF_FRAME_INTERLEAVED_ODD_FIRST_STEREO_RIGHT
        AMF_FRAME_INTERLEAVED_ODD_FIRST_STEREO_BOTH

    ctypedef enum AMF_SURFACE_FORMAT:
        AMF_SURFACE_NV12    # 1  - planar 4:2:0 Y width x height + packed UV width/2 x height/2 - 8 bit per component
        AMF_SURFACE_YV12    # 2  - planar 4:2:0 Y width x height + V width/2 x height/2 + U width/2 x height/2 - 8 bit per component
        AMF_SURFACE_BGRA    # 3  - packed 4:4:4 - 8 bit per component
        AMF_SURFACE_ARGB    # 4  - packed 4:4:4 - 8 bit per component
        AMF_SURFACE_RGBA    # 5  - packed 4:4:4 - 8 bit per component
        AMF_SURFACE_GRAY8   # 6  - single component - 8 bit
        AMF_SURFACE_YUV420P # 7  - planar 4:2:0 Y width x height + U width/2 x height/2 + V width/2 x height/2 - 8 bit per component
        AMF_SURFACE_U8V8    # 8  - packed double component - 8 bit per component
        AMF_SURFACE_YUY2    # 9  - packed 4:2:2 Byte 0=8-bit Y'0; Byte 1=8-bit Cb; Byte 2=8-bit Y'1; Byte 3=8-bit Cr
        AMF_SURFACE_P010    # 10 - planar 4:2:0 Y width x height + packed UV width/2 x height/2 - 10 bit per component (16 allocated, upper 10 bits are used)
        AMF_SURFACE_RGBA_F16 # 11 - packed 4:4:4 - 16 bit per component float
        AMF_SURFACE_UYVY    # 12 - packed 4:2:2 the similar to YUY2 but Y and UV swapped: Byte 0=8-bit Cb; Byte 1=8-bit Y'0; Byte 2=8-bit Cr Byte 3=8-bit Y'1; (used the same DX/CL/Vulkan storage as YUY2)
        AMF_SURFACE_R10G10B10A2  # 13 - packed 4:4:4 to 4 bytes, 10 bit per RGB component, 2 bits per A
        AMF_SURFACE_Y210    # 14 - packed 4:2:2 - Word 0=10-bit Y'0; Word 1=10-bit Cb; Word 2=10-bit Y'1; Word 3=10-bit Cr
        AMF_SURFACE_AYUV    # 15 - packed 4:4:4 - 8 bit per component YUVA
        AMF_SURFACE_Y410    # 16 - packed 4:4:4 - 10 bit per YUV component, 2 bits per A, AVYU
        AMF_SURFACE_Y416    # 17 - packed 4:4:4 - 16 bit per component 4 bytes, AVYU
        AMF_SURFACE_GRAY32  # 18 - single component - 32 bit
        AMF_SURFACE_P012    # 19 - planar 4:2:0 Y width x height + packed UV width/2 x height/2 - 12 bit per component (16 allocated, upper 12 bits are used)
        AMF_SURFACE_P016

    ctypedef AMF_RESULT (*SURFACE_SETPROPERTY)(AMFSurface* pThis, const wchar_t* name, AMFVariantStruct value)
    ctypedef amf_long (*SURFACE_ACQUIRE)(AMFSurface* pThis)
    ctypedef amf_long (*SURFACE_RELEASE)(AMFSurface* pThis)
    ctypedef AMF_SURFACE_FORMAT (*SURFACE_GETFORMAT)(AMFSurface* pThis)
    ctypedef amf_size (*SURFACE_GETPLANESCOUNT)(AMFSurface* pThis)
    ctypedef AMFPlane* (*SURFACE_GETPLANEAT)(AMFSurface* pThis, amf_size index)
    ctypedef AMFPlane* (*SURFACE_GETPLANE)(AMFSurface* pThis, AMF_PLANE_TYPE type)
    ctypedef AMF_FRAME_TYPE (*SURFACE_GETFRAMETYPE)(AMFSurface* pThis)
    ctypedef AMF_RESULT (*SURFACE_CONVERT)(AMFSurface* pThis, AMF_MEMORY_TYPE type)
    ctypedef AMF_RESULT (*SURFACE_INTEROP)(AMFSurface* pThis, AMF_MEMORY_TYPE type)
    ctypedef AMF_RESULT (*SETCROP)(amf_int32 x,amf_int32 y, amf_int32 width, amf_int32 height)
    ctypedef AMF_RESULT (*COPYSURFACEREGION)(AMFSurface* pDest, amf_int32 dstX, amf_int32 dstY, amf_int32 srcX, amf_int32 srcY, amf_int32 width, amf_int32 height)

    ctypedef struct AMFSurfaceVtbl:
        SURFACE_SETPROPERTY SetProperty
        SURFACE_ACQUIRE Acquire
        SURFACE_RELEASE Release
        SURFACE_GETFORMAT GetFormat
        SURFACE_GETPLANESCOUNT GetPlanesCount
        SURFACE_GETPLANEAT GetPlaneAt
        SURFACE_GETPLANE GetPlane
        SURFACE_GETFRAMETYPE GetFrameType
        SURFACE_CONVERT Convert
        SURFACE_INTEROP Interop
        SETCROP SetCrop
        COPYSURFACEREGION CopySurfaceRegion

    ctypedef struct AMFSurface:
        const AMFSurfaceVtbl *pVtbl


cdef inline SURFACE_FORMAT_STR(AMF_SURFACE_FORMAT fmt):
    return {
        AMF_SURFACE_NV12: "NV12",
        AMF_SURFACE_YV12: "YV12",
        AMF_SURFACE_BGRA: "BGRA",
        AMF_SURFACE_ARGB: "ARGB",
        AMF_SURFACE_RGBA: "RGBA",
        AMF_SURFACE_GRAY8: "GRAY8",
        AMF_SURFACE_YUV420P: "YUV420P",
        AMF_SURFACE_U8V8: "U8V8",
        AMF_SURFACE_YUY2: "YUY2",
        AMF_SURFACE_P010: "P010",
        AMF_SURFACE_RGBA_F16: "RGBA_F16",
        AMF_SURFACE_UYVY: "UYVY",
        AMF_SURFACE_R10G10B10A2: "R10G10B10A2",
        AMF_SURFACE_Y210: "Y210",
        AMF_SURFACE_AYUV: "AYUV",
        AMF_SURFACE_Y410: "Y410",
        AMF_SURFACE_Y416: "Y416",
        AMF_SURFACE_GRAY32: "GRAY32",
        AMF_SURFACE_P012: "P012",
        AMF_SURFACE_P016: "P016",
    }.get(fmt, "unknown")


cdef inline DATA_TYPE_STR(AMF_DATA_TYPE dtype):
    return {
        AMF_DATA_BUFFER: "BUFFER",
        AMF_DATA_SURFACE: "SURFACE",
        AMF_DATA_AUDIO_BUFFER: "AUDIO_BUFFER",
        AMF_DATA_USER: "USER",
    }.get(dtype, "unknown")


cdef inline FRAME_TYPE_STR(AMF_FRAME_TYPE ftype):
    return {
        AMF_FRAME_STEREO_FLAG: "STEREO_FLAG",
        AMF_FRAME_LEFT_FLAG: "LEFT_FLAG",
        AMF_FRAME_RIGHT_FLAG: "RIGHT_FLAG",
        AMF_FRAME_BOTH_FLAG: "BOTH_FLAG",
        AMF_FRAME_INTERLEAVED_FLAG: "INTERLEAVED_FLAG",
        AMF_FRAME_FIELD_FLAG: "FIELD_FLAG",
        AMF_FRAME_EVEN_FLAG: "EVEN_FLAG",
        AMF_FRAME_ODD_FLAG: "ODD_FLAG",

        # values
        AMF_FRAME_UNKNOWN: "UNKNOWN",
        AMF_FRAME_PROGRESSIVE: "PROGRESSIVE",

        AMF_FRAME_INTERLEAVED_EVEN_FIRST: "INTERLEAVED_EVEN_FIRST",
        AMF_FRAME_INTERLEAVED_ODD_FIRST: "INTERLEAVED_ODD_FIRST",
        AMF_FRAME_FIELD_SINGLE_EVEN: "FIELD_SINGLE_EVEN",
        AMF_FRAME_FIELD_SINGLE_ODD: "FIELD_SINGLE_ODD",

        AMF_FRAME_STEREO_LEFT: "STEREO_LEFT",
        AMF_FRAME_STEREO_RIGHT: "STEREO_RIGHT",
        AMF_FRAME_STEREO_BOTH: "STEREO_BOTH",

        AMF_FRAME_INTERLEAVED_EVEN_FIRST_STEREO_LEFT: "INTERLEAVED_EVEN_FIRST_STEREO_LEFT",
        AMF_FRAME_INTERLEAVED_EVEN_FIRST_STEREO_RIGHT: "INTERLEAVED_EVEN_FIRST_STEREO_RIGHT",
        AMF_FRAME_INTERLEAVED_EVEN_FIRST_STEREO_BOTH: "INTERLEAVED_EVEN_FIRST_STEREO_BOTH",

        AMF_FRAME_INTERLEAVED_ODD_FIRST_STEREO_LEFT: "INTERLEAVED_ODD_FIRST_STEREO_LEFT",
        AMF_FRAME_INTERLEAVED_ODD_FIRST_STEREO_RIGHT: "INTERLEAVED_ODD_FIRST_STEREO_RIGHT",
        AMF_FRAME_INTERLEAVED_ODD_FIRST_STEREO_BOTH: "INTERLEAVED_ODD_FIRST_STEREO_BOTH",
    }.get(ftype, "unknown")


cdef inline ACCEL_TYPE_STR(AMF_ACCELERATION_TYPE dtype):
    return{
        AMF_ACCEL_NOT_SUPPORTED: "not supported",
        AMF_ACCEL_HARDWARE: "hardware",
        AMF_ACCEL_GPU: "gpu",
        AMF_ACCEL_SOFTWARE: "software",
    }.get(dtype, "unknown")


cdef extern from "core/Context.h":
    ctypedef enum AMF_DX_VERSION:
        AMF_DX9     # 90
        AMF_DX9_EX  # 91
        AMF_DX11_0  # 110
        AMF_DX11_1  # 111
        AMF_DX12    # 120

    ctypedef amf_long (*CONTEXT_ACQUIRE)(AMFContext* pThis)
    ctypedef amf_long (*CONTEXT_RELEASE)(AMFContext* pThis)
    ctypedef AMF_RESULT (*CONTEXT_QUERYINTERFACE)(AMFContext* pThis, const AMFGuid *interfaceID, void** ppInterface)

    ctypedef AMF_RESULT (*CONTEXT_TERMINATE)(AMFContext *context)
    ctypedef AMF_RESULT (*CONTEXT_INITDX11)(AMFContext *context, void* pDX11Device, AMF_DX_VERSION dxVersionRequired)
    ctypedef void* (*CONTEXT_GETDX11DEVICE)(AMFContext *context, AMF_DX_VERSION dxVersionRequired)
    ctypedef AMF_RESULT (*CONTEXT_LOCKDX11)(AMFContext *context)
    ctypedef AMF_RESULT (*CONTEXT_UNLOCKDX11)(AMFContext *context)

    ctypedef AMF_RESULT (*CONTEXT_INITOPENGL)(AMFContext *context, amf_handle hOpenGLContext, amf_handle hWindow, amf_handle hDC)
    ctypedef amf_handle (*CONTEXT_GETOPENGLCONTEXT)(AMFContext *context)
    ctypedef amf_handle (*CONTEXT_GETOPENGLDRAWABLE)(AMFContext *context)
    ctypedef AMF_RESULT (*CONTEXT_LOCKOPENGL)(AMFContext *context)
    ctypedef AMF_RESULT (*CONTEXT_UNLOCKOPENGL)(AMFContext *context)

    ctypedef AMF_RESULT (*CONTEXT_ALLOCSURFACE)(AMFContext *context, AMF_MEMORY_TYPE type, AMF_SURFACE_FORMAT format, amf_int32 width, amf_int32 height, AMFSurface** ppSurface)

    # AMF_RESULT          AMF_STD_CALL AllocBuffer(AMF_MEMORY_TYPE type, amf_size size, AMFBuffer** ppBuffer) = 0
    # AMF_RESULT          AMF_STD_CALL CreateBufferFromHostNative(void* pHostBuffer, amf_size size, AMFBuffer** ppBuffer, AMFBufferObserver* pObserver) = 0
    # AMF_RESULT          AMF_STD_CALL CreateSurfaceFromHostNative(AMF_SURFACE_FORMAT format, amf_int32 width, amf_int32 height, amf_int32 hPitch, amf_int32 vPitch, void* pData,
    #                                                 AMFSurface** ppSurface, AMFSurfaceObserver* pObserver) = 0
    # AMF_RESULT          AMF_STD_CALL CreateSurfaceFromDX11Native(void* pDX11Surface, AMFSurface** ppSurface, AMFSurfaceObserver* pObserver) = 0
    # AMF_RESULT          AMF_STD_CALL CreateSurfaceFromOpenGLNative(AMF_SURFACE_FORMAT format, amf_handle hGLTextureID, AMFSurface** ppSurface, AMFSurfaceObserver* pObserver) = 0
    # AMF_RESULT          AMF_STD_CALL CreateSurfaceFromGrallocNative(amf_handle hGrallocSurface, AMFSurface** ppSurface, AMFSurfaceObserver* pObserver) = 0

    ctypedef struct AMFContextVtbl:
        CONTEXT_ACQUIRE Acquire
        CONTEXT_RELEASE Release
        CONTEXT_QUERYINTERFACE QueryInterface

        CONTEXT_TERMINATE Terminate
        CONTEXT_INITDX11 InitDX11
        CONTEXT_GETDX11DEVICE GetDX11Device
        CONTEXT_LOCKDX11 LockDX11
        CONTEXT_UNLOCKDX11 UnlockDX11

        CONTEXT_INITOPENGL InitOpenGL
        CONTEXT_GETOPENGLCONTEXT GetOpenGLContext
        CONTEXT_GETOPENGLDRAWABLE GetOpenGLDrawable
        CONTEXT_LOCKOPENGL LockOpenGL
        CONTEXT_UNLOCKOPENGL UnlockOpenGL

        CONTEXT_ALLOCSURFACE AllocSurface

    ctypedef struct AMFContext:
        const AMFContextVtbl *pVtbl

    ctypedef AMF_RESULT (*CONTEXT1_INITVULKAN)(AMFContext1 *context, void* pVulkanDevice)
    ctypedef void* (*CONTEXT1_GETVULKANDEVICE)(AMFContext1 *context)
    ctypedef AMF_RESULT (*CONTEXT1_LOCKVULKAN)(AMFContext1 *context)
    ctypedef AMF_RESULT (*CONTEXT1_UNLOCKVULKAN)(AMFContext1 *context)

    ctypedef struct AMFContext1Vtbl:
        CONTEXT1_INITVULKAN InitVulkan
        CONTEXT1_GETVULKANDEVICE GetVulkanDevice
        CONTEXT1_LOCKVULKAN LockVulkan
        CONTEXT1_UNLOCKVULKAN UnlockVulkan

    ctypedef struct AMFContext1:
        const AMFContext1Vtbl *pVtbl


cdef extern from "components/ComponentCaps.h":
    ctypedef enum AMF_ACCELERATION_TYPE:
        AMF_ACCEL_NOT_SUPPORTED
        AMF_ACCEL_HARDWARE
        AMF_ACCEL_GPU
        AMF_ACCEL_SOFTWARE

    ctypedef void (*GETWIDTHRANGE)(AMFIOCaps* pThis, amf_int32* minWidth, amf_int32* maxWidth)
    ctypedef void (*GETHEIGHTRANGE)(AMFIOCaps* pThis, amf_int32* minHeight, amf_int32* maxHeight)
    # Get memory alignment in lines: Vertical aligmnent should be multiples of this number
    ctypedef amf_int32 (*GETVERTALIGN)(AMFIOCaps* pThis)
    # Enumerate supported surface pixel formats
    ctypedef amf_int32 (*GETNUMOFFORMATS)(AMFIOCaps* pThis)
    ctypedef AMF_RESULT (*GETFORMATAT)(AMFIOCaps* pThis, amf_int32 index, AMF_SURFACE_FORMAT* format, amf_bool* native)
    # Enumerate supported memory types
    ctypedef amf_int32 (*GETNUMOFMEMORYTYPES)(AMFIOCaps* pThis)
    ctypedef AMF_RESULT (*GETMEMORYTYPEAT)(AMFIOCaps* pThis, amf_int32 index, AMF_MEMORY_TYPE* memType, amf_bool* native)
    ctypedef amf_bool (*ISINTERLACEDSUPPORTED)(AMFIOCaps* pThis)

    ctypedef struct AMFIOCapsVtbl:
        GETWIDTHRANGE GetWidthRange
        GETHEIGHTRANGE GetHeightRange
        GETVERTALIGN GetVertAlign
        GETNUMOFFORMATS GetNumOfFormats
        GETFORMATAT GetFormatAt
        GETNUMOFMEMORYTYPES GetNumOfMemoryTypes
        GETMEMORYTYPEAT GetMemoryTypeAt
        ISINTERLACEDSUPPORTED IsInterlacedSupported

    ctypedef struct AMFIOCaps:
        const AMFIOCapsVtbl *pVtbl

    ctypedef AMF_RESULT (*CAPSSETPROPERTY)(AMFCaps* pThis, const wchar_t* name, AMFVariantStruct value)
    ctypedef AMF_RESULT (*CAPSGETPROPERTY)(AMFCaps* pThis, const wchar_t* name, AMFVariantStruct* pValue)
    ctypedef AMF_RESULT (*HASPROPERTY)(AMFCaps* pThis, const wchar_t* name)

    ctypedef AMF_ACCELERATION_TYPE (*GETACCELERATIONTYPE)(AMFCaps* pThis)
    ctypedef AMF_RESULT (*GETINPUTCAPS)(AMFCaps* pThis, AMFIOCaps** input)
    ctypedef AMF_RESULT (*GETOUTPUTCAPS)(AMFCaps* pThis, AMFIOCaps** output)

    ctypedef struct AMFCapsVtbl:
        CAPSSETPROPERTY SetProperty
        CAPSGETPROPERTY GetProperty
        HASPROPERTY HasProperty
        GETACCELERATIONTYPE GetAccelerationType
        GETINPUTCAPS GetInputCaps
        GETOUTPUTCAPS GetOutputCaps

    ctypedef struct AMFCaps:
        const AMFCapsVtbl *pVtbl


cdef extern from "components/Component.h":
    ctypedef amf_long (*COMPONENT_ACQUIRE)(AMFComponent* pThis)
    ctypedef amf_long (*COMPONENT_RELEASE)(AMFComponent* pThis)

    ctypedef AMF_RESULT (*COMPONENT_SETPROPERTY)(AMFComponent* pThis, const wchar_t *pName, AMFVariantStruct value)
    ctypedef AMF_RESULT (*COMPONENT_GETPROPERTY)(AMFComponent* pThis, const wchar_t *pName, AMFVariantStruct* pValue)
    ctypedef amf_bool (*COMPONENT_HASPROPERTY)(AMFComponent* pThis, const wchar_t *pName, AMFVariantStruct* pValue)
    ctypedef amf_size (*COMPONENT_GETPROPERTYCOUNT)(AMFComponent* pThis)

    ctypedef AMF_RESULT (*COMPONENT_INIT)(AMFComponent* pThis, AMF_SURFACE_FORMAT format,amf_int32 width,amf_int32 height)
    ctypedef AMF_RESULT (*COMPONENT_REINIT)(AMFComponent* pThis, amf_int32 width,amf_int32 height)
    ctypedef AMF_RESULT (*COMPONENT_TERMINATE)(AMFComponent* pThis)
    ctypedef AMF_RESULT (*COMPONENT_DRAIN)(AMFComponent* pThis)
    ctypedef AMF_RESULT (*COMPONENT_FLUSH)(AMFComponent* pThis)
    ctypedef AMF_RESULT (*COMPONENT_SUBMITINPUT)(AMFComponent* pThis, AMFData* pData)
    ctypedef AMF_RESULT (*COMPONENT_QUERYOUTPUT)(AMFComponent* pThis, AMFData** ppData)
    ctypedef AMFContext* (*COMPONENT_GETCONTEXT)(AMFComponent* pThis)
    ctypedef AMF_RESULT (*COMPONENT_SETOUTPUTDATAALLOCATORCB)(AMFComponent* pThis, AMFDataAllocatorCB* callback)
    ctypedef AMF_RESULT (*COMPONENT_GETCAPS)(AMFComponent* pThis, AMFCaps** ppCaps)
    ctypedef AMF_RESULT (*COMPONENT_OPTIMIZE)(AMFComponent* pThis, AMFComponentOptimizationCallback* pCallback)

    ctypedef struct AMFComponentVtbl:
        # AMFInterface interface
        COMPONENT_ACQUIRE Acquire
        COMPONENT_RELEASE Release

        # AMFPropertyStorage
        COMPONENT_SETPROPERTY SetProperty
        COMPONENT_GETPROPERTY GetProperty
        COMPONENT_HASPROPERTY HasProperty
        COMPONENT_GETPROPERTYCOUNT GetPropertyCount

        # AMFComponent interface
        COMPONENT_INIT Init
        COMPONENT_REINIT ReInit
        COMPONENT_TERMINATE Terminate
        COMPONENT_DRAIN Drain
        COMPONENT_FLUSH Flush
        COMPONENT_SUBMITINPUT SubmitInput
        COMPONENT_QUERYOUTPUT QueryOutput
        COMPONENT_GETCONTEXT GetContext
        COMPONENT_SETOUTPUTDATAALLOCATORCB SetOutputDataAllocatorCB
        COMPONENT_GETCAPS GetCaps
        COMPONENT_OPTIMIZE Optimize

    ctypedef struct AMFComponent:
        const AMFComponentVtbl *pVtbl


cdef extern from "core/Factory.h":
    ctypedef struct AMFDebug:
        pass
    ctypedef struct AMFPrograms:
        pass

    ctypedef AMF_RESULT (*AMFCREATECONTEXT)(AMFFactory *factory, AMFContext** context)
    ctypedef AMF_RESULT (*AMFCREATECOMPONENT)(AMFFactory *factory,AMFContext* context, const wchar_t* id, AMFComponent** ppComponent)
    ctypedef AMF_RESULT (*AMFSETCACHEFOLDER)(AMFFactory *factory,const wchar_t *path)
    ctypedef const wchar_t (*AMFGETCACHEFOLDER)(AMFFactory *factory)
    ctypedef AMF_RESULT (*AMFGETDEBUG)(AMFFactory *factory, AMFDebug **debug)
    ctypedef AMF_RESULT (*AMFGETTRACE)(AMFFactory *factory, AMFTrace **trace)
    ctypedef AMF_RESULT (*AMFGETPROGRAMS)(AMFFactory *factory, AMFPrograms **programs)

    ctypedef struct AMFFactoryVtbl:
        AMFCREATECONTEXT CreateContext
        AMFCREATECOMPONENT CreateComponent
        AMFSETCACHEFOLDER SetCacheFolder
        AMFGETCACHEFOLDER GetCacheFolder
        AMFGETDEBUG GetDebug
        AMFGETTRACE GetTrace
        AMFGETPROGRAMS GetPrograms

    ctypedef struct AMFFactory:
        const AMFFactoryVtbl *pVtbl


cdef extern from "components/VideoEncoderVCE.h":
    enum AMF_VIDEO_ENCODER_USAGE_ENUM:
        AMF_VIDEO_ENCODER_USAGE_TRANSCODING
        AMF_VIDEO_ENCODER_USAGE_ULTRA_LOW_LATENCY
        AMF_VIDEO_ENCODER_USAGE_LOW_LATENCY
        AMF_VIDEO_ENCODER_USAGE_WEBCAM
        AMF_VIDEO_ENCODER_USAGE_HIGH_QUALITY
        AMF_VIDEO_ENCODER_USAGE_LOW_LATENCY_HIGH_QUALITY

    enum AMF_VIDEO_ENCODER_QUALITY_PRESET_ENUM:
        AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED
        AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED
        AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY

    enum AMF_VIDEO_ENCODER_PROFILE_ENUM:
        AMF_VIDEO_ENCODER_PROFILE_BASELINE
        AMF_VIDEO_ENCODER_PROFILE_MAIN
        AMF_VIDEO_ENCODER_PROFILE_HIGH
        AMF_VIDEO_ENCODER_PROFILE_CONSTRAINED_BASELINE
        AMF_VIDEO_ENCODER_PROFILE_CONSTRAINED_HIGH

    enum AMF_VIDEO_ENCODER_H264_LEVEL_ENUM:
        AMF_H264_LEVEL__1
        AMF_H264_LEVEL__1_1
        AMF_H264_LEVEL__1_2
        AMF_H264_LEVEL__1_3
        AMF_H264_LEVEL__2
        AMF_H264_LEVEL__2_1
        AMF_H264_LEVEL__2_2
        AMF_H264_LEVEL__3
        AMF_H264_LEVEL__3_1
        AMF_H264_LEVEL__3_2
        AMF_H264_LEVEL__4
        AMF_H264_LEVEL__4_1
        AMF_H264_LEVEL__4_2
        AMF_H264_LEVEL__5
        AMF_H264_LEVEL__5_1
        AMF_H264_LEVEL__5_2
        AMF_H264_LEVEL__6
        AMF_H264_LEVEL__6_1
        AMF_H264_LEVEL__6_2

    enum AMF_VIDEO_ENCODER_PICTURE_STRUCTURE_ENUM:
        AMF_VIDEO_ENCODER_PICTURE_STRUCTURE_NONE
        AMF_VIDEO_ENCODER_PICTURE_STRUCTURE_FRAME
        AMF_VIDEO_ENCODER_PICTURE_STRUCTURE_TOP_FIELD
        AMF_VIDEO_ENCODER_PICTURE_STRUCTURE_BOTTOM_FIELD

    enum AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_ENUM:
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_IDR
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_I
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_P
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_B

    enum AMF_VIDEO_ENCODER_OUTPUT_BUFFER_TYPE_ENUM:
        AMF_VIDEO_ENCODER_OUTPUT_BUFFER_TYPE_FRAME
        AMF_VIDEO_ENCODER_OUTPUT_BUFFER_TYPE_TILE
        AMF_VIDEO_ENCODER_OUTPUT_BUFFER_TYPE_TILE_LAST

    enum AMF_VIDEO_ENCODER_FORCE_PICTURE_TYPE:
        AMF_VIDEO_ENCODER_PICTURE_TYPE_NONE
        AMF_VIDEO_ENCODER_PICTURE_TYPE_SKIP
        AMF_VIDEO_ENCODER_PICTURE_TYPE_IDR
        AMF_VIDEO_ENCODER_PICTURE_TYPE_I
        AMF_VIDEO_ENCODER_PICTURE_TYPE_P
        AMF_VIDEO_ENCODER_PICTURE_TYPE_B


cdef inline AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_STR(AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_ENUM dtype):
    return {
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_IDR: "IDR",
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_I: "I",
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_P: "P",
        AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_B: "B",
    }.get(dtype, "unknown")


cdef extern from "components/VideoEncoderHEVC.h":
    enum AMF_VIDEO_ENCODER_HEVC_USAGE_ENUM:
        AMF_VIDEO_ENCODER_HEVC_USAGE_TRANSCODING
        AMF_VIDEO_ENCODER_HEVC_USAGE_ULTRA_LOW_LATENCY
        AMF_VIDEO_ENCODER_HEVC_USAGE_LOW_LATENCY
        AMF_VIDEO_ENCODER_HEVC_USAGE_WEBCAM
        AMF_VIDEO_ENCODER_HEVC_USAGE_HIGH_QUALITY
        AMF_VIDEO_ENCODER_HEVC_USAGE_LOW_LATENCY_HIGH_QUALITY

    enum AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_ENUM:
        AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_QUALITY
        AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_BALANCED
        AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED

    enum AMF_VIDEO_ENCODER_HEVC_PROFILE_ENUM:
        AMF_VIDEO_ENCODER_HEVC_PROFILE_MAIN
        AMF_VIDEO_ENCODER_HEVC_PROFILE_MAIN_10

    enum AMF_VIDEO_ENCODER_HEVC_TIER_ENUM:
        AMF_VIDEO_ENCODER_HEVC_TIER_MAIN
        AMF_VIDEO_ENCODER_HEVC_TIER_HIGH

    enum AMF_VIDEO_ENCODER_LEVEL_ENUM:
        AMF_LEVEL_1
        AMF_LEVEL_2
        AMF_LEVEL_2_1
        AMF_LEVEL_3
        AMF_LEVEL_3_1
        AMF_LEVEL_4
        AMF_LEVEL_4_1
        AMF_LEVEL_5
        AMF_LEVEL_5_1
        AMF_LEVEL_5_2
        AMF_LEVEL_6
        AMF_LEVEL_6_1
        AMF_LEVEL_6_2


cdef extern from "components/VideoEncoderAV1.h":
    enum AMF_VIDEO_ENCODER_AV1_ENCODING_LATENCY_MODE_ENUM:
        AMF_VIDEO_ENCODER_AV1_ENCODING_LATENCY_MODE_NONE
        AMF_VIDEO_ENCODER_AV1_ENCODING_LATENCY_MODE_POWER_SAVING_REAL_TIME
        AMF_VIDEO_ENCODER_AV1_ENCODING_LATENCY_MODE_REAL_TIME
        AMF_VIDEO_ENCODER_AV1_ENCODING_LATENCY_MODE_LOWEST_LATENCY

    enum AMF_VIDEO_ENCODER_AV1_USAGE_ENUM:
        AMF_VIDEO_ENCODER_AV1_USAGE_TRANSCODING
        AMF_VIDEO_ENCODER_AV1_USAGE_ULTRA_LOW_LATENCY
        AMF_VIDEO_ENCODER_AV1_USAGE_LOW_LATENCY
        AMF_VIDEO_ENCODER_AV1_USAGE_WEBCAM
        AMF_VIDEO_ENCODER_AV1_USAGE_HIGH_QUALITY
        AMF_VIDEO_ENCODER_AV1_USAGE_LOW_LATENCY_HIGH_QUALITY

    enum AMF_VIDEO_ENCODER_AV1_PROFILE_ENUM:
        AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN

    enum AMF_VIDEO_ENCODER_AV1_LEVEL_ENUM:
        AMF_VIDEO_ENCODER_AV1_LEVEL_2_0
        AMF_VIDEO_ENCODER_AV1_LEVEL_2_1
        AMF_VIDEO_ENCODER_AV1_LEVEL_2_2
        AMF_VIDEO_ENCODER_AV1_LEVEL_2_3
        AMF_VIDEO_ENCODER_AV1_LEVEL_3_0
        AMF_VIDEO_ENCODER_AV1_LEVEL_3_1
        AMF_VIDEO_ENCODER_AV1_LEVEL_3_2
        AMF_VIDEO_ENCODER_AV1_LEVEL_3_3
        AMF_VIDEO_ENCODER_AV1_LEVEL_4_0
        AMF_VIDEO_ENCODER_AV1_LEVEL_4_1
        AMF_VIDEO_ENCODER_AV1_LEVEL_4_2
        AMF_VIDEO_ENCODER_AV1_LEVEL_4_3
        AMF_VIDEO_ENCODER_AV1_LEVEL_5_0
        AMF_VIDEO_ENCODER_AV1_LEVEL_5_1
        AMF_VIDEO_ENCODER_AV1_LEVEL_5_2
        AMF_VIDEO_ENCODER_AV1_LEVEL_5_3
        AMF_VIDEO_ENCODER_AV1_LEVEL_6_0
        AMF_VIDEO_ENCODER_AV1_LEVEL_6_1
        AMF_VIDEO_ENCODER_AV1_LEVEL_6_2
        AMF_VIDEO_ENCODER_AV1_LEVEL_6_3
        AMF_VIDEO_ENCODER_AV1_LEVEL_7_0
        AMF_VIDEO_ENCODER_AV1_LEVEL_7_1
        AMF_VIDEO_ENCODER_AV1_LEVEL_7_2
        AMF_VIDEO_ENCODER_AV1_LEVEL_7_3

    enum AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_ENUM:
        AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY
        AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY
        AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED
        AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED

    enum AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_ENUM:
        AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_64X16_ONLY
        AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_64X16_1080P_CODED_1082
        AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_NO_RESTRICTIONS
