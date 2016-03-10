# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os

from xpra.log import Logger
log = Logger("encoder", "xvid")

from xpra.util import nonl
from xpra.os_util import bytestostr
from xpra.codecs.codec_constants import get_subsampling_divs, video_spec
from collections import deque

from libc.stdint cimport int64_t, uint64_t, uint8_t


cdef extern from "string.h":
    void * memset ( void * ptr, int value, size_t num )

cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "../../buffers/buffers.h":
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int get_buffer_api_version()

cdef extern from "xvid.h":
    int XVID_VERSION
    int XVID_API

    int XVID_ERR_FAIL       #general fault
    int XVID_ERR_MEMORY     #memory allocation error
    int XVID_ERR_FORMAT     #file format error
    int XVID_ERR_VERSION    #structure version not supported
    int XVID_ERR_END        #encoder only; end of stream reached

    int XVID_CSP_PLANAR     #4:2:0 planar (==I420, except for pointers/strides)
    int XVID_CSP_USER       #XVID_CSP_PLANAR
    int XVID_CSP_I420       #4:2:0 planar
    int XVID_CSP_YV12       #4:2:0 planar
    int XVID_CSP_YUY2       #4:2:2 packed
    int XVID_CSP_UYVY       #4:2:2 packed
    int XVID_CSP_YVYU       #4:2:2 packed
    int XVID_CSP_RGB        #24-bit rgb packed
    int XVID_CSP_BGRA       #32-bit bgra packed
    int XVID_CSP_ABGR       #32-bit abgr packed
    int XVID_CSP_RGBA       #32-bit rgba packed
    int XVID_CSP_ARGB       #32-bit argb packed
    int XVID_CSP_BGR        #24-bit bgr packed
    int XVID_CSP_RGB555     #16-bit rgb555 packed
    int XVID_CSP_RGB565     #16-bit rgb565 packed
    int XVID_CSP_SLICE      #decoder only: 4:2:0 planar, per slice rendering
    int XVID_CSP_INTERNAL   #decoder only: 4:2:0 planar, returns ptrs to internal buffers
    int XVID_CSP_NULL       #decoder only: dont output anything
    int XVID_CSP_VFLIP      #vertical flip mask

    int XVID_PROFILE_S_L0   #simple
    int XVID_PROFILE_S_L1
    int XVID_PROFILE_S_L2
    int XVID_PROFILE_S_L3
    int XVID_PROFILE_S_L4a
    int XVID_PROFILE_S_L5
    int XVID_PROFILE_S_L6
    int XVID_PROFILE_ARTS_L1    #advanced realtime simple
    int XVID_PROFILE_ARTS_L2
    int XVID_PROFILE_ARTS_L3
    int XVID_PROFILE_ARTS_L4
    int XVID_PROFILE_AS_L0      #advanced simple
    int XVID_PROFILE_AS_L1
    int XVID_PROFILE_AS_L2
    int XVID_PROFILE_AS_L3
    int XVID_PROFILE_AS_L4

    int XVID_GBL_INIT           #initialize xvidcore; must be called before using xvid_decore, or xvid_encore) */
    int XVID_GBL_INFO           #return some info about xvidcore, and the host computer */
    int XVID_GBL_CONVERT        #colorspace conversion utility

    int XVID_DEC_CREATE         #create decore instance; return 0 on success
    int XVID_DEC_DESTROY        #destroy decore instance: return 0 on success
    int XVID_DEC_DECODE         #decode a frame: returns number of bytes consumed >= 0

    int XVID_LOWDELAY           #lowdelay mode
    int XVID_DISCONTINUITY      #indicates break in stream
    int XVID_DEBLOCKY           #perform luma deblocking
    int XVID_DEBLOCKUV          #perform chroma deblocking
    int XVID_FILMEFFECT         #adds film grain
    int XVID_DERINGUV           #perform chroma deringing, requires deblocking to work
    int XVID_DERINGY            #perform luma deringing, requires deblocking to work

    int XVID_DEC_FAST           #disable postprocessing to decrease cpu usage *todo*
    int XVID_DEC_DROP           #drop bframes to decrease cpu usage *todo*
    int XVID_DEC_PREROLL        #decode as fast as you can, don't even show output *todo*

    int XVID_KEYFRAME

    #frame type flags */
    int XVID_TYPE_VOL           #decoder only: vol was decoded
    int XVID_TYPE_NOTHING       #decoder only (encoder stats): nothing was decoded/encoded */
    int XVID_TYPE_AUTO          #encoder: automatically determine coding type */
    int XVID_TYPE_IVOP          #intra frame
    int XVID_TYPE_PVOP          #predicted frame
    int XVID_TYPE_BVOP          #bidirectionally encoded
    int XVID_TYPE_SVOP          #predicted+sprite frame

    int XVID_PAR_11_VGA         #1:1 vga (square), default if supplied PAR is not a valid value
    int XVID_PAR_43_PAL         #4:3 pal (12:11 625-line)
    int XVID_PAR_43_NTSC        #4:3 ntsc (10:11 525-line)
    int XVID_PAR_169_PAL        #16:9 pal (16:11 625-line)
    int XVID_PAR_169_NTSC       #16:9 ntsc (40:33 525-line)
    int XVID_PAR_EXT            #extended par; use par_width, par_height

    int XVID_ME_FASTREFINE16
    int XVID_ME_FASTREFINE8
    int XVID_ME_SKIP_DELTASEARCH
    int XVID_ME_FAST_MODEINTERPOLATE
    int XVID_ME_BFRAME_EARLYSTOP

    ctypedef struct xvid_gbl_init_t:
        int version
        unsigned int cpu_flags      #[in:opt] zero = autodetect cpu; XVID_CPU_FORCE|{cpu features} = force cpu features
        int debug                   #[in:opt] debug level

    ctypedef struct xvid_enc_zone_t:
        pass
    ctypedef struct xvid_enc_plugin_t:
        pass

    ctypedef struct xvid_image_t:
        int csp             # colorspace; or with XVID_CSP_VFLIP to perform vertical flip
        void * plane[4]     #image plane ptrs
        int stride[4]       #image stride; "bytes per row"

    ctypedef struct xvid_enc_stats_t:
        int version

    ctypedef struct xvid_dec_create_t:
        int version
        int width               #image width
        int height              #image height
        void * handle           #decore context handle
        int fourcc              #fourcc of the input video
        int num_threads         #number of threads to use in decoder

    ctypedef struct xvid_enc_create_t:
        int version
        int profile             #[in] profile@level; refer to XVID_PROFILE_xxx
        int width               #[in] frame dimensions; width, pixel units
        int height              #[in] frame dimensions; height, pixel units
        int num_zones           #[in:opt] number of bitrate zones
        xvid_enc_zone_t * zones #zone array
        int num_plugins         #[in:opt] number of plugins
        xvid_enc_plugin_t * plugins     #plugin array
        int num_threads         #[in:opt] number of threads to use in encoder
        int max_bframes         #[in:opt] max sequential bframes (0=disable bframes)
        int _global             #in:opt] global flags; controls encoding behavior
        int fincr               #[in:opt] framerate increment; set to zero for variable framerate
        int fbase               #[in] framerate base frame_duration = fincr/fbase seconds
        int max_key_interval    #[in:opt] the maximum interval between key frames
        int frame_drop_ratio    #[in:opt] frame dropping: 0=drop none... 100=drop all
        int bquant_ratio        #[in:opt] bframe quantizer multipier/offeset; used to decide bframes quant when bquant==-1
        int bquant_offset       #bquant = (avg(past_ref_quant,future_ref_quant)*bquant_ratio + bquant_offset) / 100
        int min_quant[3]        #[in:opt]
        int max_quant[3]        #[in:opt]
        void *handle            #[out] encoder instance handle
        int start_frame_num     #[in:opt] frame number of start frame relative to zones definitions. allows to encode sub-sequences
        int num_slices          #[in:opt] number of slices to code for each frame

    ctypedef struct xvid_enc_frame_t:
        int version
        int vol_flags           #[in] vol flags
        unsigned char *quant_intra_matrix       #[in:opt] custom intra qmatrix
        unsigned char *quant_inter_matrix       #[in:opt] custom inter qmatrix
        int par                 #[in:opt] pixel aspect ratio (refer to XVID_PAR_xxx above)
        int par_width           #[in:opt] aspect ratio width
        int par_height          #[in:opt] aspect ratio height
        int fincr               #[in:opt] framerate increment, for variable framerate only
        int vop_flags           #[in] (general)vop-based flags
        int motion              #[in] ME options
        xvid_image_t input      #[in] input image (read from)
        int type                #[in:opt] coding type
        int quant               #[in] frame quantizer; if <=0, automatic (ratecontrol)
        int bframe_threshold
        void *bitstream         #[in:opt] bitstream ptr (written to)
        int length              #[in:opt] bitstream length (bytes)
        int out_flags           #[out] bitstream output flags

    # Quick API reference
    #
    # XVID_ENC_CREATE operation
    #  - handle: ignored
    #  - opt: XVID_ENC_CREATE
    #  - param1: address of a xvid_enc_create_t structure
    #  - param2: ignored
    #
    # XVID_ENC_ENCODE operation
    #  - handle: an instance returned by a CREATE op
    #  - opt: XVID_ENC_ENCODE
    #  - param1: address of a xvid_enc_frame_t structure
    #  - param2: address of a xvid_enc_stats_t structure (optional)
    #            its return value is asynchronous to what is written to the buffer
    #            depending on the delay introduced by bvop use. It's display
    #            ordered.
    #
    # XVID_ENC_DESTROY operation
    #  - handle: an instance returned by a CREATE op
    #  - opt: XVID_ENC_DESTROY
    #  - param1: ignored
    #  - param2: ignored
    #
    int XVID_ENC_CREATE
    int XVID_ENC_DESTROY
    int XVID_ENC_ENCODE

    int xvid_global(void *handle, int opt, void *param1, void *param2) nogil
    int xvid_decore(void *handle, int opt, void *param1, void *param2) nogil
    int xvid_encore(void *handle, int opt, void *param1, void *param2) nogil

    int XVID_VOP_HALFPEL
    int XVID_VOP_HQACPRED
    int XVID_VOP_DEBUG
    int XVID_VOP_MODEDECISION_RD


ERROR_TYPES = {
    XVID_ERR_FAIL       : "general fault",
    XVID_ERR_MEMORY     : "memory allocation error",
    XVID_ERR_FORMAT     : "file format error",
    XVID_ERR_VERSION    : "structure version not supported",
    XVID_ERR_END        : "encoder only; end of stream reached",
    }

def raise_xvid(info, int r):
    if r>=0:
        return
    raise Exception(info+": "+ERROR_TYPES.get(r, "unknown error %i" % r))


MAX_WIDTH = 4096
MAX_HEIGHT = 4096
#COLORSPACES = ["BGRX", "RGBX", "XRGB", "RGB", "BGR"]
COLORSPACES = ["YUV420P"]

def init_module():
    log("xvid.encoder.init_module()")
    cdef xvid_gbl_init_t init
    memset(&init, 0, sizeof(xvid_gbl_init_t))
    init.version = XVID_VERSION
    init.cpu_flags = 0
    cdef int r = xvid_global(NULL, XVID_GBL_INIT, &init, NULL)
    log("xvid_global XVID_BGL_INIT returned %i", r)
    assert r==0
    

def cleanup_module():
    log("xvid.encoder.cleanup_module()")

def get_version():
    def b(v):
        return v & 0xFF
    return b(XVID_VERSION>>16), b(XVID_VERSION)>>8, b(XVID_VERSION)

def get_type():
    return "xvid"

def get_info():
    global COLORSPACES, MAX_WIDTH, MAX_HEIGHT
    return {"version"   : get_version(),
            "buffer_api": get_buffer_api_version(),
            "max-size"  : (MAX_WIDTH, MAX_HEIGHT),
            "formats"   : COLORSPACES}

def get_encodings():
    return ["mpeg4"]

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return COLORSPACES

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in COLORSPACES
    return COLORSPACES


def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    return video_spec(encoding=encoding, output_colorspaces=COLORSPACES, has_lossless_mode=False,
                            codec_class=Encoder, codec_type=get_type(),
                            quality=50, speed=20,
                            setup_cost=20, width_mask=0xFFFE, height_mask=0xFFFE, max_w=MAX_WIDTH, max_h=MAX_HEIGHT)


cdef class Encoder:
    cdef unsigned long frames
    cdef void *context
    cdef int width
    cdef int height
    cdef int opencl
    cdef object src_format
    cdef double time
    cdef int quality
    cdef int speed
    cdef unsigned long long bytes_in
    cdef unsigned long long bytes_out

    cdef object __weakref__

    def init_context(self, int width, int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        global COLORSPACES
        assert src_format in COLORSPACES, "invalid source format: %s, must be one of: %s" % (src_format, COLORSPACES)
        assert encoding=="mpeg4", "invalid encoding: %s" % encoding
        assert scaling==(1,1), "xvid does not handle scaling"
        self.src_format = src_format
        self.width = width
        self.height = height
        self.quality = quality
        self.speed = speed
        self.frames = 0
        self.time = 0
        self.init_encoder()

    cdef init_encoder(self):
        cdef int r, i
        cdef xvid_enc_create_t create
        memset(&create, 0, sizeof(xvid_enc_create_t))
        create.version = XVID_VERSION
        create.width = self.width
        create.height = self.height
        create.profile = XVID_PROFILE_AS_L4
        #create.fincr = 1
        #create.fbase = 20
        #create.global = 0     #XVID_GLOBAL_EXTRASTATS_ENABLE
        create.max_bframes = 0
        create.bquant_ratio = 0
        create.bquant_offset = 0
        for i in range(3):
            create.min_quant[i] = 2
            create.min_quant[i] = 31
        create.max_key_interval = 2**31-1
        create.num_threads = 0
        #create.bquant_ratio = ARG_BQRATIO
        #create.bquant_offset = ARG_BQOFFSET        
        r = xvid_encore(NULL, XVID_ENC_CREATE, &create, NULL)
        raise_xvid("error creating context", r)
        self.context = create.handle
        log("xvid.init_encoder() context=%#x", <unsigned long> self.context)
        assert self.context!=NULL, "context handle is NULL!"

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            r = xvid_encore(self.context, XVID_ENC_DESTROY, NULL, NULL)
            if r<0:
                log.error("Error during encoder context cleanup: %s", ERROR_TYPES.get(r, r))
            self.context = NULL
        self.frames = 0
        self.width = 0
        self.height = 0
        self.src_format = ""
        self.time = 0
        self.quality = 0
        self.speed = 0


    def get_info(self):             #@DuplicatedSignature
        info = get_info()
        info.update({"frames"    : self.frames,
                     "width"     : self.width,
                     "height"    : self.height,
                     "speed"     : self.speed,
                     "quality"   : self.quality,
                     "src_format": self.src_format,
                     "version"   : get_version()})
        if self.frames>0 and self.time>0:
            pps = float(self.width) * float(self.height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __repr__(self):
        if self.src_format is None:
            return "xvid_encoder(uninitialized)"
        return "xvid_encoder(%s - %sx%s)" % (self.src_format, self.width, self.height)

    def is_closed(self):
        return self.context==NULL

    def get_encoding(self):
        return "mpeg4"

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):                     #@DuplicatedSignature
        return  "xvid"

    def get_src_format(self):
        return self.src_format

    def compress_image(self, image, int quality=-1, int speed=-1, options={}):
        cdef int frame_size = 0
        cdef uint8_t *pic_buf
        cdef Py_ssize_t pic_buf_len = 0
        cdef char *out
        cdef int i, r

        assert self.context!=NULL
        start = time.time()
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert pixels, "failed to get pixels from %s" % image
        log("compress_image(%s)", image)

        cdef xvid_enc_stats_t stats
        memset(&stats, 0, sizeof(xvid_enc_stats_t))
        stats.version = XVID_VERSION
        cdef xvid_enc_frame_t frame
        memset(&frame, 0, sizeof(xvid_enc_frame_t))
        frame.version = XVID_VERSION
        if self.src_format=="YUV420P":
            assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
            assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
            assert istrides[1]==istrides[2], "strides for U and V planes differ!"
            frame.input.csp = XVID_CSP_PLANAR
            for i in range(3):
                assert object_as_buffer(pixels[i], <const void**> &pic_buf, &pic_buf_len)==0, "unable to convert %s to a buffer (plane=%s)" % (type(pixels[i], i))
                frame.input.plane[i] = pic_buf
                frame.input.stride[i] = istrides[i]
                #log("plane %s at %#x with stride=%i", ["Y", "U", "V"][i], <unsigned long> pic_buf, istrides[i])
        else:
            if self.src_format in ("BGRX", "BGRA"):
                frame.input.csp = XVID_CSP_BGRA
            elif self.src_format in ("RGBX", "RGBA"):
                frame.input.csp = XVID_CSP_RGBA
            elif self.src_format in ("ARGB", "XRGB"):
                frame.input.csp = XVID_CSP_ARGB
            elif self.src_format=="RGB":
                frame.input.csp = XVID_CSP_RGB
            elif self.src_format=="BGR":
                frame.input.csp = XVID_CSP_BGR
            else:
                raise Exception("invalid source format %s" % self.src_format)
            assert object_as_buffer(pixels, <const void**> &pic_buf, &pic_buf_len)==0, "unable to convert %s to a buffer" % type(pixels)
            frame.input.plane[0] = pic_buf
            frame.input.stride[0] = istrides
            #log("BGRX data at %#x with stride=%i", <unsigned long> pic_buf, istrides)
        #frame.input.csp = XVID_CSP_NULL
        frame.par = XVID_PAR_11_VGA
        if self.frames>0:
            frame.type = XVID_TYPE_PVOP
        else:
            frame.type = XVID_TYPE_AUTO
        frame.vop_flags = XVID_VOP_HALFPEL | XVID_VOP_HQACPRED | XVID_VOP_DEBUG
        frame.vop_flags |= XVID_VOP_MODEDECISION_RD
        frame.motion = 0
        #fast:
        frame.motion = XVID_ME_FASTREFINE16 | XVID_ME_FASTREFINE8 | XVID_ME_SKIP_DELTASEARCH | XVID_ME_FAST_MODEINTERPOLATE | XVID_ME_BFRAME_EARLYSTOP
        cdef size_t l = self.width*self.height*3
        cdef char *bitstream = <char*> malloc(l)
        assert bitstream!=NULL, "failed to allocate output buffer"
        frame.bitstream = bitstream
        frame.length = l
        with nogil:
            r = xvid_encore(self.context, XVID_ENC_ENCODE, &frame, &stats)
        #log("encode returned %i", r)
        raise_xvid("frame encoding failed", r)
        log("mpeg4 frame size=%#x", r)
        cdata = (<char *> bitstream)[:r]
        free(bitstream)
        client_options = {
                "frame"     : self.frames
                #"quality"   : max(0, min(100, quality)),
                #"speed"     : max(0, min(100, speed)),
                }
        end = time.time()
        self.time += end-start
        self.frames += 1
        assert self.context!=NULL
        return  cdata, client_options


    def set_encoding_speed(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"

    def set_encoding_quality(self, int pct):
        assert pct>=0 and pct<=100, "invalid percentage: %s" % pct
        assert self.context!=NULL, "context is closed!"
        if self.quality==pct:
            return


def selftest(full=False):
    from xpra.codecs.codec_checks import testencoder, get_encoder_max_sizes
    from xpra.codecs.xvid import encoder
    init_module()
    assert testencoder(encoder, full)
    #this is expensive, so don't run it unless "full" is set:
    if full:
        global MAX_WIDTH, MAX_HEIGHT
        maxw, maxh = get_encoder_max_sizes(encoder)
        assert maxw>=MAX_WIDTH and maxh>=MAX_HEIGHT, "%s is limited to %ix%i and not %ix%i" % (encoder, maxw, maxh, MAX_WIDTH, MAX_HEIGHT)
        MAX_WIDTH, MAX_HEIGHT = maxw, maxh
        log.info("%s max dimensions: %ix%i", encoder, MAX_WIDTH, MAX_HEIGHT)
