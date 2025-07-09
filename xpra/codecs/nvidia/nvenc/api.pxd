# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Dict, Tuple, List
from collections.abc import Sequence

import binascii
import ctypes

from libc.stdint cimport uint8_t, uint16_t, uint32_t, int32_t, uint64_t   # pylint: disable=syntax-error


cdef inline int MIN(int a, int b) noexcept nogil:
    if a<=b:
        return a
    return b

cdef inline int MAX(int a, int b) noexcept nogil:
    if a>=b:
        return a
    return b


cdef extern from "nvEncodeAPI.h":
    ctypedef void* NV_ENC_INPUT_PTR
    ctypedef void* NV_ENC_OUTPUT_PTR
    ctypedef void* NV_ENC_REGISTERED_PTR

    #not available with driver version 367.35
    #NVENCSTATUS NvEncodeAPIGetMaxSupportedVersion(uint32_t* version)

    ctypedef enum NV_ENC_CAPS:
        NV_ENC_CAPS_NUM_MAX_BFRAMES
        NV_ENC_CAPS_SUPPORTED_RATECONTROL_MODES
        NV_ENC_CAPS_SUPPORT_FIELD_ENCODING
        NV_ENC_CAPS_SUPPORT_MONOCHROME
        NV_ENC_CAPS_SUPPORT_FMO
        NV_ENC_CAPS_SUPPORT_QPELMV
        NV_ENC_CAPS_SUPPORT_BDIRECT_MODE
        NV_ENC_CAPS_SUPPORT_CABAC
        NV_ENC_CAPS_SUPPORT_ADAPTIVE_TRANSFORM
        NV_ENC_CAPS_NUM_MAX_TEMPORAL_LAYERS
        NV_ENC_CAPS_SUPPORT_HIERARCHICAL_PFRAMES
        NV_ENC_CAPS_SUPPORT_HIERARCHICAL_BFRAMES
        NV_ENC_CAPS_LEVEL_MAX
        NV_ENC_CAPS_LEVEL_MIN
        NV_ENC_CAPS_SEPARATE_COLOUR_PLANE
        NV_ENC_CAPS_WIDTH_MAX
        NV_ENC_CAPS_HEIGHT_MAX
        NV_ENC_CAPS_SUPPORT_TEMPORAL_SVC
        NV_ENC_CAPS_SUPPORT_DYN_RES_CHANGE
        NV_ENC_CAPS_SUPPORT_DYN_BITRATE_CHANGE
        NV_ENC_CAPS_SUPPORT_DYN_FORCE_CONSTQP
        NV_ENC_CAPS_SUPPORT_DYN_RCMODE_CHANGE
        NV_ENC_CAPS_SUPPORT_SUBFRAME_READBACK
        NV_ENC_CAPS_SUPPORT_CONSTRAINED_ENCODING
        NV_ENC_CAPS_SUPPORT_INTRA_REFRESH
        NV_ENC_CAPS_SUPPORT_CUSTOM_VBV_BUF_SIZE
        NV_ENC_CAPS_SUPPORT_DYNAMIC_SLICE_MODE
        NV_ENC_CAPS_SUPPORT_REF_PIC_INVALIDATION
        NV_ENC_CAPS_PREPROC_SUPPORT
        NV_ENC_CAPS_ASYNC_ENCODE_SUPPORT
        NV_ENC_CAPS_MB_NUM_MAX
        NV_ENC_CAPS_EXPOSED_COUNT
        NV_ENC_CAPS_SUPPORT_YUV444_ENCODE
        NV_ENC_CAPS_SUPPORT_LOSSLESS_ENCODE
        NV_ENC_CAPS_SUPPORT_SAO
        NV_ENC_CAPS_SUPPORT_MEONLY_MODE
        NV_ENC_CAPS_SUPPORT_LOOKAHEAD
        NV_ENC_CAPS_SUPPORT_TEMPORAL_AQ
        NV_ENC_CAPS_SUPPORT_10BIT_ENCODE
        NV_ENC_CAPS_NUM_MAX_LTR_FRAMES
        NV_ENC_CAPS_SUPPORT_WEIGHTED_PREDICTION
        NV_ENC_CAPS_DYNAMIC_QUERY_ENCODER_CAPACITY
        NV_ENC_CAPS_SUPPORT_BFRAME_REF_MODE
        NV_ENC_CAPS_SUPPORT_EMPHASIS_LEVEL_MAP
        NV_ENC_CAPS_WIDTH_MIN
        NV_ENC_CAPS_HEIGHT_MIN
        NV_ENC_CAPS_SUPPORT_MULTIPLE_REF_FRAMES
        NV_ENC_CAPS_SUPPORT_ALPHA_LAYER_ENCODING
        NV_ENC_CAPS_NUM_ENCODER_ENGINES
        NV_ENC_CAPS_SINGLE_SLICE_INTRA_REFRESH
        NV_ENC_CAPS_DISABLE_ENC_STATE_ADVANCE
        NV_ENC_CAPS_OUTPUT_RECON_SURFACE
        NV_ENC_CAPS_OUTPUT_BLOCK_STATS
        NV_ENC_CAPS_OUTPUT_ROW_STATS
        NV_ENC_CAPS_SUPPORT_TEMPORAL_FILTER
        NV_ENC_CAPS_SUPPORT_LOOKAHEAD_LEVEL
        NV_ENC_CAPS_SUPPORT_UNIDIRECTIONAL_B
        NV_ENC_CAPS_SUPPORT_MVHEVC_ENCODE
        NV_ENC_CAPS_SUPPORT_YUV422_ENCODE

    ctypedef enum NV_ENC_DEVICE_TYPE:
        NV_ENC_DEVICE_TYPE_DIRECTX
        NV_ENC_DEVICE_TYPE_CUDA
        NV_ENC_DEVICE_TYPE_OPENGL

    ctypedef enum NV_ENC_INPUT_RESOURCE_TYPE:
        NV_ENC_INPUT_RESOURCE_TYPE_DIRECTX
        NV_ENC_INPUT_RESOURCE_TYPE_CUDADEVICEPTR
        NV_ENC_INPUT_RESOURCE_TYPE_CUDAARRAY
        NV_ENC_INPUT_RESOURCE_TYPE_OPENGL_TEX

    ctypedef enum NV_ENC_MEMORY_HEAP:
        NV_ENC_MEMORY_HEAP_AUTOSELECT
        NV_ENC_MEMORY_HEAP_VID
        NV_ENC_MEMORY_HEAP_SYSMEM_CACHED
        NV_ENC_MEMORY_HEAP_SYSMEM_UNCACHED

    ctypedef enum NV_ENC_H264_ENTROPY_CODING_MODE:
        NV_ENC_H264_ENTROPY_CODING_MODE_AUTOSELECT
        NV_ENC_H264_ENTROPY_CODING_MODE_CABAC
        NV_ENC_H264_ENTROPY_CODING_MODE_CAVLC

    ctypedef enum NV_ENC_STEREO_PACKING_MODE:
        NV_ENC_STEREO_PACKING_MODE_NONE
        NV_ENC_STEREO_PACKING_MODE_CHECKERBOARD
        NV_ENC_STEREO_PACKING_MODE_COLINTERLEAVE
        NV_ENC_STEREO_PACKING_MODE_ROWINTERLEAVE
        NV_ENC_STEREO_PACKING_MODE_SIDEBYSIDE
        NV_ENC_STEREO_PACKING_MODE_TOPBOTTOM
        NV_ENC_STEREO_PACKING_MODE_FRAMESEQ

    ctypedef enum NV_ENC_H264_FMO_MODE:
        NV_ENC_H264_FMO_AUTOSELECT
        NV_ENC_H264_FMO_ENABLE
        NV_ENC_H264_FMO_DISABLE

    ctypedef enum NV_ENC_H264_BDIRECT_MODE:
        NV_ENC_H264_BDIRECT_MODE_AUTOSELECT
        NV_ENC_H264_BDIRECT_MODE_DISABLE
        NV_ENC_H264_BDIRECT_MODE_TEMPORAL
        NV_ENC_H264_BDIRECT_MODE_SPATIAL

    ctypedef enum NV_ENC_H264_ADAPTIVE_TRANSFORM_MODE:
        NV_ENC_H264_ADAPTIVE_TRANSFORM_AUTOSELECT
        NV_ENC_H264_ADAPTIVE_TRANSFORM_DISABLE
        NV_ENC_H264_ADAPTIVE_TRANSFORM_ENABLE

    ctypedef enum NV_ENC_PARAMS_FRAME_FIELD_MODE:
        NV_ENC_PARAMS_FRAME_FIELD_MODE_FRAME
        NV_ENC_PARAMS_FRAME_FIELD_MODE_FIELD
        NV_ENC_PARAMS_FRAME_FIELD_MODE_MBAFF

    ctypedef enum NV_ENC_BUFFER_FORMAT:
        NV_ENC_BUFFER_FORMAT_UNDEFINED
        NV_ENC_BUFFER_FORMAT_NV12
        NV_ENC_BUFFER_FORMAT_YV12
        NV_ENC_BUFFER_FORMAT_IYUV
        NV_ENC_BUFFER_FORMAT_YUV444
        NV_ENC_BUFFER_FORMAT_YUV420_10BIT
        NV_ENC_BUFFER_FORMAT_YUV444_10BIT
        NV_ENC_BUFFER_FORMAT_ARGB
        NV_ENC_BUFFER_FORMAT_ARGB10
        NV_ENC_BUFFER_FORMAT_AYUV
        NV_ENC_BUFFER_FORMAT_ABGR
        NV_ENC_BUFFER_FORMAT_ABGR10
        NV_ENC_BUFFER_FORMAT_U8
        NV_ENC_BUFFER_FORMAT_NV16
        NV_ENC_BUFFER_FORMAT_P210

    ctypedef enum NV_ENC_PIC_FLAGS:
        NV_ENC_PIC_FLAG_FORCEINTRA
        NV_ENC_PIC_FLAG_FORCEIDR
        NV_ENC_PIC_FLAG_OUTPUT_SPSPPS
        NV_ENC_PIC_FLAG_EOS
        NV_ENC_PIC_FLAG_DISABLE_ENC_STATE_ADVANCE
        NV_ENC_PIC_FLAG_OUTPUT_RECON_FRAME

    ctypedef enum NV_ENC_PIC_STRUCT:
        NV_ENC_PIC_STRUCT_FRAME
        NV_ENC_PIC_STRUCT_FIELD_TOP_BOTTOM
        NV_ENC_PIC_STRUCT_FIELD_BOTTOM_TOP

    ctypedef enum NV_ENC_PIC_TYPE:
        NV_ENC_PIC_TYPE_P
        NV_ENC_PIC_TYPE_B
        NV_ENC_PIC_TYPE_I
        NV_ENC_PIC_TYPE_IDR
        NV_ENC_PIC_TYPE_BI
        NV_ENC_PIC_TYPE_SKIPPED
        NV_ENC_PIC_TYPE_INTRA_REFRESH
        NV_ENC_PIC_TYPE_NONREF_P
        NV_ENC_PIC_TYPE_SWITCH
        NV_ENC_PIC_TYPE_UNKNOWN

    ctypedef enum NV_ENC_SLICE_TYPE:
        NV_ENC_SLICE_TYPE_DEFAULT
        NV_ENC_SLICE_TYPE_I
        NV_ENC_SLICE_TYPE_UNKNOWN

    ctypedef enum  NV_ENC_MV_PRECISION:
        NV_ENC_MV_PRECISION_FULL_PEL
        NV_ENC_MV_PRECISION_HALF_PEL
        NV_ENC_MV_PRECISION_QUARTER_PEL

    ctypedef enum NV_ENC_LEVEL:
        NV_ENC_LEVEL_AUTOSELECT
        # H264:
        NV_ENC_LEVEL_H264_1
        NV_ENC_LEVEL_H264_1b
        NV_ENC_LEVEL_H264_11
        NV_ENC_LEVEL_H264_12
        NV_ENC_LEVEL_H264_13
        NV_ENC_LEVEL_H264_2
        NV_ENC_LEVEL_H264_21
        NV_ENC_LEVEL_H264_22
        NV_ENC_LEVEL_H264_3
        NV_ENC_LEVEL_H264_31
        NV_ENC_LEVEL_H264_32
        NV_ENC_LEVEL_H264_4
        NV_ENC_LEVEL_H264_41
        NV_ENC_LEVEL_H264_42
        NV_ENC_LEVEL_H264_5
        NV_ENC_LEVEL_H264_51
        NV_ENC_LEVEL_H264_52
        NV_ENC_LEVEL_H264_60
        NV_ENC_LEVEL_H264_61
        NV_ENC_LEVEL_H264_62
        # HEVC:
        NV_ENC_LEVEL_HEVC_1
        NV_ENC_LEVEL_HEVC_2
        NV_ENC_LEVEL_HEVC_21
        NV_ENC_LEVEL_HEVC_3
        NV_ENC_LEVEL_HEVC_31
        NV_ENC_LEVEL_HEVC_4
        NV_ENC_LEVEL_HEVC_41
        NV_ENC_LEVEL_HEVC_5
        NV_ENC_LEVEL_HEVC_51
        NV_ENC_LEVEL_HEVC_52
        NV_ENC_LEVEL_HEVC_6
        NV_ENC_LEVEL_HEVC_61
        NV_ENC_LEVEL_HEVC_62
        NV_ENC_TIER_HEVC_MAIN
        NV_ENC_TIER_HEVC_HIGH
        # AV1:
        NV_ENC_LEVEL_AV1_2
        NV_ENC_LEVEL_AV1_21
        NV_ENC_LEVEL_AV1_22
        NV_ENC_LEVEL_AV1_23
        NV_ENC_LEVEL_AV1_3
        NV_ENC_LEVEL_AV1_31
        NV_ENC_LEVEL_AV1_32
        NV_ENC_LEVEL_AV1_33
        NV_ENC_LEVEL_AV1_4
        NV_ENC_LEVEL_AV1_41
        NV_ENC_LEVEL_AV1_42
        NV_ENC_LEVEL_AV1_43
        NV_ENC_LEVEL_AV1_5
        NV_ENC_LEVEL_AV1_51
        NV_ENC_LEVEL_AV1_52
        NV_ENC_LEVEL_AV1_53
        NV_ENC_LEVEL_AV1_6
        NV_ENC_LEVEL_AV1_61
        NV_ENC_LEVEL_AV1_62
        NV_ENC_LEVEL_AV1_63
        NV_ENC_LEVEL_AV1_7
        NV_ENC_LEVEL_AV1_71
        NV_ENC_LEVEL_AV1_72
        NV_ENC_LEVEL_AV1_73
        NV_ENC_LEVEL_AV1_AUTOSELECT

        NV_ENC_TIER_AV1_0
        NV_ENC_TIER_AV1_1

    ctypedef enum NV_ENC_PARAMS_RC_MODE:
        NV_ENC_PARAMS_RC_CONSTQP            #Constant QP mode
        NV_ENC_PARAMS_RC_VBR                #Variable bitrate mode
        NV_ENC_PARAMS_RC_CBR                #Constant bitrate mode
        NV_ENC_PARAMS_RC_CBR_LOWDELAY_HQ    #low-delay CBR, high quality
        NV_ENC_PARAMS_RC_CBR_HQ             #CBR, high quality (slower)
        NV_ENC_PARAMS_RC_VBR_HQ
        #SDK 7 names (deprecated):
        NV_ENC_PARAMS_RC_VBR_MINQP          #Variable bitrate mode with MinQP
        NV_ENC_PARAMS_RC_2_PASS_QUALITY     #Multi pass encoding optimized for image quality and works only with low latency mode
        NV_ENC_PARAMS_RC_2_PASS_FRAMESIZE_CAP   #Multi pass encoding optimized for maintaining frame size and works only with low latency mode
        NV_ENC_PARAMS_RC_2_PASS_VBR         #Multi pass VBR
        NV_ENC_PARAMS_RC_CBR2               #(deprecated)

    ctypedef enum NV_ENC_HEVC_CUSIZE:
        NV_ENC_HEVC_CUSIZE_AUTOSELECT
        NV_ENC_HEVC_CUSIZE_8x8
        NV_ENC_HEVC_CUSIZE_16x16
        NV_ENC_HEVC_CUSIZE_32x32
        NV_ENC_HEVC_CUSIZE_64x64


    ctypedef struct NV_ENC_LOCK_BITSTREAM:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_LOCK_BITSTREAM_VER.
        uint32_t    doNotWait           #[in]: If this flag is set, the NvEncodeAPI interface will return buffer pointer even if operation is not completed. If not set, the call will block until operation completes.
        uint32_t    ltrFrame            #[out]: Flag indicating this frame is marked as LTR frame
        uint32_t    reservedBitFields   #[in]: Reserved bit fields and must be set to 0
        void*       outputBitstream     #[in]: Pointer to the bitstream buffer being locked.
        uint32_t*   sliceOffsets        #[in,out]: Array which receives the slice offsets. Currently used only when NV_ENC_CONFIG_H264::sliceMode == 3. Array size must be equal to NV_ENC_CONFIG_H264::sliceModeData.
        uint32_t    frameIdx            #[out]: Frame no. for which the bitstream is being retrieved.
        uint32_t    hwEncodeStatus      #[out]: The NvEncodeAPI interface status for the locked picture.
        uint32_t    numSlices           #[out]: Number of slices in the encoded picture. Will be reported only if NV_ENC_INITIALIZE_PARAMS::reportSliceOffsets set to 1.
        uint32_t    bitstreamSizeInBytes#[out]: Actual number of bytes generated and copied to the memory pointed by bitstreamBufferPtr.
        uint64_t    outputTimeStamp     #[out]: Presentation timestamp associated with the encoded output.
        uint64_t    outputDuration      #[out]: Presentation duration associates with the encoded output.
        void*       bitstreamBufferPtr  #[out]: Pointer to the generated output bitstream. Client should allocate sufficiently large buffer to hold the encoded output. Client is responsible for managing this memory.
        NV_ENC_PIC_TYPE     pictureType #[out]: Picture type of the encoded picture.
        NV_ENC_PIC_STRUCT   pictureStruct   #[out]: Structure of the generated output picture.
        uint32_t    frameAvgQP          #[out]: Average QP of the frame.
        uint32_t    frameSatd           #[out]: Total SATD cost for whole frame.
        uint32_t    ltrFrameIdx         #[out]: Frame index associated with this LTR frame.
        uint32_t    ltrFrameBitmap      #[out]: Bitmap of LTR frames indices which were used for encoding this frame. Value of 0 if no LTR frames were used.
        uint32_t    reserved[236]       #[in]: Reserved and must be set to 0
        void*       reserved2[64]       #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_LOCK_INPUT_BUFFER:
        uint32_t    version             #[in]:  Struct version. Must be set to ::NV_ENC_LOCK_INPUT_BUFFER_VER.
        uint32_t    doNotWait           #[in]:  Set to 1 to make ::NvEncLockInputBuffer() a unblocking call. If the encoding is not completed, driver will return ::NV_ENC_ERR_ENCODER_BUSY error code.
        uint32_t    reservedBitFields   #[in]:  Reserved bitfields and must be set to 0
        NV_ENC_INPUT_PTR inputBuffer    #[in]:  Pointer to the input buffer to be locked, client should pass the pointer obtained from ::NvEncCreateInputBuffer() or ::NvEncMapInputResource API.
        void*       bufferDataPtr       #[out]: Pointed to the locked input buffer data. Client can only access input buffer using the \p bufferDataPtr.
        uint32_t    pitch               #[out]: Pitch of the locked input buffer.
        uint32_t    reserved1[251]      #[in]:  Reserved and must be set to 0
        void*       reserved2[64]       #[in]:  Reserved and must be set to NULL

    ctypedef struct NV_ENC_STAT:
        uint32_t    version             #[in]:  Struct version. Must be set to ::NV_ENC_STAT_VER.
        uint32_t    reserved            #[in]:  Reserved and must be set to 0
        NV_ENC_OUTPUT_PTR outputBitStream   #[out]: Specifies the pointer to output bitstream.
        uint32_t    bitStreamSize       #[out]: Size of generated bitstream in bytes.
        uint32_t    picType             #[out]: Picture type of encoded picture. See ::NV_ENC_PIC_TYPE.
        uint32_t    lastValidByteOffset #[out]: Offset of last valid bytes of completed bitstream
        uint32_t    sliceOffsets[16]    #[out]: Offsets of each slice
        uint32_t    picIdx              #[out]: Picture number
        uint32_t    reserved1[233]      #[in]:  Reserved and must be set to 0
        void*       reserved2[64]       #[in]:  Reserved and must be set to NULL

    ctypedef struct NV_ENC_SEQUENCE_PARAM_PAYLOAD:
        pass
    ctypedef struct NV_ENC_EVENT_PARAMS:
        pass
    ctypedef struct NV_ENC_MAP_INPUT_RESOURCE:
        uint32_t    version             #[in]:  Struct version. Must be set to ::NV_ENC_MAP_INPUT_RESOURCE_VER.
        uint32_t    subResourceIndex    #[in]:  Deprecated. Do not use.
        void*       inputResource       #[in]:  Deprecated. Do not use.
        NV_ENC_REGISTERED_PTR registeredResource    #[in]:  The Registered resource handle obtained by calling NvEncRegisterInputResource.
        NV_ENC_INPUT_PTR mappedResource #[out]: Mapped pointer corresponding to the registeredResource. This pointer must be used in NV_ENC_PIC_PARAMS::inputBuffer parameter in ::NvEncEncodePicture() API.
        NV_ENC_BUFFER_FORMAT mappedBufferFmt    #[out]: Buffer format of the outputResource. This buffer format must be used in NV_ENC_PIC_PARAMS::bufferFmt if client using the above mapped resource pointer.
        uint32_t    reserved1[251]      #[in]:  Reserved and must be set to 0.
        void*       reserved2[63]       #[in]:  Reserved and must be set to NULL
    ctypedef struct NV_ENC_REGISTER_RESOURCE:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_REGISTER_RESOURCE_VER.
        NV_ENC_INPUT_RESOURCE_TYPE  resourceType    #[in]: Specifies the type of resource to be registered. Supported values are ::NV_ENC_INPUT_RESOURCE_TYPE_DIRECTX, ::NV_ENC_INPUT_RESOURCE_TYPE_CUDADEVICEPTR.
        uint32_t    width               #[in]: Input buffer Width.
        uint32_t    height              #[in]: Input buffer Height.
        uint32_t    pitch               #[in]: Input buffer Pitch.
        uint32_t    subResourceIndex    #[in]: Subresource Index of the DirectX resource to be registered. Should eb set to 0 for other interfaces.
        void*       resourceToRegister  #[in]: Handle to the resource that is being registered.
        NV_ENC_REGISTERED_PTR   registeredResource  #[out]: Registered resource handle. This should be used in future interactions with the Nvidia Video Encoder Interface.
        NV_ENC_BUFFER_FORMAT    bufferFormat        #[in]: Buffer format of resource to be registered.
        uint32_t    reserved1[248]      #[in]: Reserved and must be set to 0.
        void*       reserved2[62]       #[in]: Reserved and must be set to NULL.

    ctypedef struct GUID:
        uint32_t Data1
        uint16_t Data2
        uint16_t Data3
        uint8_t  Data4[8]

    #Encode Codec GUIDS supported by the NvEncodeAPI interface.
    GUID NV_ENC_CODEC_H264_GUID
    GUID NV_ENC_CODEC_HEVC_GUID
    GUID NV_ENC_CODEC_AV1_GUID

    #Profiles:
    GUID NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID
    GUID NV_ENC_H264_PROFILE_BASELINE_GUID
    GUID NV_ENC_H264_PROFILE_MAIN_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_10_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_422_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_444_GUID
    GUID NV_ENC_H264_PROFILE_STEREO_GUID
    #GUID NV_ENC_H264_PROFILE_SVC_TEMPORAL_SCALABILTY
    GUID NV_ENC_H264_PROFILE_PROGRESSIVE_HIGH_GUID
    GUID NV_ENC_H264_PROFILE_CONSTRAINED_HIGH_GUID

    GUID NV_ENC_HEVC_PROFILE_MAIN_GUID
    GUID NV_ENC_HEVC_PROFILE_MAIN10_GUID
    GUID NV_ENC_HEVC_PROFILE_FREXT_GUID

    GUID NV_ENC_AV1_PROFILE_MAIN_GUID

    #Presets:
    GUID NV_ENC_PRESET_P1_GUID  #FC0A8D3E-45F8-4CF8-80C7-298871590EBF
    GUID NV_ENC_PRESET_P2_GUID  #F581CFB8-88D6-4381-93F0-DF13F9C27DAB
    GUID NV_ENC_PRESET_P3_GUID  #36850110-3A07-441F-94D5-3670631F91F6
    GUID NV_ENC_PRESET_P4_GUID  #90A7B826-DF06-4862-B9D2-CD6D73A08681
    GUID NV_ENC_PRESET_P5_GUID  #21C6E6B4-297A-4CBA-998F-B6CBDE72ADE3
    GUID NV_ENC_PRESET_P6_GUID  #8E75C279-6299-4AB6-8302-0B215A335CF5
    GUID NV_ENC_PRESET_P7_GUID  #84848C12-6F71-4C13-931B-53E283F57974

    ctypedef struct NV_ENC_CAPS_PARAM:
        uint32_t    version
        uint32_t    capsToQuery
        uint32_t    reserved[62]

    ctypedef struct NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS:
        uint32_t    version         #[in]: Struct version. Must be set to ::NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER.
        NV_ENC_DEVICE_TYPE deviceType   #[in]: (NV_ENC_DEVICE_TYPE) Specified the device Type
        void        *device         #[in]: Pointer to client device.
        GUID        *reserved       #[in]: Pointer to a GUID key issued to the client.
        uint32_t    apiVersion      #[in]: API version. Should be set to NVENCAPI_VERSION.
        uint32_t    reserved1[253]  #[in]: Reserved and must be set to 0
        void        *reserved2[64]  #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CREATE_INPUT_BUFFER:
        uint32_t    version         #[in]: Struct version. Must be set to ::NV_ENC_CREATE_INPUT_BUFFER_VER
        uint32_t    width           #[in]: Input buffer width
        uint32_t    height          #[in]: Input buffer width
        NV_ENC_MEMORY_HEAP memoryHeap       #[in]: Deprecated. Do not use
        NV_ENC_BUFFER_FORMAT bufferFmt      #[in]: Input buffer format
        uint32_t    reserved        #[in]: Reserved and must be set to 0
        void        *inputBuffer    #[out]: Pointer to input buffer
        void        *pSysMemBuffer  #[in]: Pointer to existing sysmem buffer
        uint32_t    reserved1[57]   #[in]: Reserved and must be set to 0
        void        *reserved2[63]  #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CREATE_BITSTREAM_BUFFER:
        uint32_t    version         #[in]: Struct version. Must be set to ::NV_ENC_CREATE_BITSTREAM_BUFFER_VER
        uint32_t    size            #[in]: Size of the bitstream buffer to be created
        NV_ENC_MEMORY_HEAP memoryHeap      #[in]: Deprecated. Do not use
        uint32_t    reserved        #[in]: Reserved and must be set to 0
        void        *bitstreamBuffer#[out]: Pointer to the output bitstream buffer
        void        *bitstreamBufferPtr #[out]: Reserved and should not be used
        uint32_t    reserved1[58]   #[in]: Reserved and should be set to 0
        void*       reserved2[64]   #[in]: Reserved and should be set to NULL

    ctypedef struct NV_ENC_QP:
        uint32_t    qpInterP
        uint32_t    qpInterB
        uint32_t    qpIntra

    ctypedef struct NV_ENC_CONFIG_HEVC_VUI_PARAMETERS:
        uint32_t    overscanInfoPresentFlag         #[in]: if set to 1 , it specifies that the overscanInfo is present
        uint32_t    overscanInfo                    #[in]: Specifies the overscan info(as defined in Annex E of the ITU-T Specification).
        uint32_t    videoSignalTypePresentFlag      #[in]: If set to 1, it specifies  that the videoFormat, videoFullRangeFlag and colourDescriptionPresentFlag are present.
        uint32_t    videoFormat                     #[in]: Specifies the source video format(as defined in Annex E of the ITU-T Specification)
        uint32_t    videoFullRangeFlag              #[in]: Specifies the output range of the luma and chroma samples(as defined in Annex E of the ITU-T Specification).
        uint32_t    colourDescriptionPresentFlag    #[in]: If set to 1, it specifies that the colourPrimaries, transferCharacteristics and colourMatrix are present.
        uint32_t    colourPrimaries                 #[in]: Specifies color primaries for converting to RGB(as defined in Annex E of the ITU-T Specification)
        uint32_t    transferCharacteristics         #[in]: Specifies the opto-electronic transfer characteristics to use (as defined in Annex E of the ITU-T Specification)
        uint32_t    colourMatrix                    #[in]: Specifies the matrix coefficients used in deriving the luma and chroma from the RGB primaries (as defined in Annex E of the ITU-T Specification).
        uint32_t    chromaSampleLocationFlag        #[in]: if set to 1 , it specifies that the chromaSampleLocationTop and chromaSampleLocationBot are present
        uint32_t    chromaSampleLocationTop         #[in]: Specifies the chroma sample location for top field(as defined in Annex E of the ITU-T Specification)
        uint32_t    chromaSampleLocationBot         #[in]: Specifies the chroma sample location for bottom field(as defined in Annex E of the ITU-T Specification)
        uint32_t    bitstreamRestrictionFlag        #[in]: if set to 1, it specifies the bitstream restriction parameters are present in the bitstream.
        uint32_t    reserved[15]

    ctypedef struct NV_ENC_CONFIG_H264_VUI_PARAMETERS:
        uint32_t    overscanInfoPresentFlag         #[in]: if set to 1 , it specifies that the overscanInfo is present
        uint32_t    overscanInfo                    #[in]: Specifies the overscan info(as defined in Annex E of the ITU-T Specification).
        uint32_t    videoSignalTypePresentFlag      #[in]: If set to 1, it specifies  that the videoFormat, videoFullRangeFlag and colourDescriptionPresentFlag are present.
        uint32_t    videoFormat                     #[in]: Specifies the source video format(as defined in Annex E of the ITU-T Specification).
        uint32_t    videoFullRangeFlag              #[in]: Specifies the output range of the luma and chroma samples(as defined in Annex E of the ITU-T Specification).
        uint32_t    colourDescriptionPresentFlag    #[in]: If set to 1, it specifies that the colourPrimaries, transferCharacteristics and colourMatrix are present.
        uint32_t    colourPrimaries                 #[in]: Specifies color primaries for converting to RGB(as defined in Annex E of the ITU-T Specification)
        uint32_t    transferCharacteristics         #[in]: Specifies the opto-electronic transfer characteristics to use (as defined in Annex E of the ITU-T Specification)
        uint32_t    colourMatrix                    #[in]: Specifies the matrix coefficients used in deriving the luma and chroma from the RGB primaries (as defined in Annex E of the ITU-T Specification).
        uint32_t    chromaSampleLocationFlag        #[in]: if set to 1 , it specifies that thechromaSampleLocationTop and chromaSampleLocationBot are present.
        uint32_t    chromaSampleLocationTop         #[in]: Specifies the chroma sample location for top field(as defined in Annex E of the ITU-T Specification)
        uint32_t    chromaSampleLocationBot         #[in]: Specifies the chroma sample location for bottom field(as defined in Annex E of the ITU-T Specification)
        uint32_t    bitstreamRestrictionFlag        #[in]: if set to 1, it specifies the bitstream restriction parameters are present in the bitstream.
        uint32_t    reserved[15]

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
        uint32_t    enableLTR           #[in]: Currently this feature is not available and must be set to 0. Set to 1 to enable LTR support and auto-mark the first
        uint32_t    qpPrimeYZeroTransformBypassFlag #[in]  To enable lossless encode set this to 1, set QP to 0 and RC_mode to NV_ENC_PARAMS_RC_CONSTQP and profile to HIGH_444_PREDICTIVE_PROFILE
                                                    #Check support for lossless encoding using ::NV_ENC_CAPS_SUPPORT_LOSSLESS_ENCODE caps.
        uint32_t    useConstrainedIntraPred         #[in]: Set 1 to enable constrained intra prediction.
        uint32_t    reservedBitFields[15]       #[in]: Reserved bitfields and must be set to 0
        uint32_t    level               #[in]: Specifies the encoding level. Client is recommended to set this to NV_ENC_LEVEL_AUTOSELECT in order to enable the NvEncodeAPI interface to select the correct level.
        uint32_t    idrPeriod           #[in]: Specifies the IDR interval. If not set, this is made equal to gopLength in NV_ENC_CONFIG.Low latency application client can set IDR interval to NVENC_INFINITE_GOPLENGTH so that IDR frames are not inserted automatically.
        uint32_t    separateColourPlaneFlag     #[in]: Set to 1 to enable 4:4:4 separate colour planes
        uint32_t    disableDeblockingFilterIDC  #[in]: Specifies the deblocking filter mode. Permissible value range: [0,2]
        uint32_t    numTemporalLayers   #[in]: Specifies max temporal layers to be used for hierarchical coding. Valid value range is [1,::NV_ENC_CAPS_NUM_MAX_TEMPORAL_LAYERS]
        uint32_t    spsId               #[in]: Specifies the SPS id of the sequence header.
        uint32_t    ppsId               #[in]: Specifies the PPS id of the picture header.
        NV_ENC_H264_ADAPTIVE_TRANSFORM_MODE adaptiveTransformMode   #[in]: Specifies the AdaptiveTransform Mode. Check support for AdaptiveTransform mode using ::NV_ENC_CAPS_SUPPORT_ADAPTIVE_TRANSFORM caps.
        NV_ENC_H264_FMO_MODE fmoMode    #[in]: Specified the FMO Mode. Check support for FMO using ::NV_ENC_CAPS_SUPPORT_FMO caps.
        NV_ENC_H264_BDIRECT_MODE bdirectMode    #[in]: Specifies the BDirect mode. Check support for BDirect mode using ::NV_ENC_CAPS_SUPPORT_BDIRECT_MODE caps.
        NV_ENC_H264_ENTROPY_CODING_MODE entropyCodingMode   #[in]: Specifies the entropy coding mode. Check support for CABAC mode using ::NV_ENC_CAPS_SUPPORT_CABAC caps.
        NV_ENC_STEREO_PACKING_MODE stereoMode   #[in]: Specifies the stereo frame packing mode which is to be signalled in frame packing arrangement SEI
        uint32_t    intraRefreshPeriod  #[in]: Specifies the interval between successive intra refresh if enableIntrarefresh is set. Requires enableIntraRefresh to be set.
                                        #Will be disabled if NV_ENC_CONFIG::gopLength is not set to NVENC_INFINITE_GOPLENGTH.
        uint32_t    intraRefreshCnt     #[in]: Specifies the length of intra refresh in number of frames for periodic intra refresh. This value should be smaller than intraRefreshPeriod
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
        NV_ENC_CONFIG_H264_VUI_PARAMETERS h264VUIParameters   #[in]: Specifies the H264 video usability info pamameters
        uint32_t    ltrNumFrames        #[in]: Specifies the number of LTR frames used. Additionally, encoder will mark the first numLTRFrames base layer reference frames within each IDR interval as LTR
        uint32_t    ltrTrustMode        #[in]: Specifies the LTR operating mode. Set to 0 to disallow encoding using LTR frames until later specified. Set to 1 to allow encoding using LTR frames unless later invalidated.
        uint32_t    chromaFormatIDC     #[in]: Specifies the chroma format. Should be set to 1 for yuv420 input, 3 for yuv444 input.
                                        #Check support for YUV444 encoding using ::NV_ENC_CAPS_SUPPORT_YUV444_ENCODE caps.
        uint32_t    maxTemporalLayers   #[in]: Specifies the max temporal layer used for hierarchical coding.
        uint32_t    reserved1[270]      #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CONFIG_HEVC:
        uint32_t    level               #[in]: Specifies the level of the encoded bitstream.
        uint32_t    tier                #[in]: Specifies the level tier of the encoded bitstream.
        NV_ENC_HEVC_CUSIZE minCUSize    #[in]: Specifies the minimum size of luma coding unit.
        NV_ENC_HEVC_CUSIZE maxCUSize    #[in]: Specifies the maximum size of luma coding unit. Currently NVENC SDK only supports maxCUSize equal to NV_ENC_HEVC_CUSIZE_32x32.
        uint32_t    useConstrainedIntraPred             #[in]: Set 1 to enable constrained intra prediction.
        uint32_t    disableDeblockAcrossSliceBoundary   #[in]: Set 1 to disable in loop filtering across slice boundary.
        uint32_t    outputBufferingPeriodSEI            #[in]: Set 1 to write SEI buffering period syntax in the bitstream
        uint32_t    outputPictureTimingSEI              #[in]: Set 1 to write SEI picture timing syntax in the bitstream
        uint32_t    outputAUD                           #[in]: Set 1 to write Access Unit Delimiter syntax.
        uint32_t    enableLTR                           #[in]: Set 1 to enable use of long term reference pictures for inter prediction.
        uint32_t    disableSPSPPS                       #[in]: Set 1 to disable VPS,SPS and PPS signalling in the bitstream.
        uint32_t    repeatSPSPPS                        #[in]: Set 1 to output VPS,SPS and PPS for every IDR frame.
        uint32_t    enableIntraRefresh                  #[in]: Set 1 to enable gradual decoder refresh or intra refresh. If the GOP structure uses B frames this will be ignored
        uint32_t    chromaFormatIDC                     #[in]: Specifies the chroma format. Should be set to 1 for yuv420 input, 3 for yuv444 input.
        uint32_t    pixelBitDepthMinus8                 #[in]: Specifies pixel bit depth minus 8. Should be set to 0 for 8 bit input, 2 for 10 bit input.
        uint32_t    reserved                            #[in]: Reserved bitfields.
        uint32_t    idrPeriod                           #[in]: Specifies the IDR interval. If not set, this is made equal to gopLength in NV_ENC_CONFIG.Low latency application client can set IDR interval to NVENC_INFINITE_GOPLENGTH so that IDR frames are not inserted automatically.
        uint32_t    intraRefreshPeriod                  #[in]: Specifies the interval between successive intra refresh if enableIntrarefresh is set. Requires enableIntraRefresh to be set.
                                                        #Will be disabled if NV_ENC_CONFIG::gopLength is not set to NVENC_INFINITE_GOPLENGTH.
        uint32_t    intraRefreshCnt                     #[in]: Specifies the length of intra refresh in number of frames for periodic intra refresh. This value should be smaller than intraRefreshPeriod
        uint32_t    maxNumRefFramesInDPB                #[in]: Specifies the maximum number of references frames in the DPB.
        uint32_t    ltrNumFrames                        #[in]: Specifies the maximum number of long term references can be used for prediction
        uint32_t    vpsId                               #[in]: Specifies the VPS id of the video parameter set. Currently reserved and must be set to 0.
        uint32_t    spsId                               #[in]: Specifies the SPS id of the sequence header. Currently reserved and must be set to 0.
        uint32_t    ppsId                               #[in]: Specifies the PPS id of the picture header. Currently reserved and must be set to 0.
        uint32_t    sliceMode                           #[in]: This parameter in conjunction with sliceModeData specifies the way in which the picture is divided into slices
                                                        #sliceMode = 0 CTU based slices, sliceMode = 1 Byte based slices, sliceMode = 2 CTU row based slices, sliceMode = 3, numSlices in Picture
                                                        #When sliceMode == 0 and sliceModeData == 0 whole picture will be coded with one slice
        uint32_t    sliceModeData                       #[in]: Specifies the parameter needed for sliceMode. For:
                                                        #sliceMode = 0, sliceModeData specifies # of CTUs in each slice (except last slice)
                                                        #sliceMode = 1, sliceModeData specifies maximum # of bytes in each slice (except last slice)
                                                        #sliceMode = 2, sliceModeData specifies # of CTU rows in each slice (except last slice)
                                                        #sliceMode = 3, sliceModeData specifies number of slices in the picture. Driver will divide picture into slices optimally
        uint32_t    maxTemporalLayersMinus1             #[in]: Specifies the max temporal layer used for hierarchical coding.
        NV_ENC_CONFIG_HEVC_VUI_PARAMETERS hevcVUIParameters #Specifies the HEVC video usability info pamameters
        uint32_t    reserved1[218]                      #[in]: Reserved and must be set to 0.
        void*       reserved2[64]                       #[in]: Reserved and must be set to NULL

    ctypedef enum NV_ENC_BFRAME_REF_MODE:
        NV_ENC_BFRAME_REF_MODE_DISABLED
        NV_ENC_BFRAME_REF_MODE_EACH
        NV_ENC_BFRAME_REF_MODE_MIDDLE

    ctypedef struct NV_ENC_FILM_GRAIN_PARAMS_AV1:
        pass

    ctypedef enum NV_ENC_AV1_PART_SIZE:
        NV_ENC_AV1_PART_SIZE_AUTOSELECT
        NV_ENC_AV1_PART_SIZE_4x4
        NV_ENC_AV1_PART_SIZE_8x8
        NV_ENC_AV1_PART_SIZE_16x16
        NV_ENC_AV1_PART_SIZE_32x32
        NV_ENC_AV1_PART_SIZE_64x64

    ctypedef enum NV_ENC_VUI_COLOR_PRIMARIES:
        NV_ENC_VUI_COLOR_PRIMARIES_UNDEFINED
        NV_ENC_VUI_COLOR_PRIMARIES_BT709
        NV_ENC_VUI_COLOR_PRIMARIES_UNSPECIFIED
        NV_ENC_VUI_COLOR_PRIMARIES_RESERVED
        NV_ENC_VUI_COLOR_PRIMARIES_BT470M
        NV_ENC_VUI_COLOR_PRIMARIES_BT470BG
        NV_ENC_VUI_COLOR_PRIMARIES_SMPTE170M
        NV_ENC_VUI_COLOR_PRIMARIES_SMPTE240M
        NV_ENC_VUI_COLOR_PRIMARIES_FILM
        NV_ENC_VUI_COLOR_PRIMARIES_BT2020
        NV_ENC_VUI_COLOR_PRIMARIES_SMPTE428
        NV_ENC_VUI_COLOR_PRIMARIES_SMPTE431
        NV_ENC_VUI_COLOR_PRIMARIES_SMPTE432
        NV_ENC_VUI_COLOR_PRIMARIES_JEDEC_P22

    ctypedef enum NV_ENC_VUI_TRANSFER_CHARACTERISTIC:
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_UNDEFINED
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT709
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_UNSPECIFIED
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_RESERVED
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT470M
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT470BG
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_SMPTE170M
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_SMPTE240M
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_LINEAR
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_LOG
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_LOG_SQRT
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_IEC61966_2_4
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT1361_ECG
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_SRGB
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT2020_10
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT2020_12
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_SMPTE2084
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_SMPTE428
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC_ARIB_STD_B67

    ctypedef enum NV_ENC_VUI_MATRIX_COEFFS:
        NV_ENC_VUI_MATRIX_COEFFS_RGB
        NV_ENC_VUI_MATRIX_COEFFS_BT709
        NV_ENC_VUI_MATRIX_COEFFS_UNSPECIFIED
        NV_ENC_VUI_MATRIX_COEFFS_RESERVED
        NV_ENC_VUI_MATRIX_COEFFS_FCC
        NV_ENC_VUI_MATRIX_COEFFS_BT470BG
        NV_ENC_VUI_MATRIX_COEFFS_SMPTE170M
        NV_ENC_VUI_MATRIX_COEFFS_SMPTE240M
        NV_ENC_VUI_MATRIX_COEFFS_YCGCO
        NV_ENC_VUI_MATRIX_COEFFS_BT2020_NCL
        NV_ENC_VUI_MATRIX_COEFFS_BT2020_CL
        NV_ENC_VUI_MATRIX_COEFFS_SMPTE2085

    ctypedef enum NV_ENC_NUM_REF_FRAMES:
        NV_ENC_NUM_REF_FRAMES_AUTOSELECT
        NV_ENC_NUM_REF_FRAMES_1
        NV_ENC_NUM_REF_FRAMES_2
        NV_ENC_NUM_REF_FRAMES_3
        NV_ENC_NUM_REF_FRAMES_4
        NV_ENC_NUM_REF_FRAMES_5
        NV_ENC_NUM_REF_FRAMES_6
        NV_ENC_NUM_REF_FRAMES_7

    ctypedef enum NV_ENC_BIT_DEPTH:
        NV_ENC_BIT_DEPTH_INVALID
        NV_ENC_BIT_DEPTH_8
        NV_ENC_BIT_DEPTH_10

    ctypedef enum NV_ENC_TEMPORAL_FILTER_LEVEL:
        NV_ENC_TEMPORAL_FILTER_LEVEL_0
        NV_ENC_TEMPORAL_FILTER_LEVEL_4

    ctypedef struct NV_ENC_CONFIG_AV1:
        uint32_t level                                  #[in]: Specifies the level of the encoded bitstream
        uint32_t tier                                   #[in]: Specifies the level tier of the encoded bitstream
        NV_ENC_AV1_PART_SIZE minPartSize                #[in]: Specifies the minimum size of luma coding block partition
        NV_ENC_AV1_PART_SIZE maxPartSize                #[in]: Specifies the maximum size of luma coding block partition
        uint32_t outputAnnexBFormat                     #[in]: Set 1 to use Annex B format for bitstream output
        uint32_t enableTimingInfo                       #[in]: Set 1 to write Timing Info into sequence/frame headers
        uint32_t enableDecoderModelInfo                 #[in]: Set 1 to write Decoder Model Info into sequence/frame headers
        uint32_t enableFrameIdNumbers                   #[in]: Set 1 to write Frame id numbers in  bitstream
        uint32_t disableSeqHdr                          #[in]: Set 1 to disable Sequence Header signaling in the bitstream
        uint32_t repeatSeqHdr                           #[in]: Set 1 to output Sequence Header for every Key frame
        uint32_t enableIntraRefresh                     #[in]: Set 1 to enable gradual decoder refresh or intra refresh. If the GOP structure uses B frames this will be ignored
        uint32_t chromaFormatIDC                        #[in]: Specifies the chroma format. Should be set to 1 for yuv420 input (yuv444 input currently not supported)
        uint32_t enableBitstreamPadding                 #[in]: Set 1 to enable bitstream padding
        uint32_t enableCustomTileConfig                 #[in]: Set 1 to enable custom tile configuration: numTileColumns and numTileRows must have non zero values and tileWidths and tileHeights must point to a valid address
        uint32_t enableFilmGrainParams                  #[in]: Set 1 to enable custom film grain parameters: filmGrainParams must point to a valid address
        uint32_t enableLTR                              #[in]: Set to 1 to enable LTR (Long Term Reference) frame support. LTR can be used in "LTR Per Picture" mode
        uint32_t enableTemporalSVC                      #[in]: Set to 1 to enable SVC temporal
        uint32_t outputMaxCll                           #[in]: Set to 1 to write Content Light Level metadata for Av1
        uint32_t outputMasteringDisplay                 #[in]: Set to 1 to write Mastering displays metadata for Av1
        uint32_t reserved4                              #[in]: Reserved and must be set to 0
        uint32_t reserved                               #[in]: Reserved bitfields
        uint32_t idrPeriod                              #[in]: Specifies the IDR/Key frame interval. If not set, this is made equal to gopLength in NV_ENC_CONFIG.Low latency application client can set IDR interval to NVENC_INFINITE_GOPLENGTH so that IDR frames are not inserted automatically
        uint32_t intraRefreshPeriod                     #[in]: Specifies the interval between successive intra refresh if enableIntrarefresh is set. Requires enableIntraRefresh to be set
        uint32_t intraRefreshCnt                        #[in]: Specifies the length of intra refresh in number of frames for periodic intra refresh. This value should be smaller than intraRefreshPeriod
        uint32_t maxNumRefFramesInDPB                   #[in]: Specifies the maximum number of references frames in the DPB
        uint32_t numTileColumns                         #[in]: This parameter in conjunction with the flag enableCustomTileConfig and the array tileWidths[] specifies the way in which the picture is divided into tile columns
        uint32_t numTileRows                            #[in]: This parameter in conjunction with the flag enableCustomTileConfig and the array tileHeights[] specifies the way in which the picture is divided into tiles rows
        uint32_t reserved2                              #[in]: Reserved and must be set to 0
        uint32_t *tileWidths                            #[in]: If enableCustomTileConfig == 1, tileWidths[i] specifies the width of tile column i in 64x64 CTU unit, with 0 <= i <= numTileColumns -1
        uint32_t *tileHeights                           #[in]: If enableCustomTileConfig == 1, tileHeights[i] specifies the height of tile row i in 64x64 CTU unit, with 0 <= i <= numTileRows -1
        uint32_t maxTemporalLayersMinus1                #[in]: Specifies the max temporal layer used for hierarchical coding. Cannot be reconfigured and must be specified during encoder creation if temporal layer is considered
        NV_ENC_VUI_COLOR_PRIMARIES colorPrimaries       #[in]: as defined in section of ISO/IEC 23091-4/ITU-T H.273
        NV_ENC_VUI_TRANSFER_CHARACTERISTIC transferCharacteristics  #[in]: as defined in section of ISO/IEC 23091-4/ITU-T H.273
        NV_ENC_VUI_MATRIX_COEFFS matrixCoefficients     #[in]: as defined in section of ISO/IEC 23091-4/ITU-T H.273
        uint32_t colorRange                             #[in]: 0: studio swing representation - 1: full swing representation
        uint32_t chromaSamplePosition                   #[in]: 0: unknown
        NV_ENC_BFRAME_REF_MODE useBFramesAsRef          #[in]: Specifies the B-Frame as reference mode. Check support for useBFramesAsRef mode using  ::NV_ENC_CAPS_SUPPORT_BFRAME_REF_MODE caps
        NV_ENC_FILM_GRAIN_PARAMS_AV1 *filmGrainParams   #[in]: If enableFilmGrainParams == 1, filmGrainParams must point to a valid NV_ENC_FILM_GRAIN_PARAMS_AV1 structure
        NV_ENC_NUM_REF_FRAMES  numFwdRefs               #[in]: Specifies max number of forward reference frame used for prediction of a frame. It must be in range 1-4 (Last, Last2, last3 and Golden). It's a suggestive value not necessarily be honored always
        NV_ENC_NUM_REF_FRAMES  numBwdRefs               #[in]: Specifies max number of L1 list reference frame used for prediction of a frame. It must be in range 1-3 (Backward, Altref2, Altref). It's a suggestive value not necessarily be honored always
        NV_ENC_BIT_DEPTH outputBitDepth                 #[in]: Specifies pixel bit depth of encoded video. Should be set to NV_ENC_BIT_DEPTH_8 for 8 bit, NV_ENC_BIT_DEPTH_10 for 10 bit
        NV_ENC_BIT_DEPTH inputBitDepth                  #[in]: Specifies pixel bit depth of video input. Should be set to NV_ENC_BIT_DEPTH_8 for 8 bit input, NV_ENC_BIT_DEPTH_10 for 10 bit input
        uint32_t ltrNumFrames                           #[in]: In "LTR Per Picture" mode (ltrMarkFrame = 1), ltrNumFrames specifies maximum number of LTR frames in DPB.
        uint32_t numTemporalLayers                      #[in]: Specifies the number of temporal layers to be used for hierarchical coding
        NV_ENC_TEMPORAL_FILTER_LEVEL tfLevel            #[in]: Specifies the strength of temporal filtering. Check support for temporal filter using ::NV_ENC_CAPS_SUPPORT_TEMPORAL_FILTER caps
        uint32_t reserved1[230]                         #[in]: Reserved and must be set to 0
        void*    reserved3[62]                          #[in]: Reserved and must be set to NULL

    ctypedef struct NV_ENC_CONFIG_H264_MEONLY:
        pass

    ctypedef struct NV_ENC_CONFIG_HEVC_MEONLY:
        pass

    ctypedef struct NV_ENC_CODEC_CONFIG:
        NV_ENC_CONFIG_H264  h264Config                  #[in]: Specifies the H.264-specific encoder configuration
        NV_ENC_CONFIG_HEVC  hevcConfig                  #[in]: Specifies the HEVC-specific encoder configuration
        NV_ENC_CONFIG_AV1   av1Config
        NV_ENC_CONFIG_H264_MEONLY h264MeOnlyConfig
        NV_ENC_CONFIG_HEVC_MEONLY hevcMeOnlyConfig
        uint32_t            reserved[320]               #[in]: Reserved and must be set to 0

    ctypedef struct NV_ENC_RC_PARAMS:
        uint32_t    version
        NV_ENC_PARAMS_RC_MODE rateControlMode   #[in]: Specifies the rate control mode. Check support for various rate control modes using ::NV_ENC_CAPS_SUPPORTED_RATECONTROL_MODES caps.
        NV_ENC_QP   constQP             #[in]: Specifies the initial QP to be used for encoding, these values would be used for all frames if in Constant QP mode.
        uint32_t    averageBitRate      #[in]: Specifies the average bitrate(in bits/sec) used for encoding.
        uint32_t    maxBitRate          #[in]: Specifies the maximum bitrate for the encoded output. This is used for VBR and ignored for CBR mode.
        uint32_t    vbvBufferSize       #[in]: Specifies the VBV(HRD) buffer size. in bits. Set 0 to use the default VBV  buffer size.
        uint32_t    vbvInitialDelay     #[in]: Specifies the VBV(HRD) initial delay in bits. Set 0 to use the default VBV  initial delay
        uint32_t    enableMinQP         #[in]: Set this to 1 if minimum QP used for rate control.
        uint32_t    enableMaxQP         #[in]: Set this to 1 if maximum QP used for rate control.
        uint32_t    enableInitialRCQP   #[in]: Set this to 1 if user supplied initial QP is used for rate control.
        uint32_t    enableAQ            #[in]: Set this to 1 to enable adaptive quantization.
        uint32_t    reservedBitField1   #[in]: Reserved bitfields and must be set to 0
        uint32_t    reservedBitFields[27] #[in]: Reserved bitfields and must be set to 0
        NV_ENC_QP   minQP               #[in]: Specifies the minimum QP used for rate control. Client must set NV_ENC_CONFIG::enableMinQP to 1.
        NV_ENC_QP   maxQP               #[in]: Specifies the maximum QP used for rate control. Client must set NV_ENC_CONFIG::enableMaxQP to 1.
        NV_ENC_QP   initialRCQP         #[in]: Specifies the initial QP used for rate control. Client must set NV_ENC_CONFIG::enableInitialRCQP to 1.
        uint32_t    temporallayerIdxMask#[in]: Specifies the temporal layers (as a bitmask) whose QPs have changed. Valid max bitmask is [2^NV_ENC_CAPS_NUM_MAX_TEMPORAL_LAYERS - 1]
        uint8_t     temporalLayerQP[8]  #[in]: Specifies the temporal layer QPs used for rate control. Temporal layer index is used as as the array index
        uint8_t     targetQuality       #[in]: Target CQ (Constant Quality) level for VBR mode (range 0-51 with 0-automatic)
        uint8_t     targetQualityLSB    #[in]: Fractional part of target quality (as 8.8 fixed point format)
        uint16_t    lookaheadDepth      #[in]: Maximum depth of lookahead with range 0-32 (only used if enableLookahead=1)
        uint32_t    reserved[9]

    ctypedef struct NV_ENC_CONFIG:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_CONFIG_VER.
        GUID        profileGUID         #[in]: Specifies the codec profile guid. If client specifies \p NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID the NvEncodeAPI interface will select the appropriate codec profile.
        uint32_t    gopLength           #[in]: Specifies the number of pictures in one GOP. Low latency application client can set goplength to NVENC_INFINITE_GOPLENGTH so that keyframes are not inserted automatically.
        int32_t     frameIntervalP      #[in]: Specifies the GOP pattern as follows: \p frameIntervalP = 0: I, 1: IPP, 2: IBP, 3: IBBP  If goplength is set to NVENC_INFINITE_GOPLENGTH \p frameIntervalP should be set to 1.
        uint32_t    monoChromeEncoding  #[in]: Set this to 1 to enable monochrome encoding for this session.
        NV_ENC_PARAMS_FRAME_FIELD_MODE  frameFieldMode      #[in]: Specifies the frame/field mode. Check support for field encoding using ::NV_ENC_CAPS_SUPPORT_FIELD_ENCODING caps.
        NV_ENC_MV_PRECISION mvPrecision #[in]: Specifies the desired motion vector prediction precision.
        NV_ENC_RC_PARAMS    rcParams    #[in]: Specifies the rate control parameters for the current encoding session.
        NV_ENC_CODEC_CONFIG encodeCodecConfig   #[in]: Specifies the codec specific config parameters through this union.
        uint32_t    reserved[278]       #[in]: Reserved and must be set to 0
        void        *reserved2[64]      #[in]: Reserved and must be set to NULL

    ctypedef enum NV_ENC_TUNING_INFO:
        NV_ENC_TUNING_INFO_UNDEFINED            #Undefined tuningInfo. Invalid value for encoding
        NV_ENC_TUNING_INFO_HIGH_QUALITY         #Tune presets for latency tolerant encoding
        NV_ENC_TUNING_INFO_LOW_LATENCY          #Tune presets for low latency streaming
        NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY    #Tune presets for ultra low latency streaming
        NV_ENC_TUNING_INFO_LOSSLESS             #Tune presets for lossless encoding
        NV_ENC_TUNING_INFO_COUNT                #Count number of tuningInfos. Invalid value


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
        uint32_t    enableMEOnlyMode    #[in] Set to 1 to enable ME Only Mode
        uint32_t    reservedBitFields[28]   #[in]: Reserved bitfields and must be set to 0
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

    ctypedef struct NV_ENC_SEI_PAYLOAD:
        uint32_t    payloadSize         #[in] SEI payload size in bytes. SEI payload must be byte aligned, as described in Annex D
        uint32_t    payloadType         #[in] SEI payload types and syntax can be found in Annex D of the H.264 Specification.
        uint8_t     *payload            #[in] pointer to user data

    ctypedef NV_ENC_SEI_PAYLOAD NV_ENC_H264_SEI_PAYLOAD

    ctypedef struct NV_ENC_PIC_PARAMS_H264:
        uint32_t    displayPOCSyntax    #[in]: Specifies the display POC syntax This is required to be set if client is handling the picture type decision.
        uint32_t    reserved3           #[in]: Reserved and must be set to 0
        uint32_t    refPicFlag          #[in]: Set to 1 for a reference picture. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1.
        uint32_t    colourPlaneId       #[in]: Specifies the colour plane ID associated with the current input.
        uint32_t    forceIntraRefreshWithFrameCnt   #[in]: Forces an intra refresh with duration equal to intraRefreshFrameCnt.
                                        #When outputRecoveryPointSEI is set this is value is used for recovery_frame_cnt in recovery point SEI message
                                        #forceIntraRefreshWithFrameCnt cannot be used if B frames are used in the GOP structure specified
        uint32_t    constrainedFrame    #[in]: Set to 1 if client wants to encode this frame with each slice completely independent of other slices in the frame.
                                        #NV_ENC_INITIALIZE_PARAMS::enableConstrainedEncoding should be set to 1
        uint32_t    sliceModeDataUpdate #[in]: Set to 1 if client wants to change the sliceModeData field to specify new sliceSize Parameter
                                        #When forceIntraRefreshWithFrameCnt is set it will have priority over sliceMode setting
        uint32_t    ltrMarkFrame        #[in]: Set to 1 if client wants to mark this frame as LTR
        uint32_t    ltrUseFrames        #[in]: Set to 1 if client allows encoding this frame using the LTR frames specified in ltrFrameBitmap
        uint32_t    reservedBitFields   #[in]: Reserved bit fields and must be set to 0
        uint8_t*    sliceTypeData       #[in]: Array which specifies the slice type used to force intra slice for a particular slice. Currently supported only for NV_ENC_CONFIG_H264::sliceMode == 3.
                                        #Client should allocate array of size sliceModeData where sliceModeData is specified in field of ::_NV_ENC_CONFIG_H264
                                        #Array element with index n corresponds to nth slice. To force a particular slice to intra client should set corresponding array element to NV_ENC_SLICE_TYPE_I
                                        #all other array elements should be set to NV_ENC_SLICE_TYPE_DEFAULT
        uint32_t    sliceTypeArrayCnt   #[in]: Client should set this to the number of elements allocated in sliceTypeData array. If sliceTypeData is NULL then this should be set to 0
        uint32_t    seiPayloadArrayCnt  #[in]: Specifies the number of elements allocated in  seiPayloadArray array.
        NV_ENC_SEI_PAYLOAD *seiPayloadArray    #[in]: Array of SEI payloads which will be inserted for this frame.
        uint32_t    sliceMode           #[in]: This parameter in conjunction with sliceModeData specifies the way in which the picture is divided into slices
                                        #sliceMode = 0 MB based slices, sliceMode = 1 Byte based slices, sliceMode = 2 MB row based slices, sliceMode = 3, numSlices in Picture
                                        #When forceIntraRefreshWithFrameCnt is set it will have priority over sliceMode setting
                                        #When sliceMode == 0 and sliceModeData == 0 whole picture will be coded with one slice
        uint32_t    sliceModeData       #[in]: Specifies the parameter needed for sliceMode. For:
                                        #sliceMode = 0, sliceModeData specifies # of MBs in each slice (except last slice)
                                        #sliceMode = 1, sliceModeData specifies maximum # of bytes in each slice (except last slice)
                                        #sliceMode = 2, sliceModeData specifies # of MB rows in each slice (except last slice)
                                        #sliceMode = 3, sliceModeData specifies number of slices in the picture. Driver will divide picture into slices optimally
        uint32_t    ltrMarkFrameIdx     #[in]: Specifies the long term referenceframe index to use for marking this frame as LTR.
        uint32_t    ltrUseFrameBitmap   #[in]: Specifies the the associated bitmap of LTR frame indices when encoding this frame.
        uint32_t    ltrUsageMode        #[in]: Specifies additional usage constraints for encoding using LTR frames from this point further. 0: no constraints, 1: no short term refs older than current, no previous LTR frames.
        uint32_t    reserved[243]       #[in]: Reserved and must be set to 0.
        void*       reserved2[62]       #[in]: Reserved and must be set to NULL.

    ctypedef struct NV_ENC_PIC_PARAMS_HEVC:
        uint32_t displayPOCSyntax       #[in]: Specifies the display POC syntax This is required to be set if client is handling the picture type decision.
        uint32_t refPicFlag             #[in]: Set to 1 for a reference picture. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1.
        uint32_t temporalId             #[in]: Specifies the temporal id of the picture
        uint32_t forceIntraRefreshWithFrameCnt  #[in]: Forces an intra refresh with duration equal to intraRefreshFrameCnt.
                                        #When outputRecoveryPointSEI is set this is value is used for recovery_frame_cnt in recovery point SEI message
                                        #forceIntraRefreshWithFrameCnt cannot be used if B frames are used in the GOP structure specified
        uint32_t constrainedFrame       #[in]: Set to 1 if client wants to encode this frame with each slice completely independent of other slices in the frame
                                        #NV_ENC_INITIALIZE_PARAMS::enableConstrainedEncoding should be set to 1
        uint32_t sliceModeDataUpdate    #[in]: Set to 1 if client wants to change the sliceModeData field to specify new sliceSize Parameter
                                        #When forceIntraRefreshWithFrameCnt is set it will have priority over sliceMode setting
        uint32_t ltrMarkFrame           #[in]: Set to 1 if client wants to mark this frame as LTR
        uint32_t ltrUseFrames           #[in]: Set to 1 if client allows encoding this frame using the LTR frames specified in ltrFrameBitmap
        uint32_t reservedBitFields      #[in]: Reserved bit fields and must be set to 0
        uint8_t* sliceTypeData          #[in]: Array which specifies the slice type used to force intra slice for a particular slice. Currently supported only for NV_ENC_CONFIG_H264::sliceMode == 3.
                                        #Client should allocate array of size sliceModeData where sliceModeData is specified in field of ::_NV_ENC_CONFIG_H264
                                        #Array element with index n corresponds to nth slice. To force a particular slice to intra client should set corresponding array element to NV_ENC_SLICE_TYPE_I
                                        #all other array elements should be set to NV_ENC_SLICE_TYPE_DEFAULT
        uint32_t sliceTypeArrayCnt      #[in]: Client should set this to the number of elements allocated in sliceTypeData array. If sliceTypeData is NULL then this should be set to 0
        uint32_t sliceMode              #[in]: This parameter in conjunction with sliceModeData specifies the way in which the picture is divided into slices
                                        #sliceMode = 0 CTU based slices, sliceMode = 1 Byte based slices, sliceMode = 2 CTU row based slices, sliceMode = 3, numSlices in Picture
                                        #When forceIntraRefreshWithFrameCnt is set it will have priority over sliceMode setting
                                        #When sliceMode == 0 and sliceModeData == 0 whole picture will be coded with one slice
        uint32_t sliceModeData          #[in]: Specifies the parameter needed for sliceMode. For:
                                        #sliceMode = 0, sliceModeData specifies # of CTUs in each slice (except last slice)
                                        #sliceMode = 1, sliceModeData specifies maximum # of bytes in each slice (except last slice)
                                        #sliceMode = 2, sliceModeData specifies # of CTU rows in each slice (except last slice)
                                        #sliceMode = 3, sliceModeData specifies number of slices in the picture. Driver will divide picture into slices optimally
        uint32_t ltrMarkFrameIdx        #[in]: Specifies the long term reference frame index to use for marking this frame as LTR.
        uint32_t ltrUseFrameBitmap      #[in]: Specifies the associated bitmap of LTR frame indices to use when encoding this frame.
        uint32_t ltrUsageMode           #[in]: Not supported. Reserved for future use and must be set to 0.
        uint32_t seiPayloadArrayCnt     #[in]: Specifies the number of elements allocated in  seiPayloadArray array.
        uint32_t reserved               #[in]: Reserved and must be set to 0.
        NV_ENC_SEI_PAYLOAD* seiPayloadArray #[in]: Array of SEI payloads which will be inserted for this frame.
        uint32_t reserved2 [244]        #[in]: Reserved and must be set to 0.
        void*    reserved3[61]          #[in]: Reserved and must be set to NULL.

    ctypedef NV_ENC_SEI_PAYLOAD NV_ENC_AV1_OBU_PAYLOAD

    ctypedef struct NV_ENC_FILM_GRAIN_PARAMS_AV1:
        pass

    ctypedef struct NV_ENC_PIC_PARAMS_AV1:
        uint32_t displayPOCSyntax       #[in]: Specifies the display POC syntax This is required to be set if client is handling the picture type decision.
        uint32_t refPicFlag             #[in]: Set to 1 for a reference picture. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1. */
        uint32_t temporalId             #[in]: Specifies the temporal id of the picture
        uint32_t forceIntraRefreshWithFrameCnt  #[in]: Forces an intra refresh with duration equal to intraRefreshFrameCnt.
        uint32_t goldenFrameFlag        #[in]: Encode frame as Golden Frame. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1.
        uint32_t arfFrameFlag           #[in]: Encode frame as Alternate Reference Frame. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1.
        uint32_t arf2FrameFlag          #[in]: Encode frame as Alternate Reference 2 Frame. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1.
        uint32_t bwdFrameFlag           #[in]: Encode frame as Backward Reference Frame. This is ignored if NV_ENC_INITIALIZE_PARAMS::enablePTD is set to 1.
        uint32_t overlayFrameFlag       #[in]: Encode frame as overlay frame. A previously encoded frame with the same displayPOCSyntax value should be present in reference frame buffer.
        uint32_t showExistingFrameFlag  #in]: When ovelayFrameFlag is set to 1, this flag controls the value of the show_existing_frame syntax element associated with the overlay frame.
        uint32_t errorResilientModeFlag #[in]: encode frame independently from previously encoded frames */
        uint32_t tileConfigUpdate       #[in]: Set to 1 if client wants to overwrite the default tile configuration with the tile parameters specified below
        uint32_t enableCustomTileConfig #[in]: Set 1 to enable custom tile configuration: numTileColumns and numTileRows must have non zero values and tileWidths and tileHeights must point to a valid address
        uint32_t filmGrainParamsUpdate  #[in]: Set to 1 if client wants to update previous film grain parameters: filmGrainParams must point to a valid address and encoder must have been configured with film grain enabled
        uint32_t reservedBitFields      #[in]: Reserved bitfields and must be set to 0
        uint32_t numTileColumns         #[in]: This parameter in conjunction with the flag enableCustomTileConfig and the array tileWidths[] specifies the way in which the picture is divided into tile columns.
        uint32_t numTileRows            #[in]: This parameter in conjunction with the flag enableCustomTileConfig and the array tileHeights[] specifies the way in which the picture is divided into tiles rows
        uint32_t reserved               #[in]: Reserved and must be set to 0
        uint32_t *tileWidths            #[in]: If enableCustomTileConfig == 1, tileWidths[i] specifies the width of tile column i in 64x64 CTU unit, with 0 <= i <= numTileColumns -1.
        uint32_t *tileHeights           #[in]: If enableCustomTileConfig == 1, tileHeights[i] specifies the height of tile row i in 64x64 CTU unit, with 0 <= i <= numTileRows -1.
        uint32_t obuPayloadArrayCnt     #[in]: Specifies the number of elements allocated in  obuPayloadArray array.
        uint32_t reserved1              #[in]: Reserved and must be set to 0.
        NV_ENC_AV1_OBU_PAYLOAD* obuPayloadArray     #[in]: Array of OBU payloads which will be inserted for this frame.
        NV_ENC_FILM_GRAIN_PARAMS_AV1 *filmGrainParams   #[in]: If filmGrainParamsUpdate == 1, filmGrainParams must point to a valid NV_ENC_FILM_GRAIN_PARAMS_AV1 structure
        uint32_t reserved2[246]         #[in]: Reserved and must be set to 0.
        void*    reserved3[61]

    ctypedef union NV_ENC_CODEC_PIC_PARAMS:
        NV_ENC_PIC_PARAMS_H264 h264PicParams    #[in]: H264 encode picture params.
        NV_ENC_PIC_PARAMS_HEVC hevcPicParams    #[in]: HEVC encode picture params.
        NV_ENC_PIC_PARAMS_AV1  av1PicParams     #[in]: AV1 encode picture params.
        uint32_t               reserved[256]    #[in]: Reserved and must be set to 0.

    ctypedef struct NV_ENC_MEONLY_PARAMS:
        uint32_t    version             #[in]: Struct version. Must be set to NV_ENC_MEONLY_PARAMS_VER.
        uint32_t    inputWidth          #[in]: Specifies the input buffer width
        uint32_t    inputHeight         #[in]: Specifies the input buffer height
        NV_ENC_INPUT_PTR inputBuffer    #[in]: Specifies the input buffer pointer. Client must use a pointer obtained from NvEncCreateInputBuffer() or NvEncMapInputResource() APIs.
        NV_ENC_INPUT_PTR referenceFrame #[in]: Specifies the reference frame pointer
        NV_ENC_OUTPUT_PTR outputMV      #[in,out]: Specifies the pointer to output motion vector data buffer allocated by NvEncCreateMVBuffer.
        NV_ENC_BUFFER_FORMAT bufferFmt  #[in]: Specifies the input buffer format.
        uint32_t    reserved1[252]      #[in]: Reserved and must be set to 0
        void* reserved2[61]             #[in]: Reserved and must be set to NULL

    ctypedef struct NVENC_EXTERNAL_ME_HINT:
        int32_t     mvx                 #[in]: Specifies the x component of integer pixel MV (relative to current MB) S12.0.
        int32_t     mvy                 #[in]: Specifies the y component of integer pixel MV (relative to current MB) S10.0
        int32_t     refidx              #[in]: Specifies the reference index (31=invalid). Current we support only 1 reference frame per direction for external hints, so \p refidx must be 0.
        int32_t     dir                 #[in]: Specifies the direction of motion estimation . 0=L0 1=L1.
        int32_t     partType            #[in]: Specifies the bloack partition type.0=16x16 1=16x8 2=8x16 3=8x8 (blocks in partition must be consecutive).
        int32_t     lastofPart          #[in]: Set to 1 for the last MV of (sub) partition
        int32_t     lastOfMB            #[in]: Set to 1 for the last MV of macroblock.

    ctypedef struct NV_ENC_PIC_PARAMS:
        uint32_t    version             #[in]: Struct version. Must be set to ::NV_ENC_PIC_PARAMS_VER.
        uint32_t    inputWidth          #[in]: Specifies the input buffer width
        uint32_t    inputHeight         #[in]: Specifies the input buffer height
        uint32_t    inputPitch          #[in]: Specifies the input buffer pitch. If pitch value is not known, set this to inputWidth.
        uint32_t    encodePicFlags      #[in]: Specifies bit-wise OR`ed encode pic flags. See ::NV_ENC_PIC_FLAGS enum.
        uint32_t    frameIdx            #[in]: Specifies the frame index associated with the input frame [optional].
        uint64_t    inputTimeStamp      #[in]: Specifies presentation timestamp associated with the input picture.
        uint64_t    inputDuration       #[in]: Specifies duration of the input picture
        NV_ENC_INPUT_PTR  inputBuffer   #[in]: Specifies the input buffer pointer. Client must use a pointer obtained from ::NvEncCreateInputBuffer() or ::NvEncMapInputResource() APIs.
        NV_ENC_OUTPUT_PTR outputBitstream #[in]: Specifies the pointer to output buffer. Client should use a pointer obtained from ::NvEncCreateBitstreamBuffer() API.
        void*       completionEvent     #[in]: Specifies an event to be signalled on completion of encoding of this Frame [only if operating in Asynchronous mode]. Each output buffer should be associated with a distinct event pointer.
        NV_ENC_BUFFER_FORMAT bufferFmt  #[in]: Specifies the input buffer format.
        NV_ENC_PIC_STRUCT pictureStruct #[in]: Specifies structure of the input picture.
        NV_ENC_PIC_TYPE pictureType     #[in]: Specifies input picture type. Client required to be set explicitly by the client if the client has not set NV_ENC_INITALIZE_PARAMS::enablePTD to 1 while calling NvInitializeEncoder.
        NV_ENC_CODEC_PIC_PARAMS codecPicParams  #[in]: Specifies the codec specific per-picture encoding parameters.
        uint32_t    newEncodeWidth      #[in]: Specifies the new output width for current Encoding session, in case of dynamic resolution change. Client should only set this in combination with NV_ENC_PIC_FLAGS::NV_ENC_PIC_FLAG_DYN_RES_CHANGE.
                                        #Additionally, if Picture Type decision is handled by the Client [_NV_ENC_INITIALIZE_PARAMS::enablePTD == 0], the client should set the _NV_ENC_PIC_PARAMS::pictureType as ::NV_ENC_PIC_TYPE_IDR.
                                        #If _NV_ENC_INITIALIZE_PARAMS::enablePTD == 1, then the Encoder will generate an IDR frame corresponding to this input.
        uint32_t    newEncodeHeight     #[in]: Specifies the new output width for current Encoding session, in case of dynamic resolution change. Client should only set this in combination with NV_ENC_PIC_FLAGS::NV_ENC_PIC_FLAG_DYN_RES_CHANGE.
                                        #Additionally, if Picture Type decision is handled by the Client [_NV_ENC_INITIALIZE_PARAMS::enablePTD == 0], the client should set the _NV_ENC_PIC_PARAMS::pictureType as ::NV_ENC_PIC_TYPE_IDR.
                                        #If _NV_ENC_INITIALIZE_PARAMS::enablePTD == 1, then the Encoder will generate an IDR frame corresponding to this input.
        NV_ENC_RC_PARAMS rcParams       #[in]: Specifies the rate control parameters for the current encoding session.
        NVENC_EXTERNAL_ME_HINT_COUNTS_PER_BLOCKTYPE meHintCountsPerBlock[2] #[in]: Specifies the number of hint candidates per block per direction for the current frame. meHintCountsPerBlock[0] is for L0 predictors and meHintCountsPerBlock[1] is for L1 predictors.
                                        #The candidate count in NV_ENC_PIC_PARAMS::meHintCountsPerBlock[lx] must never exceed NV_ENC_INITIALIZE_PARAMS::maxMEHintCountsPerBlock[lx] provided during encoder initialization.
        NVENC_EXTERNAL_ME_HINT *meExternalHints     #[in]: Specifies the pointer to ME external hints for the current frame. The size of ME hint buffer should be equal to number of macroblocks multiplied by the total number of candidates per macroblock.
                                        #The total number of candidates per MB per direction = 1*meHintCountsPerBlock[Lx].numCandsPerBlk16x16 + 2*meHintCountsPerBlock[Lx].numCandsPerBlk16x8 + 2*meHintCountsPerBlock[Lx].numCandsPerBlk8x8
                                        # + 4*meHintCountsPerBlock[Lx].numCandsPerBlk8x8. For frames using bidirectional ME , the total number of candidates for single macroblock is sum of total number of candidates per MB for each direction (L0 and L1)
        uint32_t    newDarWidth         #[in]: Specifies the new disalay aspect ratio width for current Encoding session, in case of dynamic resolution change. Client should only set this in combination with NV_ENC_PIC_FLAGS::NV_ENC_PIC_FLAG_DYN_RES_CHANGE.
                                        #Additionally, if Picture Type decision is handled by the Client [_NV_ENC_INITIALIZE_PARAMS::enablePTD == 0], the client should set the _NV_ENC_PIC_PARAMS::pictureType as ::NV_ENC_PIC_TYPE_IDR.
                                        #If _NV_ENC_INITIALIZE_PARAMS::enablePTD == 1, then the Encoder will generate an IDR frame corresponding to this input.
        uint32_t    newDarHeight        #[in]: Specifies the new disalay aspect ratio height for current Encoding session, in case of dynamic resolution change. Client should only set this in combination with NV_ENC_PIC_FLAGS::NV_ENC_PIC_FLAG_DYN_RES_CHANGE.
                                        #If _NV_ENC_INITIALIZE_PARAMS::enablePTD == 1, then the Encoder will generate an IDR frame corresponding to this input.
        uint32_t    reserved1[259]      #[in]: Reserved and must be set to 0
        void*       reserved2[63]       #[in]: Reserved and must be set to NULL

    ctypedef enum NVENCSTATUS:
        NV_ENC_SUCCESS
        NV_ENC_ERR_NO_ENCODE_DEVICE
        NV_ENC_ERR_UNSUPPORTED_DEVICE
        NV_ENC_ERR_INVALID_ENCODERDEVICE
        NV_ENC_ERR_INVALID_DEVICE
        NV_ENC_ERR_DEVICE_NOT_EXIST
        NV_ENC_ERR_INVALID_PTR
        NV_ENC_ERR_INVALID_EVENT
        NV_ENC_ERR_INVALID_PARAM
        NV_ENC_ERR_INVALID_CALL
        NV_ENC_ERR_OUT_OF_MEMORY
        NV_ENC_ERR_ENCODER_NOT_INITIALIZED
        NV_ENC_ERR_UNSUPPORTED_PARAM
        NV_ENC_ERR_LOCK_BUSY
        NV_ENC_ERR_NOT_ENOUGH_BUFFER
        NV_ENC_ERR_INVALID_VERSION
        NV_ENC_ERR_MAP_FAILED
        NV_ENC_ERR_NEED_MORE_INPUT
        NV_ENC_ERR_ENCODER_BUSY
        NV_ENC_ERR_EVENT_NOT_REGISTERD
        NV_ENC_ERR_GENERIC
        NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY
        NV_ENC_ERR_UNIMPLEMENTED
        NV_ENC_ERR_RESOURCE_REGISTER_FAILED
        NV_ENC_ERR_RESOURCE_NOT_REGISTERED
        NV_ENC_ERR_RESOURCE_NOT_MAPPED
        NV_ENC_ERR_NEED_MORE_OUTPUT

    #NVENCSTATUS NvEncodeAPICreateInstance(NV_ENCODE_API_FUNCTION_LIST *functionList)

    ctypedef NVENCSTATUS (*PNVENCOPENENCODESESSION)         (void* device, uint32_t deviceType, void** encoder) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEGUIDCOUNT)        (void* encoder, uint32_t* encodeGUIDCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEGUIDS)            (void* encoder, GUID* GUIDs, uint32_t guidArraySize, uint32_t* GUIDCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPROFILEGUIDCOUNT) (void* encoder, GUID encodeGUID, uint32_t* encodeProfileGUIDCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPROFILEGUIDS)     (void* encoder, GUID encodeGUID, GUID* profileGUIDs, uint32_t guidArraySize, uint32_t* GUIDCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETINPUTFORMATCOUNT)       (void* encoder, GUID encodeGUID, uint32_t* inputFmtCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETINPUTFORMATS)           (void* encoder, GUID encodeGUID, NV_ENC_BUFFER_FORMAT* inputFmts, uint32_t inputFmtArraySize, uint32_t* inputFmtCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODECAPS)             (void* encoder, GUID encodeGUID, NV_ENC_CAPS_PARAM* capsParam, int* capsVal) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETCOUNT)      (void* encoder, GUID encodeGUID, uint32_t* encodePresetGUIDCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETGUIDS)      (void* encoder, GUID encodeGUID, GUID* presetGUIDs, uint32_t guidArraySize, uint32_t* encodePresetGUIDCount) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETCONFIG)     (void* encoder, GUID encodeGUID, GUID  presetGUID, NV_ENC_PRESET_CONFIG* presetConfig) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODEPRESETCONFIGEX)   (void* encoder, GUID encodeGUID, GUID  presetGUID, NV_ENC_TUNING_INFO tuningInfo, NV_ENC_PRESET_CONFIG* presetConfig)
    ctypedef NVENCSTATUS (*PNVENCINITIALIZEENCODER)         (void* encoder, NV_ENC_INITIALIZE_PARAMS* createEncodeParams) nogil
    ctypedef NVENCSTATUS (*PNVENCCREATEINPUTBUFFER)         (void* encoder, NV_ENC_CREATE_INPUT_BUFFER* createInputBufferParams) nogil
    ctypedef NVENCSTATUS (*PNVENCDESTROYINPUTBUFFER)        (void* encoder, NV_ENC_INPUT_PTR inputBuffer) nogil
    ctypedef NVENCSTATUS (*PNVENCCREATEBITSTREAMBUFFER)     (void* encoder, NV_ENC_CREATE_BITSTREAM_BUFFER* createBitstreamBufferParams) nogil
    ctypedef NVENCSTATUS (*PNVENCDESTROYBITSTREAMBUFFER)    (void* encoder, NV_ENC_OUTPUT_PTR bitstreamBuffer) nogil
    ctypedef NVENCSTATUS (*PNVENCENCODEPICTURE)             (void* encoder, NV_ENC_PIC_PARAMS* encodePicParams) nogil
    ctypedef NVENCSTATUS (*PNVENCLOCKBITSTREAM)             (void* encoder, NV_ENC_LOCK_BITSTREAM* lockBitstreamBufferParams) nogil
    ctypedef NVENCSTATUS (*PNVENCUNLOCKBITSTREAM)           (void* encoder, NV_ENC_OUTPUT_PTR bitstreamBuffer) nogil
    ctypedef NVENCSTATUS (*PNVENCLOCKINPUTBUFFER)           (void* encoder, NV_ENC_LOCK_INPUT_BUFFER* lockInputBufferParams) nogil
    ctypedef NVENCSTATUS (*PNVENCUNLOCKINPUTBUFFER)         (void* encoder, NV_ENC_INPUT_PTR inputBuffer) nogil
    ctypedef NVENCSTATUS (*PNVENCGETENCODESTATS)            (void* encoder, NV_ENC_STAT* encodeStats) nogil
    ctypedef NVENCSTATUS (*PNVENCGETSEQUENCEPARAMS)         (void* encoder, NV_ENC_SEQUENCE_PARAM_PAYLOAD* sequenceParamPayload) nogil
    ctypedef NVENCSTATUS (*PNVENCREGISTERASYNCEVENT)        (void* encoder, NV_ENC_EVENT_PARAMS* eventParams) nogil
    ctypedef NVENCSTATUS (*PNVENCUNREGISTERASYNCEVENT)      (void* encoder, NV_ENC_EVENT_PARAMS* eventParams) nogil
    ctypedef NVENCSTATUS (*PNVENCMAPINPUTRESOURCE)          (void* encoder, NV_ENC_MAP_INPUT_RESOURCE* mapInputResParams) nogil
    ctypedef NVENCSTATUS (*PNVENCUNMAPINPUTRESOURCE)        (void* encoder, NV_ENC_INPUT_PTR mappedInputBuffer) nogil
    ctypedef NVENCSTATUS (*PNVENCDESTROYENCODER)            (void* encoder) nogil
    ctypedef NVENCSTATUS (*PNVENCINVALIDATEREFFRAMES)       (void* encoder, uint64_t invalidRefFrameTimeStamp) nogil
    ctypedef NVENCSTATUS (*PNVENCOPENENCODESESSIONEX)       (NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS *openSessionExParams, void** encoder) nogil
    ctypedef NVENCSTATUS (*PNVENCREGISTERRESOURCE)          (void* encoder, NV_ENC_REGISTER_RESOURCE* registerResParams) nogil
    ctypedef NVENCSTATUS (*PNVENCUNREGISTERRESOURCE)        (void* encoder, NV_ENC_REGISTERED_PTR registeredRes) nogil
    ctypedef NVENCSTATUS (*PNVENCRECONFIGUREENCODER)        (void* encoder, NV_ENC_RECONFIGURE_PARAMS* reInitEncodeParams) nogil

    ctypedef struct NV_ENCODE_API_FUNCTION_LIST:
        uint32_t    version         #[in]: Client should pass NV_ENCODE_API_FUNCTION_LIST_VER.
        uint32_t    reserved        #[in]: Reserved and should be set to 0.
        PNVENCOPENENCODESESSION         nvEncOpenEncodeSession
        PNVENCGETENCODEGUIDCOUNT        nvEncGetEncodeGUIDCount
        PNVENCGETENCODEPROFILEGUIDCOUNT nvEncGetEncodeProfileGUIDCount
        PNVENCGETENCODEPROFILEGUIDS     nvEncGetEncodeProfileGUIDs
        PNVENCGETENCODEGUIDS            nvEncGetEncodeGUIDs
        PNVENCGETINPUTFORMATCOUNT       nvEncGetInputFormatCount
        PNVENCGETINPUTFORMATS           nvEncGetInputFormats
        PNVENCGETENCODECAPS             nvEncGetEncodeCaps
        PNVENCGETENCODEPRESETCOUNT      nvEncGetEncodePresetCount
        PNVENCGETENCODEPRESETGUIDS      nvEncGetEncodePresetGUIDs
        PNVENCGETENCODEPRESETCONFIG     nvEncGetEncodePresetConfig
        PNVENCGETENCODEPRESETCONFIGEX   nvEncGetEncodePresetConfigEx
        PNVENCINITIALIZEENCODER         nvEncInitializeEncoder
        PNVENCCREATEINPUTBUFFER         nvEncCreateInputBuffer
        PNVENCDESTROYINPUTBUFFER        nvEncDestroyInputBuffer
        PNVENCCREATEBITSTREAMBUFFER     nvEncCreateBitstreamBuffer
        PNVENCDESTROYBITSTREAMBUFFER    nvEncDestroyBitstreamBuffer
        PNVENCENCODEPICTURE             nvEncEncodePicture
        PNVENCLOCKBITSTREAM             nvEncLockBitstream
        PNVENCUNLOCKBITSTREAM           nvEncUnlockBitstream
        PNVENCLOCKINPUTBUFFER           nvEncLockInputBuffer
        PNVENCUNLOCKINPUTBUFFER         nvEncUnlockInputBuffer
        PNVENCGETENCODESTATS            nvEncGetEncodeStats
        PNVENCGETSEQUENCEPARAMS         nvEncGetSequenceParams
        PNVENCREGISTERASYNCEVENT        nvEncRegisterAsyncEvent
        PNVENCUNREGISTERASYNCEVENT      nvEncUnregisterAsyncEvent
        PNVENCMAPINPUTRESOURCE          nvEncMapInputResource
        PNVENCUNMAPINPUTRESOURCE        nvEncUnmapInputResource
        PNVENCDESTROYENCODER            nvEncDestroyEncoder
        PNVENCINVALIDATEREFFRAMES       nvEncInvalidateRefFrames
        PNVENCOPENENCODESESSIONEX       nvEncOpenEncodeSessionEx
        PNVENCREGISTERRESOURCE          nvEncRegisterResource
        PNVENCUNREGISTERRESOURCE        nvEncUnregisterResource
        PNVENCRECONFIGUREENCODER        nvEncReconfigureEncoder
        void*                           reserved2[285]                  #[in]:  Reserved and must be set to NULL

    #constants:
    unsigned int NVENCAPI_MAJOR_VERSION
    unsigned int NVENCAPI_MINOR_VERSION
    uint32_t NVENCAPI_VERSION
    unsigned int NV_ENCODE_API_FUNCTION_LIST_VER
    unsigned int NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER
    unsigned int NV_ENC_INITIALIZE_PARAMS_VER
    unsigned int NV_ENC_PRESET_CONFIG_VER
    unsigned int NV_ENC_CONFIG_VER
    unsigned int NV_ENC_CREATE_INPUT_BUFFER_VER
    unsigned int NV_ENC_CREATE_BITSTREAM_BUFFER_VER
    unsigned int NV_ENC_CAPS_PARAM_VER
    unsigned int NV_ENC_LOCK_INPUT_BUFFER_VER
    unsigned int NV_ENC_LOCK_BITSTREAM_VER
    unsigned int NV_ENC_PIC_PARAMS_VER
    unsigned int NV_ENC_RC_PARAMS_VER
    unsigned int NV_ENC_REGISTER_RESOURCE_VER
    unsigned int NV_ENC_MAP_INPUT_RESOURCE_VER
    unsigned int NV_ENC_RECONFIGURE_PARAMS_VER
    unsigned int NV_ENC_CAPS_MB_PER_SEC_MAX
    unsigned int NVENC_INFINITE_GOPLENGTH


cdef str guidstr(GUID guid)
cdef GUID parseguid(src) except *
cdef str presetstr(GUID preset)
cdef str nvencStatusInfo(NVENCSTATUS ret)


cdef dict get_profile_guids(object encode)

cdef str get_profile_name(profile_guid)

cdef uint8_t is_transient_error(NVENCSTATUS r)

cdef str get_caps_name(NV_ENC_CAPS cap)

cdef List[int] get_all_caps()

cdef str get_preset_name(object preset)

cdef str get_tuning_name(NV_ENC_TUNING_INFO tuning)

cdef NV_ENC_TUNING_INFO get_tuning_value(object name)

cdef List[int] get_buffer_formats()

cdef str get_buffer_format_name(object buffer_format)

cdef int get_chroma_format(object pixel_format)

cdef int get_preset_speed(object preset, int default)

cdef int get_preset_quality(object preset, int default)

cdef str get_picture_type(NV_ENC_PIC_TYPE ptype)
