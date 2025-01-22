# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger

from libc.stddef cimport wchar_t, size_t
from libc.stdint cimport uintptr_t, uint8_t, uint16_t, uint32_t

log = Logger("win32", "d3d11")

ctypedef unsigned int UINT
ctypedef unsigned int HRESULT
ctypedef unsigned long ULONG
ctypedef long LONG
ctypedef unsigned int DWORD


VENDORS: Dict[int, str] = {
    0x1002: "AMD",
    0x1022: "AMD",
    0x1010: "ImgTec",
    0x10DE: "NVIDIA",
    0x13B5: "ARM",
    0x5143: "Qualcomm",
    0x163C: "Intel",
    0x8086: "Intel",
    0x8087: "Intel",
}


ctypedef struct LUID:
    DWORD LowPart
    LONG HighPart


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    object PyUnicode_FromWideChar(wchar_t *w, Py_ssize_t size)


cdef extern from "string.h":
    size_t wcslen(const wchar_t *str)


cdef extern from "guiddef.h":
    ctypedef struct GUID:
        unsigned long  Data1
        unsigned short Data2
        unsigned short Data3
        unsigned char  Data4[8]

    ctypedef GUID REFIID


cdef extern from "winerror.h":
    int DXGI_STATUS_OCCLUDED
    int DXGI_STATUS_CLIPPED
    int DXGI_STATUS_NO_REDIRECTION
    int DXGI_STATUS_NO_DESKTOP_ACCESS
    int DXGI_STATUS_GRAPHICS_VIDPN_SOURCE_IN_USE
    int DXGI_STATUS_MODE_CHANGED
    int DXGI_STATUS_MODE_CHANGE_IN_PROGRESS
    int DXGI_ERROR_INVALID_CALL
    int DXGI_ERROR_NOT_FOUND
    int DXGI_ERROR_MORE_DATA
    int DXGI_ERROR_UNSUPPORTED
    int DXGI_ERROR_DEVICE_REMOVED
    int DXGI_ERROR_DEVICE_HUNG
    int DXGI_ERROR_DEVICE_RESET
    int DXGI_ERROR_WAS_STILL_DRAWING
    int DXGI_ERROR_FRAME_STATISTICS_DISJOINT
    int DXGI_ERROR_GRAPHICS_VIDPN_SOURCE_IN_USE
    int DXGI_ERROR_DRIVER_INTERNAL_ERROR
    int DXGI_ERROR_NONEXCLUSIVE
    int DXGI_ERROR_NOT_CURRENTLY_AVAILABLE
    int DXGI_ERROR_REMOTE_CLIENT_DISCONNECTED
    int DXGI_ERROR_REMOTE_OUTOFMEMORY
    int D3D11_ERROR_TOO_MANY_UNIQUE_STATE_OBJECTS
    int D3D11_ERROR_FILE_NOT_FOUND
    int D3D11_ERROR_TOO_MANY_UNIQUE_VIEW_OBJECTS
    int D3D11_ERROR_DEFERRED_CONTEXT_MAP_WITHOUT_INITIAL_DISCARD
    int D3D10_ERROR_TOO_MANY_UNIQUE_STATE_OBJECTS
    int D3D10_ERROR_FILE_NOT_FOUND
    int E_NOINTERFACE
    int E_POINTER


ERRORS = {
    DXGI_STATUS_OCCLUDED: "STATUS_OCCLUDED",
    DXGI_STATUS_CLIPPED: "STATUS_CLIPPED",
    DXGI_STATUS_NO_REDIRECTION: "STATUS_NO_REDIRECTION",
    DXGI_STATUS_NO_DESKTOP_ACCESS: "STATUS_NO_DESKTOP_ACCESS",
    DXGI_STATUS_GRAPHICS_VIDPN_SOURCE_IN_USE: "STATUS_GRAPHICS_VIDPN_SOURCE_IN_USE",
    DXGI_STATUS_MODE_CHANGED: "STATUS_MODE_CHANGED",
    DXGI_STATUS_MODE_CHANGE_IN_PROGRESS: "STATUS_MODE_CHANGE_IN_PROGRESS",
    DXGI_ERROR_INVALID_CALL: "INVALID_CALL",
    DXGI_ERROR_NOT_FOUND: "NOT_FOUND",
    DXGI_ERROR_MORE_DATA: "MORE_DATA",
    DXGI_ERROR_UNSUPPORTED: "UNSUPPORTED",
    DXGI_ERROR_DEVICE_REMOVED: "DEVICE_REMOVED",
    DXGI_ERROR_DEVICE_HUNG: "DEVICE_HUNG",
    DXGI_ERROR_DEVICE_RESET: "DEVICE_RESET",
    DXGI_ERROR_WAS_STILL_DRAWING: "WAS_STILL_DRAWING",
    DXGI_ERROR_FRAME_STATISTICS_DISJOINT: "FRAME_STATISTICS_DISJOINT",
    DXGI_ERROR_GRAPHICS_VIDPN_SOURCE_IN_USE: "GRAPHICS_VIDPN_SOURCE_IN_USE",
    DXGI_ERROR_DRIVER_INTERNAL_ERROR: "DRIVER_INTERNAL_ERROR",
    DXGI_ERROR_NONEXCLUSIVE: "NONEXCLUSIVE",
    DXGI_ERROR_NOT_CURRENTLY_AVAILABLE: "NOT_CURRENTLY_AVAILABLE",
    DXGI_ERROR_REMOTE_CLIENT_DISCONNECTED: "REMOTE_CLIENT_DISCONNECTED",
    DXGI_ERROR_REMOTE_OUTOFMEMORY: "REMOTE_OUTOFMEMORY",
    D3D11_ERROR_TOO_MANY_UNIQUE_STATE_OBJECTS: "TOO_MANY_UNIQUE_STATE_OBJECTS",
    D3D11_ERROR_FILE_NOT_FOUND: "FILE_NOT_FOUND",
    D3D11_ERROR_TOO_MANY_UNIQUE_VIEW_OBJECTS: "TOO_MANY_UNIQUE_VIEW_OBJECTS",
    D3D11_ERROR_DEFERRED_CONTEXT_MAP_WITHOUT_INITIAL_DISCARD: "DEFERRED_CONTEXT_MAP_WITHOUT_INITIAL_DISCARD",
    D3D10_ERROR_TOO_MANY_UNIQUE_STATE_OBJECTS: "TOO_MANY_UNIQUE_STATE_OBJECTS",
    D3D10_ERROR_FILE_NOT_FOUND: "FILE_NOT_FOUND",
    E_NOINTERFACE: "NOINTERFACE",
    E_POINTER: "POINTER",
}


cdef extern from "dxgi.h":
    ctypedef struct DXGI_ADAPTER_DESC:
        wchar_t  Description[128]
        UINT   VendorId
        UINT   DeviceId
        UINT   SubSysId
        UINT   Revision
        size_t DedicatedVideoMemory
        size_t DedicatedSystemMemory
        size_t SharedSystemMemory
        LUID   AdapterLuid

    # DEFINE_GUID(IID_IDXGIAdapter, 0x2411e7e1, 0x12ac, 0x4ccf, 0xbd, 0x14, 0x97, 0x9b, 0xe2, 0x52, 0x12, 0x20)
    ctypedef HRESULT (*ADAPTER_GETDESC)(IDXGIAdapter *this, DXGI_ADAPTER_DESC *desc)

    ctypedef struct IDXGIAdapterVtbl:
        ADAPTER_GETDESC GetDesc

    ctypedef struct IDXGIAdapter:
        const IDXGIAdapterVtbl *lpVtbl

    # DEFINE_GUID(IID_IDXGIDevice, 0x54ec77fa, 0x1377, 0x44e6, 0x8c, 0x32, 0x88, 0xfd, 0x5f, 0x44, 0xc8, 0x4c)
    ctypedef HRESULT (*DEVICE_GETADAPTER)(IDXGIDevice *this, IDXGIAdapter** adapter)
    ctypedef struct IDXGIDeviceVtbl:
        DEVICE_GETADAPTER GetAdapter

    ctypedef struct IDXGIDevice:
        const IDXGIDeviceVtbl *lpVtbl


cdef extern from "d3d11.h":
    ctypedef enum DXGI_FORMAT:
        DXGI_FORMAT_UNKNOWN
        DXGI_FORMAT_R32G32B32A32_TYPELESS
        DXGI_FORMAT_R32G32B32A32_FLOAT
        DXGI_FORMAT_R32G32B32A32_UINT
        DXGI_FORMAT_R32G32B32A32_SINT
        DXGI_FORMAT_R32G32B32_TYPELESS
        DXGI_FORMAT_R32G32B32_FLOAT
        DXGI_FORMAT_R32G32B32_UINT
        DXGI_FORMAT_R32G32B32_SINT
        DXGI_FORMAT_R16G16B16A16_TYPELESS
        DXGI_FORMAT_R16G16B16A16_FLOAT
        DXGI_FORMAT_R16G16B16A16_UNORM
        DXGI_FORMAT_R16G16B16A16_UINT
        DXGI_FORMAT_R16G16B16A16_SNORM
        DXGI_FORMAT_R16G16B16A16_SINT
        DXGI_FORMAT_R32G32_TYPELESS
        DXGI_FORMAT_R32G32_FLOAT
        DXGI_FORMAT_R32G32_UINT
        DXGI_FORMAT_R32G32_SINT
        DXGI_FORMAT_R32G8X24_TYPELESS
        DXGI_FORMAT_D32_FLOAT_S8X24_UINT
        DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS
        DXGI_FORMAT_X32_TYPELESS_G8X24_UINT
        DXGI_FORMAT_R10G10B10A2_TYPELESS
        DXGI_FORMAT_R10G10B10A2_UNORM
        DXGI_FORMAT_R10G10B10A2_UINT
        DXGI_FORMAT_R11G11B10_FLOAT
        DXGI_FORMAT_R8G8B8A8_TYPELESS
        DXGI_FORMAT_R8G8B8A8_UNORM
        DXGI_FORMAT_R8G8B8A8_UNORM_SRGB
        DXGI_FORMAT_R8G8B8A8_UINT
        DXGI_FORMAT_R8G8B8A8_SNORM
        DXGI_FORMAT_R8G8B8A8_SINT
        DXGI_FORMAT_R16G16_TYPELESS
        DXGI_FORMAT_R16G16_FLOAT
        DXGI_FORMAT_R16G16_UNORM
        DXGI_FORMAT_R16G16_UINT
        DXGI_FORMAT_R16G16_SNORM
        DXGI_FORMAT_R16G16_SINT
        DXGI_FORMAT_R32_TYPELESS
        DXGI_FORMAT_D32_FLOAT
        DXGI_FORMAT_R32_FLOAT
        DXGI_FORMAT_R32_UINT
        DXGI_FORMAT_R32_SINT
        DXGI_FORMAT_R24G8_TYPELESS
        DXGI_FORMAT_D24_UNORM_S8_UINT
        DXGI_FORMAT_R24_UNORM_X8_TYPELESS
        DXGI_FORMAT_X24_TYPELESS_G8_UINT
        DXGI_FORMAT_R8G8_TYPELESS
        DXGI_FORMAT_R8G8_UNORM
        DXGI_FORMAT_R8G8_UINT
        DXGI_FORMAT_R8G8_SNORM
        DXGI_FORMAT_R8G8_SINT
        DXGI_FORMAT_R16_TYPELESS
        DXGI_FORMAT_R16_FLOAT
        DXGI_FORMAT_D16_UNORM
        DXGI_FORMAT_R16_UNORM
        DXGI_FORMAT_R16_UINT
        DXGI_FORMAT_R16_SNORM
        DXGI_FORMAT_R16_SINT
        DXGI_FORMAT_R8_TYPELESS
        DXGI_FORMAT_R8_UNORM
        DXGI_FORMAT_R8_UINT
        DXGI_FORMAT_R8_SNORM
        DXGI_FORMAT_R8_SINT
        DXGI_FORMAT_A8_UNORM
        DXGI_FORMAT_R1_UNORM
        DXGI_FORMAT_R9G9B9E5_SHAREDEXP
        DXGI_FORMAT_R8G8_B8G8_UNORM
        DXGI_FORMAT_G8R8_G8B8_UNORM
        DXGI_FORMAT_BC1_TYPELESS
        DXGI_FORMAT_BC1_UNORM
        DXGI_FORMAT_BC1_UNORM_SRGB
        DXGI_FORMAT_BC2_TYPELESS
        DXGI_FORMAT_BC2_UNORM
        DXGI_FORMAT_BC2_UNORM_SRGB
        DXGI_FORMAT_BC3_TYPELESS
        DXGI_FORMAT_BC3_UNORM
        DXGI_FORMAT_BC3_UNORM_SRGB
        DXGI_FORMAT_BC4_TYPELESS
        DXGI_FORMAT_BC4_UNORM
        DXGI_FORMAT_BC4_SNORM
        DXGI_FORMAT_BC5_TYPELESS
        DXGI_FORMAT_BC5_UNORM
        DXGI_FORMAT_BC5_SNORM
        DXGI_FORMAT_B5G6R5_UNORM
        DXGI_FORMAT_B5G5R5A1_UNORM
        DXGI_FORMAT_B8G8R8A8_UNORM
        DXGI_FORMAT_B8G8R8X8_UNORM
        DXGI_FORMAT_R10G10B10_XR_BIAS_A2_UNORM
        DXGI_FORMAT_B8G8R8A8_TYPELESS
        DXGI_FORMAT_B8G8R8A8_UNORM_SRGB
        DXGI_FORMAT_B8G8R8X8_TYPELESS
        DXGI_FORMAT_B8G8R8X8_UNORM_SRGB
        DXGI_FORMAT_BC6H_TYPELESS
        DXGI_FORMAT_BC6H_UF16
        DXGI_FORMAT_BC6H_SF16
        DXGI_FORMAT_BC7_TYPELESS
        DXGI_FORMAT_BC7_UNORM
        DXGI_FORMAT_BC7_UNORM_SRGB
        DXGI_FORMAT_AYUV
        DXGI_FORMAT_Y410
        DXGI_FORMAT_Y416
        DXGI_FORMAT_NV12
        DXGI_FORMAT_P010
        DXGI_FORMAT_P016
        DXGI_FORMAT_420_OPAQUE
        DXGI_FORMAT_YUY2
        DXGI_FORMAT_Y210
        DXGI_FORMAT_Y216
        DXGI_FORMAT_NV11
        DXGI_FORMAT_AI44
        DXGI_FORMAT_IA44
        DXGI_FORMAT_P8
        DXGI_FORMAT_A8P8
        DXGI_FORMAT_B4G4R4A4_UNORM
        DXGI_FORMAT_P208
        DXGI_FORMAT_V208
        DXGI_FORMAT_V408
        DXGI_FORMAT_SAMPLER_FEEDBACK_MIN_MIP_OPAQUE
        DXGI_FORMAT_SAMPLER_FEEDBACK_MIP_REGION_USED_OPAQUE
        DXGI_FORMAT_FORCE_UINT = 0xffffffff

    ctypedef struct DXGI_SAMPLE_DESC:
        UINT Count
        UINT Quality

    ctypedef enum D3D11_USAGE:
      D3D11_USAGE_DEFAULT
      D3D11_USAGE_IMMUTABLE
      D3D11_USAGE_DYNAMIC
      D3D11_USAGE_STAGING

    ctypedef enum D3D11_CPU_ACCESS_FLAG:
        D3D11_CPU_ACCESS_WRITE
        D3D11_CPU_ACCESS_READ

    ctypedef enum D3D11_DEVICE_CONTEXT_TYPE:
        D3D11_DEVICE_CONTEXT_IMMEDIATE
        D3D11_DEVICE_CONTEXT_DEFERRED

    ctypedef enum D3D_FEATURE_LEVEL:
        # D3D_FEATURE_LEVEL_1_0_GENERIC
        # D3D_FEATURE_LEVEL_1_0_CORE
        D3D_FEATURE_LEVEL_9_1
        D3D_FEATURE_LEVEL_9_2
        D3D_FEATURE_LEVEL_9_3
        D3D_FEATURE_LEVEL_10_0
        D3D_FEATURE_LEVEL_10_1
        D3D_FEATURE_LEVEL_11_0
        D3D_FEATURE_LEVEL_11_1
        D3D_FEATURE_LEVEL_12_0
        D3D_FEATURE_LEVEL_12_1
        D3D_FEATURE_LEVEL_12_2

    ctypedef enum D3D11_FEATURE:
        D3D11_FEATURE_THREADING
        D3D11_FEATURE_DOUBLES
        D3D11_FEATURE_FORMAT_SUPPORT
        D3D11_FEATURE_FORMAT_SUPPORT2
        D3D11_FEATURE_D3D10_X_HARDWARE_OPTIONS
        D3D11_FEATURE_D3D11_OPTIONS
        D3D11_FEATURE_ARCHITECTURE_INFO
        D3D11_FEATURE_D3D9_OPTIONS
        D3D11_FEATURE_SHADER_MIN_PRECISION_SUPPORT
        D3D11_FEATURE_D3D9_SHADOW_SUPPORT
        D3D11_FEATURE_D3D11_OPTIONS1
        D3D11_FEATURE_D3D9_SIMPLE_INSTANCING_SUPPORT
        D3D11_FEATURE_MARKER_SUPPORT
        D3D11_FEATURE_D3D9_OPTIONS1
        D3D11_FEATURE_D3D11_OPTIONS2
        D3D11_FEATURE_D3D11_OPTIONS3
        D3D11_FEATURE_GPU_VIRTUAL_ADDRESS_SUPPORT
        D3D11_FEATURE_D3D11_OPTIONS4
        D3D11_FEATURE_SHADER_CACHE
        D3D11_FEATURE_D3D11_OPTIONS5
        # D3D11_FEATURE_DISPLAYABLE
        # D3D11_FEATURE_D3D11_OPTIONS6

    ctypedef enum D3D11_CREATE_DEVICE_FLAG:
        D3D11_CREATE_DEVICE_SINGLETHREADED
        D3D11_CREATE_DEVICE_DEBUG
        D3D11_CREATE_DEVICE_SWITCH_TO_REF
        D3D11_CREATE_DEVICE_PREVENT_INTERNAL_THREADING_OPTIMIZATIONS
        D3D11_CREATE_DEVICE_BGRA_SUPPORT
        D3D11_CREATE_DEVICE_DEBUGGABLE
        D3D11_CREATE_DEVICE_PREVENT_ALTERING_LAYER_SETTINGS_FROM_REGISTRY
        D3D11_CREATE_DEVICE_DISABLE_GPU_TIMEOUT
        D3D11_CREATE_DEVICE_VIDEO_SUPPORT

    ctypedef enum D3D11_VIDEO_PROCESSOR_DEVICE_CAPS:
        D3D11_VIDEO_PROCESSOR_DEVICE_CAPS_LINEAR_SPACE
        D3D11_VIDEO_PROCESSOR_DEVICE_CAPS_xvYCC
        D3D11_VIDEO_PROCESSOR_DEVICE_CAPS_RGB_RANGE_CONVERSION
        D3D11_VIDEO_PROCESSOR_DEVICE_CAPS_YCbCr_MATRIX_CONVERSION
        D3D11_VIDEO_PROCESSOR_DEVICE_CAPS_NOMINAL_RANGE

    ctypedef enum D3D11_BUS_TYPE:
        D3D11_BUS_TYPE_OTHER
        D3D11_BUS_TYPE_PCI
        D3D11_BUS_TYPE_PCIX
        D3D11_BUS_TYPE_PCIEXPRESS
        D3D11_BUS_TYPE_AGP
        D3D11_BUS_IMPL_MODIFIER_INSIDE_OF_CHIPSET
        D3D11_BUS_IMPL_MODIFIER_TRACKS_ON_MOTHER_BOARD_TO_CHIP
        D3D11_BUS_IMPL_MODIFIER_TRACKS_ON_MOTHER_BOARD_TO_SOCKET
        D3D11_BUS_IMPL_MODIFIER_DAUGHTER_BOARD_CONNECTOR
        D3D11_BUS_IMPL_MODIFIER_DAUGHTER_BOARD_CONNECTOR_INSIDE_OF_NUAE
        D3D11_BUS_IMPL_MODIFIER_NON_STANDARD

    ctypedef struct ID3D11Device:
        ID3D11DeviceVtbl *lpVtbl

    enum D3D11_RESOURCE_DIMENSION:
        D3D11_RESOURCE_DIMENSION_UNKNOWN
        D3D11_RESOURCE_DIMENSION_BUFFER
        D3D11_RESOURCE_DIMENSION_TEXTURE1D
        D3D11_RESOURCE_DIMENSION_TEXTURE2D
        D3D11_RESOURCE_DIMENSION_TEXTURE3D

    ctypedef void (*RESOURCE_GETTYPE)(ID3D11Resource *rsc, D3D11_RESOURCE_DIMENSION *dim)

    ctypedef struct ID3D11ResourceVtbl:
        RESOURCE_GETTYPE GetType

    ctypedef struct ID3D11Resource:
        const ID3D11ResourceVtbl* lpVtbl

    ctypedef struct D3D11_BOX:
        UINT left
        UINT top
        UINT front
        UINT right
        UINT bottom
        UINT back

    ctypedef struct D3D11_TEXTURE2D_DESC:
        UINT             Width
        UINT             Height
        UINT             MipLevels
        UINT             ArraySize
        DXGI_FORMAT      Format
        DXGI_SAMPLE_DESC SampleDesc
        D3D11_USAGE      Usage
        UINT             BindFlags
        UINT             CPUAccessFlags
        UINT             MiscFlags

    ctypedef ULONG (*DC_ADDREF)(ID3D11DeviceContext *context)
    ctypedef ULONG (*DC_RELEASE)(ID3D11DeviceContext *context)
    ctypedef void (*DC_BEGIN)(ID3D11DeviceContext *context)
    ctypedef void (*DC_END)(ID3D11DeviceContext *context)
    ctypedef void (*DC_FLUSH)(ID3D11DeviceContext *context)
    ctypedef UINT (*DC_GET_CONTEXT_FLAGS)(ID3D11DeviceContext *context)
    ctypedef UINT (*DC_GET_TYPE)(ID3D11DeviceContext *context)
    ctypedef void (*DC_COPYRESOURCE)(ID3D11DeviceContext *context, ID3D11Resource *dst, ID3D11Resource *src)
    ctypedef void (*DC_COPYSUBRESOURCEREGION)(ID3D11DeviceContext *context,
                                              ID3D11Resource *dst, UINT dstSubResource, UINT dstX, UINT dstY, UINT dstZ,
                                              ID3D11Resource *src, UINT srcSubResource)
    ctypedef void (*DC_UPDATESUBRESOURCEREGION)(ID3D11DeviceContext *context,
                                                ID3D11Resource  *pDstResource, UINT DstSubresource,
                                                const D3D11_BOX *pDstBox,
                                                const void      *pSrcData,
                                                UINT            SrcRowPitch,
                                                UINT            SrcDepthPitch)

    ctypedef struct ID3D11DeviceContextVtbl:
        DC_ADDREF AddRef
        DC_RELEASE Release
        DC_BEGIN Begin
        DC_END End
        DC_FLUSH Flush
        DC_GET_CONTEXT_FLAGS GetContextFlags
        DC_GET_TYPE GetType
        DC_COPYRESOURCE CopyResource
        DC_COPYSUBRESOURCEREGION CopySubresourceRegion
        DC_UPDATESUBRESOURCEREGION UpdateSubresource

    ctypedef struct ID3D11DeviceContext:
        ID3D11DeviceContextVtbl *lpVtbl

    ctypedef ULONG (*DEVICE_ADDREF)(ID3D11Device *context)
    ctypedef ULONG (*DEVICE_RELEASE)(ID3D11Device *context)
    ctypedef HRESULT (*DEVICE_QUERYINTERFACE)(ID3D11Device* pThis, REFIID *interfaceID, void** ppInterface)
    ctypedef HRESULT (*DEVICE_CREATEBUFFER)(ID3D11Device *this, void *desc, void *initialData, void **buffer)
    ctypedef HRESULT (*DEVICE_CREATETEXTURE1D)(ID3D11Device *this, void *desc, void *initialData, void **texture)
    ctypedef HRESULT (*DEVICE_CREATETEXTURE2D)(ID3D11Device *this, void *desc, void *initialData, void **texture)
    ctypedef UINT (*DEVICE_GETCREATION_FLAGS)(ID3D11Device *this)
    ctypedef int (*DEVICE_GETFEATURELEVEL)(ID3D11Device *this)
    ctypedef int (*DEVICE_GETCREATIONFLAGS)(ID3D11Device *this)
    ctypedef void (*DEVICE_GETIMMEDIATECONTEXT)(ID3D11Device *this, ID3D11DeviceContext **context)
    ctypedef HRESULT (*DEVICE_SETEXCEPTIONMODE)(ID3D11Device *this, UINT RaiseFlags)
    ctypedef UINT (*DEVICE_GETEXCEPTIONMODE)(ID3D11Device *this)

    ctypedef struct ID3D11DeviceVtbl:
        DEVICE_ADDREF AddRef
        DEVICE_RELEASE Release
        DEVICE_QUERYINTERFACE QueryInterface
        DEVICE_CREATEBUFFER CreateBuffer
        DEVICE_CREATETEXTURE1D CreateTexture1D
        DEVICE_CREATETEXTURE2D CreateTexture2D
        DEVICE_GETCREATION_FLAGS GetCreationFlags
        DEVICE_GETFEATURELEVEL GetFeatureLevel
        DEVICE_GETCREATIONFLAGS GetCreationFlags
        DEVICE_GETIMMEDIATECONTEXT GetImmediateContext
        DEVICE_SETEXCEPTIONMODE SetExceptionMode
        DEVICE_GETEXCEPTIONMODE GetExceptionMode

    ctypedef struct ID3D11Device:
        ID3D11DeviceVtbl *lpVtbl

    ctypedef enum D3D11_QUERY:
        D3D11_QUERY_EVENT
        D3D11_QUERY_OCCLUSION
        D3D11_QUERY_TIMESTAMP
        D3D11_QUERY_TIMESTAMP_DISJOINT
        D3D11_QUERY_PIPELINE_STATISTICS
        D3D11_QUERY_OCCLUSION_PREDICATE
        D3D11_QUERY_SO_STATISTICS
        D3D11_QUERY_SO_OVERFLOW_PREDICATE
        D3D11_QUERY_SO_STATISTICS_STREAM0
        D3D11_QUERY_SO_OVERFLOW_PREDICATE_STREAM0
        D3D11_QUERY_SO_STATISTICS_STREAM1
        D3D11_QUERY_SO_OVERFLOW_PREDICATE_STREAM1
        D3D11_QUERY_SO_STATISTICS_STREAM2
        D3D11_QUERY_SO_OVERFLOW_PREDICATE_STREAM2
        D3D11_QUERY_SO_STATISTICS_STREAM3
        D3D11_QUERY_SO_OVERFLOW_PREDICATE_STREAM3

    ctypedef struct D3D11_QUERY_DESC:
        D3D11_QUERY Query
        UINT MiscFlags

    # DEFINE_GUID(IID_ID3D11Query, 0xd6c00747, 0x87b7, 0x425e, 0xb8, 0x4d, 0x44, 0xd1, 0x08, 0x56, 0x0a, 0xfd)

    ctypedef void (*QUERY_GETDESC)(ID3D11Query this, D3D11_QUERY_DESC *desc)

    ctypedef struct ID3D11QueryVtbl:
        QUERY_GETDESC GetDesc

    ctypedef struct ID3D11Query:
        const ID3D11QueryVtbl *lpVtbl


FEATURE_LEVELS: Dict[int, str] = {
    # D3D_FEATURE_LEVEL_1_0_GENERIC: "1_0_GENERIC",
    # D3D_FEATURE_LEVEL_1_0_CORE: "1_0_CORE",
    D3D_FEATURE_LEVEL_9_1: (9, 1),
    D3D_FEATURE_LEVEL_9_2: (9, 2),
    D3D_FEATURE_LEVEL_9_3: (9, 3),
    D3D_FEATURE_LEVEL_10_0: (10, 0),
    D3D_FEATURE_LEVEL_10_1: (10, 1),
    D3D_FEATURE_LEVEL_11_0: (11, 0),
    D3D_FEATURE_LEVEL_11_1: (11, 1),
    D3D_FEATURE_LEVEL_12_0: (12, 0),
    D3D_FEATURE_LEVEL_12_1: (12, 1),
    D3D_FEATURE_LEVEL_12_2: (12, 2),
}

FEATURES: Dict[int, str] = {
    D3D11_FEATURE_THREADING: "THREADING",
    D3D11_FEATURE_DOUBLES: "DOUBLES",
    D3D11_FEATURE_FORMAT_SUPPORT: "FORMAT_SUPPORT",
    D3D11_FEATURE_FORMAT_SUPPORT2: "FORMAT_SUPPORT2",
    D3D11_FEATURE_D3D10_X_HARDWARE_OPTIONS: "D3D10_X_HARDWARE_OPTIONS",
    D3D11_FEATURE_D3D11_OPTIONS: "D3D11_OPTIONS",
    D3D11_FEATURE_ARCHITECTURE_INFO: "ARCHITECTURE_INFO",
    D3D11_FEATURE_D3D9_OPTIONS: "D3D9_OPTIONS",
    D3D11_FEATURE_SHADER_MIN_PRECISION_SUPPORT: "SHADER_MIN_PRECISION_SUPPORT",
    D3D11_FEATURE_D3D9_SHADOW_SUPPORT: "D3D9_SHADOW_SUPPORT",
    D3D11_FEATURE_D3D11_OPTIONS1: "D3D11_OPTIONS1",
    D3D11_FEATURE_D3D9_SIMPLE_INSTANCING_SUPPORT: "D3D9_SIMPLE_INSTANCING_SUPPORT",
    D3D11_FEATURE_MARKER_SUPPORT: "MARKER_SUPPORT",
    D3D11_FEATURE_D3D9_OPTIONS1: "D3D9_OPTIONS1",
    D3D11_FEATURE_D3D11_OPTIONS2: "D3D11_OPTIONS2",
    D3D11_FEATURE_D3D11_OPTIONS3: "D3D11_OPTIONS3",
    D3D11_FEATURE_GPU_VIRTUAL_ADDRESS_SUPPORT: "GPU_VIRTUAL_ADDRESS_SUPPORT",
    D3D11_FEATURE_D3D11_OPTIONS4: "D3D11_OPTIONS4",
    D3D11_FEATURE_SHADER_CACHE: "SHADER_CACHE",
    D3D11_FEATURE_D3D11_OPTIONS5: "D3D11_OPTIONS5",
    # D3D11_FEATURE_DISPLAYABLE: "DISPLAYABLE",
    # D3D11_FEATURE_D3D11_OPTIONS6: "D3D11_OPTIONS6",
}

DEVICE_FLAGS: Dict[int, str] = {
    D3D11_CREATE_DEVICE_SINGLETHREADED: "SINGLETHREADED",
    D3D11_CREATE_DEVICE_DEBUG: "DEBUG",
    D3D11_CREATE_DEVICE_SWITCH_TO_REF: "SWITCH_TO_REF",
    D3D11_CREATE_DEVICE_PREVENT_INTERNAL_THREADING_OPTIMIZATIONS: "PREVENT_INTERNAL_THREADING_OPTIMIZATIONS",
    D3D11_CREATE_DEVICE_BGRA_SUPPORT: "BGRA_SUPPORT",
    D3D11_CREATE_DEVICE_DEBUGGABLE: "DEBUGGABLE",
    D3D11_CREATE_DEVICE_PREVENT_ALTERING_LAYER_SETTINGS_FROM_REGISTRY: "PREVENT_ALTERING_LAYER_SETTINGS_FROM_REGISTRY",
    D3D11_CREATE_DEVICE_DISABLE_GPU_TIMEOUT: "DISABLE_GPU_TIMEOUT",
    D3D11_CREATE_DEVICE_VIDEO_SUPPORT: "VIDEO_SUPPORT",
}


cdef class D3D11DeviceContext:
    cdef ID3D11Device *device
    cdef ID3D11DeviceContext *context

    def __init__(self, devptr: uintptr_t):
        assert devptr, "no device"
        self.device = <ID3D11Device *> devptr
        self.context = NULL

    def __enter__(self):
        self.device.lpVtbl.GetImmediateContext(self.device, &self.context)
        assert self.context
        return self

    def __exit__(self, *_args):
        assert self.context
        self.context.lpVtbl.Release(self.context)
        self.context = NULL

    def __repr__(self):
        return "ImmediateContext(%s)" % self.d3d11device

    def flush(self) -> None:
        assert self.context
        self.context.lpVtbl.Flush(self.context)

    def copy_resource(self, uintptr_t dst, uintptr_t src) -> None:
        log("D3D11DeviceContext.copy_resource(%#x, %#x)", dst, src)
        assert self.context
        assert dst and src
        cdef ID3D11Resource *r_dst = <ID3D11Resource*> dst
        cdef ID3D11Resource *r_src = <ID3D11Resource*> src
        self.context.lpVtbl.CopyResource(self.context, r_dst, r_src)

    def get_info(self) -> Dict[str, Any]:
        assert self.context
        flags = self.context.lpVtbl.GetContextFlags(self.context)
        immediate = bool(self.context.lpVtbl.GetType(self.context) & D3D11_DEVICE_CONTEXT_IMMEDIATE)
        flags_strs = tuple(name for value, name in DEVICE_FLAGS.items() if flags & value)
        return {
            "address": <uintptr_t> self.context,
            "flags": flags_strs,
            "immediate": immediate,
        }


cdef class D3D11Device:
    cdef ID3D11Device *device

    def __init__(self, devptr: uintptr_t):
        assert devptr, "no device"
        self.device = <ID3D11Device *> devptr

    def get_device_context(self):
        return D3D11DeviceContext(<uintptr_t> self.device)

    def Release(self):
        self.device.lpVtbl.Release(self.device)

    def get_immediate_context(self) -> D3D11DeviceContext:
        return D3D11DeviceContext(self)

    def __repr__(self):
        return "D3D11Device(%#x)" % <uintptr_t> self.device

    def get_info(self) -> Dict[str, Any]:
        level = self.device.lpVtbl.GetFeatureLevel(self.device)
        emode = self.device.lpVtbl.GetExceptionMode(self.device)
        # D3D11_CREATE_DEVICE_SINGLETHREADED
        info = {
            "address": <uintptr_t> self.device,
            "feature-level": FEATURE_LEVELS.get(level, level),
            "exception-mode": emode,
        }
        # get a IDXGIDevice interface from this device:
        cdef GUID device_guid               # IID_IDXGIDevice
        set_GUID(&device_guid, 0x54ec77fa, 0x1377, 0x44e6, 0x8c, 0x32, 0x88, 0xfd, 0x5f, 0x44, 0xc8, 0x4c)
        cdef IDXGIDevice *dxgi_device = NULL
        cdef HRESULT res = self.device.lpVtbl.QueryInterface(self.device, &device_guid, <void**> &dxgi_device)
        log("D3D11Device.QueryInterface(DXGIDevice)=%i, dxgi_device=%#x", res, <uintptr_t> dxgi_device)
        if res:
            log.warn("Warning: failed to get DXGIDevice interface: %s", ERRORS.get(res, res))
            return info
        assert dxgi_device
        # get the adapter interface:
        cdef GUID adapter_guid     # IID_IDXGIAdapter
        set_GUID(&adapter_guid, 0x2411e7e1, 0x12ac, 0x4ccf, 0xbd, 0x14, 0x97, 0x9b, 0xe2, 0x52, 0x12, 0x20)
        cdef IDXGIAdapter *adapter
        res = dxgi_device.lpVtbl.GetAdapter(dxgi_device, &adapter)
        if res:
            log.warn("Warning: failed to get IDXGIAdapter: %s", ERRORS.get(res, res))
            return info
        assert adapter
        # get the adapter description:
        cdef DXGI_ADAPTER_DESC desc
        res = adapter.lpVtbl.GetDesc(adapter, &desc)
        if res:
            log.warn("Warning: failed to get adapter description: %s", ERRORS.get(res, res))
            return info

        cdef size_t size = wcslen(desc.Description)
        description = PyUnicode_FromWideChar(desc.Description, size)
        info.update({
            "description": description,
            "vendor": VENDORS.get(desc.VendorId, desc.VendorId),
            "device": desc.DeviceId,
            "subsystem": desc.SubSysId,
            "revision": desc.Revision,
            "memory": {
                "video": desc.DedicatedVideoMemory,
                "system": desc.DedicatedSystemMemory,
                "shared": desc.SharedSystemMemory,
            },
            "luid": "%#x:%#x" % (desc.AdapterLuid.HighPart, desc.AdapterLuid.LowPart),
        })
        return info


cdef void set_GUID(GUID* guid, uint32_t data1, uint16_t data2, uint16_t data3,
                   uint8_t data40, uint8_t data41, uint8_t data42, uint8_t data43,
                   uint8_t data44, uint8_t data45, uint8_t data46, uint8_t data47):
    guid.Data1 = data1
    guid.Data2 = data2
    guid.Data3 = data3
    guid.Data4[0] = data40
    guid.Data4[1] = data41
    guid.Data4[2] = data42
    guid.Data4[3] = data43
    guid.Data4[4] = data44
    guid.Data4[5] = data45
    guid.Data4[6] = data46
    guid.Data4[7] = data47
