#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pyopencl     #@UnresolvedImport
from pyopencl import mem_flags  #@UnresolvedImport
import ctypes

if hasattr(ctypes.pythonapi, 'Py_InitModule4'):
    Py_ssize_t = ctypes.c_int
elif hasattr(ctypes.pythonapi, 'Py_InitModule4_64'):
    Py_ssize_t = ctypes.c_int64
PyBuffer_FromReadWriteMemory = ctypes.pythonapi.PyBuffer_FromReadWriteMemory
PyBuffer_FromReadWriteMemory.restype = ctypes.py_object
PyBuffer_FromReadWriteMemory.argtypes = [ctypes.c_void_p, Py_ssize_t]

PyBuffer_FromMemory = ctypes.pythonapi.PyBuffer_FromMemory
PyBuffer_FromMemory.restype = ctypes.py_object
PyBuffer_FromMemory.argtypes = [ctypes.c_void_p, Py_ssize_t]

globalWorkSize = (32,32)
localWorkSize = (8,8)
shape = 32*8, 32*8

context = pyopencl.create_some_context(interactive=False)
assert context
kernel = """
__kernel void EXAMPLE(read_only image2d_t src, write_only image2d_t dst) {
    uint gx = get_global_id(0);
    uint gy = get_global_id(1);
    const sampler_t sampler = CLK_NORMALIZED_COORDS_FALSE |
                           CLK_ADDRESS_CLAMP |
                           CLK_FILTER_NEAREST;

    float4 p;

    float Y = 1.1643 * read_imagef(src, sampler, (int2)( gx, gy )).s0 - 0.0625;

    p.s0 = Y;
    p.s1 = 1.0;
    p.s2 = 1.0;
    p.s3 = 1.0;

    write_imagef(dst, (int2)( gx, gy ), p);
}
"""
program = pyopencl.Program(context, kernel)
program.build()


def test():
    l = shape[0]*shape[1]
    #with a string:
    s = " "*l
    test_buffer(s)
    #create a buffer with ctypes:
    buf = ctypes.create_string_buffer(l)
    test_buffer(buf)
    #create a read-write view of this buffer:
    pointer = ctypes.cast(buf,ctypes.POINTER(ctypes.c_char))
    size = Py_ssize_t(l)
    rw = PyBuffer_FromReadWriteMemory(pointer, size)
    test_buffer(rw)
    ro = PyBuffer_FromMemory(pointer, size)
    test_buffer(ro)


def test_buffer(buf):
    try:
        do_test(buf)
        print("OK:  %s buffer" % type(buf))
    except Exception as e:
        print("ERR: %s buffer fails:       %s" % (type(buf), e))

def do_test(buf):
    global program, context
    queue = pyopencl.CommandQueue(context)

    #input image:
    iformat = pyopencl.ImageFormat(pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8)
    #flags = mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR
    flags = mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR
    iimage = pyopencl.Image(context, flags, iformat, shape=shape, hostbuf=buf)

    #output image:
    oformat = pyopencl.ImageFormat(pyopencl.channel_order.RGBA, pyopencl.channel_type.UNORM_INT8)
    oimage = pyopencl.Image(context, mem_flags.WRITE_ONLY, oformat, shape=shape)

    program.EXAMPLE(queue, globalWorkSize, localWorkSize, iimage, oimage)
    #in a real application, we would readback the output image here
    queue.finish()


def main():
    test()


if __name__ == "__main__":
    main()
