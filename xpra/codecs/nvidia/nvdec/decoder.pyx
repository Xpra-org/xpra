# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger
log = Logger("encoder", "nvdec")

#we can import pycuda safely here,
#because importing cuda_context will have imported it with the lock
from pycuda import driver  # @UnresolvedImport
import numpy

cdef inline int MIN(int a, int b):
    if a<=b:
        return a
    return b
cdef inline int MAX(int a, int b):
    if a>=b:
        return a
    return b


#cdef extern from "cuviddec.h":
#    pass


def init_module():
    log("enc_x264.init_module()")

def cleanup_module():
    log("nvdec.cleanup_module()")

def get_version():
    return (0, )

def get_type():
    return "nvdec"

def get_info():
    return {
        "version"   : get_version(),
        }

def get_encodings():
    return ("h264", )

def get_input_colorspaces(encoding):
    return ("YUV420P", )

def get_output_colorspace(encoding, csc):
    #same as input
    return csc


class Decoder:
    pass


def selftest(full=False):
    from xpra.codecs.nvidia.nv_util import has_nvidia_hardware, get_nvidia_module_version
    if not has_nvidia_hardware():
        raise ImportError("no nvidia GPU device found")
    get_nvidia_module_version(True)
