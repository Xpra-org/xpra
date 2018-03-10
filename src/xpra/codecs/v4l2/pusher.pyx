# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True
from __future__ import absolute_import

import time
import os

from xpra.log import Logger
from _dbus_bindings import UInt32
log = Logger("webcam")

from xpra.os_util import path_permission_info
from xpra.util import nonl, print_nested_dict
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.buffers.membuf cimport memalign, object_as_buffer


from libc.stdint cimport uint32_t, uint8_t

cdef extern from "stdlib.h":
    void free(void* ptr)

cdef extern from "string.h":
    void *memcpy(void *destination, void *source, size_t num) nogil
    void *memset(void *ptr, int value, size_t num) nogil

cdef extern from "sys/ioctl.h":
    int ioctl(int fd, unsigned long request, ...)

include "constants.pxi"

cdef extern from "./video.h":
    #define v4l2_fourcc(a,b,c,d)\
    #    (((__u32)(a)<<0)|((__u32)(b)<<8)|((__u32)(c)<<16)|((__u32)(d)<<24))
    int v4l2_fourcc(unsigned char a, unsigned char b, unsigned char c, unsigned char d)

    IF ENABLE_DEVICE_CAPS:
        cdef struct v4l2_capability:
            uint8_t driver[16]
            uint8_t card[32]
            uint8_t bus_info[32]
            uint32_t version
            uint32_t capabilities
            uint32_t device_caps
            uint32_t reserved[3]
    ELSE:
        cdef struct v4l2_capability:        #redefined without device_caps!
            uint8_t driver[16]
            uint8_t card[32]
            uint8_t bus_info[32]
            uint32_t version
            uint32_t capabilities
            uint32_t reserved[3]

    cdef struct v4l2_pix_format:
        uint32_t width
        uint32_t height
        uint32_t pixelformat
        uint32_t field          # enum v4l2_field */
        uint32_t bytesperline   # for padding, zero if unused */
        uint32_t sizeimage
        uint32_t colorspace     # enum v4l2_colorspace */
        uint32_t priv           # private data, depends on pixelformat */
        uint32_t flags          # format flags (V4L2_PIX_FMT_FLAG_*) */
        #uint32_t ycbcr_enc      # enum v4l2_ycbcr_encoding */
        #uint32_t quantization   # enum v4l2_quantization */
        #uint32_t xfer_func      # enum v4l2_xfer_func */

    cdef struct v4l2_pix_format_mplane:
        pass
    cdef struct v4l2_window:
        pass
    cdef struct v4l2_vbi_format:
        pass
    cdef struct v4l2_sliced_vbi_format:
        pass
    cdef struct v4l2_sdr_format:
        pass

    cdef union v4l2_format_fmt:
        v4l2_pix_format          pix        #V4L2_BUF_TYPE_VIDEO_CAPTURE
        v4l2_pix_format_mplane   pix_mp     #V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        v4l2_window              win        #V4L2_BUF_TYPE_VIDEO_OVERLAY
        v4l2_vbi_format          vbi        #V4L2_BUF_TYPE_VBI_CAPTURE
        v4l2_sliced_vbi_format   sliced     #V4L2_BUF_TYPE_SLICED_VBI_CAPTURE
        v4l2_sdr_format          sdr        #V4L2_BUF_TYPE_SDR_CAPTURE
        uint8_t raw_data[200]               #user-defined

    cdef struct v4l2_format:
        uint32_t type
        v4l2_format_fmt fmt

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


#these fields are defined in the v4l2 headers,
#but they may not all be defined, and probably aren't on some platforms (ie: NetBSD)
#so we duplicate the definition here:
V4L2_CAP_VIDEO_CAPTURE          = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE   = 0x00001000
V4L2_CAP_VIDEO_OUTPUT           = 0x00000002
V4L2_CAP_VIDEO_OUTPUT_MPLANE    = 0x00002000
V4L2_CAP_VIDEO_M2M              = 0x00004000
V4L2_CAP_VIDEO_M2M_MPLANE       = 0x00008000
V4L2_CAP_VIDEO_OVERLAY          = 0x00000004
V4L2_CAP_VBI_CAPTURE            = 0x00000010
V4L2_CAP_VBI_OUTPUT             = 0x00000020
V4L2_CAP_SLICED_VBI_CAPTURE     = 0x00000040
V4L2_CAP_SLICED_VBI_OUTPUT      = 0x00000080
V4L2_CAP_RDS_CAPTURE            = 0x00000100
V4L2_CAP_VIDEO_OUTPUT_OVERLAY   = 0x00000200
V4L2_CAP_HW_FREQ_SEEK           = 0x00000400
V4L2_CAP_RDS_OUTPUT             = 0x00000800
V4L2_CAP_TUNER                  = 0x00010000
V4L2_CAP_AUDIO                  = 0x00020000
V4L2_CAP_RADIO                  = 0x00040000
V4L2_CAP_MODULATOR              = 0x00080000
V4L2_CAP_SDR_CAPTURE            = 0x00100000
V4L2_CAP_EXT_PIX_FORMAT         = 0x00200000
V4L2_CAP_SDR_OUTPUT             = 0x00400000
V4L2_CAP_READWRITE              = 0x01000000
V4L2_CAP_ASYNCIO                = 0x02000000
V4L2_CAP_STREAMING              = 0x04000000
V4L2_CAP_DEVICE_CAPS            = 0x80000000

V4L2_CAPS = {
             V4L2_CAP_VIDEO_CAPTURE         : "VIDEO_CAPTURE",
             V4L2_CAP_VIDEO_CAPTURE_MPLANE  : "VIDEO_CAPTURE_MPLANE",
             V4L2_CAP_VIDEO_OUTPUT          : "VIDEO_OUTPUT",
             V4L2_CAP_VIDEO_OUTPUT_MPLANE   : "VIDEO_OUTPUT_MPLANE",
             V4L2_CAP_VIDEO_M2M             : "VIDEO_M2M",
             V4L2_CAP_VIDEO_M2M_MPLANE      : "VIDEO_M2M_MPLANE",
             V4L2_CAP_VIDEO_OVERLAY         : "VIDEO_OVERLAY",
             V4L2_CAP_VBI_CAPTURE           : "VBI_CAPTURE",
             V4L2_CAP_VBI_OUTPUT            : "VBI_OUTPUT",
             V4L2_CAP_SLICED_VBI_CAPTURE    : "SLICED_VBI_CAPTURE",
             V4L2_CAP_SLICED_VBI_OUTPUT     : "SLICED_VBI_OUTPUT",
             V4L2_CAP_RDS_CAPTURE           : "RDS_CAPTURE",
             V4L2_CAP_VIDEO_OUTPUT_OVERLAY  : "VIDEO_OUTPUT_OVERLAY",
             V4L2_CAP_HW_FREQ_SEEK          : "HW_FREQ_SEEK",
             V4L2_CAP_RDS_OUTPUT            : "RDS_OUTPUT",
             V4L2_CAP_TUNER                 : "TUNER",
             V4L2_CAP_AUDIO                 : "AUDIO",
             V4L2_CAP_RADIO                 : "RADIO",
             V4L2_CAP_MODULATOR             : "MODULATOR",
             V4L2_CAP_SDR_CAPTURE           : "SDR_CAPTURE",
             V4L2_CAP_EXT_PIX_FORMAT        : "EXT_PIX_FORMAT",
             V4L2_CAP_SDR_OUTPUT            : "SDR_OUTPUT",
             V4L2_CAP_READWRITE             : "READWRITE",
             V4L2_CAP_ASYNCIO               : "ASYNCIO",
             V4L2_CAP_STREAMING             : "STREAMING",
             V4L2_CAP_DEVICE_CAPS           : "DEVICE_CAPS",
             }


FIELD_STR = {
    V4L2_FIELD_NONE                 : "None",
    V4L2_FIELD_TOP                  : "Top",
    V4L2_FIELD_BOTTOM               : "Bottom",
    V4L2_FIELD_INTERLACED           : "Interlaced",
    V4L2_FIELD_SEQ_TB               : "SEQ TB",
    V4L2_FIELD_SEQ_BT               : "SEQ BT",
    V4L2_FIELD_ALTERNATE            : "ALTERNATE",
    #V4L2_FIELD_INTERLACED_TB        : "INTERLACED TB",
    #V4L2_FIELD_INTERLACED_BT        : "INTERLACED BT",
}
COLORSPACE_STR = {
    V4L2_COLORSPACE_SRGB            : "SRGB",
    V4L2_COLORSPACE_470_SYSTEM_M    : "470_SYSTEM_M",
    V4L2_COLORSPACE_470_SYSTEM_BG   : "470_SYSTEM_BG",
    V4L2_COLORSPACE_SMPTE170M       : "SMPTE170M",
    V4L2_COLORSPACE_SMPTE240M       : "SMPTE240M",
    V4L2_COLORSPACE_REC709          : "REC709",
}

cdef int V4L2_PIX_FMT_H264 = v4l2_fourcc('H', '2', '6', '4')
cdef int V4L2_PIX_FMT_MPEG4 = v4l2_fourcc('M', 'P', 'G', '4')

FORMAT_STR = {
    V4L2_PIX_FMT_GREY           : "GREY",
    V4L2_PIX_FMT_YUV422P        : "YUV422P",
    V4L2_PIX_FMT_YUV420         : "YUV420P",
    V4L2_PIX_FMT_YVU420         : "YVU420P",
    V4L2_PIX_FMT_YUYV           : "YUYV",
    V4L2_PIX_FMT_UYVY           : "UYVY",
    V4L2_PIX_FMT_YUV410         : "YUV410P",
    V4L2_PIX_FMT_YUV411P        : "YUV411P",
    V4L2_PIX_FMT_BGR24          : "BGR",
    V4L2_PIX_FMT_RGB24          : "RGB",
    V4L2_PIX_FMT_BGR32          : "BGRX",
    V4L2_PIX_FMT_RGB32          : "RGBX",
    V4L2_PIX_FMT_NV12           : "NV12",
    V4L2_PIX_FMT_NV21           : "NV21",
    V4L2_PIX_FMT_H264           : "H264",
    V4L2_PIX_FMT_MPEG4          : "MPEG4",
}
PIX_FMT = {}
for k,v in FORMAT_STR.items():
    PIX_FMT[v] = k


log("v4l2.pusher init")
print_nested_dict({
                   "FIELD_STR"      : FIELD_STR,
                   "COLORSPACE_STR" : COLORSPACE_STR,
                   "FORMAT_STR"     : dict((hex(k),v) for k,v in FORMAT_STR.items()),
                   }, print_fn=log.debug)


def query_video_device(device="/dev/video0"):
    cdef v4l2_capability vid_caps
    try:
        log("v4l2 using device %s", device)
        with open(device, "wb") as f:
            r = ioctl(f.fileno(), VIDIOC_QUERYCAP, &vid_caps)
            log("ioctl(%s, VIDIOC_QUERYCAP, %#x)=%s", device, <unsigned long> &vid_caps, r)
            if r<0:
                return {}
            info = {
                    "driver"        : vid_caps.driver,
                    "card"          : vid_caps.card,
                    "bus_info"      : vid_caps.bus_info,
                    "version"       : vid_caps.version,
                    "capabilities"  : [v for k,v in V4L2_CAPS.items() if vid_caps.capabilities & k],
                    }
            IF ENABLE_DEVICE_CAPS:
                info["device_caps"] = [v for k,v in V4L2_CAPS.items() if vid_caps.device_caps & k]
            return dict((k,v) for k,v in info.items() if v)
    except Exception as e:
        log("query_video_device(%s)", device, exc_info=True)
        log.error("Error: failed to query device '%s':", device)
        log.error(" %s", e)
        for x in path_permission_info(device, "device"):
            log.error(" %s", x)
    return {}


def get_version():
    return 0

def get_type():
    return "v4l2"

def get_info():
    global COLORSPACES, MAX_WIDTH, MAX_HEIGHT
    return {
            "version"   : get_version(),
            }

def get_input_colorspaces():
    return  ["YUV420P"]     #,"YUV422P"


cdef class Pusher:
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int rowstride
    cdef size_t framesize
    cdef object src_format
    cdef object device
    cdef object device_name

    cdef object __weakref__

    def init_context(self, int width, int height, int rowstride, src_format, device):    #@DuplicatedSignature
        assert src_format in get_input_colorspaces(), "invalid source format '%s', must be one of %s" % (src_format, get_input_colorspaces())
        self.width = width
        self.height = height
        self.rowstride = rowstride
        self.src_format = src_format
        self.frames = 0
        self.init_device(device)

    cdef init_device(self, device):
        cdef v4l2_capability vid_caps
        cdef v4l2_format vid_format
        self.device_name = device or os.environ.get("XPRA_VIDEO_DEVICE", "/dev/video1")
        log("v4l2 using device %s", self.device_name)
        self.device = open(self.device_name, "wrb", 0)
        r = ioctl(self.device.fileno(), VIDIOC_QUERYCAP, &vid_caps)
        log("ioctl(%s, VIDIOC_QUERYCAP, %#x)=%s", self.device_name, <unsigned long> &vid_caps, r)
        assert r>=0, "VIDIOC_QUERYCAP ioctl failed on %s" % self.device_name
        memset(&vid_format, 0, sizeof(vid_format))
        r = ioctl(self.device.fileno(), VIDIOC_G_FMT, &vid_format)
        log("ioctl(%s, VIDIOC_G_FMT, %#x)=%s", self.device_name, <unsigned long> &vid_format, r)
        if r>=0:
            log("current device capture format:")
            self.show_vid_format(&vid_format)
        assert self.src_format in PIX_FMT, "unknown pixel format %s" % self.src_format
        cdef int pixel_format = PIX_FMT[self.src_format]
        divs = get_subsampling_divs(self.src_format)    #ie: YUV420P ->  (1, 1), (2, 2), (2, 2)
        self.framesize = 0
        for xdiv, ydiv in divs:
            self.framesize += self.rowstride//xdiv*(self.height//ydiv)
        vid_format.type = V4L2_BUF_TYPE_VIDEO_OUTPUT
        vid_format.fmt.pix.width = self.width
        vid_format.fmt.pix.height = self.height
        vid_format.fmt.pix.bytesperline = self.rowstride
        vid_format.fmt.pix.pixelformat = pixel_format
        vid_format.fmt.pix.sizeimage = self.framesize
        vid_format.fmt.pix.field = V4L2_FIELD_NONE
        #vid_format.fmt.pix.n_v4l_planes = 3
        vid_format.fmt.pix.colorspace = V4L2_COLORSPACE_SRGB
        #vid_format.fmt.pix.ycbcr_enc = V4L2_YCBCR_ENC_DEFAULT
        #vid_format.fmt.pix.quantization = V4L2_QUANTIZATION_DEFAULT
        #vid_format.fmt.pix.xfer_func = V4L2_XFER_FUNC_DEFAULT
        r = ioctl(self.device.fileno(), VIDIOC_S_FMT, &vid_format)
        log("ioctl(%s, VIDIOC_S_FMT, %#x)=%s", self.device_name, <unsigned long> &vid_format, r)
        assert r>=0, "VIDIOC_S_FMT ioctl failed on %s" % self.device_name
        self.show_vid_format(&vid_format)
        self.width = vid_format.fmt.pix.width
        self.height = vid_format.fmt.pix.height
        self.rowstride = vid_format.fmt.pix.bytesperline
        parsed_pixel_format = self.parse_pixel_format(&vid_format)
        log("parsed pixel format(%s)=%s", vid_format.fmt.pix.pixelformat, parsed_pixel_format)
        self.src_format = self.get_equiv_format(parsed_pixel_format)
        log("internal format(%s)=%s", parsed_pixel_format, self.src_format)
        #assert self.src_format in get_input_colorspaces(), "invalid pixel format used: %s" % self.src_format


    def get_equiv_format(self, fmt):
        return {"YU12" : "YUV420P", "YV12" : "YVU420P", "GREY" : "YUV420P"}.get(fmt, fmt)

    cdef parse_pixel_format(self, v4l2_format *vid_format):
        if vid_format.fmt.pix.pixelformat==0:
            return ""
        return "".join([chr((vid_format.fmt.pix.pixelformat//(2**(8*x))) % 256) for x in range(4)])

    cdef show_vid_format(self, v4l2_format *vid_format):
        log("vid_format.type                 = %i", vid_format.type)
        log("vid_format.fmt.pix.width        = %i", vid_format.fmt.pix.width)
        log("vid_format.fmt.pix.height       = %i", vid_format.fmt.pix.height)
        parsed_pixel_format = self.parse_pixel_format(vid_format)
        equiv = self.get_equiv_format(parsed_pixel_format)
        log("vid_format.fmt.pix.pixelformat  = %s = %s (for %#x)", parsed_pixel_format or "unset", equiv or "unset", vid_format.fmt.pix.pixelformat)
        log("vid_format.fmt.pix.sizeimage    = %i", vid_format.fmt.pix.sizeimage)
        log("vid_format.fmt.pix.field        = %s (%i)", FIELD_STR.get(vid_format.fmt.pix.field, vid_format.fmt.pix.field), vid_format.fmt.pix.field)
        log("vid_format.fmt.pix.bytesperline = %i", vid_format.fmt.pix.bytesperline)
        log("vid_format.fmt.pix.colorspace   = %s (%i)", COLORSPACE_STR.get(vid_format.fmt.pix.colorspace, vid_format.fmt.pix.colorspace), vid_format.fmt.pix.colorspace)
        #log("vid_format.fmt.pix.ycbcr_enc    = %s (%i)", YCBCR_ENC_STR.get(vid_format.fmt.pix.ycbcr_enc, vid_format.fmt.pix.ycbcr_enc), vid_format.fmt.pix.ycbcr_enc)
        #log("vid_format.fmt.pix.quantization = %s (%i)", QUANTIZATION_STR.get(vid_format.fmt.pix.quantization, vid_format.fmt.pix.quantization), vid_format.fmt.pix.quantization)
        #log("vid_format.fmt.pix.xfer_func    = %s (%i)", XFER_FUNC_STR.get(vid_format.fmt.pix.xfer_func, vid_format.fmt.pix.xfer_func), vid_format.fmt.pix.xfer_func)


    def clean(self):                        #@DuplicatedSignature
        self.width = 0
        self.height = 0
        self.rowstride = 0
        self.src_format = ""
        self.frames = 0
        self.framesize = 0
        d = self.device
        if d:
            self.device = None
            d.close()

    def get_info(self):             #@DuplicatedSignature
        info = get_info()
        info.update({
                     "frames"    : int(self.frames),
                     "width"     : self.width,
                     "height"    : self.height,
                     "src_format": self.src_format,
                     "device"    : self.device_name,
                     })
        return info

    def __repr__(self):
        if self.src_format is None:
            return "v4l2.Pusher(uninitialized)"
        return "v4l2.Pusher(%s:%s - %sx%s)" % (self.device_name, self.src_format, self.width, self.height)

    def is_closed(self):
        return not bool(self.src_format)

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):                     #@DuplicatedSignature
        return  "v4l2"

    def get_src_format(self):
        return self.src_format


    def push_image(self, image):
        cdef unsigned char *Ybuf
        cdef unsigned char *Ubuf
        cdef unsigned char *Vbuf
        cdef unsigned int Ystride, Ustride, Vstride
        cdef Py_ssize_t buf_len = 0

        divs = get_subsampling_divs(self.src_format)    #ie: YUV420P ->  (1, 1), (2, 2), (2, 2)
        cdef int Ywdiv = divs[0][0]
        cdef int Yhdiv = divs[0][1]
        cdef int Uwdiv = divs[1][0]
        cdef int Uhdiv = divs[1][1]
        cdef int Vwdiv = divs[2][0]
        cdef int Vhdiv = divs[2][1]

        iplanes = image.get_planes()
        assert iplanes==ImageWrapper._3_PLANES, "invalid input format: %s planes" % iplanes
        assert image.get_width()>=self.width, "invalid image width: %s (minimum is %s)" % (image.get_width(), self.width)
        assert image.get_height()>=self.height, "invalid image height: %s (minimum is %s)" % (image.get_height(), self.height)
        planes = image.get_pixels()
        assert planes, "failed to get pixels from %s" % image
        input_strides = image.get_rowstride()
        Ystride, Ustride, Vstride = input_strides
        assert Ystride==self.rowstride//Ywdiv, "invalid stride for Y plane: %s but expected %i" % (Ystride, self.rowstride//Ywdiv)
        assert Ustride==self.rowstride//Uwdiv, "invalid stride for U plane: %s but expected %s" % (Ustride, self.rowstride//Uwdiv)
        assert Vstride==self.rowstride//Vwdiv, "invalid stride for V plane: %s but expected %s" % (Vstride, self.rowstride//Vwdiv)
        assert object_as_buffer(planes[0], <const void**> &Ybuf, &buf_len)==0, "failed to convert %s to a buffer" % type(planes[0])
        assert buf_len>=Ystride*(image.get_height()//Yhdiv), "buffer for Y plane is too small: %s bytes, expected at least %s" % (buf_len, Ystride*(image.get_height()//Yhdiv))
        assert object_as_buffer(planes[1], <const void**> &Ubuf, &buf_len)==0, "failed to convert %s to a buffer" % type(planes[1])
        assert buf_len>=Ustride*(image.get_height()//Uhdiv), "buffer for U plane is too small: %s bytes, expected at least %s" % (buf_len, Ustride*(image.get_height()//Uhdiv))
        assert object_as_buffer(planes[2], <const void**> &Vbuf, &buf_len)==0, "failed to convert %s to a buffer" % type(planes[2])
        assert buf_len>=Vstride*(image.get_height()//Vhdiv), "buffer for V plane is too small: %s bytes, expected at least %s" % (buf_len, Vstride*(image.get_height()//Vhdiv))
        assert Ystride*(self.height//Yhdiv)+Ustride*(self.height//Uhdiv)+Vstride*(self.height//Vhdiv) <= self.framesize, "buffer %i is too small for %i + %i + %i" % (self.framesize, Ystride*(self.height//Yhdiv), Ustride*(self.height//Uhdiv), Vstride*(self.height//Vhdiv))

        cdef size_t l = self.framesize + self.rowstride
        cdef uint8_t* buf = <uint8_t*> memalign(l)
        assert buf!=NULL, "failed to allocate temporary output buffer"
        cdef size_t s
        cdef int i
        try:
            with nogil:
                memset(buf, 0, l)
                s = Ystride*(self.height//Yhdiv)
                memcpy(buf, Ybuf, s)
                i = s
                s = Ustride*(self.height//Uhdiv)
                memcpy(buf+i, Ubuf, s)
                i += s
                s = Vstride*(self.height//Vhdiv)
                memcpy(buf+i, Vbuf, s)
            self.device.write(buf[:self.framesize])
            self.device.flush()
        finally:
            free(buf)
