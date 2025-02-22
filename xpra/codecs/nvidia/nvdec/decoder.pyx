# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from libc.string cimport memset
from libc.stdint cimport uintptr_t
from libc.stdio cimport printf
from xpra.buffers.membuf cimport getbuf, buffer_context, MemBuf  # pylint: disable=syntax-error

from weakref import WeakValueDictionary
from typing import Any, Dict, Tuple
from collections.abc import Sequence
from threading import Event

from xpra.util.str_fn import csv
from xpra.util.objects import AtomicInteger, typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import VideoSpec
from xpra.codecs.nvidia.cuda.errors import cudacheck, get_error_name
from xpra.codecs.nvidia.cuda.context import get_default_device_context
from xpra.log import Logger
log = Logger("encoder", "nvdec")

#we can import pycuda safely here,
#because importing cuda/context will have imported it with the lock
from pycuda.driver import Memcpy2D, mem_alloc_pitch, memcpy_dtoh, Stream

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

ctypedef int CUresult
ctypedef void* CUstream
ctypedef void* CUcontext
ctypedef void* CUvideodecoder
ctypedef void* CUvideoctxlock

ctypedef void *CUvideoparser
ctypedef long long CUvideotimestamp


DEF CUDA_ERROR_INVALID_IMAGE = 200

ctypedef struct rect:
    short left
    short top
    short right
    short bottom

cdef extern from "nvcuvid.h":
    ctypedef enum CUvideopacketflags:
        CUVID_PKT_ENDOFSTREAM   #Set when this is the last packet for this stream
        CUVID_PKT_TIMESTAMP     #Timestamp is valid
        CUVID_PKT_DISCONTINUITY #Set when a discontinuity has to be signalled
        CUVID_PKT_ENDOFPICTURE  #Set when the packet contains exactly one frame or one field
        CUVID_PKT_NOTIFY_EOS    #If this flag is set along with CUVID_PKT_ENDOFSTREAM, an additional (dummy)
                                #display callback will be invoked with null value of CUVIDPARSERDISPINFO which

    ctypedef struct CUSEIMESSAGE:
        unsigned char sei_message_type  #OUT: SEI Message Type
        unsigned char reserved[3]
        unsigned int sei_message_size   #OUT: SEI Message Size
    ctypedef struct CUVIDSEIMESSAGEINFO:
        void *pSEIData                  #OUT: SEI Message Data
        CUSEIMESSAGE *pSEIMessage       #OUT: SEI Message Info
        unsigned int sei_message_count  #OUT: SEI Message Count
        unsigned int picIdx             #OUT: SEI Message Pic Index

    ctypedef struct av1:
        unsigned char  operating_points_cnt
        unsigned char  reserved24_bits[3]
        unsigned short operating_points_idc[32]

    ctypedef struct CUVIDOPERATINGPOINTINFO:
        cudaVideoCodec codec
        av1 av1
        unsigned char CodecReserved[1024]

    ctypedef struct frame_rate:
        #frame_rate
        unsigned int numerator
        unsigned int denominator

    ctypedef struct CUVIDEOFORMAT:
        cudaVideoCodec codec                    #OUT: Compression format
        frame_rate frame_rate
        unsigned char progressive_sequence      #OUT: 0=interlaced, 1=progressive
        unsigned char bit_depth_luma_minus8     #OUT: high bit depth luma
        unsigned char bit_depth_chroma_minus8   #OUT: high bit depth chroma
        unsigned char min_num_decode_surfaces   #OUT: Minimum number of decode surfaces to be allocated for correct
        unsigned int coded_width                #OUT: coded frame width in pixels
        unsigned int coded_height               #OUT: coded frame height in pixels
        rect display_area
        cudaVideoChromaFormat chroma_format     #OUT:  Chroma format
        unsigned int bitrate                    #OUT: video bitrate (bps, 0=unknown)
        #display_aspect_ratio: int x, int y

    ctypedef struct CUVIDPARSERDISPINFO:
        int picture_index           #OUT: Index of the current picture                                                         */
        int progressive_frame       #OUT: 1 if progressive frame; 0 otherwise                                                  */
        int top_field_first         #OUT: 1 if top field is displayed first; 0 otherwise                                       */
        int repeat_first_field      #OUT: Number of additional fields (1=ivtc, 2=frame doubling, 4=frame tripling,
                                    #-1=unpaired field)                                                                        */
        CUvideotimestamp timestamp  #OUT: Presentation time stamp

    ctypedef int (*PFNVIDSEQUENCECALLBACK)(void *, CUVIDEOFORMAT *) except 0
    ctypedef int (*PFNVIDDECODECALLBACK)(void *, CUVIDPICPARAMS *) except 0
    ctypedef int (*PFNVIDDISPLAYCALLBACK)(void *, CUVIDPARSERDISPINFO *) except 0
    ctypedef int (*PFNVIDOPPOINTCALLBACK)(void *, CUVIDOPERATINGPOINTINFO*) except 0
    ctypedef int (*PFNVIDSEIMSGCALLBACK)(void *, CUVIDSEIMESSAGEINFO *) except 0

    ctypedef struct CUVIDEOFORMATEX:
        pass
    ctypedef struct CUVIDPARSERPARAMS:
        cudaVideoCodec CodecType                #IN: cudaVideoCodec_XXX
        unsigned int ulMaxNumDecodeSurfaces     #IN: Max # of decode surfaces (parser will cycle through these)
        unsigned int ulClockRate                #IN: Timestamp units in Hz (0=default=10000000Hz)
        unsigned int ulErrorThreshold           #IN: % Error threshold (0-100) for calling pfnDecodePicture (100=always
                                                #IN: call pfnDecodePicture even if picture bitstream is fully corrupted)
        unsigned int ulMaxDisplayDelay          #IN: Max display queue delay (improves pipelining of decode with display)
                                                #0=no delay (recommended values: 2..4)
        unsigned int bAnnexb                    #IN: AV1 annexB stream
        unsigned int uReserved                  #Reserved for future use - set to zero
        unsigned int uReserved1[4]              #IN: Reserved for future use - set to 0
        void *pUserData                         #IN: User data for callbacks
        PFNVIDSEQUENCECALLBACK pfnSequenceCallback  #IN: Called before decoding frames and/or whenever there is a fmt change
        PFNVIDDECODECALLBACK pfnDecodePicture       #IN: Called when a picture is ready to be decoded (decode order)
        PFNVIDDISPLAYCALLBACK pfnDisplayPicture     #IN: Called whenever a picture is ready to be displayed (display order)
        PFNVIDOPPOINTCALLBACK pfnGetOperatingPoint  #IN: Called from AV1 sequence header to get operating point of a AV1
                                                    #scalable bitstream
        PFNVIDSEIMSGCALLBACK pfnGetSEIMsg       #IN: Called when all SEI messages are parsed for particular frame
        void *pvReserved2[5]                    #Reserved for future use - set to NULL
        CUVIDEOFORMATEX *pExtVideoInfo          #IN: [Optional] sequence header data from system layer
    CUresult cuvidCreateVideoParser(CUvideoparser *pObj, CUVIDPARSERPARAMS *pParams)
    #CUresult cuvidDestroyVideoSource(CUvideosource obj)
    CUresult cuvidDestroyVideoParser(CUvideoparser obj)

    ctypedef struct CUVIDSOURCEDATAPACKET:
        unsigned long flags             #IN: Combination of CUVID_PKT_XXX flags
        unsigned long payload_size      #IN: number of bytes in the payload (may be zero if EOS flag is set)
        const unsigned char *payload    #IN: Pointer to packet payload data (may be NULL if EOS flag is set)
        CUvideotimestamp timestamp      #IN: Presentation time stamp (10MHz clock), only valid if
                                        #CUVID_PKT_TIMESTAMP flag is set
    CUresult cuvidParseVideoData(CUvideoparser obj, CUVIDSOURCEDATAPACKET *pPacket) nogil


cdef extern from "cuviddec.h":
    ctypedef enum cudaVideoCodec:
        cudaVideoCodec_MPEG1
        cudaVideoCodec_MPEG2
        cudaVideoCodec_MPEG4
        cudaVideoCodec_VC1
        cudaVideoCodec_H264
        cudaVideoCodec_JPEG
        cudaVideoCodec_H264_SVC
        cudaVideoCodec_H264_MVC
        cudaVideoCodec_HEVC
        cudaVideoCodec_VP8
        cudaVideoCodec_VP9
        cudaVideoCodec_AV1
        cudaVideoCodec_NumCodecs
        #Uncompressed YUV
        cudaVideoCodec_YUV420       #Y,U,V (4:2:0)
        cudaVideoCodec_YV12         #Y,V,U (4:2:0)
        cudaVideoCodec_NV12         #Y,UV  (4:2:0)
        cudaVideoCodec_YUYV         #YUYV/YUY2 (4:2:2)
        cudaVideoCodec_UYVY         #UYVY (4:2:2)
    ctypedef enum cudaVideoChromaFormat:
        cudaVideoChromaFormat_Monochrome
        cudaVideoChromaFormat_420
        cudaVideoChromaFormat_422
        cudaVideoChromaFormat_444
    ctypedef enum cudaVideoCreateFlags:
        cudaVideoCreate_Default         #Default operation mode: use dedicated video engines
        cudaVideoCreate_PreferCUDA      #Use CUDA-based decoder (requires valid vidLock object for multi-threading)
        cudaVideoCreate_PreferDXVA      #Go through DXVA internally if possible (requires D3D9 interop)
        cudaVideoCreate_PreferCUVID     #Use dedicated video engines directly

    ctypedef enum cuvidDecodeStatus:
        cuvidDecodeStatus_Invalid           #Decode status is not valid
        cuvidDecodeStatus_InProgress        #Decode is in progress
        cuvidDecodeStatus_Success           #Decode is completed without any errors
        #// 3 to 7 enums are reserved for future use
        cuvidDecodeStatus_Error             #Decode is completed with an error (error is not concealed)
        cuvidDecodeStatus_Error_Concealed   #Decode is completed with an error and error is concealed

    ctypedef struct CUVIDDECODECAPS:
        cudaVideoCodec          eCodecType              #IN: cudaVideoCodec_XXX
        cudaVideoChromaFormat   eChromaFormat           #IN: cudaVideoChromaFormat_XXX
        unsigned int            nBitDepthMinus8         #IN: The Value "BitDepth minus 8"
        unsigned int            reserved1[3]            #Reserved for future use - set to zero

        unsigned char           bIsSupported            #OUT: 1 if codec supported, 0 if not supported
        unsigned char           nNumNVDECs              #OUT: Number of NVDECs that can support IN params
        unsigned short          nOutputFormatMask       #OUT: each bit represents corresponding cudaVideoSurfaceFormat enum
        unsigned int            nMaxWidth               #OUT: Max supported coded width in pixels
        unsigned int            nMaxHeight              #OUT: Max supported coded height in pixels
        unsigned int            nMaxMBCount             #OUT: Max supported macroblock count
                                                        #CodedWidth*CodedHeight/256 must be <= nMaxMBCount
        unsigned short          nMinWidth               #OUT: Min supported coded width in pixels
        unsigned short          nMinHeight              #OUT: Min supported coded height in pixels
        unsigned char           bIsHistogramSupported   #OUT: 1 if Y component histogram output is supported, 0 if not
                                                        #Note: histogram is computed on original picture data before
                                                        #any post-processing like scaling, cropping, etc. is applied
        unsigned char           nCounterBitDepth        #OUT: histogram counter bit depth
        unsigned short          nMaxHistogramBins       #OUT: Max number of histogram bins
        unsigned int            reserved3[10]           #Reserved for future use - set to zero

    ctypedef enum cudaVideoDeinterlaceMode:
        cudaVideoDeinterlaceMode_Weave      #Weave both fields (no deinterlacing)
        cudaVideoDeinterlaceMode_Bob        #Drop one field
        cudaVideoDeinterlaceMode_Adaptive   #Adaptive deinterlacing

    ctypedef enum cudaVideoSurfaceFormat:
        cudaVideoSurfaceFormat_NV12                     #Semi-Planar YUV [Y plane followed by interleaved UV plane]
        cudaVideoSurfaceFormat_P016                     #16 bit Semi-Planar YUV [Y plane followed by interleaved UV plane].
                                                        #Can be used for 10 bit(6LSB bits 0), 12 bit (4LSB bits 0)
        cudaVideoSurfaceFormat_YUV444                   #Planar YUV [Y plane followed by U and V planes]
        cudaVideoSurfaceFormat_YUV444_16Bit             #16 bit Planar YUV [Y plane followed by U and V planes].
                                                        #Can be used for 10 bit(6LSB bits 0), 12 bit (4LSB bits 0)
    ctypedef struct CUVIDDECODECREATEINFO:
        unsigned long ulWidth               #IN: Coded sequence width in pixels
        unsigned long ulHeight              #IN: Coded sequence height in pixels
        unsigned long ulNumDecodeSurfaces   #IN: Maximum number of internal decode surfaces
        cudaVideoCodec CodecType            #IN: cudaVideoCodec_XXX
        cudaVideoChromaFormat ChromaFormat  #IN: cudaVideoChromaFormat_XXX
        unsigned long ulCreationFlags       #IN: Decoder creation flags (cudaVideoCreateFlags_XXX)
        unsigned long bitDepthMinus8        #IN: The value "BitDepth minus 8"
        unsigned long ulIntraDecodeOnly     #IN: Set 1 only if video has all intra frames (default value is 0). This will
                                            #optimize video memory for Intra frames only decoding. The support is limited
                                            #to specific codecs - H264, HEVC, VP9, the flag will be ignored for codecs which
                                            #are not supported. However decoding might fail if the flag is enabled in case
                                            #of supported codecs for regular bit streams having P and/or B frames.
        unsigned long ulMaxWidth            #Coded sequence max width in pixels used with reconfigure Decoder
        unsigned long ulMaxHeight           #IN: Coded sequence max height in pixels used with reconfigure Decoder
        unsigned long Reserved1             #Reserved for future use - set to zero
        rect display_area
        cudaVideoSurfaceFormat OutputFormat         #IN: cudaVideoSurfaceFormat_XXX
        cudaVideoDeinterlaceMode DeinterlaceMode    #IN: cudaVideoDeinterlaceMode_XXX
        unsigned long ulTargetWidth                 #IN: Post-processed output width (Should be aligned to 2)
        unsigned long ulTargetHeight                #IN: Post-processed output height (Should be aligned to 2)
        unsigned long ulNumOutputSurfaces           #IN: Maximum number of output surfaces simultaneously mapped
        CUvideoctxlock vidLock                      #IN: If non-NULL, context lock used for synchronizing ownership of
                                                    #the cuda context. Needed for cudaVideoCreate_PreferCUDA decode
        rect target_rect
        unsigned long enableHistogram               #IN: enable histogram output, if supported
        unsigned long Reserved2[4]                  #Reserved for future use - set to zero

    ctypedef struct CUVIDH264PICPARAMS:
        int log2_max_frame_num_minus4
        int pic_order_cnt_type
        int log2_max_pic_order_cnt_lsb_minus4
        int delta_pic_order_always_zero_flag
        int frame_mbs_only_flag
        int direct_8x8_inference_flag
        int num_ref_frames                          #NOTE: shall meet level 4.1 restrictions
        unsigned char residual_colour_transform_flag;
        unsigned char bit_depth_luma_minus8         #Must be 0 (only 8-bit supported)
        unsigned char bit_depth_chroma_minus8       #Must be 0 (only 8-bit supported)
        unsigned char qpprime_y_zero_transform_bypass_flag
        # PPS
        int entropy_coding_mode_flag
        int pic_order_present_flag
        int num_ref_idx_l0_active_minus1
        int num_ref_idx_l1_active_minus1
        int weighted_pred_flag
        int weighted_bipred_idc
        int pic_init_qp_minus26
        int deblocking_filter_control_present_flag
        int redundant_pic_cnt_present_flag
        int transform_8x8_mode_flag
        int MbaffFrameFlag
        int constrained_intra_pred_flag
        int chroma_qp_index_offset
        int second_chroma_qp_index_offset
        int ref_pic_flag
        int frame_num
        int CurrFieldOrderCnt[2]
        # DPB
        #CUVIDH264DPBENTRY dpb[16];          // List of reference frames within the DPB
        # Quantization Matrices (raster-order)
        unsigned char WeightScale4x4[6][16]
        unsigned char WeightScale8x8[2][64]
        # FMO/ASO
        unsigned char fmo_aso_enable
        unsigned char num_slice_groups_minus1
        unsigned char slice_group_map_type
        signed char pic_init_qs_minus26
        unsigned int slice_group_change_rate_minus1
        #union
        #{
        #unsigned long long slice_group_map_addr;
        #const unsigned char *pMb2SliceGroupMap;
        #} fmo;
        unsigned int  Reserved[12]

    ctypedef union CUVIDCodecSpecific:
        CUVIDH264PICPARAMS  h264

    ctypedef struct CUVIDPICPARAMS:
        int PicWidthInMbs                           #IN: Coded frame size in macroblocks
        int FrameHeightInMbs                        #IN: Coded frame height in macroblocks
        int CurrPicIdx                              #IN: Output index of the current picture
        int field_pic_flag                          #IN: 0=frame picture, 1=field picture
        int bottom_field_flag                       #IN: 0=top field, 1=bottom field (ignored if field_pic_flag=0)
        int second_field                            #IN: Second field of a complementary field pair
        #Bitstream data
        unsigned int nBitstreamDataLen              #IN: Number of bytes in bitstream data buffer
        const unsigned char *pBitstreamData         #IN: Ptr to bitstream data for this picture (slice-layer)
        unsigned int nNumSlices                     #IN: Number of slices in this picture
        const unsigned int *pSliceDataOffsets       #IN: nNumSlices entries, contains offset of each slice within
                                                    #the bitstream data buffer
        int ref_pic_flag                            #IN: This picture is a reference picture
        int intra_pic_flag                          #IN: This picture is entirely intra coded
        unsigned int Reserved[30]                   #Reserved for future use
        #IN: Codec-specific data in union
        CUVIDCodecSpecific CodecSpecific

    ctypedef struct CUVIDPROCPARAMS:
        int progressive_frame                       #IN: Input is progressive (deinterlace_mode will be ignored)
        int second_field                            #IN: Output the second field (ignored if deinterlace mode is Weave)
        int top_field_first                         #IN: Input frame is top field first (1st field is top, 2nd field is bottom)
        int unpaired_field                          #IN: Input only contains one field (2nd field is invalid)
        #The fields below are used for raw YUV input
        unsigned int reserved_flags                 #Reserved for future use (set to zero)
        unsigned int reserved_zero                  #Reserved (set to zero)
        unsigned long long raw_input_dptr           #IN: Input CUdeviceptr for raw YUV extensions
        unsigned int raw_input_pitch                #IN: pitch in bytes of raw YUV input (should be aligned appropriately)
        unsigned int raw_input_format               #IN: Input YUV format (cudaVideoCodec_enum)
        unsigned long long raw_output_dptr          #IN: Output CUdeviceptr for raw YUV extensions
        unsigned int raw_output_pitch               #IN: pitch in bytes of raw YUV output (should be aligned appropriately)
        unsigned int Reserved1                      #Reserved for future use (set to zero)
        CUstream output_stream                      #IN: stream object used by cuvidMapVideoFrame
        unsigned int Reserved[46]                   #Reserved for future use (set to zero)
        unsigned long long *histogram_dptr          #OUT: Output CUdeviceptr for histogram extensions
        void *Reserved2[1]                          #Reserved for future use (set to zero)

    ctypedef struct CUVIDGETDECODESTATUS:
        cuvidDecodeStatus decodeStatus
        unsigned int reserved[31]
        void *pReserved[8]

    CUresult cuvidGetDecoderCaps(CUVIDDECODECAPS *pdc)
    CUresult cuvidCreateDecoder(CUvideodecoder *phDecoder, CUVIDDECODECREATEINFO *pdci)
    CUresult cuvidDestroyDecoder(CUvideodecoder hDecoder)
    CUresult cuvidDecodePicture(CUvideodecoder hDecoder, CUVIDPICPARAMS *pPicParams) nogil
    CUresult cuvidGetDecodeStatus(CUvideodecoder hDecoder, int nPicIdx, CUVIDGETDECODESTATUS* pDecodeStatus)

    #CUresult cuvidMapVideoFrame(CUvideodecoder hDecoder, int nPicIdx,
    #                            unsigned int *pDevPtr, unsigned int *pPitch,
    #                            CUVIDPROCPARAMS *pVPP)
    #CUresult CUDAAPI cuvidUnmapVideoFrame(CUvideodecoder hDecoder, unsigned int DevPtr)
    CUresult cuvidMapVideoFrame64(CUvideodecoder hDecoder, int nPicIdx, unsigned long long *pDevPtr,
                                             unsigned int *pPitch, CUVIDPROCPARAMS *pVPP)
    CUresult cuvidUnmapVideoFrame64(CUvideodecoder hDecoder, unsigned long long DevPtr)

    #we don't use threads, so no need for this:
    CUresult cuvidCtxLockCreate(CUvideoctxlock *pLock, CUcontext ctx)
    CUresult cuvidCtxLockDestroy(CUvideoctxlock lck)
    CUresult cuvidCtxLock(CUvideoctxlock lck, unsigned int reserved_flags)
    CUresult cuvidCtxUnlock(CUvideoctxlock lck, unsigned int reserved_flags)


DECODE_STATUS_STR: Dict[int, str] = {
    cuvidDecodeStatus_Invalid       : "invalid",
    cuvidDecodeStatus_InProgress    : "in-progress",
    cuvidDecodeStatus_Success       : "success",
    cuvidDecodeStatus_Error         : "error",
    cuvidDecodeStatus_Error_Concealed : "error-concealed",
}

CODEC_NAMES: Dict[int, str] = {
#    cudaVideoCodec_MPEG1    : "mpeg1",
#    cudaVideoCodec_MPEG2    : "mpeg2",
    cudaVideoCodec_MPEG4    : "mpeg4",
    cudaVideoCodec_VC1      : "vc1",
    cudaVideoCodec_H264     : "h264",
    cudaVideoCodec_JPEG     : "jpeg",
    cudaVideoCodec_H264_SVC : "h264-svc",
    cudaVideoCodec_H264_MVC : "h264-mvc",
    cudaVideoCodec_HEVC     : "hevc",
    cudaVideoCodec_VP8      : "vp8",
    cudaVideoCodec_VP9      : "vp9",
    cudaVideoCodec_AV1      : "av1",
}

CHROMA_NAMES: Dict[int, str] = {
    cudaVideoChromaFormat_Monochrome    : "monochrome",
    cudaVideoChromaFormat_420           : "420",
    cudaVideoChromaFormat_422           : "422",
    cudaVideoChromaFormat_444           : "444",
}

SURFACE_NAMES: Dict[int, str] = {
    cudaVideoSurfaceFormat_NV12     : "NV12",
    cudaVideoSurfaceFormat_P016     : "P016",
    cudaVideoSurfaceFormat_YUV444   : "YUV444P",
    cudaVideoSurfaceFormat_YUV444_16Bit : "YUV444P16",
}

CODEC_MAP = dict((v,k) for k,v in CODEC_NAMES.items())
CS_CHROMA: Dict[str, int] = {
    "YUV420P" : cudaVideoChromaFormat_420,
    "YUV422P" : cudaVideoChromaFormat_422,
    "YUV444P" : cudaVideoChromaFormat_444,
}


def init_module(options: dict) -> None:
    log("nvdec.init_module(%s)", options)
    from xpra.codecs.nvidia.util import has_nvidia_hardware
    if has_nvidia_hardware() is False:
        raise ImportError("no nvidia GPU device found")


def cleanup_module() -> None:
    log("nvdec.cleanup_module()")


def get_version() -> Tuple[int]:
    return (0, )


def get_type() -> str:
    return "nvdec"


def get_info() -> Dict[str, Any]:
    return {
        "version"   : get_version(),
    }


MIN_SIZES: Dict[str, Tuple[int, int]] = {}


def get_min_size(encoding: str) -> Tuple[int, int]:
    return MIN_SIZES.get(encoding, (48, 16))


#CODECS = ("jpeg", "h264", "vp8", "vp9")
CODECS = ("jpeg", )


def get_encodings() -> Sequence[str]:
    return CODECS


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    for encoding in CODECS:
        # has_lossless_mode = encoding == "vp9" and colorspace=="YUV444P"
        specs.append(VideoSpec(
                encoding=encoding, input_colorspace="YUV420P", output_colorspaces=("NV12", ),
                has_lossless_mode = False,
                codec_class=Decoder, codec_type=get_type(),
                quality=50, speed=100,
                size_efficiency=80,
                setup_cost=50,
                cpu_cost=0,
                gpu_cost=100,
                max_w=8192,
                max_h=4096,
            )
        )
    return specs


cdef int seq_cb(void *user_data, CUVIDEOFORMAT *vf) except 0:
    cdef Decoder decoder = <Decoder> decoders.get(int(<uintptr_t> user_data))
    return decoder.sequence_callback(vf)


cdef int decode_cb(void *user_data, CUVIDPICPARAMS *pp) except 0:
    cdef Decoder decoder = <Decoder> decoders.get(int(<uintptr_t> user_data))
    return decoder.decode_callback(pp)


cdef int display_cb(void *user_data, CUVIDPARSERDISPINFO *pdi) except 0:
    cdef Decoder decoder = <Decoder> decoders.get(int(<uintptr_t> user_data))
    return decoder.display_callback(pdi.picture_index, pdi.timestamp)


cdef int getop_cb(void *user_data, CUVIDOPERATINGPOINTINFO *op) except 0:
    #av1 specific, we don't care
    return 1


cdef int getseimsg_cb(void *user_data, CUVIDSEIMESSAGEINFO *seimsg) except 0:
    log(f"getseimsg_cb {seimsg.sei_message_count} sei messages")
    #void *pSEIData                  #OUT: SEI Message Data
    #CUSEIMESSAGE *pSEIMessage       #OUT: SEI Message Info
    #unsigned int sei_message_count  #OUT: SEI Message Count
    #unsigned int picIdx             #OUT: SEI Message Pic Index
    return 1


sequence = AtomicInteger()
decoders = WeakValueDictionary()


#note: the C api is event based but we want synchronous behaviour
#so we use an event to ensure that the data we feed produces an image as output
#this will need to be changed to support B-frames
cdef class Decoder:
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned long frames
    cdef unsigned long sequence
    cdef object colorspace
    cdef object encoding
    cdef CUvideodecoder context
    cdef CUvideoparser parser
    cdef CUstream stream
    cdef object event
    cdef object buffer
    cdef object image

    cdef object __weakref__

    def init_context(self, encoding: str, width: int, height: int, colorspace: str, options: typedict) -> None:
        log("nvdec.Decoder.init_context%s", (encoding, width, height, colorspace, options))
        if encoding not in CODEC_MAP:
            raise ValueError(f"invalid encoding {encoding} for nvdec")
        if colorspace not in CS_CHROMA:
            raise ValueError(f"invalid colorspace {colorspace} for nvdec")
        self.sequence = sequence.increase()
        self.encoding = encoding
        self.colorspace = colorspace
        self.width = width
        self.height = height
        self.event = Event()        #set each time the data has been parsed / processed
        self.stream = <CUstream> 0
        self.buffer = None
        self.image = None
        if self.encoding=="jpeg":
            self.init_decoder()
        else:
            self.init_parser()
        decoders[self.sequence] = self

    def init_parser(self) -> None:
        log("init_parser()")
        cdef CUVIDPARSERPARAMS pp
        memset(&pp, 0, sizeof(CUVIDPARSERPARAMS))
        pp.CodecType = CODEC_MAP[self.encoding]
        pp.ulMaxNumDecodeSurfaces = 0
        #pp.ulClockRate                #IN: Timestamp units in Hz (0=default=10000000Hz)
        pp.ulErrorThreshold = 100
        pp.ulMaxDisplayDelay = 0        #0=no delay
        pp.pUserData = <void *> (<uintptr_t> self.sequence)
        pp.pfnSequenceCallback = seq_cb
        pp.pfnDecodePicture = decode_cb
        pp.pfnDisplayPicture = display_cb
        pp.pfnGetOperatingPoint = getop_cb
        pp.pfnGetSEIMsg = getseimsg_cb
        cdef CUresult r
        r = cuvidCreateVideoParser(&self.parser, &pp)
        log(f"cuvidCreateVideoParser()={r}")
        cudacheck(r, "creating parser returned error")

    cdef sequence_callback(self, CUVIDEOFORMAT *vf):
        encoding = CODEC_NAMES.get(vf.codec, vf.codec)
        log("sequence_callback codec=%s", encoding)
        #log(" frame_rate=%s", vf.frame_rate)
        log(" progressive_sequence=%s", vf.progressive_sequence)
        log(" bit_depth_luma_minus8=%s, bit_depth_chroma_minus8=%s",
            vf.bit_depth_luma_minus8, vf.bit_depth_chroma_minus8)
        log(" min_num_decode_surfaces=%s, bitrate=%s", vf.min_num_decode_surfaces, vf.bitrate)
        log(" coded size: %sx%s", vf.coded_width, vf.coded_height)
        #print(" display_area=%s", vf.display_area)
        log(" chroma_format=%s", CHROMA_NAMES.get(vf.chroma_format, vf.chroma_format))
        if encoding!=self.encoding:
            log.error(f"Error: expected {self.encoding!r} but parser found {encoding!r}")
            return 0
        self.init_decoder(vf.min_num_decode_surfaces)
        self.event.set()
        return vf.min_num_decode_surfaces

    cdef int decode_callback(self, CUVIDPICPARAMS *pp):
        log("decode_callback(..)")
        self.decode_data(pp)
        return 1

    cdef int display_callback(self, int picture_index, CUvideotimestamp timestamp):
        log("display_callback(%s, %s)", picture_index, timestamp)
        self.image = self.get_output_image(picture_index)
        return int(self.image is not None)

    def init_decoder(self, int decode_surfaces=2) -> None:
        log(f"init_decoder({decode_surfaces})")
        cdef CUVIDDECODECREATEINFO pdci
        memset(&pdci, 0, sizeof(CUVIDDECODECREATEINFO))
        pdci.CodecType = CODEC_MAP[self.encoding]
        pdci.ChromaFormat = CS_CHROMA[self.colorspace]
        pdci.OutputFormat = cudaVideoSurfaceFormat_NV12 #cudaVideoSurfaceFormat_YUV444_16Bit
        pdci.bitDepthMinus8 = 0
        pdci.DeinterlaceMode = cudaVideoDeinterlaceMode_Weave
        #cudaVideoCreate_Default
        pdci.ulCreationFlags = cudaVideoCreate_PreferCUVID  #Use dedicated video engines directly
        pdci.ulIntraDecodeOnly = 0
        pdci.ulNumDecodeSurfaces = decode_surfaces
        pdci.ulNumOutputSurfaces = 1
        #geometry:
        pdci.ulWidth = self.width
        pdci.ulHeight = self.height
        pdci.ulTargetWidth = self.width
        pdci.ulTargetHeight = self.height
        pdci.ulMaxWidth = self.width
        pdci.ulMaxHeight = self.height
        #pdci.display_area.left = 0
        #pdci.display_area.top = 0
        #pdci.display_area.right = self.width
        #pdci.display_area.bottom = self.height
        #pdci.target_rect.left = 0
        #pdci.target_rect.top = 0
        #pdci.target_rect.right = self.width
        #pdci.target_rect.bottom = self.height
        pdci.vidLock = NULL
        pdci.enableHistogram = 0
        cdef CUresult r = cuvidCreateDecoder(&self.context, &pdci)
        log(f"cuvidCreateDecoder(..)={r}")
        cudacheck(r, "creating nvdec decoder returned error")

    def __repr__(self):
        return f"nvdec({self.encoding})"

    def get_info(self) -> Dict[str, Any]:
        return {
            "type"      : self.get_type(),
            "width"     : self.width,
            "height"    : self.height,
            "encoding"  : self.encoding,
            "frames"    : int(self.frames),
            "colorspace": self.colorspace,
        }

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context==NULL

    def get_encoding(self) -> str:
        return self.encoding

    def get_type(self) -> str:
        return "nvdec"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        cdef CUresult r = 0
        e = self.event
        if e:
            e.set()
            self.event = None
        if self.parser!=NULL:
            self.flush()
            r = cuvidDestroyVideoParser(self.parser)
            if r:
                log.error(f"Error destroying parser: {get_error_name(r)}")
            self.parser = NULL
        if self.context!=NULL:
            r = cuvidDestroyDecoder(self.context)
            if r:
                log.error(f"Error destroying decoder: {get_error_name(r)}")
            self.context = NULL
        self.width = 0
        self.height = 0
        self.colorspace = ""
        self.encoding = ""

    def decompress_image(self, data, options: typedict) -> ImageWrapper:
        log(f"nvdec.decompress_image({len(data)} bytes, {options})")
        cdef CUresult r
        cdef CUVIDSOURCEDATAPACKET packet
        cdef CUVIDPICPARAMS pic
        try:
            self.image = None
            stream = options.get("stream", None)
            if stream:
                self.stream = <CUstream> (<uintptr_t> stream.handle)
            with buffer_context(data) as bc:
                self.buffer = bc
                if self.parser:
                    self.event.clear()
                    memset(&packet, 0, sizeof(CUVIDSOURCEDATAPACKET))
                    packet.flags = CUVID_PKT_ENDOFPICTURE   #| CUVID_PKT_TIMESTAMP
                    packet.timestamp = 0
                    packet.payload_size = len(bc)
                    packet.payload = <const unsigned char*> (<uintptr_t> int(bc))
                    r = cuvidParseVideoData(self.parser, &packet)
                    log(f"cuvidParseVideoData(..)={r}")
                    cudacheck(r, "parsing error")
                    if not self.event.wait(1):
                        raise RuntimeError("parsing timed out")
                    return self.image
                else:
                    #no need: just use a blank pic params:
                    memset(&pic, 0, sizeof(CUVIDPICPARAMS))
                    self.decode_data(&pic)
                    return self.get_output_image()
        finally:
            self.buffer = None
            self.stream = <CUstream> 0

    cdef decode_data(self, CUVIDPICPARAMS *pic):
        log(f"decode_data({len(self.buffer)} bytes)")
        self.frames += 1
        cdef CUresult r = 0
        pic.nBitstreamDataLen = len(self.buffer)
        pic.pBitstreamData = <const unsigned char*> (<uintptr_t> int(self.buffer))
        with nogil:
            r = cuvidDecodePicture(self.context, pic)
        if r==CUDA_ERROR_INVALID_IMAGE:
            raise ValueError("invalid image data")
        log(f"cuvidDecodePicture()={r}")
        cudacheck(r, "GPU picture decoding returned error")
        cdef CUVIDGETDECODESTATUS status
        memset(&status, 0, sizeof(CUVIDGETDECODESTATUS))
        cdef int pic_idx = pic.CurrPicIdx
        #start = monotonic()
        r = cuvidGetDecodeStatus(self.context, pic_idx, &status)
        #while status.decodeStatus==cuvidDecodeStatus_InProgress:
        #    sleep(0.001)
        #    r = cuvidGetDecodeStatus(self.context, pic_idx, &status)
        #    log("waiting for decode")
        #end = monotonic()
        sinfo = DECODE_STATUS_STR.get(status.decodeStatus, status.decodeStatus)
        log(f"decompress_image: status={sinfo}")
        #if status.decodeStatus not in (
        #    cuvidDecodeStatus_InProgress,
        #    cuvidDecodeStatus_Success,
        #    cuvidDecodeStatus_Error_Concealed,
        #    ):
        #    if r in DECODE_STATUS_STR:
        #        raise RuntimeError(f"GPU decoding status returned error {sinfo!r}")
        #    cudacheck(r, "GPU picture decoding status error")

    def get_output_image(self, int pic_idx=0) -> ImageWrapper:
        #map it as a CUDA buffer:
        cdef CUVIDPROCPARAMS map_params
        map_params.progressive_frame = 1
        memset(&map_params, 0, sizeof(CUVIDPROCPARAMS))
        map_params.output_stream = self.stream
        cdef unsigned long long dev_ptr
        cdef unsigned int pitch
        r = cuvidMapVideoFrame64(self.context, pic_idx, &dev_ptr, &pitch, &map_params)
        cudacheck(r, "GPU mapping of picture buffer error")
        log(f"mapped picture {pic_idx} at {dev_ptr:x}, pitch={pitch}, stream=%s", <uintptr_t> self.stream)
        try:
            yuv_buf, yuv_pitch = mem_alloc_pitch(self.width, roundup(self.height, 2)*3//2, 4)
            copy = Memcpy2D()
            copy.set_src_device(dev_ptr)
            copy.src_x_in_bytes = 0
            copy.src_y = 0
            copy.src_pitch = pitch
            copy.width_in_bytes = self.width
            copy.height = roundup(self.height, 2)*3//2
            copy.set_dst_device(yuv_buf)
            copy.dst_x_in_bytes = 0
            copy.dst_y = 0
            copy.dst_pitch = yuv_pitch
            copy(aligned=False)
            rowstrides = [yuv_pitch, yuv_pitch]
            image = ImageWrapper(0, 0, self.width, self.height,
                                 yuv_buf, "NV12", 24, rowstrides, 3, ImageWrapper.PLANAR_2)
            self.frames += 1
            self.event.set()
            return image
        finally:
            r = cuvidUnmapVideoFrame64(self.context, dev_ptr)
            cudacheck(r, "error unmapping video frame")

    cdef flush(self):
        cdef CUVIDSOURCEDATAPACKET packet
        cdef CUresult r
        if self.parser:
            memset(&packet, 0, sizeof(CUVIDSOURCEDATAPACKET))
            r = cuvidParseVideoData(self.parser, &packet)
            packet.payload_size = 0
            packet.payload = NULL
            packet.flags = CUVID_PKT_ENDOFSTREAM
            r = cuvidParseVideoData(self.parser, &packet)
            log(f"cuvidParseVideoData(..)={r}")


def download_from_gpu(buf, size_t size) -> MemBuf:
    log("nvdec download_from_gpu%s", (buf, size))
    start = monotonic()
    cdef MemBuf pixels = getbuf(size, False)
    memcpy_dtoh(pixels, buf)
    end = monotonic()
    log("nvdec downloaded %i bytes in %ims", size, 1000*(end-start))
    return pixels


def decompress(encoding: str, img_data, width: int, height: int, options=None) -> ImageWrapper:
    #decompress using the default device,
    #and download the pixel data from the GPU:
    dev = get_default_device_context()
    if not dev:
        raise RuntimeError("no cuda device found")
    with dev as cuda_context:
        log("cuda_context=%s for device=%s", cuda_context, dev.get_info())
        options = typedict(options or {})
        stream = options.get("stream")
        if not stream:
            stream = Stream()
            options["stream"] = stream
        return decompress_and_download(encoding, img_data, width, height, options)


def decompress_and_download(encoding: str, img_data, width: int, height: int, options=None) -> ImageWrapper:
    img = decompress_with_device(encoding, img_data, width, height, options)
    cuda_buffer = img.get_pixels()
    rowstrides = img.get_rowstride()
    assert len(rowstrides)==2 and rowstrides[0]==rowstrides[1]
    stride = rowstrides[0]
    assert img.get_pixel_format()=="NV12"
    height = img.get_height()
    size = roundup(height, 2)*stride*3//2
    y_size = stride*height
    uv_start = roundup(height, 2)*stride
    uv_size = stride*(height//2)
    nv12_buf = download_from_gpu(cuda_buffer, size)
    pixels = memoryview(nv12_buf)
    planes = pixels[:y_size], pixels[uv_start:uv_start+uv_size]
    cuda_buffer.free()
    img.set_pixels(planes)
    return img


def decompress_with_device(encoding: str, img_data, width: int, height: int, options=None) -> ImageWrapper:
    cdef Decoder decoder = Decoder()
    try:
        tdoptions = typedict(options or {})
        decoder.init_context(encoding, width, height, "YUV420P", tdoptions)
        return decoder.decompress_image(img_data, tdoptions)
    finally:
        decoder.clean()


def selftest(full=False) -> None:
    from xpra.codecs.nvidia.util import has_nvidia_hardware, get_nvidia_module_version
    if not has_nvidia_hardware():
        raise ImportError("no nvidia GPU device found")
    get_nvidia_module_version(True)

    dev = get_default_device_context()
    if not dev:
        raise RuntimeError("no device found")

    cdef CUVIDDECODECAPS caps
    cdef CUresult r
    cdef Decoder decoder

    codec_ok = {}
    codec_failed = []
    with dev as cuda_context:
        log("cuda_context=%s for device=%s", cuda_context, dev.get_info())

        for codec_i, codec_name in CODEC_NAMES.items():
            min_w = min_h = 0
            chroma_ok= []
            chroma_failed = []
            for chroma_i, chroma_name in CHROMA_NAMES.items():
                memset(&caps, 0, sizeof(CUVIDDECODECAPS))
                caps.eCodecType = codec_i
                caps.eChromaFormat = chroma_i
                caps.nBitDepthMinus8 = 0
                r = cuvidGetDecoderCaps(&caps)
                if r:
                    chroma_failed.append(chroma_name)
                    log(f"decoder caps for {codec_name} + {chroma_name} returned error %s", get_error_name(r))
                    continue
                if not caps.bIsSupported:
                    chroma_failed.append(chroma_name)
                    #log(f"{codec_name} + {chroma_name} is not supported on this GPU")
                    continue
                if caps.nMaxWidth<4096 or caps.nMaxHeight<4096:
                    chroma_failed.append(chroma_name)
                    log(f"{codec_name} maximum dimension is only {caps.nMaxWidth}x{caps.nMaxHeight}")
                    continue
                oformats = tuple(name for sfi, name in SURFACE_NAMES.items() if caps.nOutputFormatMask & (1<<sfi))
                log(f"output formats for {codec_name} + {chroma_name}: %s (mask={caps.nOutputFormatMask:x})", csv(oformats))
                if "NV12" in oformats:
                    if min_w==0 or caps.nMinWidth>min_w:
                        min_w = caps.nMinWidth
                    if min_h==0 or caps.nMinHeight>min_h:
                        min_h = caps.nMinHeight
                    chroma_ok.append(chroma_name)
                else:
                    log(f"{codec_name} does not support NV12 surface")
            if chroma_ok:
                codec_ok[codec_name] = chroma_ok
                MIN_SIZES[codec_name] = (min_w, min_h)
            else:
                codec_failed.append(codec_name)
        log(f"codecs failed: {codec_failed}")
        log(f"codecs supported: {codec_ok}")
        log(f"minimum sizes: {MIN_SIZES}")
        from xpra.codecs.checks import testdecoder
        from xpra.codecs.nvidia import nvdec
        nvdec.decoder.CODECS = testdecoder(nvdec.decoder, full)
        log(f"validated encodings: {nvdec.decoder.CODECS}")
        if not nvdec.decoder.CODECS:
            raise RuntimeError("no encodings supported")
