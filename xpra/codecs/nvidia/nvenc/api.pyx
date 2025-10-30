# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
from typing import Dict

from libc.stdint cimport uint8_t   # pylint: disable=syntax-error


cdef str guidstr(GUID guid):
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


cdef GUID parseguid(src) except *:
    #just as ugly as above - shoot me now
    #only this format is allowed:
    sample_guid = b"CE788D20-AAA9-4318-92BB-AC7E858C8D36"
    bsrc = src.upper().encode("latin1")
    if len(bsrc)!=len(sample_guid):
        raise ValueError("invalid GUID format: expected %s characters but got %s" % (len(sample_guid), len(src)))
    cdef int i
    #validate the input bytestring:
    hexords = []
    for c in "0123456789ABCDEF":
        hexords.append(ord(c))
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
        #log("parseguid bytes(%s)=%r", part, binv)
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
    return guid


cdef str presetstr(GUID preset):
    s = guidstr(preset)
    return CODEC_PRESETS_GUIDS.get(s, s)


NV_ENC_STATUS_TXT: Dict[NVENCSTATUS, str] = {
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


cdef str nvencStatusInfo(NVENCSTATUS ret):
    return NV_ENC_STATUS_TXT.get(ret, str(ret))


CODEC_PROFILES_GUIDS: dict[str, dict[str, str]] = {
    guidstr(NV_ENC_CODEC_H264_GUID): {
        guidstr(NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID)       : "auto",
        guidstr(NV_ENC_H264_PROFILE_BASELINE_GUID)          : "baseline",
        guidstr(NV_ENC_H264_PROFILE_MAIN_GUID)              : "main",
        guidstr(NV_ENC_H264_PROFILE_HIGH_GUID)              : "high",
        guidstr(NV_ENC_H264_PROFILE_HIGH_10_GUID)           : "high10",
        guidstr(NV_ENC_H264_PROFILE_HIGH_422_GUID)          : "high422",
        guidstr(NV_ENC_H264_PROFILE_STEREO_GUID)            : "stereo",
        #guidstr(NV_ENC_H264_PROFILE_SVC_TEMPORAL_SCALABILTY): "temporal",
        guidstr(NV_ENC_H264_PROFILE_PROGRESSIVE_HIGH_GUID)  : "progressive-high",
        guidstr(NV_ENC_H264_PROFILE_CONSTRAINED_HIGH_GUID)  : "constrained-high",
        #new in SDK v4:
        guidstr(NV_ENC_H264_PROFILE_HIGH_444_GUID)          : "high-444",
    },
    guidstr(NV_ENC_CODEC_HEVC_GUID): {
        guidstr(NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID)       : "auto",
        guidstr(NV_ENC_HEVC_PROFILE_MAIN_GUID)              : "main",
        guidstr(NV_ENC_HEVC_PROFILE_MAIN10_GUID)            : "main10",
        guidstr(NV_ENC_HEVC_PROFILE_FREXT_GUID)             : "frext",
    },
    guidstr(NV_ENC_CODEC_AV1_GUID): {
        guidstr(NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID)       : "auto",
        guidstr(NV_ENC_AV1_PROFILE_MAIN_GUID)               : "main",
    }
}


PROFILE_STR = {}
for codec_guid, profiles in CODEC_PROFILES_GUIDS.items():
    for profile_guid, profile_name in profiles.items():
        PROFILE_STR[profile_guid] = profile_name


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
    NV_ENC_CAPS_WIDTH_MIN                   : "WIDTH_MIN",
    NV_ENC_CAPS_HEIGHT_MIN                  : "HEIGHT_MIN",
    NV_ENC_CAPS_SUPPORT_MULTIPLE_REF_FRAMES : "SUPPORT_MULTIPLE_REF_FRAMES",
    NV_ENC_CAPS_SUPPORT_ALPHA_LAYER_ENCODING : "SUPPORT_ALPHA_LAYER_ENCODING",
    NV_ENC_CAPS_NUM_ENCODER_ENGINES         : "NUM_ENCODER_ENGINES",
    NV_ENC_CAPS_SINGLE_SLICE_INTRA_REFRESH  : "SINGLE_SLICE_INTRA_REFRESH",
    NV_ENC_CAPS_DISABLE_ENC_STATE_ADVANCE   : "DISABLE_ENC_STATE_ADVANCE",
    NV_ENC_CAPS_OUTPUT_RECON_SURFACE        : "OUTPUT_RECON_SURFACE",
    NV_ENC_CAPS_OUTPUT_BLOCK_STATS          : "OUTPUT_BLOCK_STATS",
    NV_ENC_CAPS_OUTPUT_ROW_STATS            : "OUTPUT_ROW_STATS",
    NV_ENC_CAPS_SUPPORT_TEMPORAL_FILTER     : "SUPPORT_TEMPORAL_FILTER",
    NV_ENC_CAPS_SUPPORT_LOOKAHEAD_LEVEL     : "SUPPORT_LOOKAHEAD_LEVEL",
    NV_ENC_CAPS_SUPPORT_UNIDIRECTIONAL_B    : "SUPPORT_UNIDIRECTIONAL_B",
    NV_ENC_CAPS_SUPPORT_MVHEVC_ENCODE       : "SUPPORT_MVHEVC_ENCODE",
    NV_ENC_CAPS_SUPPORT_YUV422_ENCODE       : "SUPPORT_YUV422_ENCODE",
}


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


TUNING_STR: Dict[int, str] = {
    NV_ENC_TUNING_INFO_UNDEFINED            : "undefined",
    NV_ENC_TUNING_INFO_HIGH_QUALITY         : "high-quality",
    NV_ENC_TUNING_INFO_LOW_LATENCY          : "low-latency",
    NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY    : "ultra-low-latency",
    NV_ENC_TUNING_INFO_LOSSLESS             : "lossless",
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
    NV_ENC_BUFFER_FORMAT_U8                     : "U8",
    NV_ENC_BUFFER_FORMAT_NV16                   : "NV12",
    NV_ENC_BUFFER_FORMAT_P210                   : "P210",
}


CHROMA_FORMATS: Dict[str, int] = {
    "BGRX" : 3,
    "r210" : 3,
    "NV12" : 1,
    "YUV444P" : 3,
}


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


PIC_TYPES: Dict[int, str] = {
    NV_ENC_PIC_TYPE_P              : "P",
    NV_ENC_PIC_TYPE_B              : "B",
    NV_ENC_PIC_TYPE_I              : "I",
    NV_ENC_PIC_TYPE_IDR            : "IDR",
    NV_ENC_PIC_TYPE_BI             : "BI",
    NV_ENC_PIC_TYPE_SKIPPED        : "SKIPPED",
    NV_ENC_PIC_TYPE_INTRA_REFRESH  : "INTRA_REFRESH",
    NV_ENC_PIC_TYPE_NONREF_P       : "NONREF_P",
    NV_ENC_PIC_TYPE_SWITCH         : "SWITCH",
    NV_ENC_PIC_TYPE_UNKNOWN        : "UNKNOWN",
}


cdef dict get_profile_guids(object encode):
    return CODEC_PROFILES_GUIDS.get(encode, {})


cdef str get_profile_name(profile_guid):
    return PROFILE_STR.get(profile_guid, "")


cdef uint8_t is_transient_error(NVENCSTATUS r):
    return int(r in OPEN_TRANSIENT_ERROR)


cdef str get_caps_name(NV_ENC_CAPS cap):
    return CAPS_NAMES.get(cap) or str(cap)


cdef List[int] get_all_caps():
    return list(CAPS_NAMES.keys())


cdef str get_preset_name(object preset):
    return CODEC_PRESETS_GUIDS.get(preset, "")


cdef str get_tuning_name(NV_ENC_TUNING_INFO tuning):
    return TUNING_STR.get(tuning, "")


cdef NV_ENC_TUNING_INFO get_tuning_value(object name):
    cdef NV_ENC_TUNING_INFO tuning = NV_ENC_TUNING_INFO_UNDEFINED
    for k, v in TUNING_STR.items():
        if name == v:
            tuning = k
    return tuning


cdef List[int] get_buffer_formats():
    return list(BUFFER_FORMAT.keys())


cdef str get_buffer_format_name(object buffer_format):
    return BUFFER_FORMAT.get(buffer_format, "")


cdef int get_chroma_format(object pixel_format):
    return CHROMA_FORMATS.get(pixel_format, -1)


cdef int get_preset_speed(object preset, int default):
    return PRESET_SPEED.get(preset, default)


cdef int get_preset_quality(object preset, int default):
    return PRESET_QUALITY.get(preset, default)


cdef str get_picture_type(NV_ENC_PIC_TYPE ptype):
    return PIC_TYPES.get(ptype, "invalid")


def test_parse() -> None:
    sample_guid = "CE788D20-AAA9-4318-92BB-AC7E858C8D36"
    x = parseguid(sample_guid)
    v = guidstr(x)
    assert v==sample_guid, "expected %s but got %s" % (sample_guid, v)


test_parse()
