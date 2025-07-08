# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import errno
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.log import Logger

log = Logger("decoder", "dav1d")

from libcpp cimport bool as bool_t
from libc.string cimport memset
from libc.stdint cimport uint8_t, uint16_t, uint32_t, int64_t, uintptr_t
from xpra.buffers.membuf cimport memalign, memfree, makebuf, MemBuf, buffer_context  # pylint: disable=syntax-error


cdef unsigned char debug_enabled = log.is_debug_enabled()


cdef inline unsigned int roundup(unsigned int n, unsigned int m) noexcept nogil:
    return (n + m - 1) & ~(m - 1)


cdef unsigned int ENOMEM = errno.ENOMEM


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
    ctypedef struct Dav1dPictureParameters:
        pass

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
        void *callback

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
    return (DAV1D_API_VERSION_MAJOR, DAV1D_API_VERSION_MINOR, DAV1D_API_VERSION_PATCH)


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
    cdef AllocatorCookie *allocator_cookie = <AllocatorCookie *> cookie
    if debug_enabled:
        with gil:
            log("picture_allocator(%#x, %#x) ystride=%i, yheight=%i, uvstride=%i, uvheight=%i",
                <uintptr_t> pic, <uintptr_t> cookie,
                allocator_cookie.ystride, allocator_cookie.yheight,
                allocator_cookie.uvstride, allocator_cookie.uvheight)
    pic.stride[0] = allocator_cookie.ystride
    pic.stride[1] = allocator_cookie.uvstride
    pic.data[0] = <void *> memalign(allocator_cookie.ystride * allocator_cookie.yheight)
    if pic.data[0] is NULL:
        return -ENOMEM
    pic.data[1] = <void *> memalign(allocator_cookie.uvstride * allocator_cookie.uvheight)
    if pic.data[1] is NULL:
        return -ENOMEM
    pic.data[2] = <void *> memalign(allocator_cookie.uvstride * allocator_cookie.uvheight)
    if pic.data[2] is NULL:
        return -ENOMEM
    if debug_enabled:
        with gil:
            log("planes allocated: %#x, %#x, %#x",
                <uintptr_t> pic.data[0], <uintptr_t> pic.data[1], <uintptr_t> pic.data[2])
    return 0


cdef void release_picture(Dav1dPicture *pic, void *cookie) noexcept nogil:
    if debug_enabled:
        with gil:
            log("release_picture(%#x, %#x) planes=%#x, %#x, %#x",
                <uintptr_t> pic, <uintptr_t> cookie,
                <uintptr_t> pic.data[0], <uintptr_t> pic.data[1], <uintptr_t> pic.data[2])
    # memfree(pic.data[0])
    # memfree(pic.data[1])
    # memfree(pic.data[2])


cdef void logger_callback(void* cookie, const char *format, va_list arg) noexcept nogil:
    cdef char buf[256]
    cdef int r = vsnprintf(buf, 256, format, arg)
    if r < 0:
        with gil:
            log.error("dav1d_log: vsnprintf returned %s on format string '%s'", r, format)
        return
    with gil:
        pystr = buf[:r].decode("latin1").rstrip("\n\r")
        log.info("dav1d: %r", pystr)


ctypedef struct AllocatorCookie:
    unsigned int ystride
    unsigned int uvstride
    unsigned int yheight
    unsigned int uvheight


cdef class Decoder:
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace
    cdef Dav1dContext *context
    cdef AllocatorCookie allocator_cookie

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("dav1d.init_context%s", (encoding, width, height, colorspace))
        raise RuntimeError("dav1d decoder disabled due to crashes with some AV1 streams")
        assert encoding == "av1", f"invalid encoding: {encoding}"
        assert colorspace == "YUV420P", f"invalid colorspace: {colorspace}"
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
        self.allocator_cookie.ystride = roundup(width, 2)
        self.allocator_cookie.uvstride = roundup(self.allocator_cookie.ystride // 2, 2)
        self.allocator_cookie.yheight = roundup(height, 2)
        self.allocator_cookie.uvheight = roundup(height, 2) // 2
        settings.allocator.cookie = <void *> &self.allocator_cookie
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
        return bool(self.context != NULL)

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

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        log("decompress_image(%i bytes, %s)", len(data), options)
        cdef Dav1dData input
        memset(&input, 0, sizeof(Dav1dData))
        cdef int r = 0

        with buffer_context(data) as bc:
            input.data = <uint8_t*> (<uintptr_t> int(bc))
            input.sz = len(bc)
            input.ref = NULL
            input.m.timestamp = 0
            input.m.duration = 0
            input.m.offset = -1
            input.m.size = input.sz
            input.m.user_data.data = NULL
            input.m.user_data.ref = NULL

            with nogil:
                r = dav1d_send_data(self.context, &input)
        log("dav1d_send_data: %i", r)
        if r:
            dav1d_data_unref(&input)
            raise RuntimeError("failed to send data to decoder")

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
            raise RuntimeError("failed to get picture from decoder")

        pyplanes: list[int] = []
        pystrides = []
        cdef unsigned int stride
        cdef unsigned int height
        for i in range(3):
            if i == 0:
                stride = self.allocator_cookie.ystride
                height = self.allocator_cookie.yheight
            else:
                stride = self.allocator_cookie.uvstride
                height = self.allocator_cookie.uvheight
            pystrides.append(stride)
            pyplanes.append(makebuf(<void*> pic.data[i], stride * height, readonly=True))
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
