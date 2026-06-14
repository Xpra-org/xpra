# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Apple framework declarations shared by the VideoToolbox encoder and decoder.
# All the Apple framework types are declared inside their `cdef extern` blocks
# so that Cython uses the real header types (rather than emitting its own,
# which would be incompatible at the C level).

from libc.stdint cimport uint8_t, uint32_t, int32_t, int64_t


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


cdef extern from "CoreFoundation/CoreFoundation.h":
    ctypedef int OSStatus
    ctypedef unsigned int OSType
    ctypedef unsigned char Boolean
    ctypedef long CFIndex
    ctypedef void* CFAllocatorRef
    ctypedef const void* CFTypeRef
    ctypedef const void* CFStringRef
    ctypedef const void* CFBooleanRef
    ctypedef const void* CFNumberRef
    ctypedef const void* CFDictionaryRef
    ctypedef const void* CFArrayRef
    int kCFNumberSInt32Type
    CFBooleanRef kCFBooleanTrue
    CFBooleanRef kCFBooleanFalse
    void CFRelease(CFTypeRef cf) nogil
    CFTypeRef CFRetain(CFTypeRef cf) nogil
    CFNumberRef CFNumberCreate(CFAllocatorRef allocator, int theType, const void* valuePtr)
    CFIndex CFArrayGetCount(CFArrayRef theArray)
    const void* CFArrayGetValueAtIndex(CFArrayRef theArray, CFIndex idx)
    Boolean CFDictionaryContainsKey(CFDictionaryRef theDict, const void* key)


cdef extern from "CoreVideo/CoreVideo.h":
    ctypedef int CVReturn
    ctypedef void* CVPixelBufferRef
    CVReturn CVPixelBufferCreate(CFAllocatorRef allocator, size_t width, size_t height,
                                 OSType pixelFormatType, CFDictionaryRef pixelBufferAttributes,
                                 CVPixelBufferRef* pixelBufferOut) nogil
    CVReturn CVPixelBufferLockBaseAddress(CVPixelBufferRef pixelBuffer, uint32_t lockFlags) nogil
    CVReturn CVPixelBufferUnlockBaseAddress(CVPixelBufferRef pixelBuffer, uint32_t unlockFlags) nogil
    size_t CVPixelBufferGetPlaneCount(CVPixelBufferRef pixelBuffer) nogil
    void* CVPixelBufferGetBaseAddressOfPlane(CVPixelBufferRef pixelBuffer, size_t planeIndex) nogil
    size_t CVPixelBufferGetBytesPerRowOfPlane(CVPixelBufferRef pixelBuffer, size_t planeIndex) nogil
    size_t CVPixelBufferGetHeightOfPlane(CVPixelBufferRef pixelBuffer, size_t planeIndex) nogil
    void* CVPixelBufferGetBaseAddress(CVPixelBufferRef pixelBuffer) nogil
    size_t CVPixelBufferGetBytesPerRow(CVPixelBufferRef pixelBuffer) nogil


cdef extern from "CoreMedia/CoreMedia.h":
    ctypedef unsigned int CMVideoCodecType
    ctypedef void* CMSampleBufferRef
    ctypedef void* CMBlockBufferRef
    ctypedef void* CMFormatDescriptionRef
    ctypedef struct CMTime:
        int64_t value
        int32_t timescale
        uint32_t flags
        int64_t epoch
    CMTime CMTimeMake(int64_t value, int32_t timescale) nogil
    CMBlockBufferRef CMSampleBufferGetDataBuffer(CMSampleBufferRef sbuf) nogil
    OSStatus CMBlockBufferGetDataPointer(CMBlockBufferRef theBuffer, size_t offset,
                                         size_t* lengthAtOffsetOut, size_t* totalLengthOut,
                                         char** dataPointerOut) nogil
    CMFormatDescriptionRef CMSampleBufferGetFormatDescription(CMSampleBufferRef sbuf) nogil
    CFArrayRef CMSampleBufferGetSampleAttachmentsArray(CMSampleBufferRef sbuf, Boolean createIfNecessary) nogil
    OSStatus CMVideoFormatDescriptionGetH264ParameterSetAtIndex(CMFormatDescriptionRef videoDesc,
                                                                size_t parameterSetIndex,
                                                                const uint8_t** parameterSetPointerOut,
                                                                size_t* parameterSetSizeOut,
                                                                size_t* parameterSetCountOut,
                                                                int* nalUnitHeaderLengthOut) nogil
    OSStatus CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(CMFormatDescriptionRef videoDesc,
                                                                size_t parameterSetIndex,
                                                                const uint8_t** parameterSetPointerOut,
                                                                size_t* parameterSetSizeOut,
                                                                size_t* parameterSetCountOut,
                                                                int* nalUnitHeaderLengthOut) nogil
    CFStringRef kCMSampleAttachmentKey_NotSync


# codec types and pixel formats, expressed as their FourCC integer values:
cdef enum:
    kCMVideoCodecType_H264 = 0x61766331       # 'avc1'
    kCMVideoCodecType_HEVC = 0x68766331       # 'hvc1'
    kCVPixelFormatType_420YpCbCr8Planar = 0x79343230              # 'y420' (I420)
    kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange = 0x34323076  # '420v' (NV12, video range)
    kCVPixelFormatType_420YpCbCr8BiPlanarFullRange = 0x34323066   # '420f' (NV12, full range)
    kCVPixelFormatType_32BGRA = 0x42475241                        # 'BGRA'
