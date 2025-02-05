# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import os
import platform
from collections import deque
from time import monotonic
from typing import Any, Dict, Tuple, List
import ctypes
from ctypes import cdll, POINTER
from threading import Lock
from collections.abc import Sequence

from xpra.os_util import WIN32, LINUX
from xpra.util.thread import start_thread
from xpra.util.objects import AtomicInteger, typedict
from xpra.util.str_fn import csv, pver, strtobytes
from xpra.util.env import envint, envbool, first_time
from xpra.codecs.nvidia.cuda.context import (
    init_all_devices, get_devices, get_device_name,
    get_cuda_info, get_pycuda_info, reset_state,
    get_CUDA_function, record_device_failure, record_device_success,
    cuda_device_context, load_device,
)
from xpra.codecs.nvidia.cuda.errors import get_error_name
from xpra.codecs.constants import VideoSpec, TransientCodecException, CSC_ALIAS
from xpra.codecs.image import ImageWrapper
from xpra.codecs.nvidia.util import (
    get_nvidia_module_version, get_license_keys,
    validate_driver_yuv444lossless, get_cards,
)
from xpra.log import Logger
log = Logger("encoder", "nvenc")

#we can import pycuda safely here,
#because importing cuda/context will have imported it with the lock
from pycuda import driver  # @UnresolvedImport
import numpy

from libc.stdint cimport uintptr_t, uint8_t, uint16_t, uint32_t, int32_t, uint64_t   # pylint: disable=syntax-error
from libc.stdlib cimport free, malloc
from libc.string cimport memset, memcpy

TEST_ENCODINGS = os.environ.get("XPRA_NVENC_ENCODINGS", "h264,h265").split(",")
assert (x for x in TEST_ENCODINGS in ("h264", "h265")), "invalid list of encodings: %s" % (TEST_ENCODINGS,)
assert len(TEST_ENCODINGS)>0, "no encodings enabled!"
DESIRED_PRESET = os.environ.get("XPRA_NVENC_PRESET", "")
#NVENC requires compute capability value 0x30 or above:
DESIRED_TUNING = os.environ.get("XPRA_NVENC_TUNING", "")

cdef int SUPPORT_30BPP = envbool("XPRA_NVENC_SUPPORT_30BPP", True)
cdef int YUV444_THRESHOLD = envint("XPRA_NVENC_YUV444_THRESHOLD", 85)
cdef int LOSSLESS_THRESHOLD = envint("XPRA_NVENC_LOSSLESS_THRESHOLD", 100)
cdef int NATIVE_RGB = envbool("XPRA_NVENC_NATIVE_RGB", int(not WIN32))
cdef int LOSSLESS_ENABLED = envbool("XPRA_NVENC_LOSSLESS", True)
cdef int YUV420_ENABLED = envbool("XPRA_NVENC_YUV420P", True)
cdef int YUV444_ENABLED = envbool("XPRA_NVENC_YUV444P", True)
cdef int DEBUG_API = envbool("XPRA_NVENC_DEBUG_API", False)
cdef int GPU_MEMCOPY = envbool("XPRA_NVENC_GPU_MEMCOPY", True)
cdef int CONTEXT_LIMIT = envint("XPRA_NVENC_CONTEXT_LIMIT", 32)
cdef int THREADED_INIT = envbool("XPRA_NVENC_THREADED_INIT", True)
cdef int SLOW_DOWN_INIT = envint("XPRA_NVENC_SLOW_DOWN_INIT", 0)
cdef int INTRA_REFRESH = envbool("XPRA_NVENC_INTRA_REFRESH", True)

device_lock = Lock()


YUV444_CODEC_SUPPORT: Dict[str, bool] = {
    "h264"  : True,
    "h265"  : True,
}
LOSSLESS_CODEC_SUPPORT: Dict[str, bool] = {}

#so we can warn just once per unknown preset:
UNKNOWN_PRESETS: List[str] = []


cdef inline int MIN(int a, int b):
    if a<=b:
        return a
    return b
cdef inline int MAX(int a, int b):
    if a>=b:
        return a
    return b


CUresult = ctypes.c_int
CUcontext = ctypes.c_void_p


cdef extern from "nvEncodeAPI.h":
    ctypedef int NVENCSTATUS
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
        #added in 9.1:
        #NV_ENC_CAPS_WIDTH_MIN
        #NV_ENC_CAPS_HEIGHT_MIN
        #NV_ENC_CAPS_SUPPORT_MULTIPLE_REF_FRAMES


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

    ctypedef enum NV_ENC_PIC_FLAGS:
        NV_ENC_PIC_FLAG_FORCEINTRA
        NV_ENC_PIC_FLAG_FORCEIDR
        NV_ENC_PIC_FLAG_OUTPUT_SPSPPS
        NV_ENC_PIC_FLAG_EOS

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

    #Profiles:
    GUID NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID
    GUID NV_ENC_H264_PROFILE_BASELINE_GUID
    GUID NV_ENC_H264_PROFILE_MAIN_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_GUID
    GUID NV_ENC_H264_PROFILE_HIGH_444_GUID
    GUID NV_ENC_H264_PROFILE_STEREO_GUID
    #GUID NV_ENC_H264_PROFILE_SVC_TEMPORAL_SCALABILTY
    GUID NV_ENC_H264_PROFILE_PROGRESSIVE_HIGH_GUID
    GUID NV_ENC_H264_PROFILE_CONSTRAINED_HIGH_GUID

    GUID NV_ENC_HEVC_PROFILE_MAIN_GUID
    GUID NV_ENC_HEVC_PROFILE_MAIN10_GUID
    GUID NV_ENC_HEVC_PROFILE_FREXT_GUID

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

    ctypedef struct NV_ENC_CODEC_CONFIG:
        NV_ENC_CONFIG_H264  h264Config                  #[in]: Specifies the H.264-specific encoder configuration
        NV_ENC_CONFIG_HEVC  hevcConfig                  #[in]: Specifies the HEVC-specific encoder configuration. Currently unsupported and must not to be used.
        uint32_t            reserved[256]               #[in]: Reserved and must be set to 0

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

    ctypedef struct NV_ENC_H264_SEI_PAYLOAD:
        uint32_t    payloadSize         #[in] SEI payload size in bytes. SEI payload must be byte aligned, as described in Annex D
        uint32_t    payloadType         #[in] SEI payload types and syntax can be found in Annex D of the H.264 Specification.
        uint8_t     *payload            #[in] pointer to user data
    ctypedef NV_ENC_H264_SEI_PAYLOAD NV_ENC_SEI_PAYLOAD

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

    ctypedef union NV_ENC_CODEC_PIC_PARAMS:
        NV_ENC_PIC_PARAMS_H264 h264PicParams    #[in]: H264 encode picture params.
        NV_ENC_PIC_PARAMS_HEVC hevcPicParams    #[in]: HEVC encode picture params.
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
    unsigned int NVENC_INFINITE_GOPLENGTH
    unsigned int NV_ENC_SUCCESS
    unsigned int NV_ENC_ERR_NO_ENCODE_DEVICE
    unsigned int NV_ENC_ERR_UNSUPPORTED_DEVICE
    unsigned int NV_ENC_ERR_INVALID_ENCODERDEVICE
    unsigned int NV_ENC_ERR_INVALID_DEVICE
    unsigned int NV_ENC_ERR_DEVICE_NOT_EXIST
    unsigned int NV_ENC_ERR_INVALID_PTR
    unsigned int NV_ENC_ERR_INVALID_EVENT
    unsigned int NV_ENC_ERR_INVALID_PARAM
    unsigned int NV_ENC_ERR_INVALID_CALL
    unsigned int NV_ENC_ERR_OUT_OF_MEMORY
    unsigned int NV_ENC_ERR_ENCODER_NOT_INITIALIZED
    unsigned int NV_ENC_ERR_UNSUPPORTED_PARAM
    unsigned int NV_ENC_ERR_LOCK_BUSY
    unsigned int NV_ENC_ERR_NOT_ENOUGH_BUFFER
    unsigned int NV_ENC_ERR_INVALID_VERSION
    unsigned int NV_ENC_ERR_MAP_FAILED
    unsigned int NV_ENC_ERR_NEED_MORE_INPUT
    unsigned int NV_ENC_ERR_ENCODER_BUSY
    unsigned int NV_ENC_ERR_EVENT_NOT_REGISTERD
    unsigned int NV_ENC_ERR_GENERIC
    unsigned int NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY
    unsigned int NV_ENC_ERR_UNIMPLEMENTED
    unsigned int NV_ENC_ERR_RESOURCE_REGISTER_FAILED
    unsigned int NV_ENC_ERR_RESOURCE_NOT_REGISTERED
    unsigned int NV_ENC_ERR_RESOURCE_NOT_MAPPED

    unsigned int NV_ENC_CAPS_MB_PER_SEC_MAX
    unsigned int NV_ENC_RECONFIGURE_PARAMS_VER


NV_ENC_STATUS_TXT: Dict[int, str] = {
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
    NV_ENC_ERR_RESOURCE_NOT_REGISTERED : "This indicates that the client is attempting to unregister a resource that has not been successfully registered.",
    NV_ENC_ERR_RESOURCE_NOT_MAPPED : "This indicates that the client is attempting to unmap a resource that has not been successfully mapped.",
}

OPEN_TRANSIENT_ERROR: Sequence[int] = (
    NV_ENC_ERR_NO_ENCODE_DEVICE,
    #NV_ENC_ERR_UNSUPPORTED_DEVICE,
    #NV_ENC_ERR_INVALID_ENCODERDEVICE,
    #NV_ENC_ERR_INVALID_DEVICE,
    NV_ENC_ERR_DEVICE_NOT_EXIST,
    NV_ENC_ERR_OUT_OF_MEMORY,
    NV_ENC_ERR_ENCODER_BUSY,
    NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY,
)

CAPS_NAMES: Dict[int, str] = {
    NV_ENC_CAPS_NUM_MAX_BFRAMES             : "NUM_MAX_BFRAMES",
    NV_ENC_CAPS_SUPPORTED_RATECONTROL_MODES : "SUPPORTED_RATECONTROL_MODES",
    NV_ENC_CAPS_SUPPORT_FIELD_ENCODING      : "SUPPORT_FIELD_ENCODING",
    NV_ENC_CAPS_SUPPORT_MONOCHROME          : "SUPPORT_MONOCHROME",
    NV_ENC_CAPS_SUPPORT_FMO                 : "SUPPORT_FMO",
    NV_ENC_CAPS_SUPPORT_QPELMV              : "SUPPORT_QPELMV",
    NV_ENC_CAPS_SUPPORT_BDIRECT_MODE        : "SUPPORT_BDIRECT_MODE",
    NV_ENC_CAPS_SUPPORT_CABAC               : "SUPPORT_CABAC",
    NV_ENC_CAPS_SUPPORT_ADAPTIVE_TRANSFORM  : "SUPPORT_ADAPTIVE_TRANSFORM",
    NV_ENC_CAPS_NUM_MAX_TEMPORAL_LAYERS     : "NUM_MAX_TEMPORAL_LAYERS",
    NV_ENC_CAPS_SUPPORT_HIERARCHICAL_PFRAMES: "SUPPORT_HIERARCHICAL_PFRAMES",
    NV_ENC_CAPS_SUPPORT_HIERARCHICAL_BFRAMES: "SUPPORT_HIERARCHICAL_BFRAMES",
    NV_ENC_CAPS_LEVEL_MAX                   : "LEVEL_MAX",
    NV_ENC_CAPS_LEVEL_MIN                   : "LEVEL_MIN",
    NV_ENC_CAPS_SEPARATE_COLOUR_PLANE       : "SEPARATE_COLOUR_PLANE",
    NV_ENC_CAPS_WIDTH_MAX                   : "WIDTH_MAX",
    NV_ENC_CAPS_HEIGHT_MAX                  : "HEIGHT_MAX",
    NV_ENC_CAPS_SUPPORT_TEMPORAL_SVC        : "SUPPORT_TEMPORAL_SVC",
    NV_ENC_CAPS_SUPPORT_DYN_RES_CHANGE      : "SUPPORT_DYN_RES_CHANGE",
    NV_ENC_CAPS_SUPPORT_DYN_BITRATE_CHANGE  : "SUPPORT_DYN_BITRATE_CHANGE",
    NV_ENC_CAPS_SUPPORT_DYN_FORCE_CONSTQP   : "SUPPORT_DYN_FORCE_CONSTQP",
    NV_ENC_CAPS_SUPPORT_DYN_RCMODE_CHANGE   : "SUPPORT_DYN_RCMODE_CHANGE",
    NV_ENC_CAPS_SUPPORT_SUBFRAME_READBACK   : "SUPPORT_SUBFRAME_READBACK",
    NV_ENC_CAPS_SUPPORT_CONSTRAINED_ENCODING: "SUPPORT_CONSTRAINED_ENCODING",
    NV_ENC_CAPS_SUPPORT_INTRA_REFRESH       : "SUPPORT_INTRA_REFRESH",
    NV_ENC_CAPS_SUPPORT_CUSTOM_VBV_BUF_SIZE : "SUPPORT_CUSTOM_VBV_BUF_SIZE",
    NV_ENC_CAPS_SUPPORT_DYNAMIC_SLICE_MODE  : "SUPPORT_DYNAMIC_SLICE_MODE",
    NV_ENC_CAPS_SUPPORT_REF_PIC_INVALIDATION: "SUPPORT_REF_PIC_INVALIDATION",
    NV_ENC_CAPS_PREPROC_SUPPORT             : "PREPROC_SUPPORT",
    NV_ENC_CAPS_ASYNC_ENCODE_SUPPORT        : "ASYNC_ENCODE_SUPPORT",
    NV_ENC_CAPS_MB_NUM_MAX                  : "MB_NUM_MAX",
    NV_ENC_CAPS_EXPOSED_COUNT               : "EXPOSED_COUNT",
    NV_ENC_CAPS_SUPPORT_YUV444_ENCODE       : "SUPPORT_YUV444_ENCODE",
    NV_ENC_CAPS_SUPPORT_LOSSLESS_ENCODE     : "SUPPORT_LOSSLESS_ENCODE",
    NV_ENC_CAPS_SUPPORT_SAO                 : "SUPPORT_SAO",
    NV_ENC_CAPS_SUPPORT_MEONLY_MODE         : "SUPPORT_MEONLY_MODE",
    NV_ENC_CAPS_SUPPORT_LOOKAHEAD           : "SUPPORT_LOOKAHEAD",
    NV_ENC_CAPS_SUPPORT_TEMPORAL_AQ         : "SUPPORT_TEMPORAL_AQ",
    NV_ENC_CAPS_SUPPORT_10BIT_ENCODE        : "SUPPORT_10BIT_ENCODE",
    NV_ENC_CAPS_NUM_MAX_LTR_FRAMES          : "NUM_MAX_LTR_FRAMES",
    NV_ENC_CAPS_SUPPORT_WEIGHTED_PREDICTION : "SUPPORT_WEIGHTED_PREDICTION",
    NV_ENC_CAPS_DYNAMIC_QUERY_ENCODER_CAPACITY  : "DYNAMIC_QUERY_ENCODER_CAPACITY",
    NV_ENC_CAPS_SUPPORT_BFRAME_REF_MODE     : "SUPPORT_BFRAME_REF_MODE",
    NV_ENC_CAPS_SUPPORT_EMPHASIS_LEVEL_MAP  : "SUPPORT_EMPHASIS_LEVEL_MAP",
}

PIC_TYPES = {
    NV_ENC_PIC_TYPE_P              : "P",
    NV_ENC_PIC_TYPE_B              : "B",
    NV_ENC_PIC_TYPE_I              : "I",
    NV_ENC_PIC_TYPE_IDR            : "IDR",
    NV_ENC_PIC_TYPE_BI             : "BI",
    NV_ENC_PIC_TYPE_SKIPPED        : "SKIPPED",
    NV_ENC_PIC_TYPE_INTRA_REFRESH  : "INTRA_REFRESH",
    NV_ENC_PIC_TYPE_UNKNOWN        : "UNKNOWN",
}

TUNING_STR: Dict[int, str] = {
    NV_ENC_TUNING_INFO_UNDEFINED            : "undefined",
    NV_ENC_TUNING_INFO_HIGH_QUALITY         : "high-quality",
    NV_ENC_TUNING_INFO_LOW_LATENCY          : "low-latency",
    NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY    : "ultra-low-latency",
    NV_ENC_TUNING_INFO_LOSSLESS             : "lossless",
}
TUNINGS: Dict[str, int] = dict((v, k) for k,v in TUNING_STR.items())


NvEncodeAPICreateInstance = None
cuCtxGetCurrent = None


def init_nvencode_library() -> None:
    global NvEncodeAPICreateInstance, cuCtxGetCurrent
    if WIN32:
        load = ctypes.WinDLL
        nvenc_libname = "nvencodeapi64.dll"
        cuda_libname = "nvcuda.dll"
    else:
        #assert os.name=="posix"
        load = cdll.LoadLibrary
        nvenc_libname = "libnvidia-encode.so.1"
        cuda_libname = "libcuda.so"
    #CUDA:
    log("init_nvencode_library() will try to load %s", cuda_libname)
    try:
        x = load(cuda_libname)
        log("init_nvencode_library() %s(%s)=%s", load, cuda_libname, x)
    except Exception as e:
        log("failed to load '%s'", cuda_libname, exc_info=True)
        raise ImportError("nvenc: the required library %s cannot be loaded: %s" % (cuda_libname, e)) from None
    cuCtxGetCurrent = x.cuCtxGetCurrent
    cuCtxGetCurrent.restype = ctypes.c_int          # CUresult == int
    cuCtxGetCurrent.argtypes = [POINTER(CUcontext)] # CUcontext *pctx
    log("init_nvencode_library() %s.cuCtxGetCurrent=%s", os.path.splitext(cuda_libname)[0], cuCtxGetCurrent)
    #nvidia-encode:
    log("init_nvencode_library() will try to load %s", nvenc_libname)
    try:
        x = load(nvenc_libname)
        log("init_nvencode_library() %s(%s)=%s", load, nvenc_libname, x)
    except Exception as e:
        log("failed to load '%s'", nvenc_libname, exc_info=True)
        raise ImportError("nvenc: the required library %s cannot be loaded: %s" % (nvenc_libname, e)) from None
    NvEncodeAPICreateInstance = x.NvEncodeAPICreateInstance
    NvEncodeAPICreateInstance.restype = ctypes.c_int
    NvEncodeAPICreateInstance.argtypes = [ctypes.c_void_p]
    log("init_nvencode_library() NvEncodeAPICreateInstance=%s", NvEncodeAPICreateInstance)
    #NVENCSTATUS NvEncodeAPICreateInstance(NV_ENCODE_API_FUNCTION_LIST *functionList)


cdef guidstr(GUID guid):
    #really ugly! (surely there's a way using struct.unpack ?)
    #is this even endian safe? do we care? (always on the same system)
    parts = []
    for v, s in ((guid.Data1, 4), (guid.Data2, 2), (guid.Data3, 2)):
        b = bytearray(s)
        for j in range(s):
            b[s-j-1] = v % 256
            v = v // 256
        parts.append(b)
    parts.append(bytearray(guid.get("Data4")[:2]))
    parts.append(bytearray(guid.get("Data4")[2:8]))
    s = "-".join(binascii.hexlify(b).upper().decode("latin1") for b in parts)
    #log.info("guidstr(%s)=%s", guid, s)
    return s


cdef GUID c_parseguid(src) except *:
    #just as ugly as above - shoot me now
    #only this format is allowed:
    sample_guid = b"CE788D20-AAA9-4318-92BB-AC7E858C8D36"
    bsrc = strtobytes(src.upper())
    if len(bsrc)!=len(sample_guid):
        raise ValueError("invalid GUID format: expected %s characters but got %s" % (len(sample_guid), len(src)))
    cdef int i
    #validate the input bytestring:
    hexords = tuple(x for x in b"0123456789ABCDEF")
    for i in range(len(sample_guid)):
        if sample_guid[i]==ord(b"-"):
            #dash must be in the same place:
            if bsrc[i]!=ord(b"-"):
                raise ValueError("invalid GUID format: character at position %s is not '-': %s" % (i, src[i]))
        else:
            #must be an hex number:
            c = bsrc[i]
            if c not in hexords:
                raise ValueError("invalid GUID format: character at position %s is not in hex: %s" % (i, chr(c)))
    parts = bsrc.split(b"-")    #ie: ["CE788D20", "AAA9", ...]
    nparts = []
    for i, s in (0, 4), (1, 2), (2, 2), (3, 2), (4, 6):
        part = parts[i]
        binv = binascii.unhexlify(part)
        #log("c_parseguid bytes(%s)=%r", part, binv)
        v = 0
        for j in range(s):
            c = binv[j]
            v += c<<((s-j-1)*8)
        nparts.append(v)
    cdef GUID guid
    guid.Data1 = nparts[0]
    guid.Data2 = nparts[1]
    guid.Data3 = nparts[2]
    v = (nparts[3]<<48) + nparts[4]
    for i in range(8):
        guid.Data4[i] = <uint8_t> ((v>>((7-i)*8)) % 256)
    log("c_parseguid(%s)=%s", src, guid)
    return guid


def parseguid(s) -> GUID:
    return c_parseguid(s)


def test_parse() -> None:
    sample_guid = "CE788D20-AAA9-4318-92BB-AC7E858C8D36"
    x = c_parseguid(sample_guid)
    v = guidstr(x)
    assert v==sample_guid, "expected %s but got %s" % (sample_guid, v)


test_parse()


cdef GUID CLIENT_KEY_GUID
memset(&CLIENT_KEY_GUID, 0, sizeof(GUID))
CLIENT_KEYS_STR = get_license_keys(NVENCAPI_MAJOR_VERSION) + get_license_keys()
if CLIENT_KEYS_STR:
    #if we have client keys, parse them and keep the ones that look valid
    validated = []
    for x in CLIENT_KEYS_STR:
        if x:
            try:
                CLIENT_KEY_GUID = c_parseguid(x)
                validated.append(x)
            except Exception as e:
                log.error("invalid nvenc client key specified: '%s' (%s)", x, e)
                del e
    CLIENT_KEYS_STR = validated

CODEC_GUIDS: Dict[str, str] = {
    guidstr(NV_ENC_CODEC_H264_GUID)         : "H264",
    guidstr(NV_ENC_CODEC_HEVC_GUID)         : "HEVC",
}

cdef codecstr(GUID guid):
    s = guidstr(guid)
    return CODEC_GUIDS.get(s, s)


CODEC_PROFILES_GUIDS: Dict[str, Dict[str, str]] = {
    guidstr(NV_ENC_CODEC_H264_GUID) : {
        guidstr(NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID)       : "auto",
        guidstr(NV_ENC_H264_PROFILE_BASELINE_GUID)          : "baseline",
        guidstr(NV_ENC_H264_PROFILE_MAIN_GUID)              : "main",
        guidstr(NV_ENC_H264_PROFILE_HIGH_GUID)              : "high",
        guidstr(NV_ENC_H264_PROFILE_STEREO_GUID)            : "stereo",
        #guidstr(NV_ENC_H264_PROFILE_SVC_TEMPORAL_SCALABILTY): "temporal",
        guidstr(NV_ENC_H264_PROFILE_PROGRESSIVE_HIGH_GUID)  : "progressive-high",
        guidstr(NV_ENC_H264_PROFILE_CONSTRAINED_HIGH_GUID)  : "constrained-high",
        #new in SDK v4:
        guidstr(NV_ENC_H264_PROFILE_HIGH_444_GUID)          : "high-444",
    },
    guidstr(NV_ENC_CODEC_HEVC_GUID) : {
        guidstr(NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID)       : "auto",
        guidstr(NV_ENC_HEVC_PROFILE_MAIN_GUID)              : "main",
        guidstr(NV_ENC_HEVC_PROFILE_MAIN10_GUID)            : "main10",
        guidstr(NV_ENC_HEVC_PROFILE_FREXT_GUID)             : "frext",
    },
}

PROFILE_STR = {}
for codec_guid, profiles in CODEC_PROFILES_GUIDS.items():
    for profile_guid, profile_name in profiles.items():
        PROFILE_STR[profile_guid] = profile_name


# these presets have been deprecated for a while,
# and are finally removed in SDK v12.2
# but unfortunately they're the only ones that still work!
# see https://github.com/Xpra-org/xpra/issues/3873
PRESET_STREAMING        = "7ADD423D-D035-4F6F-AEA5-50885658643C"
PRESET_DEFAULT          = "B2DFB705-4EBD-4C49-9B5F-24A777D3E587"
PRESET_HP_GUID          = "60E4C59F-E846-4484-A56D-CD45BE9FDDF6"
PRESET_HQ_GUID          = "34DBA71D-A77B-4B8F-9C3E-B6D5DA24C012"
PRESET_BD_GUID          = "82E3E450-BDBB-4E40-989C-82A90DF9EF32"
PRESET_LOW_LATENCY      = "49DF21C5-6DFA-4FEB-9787-6ACC9EFFB726"
PRESET_LOW_LATENCY_HQ   = "C5F733B9-EA97-4CF9-BEC2-BF78A74FD105"
PRESET_LOW_LATENCY_HP   = "67082A44-4BAD-48FA-98EA-93056D150A58"
PRESET_LOSSLESS         = "D5BFB716-C604-44E7-9BB8-DEA5510FC3AC"
PRESET_LOSSLESS_HP      = "149998E7-2364-411D-82EF-179888093409"


CODEC_PRESETS_GUIDS: Dict[str, str] = {
    PRESET_STREAMING    : "streaming",
    PRESET_DEFAULT      : "default",
    PRESET_HP_GUID      : "hp",
    PRESET_HQ_GUID      : "hq",
    PRESET_BD_GUID      : "bd",
    PRESET_LOW_LATENCY  : "low-latency",
    PRESET_LOW_LATENCY_HQ : "low-latency-hq",
    PRESET_LOW_LATENCY_HP : "low-latency-hp",
    PRESET_LOSSLESS     : "lossless",
    PRESET_LOSSLESS_HP  : "lossless-hp",
    guidstr(NV_ENC_PRESET_P1_GUID)  : "P1",
    guidstr(NV_ENC_PRESET_P2_GUID)  : "P2",
    guidstr(NV_ENC_PRESET_P3_GUID)  : "P3",
    guidstr(NV_ENC_PRESET_P4_GUID)  : "P4",
    guidstr(NV_ENC_PRESET_P5_GUID)  : "P5",
    guidstr(NV_ENC_PRESET_P6_GUID)  : "P6",
    guidstr(NV_ENC_PRESET_P7_GUID)  : "P7",
}

YUV444_PRESETS: Sequence[str] = ("high-444", "lossless", "lossless-hp",)
LOSSLESS_PRESETS: Sequence[str] = ("lossless", "lossless-hp",)

cdef presetstr(GUID preset):
    s = guidstr(preset)
    return CODEC_PRESETS_GUIDS.get(s, s)


#try to map preset names to a "speed" value:
PRESET_SPEED: Dict[str, int] = {
    "lossless"      : 0,
    "lossless-hp"   : 30,
    "bd"            : 40,
    "hq"            : 50,
    "default"       : 50,
    "hp"            : 60,
    "low-latency-hq": 70,
    "low-latency"   : 80,
    "low-latency-hp": 100,
    "streaming"     : -1000,    #disabled for now
}

PRESET_QUALITY: Dict[str, int] = {
    "lossless"      : 100,
    "lossless-hp"   : 100,
    "bd"            : 80,
    "hq"            : 70,
    "low-latency-hq": 60,
    "default"       : 50,
    "hp"            : 40,
    "low-latency"   : 20,
    "low-latency-hp": 0,
    "streaming"     : -1000,    #disabled for now
    "P1"            : 10,
    "P2"            : 25,
    "P3"            : 40,
    "P4"            : 55,
    "P5"            : 70,
    "P6"            : 85,
    "P7"            : 100,
}

CHROMA_FORMATS: Dict[str, int] = {
    "BGRX" : 3,
    "r210" : 3,
    "NV12" : 1,
    "YUV444P" : 3,
}

BUFFER_FORMAT: Dict[int, str] = {
    NV_ENC_BUFFER_FORMAT_UNDEFINED              : "undefined",
    NV_ENC_BUFFER_FORMAT_NV12                   : "NV12_PL",
    NV_ENC_BUFFER_FORMAT_YV12                   : "YV12_PL",
    NV_ENC_BUFFER_FORMAT_IYUV                   : "IYUV_PL",
    NV_ENC_BUFFER_FORMAT_YUV444                 : "YUV444_PL",
    NV_ENC_BUFFER_FORMAT_YUV420_10BIT           : "YUV420_10BIT",
    NV_ENC_BUFFER_FORMAT_YUV444_10BIT           : "YUV444_10BIT",
    NV_ENC_BUFFER_FORMAT_ARGB                   : "ARGB",
    NV_ENC_BUFFER_FORMAT_ARGB10                 : "ARGB10",
    NV_ENC_BUFFER_FORMAT_AYUV                   : "AYUV",
    NV_ENC_BUFFER_FORMAT_ABGR                   : "ABGR",
    NV_ENC_BUFFER_FORMAT_ABGR10                 : "ABGR10",
}


def get_COLORSPACES(encoding: str) -> Dict[str, Sequence[str]]:
    global YUV420_ENABLED, YUV444_ENABLED, YUV444_CODEC_SUPPORT
    out_cs = []
    if YUV420_ENABLED:
        out_cs.append("YUV420P")
    if YUV444_CODEC_SUPPORT.get(encoding.lower(), YUV444_ENABLED) or NATIVE_RGB:
        out_cs.append("YUV444P")
    COLORSPACES = {
        "BGRX" : out_cs,
        "XRGB" : out_cs,
        "ARGB" : out_cs,
        }
    if SUPPORT_30BPP:
        COLORSPACES["r210"] = ("GBRP10", )
    return COLORSPACES


def get_input_colorspaces(encoding: str) -> Sequence[str]:
    return list(get_COLORSPACES(encoding).keys())


def get_output_colorspaces(encoding: str, input_colorspace: str) -> Sequence[str]:
    cs = get_COLORSPACES(encoding)
    out = cs.get(input_colorspace)
    if not out:
        raise ValueError(f"invalid input colorspace {input_colorspace} for encoding {encoding}, must be one of: {out}")
    #the output will actually be in one of those two formats once decoded
    #because internally that's what we convert to before encoding
    #(well, NV12... which is equivallent to YUV420P here...)
    return out


#Note: these counters should be per-device, but
#when we call get_runtime_factor(), we don't know which device is going to get used!
#since we have load balancing, using an overall factor isn't too bad
context_counter = AtomicInteger()
context_gen_counter = AtomicInteger()
cdef double last_context_failure = 0

# per-device preset denylist - should be mutated with device_lock held
bad_presets = {}


def get_runtime_factor() -> float:
    global last_context_failure, context_counter
    device_count = len(init_all_devices())
    max_contexts = CONTEXT_LIMIT * device_count
    cc = context_counter.get()
    #try to avoid using too many contexts
    #(usually, we can have up to 32 contexts per card)
    low_limit = min(CONTEXT_LIMIT, 1 + CONTEXT_LIMIT// 2) * device_count
    f = max(0, 1.0 - (max(0, cc-low_limit)/max(1, max_contexts-low_limit)))
    #if we have had errors recently, lower our chances further:
    cdef double failure_elapsed = monotonic()-last_context_failure
    #discount factor gradually for 1 minute:
    f /= 61-min(60, failure_elapsed)
    log("nvenc.get_runtime_factor()=%s", f)
    return f


MAX_SIZE = {}

def get_width_mask(colorspace: str) -> int:
    if colorspace.startswith("YUV42"):
        return 0xFFFE
    return 0xFFFF


def get_height_mask(colorspace: str) -> int:
    if colorspace=="YUV420":
        return 0xFFFE
    return 0xFFFF


def get_specs(encoding: str, colorspace: str) -> Sequence[VideoSpec]:
    assert encoding in get_encodings(), "invalid format: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_COLORSPACES(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_COLORSPACES(encoding))
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h
    #undocumented and found the hard way, see:
    #https://github.com/Xpra-org/xpra/issues/1046#issuecomment-765450102
    #https://github.com/Xpra-org/xpra/issues/1550
    min_w, min_h = (128, 128)
    width_mask = get_width_mask(colorspace)
    height_mask = get_height_mask(colorspace)
    #FIXME: we should probe this using WIDTH_MAX, HEIGHT_MAX!
    global MAX_SIZE
    max_w, max_h = MAX_SIZE.get(encoding, (4096, 4096))
    has_lossless_mode = colorspace in ("XRGB", "BGRX", "r210") and encoding=="h264"
    cs = VideoSpec(encoding=encoding, input_colorspace=colorspace, output_colorspaces=get_COLORSPACES(encoding)[colorspace], has_lossless_mode=LOSSLESS_CODEC_SUPPORT.get(encoding, LOSSLESS_ENABLED),
                      codec_class=Encoder, codec_type=get_type(),
                      quality=60+has_lossless_mode*40, speed=100, size_efficiency=100,
                      setup_cost=80, cpu_cost=10, gpu_cost=100,
                      #using a hardware encoder for something this small is silly:
                      min_w=min_w, min_h=min_h,
                      max_w=max_w, max_h=max_h,
                      can_scale=colorspace!="r210",
                      width_mask=width_mask, height_mask=height_mask)
    cs.get_runtime_factor = get_runtime_factor
    return (cs, )

#ie: NVENCAPI_VERSION=0x30 -> PRETTY_VERSION = [3, 0]
PRETTY_VERSION = (int(NVENCAPI_MAJOR_VERSION), int(NVENCAPI_MINOR_VERSION))


def get_version():
    return PRETTY_VERSION


def get_type() -> str:
    return "nvenc"


def get_info() -> Dict[str, Any]:
    global last_context_failure, context_counter, context_gen_counter
    info = {
        "version"           : PRETTY_VERSION,
        "device_count"      : len(get_devices() or []),
        "context_count"     : context_counter.get(),
        "generation"        : context_gen_counter.get(),
    }
    cards = get_cards()
    if cards:
        info["cards"] = cards
    #only show the version if we have it already (don't probe now)
    v = get_nvidia_module_version(False)
    if v:
        info["kernel_module_version"] = v
    if LINUX:
        info["kernel_version"] = platform.uname()[2]
    if last_context_failure>0:
        info["last_failure"] = int(monotonic()-last_context_failure)
    return info


ENCODINGS: Sequence[str] = []
def get_encodings() -> Sequence[str]:
    global ENCODINGS
    return ENCODINGS


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


cdef uintptr_t cmalloc(size_t size, what) except 0:
    cdef void *ptr = malloc(size)
    if ptr==NULL:
        raise RuntimeError("failed to allocate %i bytes of memory for %s" % (size, what))
    return <uintptr_t> ptr


cdef nvencStatusInfo(NVENCSTATUS ret):
    return NV_ENC_STATUS_TXT.get(ret, str(ret))


class NVENCException(Exception):
    def __init__(self, code, fn):
        self.function = fn
        self.code = code
        self.api_message = nvencStatusInfo(code)
        msg = "%s - returned %i" % (fn, code)
        if self.api_message:
            msg += ": %s" % self.api_message
        super().__init__(msg)


cdef inline raiseNVENC(NVENCSTATUS ret, msg):
    if DEBUG_API:
        log("raiseNVENC(%i, %s)", ret, msg)
    if ret!=0:
        raise NVENCException(ret, msg)


cdef class Encoder:
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int scaled_width
    cdef unsigned int scaled_height
    cdef unsigned int input_width
    cdef unsigned int input_height
    cdef unsigned int encoder_width
    cdef unsigned int encoder_height
    cdef object encoding
    cdef object src_format
    cdef object dst_formats
    cdef int width_mask
    cdef int height_mask
    cdef int scaling
    cdef int speed
    cdef int quality
    cdef uint32_t target_bitrate
    cdef uint32_t max_bitrate
    #PyCUDA:
    cdef object driver
    cdef object cuda_info
    cdef object pycuda_info
    cdef object cuda_device_info
    cdef object cuda_device_context
    cdef void *cuda_context_ptr
    cdef object kernel
    cdef object kernel_name
    cdef object max_block_sizes
    cdef object max_grid_sizes
    cdef unsigned long max_threads_per_block
    cdef uint64_t free_memory
    cdef uint64_t total_memory
    #NVENC:
    cdef NV_ENCODE_API_FUNCTION_LIST *functionList
    cdef NV_ENC_INITIALIZE_PARAMS *params
    cdef void *context
    cdef GUID codec
    cdef NV_ENC_REGISTERED_PTR inputHandle
    cdef object inputBuffer
    cdef object cudaInputBuffer
    cdef object cudaOutputBuffer
    cdef unsigned int inputPitch                    #note: this isn't the pitch (aka rowstride) we actually use!
                                                    #just the value returned from the allocation call
    cdef unsigned int outputPitch
    cdef void *bitstreamBuffer
    cdef NV_ENC_BUFFER_FORMAT bufferFmt
    cdef object codec_name
    cdef object preset_name
    cdef object profile_name
    cdef object pixel_format
    cdef uint8_t lossless
    #statistics, etc:
    cdef double time
    cdef uint64_t first_frame_timestamp
    cdef unsigned long frames
    cdef unsigned long index
    cdef object last_frame_times
    cdef uint64_t bytes_in
    cdef uint64_t bytes_out
    cdef uint8_t ready
    cdef uint8_t closed
    cdef uint16_t datagram
    cdef uint8_t threaded_init

    cdef object __weakref__

    cdef GUID init_codec(self) except *:
        log("init_codec()")
        codecs = self.query_codecs()
        #codecs={'H264': {"guid" : '6BC82762-4E63-4CA4-AA85-1E50F321F6BF', .. }
        internal_name = {"H265" : "HEVC"}.get(self.codec_name.upper(), self.codec_name.upper())
        guid_str = codecs.get(internal_name, {}).get("guid")
        assert guid_str, "%s not supported! (only available: %s)" % (self.codec_name, csv(codecs.keys()))
        self.codec = c_parseguid(guid_str)
        return self.codec

    cdef GUID get_codec(self):
        return self.codec

    cdef GUID get_preset(self, GUID codec) except *:
        global bad_presets
        presets = self.query_presets(codec)
        options = {}
        #if a preset was specified, give it the best score possible (-1):
        if DESIRED_PRESET:
            guid = presets.get(DESIRED_PRESET, "")
            log(f"preset override {DESIRED_PRESET!r}={guid}")
            if guid:
                return c_parseguid(guid)
        #new style presets (P1 - P7),
        #we only care about the quality here,
        #the speed is set using the "tuning"
        for i in range(1, 8):
            name = "P%i" % i
            guid = presets.get(name)
            if not guid:
                continue
            preset_quality = PRESET_QUALITY.get(name, 50)
            distance = abs(self.quality-preset_quality)
            options.setdefault(distance, []).append((name, guid))
        #TODO: figure out why the new-style presets fail
        options = {}
        #no new-style presets found,
        #fallback to older lookup code:
        if not options:
            #add all presets ranked by how far they are from the target speed and quality:
            log("presets for %s: %s (pixel format=%s)", guidstr(codec), csv(presets.keys()), self.pixel_format)
            for name, x in presets.items():
                preset_speed = PRESET_SPEED.get(name, 50)
                preset_quality = PRESET_QUALITY.get(name, 50)
                is_lossless = name in LOSSLESS_PRESETS
                log("preset %16s: speed=%5i, quality=%5i (lossless=%s - want lossless=%s)", name, preset_speed, preset_quality, is_lossless, bool(self.lossless))
                if is_lossless and self.pixel_format!="YUV444P":
                    continue
                if preset_speed>=0 and preset_quality>=0:
                    #quality (3) weighs more than speed (2):
                    v = 2 * abs(preset_speed-self.speed) + 3 * abs(preset_quality-self.quality)
                    if self.lossless!=is_lossless:
                        v -= 100
                    l = options.setdefault(v, [])
                    if x not in l:
                        l.append((name, x))
        log("get_preset(%s) speed=%s, quality=%s, lossless=%s, pixel_format=%s, options=%s", codecstr(codec), self.speed, self.quality, bool(self.lossless), self.pixel_format, options)
        device_id = self.cuda_device_context.device_id
        for score in sorted(options.keys()):
            for preset, preset_guid in options.get(score):
                if preset in bad_presets.get(device_id, []):
                    log("skipping bad preset '%s' (speed=%s, quality=%s, lossless=%s, pixel_format=%s)", preset, self.speed, self.quality, self.lossless, self.pixel_format)
                    continue

                if preset and (preset in presets.keys()):
                    log("using preset '%s' for speed=%s, quality=%s, lossless=%s, pixel_format=%s", preset, self.speed, self.quality, self.lossless, self.pixel_format)
                    return c_parseguid(preset_guid)
        raise ValueError("no matching presets available for '%s' with speed=%i and quality=%i" % (self.codec_name, self.speed, self.quality))

    def init_context(self, encoding: str, unsigned int width, unsigned int height, src_format: str,
                     options: typedict) -> None:
        assert NvEncodeAPICreateInstance is not None, "encoder module is not initialized"
        log("init_context%s", (encoding, width, height, src_format, options))
        options = options or typedict()
        cuda_device_context = options.get("cuda-device-context")
        if not cuda_device_context:
            raise RuntimeError("no cuda device context")
        self.cuda_device_context = cuda_device_context
        if src_format not in ("XRGB", "BGRX", "r210"):
            raise ValueError(f"invalid source format {src_format}")
        dst_formats = options.strtupleget("dst-formats")
        if not ("YUV420P" in dst_formats or "YUV444P" in dst_formats):
            raise ValueError(f"unsupported output formats {dst_formats}")
        self.width = width
        self.height = height
        self.quality = options.intget("quality", 50)
        self.speed = options.intget("speed", 50)
        self.scaled_width = options.intget("scaled-width", width)
        self.scaled_height = options.intget("scaled-height", height)
        self.scaling = bool(self.scaled_width!=self.width or self.scaled_height!=self.height)
        self.input_width = roundup(width, 32)
        self.input_height = roundup(height, 32)
        self.encoder_width = roundup(self.scaled_width, 32)
        self.encoder_height = roundup(self.scaled_height, 32)
        self.src_format = src_format
        self.dst_formats = dst_formats
        self.encoding = encoding
        self.codec_name = encoding.upper()      #ie: "H264"
        self.width_mask = get_width_mask(src_format)
        self.height_mask = get_height_mask(src_format)
        self.preset_name = None
        self.frames = 0
        self.pixel_format = ""
        self.last_frame_times = deque(maxlen=200)
        # this is disabled because nvenc errors out if we use sliceMode = 1
        self.datagram = 0 # options.intget("datagram", 0)
        self.update_bitrate()

        options = options or typedict()
        #the pixel format we feed into the encoder
        self.pixel_format = self.get_target_pixel_format(self.quality)
        self.profile_name = self._get_profile(options)
        self.lossless = self.get_target_lossless(self.pixel_format, self.quality)
        log("using %s %s compression at %s%% quality with pixel format %s",
            ["lossy","lossless"][self.lossless], encoding, self.quality, self.pixel_format)

        self.threaded_init = options.boolget("threaded-init", THREADED_INIT)
        if self.threaded_init:
            start_thread(self.threaded_init_device, "threaded-init-device", daemon=True, args=(options,))
        else:
            self.init_device(options)

    cdef _get_profile(self, options):
        #convert the pixel format into a "colourspace" string:
        csc_mode = "YUV420P"
        if self.pixel_format in ("BGRX", "YUV444P"):
            csc_mode = "YUV444P"
        elif self.pixel_format=="r210":
            csc_mode = "YUV444P10"
        #use the environment as default if present:
        profile = os.environ.get("XPRA_NVENC_PROFILE", "")
        profile = os.environ.get("XPRA_NVENC_%s_PROFILE" % csc_mode, profile)
        #now see if the client has requested a different value:
        profile = options.strget("h264.%s.profile" % csc_mode, profile)
        return profile

    def threaded_init_device(self, options: typedict) -> None:
        global device_lock
        with device_lock:
            if SLOW_DOWN_INIT:
                import time
                time.sleep(SLOW_DOWN_INIT)
            try:
                self.init_device(options)
            except NVENCException as e:
                log("threaded_init_device(%s)", options, exc_info=True)
                log.warn("Warning: failed to initialize NVENC device")
                if not e.api_message:
                    log.warn(" unknown error %i", e.code)
                else:
                    log.warn(" error %i:", e.code)
                    log.warn(" '%s'", e.api_message)
                self.clean()
            except Exception as e:
                log("threaded_init_device(%s)", options, exc_info=True)
                log.warn("Warning: failed to initialize device:")
                log.warn(" %s", e)
                self.clean()

    def init_device(self, options: typedict) -> None:
        global bad_presets
        cdef double start = monotonic()
        with self.cuda_device_context as cuda_context:
            self.init_cuda(cuda_context)
            self.init_cuda_kernel(cuda_context)

        device_id = self.cuda_device_context.device_id
        try:
            #the example code accesses the cuda context after a context.pop()
            #(which is weird)
            self.init_nvenc()

            record_device_success(device_id)
        except Exception as e:
            log("init_cuda failed", exc_info=True)
            if self.preset_name and isinstance(e, NVENCException) and e.code==NV_ENC_ERR_INVALID_PARAM:
                log("adding preset '%s' to bad presets", self.preset_name)
                bad_presets.setdefault(device_id, []).append(self.preset_name)
            else:
                record_device_failure(device_id)
            raise
        cdef double end = monotonic()
        self.ready = 1
        log("init_device(%s) took %1.fms", options, (end-start)*1000.0)

    def is_ready(self) -> bool:
        return bool(self.ready)

    def get_target_pixel_format(self, int quality):
        global NATIVE_RGB, YUV420_ENABLED, YUV444_ENABLED, LOSSLESS_ENABLED, YUV444_THRESHOLD, YUV444_CODEC_SUPPORT
        v = None
        hasyuv444 = YUV444_CODEC_SUPPORT.get(self.encoding, YUV444_ENABLED) and "YUV444P" in self.dst_formats
        nativergb = NATIVE_RGB and hasyuv444
        if nativergb and self.src_format in ("BGRX", ):
            v = "BGRX"
        elif self.src_format=="r210":
            v = "r210"
        else:
            hasyuv420 = YUV420_ENABLED and "YUV420P" in self.dst_formats
            if hasyuv444:
                #NVENC and the client can handle it,
                #now check quality and scaling:
                #(don't use YUV444 is we're going to downscale or use low quality anyway)
                if (quality>=YUV444_THRESHOLD and not self.scaling) or not hasyuv420:
                    v = "YUV444P"
            if not v:
                if hasyuv420:
                    v = "NV12"
                else:
                    raise ValueError("no compatible formats found for quality=%i, scaling=%s, YUV420 support=%s, YUV444 support=%s, codec=%s, dst-formats=%s" % (
                        quality, self.scaling, hasyuv420, hasyuv444, self.codec_name, self.dst_formats))
        log("get_target_pixel_format(%i)=%s for encoding=%s, scaling=%s, NATIVE_RGB=%s, YUV444_CODEC_SUPPORT=%s, YUV420_ENABLED=%s, YUV444_ENABLED=%s, YUV444_THRESHOLD=%s, LOSSLESS_ENABLED=%s, src_format=%s, dst_formats=%s",
            quality, v, self.encoding, self.scaling, bool(NATIVE_RGB), YUV444_CODEC_SUPPORT, bool(YUV420_ENABLED), bool(YUV444_ENABLED), YUV444_THRESHOLD, bool(LOSSLESS_ENABLED), self.src_format, csv(self.dst_formats))
        return v

    def get_target_lossless(self, pixel_format: str, quality : int):
        global LOSSLESS_ENABLED, LOSSLESS_CODEC_SUPPORT
        if pixel_format not in ("YUV444P", "r210"):
            return False
        if not LOSSLESS_CODEC_SUPPORT.get(self.encoding, LOSSLESS_ENABLED):
            return False
        return quality>=LOSSLESS_THRESHOLD

    def init_cuda(self, cuda_context) -> None:
        cdef int result
        cdef uintptr_t context_pointer

        global last_context_failure
        log("init_cuda(%s) pixel format=%s", cuda_context, self.pixel_format)
        try:
            log("init_cuda(%s)", cuda_context)
            self.cuda_info = get_cuda_info()
            log("init_cuda cuda info=%s", self.cuda_info)
            self.pycuda_info = get_pycuda_info()
            if self.cuda_device_context:
                log("init_cuda pycuda info=%s", self.pycuda_info)
                self.cuda_device_info = self.cuda_device_context.get_info()

            #get the CUDA context (C pointer):
            #a bit of magic to pass a cython pointer to ctypes:
            context_pointer = <uintptr_t> (&self.cuda_context_ptr)
            result = cuCtxGetCurrent(ctypes.cast(context_pointer, POINTER(ctypes.c_void_p)))
            estr = get_error_name(result)
            if DEBUG_API:
                log(f"cuCtxGetCurrent() returned {estr!r}, context_pointer=%#x, cuda context pointer=%#x",
                    context_pointer, <uintptr_t> self.cuda_context_ptr)
            if result:
                raise RuntimeError(f"failed to get current cuda context, cuCtxGetCurrent returned {estr!r}")
            if (<uintptr_t> self.cuda_context_ptr)==0:
                raise RuntimeError("invalid null cuda context pointer")
        except driver.MemoryError as e:
            last_context_failure = monotonic()
            log("init_cuda %s", e)
            raise TransientCodecException("could not initialize cuda: %s" % e) from None

    cdef void init_cuda_kernel(self, cuda_context):
        log("init_cuda_kernel(..)")
        global YUV420_ENABLED, YUV444_ENABLED, YUV444_CODEC_SUPPORT, NATIVE_RGB
        cdef unsigned int plane_size_div, wmult, hmult, max_input_stride
        #use alias to make code easier to read:
        da = driver.device_attribute
        if self.pixel_format=="BGRX":
            assert NATIVE_RGB
            kernel_name = None
            self.bufferFmt = NV_ENC_BUFFER_FORMAT_ARGB
            plane_size_div= 1
            wmult = 4
            hmult = 1
        elif self.pixel_format=="r210":
            assert NATIVE_RGB
            kernel_name = None
            self.bufferFmt = NV_ENC_BUFFER_FORMAT_ARGB10
            plane_size_div= 1
            wmult = 4
            hmult = 1
        #if supported (separate plane flag), use YUV444P:
        elif self.pixel_format=="YUV444P":
            assert YUV444_CODEC_SUPPORT.get(self.encoding, YUV444_ENABLED), "YUV444 is not enabled for %s" % self.encoding
            kernel_name = "%s_to_YUV444" % (self.src_format.replace("A", "X"))  #ie: XRGB_to_YUV444
            self.bufferFmt = NV_ENC_BUFFER_FORMAT_YUV444
            #3 full planes:
            plane_size_div = 1
            wmult = 1
            hmult = 3
        elif self.pixel_format=="NV12":
            assert YUV420_ENABLED
            kernel_name = "%s_to_NV12" % (self.src_format.replace("A", "X"))  #ie: BGRX_to_NV12
            self.bufferFmt = NV_ENC_BUFFER_FORMAT_NV12
            #1 full Y plane and 2 U+V planes subsampled by 4:
            plane_size_div = 2
            wmult = 1
            hmult = 3
        else:
            raise ValueError(f"BUG: invalid dst format {self.pixel_format!r}")

        #allocate CUDA "output" buffer (on device):
        #this is the buffer we feed into the encoder
        #the data may come from the CUDA kernel,
        #or it may be uploaded directly there (ie: BGRX)
        self.cudaOutputBuffer, self.outputPitch = driver.mem_alloc_pitch(self.encoder_width*wmult, self.encoder_height*hmult//plane_size_div, 16)
        log("CUDA Output Buffer=%#x, pitch=%s", int(self.cudaOutputBuffer), self.outputPitch)

        if kernel_name:
            #load the kernel:
            self.kernel = get_CUDA_function(kernel_name)
            self.kernel_name = kernel_name
            if not self.kernel:
                raise RuntimeError(f"failed to load {self.kernel_name!r} for cuda context {cuda_context}")
            #allocate CUDA input buffer (on device) 32-bit RGBX
            #(and make it bigger just in case - subregions from XShm can have a huge rowstride)
            #(this is the buffer we feed into the kernel)
            max_input_stride = MAX(2560, self.input_width)*4
            self.cudaInputBuffer, self.inputPitch = driver.mem_alloc_pitch(max_input_stride, self.input_height, 16)
            log("CUDA Input Buffer=%#x, pitch=%s", int(self.cudaInputBuffer), self.inputPitch)
            #CUDA
            d = self.cuda_device_context.device
            self.max_block_sizes = d.get_attribute(da.MAX_BLOCK_DIM_X), d.get_attribute(da.MAX_BLOCK_DIM_Y), d.get_attribute(da.MAX_BLOCK_DIM_Z)
            self.max_grid_sizes = d.get_attribute(da.MAX_GRID_DIM_X), d.get_attribute(da.MAX_GRID_DIM_Y), d.get_attribute(da.MAX_GRID_DIM_Z)
            log("max_block_sizes=%s, max_grid_sizes=%s", self.max_block_sizes, self.max_grid_sizes)
            self.max_threads_per_block = self.kernel.get_attribute(driver.function_attribute.MAX_THREADS_PER_BLOCK)
            log("max_threads_per_block=%s", self.max_threads_per_block)
        else:
            #we don't use a CUDA kernel
            self.kernel_name = ""
            self.kernel = None
            self.cudaInputBuffer = None
            self.inputPitch = self.outputPitch
            self.max_block_sizes = 0
            self.max_grid_sizes = 0
            self.max_threads_per_block = 0

        #allocate input buffer on host:
        #this is the buffer we upload to the device
        self.inputBuffer = driver.pagelocked_zeros(self.inputPitch*self.input_height, dtype=numpy.byte)
        log("inputBuffer=%s (size=%s)", self.inputBuffer, self.inputPitch*self.input_height)

    def init_nvenc(self) -> None:
        log("init_nvenc()")
        self.open_encode_session()
        self.init_encoder()
        self.init_buffers()

    def init_encoder(self) -> None:
        log("init_encoder()")
        cdef GUID codec = self.init_codec()
        cdef NVENCSTATUS r
        cdef NV_ENC_INITIALIZE_PARAMS *params = <NV_ENC_INITIALIZE_PARAMS*> cmalloc(sizeof(NV_ENC_INITIALIZE_PARAMS), "initialization params")
        assert memset(params, 0, sizeof(NV_ENC_INITIALIZE_PARAMS))!=NULL
        try:
            self.init_params(codec, params)
            if DEBUG_API:
                log("nvEncInitializeEncoder using encode=%s", codecstr(codec))
            with nogil:
                r = self.functionList.nvEncInitializeEncoder(self.context, params)
            raiseNVENC(r, "initializing encoder")
            log("NVENC initialized with '%s' codec and '%s' preset" % (self.codec_name, self.preset_name))

            self.dump_caps(self.codec_name, codec)
        finally:
            if params.encodeConfig!=NULL:
                free(params.encodeConfig)
            free(params)

    cdef dump_caps(self, codec_name, GUID codec):
        #test all caps:
        caps = {}
        for cap, descr in CAPS_NAMES.items():
            if cap!=NV_ENC_CAPS_EXPOSED_COUNT:
                v = self.query_encoder_caps(codec, cap)
                caps[descr] = v
        log("caps(%s)=%s", codec_name, caps)

    cdef void init_params(self, GUID codec, NV_ENC_INITIALIZE_PARAMS *params):
        #caller must free the config!
        assert self.context, "context is not initialized"
        cdef GUID preset = self.get_preset(self.codec)
        self.preset_name = CODEC_PRESETS_GUIDS.get(guidstr(preset), guidstr(preset))
        log("init_params(%s) using preset=%s", codecstr(codec), presetstr(preset))
        profiles = self.query_profiles(codec)
        if self.profile_name and profiles and self.profile_name not in profiles:
            self.profile_name = tuple(profiles.keys())[0]
        profile_guidstr = profiles.get(self.profile_name)
        cdef GUID profile
        if profile_guidstr:
            profile = c_parseguid(profile_guidstr)
        else:
            profile = NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID
        log("using profile=%s", PROFILE_STR.get(guidstr(profile)))

        input_format = BUFFER_FORMAT[self.bufferFmt]
        input_formats = self.query_input_formats(codec)
        if input_format not in input_formats:
            raise ValueError(f"{self.codec_name} does not support {input_format}, only: {input_formats}")

        assert memset(params, 0, sizeof(NV_ENC_INITIALIZE_PARAMS))!=NULL
        params.version = NV_ENC_INITIALIZE_PARAMS_VER
        params.encodeGUID = codec
        params.presetGUID = preset
        params.encodeWidth = self.encoder_width
        params.encodeHeight = self.encoder_height
        params.maxEncodeWidth = self.encoder_width
        params.maxEncodeHeight = self.encoder_height
        params.darWidth = self.encoder_width
        params.darHeight = self.encoder_height
        params.enableEncodeAsync = 0            #not supported on Linux
        params.enablePTD = 1                    #not supported in sync mode!?
        params.frameRateNum = 30
        params.frameRateDen = 1

        #apply preset:
        cdef NV_ENC_PRESET_CONFIG *presetConfig = self.get_preset_config(self.preset_name, codec, preset)
        if presetConfig==NULL:
            raise RuntimeError(f"could not find preset {self.preset_name}")
        cdef NV_ENC_CONFIG *config = <NV_ENC_CONFIG*> cmalloc(sizeof(NV_ENC_CONFIG), "encoder config")
        assert memcpy(config, &presetConfig.presetCfg, sizeof(NV_ENC_CONFIG))!=NULL
        free(presetConfig)
        config.version = NV_ENC_CONFIG_VER
        config.profileGUID = profile
        self.tune_preset(config)
        params.encodeConfig = config

    cdef int get_chroma_format(self):
        cdef int chroma = CHROMA_FORMATS.get(self.pixel_format, -1)
        if chroma<0:
            raise ValueError(f"unknown pixel format {self.pixel_format!r}")
        log("get_chroma_format(%s)=%s", self.pixel_format, chroma)
        return chroma

    cdef tune_preset(self, NV_ENC_CONFIG *config):
        config.gopLength = NVENC_INFINITE_GOPLENGTH
        config.frameIntervalP = 1
        config.frameFieldMode = NV_ENC_PARAMS_FRAME_FIELD_MODE_FRAME
        self.tune_qp(&config.rcParams)
        cdef NV_ENC_CONFIG_H264 *h264 = &config.encodeCodecConfig.h264Config
        cdef NV_ENC_CONFIG_HEVC *hevc = &config.encodeCodecConfig.hevcConfig
        if self.codec_name=="H264":
            self.tune_h264(&config.encodeCodecConfig.h264Config, config.gopLength)
        elif self.codec_name=="H265":
            self.tune_hevc(&config.encodeCodecConfig.hevcConfig, config.gopLength)
        else:
            raise ValueError(f"invalid codec name {self.codec_name}")

    cdef tune_qp(self, NV_ENC_RC_PARAMS *rc):
        if self.lossless:
            rc.rateControlMode = NV_ENC_PARAMS_RC_CONSTQP
            rc.constQP.qpInterB = 0
            rc.constQP.qpInterP = 0
            rc.constQP.qpIntra  = 0
            return
        #rc.multiPass = 0
        rc.rateControlMode = NV_ENC_PARAMS_RC_VBR
        #rc.zeroReorderDelay = 1       #zero-latency
        QP_MAX_VALUE = 51       #255 for AV1!

        def qp(pct: float) -> int:
            return QP_MAX_VALUE-max(0, min(QP_MAX_VALUE, round(QP_MAX_VALUE * pct / 100)))
        qpmin = qp(self.quality-10)
        qpmax = qp(self.quality+10)
        qp = min(QP_MAX_VALUE, max(0, round((qpmin + qpmax)//2)))
        rc.enableMinQP = 1
        rc.enableMaxQP = 1
        rc.minQP.qpInterB = qpmin
        rc.minQP.qpInterP = qpmin
        rc.minQP.qpIntra  = qpmin
        rc.maxQP.qpInterB = qpmax
        rc.maxQP.qpInterP = qpmax
        rc.maxQP.qpIntra = qpmax
        rc.enableInitialRCQP = 1
        rc.initialRCQP.qpInterP = qp
        rc.initialRCQP.qpIntra = qp
        #cbr:
        #rc.targetQuality = qp
        #rc.targetQualityLSB = 0
        #rc.averageBitRate = 1
        #rc.vbvBufferSize = 1
        #rc.averageBitRate = self.max_bitrate or 10*1024*1024
        #rc.maxBitRate = self.max_bitrate or 10*1024*1024
        #log("qp: %i", qp)
        #rcParams.constQP.qpInterP = qp
        #rcParams.constQP.qpInterB = qp
        #rcParams.constQP.qpIntra = qp

    cdef tune_h264(self, NV_ENC_CONFIG_H264 *h264, int gopLength):
        h264.level = NV_ENC_LEVEL_H264_5 #NV_ENC_LEVEL_AUTOSELECT
        h264.chromaFormatIDC = self.get_chroma_format()
        h264.disableSPSPPS = 0
        if self.datagram:
            h264.sliceMode = 1
            h264.sliceModeData = self.datagram
            h264.repeatSPSPPS = 1
        else:
            h264.sliceMode = 3            #sliceModeData specifies the number of slices
            h264.sliceModeData = 1        #1 slice!
        h264.repeatSPSPPS = 0
        h264.outputAUD = 1
        h264.outputPictureTimingSEI = 1
        h264.idrPeriod = gopLength
        h264.enableIntraRefresh = INTRA_REFRESH
        if INTRA_REFRESH:
            h264.intraRefreshPeriod = 16
            #h264.singleSliceIntraRefresh = 0
        #h264.maxNumRefFrames = 0
        cdef NV_ENC_CONFIG_H264_VUI_PARAMETERS *vui = &h264.h264VUIParameters
        vui.videoSignalTypePresentFlag = 1          # videoFormat, videoFullRangeFlag and colourDescriptionPresentFlag are present
        vui.videoFormat = 0                         # 0=Component
        vui.videoFullRangeFlag = 1
        vui.colourDescriptionPresentFlag = 0
        #vui.colourPrimaries = 1   #AVCOL_PRI_BT709 ?
        #vui.transferCharacteristics = 1   #AVCOL_TRC_BT709 ?
        #vui.colourMatrix = 5    #AVCOL_SPC_BT470BG  - switch to AVCOL_SPC_BT709?

    cdef tune_hevc(self, NV_ENC_CONFIG_HEVC *hevc, int gopLength):
        hevc.chromaFormatIDC = self.get_chroma_format()
        #hevc.level = NV_ENC_LEVEL_HEVC_5
        hevc.idrPeriod = gopLength
        hevc.enableIntraRefresh = INTRA_REFRESH
        #hevc.pixelBitDepthMinus8 = 2*int(self.bufferFmt==NV_ENC_BUFFER_FORMAT_ARGB10)
        #hevc.maxNumRefFramesInDPB = 16
        #hevc.hevcVUIParameters.videoFormat = ...
        cdef NV_ENC_CONFIG_HEVC_VUI_PARAMETERS *vui = &hevc.hevcVUIParameters
        vui.videoSignalTypePresentFlag = 1          # videoFormat, videoFullRangeFlag and colourDescriptionPresentFlag are present
        vui.videoFormat = 0                         # 0=Component
        vui.videoFullRangeFlag = 1
        vui.colourDescriptionPresentFlag = 0
        #vui.colourPrimaries = 1
        #vui.transferCharacteristics = 1
        #vui.colourMatrix = 5

    def init_buffers(self) -> None:
        log("init_buffers()")
        cdef NV_ENC_REGISTER_RESOURCE registerResource
        cdef NV_ENC_CREATE_BITSTREAM_BUFFER createBitstreamBufferParams
        assert self.context, "context is not initialized"
        #register CUDA input buffer:
        memset(&registerResource, 0, sizeof(NV_ENC_REGISTER_RESOURCE))
        registerResource.version = NV_ENC_REGISTER_RESOURCE_VER
        registerResource.resourceType = NV_ENC_INPUT_RESOURCE_TYPE_CUDADEVICEPTR
        cdef uintptr_t resource = int(self.cudaOutputBuffer)
        registerResource.resourceToRegister = <void *> resource
        registerResource.width = self.encoder_width
        registerResource.height = self.encoder_height
        registerResource.pitch = self.outputPitch
        registerResource.bufferFormat = self.bufferFmt
        if DEBUG_API:
            log("nvEncRegisterResource(%#x)", <uintptr_t> &registerResource)
        cdef NVENCSTATUS r                  #
        with nogil:
            r = self.functionList.nvEncRegisterResource(self.context, &registerResource)
        raiseNVENC(r, "registering CUDA input buffer")
        self.inputHandle = registerResource.registeredResource
        log("input handle for CUDA buffer: %#x", <uintptr_t> self.inputHandle)

        #allocate output buffer:
        memset(&createBitstreamBufferParams, 0, sizeof(NV_ENC_CREATE_BITSTREAM_BUFFER))
        createBitstreamBufferParams.version = NV_ENC_CREATE_BITSTREAM_BUFFER_VER
        #this is the uncompressed size - must be big enough for the compressed stream:
        createBitstreamBufferParams.size = min(1024*1024*2, self.encoder_width*self.encoder_height*3//2)
        createBitstreamBufferParams.memoryHeap = NV_ENC_MEMORY_HEAP_SYSMEM_CACHED
        if DEBUG_API:
            log("nvEncCreateBitstreamBuffer(%#x)", <uintptr_t> &createBitstreamBufferParams)
        with nogil:
            r = self.functionList.nvEncCreateBitstreamBuffer(self.context, &createBitstreamBufferParams)
        raiseNVENC(r, "creating output buffer")
        self.bitstreamBuffer = createBitstreamBufferParams.bitstreamBuffer
        log("output bitstream buffer=%#x", <uintptr_t> self.bitstreamBuffer)
        if self.bitstreamBuffer==NULL:
            raise RuntimeError("bitstream buffer pointer is null")

    def get_info(self) -> Dict[str, Any]:
        global YUV444_CODEC_SUPPORT, YUV444_ENABLED, LOSSLESS_CODEC_SUPPORT, LOSSLESS_ENABLED
        cdef double pps
        info = get_info()
        info |= {
            "width"     : self.width,
            "height"    : self.height,
            "frames"    : int(self.frames),
            "codec"     : self.codec_name,
            "encoder_width"     : self.encoder_width,
            "encoder_height"    : self.encoder_height,
            "bitrate"           : self.target_bitrate,
            "quality"           : self.quality,
            "speed"             : self.speed,
            "lossless"  : {
                           ""          : self.lossless,
                           "supported" : LOSSLESS_CODEC_SUPPORT.get(self.encoding, LOSSLESS_ENABLED),
                           "threshold" : LOSSLESS_THRESHOLD
                },
            "yuv444" : {
                        "supported" : YUV444_CODEC_SUPPORT.get(self.encoding, YUV444_ENABLED),
                        "threshold" : YUV444_THRESHOLD,
                        },
            "cuda-device"   : self.cuda_device_info or {},
            "cuda"          : self.cuda_info or {},
            "pycuda"        : self.pycuda_info or {},
        }
        if self.scaling:
            info |= {
                "input_width"       : self.input_width,
                "input_height"      : self.input_height,
            }
        if self.src_format:
            info["src_format"] = self.src_format
        if self.pixel_format:
            info["pixel_format"] = self.pixel_format
        cdef unsigned long long b = self.bytes_in
        if b>0 and self.bytes_out>0:
            info |= {
                "bytes_in"  : self.bytes_in,
                "bytes_out" : self.bytes_out,
                "ratio_pct" : int(100 * self.bytes_out // b)
            }
        if self.preset_name:
            info["preset"] = self.preset_name
        if self.profile_name:
            info["profile"] = self.profile_name
        cdef double t = self.time
        info["total_time_ms"] = int(self.time*1000.0)
        if self.frames>0 and t>0:
            pps = self.width * self.height * self.frames / t
            info["pixels_per_second"] = int(pps)
        info["free_memory"] = int(self.free_memory)
        info["total_memory"] = int(self.total_memory)
        cdef uint64_t m = self.total_memory
        if m>0:
            info["free_memory_pct"] = int(100.0*self.free_memory/m)
        #calculate fps:
        cdef int f = 0
        cdef double now = monotonic()
        cdef double last_time = now
        cdef double cut_off = now-10.0
        cdef double ms_per_frame = 0
        for start,end in tuple(self.last_frame_times):
            if end>cut_off:
                f += 1
                last_time = min(last_time, end)
                ms_per_frame += (end-start)
        if f>0 and last_time<now:
            info["fps"] = int(0.5+f/(now-last_time))
            info["ms_per_frame"] = int(1000.0*ms_per_frame/f)
        return info

    def __repr__(self):
        return "nvenc(%s/%s/%s - %s - %4ix%-4i)" % (self.src_format, self.pixel_format, self.codec_name, self.preset_name, self.width, self.height)

    def is_closed(self) -> bool:
        return bool(self.closed)

    def __dealloc__(self):
        if not self.closed:
            self.clean()

    def clean(self) -> None:
        if not self.closed:
            self.closed = 1
            if self.threaded_init:
                start_thread(self.threaded_clean, "threaded-clean", daemon=True)
            else:
                self.do_clean()

    def threaded_clean(self) -> None:
        global device_lock
        with device_lock:
            self.do_clean()

    def do_clean(self) -> None:
        cdc = self.cuda_device_context
        log("clean() cuda_context=%s, encoder context=%#x", cdc, <uintptr_t> self.context)
        if cdc:
            with cdc:
                self.cuda_clean()
                self.cuda_device_context = None
        self.width = 0
        self.height = 0
        self.input_width = 0
        self.input_height = 0
        self.encoder_width = 0
        self.encoder_height = 0
        self.src_format = ""
        self.dst_formats = []
        self.scaling = 0
        self.speed = 0
        self.quality = 0
        #PyCUDA:
        self.driver = 0
        self.cuda_info = None
        self.pycuda_info = None
        self.cuda_device_info = None
        self.kernel = None
        self.kernel_name = ""
        self.max_block_sizes = 0
        self.max_grid_sizes = 0
        self.max_threads_per_block = 0
        self.free_memory = 0
        self.total_memory = 0
        #NVENC (mostly already cleaned up in cuda_clean):
        self.inputPitch = 0
        self.outputPitch = 0
        self.bitstreamBuffer = NULL
        self.bufferFmt = NV_ENC_BUFFER_FORMAT_UNDEFINED
        self.codec_name = ""
        self.preset_name = ""
        self.pixel_format = ""
        #statistics, etc:
        self.time = 0
        self.frames = 0
        self.first_frame_timestamp = 0
        self.last_frame_times = []
        self.bytes_in = 0
        self.bytes_out = 0
        log("clean() done")

    cdef cuda_clean(self):
        log("cuda_clean()")
        cdef NVENCSTATUS r
        if self.context!=NULL and self.frames>0:
            try:
                self.flushEncoder()
            except Exception as e:
                log.warn("got exception on flushEncoder, continuing anyway", exc_info=True)
        self.buffer_clean()
        if self.context!=NULL:
            if self.bitstreamBuffer!=NULL:
                log("cuda_clean() destroying output bitstream buffer %#x", <uintptr_t> self.bitstreamBuffer)
                if DEBUG_API:
                    log("nvEncDestroyBitstreamBuffer(%#x)", <uintptr_t> self.bitstreamBuffer)
                with nogil:
                    r = self.functionList.nvEncDestroyBitstreamBuffer(self.context, self.bitstreamBuffer)
                raiseNVENC(r, "destroying output buffer")
                self.bitstreamBuffer = NULL
            log("cuda_clean() destroying encoder %#x", <uintptr_t> self.context)
            if DEBUG_API:
                log("nvEncDestroyEncoder(%#x)", <uintptr_t> self.context)
            with nogil:
                r = self.functionList.nvEncDestroyEncoder(self.context)
            raiseNVENC(r, "destroying context")
            self.functionList = NULL
            self.context = NULL
            global context_counter
            context_counter.decrease()
            log(f"cuda_clean() (still {context_counter} contexts in use)")
        else:
            log("skipping encoder context cleanup")
        self.cuda_context_ptr = <void *> 0

    def buffer_clean(self) -> None:
        if self.inputHandle!=NULL and self.context!=NULL:
            log("buffer_clean() unregistering CUDA output buffer input handle %#x", <uintptr_t> self.inputHandle)
            if DEBUG_API:
                log("nvEncUnregisterResource(%#x)", <uintptr_t> self.inputHandle)
            with nogil:
                r = self.functionList.nvEncUnregisterResource(self.context, self.inputHandle)
            raiseNVENC(r, "unregistering CUDA input buffer")
            self.inputHandle = NULL
        if self.inputBuffer is not None:
            log("buffer_clean() freeing CUDA host buffer %s", self.inputBuffer)
            self.inputBuffer = None
        if self.cudaInputBuffer is not None:
            log("buffer_clean() freeing CUDA input buffer %#x", int(self.cudaInputBuffer))
            self.cudaInputBuffer.free()
            self.cudaInputBuffer = None
        if self.cudaOutputBuffer is not None:
            log("buffer_clean() freeing CUDA output buffer %#x", int(self.cudaOutputBuffer))
            self.cudaOutputBuffer.free()
            self.cudaOutputBuffer = None

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "nvenc"

    def get_encoding(self) -> str:
        return self.encoding

    def get_src_format(self) -> str:
        return self.src_format

    def set_encoding_speed(self, int speed) -> None:
        if self.speed!=speed:
            self.speed = speed
            self.update_bitrate()

    def set_encoding_quality(self, int quality) -> None:
        #cdef NV_ENC_RECONFIGURE_PARAMS reconfigure_params
        assert self.context, "context is not initialized"
        if self.quality==quality:
            return
        log("set_encoding_quality(%s) current quality=%s", quality, self.quality)
        if quality<LOSSLESS_THRESHOLD:
            #edge resistance:
            raw_delta = quality-self.quality
            max_delta = max(-1, min(1, raw_delta))*10
            if abs(raw_delta)<abs(max_delta):
                delta = raw_delta
            else:
                delta = max_delta
            target_quality = quality-delta
        else:
            target_quality = 100
        self.quality = quality
        log("set_encoding_quality(%s) target quality=%s", quality, target_quality)
        #code removed:
        #new_pixel_format = self.get_target_pixel_format(target_quality)
        #etc...
        #we can't switch pixel format,
        #because we would need to free the buffers and re-allocate new ones
        #best to just tear down the encoder context and create a new one
        return

    def update_bitrate(self) -> None:
        #use an exponential scale so for a 1Kx1K image (after scaling), roughly:
        #speed=0   -> 1Mbit/s
        #speed=50  -> 10Mbit/s
        #speed=90  -> 66Mbit/s
        #speed=100 -> 100Mbit/s
        MPixels = (self.encoder_width * self.encoder_height) / (1000.0 * 1000.0)
        if self.pixel_format=="NV12":
            #subsampling halves the input size:
            mult = 0.5
        else:
            #yuv444p preserves it:
            mult = 1.0
        lim = 100*1000000
        self.target_bitrate = min(lim, max(1000000, int(((0.5+self.speed/200.0)**8)*lim*MPixels*mult)))
        self.max_bitrate = 2*self.target_bitrate

    cdef flushEncoder(self):
        cdef NV_ENC_PIC_PARAMS pic
        cdef NVENCSTATUS r
        assert self.context, "context is not initialized"
        memset(&pic, 0, sizeof(NV_ENC_PIC_PARAMS))
        pic.version = NV_ENC_PIC_PARAMS_VER
        pic.encodePicFlags = NV_ENC_PIC_FLAG_EOS
        if DEBUG_API:
            log("nvEncEncodePicture(%#x)", <uintptr_t> &pic)
        with nogil:
            r = self.functionList.nvEncEncodePicture(self.context, &pic)
        raiseNVENC(r, "flushing encoder buffer")

    def compress_image(self, image: ImageWrapper, options: typedict, int retry=0) -> Tuple[bytes, Dict]:
        options = options or {}
        cuda_device_context = options.get("cuda-device-context")
        assert cuda_device_context, "no cuda device context"
        #cuda_device_context.__enter__ does self.context.push()
        with cuda_device_context as cuda_context:
            quality = options.get("quality", -1)
            if quality>=0:
                self.set_encoding_quality(quality)
            speed = options.get("speed", -1)
            if speed>=0:
                self.set_encoding_speed(speed)
            return self.do_compress_image(cuda_context, image)

    cdef do_compress_image(self, cuda_context, image: ImageWrapper):
        assert self.context, "nvenc context is not initialized"
        assert cuda_context, "missing device context"
        cdef unsigned int w = image.get_width()
        cdef unsigned int h = image.get_height()
        gpu_buffer = image.get_gpu_buffer()
        cdef unsigned int stride = image.get_rowstride()
        log("do_compress_image(%s) kernel=%s, GPU buffer=%#x, stride=%i, input pitch=%i, output pitch=%i",
            image, self.kernel_name, int(gpu_buffer or 0), stride, self.inputPitch, self.outputPitch)
        assert image.get_planes()==ImageWrapper.PACKED, "invalid number of planes: %s" % image.get_planes()
        assert (w & self.width_mask)<=self.input_width, "invalid width: %s" % w
        assert (h & self.height_mask)<=self.input_height, "invalid height: %s" % h
        assert self.inputBuffer is not None, "BUG: encoder is closed?"

        if self.frames==0:
            #first frame, record pts:
            self.first_frame_timestamp = image.get_timestamp()

        cdef unsigned long input_size
        if self.kernel:
            #copy to input buffer, CUDA kernel converts into output buffer:
            if GPU_MEMCOPY and gpu_buffer and stride<=self.inputPitch:
                driver.memcpy_dtod(self.cudaInputBuffer, int(gpu_buffer), stride*h)
                log("GPU memcopy %i bytes from %#x to %#x", stride*h, int(gpu_buffer), int(self.cudaInputBuffer))
            else:
                stride = self.copy_image(image, False)
                log("memcpy_htod(cudaOutputBuffer=%s, inputBuffer=%s)", self.cudaOutputBuffer, self.inputBuffer)
                driver.memcpy_htod(self.cudaInputBuffer, self.inputBuffer)
            self.exec_kernel(cuda_context, w, h, stride)
            input_size = self.inputPitch * self.input_height
        else:
            #go direct to the CUDA "output" buffer:
            if GPU_MEMCOPY and gpu_buffer and stride<=self.outputPitch:
                driver.memcpy_dtod(self.cudaOutputBuffer, int(gpu_buffer), stride*h)
                log("GPU memcopy %i bytes from %#x to %#x", stride*h, int(gpu_buffer), int(self.cudaOutputBuffer))
            else:
                stride = self.copy_image(image, True)
                driver.memcpy_htod(self.cudaOutputBuffer, self.inputBuffer)
            input_size = stride * self.encoder_height
        self.bytes_in += input_size

        cdef NV_ENC_INPUT_PTR mappedResource = self.map_input_resource()
        assert mappedResource!=NULL
        try:
            return self.nvenc_compress(input_size, mappedResource, image.get_timestamp(), image.get_full_range())
        finally:
            self.unmap_input_resource(mappedResource)

    cdef unsigned int copy_image(self, image, int strict_stride) except -1:
        if DEBUG_API:
            log("copy_image(%s, %i)", image, strict_stride)
        cdef unsigned int image_stride = image.get_rowstride()
        #input_height may be smaller if we have rounded down:
        cdef unsigned int h = min(image.get_height(), self.input_height)
        cdef unsigned int i = 0
        cdef unsigned int stride, min_stride, x, y
        pixels = image.get_pixels()
        if not pixels:
            raise ValueError(f"no pixels in {image}")
        #copy to input buffer:
        cdef object buf
        if isinstance(pixels, (bytearray, bytes)):
            pixels = memoryview(pixels)
        if isinstance(pixels, memoryview):
            #copy memoryview to inputBuffer directly:
            buf = self.inputBuffer
        else:
            #this is a numpy.ndarray type:
            buf = self.inputBuffer.data
        cdef double start = monotonic()
        cdef unsigned long copy_len
        cdef unsigned long pix_len = len(pixels)
        assert pix_len>=(h*image_stride), "image pixel buffer is too small: expected at least %ix%i=%i bytes but got %i bytes" % (h, image_stride, h*image_stride, pix_len)
        if image_stride==self.inputPitch or (image_stride<self.inputPitch and not strict_stride):
            stride = image_stride
            copy_len = h*image_stride
            #assert pix_len<=input_size, "too many pixels (expected %s max, got %s) image: %sx%s stride=%s, input buffer: stride=%s, height=%s" % (input_size, pix_len, w, h, stride, self.inputPitch, self.input_height)
            log("copying %s bytes from %s into %s (len=%i), in one shot",
                pix_len, type(pixels), type(self.inputBuffer), len(self.inputBuffer))
            #log("target: %s, %s, %s", buf.shape, buf.size, buf.dtype)
            if isinstance(pixels, memoryview):
                tmp = numpy.asarray(pixels, numpy.int8)
            else:
                tmp = numpy.frombuffer(pixels, numpy.int8)
            try:
                buf[:copy_len] = tmp[:copy_len]
            except Exception as e:
                log("copy_image%s", (image, strict_stride), exc_info=True)
                log.error("Error: numpy one shot buffer copy failed")
                log.error(" from %s to %s, length=%i", tmp, buf, copy_len)
                log.error(" original pixel buffer: %s", type(pixels))
                log.error(" for image %s", image)
                log.error(" input buffer: %i x %i", self.inputPitch, self.input_height)
        else:
            #ouch, we need to copy the source pixels into the smaller buffer
            #before uploading to the device... this is probably costly!
            stride = self.inputPitch
            min_stride = min(self.inputPitch, image_stride)
            log("copying %s bytes from %s into %s, %i stride at a time (from image stride=%i, target stride=%i)",
                stride*h, type(pixels), type(self.inputBuffer), min_stride, image_stride, self.inputPitch)
            try:
                for i in range(h):
                    x = i*self.inputPitch
                    y = i*image_stride
                    buf[x:x+min_stride] = pixels[y:y+min_stride]
            except Exception as e:
                log("copy_image%s", (image, strict_stride), exc_info=True)
                log.error("Error: numpy partial line buffer copy failed")
                log.error(" from %s to %s, length=%i", pixels, buf, min_stride)
                log.error(" for image %s", image)
                log.error(" original pixel buffer: %s", type(pixels))
                log.error(" input buffer: %i x %i", self.inputPitch, self.input_height)
                log.error(" at line %i of %i", i+1, h)
                raise
            copy_len = min_stride * h
        cdef double end = monotonic()
        cdef double elapsed = end-start
        if elapsed==0:
            #mswindows monotonic time minimum precision is 1ms...
            elapsed = 0.0001
        log("copy_image: %9i bytes uploaded in %3.1f ms: %5i MB/s", copy_len, 1000*elapsed, int(copy_len/elapsed)//1024//1024)
        return stride

    cdef exec_kernel(self, cuda_context, unsigned int w, unsigned int h, unsigned int stride):
        cdef uint8_t dx, dy
        if self.pixel_format=="NV12":
            #(these values are derived from the kernel code - which we should know nothing about here..)
            #divide each dimension by 2 since we process 4 pixels at a time:
            dx, dy = (2, 2)
        elif self.pixel_format=="YUV444P":
            #one pixel at a time:
            dx, dy = (1, 1)
        else:
            raise ValueError(f"bug: invalid pixel format {self.pixel_format!r}")

        #FIXME: find better values and validate against max_block/max_grid:
        #calculate grids/blocks:
        #a block is a group of threads: (blockw * blockh) threads
        #a grid is a group of blocks: (gridw * gridh) blocks
        cdef uint32_t blockw = 32
        cdef uint32_t blockh = 32
        cdef uint32_t gridw = MAX(1, w//(blockw*dx))
        cdef uint32_t gridh = MAX(1, h//(blockh*dy))
        #if dx or dy made us round down, add one:
        if gridw*dx*blockw<w:
            gridw += 1
        if gridh*dy*blockh<h:
            gridh += 1
        cdef unsigned int in_w = self.input_width
        cdef unsigned int in_h = self.input_height
        if self.scaling:
            #scaling so scale exact dimensions, not padded input dimensions:
            in_w, in_h = w, h

        cdef double start = monotonic()
        args = (self.cudaInputBuffer, numpy.int32(in_w), numpy.int32(in_h), numpy.int32(stride),
               self.cudaOutputBuffer, numpy.int32(self.encoder_width), numpy.int32(self.encoder_height), numpy.int32(self.outputPitch),
               numpy.int32(w), numpy.int32(h))
        if DEBUG_API:
            def lf(v):
                if isinstance(v, driver.DeviceAllocation):
                    return hex(int(v))
                return int(v)
            log_args = tuple(lf(v) for v in args)
            log("calling %s%s with block=%s, grid=%s", self.kernel_name, log_args, (blockw,blockh,1), (gridw, gridh))
        self.kernel(*args, block=(blockw,blockh,1), grid=(gridw, gridh))
        cuda_context.synchronize()
        cdef double end = monotonic()
        cdef elapsed = end-start
        if elapsed==0:
            #mswindows monotonic time minimum precision is 1ms...
            elapsed = 0.0001
        log("exec_kernel:  kernel %13s took %3.1f ms: %5i MPixels/s", self.kernel_name, elapsed*1000.0, (w*h)/elapsed//1024//1024)

    cdef NV_ENC_INPUT_PTR map_input_resource(self):
        cdef NV_ENC_MAP_INPUT_RESOURCE mapInputResource
        #map buffer so nvenc can access it:
        memset(&mapInputResource, 0, sizeof(NV_ENC_MAP_INPUT_RESOURCE))
        mapInputResource.version = NV_ENC_MAP_INPUT_RESOURCE_VER
        mapInputResource.registeredResource  = self.inputHandle
        mapInputResource.mappedBufferFmt = self.bufferFmt
        if DEBUG_API:
            log("nvEncMapInputResource(%#x) inputHandle=%#x", <uintptr_t> &mapInputResource, <uintptr_t> self.inputHandle)
        cdef NVENCSTATUS r = self.functionList.nvEncMapInputResource(self.context, &mapInputResource)
        raiseNVENC(r, "mapping input resource")
        cdef NV_ENC_INPUT_PTR mappedResource = mapInputResource.mappedResource
        if DEBUG_API:
            log("compress_image(..) device buffer mapped to %#x", <uintptr_t> mappedResource)
        return mappedResource

    cdef unmap_input_resource(self, NV_ENC_INPUT_PTR mappedResource):
        if DEBUG_API:
            log("nvEncUnmapInputResource(%#x)", <uintptr_t> mappedResource)
        cdef int r = self.functionList.nvEncUnmapInputResource(self.context, mappedResource)
        raiseNVENC(r, "unmapping input resource")

    cdef nvenc_compress(self, int input_size, NV_ENC_INPUT_PTR input, timestamp=0, full_range=True):
        cdef NV_ENC_PIC_PARAMS pic
        cdef NV_ENC_LOCK_BITSTREAM lockOutputBuffer
        assert input_size>0, "invalid input size %i" % input_size

        cdef double start = monotonic()
        if DEBUG_API:
            log("nvEncEncodePicture(%#x)", <uintptr_t> &pic)
        memset(&pic, 0, sizeof(NV_ENC_PIC_PARAMS))
        pic.version = NV_ENC_PIC_PARAMS_VER
        pic.bufferFmt = self.bufferFmt
        pic.pictureStruct = NV_ENC_PIC_STRUCT_FRAME
        pic.inputWidth = self.encoder_width
        pic.inputHeight = self.encoder_height
        pic.inputPitch = self.outputPitch
        pic.inputBuffer = input
        pic.outputBitstream = self.bitstreamBuffer
        #pic.pictureType: required when enablePTD is disabled
        if self.frames==0:
            #only the first frame needs to be IDR (as we never lose frames)
            pic.pictureType = NV_ENC_PIC_TYPE_IDR
            # pic.encodePicFlags = NV_ENC_PIC_FLAG_OUTPUT_SPSPPS
            pic.encodePicFlags = NV_ENC_PIC_FLAG_FORCEIDR
        else:
            pic.pictureType = NV_ENC_PIC_TYPE_P
            pic.encodePicFlags = 0
        if self.encoding=="h264":
            pic.codecPicParams.h264PicParams.displayPOCSyntax = 2*self.frames
            pic.codecPicParams.h264PicParams.refPicFlag = self.frames==0
        else:
            pic.codecPicParams.hevcPicParams.displayPOCSyntax = 2*self.frames
            pic.codecPicParams.hevcPicParams.refPicFlag = self.frames==0
        pic.frameIdx = self.frames
        if timestamp>0:
            if timestamp>=self.first_frame_timestamp:
                pic.inputTimeStamp = timestamp-self.first_frame_timestamp
            else:
                log.warn("Warning: image timestamp is older than the first frame")
                log.warn(" %s vs %s", timestamp, self.first_frame_timestamp)
        #inputDuration = 0      #FIXME: use frame delay?
        #cdef NV_ENC_RC_PARAMS *rc = &pic.rcParams
        #rc.rateControlMode = NV_ENC_PARAMS_RC_VBR     #FIXME: check NV_ENC_CAPS_SUPPORTED_RATECONTROL_MODES caps
        #rc.enableMinQP = 1
        #rc.enableMaxQP = 1
        #0=max quality, 63 lowest quality
        #qmin = QP_MAX_VALUE-min(QP_MAX_VALUE, int(QP_MAX_VALUE*(self.quality+20)/100))
        #qmax = QP_MAX_VALUE-max(0, int(QP_MAX_VALUE*(self.quality-20)/100))
        #rc.minQP.qpInterB = qmin
        #rc.minQP.qpInterP = qmin
        #rc.minQP.qpIntra = qmin
        #rc.maxQP.qpInterB = qmax
        #rc.maxQP.qpInterP = qmax
        #rc.maxQP.qpIntra = qmax
        #rc.averageBitRate = self.target_bitrate
        #rc.maxBitRate = self.max_bitrate
        cdef NVENCSTATUS r
        with nogil:
            r = self.functionList.nvEncEncodePicture(self.context, &pic)
        raiseNVENC(r, "error during picture encoding")

        memset(&lockOutputBuffer, 0, sizeof(NV_ENC_LOCK_BITSTREAM))
        #lock output buffer:
        lockOutputBuffer.version = NV_ENC_LOCK_BITSTREAM_VER
        lockOutputBuffer.doNotWait = 0
        lockOutputBuffer.outputBitstream = self.bitstreamBuffer
        if DEBUG_API:
            log("nvEncLockBitstream(%#x) bitstreamBuffer=%#x", <uintptr_t> &lockOutputBuffer, <uintptr_t> self.bitstreamBuffer)
        with nogil:
            r = self.functionList.nvEncLockBitstream(self.context, &lockOutputBuffer)
        raiseNVENC(r, "locking output buffer")
        assert lockOutputBuffer.bitstreamBufferPtr!=NULL
        #copy to python buffer:
        size = lockOutputBuffer.bitstreamSizeInBytes
        self.bytes_out += size
        data = (<char *> lockOutputBuffer.bitstreamBufferPtr)[:size]
        if DEBUG_API:
            log("nvEncUnlockBitstream(%#x)", <uintptr_t> self.bitstreamBuffer)
        r = self.functionList.nvEncUnlockBitstream(self.context, self.bitstreamBuffer)
        raiseNVENC(r, "unlocking output buffer")

        #update info:
        self.free_memory, self.total_memory = driver.mem_get_info()

        client_options = {
            "csc"       : CSC_ALIAS.get(self.pixel_format, self.pixel_format),
            "frame"     : int(self.frames),
            "pts"       : int(timestamp-self.first_frame_timestamp),
            "full-range" : full_range,
        }
        if self.kernel_name:
            client_options["csc-type"] = f"cuda:{self.kernel_name}"
        if pic.pictureType==NV_ENC_PIC_TYPE_IDR:
            client_options["type"] = "IDR"
        if self.lossless and not self.scaling:
            client_options["quality"] = 100
        else:
            client_options["quality"] = min(99, self.quality)   #ensure we cap it at 99 because this is lossy
        if self.scaling:
            client_options["scaled_size"] = self.encoder_width, self.encoder_height
            client_options["scaling-quality"] = "low"   #our dumb scaling kernels produce low quality output
        cdef double end = monotonic()
        self.frames += 1
        self.last_frame_times.append((start, end))
        cdef double elapsed = end-start
        self.time += elapsed
        #log("memory: %iMB free, %iMB total", self.free_memory//1024//1024, self.total_memory//1024//1024)
        log("compress_image(..) %5s %3s returning %9s bytes (%.1f%%) for %4s %s-frame no %6i took %3.1fms",
            get_type(), get_version(),
            size, 100.0*size/input_size, self.encoding, PIC_TYPES.get(pic.pictureType, pic.pictureType), self.frames, 1000.0*elapsed)
        return data, client_options


    cdef NV_ENC_PRESET_CONFIG *get_preset_config(self, name, GUID encode_GUID, GUID preset_GUID) except *:
        """ you must free it after use! """
        cdef NV_ENC_PRESET_CONFIG *presetConfig
        cdef NVENCSTATUS r
        assert self.context, "context is not initialized"
        presetConfig = <NV_ENC_PRESET_CONFIG*> cmalloc(sizeof(NV_ENC_PRESET_CONFIG), "preset config")
        memset(presetConfig, 0, sizeof(NV_ENC_PRESET_CONFIG))
        presetConfig.version = NV_ENC_PRESET_CONFIG_VER
        presetConfig.presetCfg.version = NV_ENC_CONFIG_VER
        if DEBUG_API:
            log("nvEncGetEncodePresetConfig(%s, %s)", codecstr(encode_GUID), presetstr(preset_GUID))
        cdef int tuning = self.get_tuning()
        log("tuning=%s (%i)", TUNING_STR.get(tuning, "unknown"), tuning)
        r = self.functionList.nvEncGetEncodePresetConfigEx(self.context, encode_GUID,
                                                           preset_GUID, <NV_ENC_TUNING_INFO> tuning, presetConfig)
        if r!=0:
            log.warn("failed to get preset config for %s (%s / %s): %s", name, guidstr(encode_GUID), guidstr(preset_GUID), NV_ENC_STATUS_TXT.get(r, r))
            return NULL
        return presetConfig

    cdef int get_tuning(self):
        if DESIRED_TUNING:
            tuning = TUNINGS.get(DESIRED_TUNING, -1)
            log(f"tuning override {DESIRED_TUNING!r}={tuning}")
            if tuning>=0:
                return tuning
        if self.lossless:
            return NV_ENC_TUNING_INFO_LOSSLESS
        if self.speed>80:
            return NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY
        if self.speed>=50:
            return NV_ENC_TUNING_INFO_LOW_LATENCY
        return NV_ENC_TUNING_INFO_HIGH_QUALITY

    cdef object query_presets(self, GUID encode_GUID):
        cdef uint32_t presetCount
        cdef uint32_t presetsRetCount
        cdef GUID* preset_GUIDs
        cdef GUID preset_GUID
        cdef NV_ENC_PRESET_CONFIG *presetConfig
        cdef NV_ENC_CONFIG *encConfig
        cdef NVENCSTATUS r
        assert self.context, "context is not initialized"
        presets = {}
        if DEBUG_API:
            log("nvEncGetEncodePresetCount(%s, %#x)", codecstr(encode_GUID), <uintptr_t> &presetCount)
        with nogil:
            r = self.functionList.nvEncGetEncodePresetCount(self.context, encode_GUID, &presetCount)
        raiseNVENC(r, "getting preset count for %s" % guidstr(encode_GUID))
        log(f"found {presetCount} presets:")
        assert presetCount<2**8
        preset_GUIDs = <GUID*> cmalloc(sizeof(GUID) * presetCount, "preset GUIDs")
        try:
            if DEBUG_API:
                log("nvEncGetEncodePresetGUIDs(%s, %#x)", codecstr(encode_GUID), <uintptr_t> &presetCount)
            with nogil:
                r = self.functionList.nvEncGetEncodePresetGUIDs(self.context, encode_GUID, preset_GUIDs, presetCount, &presetsRetCount)
            raiseNVENC(r, "getting encode presets")
            assert presetsRetCount==presetCount
            unknowns = []
            for x in range(presetCount):
                preset_GUID = preset_GUIDs[x]
                preset_str = guidstr(preset_GUID)
                preset_name = CODEC_PRESETS_GUIDS.get(preset_str)
                if DEBUG_API:
                    log("* %s : %s", guidstr(preset_GUID), preset_name or "unknown!")
                if preset_name is None:
                    global UNKNOWN_PRESETS
                    if preset_str not in UNKNOWN_PRESETS:
                        UNKNOWN_PRESETS.append(preset_str)
                        unknowns.append(preset_str)
                else:
                    presetConfig = self.get_preset_config(preset_name, encode_GUID, preset_GUID)
                    if presetConfig!=NULL:
                        try:
                            encConfig = &presetConfig.presetCfg
                            if DEBUG_API:
                                log("presetConfig.presetCfg=%s", <uintptr_t> encConfig)
                            gop = {NVENC_INFINITE_GOPLENGTH : "infinite"}.get(encConfig.gopLength, encConfig.gopLength)
                            log("* %-20s P frame interval=%i, gop length=%-10s", preset_name or "unknown!", encConfig.frameIntervalP, gop)
                        finally:
                            free(presetConfig)
                    presets[preset_name] = preset_str
            if len(unknowns)>0:
                log.warn("Warning: found some unknown NVENC presets:")
                for x in unknowns:
                    log.warn(" * %s", x)
        finally:
            free(preset_GUIDs)
        if DEBUG_API:
            log("query_presets(%s)=%s", codecstr(encode_GUID), presets)
        return presets

    cdef object query_profiles(self, GUID encode_GUID):
        cdef uint32_t profileCount
        cdef uint32_t profilesRetCount
        cdef GUID profile_GUID
        assert self.context, "context is not initialized"
        profiles = {}
        if DEBUG_API:
            log("nvEncGetEncodeProfileGUIDCount(%s, %#x)", codecstr(encode_GUID), <uintptr_t> &profileCount)
        cdef NVENCSTATUS r
        with nogil:
            r = self.functionList.nvEncGetEncodeProfileGUIDCount(self.context, encode_GUID, &profileCount)
        raiseNVENC(r, "getting profile count")
        log("%s profiles:", profileCount)
        assert profileCount<2**8
        cdef GUID* profile_GUIDs = <GUID*> cmalloc(sizeof(GUID) * profileCount, "profile GUIDs")
        PROFILES_GUIDS = CODEC_PROFILES_GUIDS.get(guidstr(encode_GUID), {})
        try:
            if DEBUG_API:
                log("nvEncGetEncodeProfileGUIDs(%s, %#x, %#x)", codecstr(encode_GUID), <uintptr_t> profile_GUIDs, <uintptr_t> &profileCount)
            with nogil:
                r = self.functionList.nvEncGetEncodeProfileGUIDs(self.context, encode_GUID, profile_GUIDs, profileCount, &profilesRetCount)
            raiseNVENC(r, "getting encode profiles")
            #(void* encoder, GUID encodeGUID, GUID* profileGUIDs, uint32_t guidArraySize, uint32_t* GUIDCount)
            assert profilesRetCount==profileCount
            for x in range(profileCount):
                profile_GUID = profile_GUIDs[x]
                profile_name = PROFILES_GUIDS.get(guidstr(profile_GUID))
                log("* %s : %s", guidstr(profile_GUID), profile_name)
                profiles[profile_name] = guidstr(profile_GUID)
        finally:
            free(profile_GUIDs)
        return profiles

    cdef object query_input_formats(self, GUID encode_GUID):
        cdef uint32_t inputFmtCount
        cdef uint32_t inputFmtsRetCount
        cdef NV_ENC_BUFFER_FORMAT inputFmt
        assert self.context, "context is not initialized"
        input_formats = {}
        if DEBUG_API:
            log("nvEncGetInputFormatCount(%s, %#x)", codecstr(encode_GUID), <uintptr_t> &inputFmtCount)
        cdef NVENCSTATUS r
        with nogil:
            r = self.functionList.nvEncGetInputFormatCount(self.context, encode_GUID, &inputFmtCount)
        raiseNVENC(r, "getting input format count")
        log(f"{inputFmtCount} input format types:")
        assert inputFmtCount>0 and inputFmtCount<2**8
        cdef NV_ENC_BUFFER_FORMAT* inputFmts = <NV_ENC_BUFFER_FORMAT*> cmalloc(sizeof(int) * inputFmtCount, "input formats")
        try:
            if DEBUG_API:
                log("nvEncGetInputFormats(%s, %#x, %i, %#x)", codecstr(encode_GUID), <uintptr_t> inputFmts, inputFmtCount, <uintptr_t> &inputFmtsRetCount)
            with nogil:
                r = self.functionList.nvEncGetInputFormats(self.context, encode_GUID, inputFmts, inputFmtCount, &inputFmtsRetCount)
            raiseNVENC(r, "getting input formats")
            assert inputFmtsRetCount==inputFmtCount
            for x in range(inputFmtCount):
                inputFmt = inputFmts[x]
                for format_mask in sorted(BUFFER_FORMAT.keys()):
                    if format_mask>0 and (format_mask & inputFmt)>0:
                        format_name = BUFFER_FORMAT.get(format_mask)
                        log("  %#10x : %s", format_mask, format_name)
                        input_formats[format_name] = hex(format_mask)
        finally:
            free(inputFmts)
        return input_formats

    cdef int query_encoder_caps(self, GUID encode_GUID, NV_ENC_CAPS caps_type) except *:
        cdef int val
        cdef NV_ENC_CAPS_PARAM encCaps
        cdef NVENCSTATUS r
        assert self.context, "context is not initialized"
        memset(&encCaps, 0, sizeof(NV_ENC_CAPS_PARAM))
        encCaps.version = NV_ENC_CAPS_PARAM_VER
        encCaps.capsToQuery = caps_type
        with nogil:
            r = self.functionList.nvEncGetEncodeCaps(self.context, encode_GUID, &encCaps, &val)
        raiseNVENC(r, "getting encode caps for %s" % CAPS_NAMES.get(caps_type, caps_type))
        if DEBUG_API:
            log("query_encoder_caps(%s, %s) %s=%s", codecstr(encode_GUID), caps_type, CAPS_NAMES.get(caps_type, caps_type), val)
        return val

    def query_codecs(self, full_query=False) -> Dict[str, Dict]:
        cdef uint32_t GUIDCount
        cdef uint32_t GUIDRetCount
        cdef GUID* encode_GUIDs
        cdef GUID encode_GUID
        cdef NVENCSTATUS r
        assert self.context, "context is not initialized"
        if DEBUG_API:
            log("nvEncGetEncodeGUIDCount(%#x, %#x)", <uintptr_t> self.context, <uintptr_t> &GUIDCount)
        with nogil:
            r = self.functionList.nvEncGetEncodeGUIDCount(self.context, &GUIDCount)
        raiseNVENC(r, "getting encoder count")
        log(f"found {GUIDCount} encoders:")
        assert GUIDCount<2**8
        encode_GUIDs = <GUID*> cmalloc(sizeof(GUID) * GUIDCount, "encode GUIDs")
        codecs = {}
        try:
            if DEBUG_API:
                log("nvEncGetEncodeGUIDs(%#x, %i, %#x)", <uintptr_t> encode_GUIDs, GUIDCount, <uintptr_t> &GUIDRetCount)
            with nogil:
                r = self.functionList.nvEncGetEncodeGUIDs(self.context, encode_GUIDs, GUIDCount, &GUIDRetCount)
            raiseNVENC(r, "getting list of encode GUIDs")
            assert GUIDRetCount==GUIDCount, "expected %s items but got %s" % (GUIDCount, GUIDRetCount)
            for x in range(GUIDRetCount):
                encode_GUID = encode_GUIDs[x]
                codec_name = CODEC_GUIDS.get(guidstr(encode_GUID))
                if not codec_name:
                    log("[%s] unknown codec GUID: %s", x, guidstr(encode_GUID))
                else:
                    log("[%s] %s", x, codec_name)

                maxw = self.query_encoder_caps(encode_GUID, NV_ENC_CAPS_WIDTH_MAX)
                maxh = self.query_encoder_caps(encode_GUID, NV_ENC_CAPS_HEIGHT_MAX)
                async = self.query_encoder_caps(encode_GUID, NV_ENC_CAPS_ASYNC_ENCODE_SUPPORT)
                rate_control = self.query_encoder_caps(encode_GUID, NV_ENC_CAPS_SUPPORTED_RATECONTROL_MODES)
                codec = {
                         "guid"         : guidstr(encode_GUID),
                         "name"         : codec_name,
                         "max-size"     : (maxw, maxh),
                         "async"        : async,
                         "rate-control" : rate_control
                         }
                if full_query:
                    presets = self.query_presets(encode_GUID)
                    profiles = self.query_profiles(encode_GUID)
                    input_formats = self.query_input_formats(encode_GUID)
                    codec |= {
                        "presets"         : presets,
                        "profiles"        : profiles,
                        "input-formats"   : input_formats,
                    }
                codecs[codec_name] = codec
        finally:
            free(encode_GUIDs)
        log("codecs=%s", csv(codecs.keys()))
        return codecs

    def open_encode_session(self) -> None:
        global context_counter, context_gen_counter, last_context_failure
        cdef NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS params

        assert self.functionList is NULL, "session already active"
        assert self.context is NULL, "context already set"
        assert self.cuda_context_ptr!=NULL, "cuda context is not set"
        #params = <NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS*> malloc(sizeof(NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS))
        log("open_encode_session() cuda_context=%s, cuda_context_ptr=%#x", self.cuda_device_context, <uintptr_t> self.cuda_context_ptr)

        self.functionList = <NV_ENCODE_API_FUNCTION_LIST*> cmalloc(sizeof(NV_ENCODE_API_FUNCTION_LIST), "function list")
        assert memset(self.functionList, 0, sizeof(NV_ENCODE_API_FUNCTION_LIST))!=NULL
        log("open_encode_session() functionList=%#x", <uintptr_t> self.functionList)

        #get NVENC function pointers:
        memset(self.functionList, 0, sizeof(NV_ENCODE_API_FUNCTION_LIST))
        self.functionList.version = NV_ENCODE_API_FUNCTION_LIST_VER
        if DEBUG_API:
            log("NvEncodeAPICreateInstance(%#x)", <uintptr_t> self.functionList)
        cdef NVENCSTATUS r = NvEncodeAPICreateInstance(<uintptr_t> self.functionList)
        raiseNVENC(r, "getting API function list")
        assert self.functionList.nvEncOpenEncodeSessionEx!=NULL, "looks like NvEncodeAPICreateInstance failed!"

        #NVENC init:
        memset(&params, 0, sizeof(NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS))
        params.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER
        params.deviceType = NV_ENC_DEVICE_TYPE_CUDA
        params.device = self.cuda_context_ptr
        params.reserved = &CLIENT_KEY_GUID
        params.apiVersion = NVENCAPI_VERSION
        if DEBUG_API:
            cstr = <unsigned char*> &params
            pstr = cstr[:sizeof(NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS)]
            log("calling nvEncOpenEncodeSessionEx @ %#x, NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS=%s", <uintptr_t> self.functionList.nvEncOpenEncodeSessionEx, pstr)
        self.context = NULL
        with nogil:
            r = self.functionList.nvEncOpenEncodeSessionEx(&params, &self.context)
        if DEBUG_API:
            log("nvEncOpenEncodeSessionEx(..)=%s", r)
        if r in OPEN_TRANSIENT_ERROR:
            last_context_failure = monotonic()
            msg = "could not open encode session: %s" % (nvencStatusInfo(r) or r)
            log(msg)
            raise TransientCodecException(msg)
        if self.context==NULL:
            if r!=0:
                msg = nvencStatusInfo(r) or str(r)
            else:
                msg = "context is NULL"
            last_context_failure = monotonic()
            raise RuntimeError("cannot open encoding session: %s, %i contexts are in use" % (msg, context_counter.get()))
        raiseNVENC(r, "opening session")
        context_counter.increase()
        context_gen_counter.increase()
        log(f"success, encoder context=%#x ({context_counter} contexts in use)", <uintptr_t> self.context)


_init_message = False
def init_module() -> None:
    from xpra.codecs.nvidia.util import has_nvidia_hardware
    if has_nvidia_hardware() is False:
        raise ImportError("no nvidia GPU device found")
    log("nvenc.init_module()")
    min_version = 10
    if NVENCAPI_MAJOR_VERSION < min_version:
        raise RuntimeError("unsupported version of NVENC: %i, minimum version is %i" % (NVENCAPI_VERSION, min_version))
    log("NVENC encoder API version %s", ".".join([str(x) for x in PRETTY_VERSION]))

    cdef Encoder test_encoder
    #cdef uint32_t max_version
    #cdef NVENCSTATUS r = NvEncodeAPIGetMaxSupportedVersion(&max_version)
    #raiseNVENC(r, "querying max version")
    #log(" maximum supported version: %s", max_version)

    #load the library / DLL:
    init_nvencode_library()

    #make sure we have devices we can use:
    devices = init_all_devices()
    if len(devices)==0:
        log("nvenc: no compatible devices found")
        return

    success = False
    valid_keys = []
    failed_keys = []
    try_keys = CLIENT_KEYS_STR or [None]
    FAILED_ENCODINGS = set()
    global YUV444_ENABLED, YUV444_CODEC_SUPPORT, LOSSLESS_ENABLED, ENCODINGS, MAX_SIZE
    if not validate_driver_yuv444lossless():
        if YUV444_ENABLED:
            YUV444_ENABLED = False
        if LOSSLESS_ENABLED:
            LOSSLESS_ENABLED = False
    #check NVENC availability by creating a context:
    device_warnings = {}
    log("init_module() will try keys: %s", try_keys)
    for client_key in try_keys:
        if client_key:
            #this will set the global key object used by all encoder contexts:
            log("init_module() testing with key '%s'", client_key)
            global CLIENT_KEY_GUID
            CLIENT_KEY_GUID = c_parseguid(client_key)

        for device_id in tuple(devices):
            log("testing encoder with device %s", device_id)
            device = load_device(device_id)
            cdc = cuda_device_context(device_id, device)
            with cdc as device_context:
                options = typedict({
                    "cuda_device"   : device_id,
                    "cuda-device-context" : cdc,
                    "threaded-init" : False,
                    })
                try:
                    test_encoder = Encoder()
                    test_encoder.init_cuda(device_context)
                    log("test encoder=%s", test_encoder)
                    test_encoder.open_encode_session()
                    log("init_encoder() %s", test_encoder)
                    codecs = test_encoder.query_codecs()
                    log("device %i supports: %s", device_id, codecs)
                except Exception as e:
                    log("failed to test encoder with %s", cdc, exc_info=True)
                    log.warn(" device %s is not supported: %s", get_device_name(device_id) or device_id, e)
                    devices.remove(device_id)
                    continue
                finally:
                    test_encoder.clean()
                    test_encoder = None

                test_encodings = []
                for e in TEST_ENCODINGS:
                    if e in FAILED_ENCODINGS:
                        continue
                    nvenc_encoding_name = {
                                           "h264"   : "H264",
                                           "h265"   : "HEVC",
                                           }.get(e, e)
                    codec_query = codecs.get(nvenc_encoding_name)
                    if not codec_query:
                        wkey = "nvenc:%s-%s" % (device_id, nvenc_encoding_name)
                        if first_time(wkey):
                            log.warn("Warning: NVENC on device %s:", get_device_name(device_id) or device_id)
                            log.warn(" does not support %s", nvenc_encoding_name)
                        FAILED_ENCODINGS.add(e)
                        continue
                    #ensure MAX_SIZE is set:
                    cmax = MAX_SIZE.get(e)
                    qmax = codec_query.get("max-size")
                    if qmax:
                        #minimum of current value and value for this device:
                        qmx, qmy = qmax
                        cmx, cmy = cmax or qmax
                        v = min(qmx, cmx), min(qmy, cmy)
                        log("max-size(%s)=%s", e, v)
                        MAX_SIZE[e] = v
                    test_encodings.append(e)

                log("will test: %s", test_encodings)
                for encoding in test_encodings:
                    colorspaces = get_input_colorspaces(encoding)
                    if not colorspaces:
                        raise ValueError(f"cannot use NVENC: no colorspaces available for {encoding}")
                    src_format = colorspaces[0]
                    log(f"testing {encoding} using {src_format} from {colorspaces}")
                    options["dst-formats"] = get_output_colorspaces(encoding, src_format)
                    test_encoder = None
                    try:
                        test_encoder = Encoder()
                        test_encoder.init_context(encoding, 1920, 1080, src_format, options)
                        success = True
                        if client_key:
                            log("the license key '%s' is valid", client_key)
                            valid_keys.append(client_key)
                        #check for YUV444 support
                        yuv444_support = YUV444_ENABLED and test_encoder.query_encoder_caps(test_encoder.get_codec(), <NV_ENC_CAPS> NV_ENC_CAPS_SUPPORT_YUV444_ENCODE)
                        YUV444_CODEC_SUPPORT[encoding] = bool(yuv444_support)
                        if YUV444_ENABLED and not yuv444_support:
                            wkey = "nvenc:%s-%s-%s" % (device_id, encoding, "YUV444")
                            if first_time(wkey):
                                device_warnings.setdefault(device_id, {}).setdefault(encoding, []).append("YUV444")
                            log("no support for YUV444 with %s", encoding)
                        log("%s YUV444 support: %s", encoding, YUV444_CODEC_SUPPORT.get(encoding, YUV444_ENABLED))
                        #check for lossless:
                        lossless_support = yuv444_support and LOSSLESS_ENABLED and test_encoder.query_encoder_caps(test_encoder.get_codec(), <NV_ENC_CAPS> NV_ENC_CAPS_SUPPORT_LOSSLESS_ENCODE)
                        LOSSLESS_CODEC_SUPPORT[encoding] = lossless_support
                        if LOSSLESS_ENABLED and not lossless_support:
                            wkey = "nvenc:%s-%s-%s" % (device_id, encoding, "lossless")
                            if first_time(wkey):
                                device_warnings.setdefault(device_id, {}).setdefault(encoding, []).append("lossless")
                            log("no support for lossless mode with %s", encoding)
                        log("%s lossless support: %s", encoding, LOSSLESS_CODEC_SUPPORT.get(encoding, LOSSLESS_ENABLED))
                        # check intra refresh:
                        intra = test_encoder.query_encoder_caps(test_encoder.get_codec(), <NV_ENC_CAPS> NV_ENC_CAPS_SUPPORT_INTRA_REFRESH)
                        log("%s intra refresh: %s", encoding, intra)
                    except NVENCException as e:
                        log("encoder %s failed: %s", test_encoder, e)
                        #special handling for license key issues:
                        if e.code==NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY:
                            if client_key:
                                log("invalid license key '%s' (skipped)", client_key)
                                failed_keys.append(client_key)
                            else:
                                log("a license key is required")
                        elif e.code==NV_ENC_ERR_INVALID_VERSION:
                            #we can bail out already:
                            raise RuntimeError("version mismatch, you need a newer/older codec build or newer/older drivers")
                        else:
                            #it seems that newer version will fail with
                            #seemingly random errors when we supply the wrong key
                            log.warn("error during NVENC encoder test: %s", e)
                            if client_key:
                                log(" license key '%s' may not be valid (skipped)", client_key)
                                failed_keys.append(client_key)
                            else:
                                log(" a license key may be required")
                    finally:
                        if test_encoder:
                            test_encoder.clean()
    if device_warnings:
        for device_id, encoding_warnings in device_warnings.items():
            log.info("NVENC on device %s:", get_device_name(device_id) or device_id)
            for encoding, warnings in encoding_warnings.items():
                log.info(f" {encoding} encoding does not support %s mode", " or ".join(warnings))
    if not devices:
        ENCODINGS[:] = []
        log.warn("no valid NVENC devices found")
        return
    if success:
        #pick the first valid license key:
        if len(valid_keys)>0:
            x = valid_keys[0]
            log("using the license key '%s'", x)
            CLIENT_KEY_GUID = c_parseguid(x)
        else:
            log("no license keys are required")
        ENCODINGS[:] = [x for x in TEST_ENCODINGS if x not in FAILED_ENCODINGS]
    else:
        #we got license key error(s)
        if len(failed_keys)>0:
            raise ValueError("the license %s specified may be invalid" % (["key", "keys"][len(failed_keys)>1]))
        else:
            raise RuntimeError("you may need to provide a license key")
    global _init_message
    if ENCODINGS and not _init_message:
        log.info("NVENC v%i successfully initialized with codecs: %s", NVENCAPI_MAJOR_VERSION, csv(ENCODINGS))
        _init_message = True


def cleanup_module() -> None:
    log("nvenc.cleanup_module()")
    reset_state()


def selftest(full=False) -> None:
    from xpra.codecs.nvidia.util import has_nvidia_hardware
    if not has_nvidia_hardware():
        raise ImportError("no nvidia GPU device found")
    v = get_nvidia_module_version(True)
    assert NVENCAPI_MAJOR_VERSION>=9, "unsupported NVENC version %i" % NVENCAPI_MAJOR_VERSION
    if v:
        NVENC_UNSUPPORTED_DRIVER_VERSION = envbool("XPRA_NVENC_UNSUPPORTED_DRIVER_VERSION", False)
        if v<(400, 0):
            if not NVENC_UNSUPPORTED_DRIVER_VERSION:
                raise ImportError("unsupported NVidia driver version %s\nuse XPRA_NVENC_UNSUPPORTED_DRIVER_VERSION=1 to force enable it" % pver(v))
    #this is expensive, so don't run it unless "full" is set:
    if full:
        from xpra.codecs.checks import get_encoder_max_sizes
        from xpra.codecs.nvidia.nvenc import encoder
        init_module()
        log.info("%s max dimensions: %s", encoder, get_encoder_max_sizes(encoder))
