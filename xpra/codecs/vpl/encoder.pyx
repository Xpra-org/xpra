# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.log import Logger
log = Logger("encoder", "vpl")

from xpra.codecs.codec_constants import video_spec, get_subsampling_divs
from xpra.util import csv, typedict, AtomicInteger

from libc.stdint cimport uint8_t, uint16_t, uint32_t, uint64_t, int64_t
from libc.stdlib cimport free, malloc
from libc.string cimport memset


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "vpl/mfx.h":
    pass

ctypedef uint8_t mfxU8
ctypedef uint16_t mfxU16
ctypedef uint32_t mfxU32
ctypedef uint64_t mfxU64
ctypedef int64_t mfxI64

ctypedef int mfxStatus
ctypedef void * mfxExtBuffer
ctypedef void * mfxEncryptedData
ctypedef void * mfxPayload
ctypedef void * mfxFrameSurface1
ctypedef void * mfxSyncPoint

cdef extern from "vpl/mfxcommon.h":
    ctypedef struct mfxBitstream:
        mfxEncryptedData* EncryptedData     # Reserved and must be zero
        mfxExtBuffer **ExtParam             # Array of extended buffers for additional bitstream configuration. See the ExtendedBufferID enumerator for a complete list of extended buffers
        mfxU16  NumExtParam                 # The number of extended buffers attached to this structure
        mfxU32  CodecId                     # Specifies the codec format identifier in the FourCC code. See the CodecFormatFourCC enumerator for details. This optional parameter is required for the simplified decode initialization
        mfxU32  reserved[6]
        mfxI64  DecodeTimeStamp
        mfxU64  TimeStamp   # Time stamp of the compressed bitstream in units of 90KHz. A value of MFX_TIMESTAMP_UNKNOWN indicates that there is no time stamp
        mfxU8*  Data        # Bitstream buffer pointer, 32-bytes aligned
        mfxU32  DataOffset  # Next reading or writing position in the bitstream buffer
        mfxU32  DataLength  # Size of the actual bitstream data in bytes
        mfxU32  MaxLength   # Allocated bitstream buffer size in bytes
        mfxU16  PicStruct   # Type of the picture in the bitstream. Output parameter
        mfxU16  FrameType   # Frame type of the picture in the bitstream. Output parameter
        mfxU16  DataFlag    # Indicates additional bitstream properties. See the BitstreamDataFlag enumerator for details
        mfxU16  reserved2   # Reserved for future use

cdef extern from "mfxstructures.h":
    int MFX_IOPATTERN_IN_VIDEO_MEMORY   # Input to functions is a video memory surface
    int MFX_IOPATTERN_IN_SYSTEM_MEMORY  # Input to functions is a linear buffer directly in system memory or in system memory through an external allocator
    int MFX_IOPATTERN_OUT_VIDEO_MEMORY  # Output to functions is a video memory surface
    int MFX_IOPATTERN_OUT_SYSTEM_MEMORY # Output to functions is a linear buffer directly in system memory or in system memory through an external allocator

    int MFX_CODEC_AVC       # AVC, H.264, or MPEG-4, part 10 codec
    int MFX_CODEC_HEVC
    int MFX_CODEC_MPEG2
    int MFX_CODEC_VC1
    int MFX_CODEC_CAPTURE
    int MFX_CODEC_VP9
    int MFX_CODEC_AV1

    int MFX_FOURCC_I420
    int MFX_FOURCC_I422
    int MFX_FOURCC_NV12
    int MFX_FOURCC_RGBP
    int MFX_FOURCC_BGRP
    int MFX_FOURCC_RGB4         # RGB4 (RGB32) color planes. BGRA is the order, 'B' is 8 MSBs, then 8 bits for 'G' channel, then 'R' and 'A' channels
    int MFX_FOURCC_BGRA         # Alias for the RGB4 color format
    int MFX_FOURCC_P210         # 10 bit per sample 4:2:2 color format with similar to NV12 layout
    int MFX_FOURCC_BGR4         # RGBA color format. It is similar to MFX_FOURCC_RGB4 but with different order of channels. 'R' is 8 MSBs, then 8 bits for 'G' channel, then 'B' and 'A' channels
    int MFX_FOURCC_RGB565
    int MFX_FOURCC_A2RGB10      # 10 bits ARGB color format packed in 32 bits. 'A' channel is two MSBs, then 'R', then 'G' and then 'B' channels. This format should be mapped to DXGI_FORMAT_R10G10B10A2_UNORM or D3DFMT_A2R10G10B10
    int MFX_FOURCC_ARGB16       # 10 bits ARGB color format packed in 64 bits. 'A' channel is 16 MSBs, then 'R', then 'G' and then 'B' channels. This format should be mapped to DXGI_FORMAT_R16G16B16A16_UINT or D3DFMT_A16B16G16R16 formats
    int MFX_FOURCC_ABGR16       # 10 bits ABGR color format packed in 64 bits. 'A' channel is 16 MSBs, then 'B', then 'G' and then 'R' channels. This format should be mapped to DXGI_FORMAT_R16G16B16A16_UINT or D3DFMT_A16B16G16R16 formats

    int MFX_CHROMAFORMAT_YUV420
    int MFX_CHROMAFORMAT_YUV422
    int MFX_CHROMAFORMAT_YUV444
    int MFX_CHROMAFORMAT_YUV400

    int MFX_RATECONTROL_CBR     # Use the constant bitrate control algorithm
    int MFX_RATECONTROL_VBR     # Use the variable bitrate control algorithm
    int MFX_RATECONTROL_CQP     # Use the constant quantization parameter algorithm
    int MFX_RATECONTROL_AVBR    # Use the average variable bitrate control algorithm

    int MFX_TARGETUSAGE_1   # Best quality
    int MFX_TARGETUSAGE_2
    int MFX_TARGETUSAGE_3
    int MFX_TARGETUSAGE_4   # Balanced quality and speed
    int MFX_TARGETUSAGE_5
    int MFX_TARGETUSAGE_6
    int MFX_TARGETUSAGE_7   # Best speed
    int MFX_TARGETUSAGE_UNKNOWN         # Unspecified target usage
    int MFX_TARGETUSAGE_BEST_QUALITY    # Best quality
    int MFX_TARGETUSAGE_BALANCED        # Balanced quality and speed
    int MFX_TARGETUSAGE_BEST_SPEED      # Best speed

    ctypedef struct mfxEncodeCtrl:
        mfxExtBuffer    Header      # This extension buffer doesn't have assigned buffer ID. Ignored
        mfxU32  reserved[4]
        mfxU16  reserved1
        mfxU16  MfxNalUnitType
        mfxU16  SkipFrame           # Indicates that current frame should be skipped or the number of missed frames before the current frame. See mfxExtCodingOption2::SkipFrame for details
        mfxU16  QP                  # If nonzero, this value overwrites the global QP value for the current frame in the constant QP mode
        mfxU16  FrameType
        mfxU16  NumExtParam         # Number of extra control buffers
        mfxU16  NumPayload          # Number of payload records to insert into the bitstream
        mfxU16  reserved2
        mfxExtBuffer    **ExtParam
        mfxPayload      **Payload

    ctypedef struct mfxFrameId:
        mfxU16      TemporalId      # The temporal identifier as defined in the annex H of the ITU*-T H.264 specification
        mfxU16      PriorityId
        mfxU16      DependencyId
        mfxU16      QualityId
        mfxU16      ViewId          # The view identifier as defined in the annex H of the ITU-T H.264 specification

    ctypedef struct mfxFrameInfo:
        mfxU32  reserved[4]
        mfxU16  ChannelId   #The unique ID of each VPP channel set by application
        mfxU16  BitDepthLuma    #Number of bits used to represent luma samples
        mfxU16  BitDepthChroma  #Number of bits used to represent chroma samples
        mfxU16  Shift           #When the value is not zero, indicates that values of luma and chroma samples are shifted
        mfxFrameId FrameId      #Describes the view and layer of a frame picture.
        mfxU32  FourCC          #FourCC code of the color format. See the ColorFourCC enumerator for details
        mfxU16  Width           #Width of the video frame in pixels. Must be a multiple of 16
        mfxU16  Height          #Height of the video frame in pixels. Must be a multiple of 16 for progressive frame sequence and a multiple of 32 otherwise
        #ROI  The region of interest of the frame. Specify the display width and height in mfxVideoParam
        mfxU16  CropX
        mfxU16  CropY
        mfxU16  CropW
        mfxU16  CropH
        mfxU64 BufferSize       #Size of frame buffer in bytes. Valid only for plain formats (when FourCC is P8). In this case, Width, Height, and crop values are invalid
        mfxU32 reserved5
        mfxU32  FrameRateExtN   # Frame rate numerator
        mfxU32  FrameRateExtD   # Frame rate denominator
        mfxU16  reserved3
        mfxU16  AspectRatioW    # Aspect Ratio for width
        mfxU16  AspectRatioH    # Aspect Ratio for height
        mfxU16  PicStruct       # Picture type as specified in the PicStruct enumerator
        mfxU16  ChromaFormat    # Color sampling method. Value is the same as that of ChromaFormatIdc.
                                # ChromaFormat is not defined if FourCC is zero.*/
        mfxU16  reserved2

    ctypedef struct mfxInfoVPP:
        mfxU32  reserved[8]
        mfxFrameInfo    In      #Input format for video processing
        mfxFrameInfo    Out     #Output format for video processing

    ctypedef struct mfxInfoMFX:
        mfxU32  reserved[7]
        mfxU16  LowPower        #Hint to enable low power consumption mode for encoders
        mfxU16  BRCParamMultiplier #Specifies a multiplier for bitrate control parameters. Affects the following variables: InitialDelayInKB, BufferSizeInKB, TargetKbps, MaxKbps. If this value is not equal to zero, the encoder calculates BRC parameters as ``value * BRCParamMultiplier``
        mfxFrameInfo FrameInfo  #mfxFrameInfo structure that specifies frame parameters
        mfxU32  CodecId         #Specifies the codec format identifier in the FourCC code; see the CodecFormatFourCC enumerator for details
        mfxU16  CodecProfile    #Specifies the codec profile; see the CodecProfile enumerator for details. Specify the codec profile explicitly or the API functions will determine
                                #the correct profile from other sources, such as resolution and bitrate.
        mfxU16  CodecLevel      #Codec level; see the CodecLevel enumerator for details. Specify the codec level explicitly or the functions will determine the correct level from other sources,
                                #such as resolution and bitrate. */
        mfxU16  NumThread
        mfxU16  TargetUsage
        #mfxU16  GopPicSize
        #mfxU16  GopRefDist
        #mfxU16  GopOptFlag
        #mfxU16  IdrInterval
        mfxU16  RateControlMethod
        #mfxU16  InitialDelayInKB
        #mfxU16  QPI
        #mfxU16  Accuracy
        mfxU16  TargetKbps
        #mfxU16  QPP
        #mfxU16  ICQQuality
        mfxU16  MaxKbps
        #mfxU16  QPB
        #mfxU16  Convergence

    ctypedef struct mfxVideoParam:
        mfxU32  AllocId     #Unique component ID that will be passed by the library to mfxFrameAllocRequest. Useful in pipelines where several components of the same type share the same allocator. */
        mfxU32  reserved[2]
        mfxU16  reserved3
        mfxU16  AsyncDepth  #Specifies how many asynchronous operations an application performs before the application explicitly synchronizes the result. If zero, the value is not specified
        mfxInfoMFX  mfx     # Configurations related to encoding, decoding, and transcoding
        mfxInfoVPP  vpp     # Configurations related to video processing
        mfxU16  Protected   # Specifies the content protection mechanism
        #Input and output memory access types for functions. See the enumerator IOPattern for details
        #The Query API functions return the natively supported IOPattern if the Query input argument is NULL
        #This parameter is a mandated input for QueryIOSurf and Init API functions. The output pattern must be specified for DECODE.
        #The input pattern must be specified for ENCODE. Both input and output pattern must be specified for VPP.
        mfxU16  IOPattern
        mfxExtBuffer** ExtParam # The number of extra configuration structures attached to this structure.
        mfxU16  NumExtParam     # Points to an array of pointers to the extra configuration structures. See the ExtendedBufferID enumerator
                                # for a list of extended configurations.
        mfxU16  reserved2

    ctypedef struct mfxFrameAllocRequest:
        mfxU32  AllocId         # Unique (within the session) ID of component requested the allocation
        mfxU32  reserved[1]
        mfxU32  reserved3[3]
        mfxFrameInfo    Info    # Describes the properties of allocated frames
        mfxU16  Type            # Allocated memory type. See the ExtMemFrameType enumerator for details
        mfxU16  NumFrameMin     # Minimum number of allocated frames
        mfxU16  NumFrameSuggested   # Suggested number of allocated frames
        mfxU16  reserved2

cdef extern from "mfxdispatcher.h":
    ctypedef void * mfxLoader
    ctypedef void * mfxConfig
    ctypedef void * mfxSession
    ctypedef int mfxHDL
    ctypedef void * mfxVariant
    ctypedef int mfxImplCapsDeliveryFormat
    mfxLoader MFXLoad()
    void MFXUnload(mfxLoader loader)
    mfxConfig MFXCreateConfig(mfxLoader loader)
    mfxStatus MFXSetConfigFilterProperty(mfxConfig config, const mfxU8* name, mfxVariant value)
    mfxStatus MFXEnumImplementations(mfxLoader loader, mfxU32 i, mfxImplCapsDeliveryFormat format, mfxHDL* idesc)
    mfxStatus MFXCreateSession(mfxLoader loader, mfxU32 i, mfxSession* session)
    mfxStatus MFXDispReleaseImplDescription(mfxLoader loader, mfxHDL hdl)

cdef extern from "mfxvideo.h":
    mfxStatus MFXVideoENCODE_Query(mfxSession session, mfxVideoParam *invp, mfxVideoParam *outvp)
    mfxStatus MFXVideoENCODE_QueryIOSurf(mfxSession session, mfxVideoParam *par, mfxFrameAllocRequest *request)
    mfxStatus MFXVideoENCODE_Init(mfxSession session, mfxVideoParam *par)
    mfxStatus MFXVideoENCODE_EncodeFrameAsync(mfxSession session, mfxEncodeCtrl *ctrl, mfxFrameSurface1 *surface, mfxBitstream *bs, mfxSyncPoint *syncp)
    mfxStatus MFXVideoENCODE_Close(mfxSession session)
    mfxStatus MFXVideoENCODE_Reset(mfxSession session, mfxVideoParam *par)
    mfxStatus MFXMemory_GetSurfaceForEncode(mfxSession session, mfxFrameSurface1** surface)


SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

COLORSPACES = {}
COLORSPACES["h265"] = ("YUV420P", )
CODECS = tuple(COLORSPACES.keys())


def init_module():
    log("vpl.encoder.init_module() info=%s", get_info())
    assert CODECS, "no supported encodings!"
    log(f"supported codecs: {CODECS}")
    log(f"supported colorspaces: {COLORSPACES}")

def cleanup_module():
    log("vpl.encoder.cleanup_module()")

def get_version():
    return 0

def get_type():
    return "vpl"

def get_encodings():
    return CODECS

def get_input_colorspaces(encoding):
    assert encoding in get_encodings(), f"invalid encoding: {encoding}"
    return COLORSPACES[encoding]

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings(), f"invalid encoding: {encoding}"
    csoptions = COLORSPACES[encoding]
    assert input_colorspace in csoptions, f"invalid input colorspace: {input_colorspace}, {encoding} only supports "+csv(csoptions)
    #always unchanged in output:
    if input_colorspace=="YUV444P10":
        return ["r210",]
    return [input_colorspace]


generation = AtomicInteger()

def get_info():
    global CODECS, MAX_SIZE
    return {
        "version"       : get_version(),
        "encodings"     : CODECS,
        }


def get_spec(encoding, colorspace):
    assert encoding in CODECS, f"invalid encoding: {encoding}, must be one of "+csv(get_encodings())
    assert colorspace in get_input_colorspaces(encoding), f"invalid colorspace: {colorspace}, must be one of "+csv(get_input_colorspaces(encoding))
    #quality: we only handle YUV420P but this is already accounted for by the subsampling factor
    #setup cost is reasonable (usually about 5ms)
    global MAX_SIZE
    max_w, max_h = MAX_SIZE[encoding]
    has_lossless_mode = False
    speed = 50
    quality = 50
    return video_spec(encoding=encoding, input_colorspace=colorspace, output_colorspaces=[colorspace],
                      has_lossless_mode=has_lossless_mode,
                      codec_class=Encoder, codec_type=get_type(),
                      quality=quality, speed=speed,
                      size_efficiency=60,
                      setup_cost=20, max_w=max_w, max_h=max_h)


cdef class Encoder:
    cdef mfxLoader loader
    cdef mfxConfig config
    cdef mfxSession session
    cdef mfxVideoParam encodeParams
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object encoding
    cdef object src_format
    cdef int speed
    cdef int quality
    cdef unsigned int generation
    cdef object file

    cdef object __weakref__

    def init_context(self, encoding, unsigned int width, unsigned int height, src_format, options):
        log("vpl init_context%s", (encoding, width, height, src_format, options))
        assert encoding in COLORSPACES, f"invalid encoding: {encoding}"
        options = options or typedict()
        assert options.get("scaled-width", width)==width, "vpl encoder does not handle scaling"
        assert options.get("scaled-height", height)==height, "vpl encoder does not handle scaling"
        assert encoding in get_encodings()
        assert src_format in get_input_colorspaces(encoding)
        self.src_format = src_format
        self.encoding = encoding
        self.width = width
        self.height = height
        self.quality = options.intget("quality", 50)
        self.speed = options.intget("speed", 50)
        self.generation = generation.increase()
        self.loader = MFXLoad()
        if self.loader==NULL:
            raise RuntimeError("MFXLoad failed")
        self.config = MFXCreateConfig(self.loader)
        if self.config==NULL:
            raise RuntimeError("MFXCreateConfig failed")
        #MFXSetConfigFilterProperty(cfg[0], (mfxU8 *)"mfxImplDescription.Impl", implValue)
        cdef r = MFXCreateSession(self.loader, 0, &self.session)
        if r:
            raise RuntimeError("MFXCreateSession failed")
        self.show_implementation_info()
        self.set_encoder_params()
        r = MFXVideoENCODE_Init(self.session, &self.encodeParams)
        if r:
            raise RuntimeError("Encode init failed")
        cdef mfxFrameAllocRequest encRequest
        r = MFXVideoENCODE_QueryIOSurf(self.session, &self.encodeParams, &encRequest)
        if r:
            raise RuntimeError("QueryIOSurf failed")
        cdef mfxBitstream bitstream
        BITSTREAM_BUFFER_SIZE = 2000000
        bitstream.MaxLength = BITSTREAM_BUFFER_SIZE
        r = MFXVideoENCODE_EncodeFrameAsync(self.session, NULL, NULL, &bitstream, NULL)
        if r:
            raise RuntimeError("MFXVideoENCODE_EncodeFrameAsync failed")
        #bitstream.Data = (mfxU8 *)malloc(bitstream.MaxLength * sizeof(mfxU8))
        #AllocateExternalSystemMemorySurfacePool
        #cdef mfxEncodeCtrl ctrl
        #r = MFXVideoENCODE_EncodeFrameAsync(self.session, mfxEncodeCtrl *ctrl, mfxFrameSurface1 *surface, mfxBitstream *bs, mfxSyncPoint *syncp);
        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+f"vpl-{self.generation}.{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")

    def show_implementation_info(self):
        pass

    def set_encoder_params(self):
        cdef mfxInfoMFX * mfx = &self.encodeParams.mfx
        mfx.CodecId = MFX_CODEC_HEVC
        if self.speed>80:
            mfx.TargetUsage = MFX_TARGETUSAGE_7
        else:
            mfx.TargetUsage = MFX_TARGETUSAGE_BALANCED
        mfx.TargetKbps              = 4000  #4Mbps
        mfx.RateControlMethod       = MFX_RATECONTROL_VBR
        mfx.FrameInfo.FrameRateExtN = 30
        mfx.FrameInfo.FrameRateExtD = 1
        mfx.FrameInfo.FourCC = MFX_FOURCC_I420
        mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420
        mfx.FrameInfo.CropX        = 0
        mfx.FrameInfo.CropY        = 0
        mfx.FrameInfo.CropW        = self.width
        mfx.FrameInfo.CropH        = self.height
        mfx.FrameInfo.Width        = roundup(self.width, 16)
        mfx.FrameInfo.Height       = roundup(self.height, 16)
        self.encodeParams.IOPattern = MFX_IOPATTERN_IN_SYSTEM_MEMORY
        cdef mfxStatus r = MFXVideoENCODE_Query(self.session, &self.encodeParams, &self.encodeParams)
        if r:
            raise RuntimeError("Encode query failed")

    def is_ready(self):
        return True

    def __repr__(self):
        return f"vpl.Encoder({self.encoding})"

    def get_info(self) -> dict:
        info = get_info()
        info.update({
            "frames"    : int(self.frames),
            "width"     : self.width,
            "height"    : self.height,
            "speed"     : self.speed,
            "quality"   : self.quality,
            "generation" : self.generation,
            "encoding"  : self.encoding,
            "src_format": self.src_format,
            })
        return info

    def get_encoding(self):
        return self.encoding

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def is_closed(self):
        return self.width == 0

    def get_type(self):
        return "vpl"

    def get_src_format(self):
        return self.src_format

    def __dealloc__(self):
        self.clean()

    def clean(self):
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.src_format = ""
        f = self.file
        if f:
            self.file = None
            f.close()


    def compress_image(self, image, options=None):
        cdef uint8_t *pic_in[3]
        cdef int strides[3]
        pixels = image.get_pixels()
        istrides = image.get_rowstride()
        assert image.get_pixel_format()==self.src_format, "invalid input format %s, expected %s" % (image.get_pixel_format, self.src_format)
        assert image.get_width()==self.width, "invalid image width %s, expected %s" % (image.get_width(), self.width)
        assert image.get_height()==self.height, "invalid image height %s, expected %s" % (image.get_height(), self.height)
        assert pixels, "failed to get pixels from %s" % image
        assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
        assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
        cdef unsigned int Bpp = 1 + int(self.src_format.endswith("P10"))
        divs = get_subsampling_divs(self.src_format)

        cdef Py_buffer py_buf[3]
        for i in range(3):
            memset(&py_buf[i], 0, sizeof(Py_buffer))
        try:
            for i in range(3):
                xdiv, ydiv = divs[i]
                if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                    raise Exception("failed to read pixel data from %s" % type(pixels[i]))
                assert istrides[i]>=self.width*Bpp//xdiv, "invalid stride %i for width %i" % (istrides[i], self.width)
                assert py_buf[i].len>=istrides[i]*(self.height//ydiv), "invalid buffer length %i for plane %s, at least %i needed" % (
                    py_buf[i].len, "YUV"[i], istrides[i]*(self.height//ydiv))
                pic_in[i] = <uint8_t *> py_buf[i].buf
                strides[i] = istrides[i]
            return self.do_compress_image(pic_in, strides), {
                "csc"       : self.src_format,
                "frame"     : int(self.frames),
                #"quality"  : min(99+self.lossless, self.quality),
                #"speed"    : self.speed,
                }
        finally:
            for i in range(3):
                if py_buf[i].buf:
                    PyBuffer_Release(&py_buf[i])

    cdef do_compress_image(self, uint8_t *pic_in[3], int strides[3]):
        self.frames += 1
        return None


def selftest(full=False):
    global CODECS, SAVE_TO_FILE
    from xpra.codecs.codec_checks import testencoder
    from xpra.codecs.vpl import encoder
    temp = SAVE_TO_FILE
    try:
        SAVE_TO_FILE = None
        CODECS = testencoder(encoder, full)
    finally:
        SAVE_TO_FILE = temp
