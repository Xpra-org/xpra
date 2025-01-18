# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stddef cimport wchar_t

ctypedef int AMF_RESULT
ctypedef unsigned long amf_handle
ctypedef long amf_long
ctypedef int amf_int32
ctypedef void* AMFDataAllocatorCB
ctypedef void* AMFComponentOptimizationCallback


cdef extern from "core/Variant.h":
    ctypedef struct AMFVariantStruct:
        pass


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

    ctypedef struct AMFDataVtbl:
        pass

    ctypedef struct AMFData:
        const AMFDataVtbl *pVtbl


cdef extern from "core/Surface.h":
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

    ctypedef struct AMFSurfaceVtbl:
        SURFACE_SETPROPERTY SetProperty
        SURFACE_ACQUIRE Acquire
        SURFACE_RELEASE Release

    ctypedef struct AMFSurface:
        const AMFSurfaceVtbl *pVtbl


cdef extern from "core/Context.h":
    ctypedef enum AMF_DX_VERSION:
        AMF_DX9     # 90
        AMF_DX9_EX  # 91
        AMF_DX11_0  # 110
        AMF_DX11_1  # 111
        AMF_DX12    # 120

    ctypedef amf_long (*CONTEXT_ACQUIRE)(AMFContext* pThis)
    ctypedef amf_long (*CONTEXT_RELEASE)(AMFContext* pThis)

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


cdef extern from "components/ComponentCaps.h":
    ctypedef struct AMFCapsVtbl:
        pass

    ctypedef struct AMFCaps:
        const AMFCapsVtbl *pVtbl


cdef extern from "components/Component.h":

    ctypedef amf_long (*COMPONENT_ACQUIRE)(AMFComponent* pThis)
    ctypedef amf_long (*COMPONENT_RELEASE)(AMFComponent* pThis)
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
    ctypedef struct AMFTrace:
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

# cdef extern from "components/VideoEncoderVCE.h":
#    # int AMFVideoEncoderHW_AVC
#    int AMFVideoEncoderVCE_AVC
#    int AMFVideoEncoderVCE_SVC

cdef extern from "components/VideoEncoderHEVC.h":
    int AMFVideoEncoder_HEVC

cdef extern from "components/VideoEncoderAV1.h":
    int AMFVideoEncoder_AV1


AMF_ENCODINGS : Dict[str, str] = {
    "hevc": "AMFVideoEncoder_HEVC",
    "av1": "AMFVideoEncoder_AV1",
}
