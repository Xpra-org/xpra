# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from libc.stdint cimport uintptr_t

ctypedef unsigned int UINT
ctypedef unsigned int HRESULT
ctypedef unsigned long ULONG


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


cdef extern from "d3d11.h":
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

    ctypedef struct ID3D11Resource:
        pass

    ctypedef struct D3D11_BOX:
        pass

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
        self.context.lpVtbl.Flush(self.context)

    def copy_resource(self, dst: int, src: int) -> None:
        assert dst and src
        cdef ID3D11Resource *r_dst = <ID3D11Resource*> dst
        cdef ID3D11Resource *r_src = <ID3D11Resource*> src
        self.context.lpVtbl.CopyResource(self.context, r_dst, r_src)

    def update_subresource(self, dst: int, dst_sub: int, box: tuple, src: int, stride: int, depth_pitch: int) -> None:
        assert dst
        cdef ID3D11Resource *dstr = <ID3D11Resource*> dst
        cdef void *data = <void *> src
        self.context.lpVtbl.UpdateSubresource(self.context, dstr, dst_sub, NULL, data, stride, depth_pitch)

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
        return {
            "address": <uintptr_t> self.device,
            "feature-level": FEATURE_LEVELS.get(level, level),
            "exception-mode": emode,
        }
