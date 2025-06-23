# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ctypes
from ctypes import cdll, POINTER

from xpra.os_util import WIN32, LINUX
from xpra.codecs.nvidia.cuda.errors import get_error_name

from libc.stdint cimport uintptr_t


from xpra.log import Logger
log = Logger("encoder", "nvenc")


# CUresult = ctypes.c_int
CUcontext = ctypes.c_void_p


NvEncodeAPICreateInstance = None
cuCtxGetCurrent = None


cdef void init_nvencode_library():
    global NvEncodeAPICreateInstance, cuCtxGetCurrent
    if WIN32:
        load = ctypes.WinDLL
        nvenc_libname = "nvencodeapi64.dll"
        cuda_libname = "nvcuda.dll"
    else:
        #assert os.name=="posix"
        load = cdll.LoadLibrary
        nvenc_libname = "libnvidia-encode.so.1"
        cuda_libname = "libcuda.so"
    # CUDA:
    log("init_nvencode_library() will try to load %r", cuda_libname)
    try:
        x = load(cuda_libname)
        log("init_nvencode_library() %s(%s)=%s", load, cuda_libname, x)
    except Exception as e:
        log("failed to load '%s'", cuda_libname, exc_info=True)
        raise ImportError("nvenc: the required library %s cannot be loaded: %s" % (cuda_libname, e)) from None
    cuCtxGetCurrent = x.cuCtxGetCurrent
    cuCtxGetCurrent.restype = ctypes.c_int          # CUresult == int
    cuCtxGetCurrent.argtypes = [POINTER(CUcontext)] # CUcontext *pctx
    log("init_nvencode_library() %s.cuCtxGetCurrent=%s", os.path.splitext(cuda_libname)[0], cuCtxGetCurrent)
    #nvidia-encode:
    log("init_nvencode_library() will try to load %s", nvenc_libname)
    try:
        x = load(nvenc_libname)
        log("init_nvencode_library() %s(%s)=%s", load, nvenc_libname, x)
    except Exception as e:
        log("failed to load '%s'", nvenc_libname, exc_info=True)
        raise ImportError("nvenc: the required library %s cannot be loaded: %s" % (nvenc_libname, e)) from None
    NvEncodeAPICreateInstance = x.NvEncodeAPICreateInstance
    NvEncodeAPICreateInstance.restype = ctypes.c_int
    NvEncodeAPICreateInstance.argtypes = [ctypes.c_void_p]
    log("init_nvencode_library() NvEncodeAPICreateInstance=%s", NvEncodeAPICreateInstance)
    #NVENCSTATUS NvEncodeAPICreateInstance(NV_ENCODE_API_FUNCTION_LIST *functionList)


cdef NVENCSTATUS create_nvencode_instance(NV_ENCODE_API_FUNCTION_LIST *functionList):
    if not NvEncodeAPICreateInstance:
        raise RuntimeError("NvEncodeAPICreateInstance is not available")
    log("NvEncodeAPICreateInstance(%#x)", <uintptr_t> functionList)
    return NvEncodeAPICreateInstance(<uintptr_t> functionList)


cdef uintptr_t get_current_cuda_context():
    # get the CUDA context C pointer,
    # using a bit of magic to pass a cython pointer to ctypes:
    cdef uintptr_t cuda_context_ptr = 0
    cdef context_pp = <uintptr_t> (&cuda_context_ptr)
    cdef int result = cuCtxGetCurrent(ctypes.cast(context_pp, POINTER(ctypes.c_void_p)))
    estr = get_error_name(result)
    log(f"cuCtxGetCurrent() returned {estr!r}, context_pointer=%#x, cuda context pointer=%#x",
        context_pp, cuda_context_ptr)
    if result:
        raise RuntimeError(f"failed to get current cuda context, cuCtxGetCurrent returned {estr!r}")
    if (<uintptr_t> cuda_context_ptr) == 0:
        raise RuntimeError("invalid null cuda context pointer")
    return cuda_context_ptr
