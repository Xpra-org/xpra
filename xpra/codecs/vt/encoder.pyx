# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

# Basic hardware video encoder using Apple's VideoToolbox framework.
# Only the encoder is implemented for now (the decoder can be added later).
# The compressed bitstream is converted from the AVCC format produced by
# VideoToolbox into the Annex-B format that the xpra h264/h265 decoders expect:
# each 4-byte NAL length prefix is replaced by a start code and, on keyframes,
# the parameter sets (SPS/PPS, plus VPS for h265) are prepended.

import os
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("encoder", "videotoolbox")

from xpra.codecs.image import ImageWrapper
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.str_fn import csv
from xpra.util.objects import typedict, AtomicInteger
from xpra.codecs.constants import VideoSpec, get_profile, is_screen_content

from libc.string cimport memset, memcpy
from libc.stdint cimport uint8_t, int32_t, int64_t, uintptr_t

from xpra.codecs.vt.vt cimport *  # noqa: F403 (shared CoreFoundation/CoreVideo/CoreMedia declarations + FourCC enum)


SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE", "")


cdef extern from "VideoToolbox/VideoToolbox.h":
    ctypedef unsigned int VTEncodeInfoFlags
    ctypedef void* VTCompressionSessionRef
    ctypedef void (*VTCompressionOutputCallback)(void* outputCallbackRefCon,
                                                 void* sourceFrameRefCon,
                                                 OSStatus status,
                                                 VTEncodeInfoFlags infoFlags,
                                                 CMSampleBufferRef sampleBuffer) noexcept
    OSStatus VTCompressionSessionCreate(CFAllocatorRef allocator,
                                        int32_t width, int32_t height,
                                        CMVideoCodecType codecType,
                                        CFDictionaryRef encoderSpecification,
                                        CFDictionaryRef sourceImageBufferAttributes,
                                        CFAllocatorRef compressedDataAllocator,
                                        VTCompressionOutputCallback outputCallback,
                                        void* outputCallbackRefCon,
                                        VTCompressionSessionRef* compressionSessionOut) nogil
    OSStatus VTCompressionSessionPrepareToEncodeFrames(VTCompressionSessionRef session) nogil
    OSStatus VTCompressionSessionEncodeFrame(VTCompressionSessionRef session,
                                             CVPixelBufferRef imageBuffer,
                                             CMTime presentationTimeStamp,
                                             CMTime duration,
                                             CFDictionaryRef frameProperties,
                                             void* sourceFrameRefCon,
                                             VTEncodeInfoFlags* infoFlagsOut) nogil
    OSStatus VTCompressionSessionCompleteFrames(VTCompressionSessionRef session,
                                                CMTime completeUntilPresentationTimeStamp) nogil
    void VTCompressionSessionInvalidate(VTCompressionSessionRef session) nogil
    OSStatus VTSessionSetProperty(VTCompressionSessionRef session, CFStringRef propertyKey, CFTypeRef propertyValue) nogil

    CFStringRef kVTCompressionPropertyKey_RealTime
    CFStringRef kVTCompressionPropertyKey_AllowFrameReordering
    CFStringRef kVTCompressionPropertyKey_MaxKeyFrameInterval
    CFStringRef kVTCompressionPropertyKey_AverageBitRate
    CFStringRef kVTCompressionPropertyKey_ProfileLevel
    CFStringRef kVTProfileLevel_H264_ConstrainedBaseline_AutoLevel
    CFStringRef kVTProfileLevel_H264_Main_AutoLevel
    CFStringRef kVTProfileLevel_H264_High_AutoLevel
    CFStringRef kVTProfileLevel_HEVC_Main_AutoLevel
    # the quality floor / ceiling (macos 12 and macos 13 - see `set_qp_range`):
    CFStringRef kVTCompressionPropertyKey_MaxAllowedFrameQP
    CFStringRef kVTCompressionPropertyKey_MinAllowedFrameQP
    CFStringRef kVTCompressionPropertyKey_PrioritizeEncodingSpeedOverQuality


# input colorspaces we accept, mapped to the number of (source) planes:
COLORSPACES: Dict[str, int] = {
    "YUV420P"   : 3,
    "NV12"      : 2,
    "BGRX"      : 1,
    "BGRA"      : 1,
}

# the colorspace the decoder will get for a given input colorspace:
OUTPUT_COLORSPACE: Dict[str, str] = {
    "YUV420P"   : "YUV420P",
    "NV12"      : "NV12",
    "BGRX"      : "YUV420P",
    "BGRA"      : "YUV420P",
}

CODEC_TYPES: Dict[str, CMVideoCodecType] = {
    "h264"  : kCMVideoCodecType_H264,
    "h265"  : kCMVideoCodecType_HEVC,
}


def get_version() -> Tuple[int, int]:
    return 1, 0


def get_type() -> str:
    return "vt"


def get_info() -> Dict[str, Any]:
    return {
        "version"       : get_version(),
        "encodings"     : get_encodings(),
        "colorspaces"   : tuple(COLORSPACES.keys()),
        "h264-profiles" : H264_PROFILES,
        "h264-default-profile": "main",
    }


def get_encodings() -> Sequence[str]:
    return "h264", "h265"


H264_PROFILES: Sequence[str] = ("constrained-baseline", "main", "high")


def get_h264_profile(options: typedict) -> str:
    profile = get_profile(options)
    if profile == "baseline":
        return "constrained-baseline"
    if profile not in H264_PROFILES:
        log.warn("Warning: %r is not a valid VideoToolbox H.264 profile", profile)
        log.warn(" valid profiles are: %s", csv(H264_PROFILES))
        return "main"
    return profile


MAX_WIDTH, MAX_HEIGHT = (4096, 4096)


# the quantizer range of h264 and h265: 0 is the finest, 51 the coarsest
MAX_QP = 51

# how many quantizer steps we move the window by for the content-types we recognize.
# a dB is far cheaper on synthetic content than on continuous tone imagery: measured at
# quality=50, this 3 step shift buys a browser window +3.0dB for 16% more bytes and a
# text window +2.8dB for 14% more, whereas handing the same 3 steps back on video
# content saves 28% of the bytes and costs only 1.3dB - and the sharpness we give up
# there matters less, since video detail is masked whereas screen content is all edges:
CONTENT_QP_SHIFT = 3


def get_qp_shift(content_types: Sequence[str]) -> int:
    if is_screen_content(content_types):
        return -CONTENT_QP_SHIFT
    if any(x in content_types for x in ("video", "picture")):
        return CONTENT_QP_SHIFT
    # unclassified windows keep the neutral mapping
    return 0


# the speed setting from which we ask the encoder to favour encoding time over quality:
SPEED_PRIORITY = 80

# the quantizer window is only read when the compression session is created: VideoToolbox
# accepts the property on an open session and returns no error, but the stream comes out
# unchanged (measured: a session started at quality=20 and switched to quality=80 keeps
# emitting 3.8KB frames, where a session created at quality=80 emits 17.9KB frames).
# Honouring a quality change therefore costs a new session, and the IDR frame that comes
# with it: 7 to 40ms of setup, and a keyframe worth 10 to 90 inter frames.
# So we ignore the jitter and only pay for changes worth a keyframe - the same rule the
# x264 encoder applies, with a wider band since a reconfiguration is free there:
MIN_QP_DELTA = 4


def get_qp_range(quality: int, content_types: Sequence[str] = ()) -> Tuple[int, int]:
    """the quantizer window to allow for this quality setting and content-type"""
    cdef int shift = get_qp_shift(content_types)
    cdef int pct = min(100, max(0, quality))
    # the coarsest quantizer we are willing to accept - this is the quality knob:
    cdef int max_qp = min(MAX_QP, max(0, (100 - pct) * MAX_QP // 100 + shift))
    # and the finest one worth using, which stops the encoder from spending
    # bits on a quality we did not ask for (as the vpx encoder does):
    cdef int min_qp = min(max_qp, max(0, (80 - pct) * MAX_QP // 100 + shift))
    return min_qp, max_qp


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    for encoding in get_encodings():
        for in_cs in tuple(COLORSPACES.keys()):
            out_cs = OUTPUT_COLORSPACE[in_cs]
            specs.append(VideoSpec(
                encoding=encoding, input_colorspace=in_cs, output_colorspaces=(out_cs, ),
                has_lossless_mode=False,
                codec_class=Encoder, codec_type=get_type(),
                # hardware encoder: fast, low cpu cost, runs on the GPU / media engine:
                quality=50, speed=100,
                size_efficiency=50,
                setup_cost=20, cpu_cost=10, gpu_cost=100,
                width_mask=0xFFFE, height_mask=0xFFFE,
                max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            ))
    return specs


generation = AtomicInteger()


# the output callback runs on a VideoToolbox internal thread:
# it acquires the GIL and hands the sample buffer to the Encoder instance.
cdef void encoder_output_callback(void* outputCallbackRefCon, void* sourceFrameRefCon,
                                  OSStatus status, VTEncodeInfoFlags infoFlags,
                                  CMSampleBufferRef sampleBuffer) noexcept with gil:
    cdef Encoder encoder = <Encoder> outputCallbackRefCon
    encoder.process_output(status, sampleBuffer)


cdef class Encoder:
    cdef VTCompressionSessionRef session
    cdef unsigned int width
    cdef unsigned int height
    cdef OSType pixel_format
    cdef object encoding
    cdef object profile
    cdef object src_format
    cdef unsigned long frames
    cdef int full_range
    cdef object init_options
    cdef uint8_t ready
    cdef int quality
    cdef int speed
    cdef int min_qp
    cdef int max_qp
    cdef object content_types
    cdef object file
    # set by the output callback for each encoded frame:
    cdef object frame_data
    cdef int frame_keyframe
    cdef int frame_error

    cdef object __weakref__

    def init_context(self, encoding: str, unsigned int width, unsigned int height, src_format: str,
                     options: typedict) -> None:
        log("vt.init_context%s", (encoding, width, height, src_format, options))
        if encoding not in CODEC_TYPES:
            raise ValueError(f"invalid encoding {encoding!r}, must be one of: {csv(CODEC_TYPES.keys())}")
        if src_format not in COLORSPACES:
            raise ValueError(f"invalid source format {src_format!r}, must be one of: {csv(COLORSPACES.keys())}")
        if options.intget("scaled-width", width) != width or options.intget("scaled-height", height) != height:
            raise ValueError("vt encoder does not handle scaling")
        if width % 2 != 0 or height % 2 != 0:
            raise ValueError(f"invalid odd width {width} or height {height} for {src_format}")
        self.encoding = encoding
        self.profile = get_h264_profile(options) if encoding == "h264" else "main"
        self.width = width
        self.height = height
        self.src_format = src_format
        self.frames = 0
        self.full_range = options.boolget("full-range", True)
        self.quality = options.intget("quality", 50)
        self.speed = options.intget("speed", 50)
        self.content_types = options.strtupleget("content-types", ())
        self.min_qp = self.max_qp = -1
        self.init_options = options
        self.set_pixel_format()
        self.init_encoder(options)
        gen = generation.increase()
        if SAVE_TO_FILE:
            filename = SAVE_TO_FILE + "vt-" + str(gen) + f".{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")
        self.ready = 1

    cdef void init_encoder(self, options: typedict):
        cdef CMVideoCodecType codec = CODEC_TYPES[self.encoding]
        cdef OSStatus r = 0
        cdef CFStringRef profile_level = NULL
        with nogil:
            r = VTCompressionSessionCreate(NULL, self.width, self.height, codec,
                                           NULL, NULL, NULL,
                                           <VTCompressionOutputCallback> encoder_output_callback,
                                           <void*> self, &self.session)
        log("VTCompressionSessionCreate()=%i session=%#x", r, <uintptr_t> self.session)
        if r != 0 or self.session == NULL:
            raise RuntimeError(f"failed to create VideoToolbox compression session, error {r}")

        VTSessionSetProperty(self.session, kVTCompressionPropertyKey_RealTime, kCFBooleanTrue)
        # no B-frames: keep latency low and the bitstream in decode order:
        VTSessionSetProperty(self.session, kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse)
        if self.encoding == "h264":
            if self.profile == "constrained-baseline":
                profile_level = kVTProfileLevel_H264_ConstrainedBaseline_AutoLevel
            elif self.profile == "main":
                profile_level = kVTProfileLevel_H264_Main_AutoLevel
            else:
                profile_level = kVTProfileLevel_H264_High_AutoLevel
        else:
            profile_level = kVTProfileLevel_HEVC_Main_AutoLevel
        r = VTSessionSetProperty(self.session, kVTCompressionPropertyKey_ProfileLevel, profile_level)
        if r != 0:
            raise RuntimeError(f"failed to set VideoToolbox {self.profile} profile, error {r}")

        # like the other xpra video encoders, we only ever need the first frame to be a keyframe
        # (frames are never lost within a stream), so push the keyframe interval far into the future:
        self.set_int_property(kVTCompressionPropertyKey_MaxKeyFrameInterval, 1 << 30)

        cdef int fps = max(1, options.intget("framerate", 30))
        # rough target bitrate derived from the resolution, framerate and quality,
        # bounded by the bandwidth the server is willing to give this connection:
        cdef int64_t pixels = <int64_t> self.width * self.height
        cdef int64_t bitrate = <int64_t> (pixels * fps * (0.04 + self.quality / 100.0 * 0.16))
        cdef int64_t bandwidth_limit = options.intget("bandwidth-limit", 0)
        if bandwidth_limit > 0:
            bitrate = min(bitrate, bandwidth_limit)
        # note: the media engine all but ignores this target once a quantizer window is set
        # (measured: a 500Kbps and a 2Mbps target give byte for byte the same stream), so the
        # quality setting below is what governs the bitrate here. This still matters for the
        # encoders that refuse the quantizer window and keep doing their own rate control:
        self.set_int_property(kVTCompressionPropertyKey_AverageBitRate, <int> bitrate)
        log("vt bitrate=%i bps for %ix%i@%ifps quality=%i", bitrate, self.width, self.height, fps, self.quality)
        self.set_qp_range()
        self.set_speed_priority()

        with nogil:
            r = VTCompressionSessionPrepareToEncodeFrames(self.session)
        if r != 0:
            raise RuntimeError(f"failed to prepare VideoToolbox encoder, error {r}")

    cdef void set_qp_range(self):
        # `AverageBitRate` on its own leaves the quality knob doing almost nothing:
        # the rate controller picks its own quantizers and never even spends the budget
        # it was given (measured: 1.4Mbps out of a 20Mbps target). Asking for a quantizer
        # window instead is what makes `quality` mean something.
        # This can only be done here, when the session is created - see `MIN_QP_DELTA`:
        min_qp, max_qp = get_qp_range(self.quality, self.content_types)
        self.min_qp = min_qp
        self.max_qp = max_qp
        # the quality floor (macos 12 and later):
        self.set_int_property(kVTCompressionPropertyKey_MaxAllowedFrameQP, max_qp)
        # and the ceiling, which is only available from macos 13
        # (the symbol is weakly linked, so it is NULL on anything older):
        if kVTCompressionPropertyKey_MinAllowedFrameQP != NULL:
            self.set_int_property(kVTCompressionPropertyKey_MinAllowedFrameQP, min_qp)
        log("vt qp range=%i-%i for quality=%i, content-types=%s",
            min_qp, max_qp, self.quality, self.content_types)

    cdef void set_speed_priority(self):
        # the only speed knob VideoToolbox exposes. The Apple Silicon media engine is a fixed
        # function pipeline and ignores it (measured: byte for byte the same stream, at the same
        # cost), but the Intel and software encoders do trade quality for encoding time here:
        cdef Boolean prioritize = self.speed >= SPEED_PRIORITY
        VTSessionSetProperty(self.session, kVTCompressionPropertyKey_PrioritizeEncodingSpeedOverQuality,
                             kCFBooleanTrue if prioritize else kCFBooleanFalse)

    cdef void set_pixel_format(self):
        # the bitstream colour range (video_full_range_flag) is carried by the input pixel
        # buffer format - only NV12 has distinct full / video range fourccs here:
        if self.src_format == "YUV420P":
            self.pixel_format = kCVPixelFormatType_420YpCbCr8Planar
        elif self.src_format == "NV12":
            self.pixel_format = kCVPixelFormatType_420YpCbCr8BiPlanarFullRange if self.full_range \
                else kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        else:
            self.pixel_format = kCVPixelFormatType_32BGRA

    cdef void reinit_encoder(self):
        # close and reopen the compression session so VideoToolbox regenerates the SPS with
        # the colour range derived from the (updated) input pixel buffer format; the next
        # encoded frame will be a fresh keyframe:
        cdef VTCompressionSessionRef session = self.session
        if session != NULL:
            self.session = NULL
            with nogil:
                VTCompressionSessionInvalidate(session)
                CFRelease(session)
        self.init_encoder(self.init_options)

    cdef OSStatus set_int_property(self, CFStringRef key, int value):
        cdef int32_t v = value
        cdef CFNumberRef num = CFNumberCreate(NULL, kCFNumberSInt32Type, &v)
        if num == NULL:
            return -1
        cdef OSStatus r = VTSessionSetProperty(self.session, key, num)
        CFRelease(num)
        if r != 0:
            log("failed to set VideoToolbox property to %i: error %i", value, r)
        return r

    def is_ready(self) -> bool:
        return bool(self.ready)

    def is_closed(self) -> bool:
        return not bool(self.ready)

    def clean(self) -> None:
        cdef VTCompressionSessionRef session = self.session
        if session != NULL:
            self.session = NULL
            with nogil:
                VTCompressionSessionInvalidate(session)
                CFRelease(session)
        self.ready = 0
        self.frames = 0
        self.width = 0
        self.height = 0
        self.min_qp = self.max_qp = -1
        self.content_types = ()
        self.profile = ""
        self.frame_data = None
        f = self.file
        if f:
            self.file = None
            f.close()

    def __dealloc__(self):
        self.clean()

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "encoding"      : self.encoding,
            "profile"       : self.profile,
            "src_format"    : self.src_format,
            "full-range"    : self.full_range,
            "quality"       : self.quality,
            "speed"         : self.speed,
            "qp-range"      : (self.min_qp, self.max_qp),
            "content-types" : self.content_types,
        }
        return info

    def __repr__(self):
        if not self.ready:
            return "vt_encoder(uninitialized)"
        return f"vt_encoder({self.encoding} - {self.width}x{self.height})"

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "vt"

    def get_src_format(self) -> str:
        return self.src_format

    cdef CVPixelBufferRef make_pixel_buffer(self, image: ImageWrapper):
        cdef unsigned int width = image.get_width()
        cdef unsigned int height = image.get_height()
        if width != self.width or height != self.height:
            raise ValueError(f"invalid image size {width}x{height}, expected {self.width}x{self.height}")
        pf = image.get_pixel_format()
        if pf != self.src_format:
            raise ValueError(f"expected {self.src_format} but got {pf}")

        cdef CVPixelBufferRef pixbuf = NULL
        cdef CVReturn r = 0
        with nogil:
            r = CVPixelBufferCreate(NULL, self.width, self.height, self.pixel_format, NULL, &pixbuf)
        if r != 0 or pixbuf == NULL:
            raise RuntimeError(f"failed to allocate CVPixelBuffer, error {r}")

        pixels = image.get_pixels()
        strides = image.get_rowstride()
        cdef int nplanes = COLORSPACES[self.src_format]

        # normalize to a list of (buffer, stride) per plane:
        if nplanes == 1:
            planes = [pixels]
            plane_strides = [strides]
        else:
            planes = list(pixels)
            plane_strides = list(strides)
        if len(planes) < nplanes:
            CFRelease(pixbuf)
            raise ValueError(f"expected {nplanes} planes but got {len(planes)}")

        cdef Py_buffer py_buf
        cdef void* dst
        cdef size_t dst_stride
        cdef size_t dst_rows
        cdef size_t src_stride
        cdef size_t copy_len
        cdef size_t y
        cdef int plane
        cdef uint8_t* src_ptr
        cdef uint8_t* dst_ptr

        CVPixelBufferLockBaseAddress(pixbuf, 0)
        try:
            for plane in range(nplanes):
                memset(&py_buf, 0, sizeof(Py_buffer))
                if PyObject_GetBuffer(planes[plane], &py_buf, PyBUF_ANY_CONTIGUOUS):
                    raise ValueError(f"failed to read pixel data from plane {plane}")
                try:
                    src_stride = plane_strides[plane]
                    if nplanes == 1:
                        dst = CVPixelBufferGetBaseAddress(pixbuf)
                        dst_stride = CVPixelBufferGetBytesPerRow(pixbuf)
                        dst_rows = self.height
                    else:
                        dst = CVPixelBufferGetBaseAddressOfPlane(pixbuf, plane)
                        dst_stride = CVPixelBufferGetBytesPerRowOfPlane(pixbuf, plane)
                        dst_rows = CVPixelBufferGetHeightOfPlane(pixbuf, plane)
                    copy_len = min(src_stride, dst_stride)
                    src_ptr = <uint8_t*> py_buf.buf
                    dst_ptr = <uint8_t*> dst
                    with nogil:
                        for y in range(dst_rows):
                            memcpy(dst_ptr + y * dst_stride, src_ptr + y * src_stride, copy_len)
                finally:
                    PyBuffer_Release(&py_buf)
        finally:
            CVPixelBufferUnlockBaseAddress(pixbuf, 0)
        return pixbuf

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple[bytes, Dict]:
        cdef double start = monotonic()
        # VideoToolbox derives the bitstream colour range from the input pixel buffer format,
        # which is fixed when the session is created - so on a range change we update the pixel
        # format and reopen the session to emit a fresh SPS (the next frame is then a keyframe):
        cdef int image_range = image.get_full_range()
        cdef int range_changed = image_range != self.full_range
        if range_changed:
            self.full_range = image_range
            if self.src_format == "NV12":
                self.set_pixel_format()
                self.reinit_encoder()
        # the server re-evaluates quality, speed and content-type for every frame:
        cdef int speed = options.intget("speed", self.speed)
        if speed != self.speed:
            self.speed = speed
            self.set_speed_priority()
        cdef int quality = options.intget("quality", self.quality)
        content_types = options.strtupleget("content-types", ()) or self.content_types
        if quality != self.quality or content_types != self.content_types:
            self.quality = quality
            self.content_types = content_types
            min_qp, max_qp = get_qp_range(quality, content_types)
            if max(abs(min_qp - self.min_qp), abs(max_qp - self.max_qp)) >= MIN_QP_DELTA:
                log("compress_image: quality=%i, content-types=%s: restarting the session"
                    " for qp range %i-%i (was %i-%i)",
                    quality, content_types, min_qp, max_qp, self.min_qp, self.max_qp)
                self.reinit_encoder()
        cdef CVPixelBufferRef pixbuf = self.make_pixel_buffer(image)

        self.frame_data = None
        self.frame_keyframe = 0
        self.frame_error = 0

        cdef CMTime pts = CMTimeMake(self.frames, 90000)
        cdef CMTime duration
        memset(&duration, 0, sizeof(CMTime))      # invalid duration
        cdef VTEncodeInfoFlags flags = 0
        cdef OSStatus r = 0
        try:
            with nogil:
                r = VTCompressionSessionEncodeFrame(self.session, pixbuf, pts, duration,
                                                    NULL, NULL, &flags)
                if r == 0:
                    # force synchronous completion so the callback fires before we return:
                    r = VTCompressionSessionCompleteFrames(self.session, pts)
        finally:
            CFRelease(pixbuf)
        if r != 0:
            raise RuntimeError(f"VideoToolbox failed to encode frame, error {r}")
        if self.frame_error:
            raise RuntimeError(f"VideoToolbox encode callback error {self.frame_error}")

        data = self.frame_data
        self.frame_data = None
        if not data:
            raise RuntimeError("VideoToolbox produced no compressed data")

        client_options = {
            "frame"         : int(self.frames),
            "csc"           : OUTPUT_COLORSPACE[self.src_format],
        }
        if BACKWARDS_COMPATIBLE or range_changed or (self.frames == 0 and not self.full_range):
            client_options["full-range"] = bool(self.full_range)
        if self.frame_keyframe:
            client_options["type"] = "IDR"
        if self.frames == 0:
            client_options["profile"] = self.profile
        self.frames += 1
        if self.file:
            self.file.write(data)
            self.file.flush()
        log("vt compress_image: %i bytes for frame %i in %.1fms",
            len(data), self.frames, 1000 * (monotonic() - start))
        return data, client_options

    # called from the VideoToolbox output thread (holding the GIL):
    cdef void process_output(self, OSStatus status, CMSampleBufferRef sampleBuffer):
        if status != 0:
            self.frame_error = status
            return
        if sampleBuffer == NULL:
            self.frame_error = -1
            return
        cdef int keyframe = self.is_keyframe(sampleBuffer)
        cdef CMBlockBufferRef bb = CMSampleBufferGetDataBuffer(sampleBuffer)
        if bb == NULL:
            self.frame_error = -2
            return
        cdef size_t total = 0
        cdef char* dataptr = NULL
        cdef OSStatus r = CMBlockBufferGetDataPointer(bb, 0, NULL, &total, &dataptr)
        if r != 0 or dataptr == NULL:
            self.frame_error = -3
            return

        # the start code that separates Annex-B NAL units:
        STARTCODE = b"\x00\x00\x00\x01"
        out = []
        if keyframe:
            out += self.get_parameter_sets(sampleBuffer, STARTCODE)

        # walk the AVCC buffer: [4-byte big-endian NAL length][NAL data] ...
        cdef size_t pos = 0
        cdef size_t nal_len = 0
        while pos + 4 <= total:
            nal_len = ((<uint8_t> dataptr[pos]) << 24) | ((<uint8_t> dataptr[pos + 1]) << 16) | \
                      ((<uint8_t> dataptr[pos + 2]) << 8) | (<uint8_t> dataptr[pos + 3])
            pos += 4
            if pos + nal_len > total:
                break
            out.append(STARTCODE + dataptr[pos:pos + nal_len])
            pos += nal_len

        self.frame_keyframe = keyframe
        self.frame_data = b"".join(out)

    cdef int is_keyframe(self, CMSampleBufferRef sampleBuffer):
        cdef CFArrayRef attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, 0)
        if attachments == NULL or CFArrayGetCount(attachments) == 0:
            # no attachments: assume sync sample (keyframe)
            return 1
        cdef CFDictionaryRef d = <CFDictionaryRef> CFArrayGetValueAtIndex(attachments, 0)
        if d == NULL:
            return 1
        # a sync sample (keyframe) is one that does NOT carry the "NotSync" attachment:
        return 0 if CFDictionaryContainsKey(d, <const void*> kCMSampleAttachmentKey_NotSync) else 1

    cdef list get_parameter_sets(self, CMSampleBufferRef sampleBuffer, bytes startcode):
        cdef CMFormatDescriptionRef fmt = CMSampleBufferGetFormatDescription(sampleBuffer)
        if fmt == NULL:
            return []
        cdef const uint8_t* ps_ptr = NULL
        cdef size_t ps_size = 0
        cdef size_t ps_count = 0
        cdef int nal_header_length = 0
        cdef OSStatus r
        cdef int hevc = (self.encoding == "h265")
        # query the first parameter set to discover how many there are:
        if hevc:
            r = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(fmt, 0, &ps_ptr, &ps_size,
                                                                   &ps_count, &nal_header_length)
        else:
            r = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(fmt, 0, &ps_ptr, &ps_size,
                                                                   &ps_count, &nal_header_length)
        if r != 0 or ps_count == 0:
            return []
        out = []
        cdef size_t i
        for i in range(ps_count):
            ps_ptr = NULL
            ps_size = 0
            if hevc:
                r = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(fmt, i, &ps_ptr, &ps_size,
                                                                       NULL, NULL)
            else:
                r = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(fmt, i, &ps_ptr, &ps_size,
                                                                       NULL, NULL)
            if r == 0 and ps_ptr != NULL and ps_size > 0:
                out.append(startcode + ps_ptr[:ps_size])
        return out


def selftest(full=False) -> None:
    log("vt selftest: %s", get_info())
    global SAVE_TO_FILE
    from xpra.codecs.checks import testencoder
    from xpra.codecs.vt import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = ""
        assert testencoder(encoder, full, typedict())
    finally:
        SAVE_TO_FILE = temp
