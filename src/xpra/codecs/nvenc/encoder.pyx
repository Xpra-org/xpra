# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import time
import os

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_NVENC_DEBUG")
error = log.error

from libc.stdint cimport uint8_t, uint16_t, uint32_t, int32_t, uint64_t

FORCE = True


cdef extern from "string.h":
    void * memcpy ( void * destination, void * source, size_t num )
    void * memset ( void * ptr, int value, size_t num )

cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

#could also use pycuda...
cdef extern from "cuda.h":
    ctypedef int CUdevice
    ctypedef struct CUcontext:
        pass
    int cuInit(unsigned int flags)
    int cuDeviceGet(CUdevice *device, int ordinal)
    int cuDeviceGetCount(int *count)
    int cuDeviceGetName(char *name, int len, CUdevice dev)
    int cuDeviceComputeCapability(int *major, int *minor, CUdevice dev)

    int cuCtxCreate(CUcontext *pctx, unsigned int flags, CUdevice dev)
    int cuCtxPopCurrent(CUcontext *pctx)
    int cuCtxPushCurrent(CUcontext pctx)


cdef extern from "NvTypes.h":
    pass


CODEC_PROFILES = {
                  #NV_ENC_H264_PROFILE_BASELINE_GUID
                  "baseline"    : 66,
                  #NV_ENC_H264_PROFILE_MAIN_GUID
                  "main"        : 77,
                  #NV_ENC_H264_PROFILE_HIGH_GUID
                  "high"        : 100,
                  #NV_ENC_H264_PROFILE_STEREO_GUID
                  "stereo"      : 128,
                  }
#cdef extern from "videoFormats.h":
#    const char *getVideoFormatString(unsigned int dwFormat)

ctypedef uint32_t CONSTANT

cdef extern from "nvEncodeAPI.h":

    ctypedef int NVENCSTATUS
    ctypedef void* NV_ENC_INPUT_PTR
    ctypedef void* NV_ENC_OUTPUT_PTR
    ctypedef void* NV_ENC_REGISTERED_PTR

    ctypedef struct NV_ENC_PIC_PARAMS:
        pass
    ctypedef struct NV_ENC_LOCK_BITSTREAM:
        pass
    ctypedef struct NV_ENC_LOCK_INPUT_BUFFER:
        pass
    ctypedef struct NV_ENC_STAT:
        pass
    ctypedef struct NV_ENC_SEQUENCE_PARAM_PAYLOAD:
        pass
    ctypedef struct NV_ENC_EVENT_PARAMS:
        pass
    ctypedef struct NV_ENC_MAP_INPUT_RESOURCE:
        pass
    ctypedef struct NV_ENC_REGISTER_RESOURCE:
        pass

    ctypedef struct GUID:
        uint32_t Data1
        uint16_t Data2
        uint16_t Data3
        uint8_t  Data4[8]

    #Encode Codec GUIDS supported by the NvEncodeAPI interface.
    GUID NV_ENC_CODEC_H264_GUID
    #NV_ENC_CODEC_MPEG2_GUID, etc..

    #Encode Profile GUIDS supported by the NvEncodeAPI interface.
    GUID NV_ENC_H264_PROFILE_BASELINE_GUID
    GUID NV_ENC_H264_PROFILE_BASELINE_GUID
    GUID NV_ENC_H264_PROFILE_MAIN_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_GUID
    GUID NV_ENC_H264_PROFILE_STEREO_GUID
    GUID NV_ENC_H264_PROFILE_SVC_TEMPORAL_SCALABILTY
    GUID NV_ENC_H264_PROFILE_CONSTRAINED_HIGH_GUID
    #GUID NV_ENC_MPEG2_PROFILE_SIMPLE_GUID etc..

    #Preset GUIDS supported by the NvEncodeAPI interface.
    GUID NV_ENC_PRESET_DEFAULT_GUID
    GUID NV_ENC_PRESET_HP_GUID
    GUID NV_ENC_PRESET_HQ_GUID
    GUID NV_ENC_PRESET_HQ_GUID
    GUID NV_ENC_PRESET_LOW_LATENCY_DEFAULT_GUID
    GUID NV_ENC_PRESET_LOW_LATENCY_HQ_GUID
    GUID NV_ENC_PRESET_LOW_LATENCY_HQ_GUID
    GUID NV_ENC_PRESET_LOW_LATENCY_HQ_GUID

    ctypedef struct NV_ENC_CAPS_PARAM:
        uint32_t    version
        uint32_t    capsToQuery
        uint32_t    reserved[62]

    ctypedef struct NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS:
        uint32_t    version         #[in]: Struct version. Must be set to ::NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER.
        int         deviceType      #[in]: (NV_ENC_DEVICE_TYPE) Specified the device Type
        void        *device         #[in]: Pointer to client device.
        GUID        *clientKeyPtr   #[in]: Pointer to a GUID key issued to the client.
        uint32_t    apiVersion      #[in]: API version. Should be set to NVENCAPI_VERSION.
        uint32_t    reserved1[253]  #[in]: Reserved and must be set to 0
        void        *reserved2[64]  #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CREATE_INPUT_BUFFER:
        uint32_t    version         #[in]: Struct version. Must be set to ::NV_ENC_CREATE_INPUT_BUFFER_VER
        uint32_t    width           #[in]: Input buffer width
        uint32_t    height          #[in]: Input buffer width
        CONSTANT    memoryHeap      #[in]: Input buffer memory heap (NV_ENC_MEMORY_HEAP)
        CONSTANT    bufferFmt       #[in]: Input buffer format (NV_ENC_BUFFER_FORMAT)
        uint32_t    reserved        #[in]: Reserved and must be set to 0
        void        *inputBuffer    #[out]: Pointer to input buffer
        void        *pSysMemBuffer  #[in]: Pointer to existing sysmem buffer
        uint32_t    reserved1[57]   #[in]: Reserved and must be set to 0
        void        *reserved2[63]  #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CREATE_BITSTREAM_BUFFER:
        uint32_t    version         #[in]: Struct version. Must be set to ::NV_ENC_CREATE_BITSTREAM_BUFFER_VER
        uint32_t    size            #[in]: Size of the bitstream buffer to be created
        CONSTANT    memoryHeap      #[in]: Output buffer memory heap
        uint32_t    reserved        #[in]: Reserved and must be set to 0
        void        *bitstreamBuffer#[out]: Pointer to the output bitstream buffer
        void        *bitstreamBufferPtr #[out]: Reserved and should not be used
        uint32_t    reserved1[58]   #[in]: Reserved and should be set to 0
        void*       reserved2[64]   #[in]: Reserved and should be set to NULL

    ctypedef struct NV_ENC_QP:
        uint32_t    qpInterP
        uint32_t    qpInterB
        uint32_t    qpIntra

    ctypedef struct NV_ENC_CONFIG_H264:
        uint32_t    enableTemporalSVC   #[in]: Set to 1 to enable SVC temporal
        uint32_t    enableStereoMVC     #[in]: Set to 1 to enable stereo MVC
        uint32_t    hierarchicalPFrames #[in]: Set to 1 to enable hierarchical PFrames
        uint32_t    hierarchicalBFrames #[in]: Set to 1 to enable hierarchical BFrames
        uint32_t    outputBufferingPeriodSEI    #[in]: Set to 1 to write SEI buffering period syntax in the bitstream
        uint32_t    outputPictureTimingSEI      #[in]: Set to 1 to write SEI picture timing syntax in the bitstream
        uint32_t    outputAUD                   #[in]: Set to 1 to write access unit delimiter syntax in bitstream
        uint32_t    disableSPSPPS               #[in]: Set to 1 to disable writing of Sequence and Picture parameter info in bitstream
        uint32_t    outputFramePackingSEI       #[in]: Set to 1 to enable writing of frame packing arrangement SEI messages to bitstream
        uint32_t    outputRecoveryPointSEI      #[in]: Set to 1 to enable writing of recovery point SEI message
        uint32_t    enableIntraRefresh          #[in]: Set to 1 to enable gradual decoder refresh or intra refresh. If the GOP structure uses B frames this will be ignored
        uint32_t    enableConstrainedEncoding   #[in]: Set this to 1 to enable constrainedFrame encoding where each slice in the constarined picture is independent of other slices
                                                #Check support for constrained encoding using ::NV_ENC_CAPS_SUPPORT_CONSTRAINED_ENCODING caps.
        uint32_t    repeatSPSPPS        #[in]: Set to 1 to enable writing of Sequence and Picture parameter for every IDR frame
        uint32_t    enableVFR           #[in]: Set to 1 to enable variable frame rate.
        uint32_t    enableLTR           #[in]: Set to 1 to enable LTR support and auto-mark the first
        uint32_t    reservedBitFields   #[in]: Reserved bitfields and must be set to 0
        uint32_t    level               #[in]: Specifies the encoding level. Client is recommended to set this to NV_ENC_LEVEL_AUTOSELECT in order to enable the NvEncodeAPI interface to select the correct level.
        uint32_t    idrPeriod           #[in]: Specifies the IDR interval. If not set, this is made equal to gopLength in NV_ENC_CONFIG.Low latency application client can set IDR interval to NVENC_INFINITE_GOPLENGTH so that IDR frames are not inserted automatically.
        uint32_t    separateColourPlaneFlag     #[in]: Set to 1 to enable 4:4:4 separate colour planes
        uint32_t    disableDeblockingFilterIDC  #[in]: Specifies the deblocking filter mode. Permissible value range: [0,2]
        uint32_t    numTemporalLayers   #[in]: Specifies max temporal layers to be used for hierarchical coding. Valid value range is [1,::NV_ENC_CAPS_NUM_MAX_TEMPORAL_LAYERS]
        uint32_t    spsId               #[in]: Specifies the SPS id of the sequence header. Currently reserved and must be set to 0.
        uint32_t    ppsId               #[in]: Specifies the PPS id of the picture header. Currently reserved and must be set to 0.
        CONSTANT    adaptiveTransformMode       #[in]: (NV_ENC_H264_ADAPTIVE_TRANSFORM_MODE) Specifies the AdaptiveTransform Mode. Check support for AdaptiveTransform mode using ::NV_ENC_CAPS_SUPPORT_ADAPTIVE_TRANSFORM caps.
        CONSTANT    fmoMode             #[in]: (NV_ENC_H264_FMO_MODE) Specified the FMO Mode. Check support for FMO using ::NV_ENC_CAPS_SUPPORT_FMO caps.
        CONSTANT    bdirectMode         #[in]: (NV_ENC_H264_BDIRECT_MODE) Specifies the BDirect mode. Check support for BDirect mode using ::NV_ENC_CAPS_SUPPORT_BDIRECT_MODE caps.
        CONSTANT    entropyCodingMode   #[in]: (NV_ENC_H264_ENTROPY_CODING_MODE) Specifies the entropy coding mode. Check support for CABAC mode using ::NV_ENC_CAPS_SUPPORT_CABAC caps.
        CONSTANT    stereoMode          #[in]: (NV_ENC_STEREO_PACKING_MODE) Specifies the stereo frame packing mode which is to be signalled in frame packing arrangement SEI
        CONSTANT    h264Extension       #[in]: (NV_ENC_CONFIG_H264_EXT) Specifies the H264 extension config
        uint32_t    intraRefreshPeriod  #[in]: Specifies the interval between successive intra refresh if enableIntrarefresh is set and one time intraRefresh configuration is desired.
                                        #When this is specified only first IDR will be encoded and no more key frames will be encoded. Client should set PIC_TYPE = NV_ENC_PIC_TYPE_INTRA_REFRESH
                                        #for first picture of every intra refresh period.
        uint32_t    intraRefreshCnt     #[in]: Specifies the number of frames over which intra refresh will happen
        uint32_t    maxNumRefFrames     #[in]: Specifies the DPB size used for encoding. Setting it to 0 will let driver use the default dpb size.
                                        #The low latency application which wants to invalidate reference frame as an error resilience tool
                                        #is recommended to use a large DPB size so that the encoder can keep old reference frames which can be used if recent
                                        #frames are invalidated.
        uint32_t    sliceMode           #[in]: This parameter in conjunction with sliceModeData specifies the way in which the picture is divided into slices
                                        #sliceMode = 0 MB based slices, sliceMode = 1 Byte based slices, sliceMode = 2 MB row based slices, sliceMode = 3, numSlices in Picture
                                        #When forceIntraRefreshWithFrameCnt is set it will have priority over sliceMode setting
                                        #When sliceMode == 0 and sliceModeData == 0 whole picture will be coded with one slice
        uint32_t    sliceModeData       #[in]: Specifies the parameter needed for sliceMode. For:
                                        #sliceMode = 0, sliceModeData specifies # of MBs in each slice (except last slice)
                                        #sliceMode = 1, sliceModeData specifies maximum # of bytes in each slice (except last slice)
                                        #sliceMode = 2, sliceModeData specifies # of MB rows in each slice (except last slice)
                                        #sliceMode = 3, sliceModeData specifies number of slices in the picture. Driver will divide picture into slices optimally
        CONSTANT    h264VUIParameters   #[in]: (NV_ENC_CONFIG_H264_VUI_PARAMETERS) Specifies the H264 video usability info pamameters
        uint32_t    ltrNumFrames        #[in]: Specifies the number of LTR frames used. Additionally, encoder will mark the first numLTRFrames base layer reference frames within each IDR interval as LTR
        uint32_t    ltrTrustMode        #[in]: Specifies the LTR operating mode. Set to 0 to disallow encoding using LTR frames until later specified. Set to 1 to allow encoding using LTR frames unless later invalidated.
        uint32_t    reserved1[272]      #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CONFIG_MPEG2:
        uint32_t    profile             #[in]: Specifies the encoding profile
        uint32_t    level               #[in]: Specifies the encoding level
        uint32_t    alternateScanValue  #[in]: Specifies the AlternateScan value
        uint32_t    quantScaleType      #[in]: Specifies the QuantScale value
        uint32_t    intraDCPrecision    #[in]: Specifies the intra DC precision
        uint32_t    frameDCT            #[in]: Specifies the frame Discrete Cosine Transform
        uint32_t    reserved[250]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CONFIG_JPEG:
        uint32_t    reserved[256]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CONFIG_VC1:
        uint32_t    level               #[in]: Specifies the encoding level
        uint32_t    disableOverlapSmooth#[in]: Set this to 1 for disabling overlap smoothing
        uint32_t    disableFastUVMC     #[in]: Set this to 1 for disabling fastUVMC mode
        uint32_t    disableInloopFilter #[in]: Set this to 1 for disabling in-loop filtering
        uint32_t    disable4MV          #[in]: Set this to 1 for disabling 4MV mode
        uint32_t    reservedBitFields   #[in]: Reserved bitfields and must be set to 0
        uint32_t    numSlices           #[in]: Specifies number of slices to encode. This field is applicable only for Advanced Profile.
                                        #If set to 0, NvEncodeAPI interface will choose optimal number of slices. Currently we support only a maximum of three slices
        uint32_t    reserved[253]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CONFIG_VP8:
        uint32_t    reserved[256]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CODEC_CONFIG:
        NV_ENC_CONFIG_H264  h264Config  #[in]: Specifies the H.264-specific encoder configuration
        NV_ENC_CONFIG_VC1   vc1Config   #[in]: Specifies the VC1-specific encoder configuration. Currently unsupported and must not to be used.
        NV_ENC_CONFIG_JPEG  jpegConfig  #[in]: Specifies the JPEG-specific encoder configuration. Currently unsupported and must not to be used.
        NV_ENC_CONFIG_MPEG2 mpeg2Config #[in]: Specifies the MPEG2-specific encoder configuration. Currently unsupported and must not to be used.
        NV_ENC_CONFIG_VP8   vp8Config   #[in]: Specifies the VP8-specific encoder configuration. Currently unsupported and must not to be used.
        uint32_t            reserved[256]       #[in]: Reserved and must be set to 0

    ctypedef struct NV_ENC_CONFIG:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_CONFIG_VER.
        GUID        profileGUID         #[in]: Specifies the codec profile guid. If client specifies \p NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID the NvEncodeAPI interface will select the appropriate codec profile.
        uint32_t    gopLength           #[in]: Specifies the number of pictures in one GOP. Low latency application client can set goplength to NVENC_INFINITE_GOPLENGTH so that keyframes are not inserted automatically.
        int32_t     frameIntervalP      #[in]: Specifies the GOP pattern as follows: \p frameIntervalP = 0: I, 1: IPP, 2: IBP, 3: IBBP  If goplength is set to NVENC_INFINITE_GOPLENGTH \p frameIntervalP should be set to 1.
        uint32_t    monoChromeEncoding  #[in]: Set this to 1 to enable monochrome encoding for this session.
        CONSTANT    frameFieldMode      #[in]: (NV_ENC_PARAMS_FRAME_FIELD_MODE) Specifies the frame/field mode. Check support for field encoding using ::NV_ENC_CAPS_SUPPORT_FIELD_ENCODING caps.
        CONSTANT    mvPrecision         #[in]: (NV_ENC_MV_PRECISION) Specifies the desired motion vector prediction precision.
        CONSTANT    rcParams            #[in]: (NV_ENC_RC_PARAMS) Specifies the rate control parameters for the current encoding session.
        CONSTANT    encodeCodecConfig   #[in]: (NV_ENC_CODEC_CONFIG) Specifies the codec specific config parameters through this union.
        uint32_t    reserved[278]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL


    ctypedef struct NVENC_EXTERNAL_ME_HINT_COUNTS_PER_BLOCKTYPE:
        uint32_t    numCandsPerBlk16x16 #[in]: Specifies the number of candidates per 16x16 block.
        uint32_t    numCandsPerBlk16x8  #[in]: Specifies the number of candidates per 16x8 block.
        uint32_t    numCandsPerBlk8x16  #[in]: Specifies the number of candidates per 8x16 block.
        uint32_t    numCandsPerBlk8x8   #[in]: Specifies the number of candidates per 8x8 block.
        uint32_t    reserved            #[in]: Reserved for padding.
        uint32_t    reserved1[3]        #[in]: Reserved for future use.

    ctypedef struct NV_ENC_INITIALIZE_PARAMS:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_INITIALIZE_PARAMS_VER.
        GUID        encodeGUID          #[in]: Specifies the Encode GUID for which the encoder is being created. ::NvEncInitializeEncoder() API will fail if this is not set, or set to unsupported value.
        GUID        presetGUID          #[in]: Specifies the preset for encoding. If the preset GUID is set then , the preset configuration will be applied before any other parameter.
        uint32_t    encodeWidth         #[in]: Specifies the encode width. If not set ::NvEncInitializeEncoder() API will fail.
        uint32_t    encodeHeight        #[in]: Specifies the encode height. If not set ::NvEncInitializeEncoder() API will fail.
        uint32_t    darWidth            #[in]: Specifies the display aspect ratio Width.
        uint32_t    darHeight           #[in]: Specifies the display aspect ratio height.
        uint32_t    frameRateNum        #[in]: Specifies the numerator for frame rate used for encoding in frames per second ( Frame rate = frameRateNum / frameRateDen ).
        uint32_t    frameRateDen        #[in]: Specifies the denominator for frame rate used for encoding in frames per second ( Frame rate = frameRateNum / frameRateDen ).
        uint32_t    enableEncodeAsync   #[in]: Set this to 1 to enable asynchronous mode and is expected to use events to get picture completion notification.
        uint32_t    enablePTD           #[in]: Set this to 1 to enable the Picture Type Decision is be taken by the NvEncodeAPI interface.
        uint32_t    reportSliceOffsets  #[in]: Set this to 1 to enable reporting slice offsets in ::_NV_ENC_LOCK_BITSTREAM. Currently supported only for H264. Client must set this to 0 if NV_ENC_CONFIG_H264::sliceMode is 1
        uint32_t    enableSubFrameWrite #[in]: Set this to 1 to write out available bitstream to memory at subframe intervals
        uint32_t    enableExternalMEHints   #[in]: Set to 1 to enable external ME hints for the current frame. Currently this feature is supported only if NV_ENC_INITIALIZE_PARAMS::enablePTD to 0 or\p frameIntervalP = 1 (i.e no B frames).
        uint32_t    reservedBitFields   #[in]: Reserved bitfields and must be set to 0
        uint32_t    privDataSize        #[in]: Reserved private data buffer size and must be set to 0
        void        *privData           #[in]: Reserved private data buffer and must be set to NULL
        NV_ENC_CONFIG *encodeConfig     #[in]: Specifies the advanced codec specific structure. If client has sent a valid codec config structure, it will override parameters set by the NV_ENC_INITIALIZE_PARAMS::presetGUID parameter. If set to NULL the NvEncodeAPI interface will use the NV_ENC_INITIALIZE_PARAMS::presetGUID to set the codec specific parameters.
                                        #Client can also optionally query the NvEncodeAPI interface to get codec specific parameters for a presetGUID using ::NvEncGetEncodePresetConfig() API. It can then modify (if required) some of the codec config parameters and send down a custom config structure as part of ::_NV_ENC_INITIALIZE_PARAMS.
                                        #Even in this case client is recommended to pass the same preset guid it has used in ::NvEncGetEncodePresetConfig() API to query the config structure; as NV_ENC_INITIALIZE_PARAMS::presetGUID. This will not override the custom config structure but will be used to determine other Encoder HW specific parameters not exposed in the API.
        uint32_t    maxEncodeWidth      #[in]: Maximum encode width to be used for current Encode session.
                                        #Client should allocate output buffers according to this dimension for dynamic resolution change. If set to 0, Encoder will not allow dynamic resolution change.
        uint32_t    maxEncodeHeight     #[in]: Maximum encode height to be allowed for current Encode session.
                                        #Client should allocate output buffers according to this dimension for dynamic resolution change. If set to 0, Encode will not allow dynamic resolution change.
        NVENC_EXTERNAL_ME_HINT_COUNTS_PER_BLOCKTYPE maxMEHintCountsPerBlock[2]  #[in]: If Client wants to pass external motion vectors in NV_ENC_PIC_PARAMS::meExternalHints buffer it must specify the maximum number of hint candidates per block per direction for the encode session.
                                        #The NV_ENC_INITIALIZE_PARAMS::maxMEHintCountsPerBlock[0] is for L0 predictors and NV_ENC_INITIALIZE_PARAMS::maxMEHintCountsPerBlock[1] is for L1 predictors.
                                        #This client must also set NV_ENC_INITIALIZE_PARAMS::enableExternalMEHints to 1.
        uint32_t    reserved[289]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_RECONFIGURE_PARAMS:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_RECONFIGURE_PARAMS_VER.
        NV_ENC_INITIALIZE_PARAMS reInitEncodeParams
        uint32_t    resetEncoder        #[in]: This resets the rate control states and other internal encoder states. This should be used only with an IDR frame.
                                        #If NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1, encoder will force the frame type to IDR
        uint32_t    forceIDR            #[in]: Encode the current picture as an IDR picture. This flag is only valid when Picture type decision is taken by the Encoder
                                        #[_NV_ENC_INITIALIZE_PARAMS::enablePTD == 1].
        uint32_t    reserved

    ctypedef struct NV_ENC_PRESET_CONFIG:
        uint32_t    version             #[in]:  Struct version. Must be set to ::NV_ENC_PRESET_CONFIG_VER.
        NV_ENC_CONFIG presetCfg         #[out]: preset config returned by the Nvidia Video Encoder interface.
        uint32_t    reserved1[255]      #[in]: Reserved and must be set to 0
        void*       reserved2[64]       #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_PIC_PARAMS_MVC:
        uint32_t    viewID              #[in]: Specifies the view ID associated with the current input view.
        uint32_t    temporalID          #[in]: Specifies the temporal ID associated with the current input view.
        uint32_t    priorityID          #[in]: Specifies the priority ID associated with the current input view. Reserved and ignored by the NvEncodeAPI interface.
        uint32_t    reserved1[253]      #[in]: Reserved and must be set to 0.
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL.

    ctypedef struct NV_ENC_PIC_PARAMS_SVC:
        uint32_t    priorityID          #[in]: Specifies the priority id associated with the current input.
        uint32_t    temporalID          #[in]: Specifies the temporal id associated with the current input.
        uint32_t    dependencyID        #[in]: Specifies the dependency id  associated with the current input.
        uint32_t    qualityID           #[in]: Specifies the quality id associated with the current input.
        uint32_t    reserved1[252]      #[in]: Reserved and must be set to 0.
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL.

    ctypedef struct NV_ENC_PIC_PARAMS_H264_EXT:
        NV_ENC_PIC_PARAMS_MVC mvcPicParams   #[in]: Specifies the MVC picture parameters.
        NV_ENC_PIC_PARAMS_SVC svcPicParams   #[in]: Specifies the SVC picture parameters.
        uint32_t    reserved1[256]      #[in]: Reserved and must be set to 0.

    NVENCSTATUS NvEncodeAPICreateInstance(NV_ENCODE_API_FUNCTION_LIST *functionList)

    ctypedef NVENCSTATUS (*PNVENCOPENENCODESESSION)         (void* device, uint32_t deviceType, void** encoder)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEGUIDCOUNT)        (void* encoder, uint32_t* encodeGUIDCount)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEGUIDS)            (void* encoder, GUID* GUIDs, uint32_t guidArraySize, uint32_t* GUIDCount)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPROFILEGUIDCOUNT) (void* encoder, GUID encodeGUID, uint32_t* encodeProfileGUIDCount)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPROFILEGUIDS)     (void* encoder, GUID encodeGUID, GUID* profileGUIDs, uint32_t guidArraySize, uint32_t* GUIDCount)
    ctypedef NVENCSTATUS (*PNVENCGETINPUTFORMATCOUNT)       (void* encoder, GUID encodeGUID, uint32_t* inputFmtCount)
    ctypedef NVENCSTATUS (*PNVENCGETINPUTFORMATS)           (void* encoder, GUID encodeGUID, int* inputFmts, uint32_t inputFmtArraySize, uint32_t* inputFmtCount)
    ctypedef NVENCSTATUS (*PNVENCGETENCODECAPS)             (void* encoder, GUID encodeGUID, NV_ENC_CAPS_PARAM* capsParam, int* capsVal)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETCOUNT)      (void* encoder, GUID encodeGUID, uint32_t* encodePresetGUIDCount)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETGUIDS)      (void* encoder, GUID encodeGUID, GUID* presetGUIDs, uint32_t guidArraySize, uint32_t* encodePresetGUIDCount)
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETCONFIG)     (void* encoder, GUID encodeGUID, GUID  presetGUID, NV_ENC_PRESET_CONFIG* presetConfig)
    ctypedef NVENCSTATUS (*PNVENCINITIALIZEENCODER)         (void* encoder, NV_ENC_INITIALIZE_PARAMS* createEncodeParams)
    ctypedef NVENCSTATUS (*PNVENCCREATEINPUTBUFFER)         (void* encoder, NV_ENC_CREATE_INPUT_BUFFER* createInputBufferParams)
    ctypedef NVENCSTATUS (*PNVENCDESTROYINPUTBUFFER)        (void* encoder, NV_ENC_INPUT_PTR inputBuffer)
    ctypedef NVENCSTATUS (*PNVENCCREATEBITSTREAMBUFFER)     (void* encoder, NV_ENC_CREATE_BITSTREAM_BUFFER* createBitstreamBufferParams)
    ctypedef NVENCSTATUS (*PNVENCDESTROYBITSTREAMBUFFER)    (void* encoder, NV_ENC_OUTPUT_PTR bitstreamBuffer)
    ctypedef NVENCSTATUS (*PNVENCENCODEPICTURE)             (void* encoder, NV_ENC_PIC_PARAMS* encodePicParams)
    ctypedef NVENCSTATUS (*PNVENCLOCKBITSTREAM)             (void* encoder, NV_ENC_LOCK_BITSTREAM* lockBitstreamBufferParams)
    ctypedef NVENCSTATUS (*PNVENCUNLOCKBITSTREAM)           (void* encoder, NV_ENC_OUTPUT_PTR bitstreamBuffer)
    ctypedef NVENCSTATUS (*PNVENCLOCKINPUTBUFFER)           (void* encoder, NV_ENC_LOCK_INPUT_BUFFER* lockInputBufferParams)
    ctypedef NVENCSTATUS (*PNVENCUNLOCKINPUTBUFFER)         (void* encoder, NV_ENC_INPUT_PTR inputBuffer)
    ctypedef NVENCSTATUS (*PNVENCGETENCODESTATS)            (void* encoder, NV_ENC_STAT* encodeStats)
    ctypedef NVENCSTATUS (*PNVENCGETSEQUENCEPARAMS)         (void* encoder, NV_ENC_SEQUENCE_PARAM_PAYLOAD* sequenceParamPayload)
    ctypedef NVENCSTATUS (*PNVENCREGISTERASYNCEVENT)        (void* encoder, NV_ENC_EVENT_PARAMS* eventParams)
    ctypedef NVENCSTATUS (*PNVENCUNREGISTERASYNCEVENT)      (void* encoder, NV_ENC_EVENT_PARAMS* eventParams)
    ctypedef NVENCSTATUS (*PNVENCMAPINPUTRESOURCE)          (void* encoder, NV_ENC_MAP_INPUT_RESOURCE* mapInputResParams)
    ctypedef NVENCSTATUS (*PNVENCUNMAPINPUTRESOURCE)        (void* encoder, NV_ENC_INPUT_PTR mappedInputBuffer)
    ctypedef NVENCSTATUS (*PNVENCDESTROYENCODER)            (void* encoder)
    ctypedef NVENCSTATUS (*PNVENCINVALIDATEREFFRAMES)       (void* encoder, uint64_t invalidRefFrameTimeStamp)
    ctypedef NVENCSTATUS (*PNVENCOPENENCODESESSIONEX)       (NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS *openSessionExParams, void** encoder)
    ctypedef NVENCSTATUS (*PNVENCREGISTERRESOURCE)          (void* encoder, NV_ENC_REGISTER_RESOURCE* registerResParams)
    ctypedef NVENCSTATUS (*PNVENCUNREGISTERRESOURCE)        (void* encoder, NV_ENC_REGISTERED_PTR registeredRes)
    ctypedef NVENCSTATUS (*PNVENCRECONFIGUREENCODER)        (void* encoder, NV_ENC_RECONFIGURE_PARAMS* reInitEncodeParams)

    ctypedef struct NV_ENCODE_API_FUNCTION_LIST:
        uint32_t    version         #[in]: Client should pass NV_ENCODE_API_FUNCTION_LIST_VER.
        uint32_t    reserved        #[in]: Reserved and should be set to 0.
        PNVENCOPENENCODESESSION         nvEncOpenEncodeSession          #[out]: Client should access ::NvEncOpenEncodeSession() API through this pointer.
        PNVENCGETENCODEGUIDCOUNT        nvEncGetEncodeGUIDCount         #[out]: Client should access ::NvEncGetEncodeGUIDCount() API through this pointer.
        PNVENCGETENCODEPROFILEGUIDCOUNT nvEncGetEncodeProfileGUIDCount  #[out]: Client should access ::NvEncGetEncodeProfileGUIDCount() API through this pointer.*/
        PNVENCGETENCODEPROFILEGUIDS     nvEncGetEncodeProfileGUIDs      #[out]: Client should access ::NvEncGetEncodeProfileGUIDs() API through this pointer.     */
        PNVENCGETENCODEGUIDS            nvEncGetEncodeGUIDs	            #[out]: Client should access ::NvEncGetEncodeGUIDs() API through this pointer.           */
        PNVENCGETINPUTFORMATCOUNT       nvEncGetInputFormatCount	    #[out]: Client should access ::NvEncGetInputFormatCount() API through this pointer.      */
        PNVENCGETINPUTFORMATS           nvEncGetInputFormats	        #[out]: Client should access ::NvEncGetInputFormats() API through this pointer.          */
        PNVENCGETENCODECAPS             nvEncGetEncodeCaps	            #[out]: Client should access ::NvEncGetEncodeCaps() API through this pointer.            */
        PNVENCGETENCODEPRESETCOUNT      nvEncGetEncodePresetCount	    #[out]: Client should access ::NvEncGetEncodePresetCount() API through this pointer.     */
        PNVENCGETENCODEPRESETGUIDS      nvEncGetEncodePresetGUIDs	    #[out]: Client should access ::NvEncGetEncodePresetGUIDs() API through this pointer.     */
        PNVENCGETENCODEPRESETCONFIG     nvEncGetEncodePresetConfig	    #[out]: Client should access ::NvEncGetEncodePresetConfig() API through this pointer.    */
        PNVENCINITIALIZEENCODER         nvEncInitializeEncoder	        #[out]: Client should access ::NvEncInitializeEncoder() API through this pointer.        */
        PNVENCCREATEINPUTBUFFER         nvEncCreateInputBuffer	        #[out]: Client should access ::NvEncCreateInputBuffer() API through this pointer.        */
        PNVENCDESTROYINPUTBUFFER        nvEncDestroyInputBuffer	        #[out]: Client should access ::NvEncDestroyInputBuffer() API through this pointer.       */
        PNVENCCREATEBITSTREAMBUFFER     nvEncCreateBitstreamBuffer	    #[out]: Client should access ::NvEncCreateBitstreamBuffer() API through this pointer.    */
        PNVENCDESTROYBITSTREAMBUFFER    nvEncDestroyBitstreamBuffer	    #[out]: Client should access ::NvEncDestroyBitstreamBuffer() API through this pointer.   */
        PNVENCENCODEPICTURE             nvEncEncodePicture	            #[out]: Client should access ::NvEncEncodePicture() API through this pointer.            */
        PNVENCLOCKBITSTREAM             nvEncLockBitstream	            #[out]: Client should access ::NvEncLockBitstream() API through this pointer.            */
        PNVENCUNLOCKBITSTREAM           nvEncUnlockBitstream	        #[out]: Client should access ::NvEncUnlockBitstream() API through this pointer.          */
        PNVENCLOCKINPUTBUFFER           nvEncLockInputBuffer	        #[out]: Client should access ::NvEncLockInputBuffer() API through this pointer.          */
        PNVENCUNLOCKINPUTBUFFER         nvEncUnlockInputBuffer	        #[out]: Client should access ::NvEncUnlockInputBuffer() API through this pointer.        */
        PNVENCGETENCODESTATS            nvEncGetEncodeStats	            #[out]: Client should access ::NvEncGetEncodeStats() API through this pointer.           */
        PNVENCGETSEQUENCEPARAMS         nvEncGetSequenceParams	        #[out]: Client should access ::NvEncGetSequenceParams() API through this pointer.        */
        PNVENCREGISTERASYNCEVENT        nvEncRegisterAsyncEvent	        #[out]: Client should access ::NvEncRegisterAsyncEvent() API through this pointer.       */
        PNVENCUNREGISTERASYNCEVENT      nvEncUnregisterAsyncEvent	    #[out]: Client should access ::NvEncUnregisterAsyncEvent() API through this pointer.     */
        PNVENCMAPINPUTRESOURCE          nvEncMapInputResource	        #[out]: Client should access ::NvEncMapInputResource() API through this pointer.         */
        PNVENCUNMAPINPUTRESOURCE        nvEncUnmapInputResource	        #[out]: Client should access ::NvEncUnmapInputResource() API through this pointer.       */
        PNVENCDESTROYENCODER            nvEncDestroyEncoder	            #[out]: Client should access ::NvEncDestroyEncoder() API through this pointer.           */
        PNVENCINVALIDATEREFFRAMES       nvEncInvalidateRefFrames	    #[out]: Client should access ::NvEncInvalidateRefFrames() API through this pointer.      */
        PNVENCOPENENCODESESSIONEX       nvEncOpenEncodeSessionEx	    #[out]: Client should access ::NvEncOpenEncodeSession() API through this pointer.        */
        PNVENCREGISTERRESOURCE          nvEncRegisterResource	        #[out]: Client should access ::NvEncRegisterResource() API through this pointer.         */
        PNVENCUNREGISTERRESOURCE        nvEncUnregisterResource	        #[out]: Client should access ::NvEncUnregisterResource() API through this pointer.       */
        PNVENCRECONFIGUREENCODER        nvEncReconfigureEncoder	        #[out]: Client should access ::NvEncReconfigureEncoder() API through this pointer.       */
        void*                           reserved2[285]	                #[in]:  Reserved and must be set to NULL          	#[

include "constants.pxi"
from xpra.codecs.codec_constants import codec_spec

STATUS_TXT = {
    NV_ENC_SUCCESS : "This indicates that API call returned with no errors.",
    NV_ENC_ERR_NO_ENCODE_DEVICE       : "This indicates that no encode capable devices were detected",
    NV_ENC_ERR_UNSUPPORTED_DEVICE     : "This indicates that devices pass by the client is not supported.",
    NV_ENC_ERR_INVALID_ENCODERDEVICE  : "This indicates that the encoder device supplied by the client is not valid.",
    NV_ENC_ERR_INVALID_DEVICE         : "This indicates that device passed to the API call is invalid.",
    NV_ENC_ERR_DEVICE_NOT_EXIST       : """This indicates that device passed to the API call is no longer available and
 needs to be reinitialized. The clients need to destroy the current encoder
 session by freeing the allocated input output buffers and destroying the device
 and create a new encoding session.""",
    NV_ENC_ERR_INVALID_PTR            : "This indicates that one or more of the pointers passed to the API call is invalid.",
    NV_ENC_ERR_INVALID_EVENT          : "This indicates that completion event passed in ::NvEncEncodePicture() call is invalid.",
    NV_ENC_ERR_INVALID_PARAM          : "This indicates that one or more of the parameter passed to the API call is invalid.",
    NV_ENC_ERR_INVALID_CALL           : "This indicates that an API call was made in wrong sequence/order.",
    NV_ENC_ERR_OUT_OF_MEMORY          : "This indicates that the API call failed because it was unable to allocate enough memory to perform the requested operation.",
    NV_ENC_ERR_ENCODER_NOT_INITIALIZED: """This indicates that the encoder has not been initialized with
::NvEncInitializeEncoder() or that initialization has failed.
The client cannot allocate input or output buffers or do any encoding
related operation before successfully initializing the encoder.""",
    NV_ENC_ERR_UNSUPPORTED_PARAM      : "This indicates that an unsupported parameter was passed by the client.",
    NV_ENC_ERR_LOCK_BUSY              : """This indicates that the ::NvEncLockBitstream() failed to lock the output
buffer. This happens when the client makes a non blocking lock call to
access the output bitstream by passing NV_ENC_LOCK_BITSTREAM::doNotWait flag.
This is not a fatal error and client should retry the same operation after
few milliseconds.""",
    NV_ENC_ERR_NOT_ENOUGH_BUFFER      : "This indicates that the size of the user buffer passed by the client is insufficient for the requested operation.",
    NV_ENC_ERR_INVALID_VERSION        : "This indicates that an invalid struct version was used by the client.",
    NV_ENC_ERR_MAP_FAILED             : "This indicates that ::NvEncMapInputResource() API failed to map the client provided input resource.",
    NV_ENC_ERR_NEED_MORE_INPUT        : """
This indicates encode driver requires more input buffers to produce an output
bitstream. If this error is returned from ::NvEncEncodePicture() API, this
is not a fatal error. If the client is encoding with B frames then,
::NvEncEncodePicture() API might be buffering the input frame for re-ordering.
A client operating in synchronous mode cannot call ::NvEncLockBitstream()
API on the output bitstream buffer if ::NvEncEncodePicture() returned the
::NV_ENC_ERR_NEED_MORE_INPUT error code.
The client must continue providing input frames until encode driver returns
::NV_ENC_SUCCESS. After receiving ::NV_ENC_SUCCESS status the client can call
::NvEncLockBitstream() API on the output buffers in the same order in which
it has called ::NvEncEncodePicture().
""",
    NV_ENC_ERR_ENCODER_BUSY : """This indicates that the HW encoder is busy encoding and is unable to encode
the input. The client should call ::NvEncEncodePicture() again after few milliseconds.""",
    NV_ENC_ERR_EVENT_NOT_REGISTERD : """This indicates that the completion event passed in ::NvEncEncodePicture()
API has not been registered with encoder driver using ::NvEncRegisterAsyncEvent().""",
    NV_ENC_ERR_GENERIC : "This indicates that an unknown internal error has occurred.",
    NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY  : "This indicates that the client is attempting to use a feature that is not available for the license type for the current system.",
    NV_ENC_ERR_UNIMPLEMENTED : "This indicates that the client is attempting to use a feature that is not implemented for the current version.",
    NV_ENC_ERR_RESOURCE_REGISTER_FAILED : "This indicates that the ::NvEncRegisterResource API failed to register the resource.",
    NV_ENC_ERR_RESOURCE_NOT_REGISTERED : "This indicates that the client is attempting to unregister a resource that has not been successfuly registered.",
    NV_ENC_ERR_RESOURCE_NOT_MAPPED : "This indicates that the client is attempting to unmap a resource that has not been successfuly mapped.",
      }


COLORSPACES = ("YUV444P", )
def get_colorspaces():
    return COLORSPACES

def get_spec(colorspace):
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    return codec_spec(Encoder, quality=60, setup_cost=100, cpu_cost=10, gpu_cost=100)


def get_version():
    return NVENCAPI_VERSION

def get_type():
    return "nvenc"

def roundup(n, m):
    return (n + m - 1) & ~(m - 1)

def statusInfo(ret):
    if ret in STATUS_TXT:
        return "%s: %s" % (ret, STATUS_TXT[ret])
    return str(ret)

def checkCuda(ret, msg=""):
    if ret!=0:
        log.warn("error during %s: %s", msg, statusInfo(ret))
def raiseCuda(ret, msg=""):
    if ret!=0:
        raise Exception("%s - returned %s" % (msg, statusInfo(ret)))

cdef cuda_init(deviceId=0):
    cdef int deviceCount, i
    cdef CUdevice cuDevice
    cdef char gpu_name[100]
    cdef int SMminor, SMmajor
    raiseCuda(cuInit(0), "cuInit")
    raiseCuda(cuDeviceGetCount(&deviceCount), "failed to get device count")
    log.info("cuda_init() found %s devices", deviceCount)
    for i in range(deviceCount):
        checkCuda(cuDeviceGet(&cuDevice, i), "cuDeviceGet")
        checkCuda(cuDeviceGetName(gpu_name, 100, cuDevice), "cuDeviceGetName")
        log.info("device[%s]=%s", i, gpu_name)
        checkCuda(cuDeviceComputeCapability(&SMmajor, &SMminor, i))
        has_nvenc = ((SMmajor<<4) + SMminor) >= 0x30
        log.info("capability: %s.%s (nvenc=%s)", SMmajor, SMminor, has_nvenc)
    if deviceId<0:
        deviceId = 0
    if deviceId>=deviceCount:
        raise Exception("invalid deviceId %s: only %s devices found" % (deviceId, deviceCount))

    raiseCuda(cuDeviceGet(&cuDevice, deviceId), "cuDeviceGet")
    raiseCuda(cuDeviceGetName(gpu_name, 100, cuDevice), "cuDeviceGetName")
    log.info("using device %s: %s", deviceId, gpu_name)
    raiseCuda(cuDeviceComputeCapability(&SMmajor, &SMminor, deviceId))
    has_nvenc = ((SMmajor<<4) + SMminor) >= 0x30
    if FORCE and not has_nvenc:
        log.warn("selected device %s does not have NVENC capability!" % gpu_name)
    else:
        assert has_nvenc, "selected device %s does not have NVENC capability!" % gpu_name
    return cuDevice

def guidstr(guid):
    #really ugly!
    b = bytearray((4+2+2+1))
    i = 0
    vi = 0
    for s in (4, 2, 2, 1):
        v = bytearray(guid.values()[vi])
        vi += 1
        for j in range(s):
            b[i] = v[j]
            i += 1
    return binascii.hexlify(b)


def cuda_check():
    cdef CUcontext context
    cdef int cuDevice
    cuDevice = cuda_init()

    raiseCuda(cuCtxCreate(&context, 0, cuDevice))
    raiseCuda(cuCtxPopCurrent(&context))

    debug("NV_ENC_CODEC_H264_GUID=%s" % guidstr(NV_ENC_CODEC_H264_GUID))
cuda_check()

#we keep these as globals for now
cdef NV_ENCODE_API_FUNCTION_LIST functionList
cdef CUcontext cuda_context          #@DuplicatedSignature

cdef void *open_encode_session():
    global cuda_context
    cdef NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS params
    cdef int cuDevice               #@DuplicatedSignature
    cdef GUID clientKeyPtr
    cdef void *encoder = NULL
    log.info("open_encode_session()")

    #cuda init:
    cuDevice = cuda_init()
    raiseCuda(cuCtxCreate(&cuda_context, 0, cuDevice))
    log.info("CUContext(%s)=%s", cuDevice, hex(<long> cuda_context))
    #raiseCuda(cuCtxPopCurrent(&cuda_context))
    #raiseCuda(cuCtxPushCurrent(&cuda_context))

    #get NVENC function pointers:
    memset(&functionList, 0, sizeof(NV_ENCODE_API_FUNCTION_LIST))
    functionList.version = NV_ENCODE_API_FUNCTION_LIST_VER
    raiseCuda(NvEncodeAPICreateInstance(&functionList), "getting API function list")


    assert functionList.nvEncOpenEncodeSessionEx!=NULL, "looks like NvEncodeAPICreateInstance failed!"

    #NVENC init:
    memset(&params, 0, sizeof(NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS))
    params.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER
    params.deviceType = NV_ENC_DEVICE_TYPE_CUDA
    params.device = <void*> cuda_context
    params.clientKeyPtr = &clientKeyPtr
    params.apiVersion = NVENCAPI_VERSION
    debug("calling nvEncOpenEncodeSessionEx @ %s", hex(<long> functionList.nvEncOpenEncodeSessionEx))
    raiseCuda(functionList.nvEncOpenEncodeSessionEx(&params, &encoder), "opening session")
    log.info("success, encoder context=%s", hex(<long> encoder))

    cdef uint32_t GUIDCount
    cdef uint32_t GUIDRetCount
    cdef GUID* encode_GUIDs
    cdef GUID encode_GUID
    cdef uint32_t presetCount
    cdef uint32_t presetsRetCount
    cdef GUID* preset_GUIDs
    cdef GUID preset_GUID
    cdef NV_ENC_PRESET_CONFIG presetConfig
    cdef NV_ENC_CONFIG encConfig
    cdef uint32_t profileCount
    cdef uint32_t profilesRetCount
    cdef GUID* profile_GUIDs
    cdef GUID profile_GUID
    cdef uint32_t inputFmtCount
    cdef int* inputFmts
    cdef uint32_t inputFmtsRetCount

    raiseCuda(functionList.nvEncGetEncodeGUIDCount(encoder, &GUIDCount))
    log.info("found %s encode GUIDs", GUIDCount)
    assert GUIDCount<2**8
    encode_GUIDs = <GUID*> malloc(sizeof(GUID) * GUIDCount)
    assert encode_GUIDs!=NULL, "could not allocate memory for %s encode GUIDs!" % (GUIDCount)
    try:
        raiseCuda(functionList.nvEncGetEncodeGUIDs(encoder, encode_GUIDs, GUIDCount, &GUIDRetCount), "getting list of encode GUIDs")
        assert GUIDRetCount==GUIDCount, "expected %s items but got %s" % (GUIDCount, GUIDRetCount)
        guids = []
        for x in range(GUIDRetCount):
            encode_GUID = encode_GUIDs[x]
            log.info("EncodeGUID[%s]=%s", x, guidstr(encode_GUID))
            #TODO compare with:
            log.info("NV_ENC_CODEC_H264_GUID=%s", guidstr(NV_ENC_CODEC_H264_GUID))

            raiseCuda(functionList.nvEncGetEncodePresetCount(encoder, encode_GUID, &presetCount), "getting preset count for %s" % guidstr(encode_GUID))
            log.info("%s presets:", presetCount)
            assert presetCount<2**8
            preset_GUIDs = <GUID*> malloc(sizeof(GUID) * presetCount)
            assert encode_GUIDs!=NULL, "could not allocate memory for %s preset GUIDs!" % (presetCount)
            try:
                raiseCuda(functionList.nvEncGetEncodePresetGUIDs(encoder, encode_GUID, preset_GUIDs, presetCount, &presetsRetCount))
                assert presetsRetCount==presetCount
                for x in range(presetCount):
                    preset_GUID = preset_GUIDs[x]
                    log.info("* %s", guidstr(preset_GUID))
                    memset(&presetConfig, 0, sizeof(NV_ENC_PRESET_CONFIG))
                    presetConfig.version = NV_ENC_PRESET_CONFIG_VER
                    raiseCuda(functionList.nvEncGetEncodePresetConfig(encoder, encode_GUID, preset_GUID, &presetConfig), "getting preset config for %s" % guidstr(preset_GUID))
                    encConfig = presetConfig.presetCfg
                    log.info("   gopLength=%s, frameIntervalP=%s", encConfig.gopLength, encConfig.frameIntervalP)
            finally:
                free(preset_GUIDs)

            raiseCuda(functionList.nvEncGetEncodeProfileGUIDCount(encoder, encode_GUID, &profileCount), "getting profile count")
            log.info("%s profiles:", profileCount)
            assert profileCount<2**8
            profile_GUIDs = <GUID*> malloc(sizeof(GUID) * profileCount)
            assert encode_GUIDs!=NULL, "could not allocate memory for %s profile GUIDs!" % (profileCount)
            try:
                raiseCuda(functionList.nvEncGetEncodeProfileGUIDs(encoder, encode_GUID, profile_GUIDs, profileCount, &profilesRetCount))
                #(void* encoder, GUID encodeGUID, GUID* profileGUIDs, uint32_t guidArraySize, uint32_t* GUIDCount)
                assert profilesRetCount==profileCount
                for x in range(profileCount):
                    profile_GUID = profile_GUIDs[x]
                    log.info("* %s", guidstr(profile_GUID))
            finally:
                free(profile_GUIDs)

            raiseCuda(functionList.nvEncGetInputFormatCount(encoder, encode_GUID, &inputFmtCount), "getting input format count")
            log.info("%s input formats:", inputFmtCount)
            assert inputFmtCount>0 and inputFmtCount<2**8
            inputFmts = <int*> malloc(sizeof(int) * inputFmtCount)
            assert inputFmts!=NULL, "could not allocate memory for %s input formats!" % (inputFmtCount)
            try:
                raiseCuda(functionList.nvEncGetInputFormats(encoder, encode_GUID, inputFmts, inputFmtCount, &inputFmtsRetCount), "getting input formats")
                assert inputFmtsRetCount==inputFmtCount
                for x in range(inputFmtCount):
                    log.info("* %s", hex(inputFmts[x]))
            finally:
                free(inputFmts)
    finally:
        free(encode_GUIDs)
    return encoder

cdef closeEncoder(void *encoder):
    global functionList
    functionList.nvEncDestroyEncoder(encoder)

#create one to ensure we can:
cdef void *test_encoder = NULL
try:
    test_encoder = open_encode_session()
except:
    log.error("open_encode_session() failed", exc_info=True)
    raise
closeEncoder(test_encoder)


"""cdef query_encoder_caps(CNvEncoder *encoder):
    cdef int val
    for k in {}.items():
        #NvEncGetEncodeCaps
        pass
    pass
"""


cdef class Encoder:
    cdef int width
    cdef int height
    cdef object src_format
    cdef void *context
    cdef void *inputBuffer
    cdef void *bitstreamBuffer

    def init_context(self, int width, int height, src_format, int quality, int speed, options):    #@DuplicatedSignature
        global functionList
        log.info("init_context%s", (width, height, src_format, quality, speed, options))
        self.width = width
        self.height = height
        self.src_format = src_format
        self.context = open_encode_session()

        cdef NV_ENC_INITIALIZE_PARAMS params
        memset(&params, 0, sizeof(NV_ENC_INITIALIZE_PARAMS))
        params.version = NV_ENC_INITIALIZE_PARAMS_VER
        params.encodeGUID = NV_ENC_CODEC_H264_GUID
        params.encodeWidth = width
        params.encodeHeight = height
        params.enableEncodeAsync = 0
        raiseCuda(functionList.nvEncInitializeEncoder(self.context, &params))
        log.info("encoder initialized")

        #allocate input buffer:
        cdef NV_ENC_CREATE_INPUT_BUFFER createInputBufferParams
        memset(&createInputBufferParams, 0, sizeof(NV_ENC_CREATE_INPUT_BUFFER))
        createInputBufferParams.version = NV_ENC_CREATE_INPUT_BUFFER_VER
        createInputBufferParams.width = roundup(width, 32)
        createInputBufferParams.height = roundup(height, 32)
        createInputBufferParams.memoryHeap = NV_ENC_MEMORY_HEAP_SYSMEM_UNCACHED     #NV_ENC_MEMORY_HEAP_AUTOSELECT
        createInputBufferParams.bufferFmt = NV_ENC_BUFFER_FORMAT_YV12_PL
        raiseCuda(functionList.nvEncCreateInputBuffer(self.context, &createInputBufferParams), "creating input buffer")
        self.inputBuffer = createInputBufferParams.inputBuffer
        log.info("inputBuffer=%s", hex(<long> self.inputBuffer))

        #allocate output buffer:
        cdef NV_ENC_CREATE_BITSTREAM_BUFFER createBitstreamBufferParams
        memset(&createBitstreamBufferParams, 0, sizeof(NV_ENC_CREATE_BITSTREAM_BUFFER))
        createBitstreamBufferParams.version = NV_ENC_CREATE_BITSTREAM_BUFFER_VER
        createBitstreamBufferParams.size = 1024*1024
        createBitstreamBufferParams.memoryHeap = NV_ENC_MEMORY_HEAP_SYSMEM_CACHED
        raiseCuda(functionList.nvEncCreateBitstreamBuffer(self.context, &createBitstreamBufferParams), "creating output buffer")
        self.bitstreamBuffer = createBitstreamBufferParams.bitstreamBuffer
        log.info("bitstreamBuffer=%s", hex(<long> self.bitstreamBuffer))

    def get_info(self):
        cdef float pps
        info = {"width"     : self.width,
                "height"    : self.height,
                "src_format": self.src_format}
        return info

    def __str__(self):
        return "nvenc(%s - %sx%s)" % (self.src_format, self.width, self.height)

    def is_closed(self):
        return self.context==NULL

    def __dealloc__(self):
        self.clean()

    def clean(self):                        #@DuplicatedSignature
        if self.context!=NULL:
            closeEncoder(self.context)
            self.context = NULL

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):                     #@DuplicatedSignature
        return  "nvenc"

    def get_src_format(self):
        return self.src_format

    def get_client_options(self, options):
        return {}

    def compress_image(self, image, options={}):
        assert self.context!=NULL, "context is not initialized"
        return None
