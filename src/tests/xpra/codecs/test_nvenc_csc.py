#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

print("starting imports")
import binascii
import numpy

from xpra.log import Logger
log = Logger()

from xpra.util import roundup
print("loading encoder class")
from xpra.codecs.nvenc.encoder import cuda_check, get_BGRA2NV12

print("cuda check")
cuda_check()

print("pycuda import")
from pycuda import driver       #@UnresolvedImport

cuda_device = driver.Device(0)
print("cuda_device=%s" % cuda_device)
cuda_context = cuda_device.make_context(flags=driver.ctx_flags.SCHED_AUTO | driver.ctx_flags.MAP_HOST)
try:
    print("cuda_context=%s" % cuda_context)

    BGRA2NV12 = get_BGRA2NV12()
    print("BGRA2NV12=%s" % BGRA2NV12)

    w = roundup(512, 32)
    h = roundup(512, 32)

    log("w=%s, h=%s", w, h)

    cudaInputBuffer, inputPitch = driver.mem_alloc_pitch(w, h*3/2, 16)
    log("CUDA Input Buffer=%s, pitch=%s", hex(int(cudaInputBuffer)), inputPitch)
    #allocate CUDA NV12 buffer (on device):
    cudaNV12Buffer, NV12Pitch = driver.mem_alloc_pitch(w, h*3/2, 16)
    log("CUDA NV12 Buffer=%s, pitch=%s", hex(int(cudaNV12Buffer)), NV12Pitch)

    #host buffers:
    inputBuffer = driver.pagelocked_zeros(inputPitch*h*3/2, dtype=numpy.byte)
    log("inputBuffer=%s", inputBuffer)

    outputBuffer = driver.pagelocked_zeros(inputPitch*h*3/2, dtype=numpy.byte)
    log("outputBuffer=%s", outputBuffer)

    #populate host buffer with random data:
    buf = inputBuffer.data
    for y in range(h*3/2):
        dst = y * inputPitch
        #debug("%s: %s:%s (size=%s) <- %s:%s (size=%s)", y, dst, dst+w, len(buffer), src, src+w, len(Yplane))
        for x in range(w):
            buf[dst+x] = numpy.byte((x+y) % 256)

    #copy input buffer to CUDA buffer:
    driver.memcpy_htod(cudaInputBuffer, inputBuffer)
    log("input buffer copied to device")

    #FIXME: just clear the NV12 buffer:
    driver.memcpy_htod(cudaNV12Buffer, outputBuffer)
    #FIXME: just for testing fill the buffer with our input already:
    #driver.memcpy_htod(cudaNV12Buffer, inputBuffer)

    if True:
        log("calling %s", BGRA2NV12)
        BGRA2NV12(cudaInputBuffer, numpy.int32(inputPitch),
               cudaNV12Buffer, numpy.int32(NV12Pitch),
               numpy.int32(w), numpy.int32(h),
               block=(16,16,1), grid=(w/16, h/16))

    #download NV12 buffer:
    log("downloading output")
    driver.memcpy_dtoh(outputBuffer, cudaNV12Buffer)

    for i in range(h):
        p = i*w
        l = outputBuffer.data[p:p+w]
        log("%s: %s", hex(i).ljust(5), binascii.hexlify(str(l)))
            #debug("[%s] = %s / %s", i, ord(inputBuffer.data[i]), ord(outputBuffer.data[i]))

    #outputBuffer.data[1024] = numpy.byte(20)
    same = 0
    diff = 0
    zeroes = 0
    for i in range(w*h*3/2):
        if ord(outputBuffer.data[i])==0:
            zeroes += 1
        if inputBuffer.data[i]!=outputBuffer.data[i]:
            if diff<10:
                log("buffer differs at %s: %s vs %s", i, ord(inputBuffer.data[i]), ord(outputBuffer.data[i]))
            diff +=1
        else:
            same +=1

    log("end: same=%s, diff=%s, zeroes=%s", same, diff, zeroes)

except Exception as e:
    log("exception: %s" % e)
    import traceback
    traceback.print_stack()
finally:
    cuda_context.pop()
    cuda_context.detach()
