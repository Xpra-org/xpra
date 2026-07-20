# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import errno
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, check_image_size, MAX_IMAGE_DIMENSION
from xpra.util.objects import typedict
from xpra.common import SizedBuffer
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.log import Logger

log = Logger("decoder", "dav1d")

from libc.string cimport memset, memcpy
from libc.stdint cimport uint8_t, uint16_t, uint32_t, int64_t, uintptr_t
from xpra.buffers.membuf cimport memalign, memfree, getbuf, MemBuf, buffer_context  # pylint: disable=syntax-error


cdef unsigned char debug_enabled = log.is_debug_enabled()


cdef inline unsigned int roundup(unsigned int n, unsigned int m) noexcept nogil:
    return (n + m - 1) & ~(m - 1)


cdef int ENOMEM = errno.ENOMEM
cdef int EINVAL = errno.EINVAL

# upper bound for the frame dimensions we accept from the bitstream:
cdef int MAX_DIMENSION = MAX_IMAGE_DIMENSION


cdef extern from "stdarg.h":
    ctypedef struct va_list:
        pass


cdef extern from "string.h":
    int vsnprintf(char * s, size_t n, const char *fmt, va_list arg) nogil


cdef extern from "dav1d/version.h":
    int DAV1D_API_VERSION_MAJOR
    int DAV1D_API_VERSION_MINOR
    int DAV1D_API_VERSION_PATCH

cdef extern from "dav1d/common.h":
    ctypedef struct Dav1dUserData:
        const uint8_t *data         # data pointer
        Dav1dRef *ref

    ctypedef struct Dav1dDataProps:
        int64_t timestamp           # container timestamp of input data, INT64_MIN if unknown (default)
        int64_t duration            # container duration of input data, 0 if unknown (default)
        int64_t offset              # stream offset of input data, -1 if unknown (default)
        size_t size                 # packet size, default Dav1dData.sz
        Dav1dUserData user_data     # user-configur

cdef extern from "dav1d/headers.h":
    ctypedef enum Dav1dPixelLayout:
        DAV1D_PIXEL_LAYOUT_I400     # monochrome
        DAV1D_PIXEL_LAYOUT_I420     # 4:2:0 planar
        DAV1D_PIXEL_LAYOUT_I422     # 4:2:2 planar
        DAV1D_PIXEL_LAYOUT_I444     # 4:4:4 planar

    ctypedef enum Dav1dFrameType:
        DAV1D_FRAME_TYPE_KEY
        DAV1D_FRAME_TYPE_INTER
        DAV1D_FRAME_TYPE_INTRA
        DAV1D_FRAME_TYPE_SWITCH

    ctypedef enum Dav1dColorPrimaries:
        DAV1D_COLOR_PRI_BT709
        DAV1D_COLOR_PRI_UNKNOWN
        DAV1D_COLOR_PRI_BT470M
        DAV1D_COLOR_PRI_BT470BG
        DAV1D_COLOR_PRI_BT601
        DAV1D_COLOR_PRI_SMPTE240
        DAV1D_COLOR_PRI_FILM
        DAV1D_COLOR_PRI_BT2020
        DAV1D_COLOR_PRI_XYZ
        DAV1D_COLOR_PRI_SMPTE431
        DAV1D_COLOR_PRI_SMPTE432
        DAV1D_COLOR_PRI_EBU3213
        DAV1D_COLOR_PRI_RESERVED

    ctypedef enum Dav1dTransferCharacteristics:
        DAV1D_TRC_BT709
        DAV1D_TRC_UNKNOWN
        DAV1D_TRC_BT470M
        DAV1D_TRC_BT470BG
        DAV1D_TRC_BT601
        DAV1D_TRC_SMPTE240
        DAV1D_TRC_LINEAR
        DAV1D_TRC_LOG100
        DAV1D_TRC_LOG100_SQRT10
        DAV1D_TRC_IEC61966
        DAV1D_TRC_BT1361
        DAV1D_TRC_SRGB
        DAV1D_TRC_BT2020_10BIT
        DAV1D_TRC_BT2020_12BIT
        DAV1D_TRC_SMPTE2084
        DAV1D_TRC_SMPTE428
        DAV1D_TRC_HLG
        DAV1D_TRC_RESERVED

    ctypedef enum Dav1dMatrixCoefficients:
        DAV1D_MC_IDENTITY
        DAV1D_MC_BT709
        DAV1D_MC_UNKNOWN
        DAV1D_MC_FCC
        DAV1D_MC_BT470BG
        DAV1D_MC_BT601
        DAV1D_MC_SMPTE240
        DAV1D_MC_SMPTE_YCGCO
        DAV1D_MC_BT2020_NCL
        DAV1D_MC_BT2020_CL
        DAV1D_MC_SMPTE2085
        DAV1D_MC_CHROMAT_NCL
        DAV1D_MC_CHROMAT_CL
        DAV1D_MC_ICTCP
        DAV1D_MC_RESERVED

    ctypedef struct Dav1dSequenceHeader:
        uint8_t profile
        # etc..

    ctypedef struct Dav1dFrameHeader:
        pass

    ctypedef struct Dav1dContentLightLevel:
        uint16_t max_content_light_level
        uint16_t max_frame_average_light_level

    ctypedef struct Dav1dMasteringDisplay:
        uint16_t primaries[3][2]    # 0.16 fixed point
        uint16_t white_point[2]     # 0.16 fixed point
        uint32_t max_luminance      # 24.8 fixed point
        uint32_t min_luminance      # 18.14 fixed point

    ctypedef struct Dav1dITUTT35:
        uint8_t  country_code
        uint8_t  country_code_extension_byte
        size_t   payload_size
        uint8_t *payload


cdef extern from "dav1d/data.h":
    ctypedef struct Dav1dData:
        const uint8_t *data         # data pointer
        size_t sz                   # data size
        Dav1dRef *ref               # allocation origin
        Dav1dDataProps m            # user provided metadata passed to the output picture

    uint8_t * dav1d_data_create(Dav1dData *data, size_t sz)
    ctypedef void (*FREECALLBACK)(const uint8_t *buf, void *cookie)
    int dav1d_data_wrap(Dav1dData *data, const uint8_t *buf, size_t sz, FREECALLBACK, void *cookie)
    void dav1d_data_unref(Dav1dData *data)


cdef extern from "dav1d/picture.h":
    ctypedef int (*ALLOC_PICTURE_CALLBACK)(Dav1dPicture *pic, void *cookie)
    ctypedef void(*RELEASE_PICTURE_CALLBACK)(Dav1dPicture *pic, void *cookie)
    ctypedef struct Dav1dPicAllocator:
        void * 	cookie
        ALLOC_PICTURE_CALLBACK alloc_picture_callback
        RELEASE_PICTURE_CALLBACK release_picture_callback
    int DAV1D_PICTURE_ALIGNMENT

    ctypedef struct Dav1dPictureParameters:
        int w                       # width (in pixels)
        int h                       # height (in pixels)
        # `enum Dav1dPixelLayout` is not typedef'd in the dav1d headers,
        # so declare it as an int here to avoid emitting an invalid C type name:
        int layout                  # format of the picture
        int bpc                     # bits per pixel component (8 or 10)

    ctypedef struct Dav1dPicture:
        Dav1dSequenceHeader *seq_hdr
        Dav1dFrameHeader *frame_hdr

        void *data[3]
        ptrdiff_t stride[2]

        Dav1dPictureParameters p
        Dav1dDataProps m
        Dav1dContentLightLevel *content_light
        Dav1dMasteringDisplay *mastering_display
        Dav1dITUTT35 *itut_t35
        size_t n_itut_t35
        uintptr_t reserved[4]

        Dav1dRef *frame_hdr_ref
        Dav1dRef *seq_hdr_ref
        Dav1dRef *content_light_ref
        Dav1dRef *mastering_display_ref
        Dav1dRef *itut_t35_ref
        uintptr_t reserved_ref[4]
        Dav1dRef *ref               # Frame data allocation origin
        void *allocator_data

    void dav1d_picture_unref(Dav1dPicture *p)


cdef extern from "dav1d/dav1d.h":
    ctypedef struct Dav1dContext:
        pass
    ctypedef struct Dav1dRef:
        pass

    ctypedef void (*CALLBACK)(void* cookie, const char *format, va_list ap) noexcept nogil

    ctypedef struct Dav1dLogger:
        void *cookie
        CALLBACK callback

    ctypedef enum Dav1dInloopFilterType:
        DAV1D_INLOOPFILTER_NONE
        DAV1D_INLOOPFILTER_DEBLOCK
        DAV1D_INLOOPFILTER_CDEF
        DAV1D_INLOOPFILTER_RESTORATION
        DAV1D_INLOOPFILTER_ALL

    ctypedef enum Dav1dDecodeFrameType:
        DAV1D_DECODEFRAMETYPE_ALL
        DAV1D_DECODEFRAMETYPE_REFERENCE
        DAV1D_DECODEFRAMETYPE_INTRA
        DAV1D_DECODEFRAMETYPE_KEY

    ctypedef enum Dav1dEventFlags:
        DAV1D_EVENT_FLAG_NEW_SEQUENCE
        DAV1D_EVENT_FLAG_NEW_OP_PARAMS_INFO

    ctypedef struct Dav1dSettings:
        int n_threads                   #number of threads (0 = number of logical cores in host system, default 0)
        int max_frame_delay             #Set to 1 for low-latency decoding (0 = ceil(sqrt(n_threads)), default 0)
        int apply_grain                 #whether to apply film grain on output frames (default 1)
        int operating_point             #select an operating point for scalable AV1 bitstreams (0 - 31, default 0)
        int all_layers                  #output all spatial layers of a scalable AV1 biststream (default 1)
        unsigned frame_size_limit       #maximum frame size, in pixels (0 = unlimited, default 0)
        Dav1dPicAllocator allocator     #Picture allocator callback.
        Dav1dLogger logger              #Logger callback.
        int strict_std_compliance       #whether to abort decoding on standard compliance violations
        int output_invisible_frames     #output invisibly coded frames (in coding order) in addition
        Dav1dInloopFilterType inloop_filters    #postfilters to enable during decoding (default DAV1D_INLOOPFILTER_ALL)
        Dav1dDecodeFrameType decode_frame_type  #frame types to decode (default DAV1D_DECODEFRAMETYPE_ALL)
        uint8_t reserved[16]            #reserved for future use

    const char *dav1d_version()
    unsigned dav1d_version_api()

    void dav1d_default_settings(Dav1dSettings *s)
    int dav1d_open(Dav1dContext **c_out, const Dav1dSettings *s)
    int dav1d_parse_sequence_header(Dav1dSequenceHeader *out, const uint8_t *buf, const size_t sz)
    int dav1d_send_data(Dav1dContext *c, Dav1dData *input) nogil
    int dav1d_get_picture(Dav1dContext *c, Dav1dPicture *output) nogil
    int dav1d_apply_grain(Dav1dContext *c, Dav1dPicture *output, const Dav1dPicture *input)
    void dav1d_close(Dav1dContext **c_out)
    void dav1d_flush(Dav1dContext *c)
    int dav1d_get_event_flags(Dav1dContext *c, Dav1dEventFlags *flags)
    int dav1d_get_decode_error_data_props(Dav1dContext *c, Dav1dDataProps *output)
    int dav1d_get_frame_delay(const Dav1dSettings *s)



def get_version() -> Tuple[int, int, int]:
    return DAV1D_API_VERSION_MAJOR, DAV1D_API_VERSION_MINOR, DAV1D_API_VERSION_PATCH


def get_type() -> str:
    return "dav1d"


def get_info() -> Dict[str, Any]:
    return {
        "version"   : get_version(),
    }


def get_encodings() -> Sequence[str]:
    return ("av1", )


def get_min_size(encoding) -> Tuple[int, int]:
    return 32, 32


MAX_WIDTH, MAX_HEIGHT = (8192, 4096)


def get_specs() -> Sequence[VideoSpec]:
    return (
        VideoSpec(
            encoding="av1", input_colorspace="YUV420P", output_colorspaces=("YUV420P", ),
            has_lossless_mode=False,
            codec_class=Decoder, codec_type=get_type(),
            quality=40, speed=20,
            size_efficiency=40,
            setup_cost=0, width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
        ),
    )


cdef int picture_allocator(Dav1dPicture *pic, void *cookie) noexcept nogil:
    # dav1d requires the buffer to be sized from `pic.p` - the dimensions of the picture
    # dav1d is about to decode - and *not* from the dimensions we were configured with:
    # the two can differ, since a stream is free to change resolution.
    # The documented contract is that each plane is DAV1D_PICTURE_ALIGNMENT aligned,
    # covers a width and height rounded up to a multiple of 128 pixels,
    # and is padded by DAV1D_PICTURE_ALIGNMENT bytes.
    cdef int w = pic.p.w
    cdef int h = pic.p.h
    if w <= 0 or h <= 0 or w > MAX_DIMENSION or h > MAX_DIMENSION:
        return -EINVAL
    if pic.p.layout != DAV1D_PIXEL_LAYOUT_I420:
        return -EINVAL
    if pic.p.bpc != 8:
        return -EINVAL
    cdef size_t aligned_w = roundup(w, 128)
    cdef size_t aligned_h = roundup(h, 128)
    cdef size_t ystride = aligned_w
    cdef size_t uvstride = aligned_w // 2
    cdef size_t ysize = ystride * aligned_h
    cdef size_t uvsize = uvstride * (aligned_h // 2)
    cdef size_t pad = DAV1D_PICTURE_ALIGNMENT
    # one allocation for all three planes, so that a single pointer can be freed
    # by `release_picture` - each plane is followed by `pad` bytes of padding,
    # which also keeps the following plane aligned:
    cdef uintptr_t base = <uintptr_t> memalign(ysize + uvsize * 2 + pad * 3)
    if base == 0:
        return -ENOMEM
    pic.allocator_data = <void *> base
    pic.stride[0] = <ptrdiff_t> ystride
    pic.stride[1] = <ptrdiff_t> uvstride
    pic.data[0] = <void *> base
    pic.data[1] = <void *> (base + ysize + pad)
    pic.data[2] = <void *> (base + ysize + pad + uvsize + pad)
    if debug_enabled:
        with gil:
            log("picture_allocator(%#x, %#x) %ix%i ystride=%i, uvstride=%i, planes=%#x, %#x, %#x",
                <uintptr_t> pic, <uintptr_t> cookie, w, h, ystride, uvstride,
                <uintptr_t> pic.data[0], <uintptr_t> pic.data[1], <uintptr_t> pic.data[2])
    return 0


cdef void release_picture(Dav1dPicture *pic, void *cookie) noexcept nogil:
    if debug_enabled:
        with gil:
            log("release_picture(%#x, %#x) allocator_data=%#x",
                <uintptr_t> pic, <uintptr_t> cookie, <uintptr_t> pic.allocator_data)
    # dav1d only calls this once it has dropped all its own references to the picture
    # (it keeps them for as long as the frame is used for prediction),
    # so this is the only safe place to free the planes:
    if pic.allocator_data != NULL:
        memfree(pic.allocator_data)
        pic.allocator_data = NULL


cdef void logger_callback(void* cookie, const char *format, va_list arg) noexcept nogil:
    cdef char buf[256]
    cdef int r = vsnprintf(buf, 256, format, arg)
    if r < 0:
        with gil:
            log.error("dav1d_log: vsnprintf returned %s on format string '%s'", r, format)
        return
    cdef int length = r
    if length >= <int> sizeof(buf):
        length = <int> sizeof(buf) - 1
    with gil:
        pystr = buf[:length].decode("latin1").rstrip("\n\r")
        log.info("dav1d: %r", pystr)


cdef class Decoder:
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace
    cdef Dav1dContext *context

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("dav1d.init_context%s", (encoding, width, height, colorspace))
        if self.context != NULL:
            raise RuntimeError("decoder context is already initialized")
        assert encoding == "av1", f"invalid encoding: {encoding}"
        assert colorspace == "YUV420P", f"invalid colorspace: {colorspace}"
        check_image_size(width, height, "av1 decoder")
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.frames = 0
        cdef Dav1dSettings settings
        memset(&settings, 0, sizeof(Dav1dSettings))
        dav1d_default_settings(&settings)
        settings.n_threads = 0
        settings.max_frame_delay = 1
        settings.apply_grain = 0
        # The coded frame may include padding beyond the visible size (a
        # 1920x1080 stream is commonly coded as 1920x1088), so allow one AV1
        # superblock of padding while still bounding allocations from the stream.
        settings.frame_size_limit = roundup(width, 128) * roundup(height, 128)
        settings.allocator.cookie = <void *> NULL
        settings.allocator.alloc_picture_callback = &picture_allocator
        settings.allocator.release_picture_callback = &release_picture
        settings.logger.cookie = <void *> NULL
        settings.logger.callback = &logger_callback
        settings.strict_std_compliance = 0
        settings.output_invisible_frames = 0
        settings.inloop_filters = DAV1D_INLOOPFILTER_ALL
        settings.decode_frame_type = DAV1D_DECODEFRAMETYPE_ALL
        if dav1d_open(&self.context, &settings):
            raise RuntimeError("failed to open session")

    def get_encoding(self) -> str:
        return "av1"

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context == NULL

    def get_type(self) -> str:
        return "dav1d"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        log("dav1d close context %#x", <uintptr_t> self.context)
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""
        if self.context is not NULL:
            dav1d_close(&self.context)
            self.context = NULL

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "colorspace"    : self.colorspace,
        }
        return info

    def decompress_image(self, data: SizedBuffer, options: typedict) -> ImageWrapper:
        log("decompress_image(%i bytes, %s)", len(data), options)
        if self.context == NULL:
            raise RuntimeError("decoder is closed")
        if not data:
            raise ValueError("no AV1 data to decode")
        cdef Dav1dData input
        memset(&input, 0, sizeof(Dav1dData))
        cdef int r = 0
        cdef uint8_t *input_buf = NULL

        try:
            with buffer_context(data) as bc:
                input_buf = dav1d_data_create(&input, len(bc))
                if input_buf == NULL:
                    raise MemoryError("failed to allocate dav1d input buffer")
                memcpy(input_buf, <const void *> (<uintptr_t> int(bc)), len(bc))
            input.m.timestamp = 0
            input.m.duration = 0
            input.m.offset = -1
            input.m.size = input.sz
            input.m.user_data.data = NULL
            input.m.user_data.ref = NULL

            with nogil:
                r = dav1d_send_data(self.context, &input)
            log("dav1d_send_data: %i", r)
        finally:
            # dav1d advances or clears `input` after taking ownership of the
            # consumed bytes. Unref any remainder still owned by the caller.
            dav1d_data_unref(&input)
        if r:
            raise RuntimeError(f"failed to send data to decoder: {r}")

        cdef Dav1dPicture pic
        memset(&pic, 0, sizeof(Dav1dPicture))
        # Dav1dPictureParameters p
        # Dav1dRef *ref               # Frame data allocation origin
        # allocator_data
        with nogil:
            r = dav1d_get_picture(self.context, &pic)
        log("dav1d_get_picture: %i", r)
        if r:
            if r == -errno.EAGAIN:
                raise RuntimeError("decoder is waiting for more data: EAGAIN")
            raise RuntimeError(f"failed to get picture from decoder: {r}")

        # validate what the decoder produced before using it to size the planes below:
        # the dimensions come from the bitstream, so a hostile stream could otherwise
        # make us read past the buffers our allocator reserved for it
        cdef int pic_w = pic.p.w
        cdef int pic_h = pic.p.h
        cdef int layout = pic.p.layout
        cdef int bpc = pic.p.bpc
        cdef ptrdiff_t ystride = pic.stride[0]
        cdef ptrdiff_t uvstride = pic.stride[1]
        try:
            check_image_size(pic_w, pic_h, "av1 picture")
            if layout != DAV1D_PIXEL_LAYOUT_I420:
                raise ValueError(f"unsupported av1 pixel layout {layout}")
            if bpc != 8:
                raise ValueError(f"unsupported av1 bit depth {bpc}")
            if pic_w < self.width or pic_h < self.height:
                raise ValueError(f"av1 picture {pic_w}x{pic_h} is smaller than {self.width}x{self.height}")
            if pic.data[0] == NULL or pic.data[1] == NULL or pic.data[2] == NULL:
                raise ValueError("dav1d returned a picture with a missing plane")
            if ystride < pic_w or ystride > roundup(MAX_DIMENSION, 128):
                raise ValueError(f"invalid av1 luma stride {ystride} for width {pic_w}")
            if uvstride < (pic_w + 1) // 2 or uvstride > roundup(MAX_DIMENSION, 128):
                raise ValueError(f"invalid av1 chroma stride {uvstride} for width {pic_w}")
        except ValueError:
            dav1d_picture_unref(&pic)
            raise

        cdef size_t stride
        cdef size_t height
        cdef MemBuf plane
        pyplanes = []
        pystrides = []
        # copy the planes out: dav1d keeps its own references to the picture for as long
        # as it is used for prediction, and frees it via `release_picture` - so we must not
        # hand this memory to a `MemBuf` that would free it from under the decoder:
        try:
            for i in range(3):
                if i == 0:
                    stride = <size_t> ystride
                    height = <size_t> pic_h
                else:
                    stride = <size_t> uvstride
                    height = <size_t> (pic_h + 1) // 2
                plane = getbuf(stride * height, 0)
                memcpy(<void *> plane.get_mem(), <const void *> pic.data[i], stride * height)
                pystrides.append(stride)
                pyplanes.append(memoryview(plane))
        finally:
            dav1d_picture_unref(&pic)
        self.frames += 1
        return ImageWrapper(0, 0, self.width, self.height, pyplanes, "YUV420P", 24, pystrides, planes=PlanarFormat.PLANAR_3)


def selftest(full=False) -> None:
    log("dav1d selftest: %s", get_info())
    if log.is_debug_enabled():
        global debug_enabled
        debug_enabled = True
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.dav1d import decoder
    testdecoder(decoder, full)
