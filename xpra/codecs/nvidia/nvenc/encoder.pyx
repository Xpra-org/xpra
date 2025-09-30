# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import platform
from collections import deque
from time import monotonic
from typing import Any, Dict, Tuple, List
from threading import Lock
from collections.abc import Sequence

from xpra.os_util import WIN32, LINUX
from xpra.util.thread import start_thread
from xpra.util.objects import AtomicInteger, typedict
from xpra.util.str_fn import csv, pver
from xpra.util.env import envint, envbool, first_time
from xpra.codecs.nvidia.cuda.context import (
    init_all_devices, free_default_device_context,
    get_devices, get_device_name,
    get_cuda_info, get_pycuda_info, reset_state,
    get_CUDA_function, record_device_failure, record_device_success,
    cuda_device_context, load_device,
)
from xpra.codecs.constants import VideoSpec, TransientCodecException, CSC_ALIAS
from xpra.codecs.image import ImageWrapper
from xpra.codecs.nvidia.util import get_nvidia_module_version, get_license_keys, get_cards
from xpra.log import Logger
log = Logger("encoder", "nvenc")

# we can import pycuda safely here,
# because importing cuda/context will have imported it with the lock
from pycuda import driver  # @UnresolvedImport
import numpy

from libc.stdint cimport uintptr_t, uint8_t, uint16_t, uint32_t, uint64_t   # pylint: disable=syntax-error
from libc.stdlib cimport free, malloc
from libc.string cimport memset, memcpy

from xpra.codecs.nvidia.nvenc.nvencode cimport init_nvencode_library, create_nvencode_instance, get_current_cuda_context

from xpra.codecs.nvidia.nvenc.api cimport (
    MIN, MAX, nvencStatusInfo, guidstr, parseguid, presetstr,
    GUID,
    get_profile_guids, get_profile_name, is_transient_error,
    get_all_caps, get_caps_name,
    get_preset_name, get_tuning_name, get_tuning_value,
    get_buffer_formats, get_buffer_format_name, get_chroma_format,
    get_preset_speed, get_preset_quality, get_picture_type,

    NV_ENC_PIC_FLAG_EOS, NV_ENC_PIC_FLAG_FORCEIDR, NV_ENC_PIC_FLAG_OUTPUT_SPSPPS,
    NV_ENCODE_API_FUNCTION_LIST,
    NV_ENC_INITIALIZE_PARAMS, NV_ENC_INITIALIZE_PARAMS_VER,
    NV_ENC_REGISTERED_PTR,
    NV_ENC_BUFFER_FORMAT, NV_ENC_BUFFER_FORMAT_UNDEFINED,
    NV_ENC_CONFIG, NV_ENC_CONFIG_VER,
    NV_ENC_RC_PARAMS,
    NV_ENC_CODEC_H264_GUID, NV_ENC_CONFIG_H264, NV_ENC_CONFIG_H264_VUI_PARAMETERS,
    NV_ENC_CODEC_HEVC_GUID, NV_ENC_CONFIG_HEVC, NV_ENC_CONFIG_HEVC_VUI_PARAMETERS,
    NV_ENC_CODEC_AV1_GUID, NV_ENC_CONFIG_AV1,
    NV_ENC_INPUT_PTR,
    NV_ENC_PRESET_CONFIG, NV_ENC_PRESET_CONFIG_VER,
    NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID,
    NV_ENC_REGISTER_RESOURCE, NV_ENC_REGISTER_RESOURCE_VER,
    NV_ENC_INPUT_RESOURCE_TYPE_CUDADEVICEPTR,
    NV_ENC_MAP_INPUT_RESOURCE, NV_ENC_MAP_INPUT_RESOURCE_VER,
    NV_ENC_CREATE_BITSTREAM_BUFFER, NV_ENC_CREATE_BITSTREAM_BUFFER_VER, NV_ENC_MEMORY_HEAP_SYSMEM_CACHED,
    NVENCSTATUS,
    NV_ENC_PIC_PARAMS, NV_ENC_PIC_PARAMS_VER, NV_ENC_PIC_STRUCT_FRAME,
    NV_ENC_PIC_TYPE_IDR, NV_ENC_PIC_TYPE_P,
    NV_ENC_LOCK_BITSTREAM, NV_ENC_LOCK_BITSTREAM_VER,
    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS, NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER,
    NVENCAPI_VERSION, NVENCAPI_MAJOR_VERSION, NVENCAPI_MINOR_VERSION,
    NV_ENC_TUNING_INFO,
    NV_ENC_TUNING_INFO_LOSSLESS, NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY, NV_ENC_TUNING_INFO_LOW_LATENCY,
    NV_ENC_TUNING_INFO_HIGH_QUALITY,
    NV_ENC_DEVICE_TYPE_CUDA,
    NV_ENC_ERR_INVALID_PARAM, NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY, NV_ENC_ERR_INVALID_VERSION,
    NV_ENC_BUFFER_FORMAT_ARGB, NV_ENC_BUFFER_FORMAT_ARGB10, NV_ENC_BUFFER_FORMAT_YUV444, NV_ENC_BUFFER_FORMAT_NV12,
    NV_ENC_CAPS, NV_ENC_CAPS_PARAM, NV_ENC_CAPS_PARAM_VER,
    NV_ENC_CAPS_EXPOSED_COUNT, NV_ENC_CAPS_WIDTH_MAX, NV_ENC_CAPS_HEIGHT_MAX, NV_ENC_CAPS_ASYNC_ENCODE_SUPPORT,
    NV_ENC_CAPS_SUPPORTED_RATECONTROL_MODES, NV_ENC_CAPS_SUPPORT_YUV444_ENCODE, NV_ENC_CAPS_SUPPORT_LOSSLESS_ENCODE,
    NV_ENC_CAPS_SUPPORT_INTRA_REFRESH,
    NV_ENCODE_API_FUNCTION_LIST_VER,
    NVENC_INFINITE_GOPLENGTH,
    NV_ENC_PARAMS_FRAME_FIELD_MODE_FRAME,
    NV_ENC_PARAMS_RC_CONSTQP, NV_ENC_PARAMS_RC_VBR, NV_ENC_LEVEL_H264_5,
    NV_ENC_LEVEL_AV1_AUTOSELECT, NV_ENC_TIER_AV1_1, NV_ENC_AV1_PART_SIZE_AUTOSELECT,
    NV_ENC_VUI_COLOR_PRIMARIES_BT709, NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT709, NV_ENC_VUI_MATRIX_COEFFS_BT709,
    NV_ENC_BIT_DEPTH_8,
)


TEST_ENCODINGS = os.environ.get("XPRA_NVENC_ENCODINGS", "h264,h265,av1").split(",")
assert (x for x in TEST_ENCODINGS in ("h264", "h265", "av1")), "invalid list of encodings: %s" % (TEST_ENCODINGS,)
assert len(TEST_ENCODINGS)>0, "no encodings enabled!"
DESIRED_PRESET = os.environ.get("XPRA_NVENC_PRESET", "")
# NVENC requires compute capability value 0x30 or above:
DESIRED_TUNING = os.environ.get("XPRA_NVENC_TUNING", "")

SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE", "") or os.environ.get("XPRA_NVENC_SAVE_TO_FILE", "")

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
    "av1"   : False,
}
LOSSLESS_CODEC_SUPPORT: Dict[str, bool] = {
    "h264" : True,
    "h265" : True,
    "av1" : False,
}


# so we can warn just once per unknown preset:
UNKNOWN_PRESETS: List[str] = []


cdef GUID CLIENT_KEY_GUID
memset(&CLIENT_KEY_GUID, 0, sizeof(GUID))
CLIENT_KEYS_STR = get_license_keys(NVENCAPI_MAJOR_VERSION) + get_license_keys()
if CLIENT_KEYS_STR:
    #if we have client keys, parse them and keep the ones that look valid
    validated = []
    for x in CLIENT_KEYS_STR:
        if x:
            try:
                CLIENT_KEY_GUID = parseguid(x)
                validated.append(x)
            except Exception as e:
                log.error("invalid nvenc client key specified: '%s' (%s)", x, e)
                del e
    CLIENT_KEYS_STR = validated

CODEC_GUIDS: Dict[str, str] = {
    guidstr(NV_ENC_CODEC_H264_GUID)         : "H264",
    guidstr(NV_ENC_CODEC_HEVC_GUID)         : "HEVC",
    guidstr(NV_ENC_CODEC_AV1_GUID)          : "AV1",
}

cdef str codecstr(GUID guid):
    s = guidstr(guid)
    return CODEC_GUIDS.get(s, s)


YUV444_PRESETS: Sequence[str] = ("high-444", "lossless", "lossless-hp",)
LOSSLESS_PRESETS: Sequence[str] = ("lossless", "lossless-hp",)


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


# Note: these counters should be per-device, but
# when we call get_runtime_factor(), we don't know which device is going to get used!
# since we have load balancing, using an overall factor isn't too bad
context_counter = AtomicInteger()
context_gen_counter = AtomicInteger()
cdef double last_context_failure = 0

# per-device preset denylist - should be mutated with device_lock held
bad_presets: dict[int, list[str]] = {}
no_preset: dict[str, float] = {}


def get_runtime_factor(encoding: str, in_cs: str) -> float:
    if no_preset.get(encoding, 0):
        return 0
    global last_context_failure, context_counter
    device_count = len(init_all_devices())
    max_contexts = CONTEXT_LIMIT * device_count
    cc = context_counter.get()
    #try to avoid using too many contexts
    #(usually, we can have up to 32 contexts per card)
    low_limit = min(CONTEXT_LIMIT, 1 + CONTEXT_LIMIT// 2) * device_count
    f = max(0, 1.0 - (max(0, cc-low_limit)/max(1, max_contexts-low_limit)))
    #if we have had errors recently, lower our chances further:
    cdef double failure_elapsed = monotonic() - last_context_failure
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


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    for encoding in get_encodings():
        for in_cs, out_css in get_COLORSPACES(encoding).items():
            specs.append(
                _get_spec(encoding, in_cs, out_css)
            )
    return specs


def _get_spec(encoding: str, in_cs: str, out_css: Sequence[str]) -> VideoSpec:
    # undocumented and found the hard way, see:
    # https://github.com/Xpra-org/xpra/issues/1046#issuecomment-765450102
    # https://github.com/Xpra-org/xpra/issues/1550
    min_w, min_h = (128, 128)
    # FIXME: we should probe this using WIDTH_MAX, HEIGHT_MAX!
    max_w, max_h = MAX_SIZE.get(encoding, (4096, 4096))
    has_lossless_mode = LOSSLESS_CODEC_SUPPORT.get(encoding, LOSSLESS_ENABLED)
    width_mask = get_width_mask(in_cs)
    height_mask = get_height_mask(in_cs)
    has_lossless_mode = in_cs in ("XRGB", "BGRX", "r210") and encoding == "h264"

    #the output will actually be in one of those two formats once decoded
    #because internally that's what we convert to before encoding
    #(well, NV12... which is equivallent to YUV420P here...)

    spec = VideoSpec(
        encoding=encoding, input_colorspace=in_cs, output_colorspaces=out_css,
        has_lossless_mode=has_lossless_mode,
        codec_class=Encoder, codec_type=get_type(),
        quality=60+has_lossless_mode*40, speed=100, size_efficiency=100,
        setup_cost=80, cpu_cost=10, gpu_cost=100,
        #using a hardware encoder for something this small is silly:
        min_w=min_w, min_h=min_h,
        max_w=max_w, max_h=max_h,
        can_scale=in_cs != "r210",
        width_mask=width_mask, height_mask=height_mask,
    )
    def _get_runtime_factor() -> float:
        return get_runtime_factor(encoding, in_cs)
    spec.get_runtime_factor = _get_runtime_factor
    return spec


#ie: NVENCAPI_VERSION=0x30 -> PRETTY_VERSION = [3, 0]
PRETTY_VERSION = (int(NVENCAPI_MAJOR_VERSION), int(NVENCAPI_MINOR_VERSION))


def get_version() -> Tuple[int, int]:
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


cdef inline int roundup(int n, int m) noexcept nogil:
    return (n + m - 1) & ~(m - 1)


cdef uintptr_t cmalloc(size_t size, what) except 0:
    cdef void *ptr = malloc(size)
    if ptr==NULL:
        raise RuntimeError("failed to allocate %i bytes of memory for %s" % (size, what))
    return <uintptr_t> ptr


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

    cdef object file

    cdef object __weakref__

    cdef GUID init_codec(self) except *:
        log("init_codec()")
        codecs = self.query_codecs()
        #codecs={'H264': {"guid" : '6BC82762-4E63-4CA4-AA85-1E50F321F6BF', .. }
        internal_name = {"H265" : "HEVC"}.get(self.codec_name.upper(), self.codec_name.upper())
        guid_str = codecs.get(internal_name, {}).get("guid")
        assert guid_str, "%s not supported! (only available: %s)" % (self.codec_name, csv(codecs.keys()))
        self.codec = parseguid(guid_str)
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
                return parseguid(guid)
        #new style presets (P1 - P7),
        #we only care about the quality here,
        #the speed is set using the "tuning"
        for i in range(1, 8):
            name = "P%i" % i
            guid = presets.get(name)
            if not guid:
                continue
            preset_quality = get_preset_quality(name, 50)
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
                preset_speed = get_preset_speed(name, 50)
                preset_quality = get_preset_quality(name, 50)
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
                    return parseguid(preset_guid)
        no_preset[self.encoding] = monotonic()
        raise ValueError("no matching presets available for '%s' with speed=%i and quality=%i" % (self.codec_name, self.speed, self.quality))

    def init_context(self, encoding: str, unsigned int width, unsigned int height, src_format: str,
                     options: typedict) -> None:
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

        if SAVE_TO_FILE:
            gen = context_gen_counter.get()
            filename = SAVE_TO_FILE+"nvenc-"+str(gen)+f".{encoding}"
            self.file = open(filename, "wb")
            log.info(f"saving {encoding} stream to {filename!r}")

    cdef str _get_profile(self, options):
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
        log("init_device(%s) took %1.fms", options, (end - start) * 1000)

    def is_ready(self) -> bool:
        return bool(self.ready)

    def get_target_pixel_format(self, int quality) -> str:
        global NATIVE_RGB, YUV420_ENABLED, YUV444_ENABLED, LOSSLESS_ENABLED, YUV444_THRESHOLD, YUV444_CODEC_SUPPORT
        v = ""
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

    def get_target_lossless(self, pixel_format: str, quality : int) -> bool:
        global LOSSLESS_ENABLED, LOSSLESS_CODEC_SUPPORT
        if pixel_format not in ("YUV444P", "r210"):
            return False
        if not LOSSLESS_CODEC_SUPPORT.get(self.encoding, LOSSLESS_ENABLED):
            return False
        return quality >= LOSSLESS_THRESHOLD

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

            self.cuda_context_ptr = <void *> get_current_cuda_context()
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

    cdef void dump_caps(self, codec_name, GUID codec):
        #test all caps:
        caps = {}
        for cap in get_all_caps():
            if cap != NV_ENC_CAPS_EXPOSED_COUNT:
                v = self.query_encoder_caps(codec, cap)
                descr = get_caps_name(cap)
                caps[descr] = v
        log("caps(%s)=%s", codec_name, caps)

    cdef void init_params(self, GUID codec, NV_ENC_INITIALIZE_PARAMS *params):
        #caller must free the config!
        assert self.context, "context is not initialized"
        cdef GUID preset = self.get_preset(self.codec)
        self.preset_name = get_preset_name(guidstr(preset))
        log("init_params(%s) using preset=%s", codecstr(codec), presetstr(preset))
        profiles = self.query_profiles(codec)
        if self.profile_name and profiles and self.profile_name not in profiles:
            self.profile_name = tuple(profiles.keys())[0]
        profile_guidstr = profiles.get(self.profile_name)
        cdef GUID profile
        if profile_guidstr:
            profile = parseguid(profile_guidstr)
        else:
            profile = NV_ENC_CODEC_PROFILE_AUTOSELECT_GUID
        log("using profile=%s", get_profile_name(guidstr(profile)))

        input_format = get_buffer_format_name(self.bufferFmt)
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
        cdef int chroma = get_chroma_format(self.pixel_format)
        if chroma < 0:
            raise ValueError(f"unknown pixel format {self.pixel_format!r}")
        log("get_chroma_format(%s)=%s", self.pixel_format, chroma)
        return chroma

    cdef void tune_preset(self, NV_ENC_CONFIG *config):
        config.gopLength = NVENC_INFINITE_GOPLENGTH
        config.frameIntervalP = 1
        config.frameFieldMode = NV_ENC_PARAMS_FRAME_FIELD_MODE_FRAME
        self.tune_qp(&config.rcParams)
        cdef NV_ENC_CONFIG_H264 *h264 = &config.encodeCodecConfig.h264Config
        cdef NV_ENC_CONFIG_HEVC *hevc = &config.encodeCodecConfig.hevcConfig
        cdef NV_ENC_CONFIG_AV1 *av1 = &config.encodeCodecConfig.av1Config
        if self.codec_name=="H264":
            self.tune_h264(&config.encodeCodecConfig.h264Config, config.gopLength)
        elif self.codec_name=="H265":
            self.tune_hevc(&config.encodeCodecConfig.hevcConfig, config.gopLength)
        elif self.codec_name=="AV1":
            self.tune_av1(&config.encodeCodecConfig.av1Config, config.gopLength)
        else:
            raise ValueError(f"invalid codec name {self.codec_name}")

    cdef void tune_qp(self, NV_ENC_RC_PARAMS *rc):
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

    cdef void tune_hevc(self, NV_ENC_CONFIG_HEVC *hevc, int gopLength):
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

    cdef void tune_av1(self, NV_ENC_CONFIG_AV1 *av1, int gopLength):
        memset(av1, 0, sizeof(NV_ENC_CONFIG_AV1))
        av1.level = NV_ENC_LEVEL_AV1_AUTOSELECT
        av1.chromaFormatIDC = self.get_chroma_format()
        av1.tier = NV_ENC_TIER_AV1_1
        av1.minPartSize = NV_ENC_AV1_PART_SIZE_AUTOSELECT
        av1.maxPartSize = NV_ENC_AV1_PART_SIZE_AUTOSELECT
        # av1.outputAnnexBFormat = 0	# do not use this flag! (the decoders won' be able to parse the bitstream)
        av1.enableTimingInfo = 1
        av1.enableDecoderModelInfo = 1
        av1.enableFrameIdNumbers = 1
        av1.disableSeqHdr = 0
        av1.repeatSeqHdr = 1
        av1.enableBitstreamPadding = 0
        av1.enableLTR = 0
        # `enableTemporalSVC=1` causes crashes?
        # av1.enableTemporalSVC = 1
        av1.idrPeriod = NVENC_INFINITE_GOPLENGTH
        av1.enableIntraRefresh = INTRA_REFRESH
        if INTRA_REFRESH:
            av1.intraRefreshPeriod = 16
            av1.intraRefreshCnt = 4
        av1.maxNumRefFramesInDPB = 16
        av1.colorPrimaries = NV_ENC_VUI_COLOR_PRIMARIES_BT709
        av1.transferCharacteristics = NV_ENC_VUI_TRANSFER_CHARACTERISTIC_BT709
        av1.matrixCoefficients = NV_ENC_VUI_MATRIX_COEFFS_BT709
        av1.colorRange = 1  # full-range=1
        av1.chromaSamplePosition = 0
        av1.outputBitDepth = NV_ENC_BIT_DEPTH_8
        av1.inputBitDepth = NV_ENC_BIT_DEPTH_8
        av1.idrPeriod = gopLength

    cdef void init_buffers(self):
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
        info["total_time_ms"] = int(self.time * 1000)
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
        f = self.file
        if f:
            self.file = None
            f.close()
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

    cdef void do_clean(self):
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

    cdef void cuda_clean(self):
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

    cdef void buffer_clean(self):
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

    cdef void update_bitrate(self):
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

    cdef void flushEncoder(self):
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
        if not cuda_device_context:
            log.error("Error: no 'cuda-device-context' in %s", options)
            global last_context_failure
            last_context_failure = monotonic()
            raise RuntimeError("no cuda device context")
        # cuda_device_context.__enter__ does self.context.push()
        with cuda_device_context as cuda_context:
            quality = options.get("quality", -1)
            if quality>=0:
                self.set_encoding_quality(quality)
            speed = options.get("speed", -1)
            if speed>=0:
                self.set_encoding_speed(speed)
            return self.do_compress_image(cuda_context, image)

    cdef Tuple do_compress_image(self, cuda_context, image: ImageWrapper):
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

    cdef void exec_kernel(self, cuda_context, unsigned int w, unsigned int h, unsigned int stride):
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
        log("exec_kernel:  kernel %13s took %3.1f ms: %5i MPixels/s", self.kernel_name, elapsed * 1000, (w*h)/elapsed//1024//1024)

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

    cdef void unmap_input_resource(self, NV_ENC_INPUT_PTR mappedResource):
        if DEBUG_API:
            log("nvEncUnmapInputResource(%#x)", <uintptr_t> mappedResource)
        cdef NVENCSTATUS r = self.functionList.nvEncUnmapInputResource(self.context, mappedResource)
        raiseNVENC(r, "unmapping input resource")

    cdef Tuple nvenc_compress(self, int input_size, NV_ENC_INPUT_PTR input, timestamp=0, full_range=True):
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
            pic.encodePicFlags = NV_ENC_PIC_FLAG_FORCEIDR
        else:
            pic.pictureType = NV_ENC_PIC_TYPE_P
            pic.encodePicFlags = 0
        if self.encoding=="h264":
            pic.codecPicParams.h264PicParams.displayPOCSyntax = 2*self.frames
            pic.codecPicParams.h264PicParams.refPicFlag = self.frames==0
        elif self.encoding=="hevc":
            pic.codecPicParams.hevcPicParams.displayPOCSyntax = 2*self.frames
            pic.codecPicParams.hevcPicParams.refPicFlag = self.frames==0
        elif self.encoding=="av1":
            pic.codecPicParams.av1PicParams.displayPOCSyntax = 2*self.frames
            pic.codecPicParams.av1PicParams.refPicFlag = self.frames==0
            pic.encodePicFlags |= NV_ENC_PIC_FLAG_OUTPUT_SPSPPS
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
            size, 100.0*size/input_size, self.encoding, get_picture_type(pic.pictureType), self.frames, 1000.0*elapsed)
        if self.file:
            self.file.write(data)
            self.file.flush()
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
        cdef NV_ENC_TUNING_INFO tuning = self.get_tuning()
        log("tuning=%s (%i)", get_tuning_name(tuning), tuning)
        r = self.functionList.nvEncGetEncodePresetConfigEx(self.context, encode_GUID,
                                                           preset_GUID, <NV_ENC_TUNING_INFO> tuning, presetConfig)
        if r!=0:
            log.warn("failed to get preset config for %s (%s / %s): %s", name, guidstr(encode_GUID), guidstr(preset_GUID), nvencStatusInfo(r))
            return NULL
        return presetConfig

    cdef NV_ENC_TUNING_INFO get_tuning(self):
        cdef NV_ENC_TUNING_INFO tuning
        if DESIRED_TUNING:
            tuning = get_tuning_value(DESIRED_TUNING)
            log(f"tuning override {DESIRED_TUNING!r}={tuning}")
            if tuning >= 0:
                return tuning
        if self.lossless:
            return NV_ENC_TUNING_INFO_LOSSLESS
        if self.speed > 80:
            return NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY
        if self.speed >= 50:
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
                preset_name = get_preset_name(preset_str)
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
        PROFILES_GUIDS = get_profile_guids(guidstr(encode_GUID))
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
                for format_mask in sorted(get_buffer_formats()):
                    if format_mask>0 and (format_mask & inputFmt)>0:
                        format_name = get_buffer_format_name(format_mask)
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
        raiseNVENC(r, "getting encode caps for %s" % get_caps_name(caps_type))
        if DEBUG_API:
            log("query_encoder_caps(%s, %s) %s=%s", codecstr(encode_GUID), caps_type, get_caps_name(caps_type), val)
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

    cdef void open_encode_session(self):
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
        cdef NVENCSTATUS r = create_nvencode_instance(self.functionList)
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
        if is_transient_error(r):
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
def init_module(options: dict) -> None:
    from xpra.codecs.nvidia.util import has_nvidia_hardware
    if has_nvidia_hardware() is False:
        raise ImportError("no nvidia GPU device found")
    log("nvenc.init_module(%s)", options)
    min_version = 10
    if NVENCAPI_MAJOR_VERSION < min_version:
        raise RuntimeError("unsupported version of NVENC: %i, minimum version is %i" % (NVENCAPI_VERSION, min_version))
    log("NVENC encoder API version %s", ".".join([str(x) for x in PRETTY_VERSION]))

    cdef Encoder test_encoder
    #cdef uint32_t max_version
    #cdef NVENCSTATUS r = NvEncodeAPIGetMaxSupportedVersion(&max_version)
    #raiseNVENC(r, "querying max version")
    #log(" maximum supported version: %s", max_version)

    # load the library / DLL:
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
    # check NVENC availability by creating a context:
    device_warnings = {}
    log("init_module(%s) will try keys: %s", options, try_keys)
    for client_key in try_keys:
        if client_key:
            #this will set the global key object used by all encoder contexts:
            log("init_module(%s) testing with key '%s'", options, client_key)
            global CLIENT_KEY_GUID
            CLIENT_KEY_GUID = parseguid(client_key)

        for device_id in tuple(devices):
            log("testing encoder with device %s", device_id)
            device = load_device(device_id)
            cdc = cuda_device_context(device_id, device)
            with cdc as device_context:
                encoder_options = typedict(options)
                encoder_options.update({
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
                    log.warn(" device %s is not supported", get_device_name(device_id) or device_id)
                    log.warn(" %s", repr(e) or type(e))
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
                                           "av1"    : "AV1",
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
                    colorspaces = list(get_COLORSPACES(encoding).keys())
                    if not colorspaces:
                        raise ValueError(f"cannot use NVENC: no colorspaces available for {encoding}")
                    src_format = colorspaces[0]
                    log(f"testing {encoding} using {src_format} from {colorspaces}")
                    encoder_options["dst-formats"] = get_COLORSPACES(encoding).get(src_format, ())
                    test_encoder = None
                    W = 1920
                    H = 1080
                    try:
                        test_encoder = Encoder()
                        test_encoder.init_context(encoding, W, H, src_format, encoder_options)
                        success = True
                        if client_key:
                            log("the license key '%s' is valid", client_key)
                            valid_keys.append(client_key)
                        #check for YUV444 support
                        yuv444_support = YUV444_ENABLED and bool(test_encoder.query_encoder_caps(test_encoder.get_codec(), <NV_ENC_CAPS> NV_ENC_CAPS_SUPPORT_YUV444_ENCODE))
                        current = YUV444_CODEC_SUPPORT.get(encoding, YUV444_ENABLED)
                        YUV444_CODEC_SUPPORT[encoding] = yuv444_support
                        if YUV444_ENABLED and current != yuv444_support:
                            wkey = "nvenc:%s-%s-%s" % (device_id, encoding, "YUV444")
                            if first_time(wkey):
                                device_warnings.setdefault(device_id, {}).setdefault(encoding, []).append("YUV444")
                            log("no support for YUV444 with %s", encoding)
                        log("%s YUV444 support: %s", encoding, YUV444_CODEC_SUPPORT.get(encoding, YUV444_ENABLED))
                        #check for lossless:
                        lossless_support = yuv444_support and LOSSLESS_ENABLED and bool(test_encoder.query_encoder_caps(test_encoder.get_codec(), <NV_ENC_CAPS> NV_ENC_CAPS_SUPPORT_LOSSLESS_ENCODE))
                        current = LOSSLESS_CODEC_SUPPORT.get(encoding, LOSSLESS_ENABLED)
                        LOSSLESS_CODEC_SUPPORT[encoding] = lossless_support
                        if current != lossless_support:
                            wkey = "nvenc:%s-%s-%s" % (device_id, encoding, "lossless")
                            if first_time(wkey):
                                device_warnings.setdefault(device_id, {}).setdefault(encoding, []).append("lossless")
                            log("no support for lossless mode with %s", encoding)
                        log("%s lossless support: %s", encoding, LOSSLESS_CODEC_SUPPORT.get(encoding, LOSSLESS_ENABLED))
                        # check intra refresh:
                        intra = test_encoder.query_encoder_caps(test_encoder.get_codec(), <NV_ENC_CAPS> NV_ENC_CAPS_SUPPORT_INTRA_REFRESH)
                        log("%s intra refresh: %s", encoding, intra)
                        # test compress:
                        if options.get("full", False):
                            from xpra.codecs.checks import make_test_image
                            image = make_test_image(src_format, W, H)
                            out = test_encoder.compress_image(image, encoder_options)
                            if not out:
                                raise RuntimeError("failed to compress test image %s" % (image, ))

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
            CLIENT_KEY_GUID = parseguid(x)
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
        pretty_strs = tuple({"h265": "hevc"}.get(encoding, encoding) for encoding in ENCODINGS)
        log.info("NVENC v%i successfully initialized with codecs: %s", NVENCAPI_MAJOR_VERSION, csv(pretty_strs))
        _init_message = True


def cleanup_module() -> None:
    log("nvenc.cleanup_module()")
    reset_state()
    free_default_device_context()


def selftest(full=False) -> None:
    from xpra.codecs.nvidia.util import has_nvidia_hardware
    if not has_nvidia_hardware():
        raise ImportError("no nvidia GPU device found")
    v = get_nvidia_module_version(True)
    assert NVENCAPI_MAJOR_VERSION>=9, "unsupported NVENC version %i" % NVENCAPI_MAJOR_VERSION
    log("nvidia module version: %s", v)
    if full:
        from xpra.codecs.checks import testencoder, get_encoder_max_sizes
        from xpra.codecs.nvidia.nvenc import encoder
        init_module({"full": full})
        # assert testencoder(encoder, False, typedict())
        log.info("%s max dimensions: %s", encoder, get_encoder_max_sizes(encoder))
