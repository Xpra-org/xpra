# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uintptr_t
from xpra.codecs.nvidia.nvenc.api cimport NV_ENCODE_API_FUNCTION_LIST

ctypedef int NVENCSTATUS


cdef void init_nvencode_library()

cdef NVENCSTATUS create_nvencode_instance(NV_ENCODE_API_FUNCTION_LIST *functionList)

cdef uintptr_t get_current_cuda_context()
