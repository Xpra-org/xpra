# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

# Basic hardware video decoder using Apple's VideoToolbox framework.
# It is the counterpart of the VideoToolbox encoder (encoder.pyx).
# The xpra h264/h265 streams arrive in Annex-B format (start-code separated
# NAL units, with the parameter sets - SPS/PPS, plus VPS for h265 - prepended
# on keyframes). VideoToolbox wants the parameter sets supplied separately (as a
# CMVideoFormatDescription) and the picture NAL units in AVCC format (each NAL
# prefixed by a 4-byte big-endian length), so we split the stream here and
# rebuild it the way VideoToolbox expects.
# Decoded frames come back as NV12 CVPixelBuffers which we copy into a plain
# (CPU) ImageWrapper, like the other xpra video decoders.

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("decoder", "videotoolbox")

from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import VideoSpec, EncodingNotSupported
from xpra.common import SizedBuffer
from xpra.util.str_fn import csv
from xpra.util.objects import typedict

from libc.stdint cimport uint8_t, int32_t, uintptr_t
from libc.string cimport memcpy
from cpython.bytes cimport PyBytes_FromStringAndSize, PyBytes_AS_STRING

from xpra.buffers.membuf cimport buffer_context  # pylint: disable=syntax-error
from xpra.codecs.vt.vt cimport *  # noqa: F403 (shared CoreFoundation/CoreVideo/CoreMedia declarations + FourCC enum)


# decoder-specific declarations (the encoder does not need these):
cdef extern from "CoreFoundation/CoreFoundation.h":
    ctypedef struct CFDictionaryKeyCallBacks:
        pass
    ctypedef struct CFDictionaryValueCallBacks:
        pass
    const CFDictionaryKeyCallBacks kCFTypeDictionaryKeyCallBacks
    const CFDictionaryValueCallBacks kCFTypeDictionaryValueCallBacks
    CFDictionaryRef CFDictionaryCreate(CFAllocatorRef allocator, const void** keys, const void** values,
                                       CFIndex numValues, const CFDictionaryKeyCallBacks* keyCallBacks,
                                       const CFDictionaryValueCallBacks* valueCallBacks) nogil
    # "null" allocator: CoreMedia references the memory block without owning or freeing it
    CFAllocatorRef kCFAllocatorNull


cdef extern from "CoreVideo/CoreVideo.h":
    CFStringRef kCVPixelBufferPixelFormatTypeKey


cdef extern from "CoreMedia/CoreMedia.h":
    ctypedef unsigned int CMBlockBufferFlags
    ctypedef long CMItemCount
    OSStatus CMBlockBufferCreateWithMemoryBlock(CFAllocatorRef structureAllocator, void* memoryBlock,
                                                size_t blockLength, CFAllocatorRef blockAllocator,
                                                const void* customBlockSource,
                                                size_t offsetToData, size_t dataLength,
                                                CMBlockBufferFlags flags,
                                                CMBlockBufferRef* blockBufferOut) nogil
    OSStatus CMSampleBufferCreateReady(CFAllocatorRef allocator, CMBlockBufferRef dataBuffer,
                                       CMFormatDescriptionRef formatDescription,
                                       CMItemCount numSamples, CMItemCount numSampleTimingEntries,
                                       const void* sampleTimingArray,
                                       CMItemCount numSampleSizeEntries, const size_t* sampleSizeArray,
                                       CMSampleBufferRef* sampleBufferOut) nogil
    OSStatus CMVideoFormatDescriptionCreateFromH264ParameterSets(CFAllocatorRef allocator,
                                                                 size_t parameterSetCount,
                                                                 const uint8_t* const* parameterSetPointers,
                                                                 const size_t* parameterSetSizes,
                                                                 int NALUnitHeaderLength,
                                                                 CMFormatDescriptionRef* formatDescriptionOut) nogil
    OSStatus CMVideoFormatDescriptionCreateFromHEVCParameterSets(CFAllocatorRef allocator,
                                                                 size_t parameterSetCount,
                                                                 const uint8_t* const* parameterSetPointers,
                                                                 const size_t* parameterSetSizes,
                                                                 int NALUnitHeaderLength,
                                                                 CFDictionaryRef extensions,
                                                                 CMFormatDescriptionRef* formatDescriptionOut) nogil


cdef extern from "VideoToolbox/VideoToolbox.h":
    ctypedef void* VTDecompressionSessionRef
    ctypedef unsigned int VTDecodeFrameFlags
    ctypedef unsigned int VTDecodeInfoFlags
    ctypedef void (*VTDecompressionOutputCallback)(void* decompressionOutputRefCon,
                                                   void* sourceFrameRefCon,
                                                   OSStatus status,
                                                   VTDecodeInfoFlags infoFlags,
                                                   CVPixelBufferRef imageBuffer,
                                                   CMTime presentationTimeStamp,
                                                   CMTime presentationDuration) noexcept
    ctypedef struct VTDecompressionOutputCallbackRecord:
        VTDecompressionOutputCallback decompressionOutputCallback
        void* decompressionOutputRefCon
    OSStatus VTDecompressionSessionCreate(CFAllocatorRef allocator,
                                          CMFormatDescriptionRef videoFormatDescription,
                                          CFDictionaryRef videoDecoderSpecification,
                                          CFDictionaryRef destinationImageBufferAttributes,
                                          const VTDecompressionOutputCallbackRecord* outputCallback,
                                          VTDecompressionSessionRef* decompressionSessionOut) nogil
    OSStatus VTDecompressionSessionDecodeFrame(VTDecompressionSessionRef session,
                                               CMSampleBufferRef sampleBuffer,
                                               VTDecodeFrameFlags decodeFlags,
                                               void* sourceFrameRefCon,
                                               VTDecodeInfoFlags* infoFlagsOut) nogil
    OSStatus VTDecompressionSessionWaitForAsynchronousFrames(VTDecompressionSessionRef session) nogil
    Boolean VTDecompressionSessionCanAcceptFormatDescription(VTDecompressionSessionRef session,
                                                             CMFormatDescriptionRef newFormatDescription) nogil
    void VTDecompressionSessionInvalidate(VTDecompressionSessionRef session) nogil


# lock the pixel buffer read-only when copying the decoded planes out:
DEF kCVPixelBufferLock_ReadOnly = 0x00000001


def get_version() -> Tuple[int, int]:
    return (1, 0)


def get_type() -> str:
    return "vt"


def get_info() -> Dict[str, Any]:
    return {
        "version"       : get_version(),
        "encodings"     : get_encodings(),
        "colorspaces"   : COLORSPACES,
    }


def get_encodings() -> Sequence[str]:
    return tuple(CODEC_TYPES.keys())


def get_min_size(encoding) -> Tuple[int, int]:
    return 16, 16


# the input colorspaces we accept (what the encoder produced before encoding).
# We always output NV12.
COLORSPACES: Tuple[str, ...] = ("YUV420P", "NV12")

CODEC_TYPES: Dict[str, CMVideoCodecType] = {
    "h264"  : kCMVideoCodecType_H264,
    "h265"  : kCMVideoCodecType_HEVC,
}

# h264/h265 NAL unit types that carry parameter sets (handled via the format
# description rather than the picture sample buffer):
H264_PARAMETER_SETS = (7, 8)            # SPS, PPS
H265_PARAMETER_SETS = (32, 33, 34)      # VPS, SPS, PPS


# the VideoToolbox / CoreMedia OSStatus error codes this decoder can hit,
# so that log messages name the failure rather than showing a bare integer:
OSSTATUS_ERRORS: Dict[int, str] = {
    -12210: "kVTVideoDecoderAuthorizationErr",
    -12900: "kVTPropertyNotSupportedErr",
    -12902: "kVTParameterErr",
    -12903: "kVTInvalidSessionErr",
    -12904: "kVTAllocationFailedErr",
    -12906: "kVTCouldNotFindVideoDecoderErr",
    -12907: "kVTCouldNotCreateInstanceErr",
    -12909: "kVTVideoDecoderBadDataErr",
    -12910: "kVTVideoDecoderUnsupportedDataFormatErr",
    -12911: "kVTVideoDecoderMalfunctionErr",
    -12913: "kVTVideoDecoderNotAvailableNowErr",
    -12916: "kVTFormatDescriptionChangeNotSupportedErr",
    # CMBlockBuffer:
    -12700: "kCMBlockBufferStructureAllocationFailedErr",
    -12701: "kCMBlockBufferBlockAllocationFailedErr",
    -12702: "kCMBlockBufferBadCustomBlockSourceErr",
    -12703: "kCMBlockBufferBadOffsetParameterErr",
    -12704: "kCMBlockBufferBadLengthParameterErr",
    -12705: "kCMBlockBufferBadPointerParameterErr",
    -12706: "kCMBlockBufferEmptyBBufErr",
    -12707: "kCMBlockBufferUnallocatedBlockErr",
    -12708: "kCMBlockBufferInsufficientSpaceErr",
    # CMFormatDescription:
    -12710: "kCMFormatDescriptionError_InvalidParameter",
    -12711: "kCMFormatDescriptionError_AllocationFailed",
    -12712: "kCMFormatDescriptionError_ValueNotAvailable",
    # CMSampleBuffer:
    -12730: "kCMSampleBufferError_AllocationFailed",
    -12731: "kCMSampleBufferError_RequiredParameterMissing",
    -12743: "kCMSampleBufferError_InvalidMediaFormat",
}


def fourcc_str(code: int) -> str:
    if not code:
        return ""
    try:
        chars = bytes(((code >> 24) & 0xFF, (code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF))
        if all(32 <= c < 127 for c in chars):
            return chars.decode("ascii")
    except ValueError:
        pass
    return f"{code:#x}"


def osstatus_str(status: int) -> str:
    name = OSSTATUS_ERRORS.get(status)
    if name:
        return f"{status} ({name})"
    # positive statuses are often FourCC codes - render them if printable:
    if status > 0:
        fourcc = fourcc_str(status)
        if not fourcc.startswith("0x"):
            return f"{status} ({fourcc!r})"
    return str(status)


MAX_WIDTH, MAX_HEIGHT = (4096, 4096)


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    for encoding in get_encodings():
        for in_cs in COLORSPACES:
            specs.append(VideoSpec(
                encoding=encoding, input_colorspace=in_cs, output_colorspaces=("NV12", ),
                has_lossless_mode=False,
                codec_class=Decoder, codec_type=get_type(),
                # hardware decoder: fast, low cpu cost, runs on the GPU / media engine:
                quality=50, speed=100,
                size_efficiency=50,
                setup_cost=20, cpu_cost=10, gpu_cost=100,
                width_mask=0xFFFE, height_mask=0xFFFE,
                max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            ))
    return specs


cdef tuple split_annexb(const uint8_t* raw, Py_ssize_t n, bint hevc):
    """ split an Annex-B frame into parameter sets and a ready-to-decode AVCC buffer.

    `raw` points at the compressed frame (borrowed - valid only for the duration
    of the call). Returns `(param_sets, avcc)` where:
      - `param_sets` is a list of `bytes`, one per SPS/PPS (plus VPS for h265),
        used to (re)build the CMVideoFormatDescription on keyframes;
      - `avcc` is a single `bytes` holding the picture NAL units in AVCC layout
        (each prefixed by its 4-byte big-endian length), built in one pass so the
        picture data is copied exactly once.
    """
    param_set_types = H265_PARAMETER_SETS if hevc else H264_PARAMETER_SETS
    # locate every start code (3 or 4 bytes) and record (start_code_pos, body_offset):
    starts = []
    cdef Py_ssize_t i = 0
    while i + 3 <= n:
        if raw[i] == 0 and raw[i + 1] == 0:
            if raw[i + 2] == 1:
                starts.append((i, i + 3))
                i += 3
                continue
            if i + 4 <= n and raw[i + 2] == 0 and raw[i + 3] == 1:
                starts.append((i, i + 4))
                i += 4
                continue
        i += 1

    # classify each NAL: parameter sets are copied out (small, keyframe-only),
    # picture NALs are recorded and their AVCC size accumulated:
    param_sets = []
    cdef list picture = []      # (body_start, body_end) of each picture NAL
    cdef Py_ssize_t total = 0
    cdef Py_ssize_t count = len(starts)
    cdef Py_ssize_t idx, bs, be
    cdef int nal_type
    for idx in range(count):
        bs = starts[idx][1]
        be = starts[idx + 1][0] if idx + 1 < count else n
        if be <= bs:
            continue
        nal_type = ((raw[bs] >> 1) & 0x3F) if hevc else (raw[bs] & 0x1F)
        if nal_type in param_set_types:
            param_sets.append(raw[bs:be])
        else:
            picture.append((bs, be))
            total += 4 + (be - bs)

    # build the AVCC buffer in one shot (4-byte big-endian length prefix per NAL):
    cdef bytes avcc = PyBytes_FromStringAndSize(NULL, total)
    cdef uint8_t* dst = <uint8_t*> PyBytes_AS_STRING(avcc)
    cdef Py_ssize_t off = 0
    cdef Py_ssize_t blen
    for bs, be in picture:
        blen = be - bs
        dst[off + 0] = <uint8_t> ((blen >> 24) & 0xFF)
        dst[off + 1] = <uint8_t> ((blen >> 16) & 0xFF)
        dst[off + 2] = <uint8_t> ((blen >> 8) & 0xFF)
        dst[off + 3] = <uint8_t> (blen & 0xFF)
        memcpy(dst + off + 4, raw + bs, blen)
        off += 4 + blen
    return param_sets, avcc


# the decompression callback runs on a VideoToolbox internal thread:
# it acquires the GIL, retains the decoded image buffer and hands it to the
# Decoder instance (which copies it out once decoding has completed).
cdef void decoder_output_callback(void* decompressionOutputRefCon, void* sourceFrameRefCon,
                                  OSStatus status, VTDecodeInfoFlags infoFlags,
                                  CVPixelBufferRef imageBuffer,
                                  CMTime presentationTimeStamp, CMTime presentationDuration) noexcept with gil:
    cdef Decoder decoder = <Decoder> decompressionOutputRefCon
    decoder.process_output(status, imageBuffer)


cdef class Decoder:
    cdef VTDecompressionSessionRef session
    cdef CMFormatDescriptionRef format_desc
    cdef unsigned int width
    cdef unsigned int height
    cdef OSType pixel_format
    cdef object encoding
    cdef object colorspace
    cdef object param_sets
    cdef unsigned long frames
    cdef int full_range
    cdef uint8_t ready
    # set by the output callback for each decoded frame:
    cdef CVPixelBufferRef frame_image
    cdef int frame_error

    cdef object __weakref__

    def init_context(self, encoding: str, unsigned int width, unsigned int height, colorspace: str,
                     options: typedict) -> None:
        log("vt.init_context%s", (encoding, width, height, colorspace, options))
        if encoding not in CODEC_TYPES:
            raise ValueError(f"invalid encoding {encoding!r}, must be one of: {csv(CODEC_TYPES.keys())}")
        if colorspace not in COLORSPACES:
            raise ValueError(f"invalid colorspace {colorspace!r}, must be one of: {csv(COLORSPACES)}")
        self.encoding = encoding
        self.colorspace = colorspace
        self.param_sets = None
        self.width = width
        self.height = height
        self.frames = 0
        self.full_range = options.boolget("full-range", True)
        self.session = NULL
        self.format_desc = NULL
        self.frame_image = NULL
        # the session is created lazily on the first frame, once the parameter
        # sets needed to build the format description have arrived:
        self.ready = 1

    def is_ready(self) -> bool:
        return bool(self.ready)

    def is_closed(self) -> bool:
        return not bool(self.ready)

    cdef void free_session(self):
        cdef VTDecompressionSessionRef session = self.session
        if session != NULL:
            self.session = NULL
            with nogil:
                VTDecompressionSessionInvalidate(session)
                CFRelease(session)
        cdef CMFormatDescriptionRef fmt = self.format_desc
        if fmt != NULL:
            self.format_desc = NULL
            CFRelease(fmt)

    cdef void free_frame_image(self):
        cdef CVPixelBufferRef img = self.frame_image
        if img != NULL:
            self.frame_image = NULL
            CFRelease(img)

    def clean(self) -> None:
        self.free_frame_image()
        self.free_session()
        self.ready = 0
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.colorspace = ""
        self.param_sets = None

    def __dealloc__(self):
        self.clean()

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "encoding"      : self.encoding,
            "colorspace"    : self.colorspace,
            "full-range"    : bool(self.full_range),
            "pixel-format"  : fourcc_str(self.pixel_format),
            "session"       : self.session != NULL,
        }
        return info

    def __repr__(self):
        if not self.ready:
            return "vt_decoder(uninitialized)"
        return f"vt_decoder({self.encoding} - {self.width}x{self.height})"

    def get_encoding(self) -> str:
        return self.encoding

    def get_colorspace(self) -> str:
        return "NV12"

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "vt"

    cdef CMFormatDescriptionRef make_format_description(self, list param_sets) except NULL:
        # h264/h265 only ever carry a handful of parameter sets (VPS/SPS/PPS),
        # so a small fixed-size array on the stack avoids a per-keyframe malloc:
        cdef size_t count = len(param_sets)
        if count == 0:
            raise ValueError("no parameter sets to build a format description")
        if count > 16:
            raise ValueError(f"too many parameter sets: {count}")
        cdef const uint8_t* ptrs[16]
        cdef size_t sizes[16]
        cdef CMFormatDescriptionRef fmt = NULL
        cdef OSStatus r = 0
        cdef size_t i
        cdef bytes ps
        for i in range(count):
            ps = param_sets[i]
            ptrs[i] = <const uint8_t*> (<const char*> ps)
            sizes[i] = len(ps)
        if self.encoding == "h265":
            r = CMVideoFormatDescriptionCreateFromHEVCParameterSets(NULL, count, ptrs, sizes, 4, NULL, &fmt)
        else:
            r = CMVideoFormatDescriptionCreateFromH264ParameterSets(NULL, count, ptrs, sizes, 4, &fmt)
        if r != 0 or fmt == NULL:
            raise RuntimeError(f"failed to create {self.encoding} format description, error {osstatus_str(r)}")
        return fmt

    cdef void make_session(self):
        # destination attributes: ask VideoToolbox for NV12 output (so we always
        # know the layout), full or video range depending on the stream:
        cdef int32_t pf = kCVPixelFormatType_420YpCbCr8BiPlanarFullRange if self.full_range \
            else kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        self.pixel_format = pf
        cdef CFNumberRef num = CFNumberCreate(NULL, kCFNumberSInt32Type, &pf)
        if num == NULL:
            raise RuntimeError("failed to create pixel format number")
        cdef const void* keys[1]
        cdef const void* values[1]
        keys[0] = <const void*> kCVPixelBufferPixelFormatTypeKey
        values[0] = <const void*> num
        cdef CFDictionaryRef attrs = CFDictionaryCreate(NULL, keys, values, 1,
                                                        &kCFTypeDictionaryKeyCallBacks,
                                                        &kCFTypeDictionaryValueCallBacks)
        CFRelease(num)
        if attrs == NULL:
            raise RuntimeError("failed to create destination image buffer attributes")

        cdef VTDecompressionOutputCallbackRecord cb
        cb.decompressionOutputCallback = <VTDecompressionOutputCallback> decoder_output_callback
        cb.decompressionOutputRefCon = <void*> self
        cdef OSStatus r = 0
        with nogil:
            r = VTDecompressionSessionCreate(NULL, self.format_desc, NULL, attrs, &cb, &self.session)
        CFRelease(attrs)
        log("VTDecompressionSessionCreate()=%i session=%#x", r, <uintptr_t> self.session)
        if r != 0 or self.session == NULL:
            self.session = NULL
            raise RuntimeError(f"failed to create VideoToolbox decompression session, error {osstatus_str(r)}")

    cdef void update_format_description(self, list param_sets) except *:
        cdef CMFormatDescriptionRef new_fmt = self.make_format_description(param_sets)
        # if we already have a session, try to keep it: VideoToolbox can often
        # accept a new format description (same resolution / profile) without a
        # full session teardown:
        cdef CMFormatDescriptionRef old_fmt
        if self.session != NULL and VTDecompressionSessionCanAcceptFormatDescription(self.session, new_fmt):
            old_fmt = self.format_desc
            self.format_desc = new_fmt
            if old_fmt != NULL:
                CFRelease(old_fmt)
            log("vt: reused existing session with updated format description")
            return
        # otherwise rebuild from scratch (free_session also releases format_desc):
        self.free_session()
        self.format_desc = new_fmt
        self.make_session()

    def decompress_image(self, data: SizedBuffer, options: typedict) -> ImageWrapper:
        cdef double start = monotonic()
        if not self.ready:
            raise RuntimeError("decoder is closed")
        if "full-range" in options:
            self.full_range = options.boolget("full-range")

        # read the compressed frame straight from the input buffer (no copy) and,
        # in a single pass, split it into parameter sets and the AVCC picture data:
        cdef bint hevc = (self.encoding == "h265")
        cdef Py_ssize_t raw_len
        with buffer_context(data) as bc:
            raw_len = len(bc)
            param_sets, avcc = split_annexb(<const uint8_t*> (<uintptr_t> int(bc)), raw_len, hevc)

        # (re)build the format description and session when parameter sets arrive
        # (the encoder only sends them on keyframes). Most keyframes resend the
        # same SPS/PPS, so skip all VideoToolbox work when they are unchanged, and
        # otherwise keep the existing session if it can accept the new format
        # description - recreating a decompression session is expensive:
        if param_sets and param_sets != self.param_sets:
            self.update_format_description(param_sets)
            self.param_sets = param_sets
        if self.session == NULL:
            raise RuntimeError("no VideoToolbox session: first frame must be a keyframe with parameter sets")
        if not avcc:
            raise RuntimeError("no picture data in frame")

        image = self.do_decompress(avcc)

        self.frames += 1
        log("vt decompress_image: %i bytes -> %ix%i in %.1fms",
            raw_len, self.width, self.height, 1000 * (monotonic() - start))
        return image

    cdef object do_decompress(self, bytes avcc):
        cdef void* src = <void*> (<const char*> avcc)
        cdef size_t total = len(avcc)
        cdef CMBlockBufferRef bb = NULL
        cdef CMSampleBufferRef sample = NULL
        cdef size_t sample_size = total
        cdef VTDecodeInfoFlags flags = 0
        cdef OSStatus r = 0
        # reference the AVCC buffer in place (kCFAllocatorNull = don't copy/own/free it):
        # `avcc` stays alive for the whole call and the decode is synchronous
        # (WaitForAsynchronousFrames below), so VideoToolbox never sees freed memory.
        with nogil:
            r = CMBlockBufferCreateWithMemoryBlock(NULL, src, total, kCFAllocatorNull, NULL, 0, total,
                                                   0, &bb)
        if r != 0 or bb == NULL:
            raise RuntimeError(f"failed to create CMBlockBuffer, error {osstatus_str(r)}")
        try:
            with nogil:
                r = CMSampleBufferCreateReady(NULL, bb, self.format_desc, 1, 0, NULL, 1, &sample_size, &sample)
            if r != 0 or sample == NULL:
                raise RuntimeError(f"failed to create CMSampleBuffer, error {osstatus_str(r)}")
            try:
                self.free_frame_image()
                self.frame_error = 0
                with nogil:
                    r = VTDecompressionSessionDecodeFrame(self.session, sample, 0, NULL, &flags)
                    if r == 0:
                        # force synchronous completion so the callback fires before we return:
                        r = VTDecompressionSessionWaitForAsynchronousFrames(self.session)
            finally:
                CFRelease(sample)
        finally:
            CFRelease(bb)
        if r != 0:
            raise RuntimeError(f"VideoToolbox failed to decode frame, error {osstatus_str(r)}")
        if self.frame_error:
            raise RuntimeError(f"VideoToolbox decode callback error {osstatus_str(self.frame_error)}")
        if self.frame_image == NULL:
            raise RuntimeError("VideoToolbox produced no image")
        return self.copy_image()

    # called from the VideoToolbox output thread (holding the GIL):
    cdef void process_output(self, OSStatus status, CVPixelBufferRef imageBuffer):
        if status != 0:
            self.frame_error = status
            return
        if imageBuffer == NULL:
            self.frame_error = -1
            return
        CFRetain(<CFTypeRef> imageBuffer)
        self.frame_image = imageBuffer

    cdef object copy_image(self):
        cdef CVPixelBufferRef img = self.frame_image
        cdef size_t nplanes = 0
        cdef uint8_t* y_ptr
        cdef uint8_t* uv_ptr
        cdef size_t y_stride, uv_stride, y_height, uv_height
        cdef CVReturn lock = CVPixelBufferLockBaseAddress(img, kCVPixelBufferLock_ReadOnly)
        if lock != 0:
            self.free_frame_image()
            raise RuntimeError(f"failed to lock CVPixelBuffer, error {lock}")
        try:
            nplanes = CVPixelBufferGetPlaneCount(img)
            if nplanes != 2:
                raise RuntimeError(f"expected 2 planes (NV12) but got {nplanes}")
            y_ptr = <uint8_t*> CVPixelBufferGetBaseAddressOfPlane(img, 0)
            y_stride = CVPixelBufferGetBytesPerRowOfPlane(img, 0)
            y_height = CVPixelBufferGetHeightOfPlane(img, 0)
            uv_ptr = <uint8_t*> CVPixelBufferGetBaseAddressOfPlane(img, 1)
            uv_stride = CVPixelBufferGetBytesPerRowOfPlane(img, 1)
            uv_height = CVPixelBufferGetHeightOfPlane(img, 1)
            y_plane = y_ptr[:y_stride * y_height]
            uv_plane = uv_ptr[:uv_stride * uv_height]
        finally:
            CVPixelBufferUnlockBaseAddress(img, kCVPixelBufferLock_ReadOnly)
            self.free_frame_image()
        pixels = (y_plane, uv_plane)
        strides = (y_stride, uv_stride)
        return ImageWrapper(0, 0, self.width, self.height,
                            pixels, "NV12", 24, strides, 2,
                            ImageWrapper.PLANAR_2,
                            full_range=bool(self.full_range))


def selftest(full=False) -> None:
    log("vt decoder selftest: %s", get_info())
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.vt import decoder
    global CODEC_TYPES
    working = testdecoder(decoder, full)
    CODEC_TYPES = {k: v for k, v in CODEC_TYPES.items() if k in working}
