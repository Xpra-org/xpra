# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_OPENCL_DEBUG")
error = log.error

import time
import os
import warnings
import numpy
assert bytearray
import pyopencl             #@UnresolvedImport
from pyopencl import mem_flags  #@UnresolvedImport

PREFERRED_DEVICE_TYPE = os.environ.get("XPRA_OPENCL_DEVICE_TYPE", "GPU")
PREFERRED_DEVICE_NAME = os.environ.get("XPRA_OPENCL_DEVICE_NAME", "")
PREFERRED_DEVICE_PLATFORM = os.environ.get("XPRA_OPENCL_PLATFORM", "")


opencl_platforms = pyopencl.get_platforms()
if len(opencl_platforms)==0:
    raise ImportError("no OpenCL platforms found!")

def roundup(n, m):
    return (n + m - 1) & ~(m - 1)

def dimdiv(dim, div):
    #when we divide a dimensions by the subsampling
    #we want to round up so as to include the last
    #pixel when we hit odd dimensions
    return roundup(dim/div, div)

def device_type(d):
    try:
        return pyopencl.device_type.to_string(d.type)
    except:
        return d.type

def device_info(d):
    dtype = device_type(d)
    if hasattr(d, "opencl_c_version"):
        return "%s: %s (%s / %s)" % (dtype, d.name.strip(), d.version, d.opencl_c_version)
    return "%s: %s (%s)" % (dtype, d.name.strip(), d.version)
def platform_info(platform):
    return "%s (%s)" % (platform.name, platform.vendor)

def is_supported(platform_name):
    #FreeOCL and pocl do not work:
    return not platform_name.startswith("FreeOCL") and not platform_name.startswith("Portable Computing Language")

def log_device_info(device):
    if not device:
        return
    log.info(" using device: %s", device_info(device))
    debug("max_work_group_size=%s", device.max_work_group_size)
    debug("max_work_item_dimensions=%s", device.max_work_item_dimensions)
    debug("max_work_item_sizes=%s", device.max_work_item_sizes)

def log_platforms_info():
    debug("found %s OpenCL platforms:", len(opencl_platforms))
    for platform in opencl_platforms:
        devices = platform.get_devices()
        p = "*"
        if not is_supported(platform.name):
            p = "-"
        debug("%s %s - %s devices:", p, platform_info(platform), len(devices))
        for d in devices:
            p = "-"
            if d.available and d.compiler_available and d.get_info(pyopencl.device_info.IMAGE_SUPPORT) and is_supported(platform.name):
                p = "+"
            debug(" %s %s", p, device_info(d))

def log_version_info():
    log.info("PyOpenCL loaded, header version: %s, GL support: %s",
             ".".join([str(x) for x in pyopencl.get_cl_header_version()]), pyopencl.have_gl())


#select a platform and device:
selected_device = None
selected_platform = None
context = None
def reselect_device():
    global context, selected_device,selected_platform
    selected_device = None
    selected_platform = None
    context = None
    select_device()
def select_device():
    global context, selected_device,selected_platform
    if context is not None:
        return
    log_version_info()
    log_platforms_info()
    #try to choose a platform and device using *our* heuristics / env options:
    best_options = []
    other_options = []
    for platform in opencl_platforms:
        devices = platform.get_devices()
        for d in devices:
            if d.available and d.compiler_available and d.get_info(pyopencl.device_info.IMAGE_SUPPORT):
                dtype = device_type(d)
                add_to = other_options
                if dtype==PREFERRED_DEVICE_TYPE and \
                    (len(PREFERRED_DEVICE_NAME)==0 or d.name.find(PREFERRED_DEVICE_NAME)>=0) and \
                    (len(PREFERRED_DEVICE_PLATFORM)==0 or str(platform.name).find(PREFERRED_DEVICE_PLATFORM)>=0):
                    add_to = best_options
                if not is_supported(platform.name) and (len(PREFERRED_DEVICE_PLATFORM)==0 or str(platform.name).find(PREFERRED_DEVICE_PLATFORM)<0):
                    debug("ignoring unsupported platform/device: %s / %s", platform.name, d.name)
                    continue
                #Intel SDK does not work (well?) on AMD CPUs:
                if platform.name.startswith("Intel") and d.name.startswith("AMD"):
                    #less likely to work: add to end of the list...
                    add_to.append((d, platform))
                else:
                    add_to.insert(0, (d, platform))
    debug("best device/platform options: %s", best_options)
    debug("other device/platform options: %s", other_options)
    for d, p in best_options+other_options:
        try:
            debug("trying platform: %s", platform_info(p))
            debug("with device: %s", device_info(d))
            context = pyopencl.Context([d])
            selected_platform = p
            selected_device = d
            log.info(" using platform: %s", platform_info(selected_platform))
            log_device_info(selected_device)
            return
        except Exception, e:
            log.warn("failed to use %s", platform_info(p))
            log.warn("with device %s", device_info(d))
            log.warn("Error: %s", e, exc_info=True)
    #fallback to pyopencl auto mode:
    log.warn("OpenCL Error: failed to find a working platform and device combination... trying with pyopencl's 'create_some_context'")
    context = pyopencl.create_some_context(interactive=False)
    devices = context.get_info(pyopencl.context_info.DEVICES)
    log.info("chosen context has %s device(s):", len(devices))
    for d in devices:
        log_device_info(d)
    assert len(devices)==1, "we only handle a single device at a time, sorry!"
    selected_device = devices[0]
    assert context is not None and selected_device is not None


#Note: we don't care about alpha!
#This tries to map our standard RGB representation
#to the channel_order types that OpenCL may support
IN_CHANNEL_ORDER = []
#a list of: (string, pyopencl.channel_order)
#ie: [("RGBA", pyopencl.channel_order.RGBA), ..]
CHANNEL_ORDER_TO_STR = {}
#channel order to name:
#ie: { pyopencl.channel_order.RGBx : "RGBx", ...}
for rgb_mode, channel_order_name in (
                  ("RGBX",  "RGBx"),   #pyopencl.channel_order.RGBx
                  ("RGBX",  "RGBA"),   #pyopencl.channel_order.RGBA
                  ("BGRX",  "BGRA"),   #pyopencl.channel_order.BGRA
                  ("RGB" ,  "RGB"),    #pyopencl.channel_order.RGB
                  ):
    if not hasattr(pyopencl.channel_order, channel_order_name):
        debug("this build does not have support for %s", channel_order_name)
        continue
    channel_order = getattr(pyopencl.channel_order, channel_order_name)
    IN_CHANNEL_ORDER.append((rgb_mode, channel_order))
    CHANNEL_ORDER_TO_STR[channel_order] = channel_order_name


FILTER_MODE_TO_STR = {
                    pyopencl.filter_mode.LINEAR : "LINEAR",
                    pyopencl.filter_mode.NEAREST: "NEAREST"
                  }

def has_image_format(image_formats, channel_order, channel_type):
    """ checks that the combination of channel_order and channel_type is supported
        in one of the image_formats.
    """
    for iformat in image_formats:
        if iformat.channel_order==channel_order and iformat.channel_data_type==channel_type:
            return True
    return False

def has_same_channels(src, dst):
    """ checks for missing RGB channels ignoring alpha, RGB-BGR -> True, but also BGRX-RGBA -> True ...
        in effect, this should always be True for the modes we use in this class
    """
    scheck = [x for x in src if (x not in dst and x not in ("A", "X"))]
    dcheck = [x for x in dst if (x not in src and x not in ("A", "X"))]
    #log.info("has_same_channels(%s, %s)=%s (%s - %s)", src, dst, scheck, dcheck, len(scheck)==0 and len(dcheck)==0)
    return len(scheck)==0 and len(dcheck)==0

def gen_yuv_to_rgb():
    global context
    from xpra.codecs.csc_opencl.opencl_kernels import gen_yuv_to_rgb_kernels, rgb_mode_to_indexes, indexes_to_rgb_mode

    YUV_to_RGB_KERNELS = {}
    #for YUV to RGB support we need to be able to handle the channel_order in WRITE_ONLY mode
    #so we can download the result of the CSC:
    sif = pyopencl.get_supported_image_formats(context, mem_flags.WRITE_ONLY,  pyopencl.mem_object_type.IMAGE2D)
    debug("get_supported_image_formats(WRITE_ONLY, IMAGE2D)=%s", sif)
    missing = []
    found_rgb = set()
    def add_yuv_to_rgb(dst_rgb_mode, kernel_rgb_mode, download_rgb_mode, channel_order):
        """ add the kernels converting yuv-to-rgb for the rgb_mode given (and record the channel order)"""
        debug("add_yuv_to_rgb%s", (dst_rgb_mode, kernel_rgb_mode, download_rgb_mode, CHANNEL_ORDER_TO_STR.get(channel_order)))
        kernels = gen_yuv_to_rgb_kernels(kernel_rgb_mode)
        for (yuv_mode, krgb_mode), (kname, ksrc) in kernels.items():
            assert krgb_mode==kernel_rgb_mode
            YUV_to_RGB_KERNELS[(yuv_mode, dst_rgb_mode)] = (kname, download_rgb_mode, channel_order, ksrc)
            found_rgb.add(dst_rgb_mode)

    for rgb_mode, channel_order in IN_CHANNEL_ORDER:
        #why do we discard RGBX download mode? because it doesn't work, don't ask me why
        if not has_image_format(sif, channel_order, pyopencl.channel_type.UNSIGNED_INT8) or rgb_mode=="RGBX":
            debug("YUV 2 RGB: channel order %s is not supported directly in WRITE_ONLY + UNSIGNED_INT8 mode", CHANNEL_ORDER_TO_STR.get(channel_order))
            missing.append((rgb_mode, channel_order))
            continue
        #it is supported natively, so this is easy:
        #just generate kernels for the "RGB(X)" format OpenCL will deliver the image in
        #and dst_rgb_mode is the same mode we download to
        add_yuv_to_rgb(rgb_mode, "RGBX", rgb_mode, channel_order)

    if len(YUV_to_RGB_KERNELS)>0 and len(missing)>0:
        debug("YUV 2 RGB: trying to find alternatives for: %s", missing)
        #now look for rgb byte order workarounds (doing the byteswapping ourselves):
        for dst_rgb_mode, _ in missing:
            if dst_rgb_mode in found_rgb:
                #we already have an alternative channel_order for this rgb mode
                #ie: RGBx and RGBA both map to "RGBX" or "RGBA"
                debug("%s already found", dst_rgb_mode)
                continue
            #we want a mode which is supported and has the same component channels
            for _, download_rgb_mode, channel_order, _ in YUV_to_RGB_KERNELS.values():
                if len(download_rgb_mode)!=len(dst_rgb_mode):
                    #skip mode if it has fewer channels (could drop one we need)
                    debug("skipping %s (number of channels different from %s)", download_rgb_mode, dst_rgb_mode)
                    continue
                ok = has_same_channels(download_rgb_mode, dst_rgb_mode)
                debug("testing %s as byteswap alternative to %s : %s", download_rgb_mode, dst_rgb_mode, ok)
                if not ok:
                    continue
                debug("YUV 2 RGB: using download mode %s to support %s via generated CL kernel byteswapping", download_rgb_mode, dst_rgb_mode)
                #now we "just" need to add a kernel which will give us
                #dst_rgb_mode after the ???X image data is downloaded as download_rgb_mode
                #ie: we may want BGRX as output, but are downloading the pixels to RGBX (OpenCL does byteswapping)
                #OR: we want RGBX as output, but are downloading to BGRX..
                #so we need the inverse transform which will come out right
                dli = rgb_mode_to_indexes(download_rgb_mode)    #ie: BGRX -> [2,1,0,3]
                wanti = rgb_mode_to_indexes(dst_rgb_mode)       #ie: RGBX -> [0,1,2,3]
                #for each ending position, figure out where it started from:
                rindex = {} #reverse index
                for i in range(4):
                    rindex[dli.index(i)] = i                    #ie: {2:0, 1:1, 0:2, 3:3}
                debug("YUV 2 RGB: reverse map for download mode %s (%s): %s", download_rgb_mode, dli, rindex)
                virt_mode = indexes_to_rgb_mode([rindex[x] for x in wanti])
                debug("YUV 2 RGB: virtual mode for %s (%s): %s", dst_rgb_mode, wanti, virt_mode)
                add_yuv_to_rgb(dst_rgb_mode, virt_mode, download_rgb_mode, channel_order)
                break
            if dst_rgb_mode not in found_rgb:
                #not matched:
                log("YUV 2 RGB: channel order %s is not supported: we don't have a byteswapping alternative", dst_rgb_mode)
                continue
    debug("YUV 2 RGB conversions=%s", sorted(YUV_to_RGB_KERNELS.keys()))
    #debug("YUV 2 RGB kernels=%s", YUV_to_RGB_KERNELS)
    debug("YUV 2 RGB kernels=%s", sorted(list(set([x[0] for x in YUV_to_RGB_KERNELS.values()]))))
    return YUV_to_RGB_KERNELS


def gen_rgb_to_yuv():
    global context
    from xpra.codecs.csc_opencl.opencl_kernels import gen_rgb_to_yuv_kernels, rgb_mode_to_indexes, indexes_to_rgb_mode
    #for RGB to YUV support we need to be able to handle the channel_order,
    #with READ_ONLY and both with COPY_HOST_PTR and USE_HOST_PTR since we
    #do not know in advance which one we can use..
    RGB_to_YUV_KERNELS = {}
    sif = pyopencl.get_supported_image_formats(context, mem_flags.WRITE_ONLY,  pyopencl.mem_object_type.IMAGE2D)
    sif_copy = pyopencl.get_supported_image_formats(context, mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR,  pyopencl.mem_object_type.IMAGE2D)
    debug("get_supported_image_formats(READ_ONLY | COPY_HOST_PTR, IMAGE2D)=%s", sif)
    sif_use = pyopencl.get_supported_image_formats(context, mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR,  pyopencl.mem_object_type.IMAGE2D)
    debug("get_supported_image_formats(READ_ONLY | USE_HOST_PTR, IMAGE2D)=%s", sif)
    if not has_image_format(sif_copy, pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8) or \
       not has_image_format(sif_use, pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8):
        log.error("cannot convert to YUV without support for READ_ONLY R channel with both COPY_HOST_PTR and USE_HOST_PTR")
        return  {}
    missing = []
    found_rgb = set()
    def add_rgb_to_yuv(src_rgb_mode, kernel_rgb_mode, upload_rgb_mode, channel_order):
        debug("add_rgb_to_yuv%s", (src_rgb_mode, kernel_rgb_mode, upload_rgb_mode, CHANNEL_ORDER_TO_STR.get(channel_order)))
        kernels = gen_rgb_to_yuv_kernels(kernel_rgb_mode)
        #debug("kernels(%s)=%s", rgb_mode, kernels)
        for key, k_def in kernels.items():
            ksrc, dst = key
            assert ksrc==kernel_rgb_mode
            kname, ksrc = k_def
            RGB_to_YUV_KERNELS[(src_rgb_mode, dst)] = (kname, upload_rgb_mode, channel_order, ksrc)
            found_rgb.add(src_rgb_mode)
    for src_rgb_mode, channel_order in IN_CHANNEL_ORDER:
        errs = []
        if not has_image_format(sif_copy, channel_order, pyopencl.channel_type.UNSIGNED_INT8):
            errs.append("COPY_HOST_PTR")
        if not has_image_format(sif_use, channel_order, pyopencl.channel_type.UNSIGNED_INT8):
            errs.append("USE_HOST_PTR")
        if len(errs)>0:
            debug("RGB 2 YUV: channel order %s is not supported in READ_ONLY mode(s): %s", src_rgb_mode, " or ".join(errs))
            missing.append((src_rgb_mode, channel_order))
            continue
        #OpenCL handles this rgb mode natively,
        #so we can generate the kernel for RGB(x) format:
        #(and let the copy to device deal natively with the format given)
        add_rgb_to_yuv(src_rgb_mode, "RGBX", src_rgb_mode, channel_order)
    if len(missing)>0:
        debug("RGB 2 YUV: trying to find alternatives for: %s", missing)
        #now look for rgb byte order workarounds (doing the byteswapping ourselves):
        for src_rgb_mode, _ in missing:
            if src_rgb_mode in found_rgb:
                #we already have an alternative channel_order for this rgb mode
                #ie: RGBx and RGBA both map to "RGBX" or "RGBA"
                debug("%s already found", src_rgb_mode)
                continue
            #we want a mode which is supported and has the same component channels
            for _, upload_rgb_mode, channel_order, _ in RGB_to_YUV_KERNELS.values():
                if len(upload_rgb_mode)!=len(src_rgb_mode):
                    #skip mode if it has fewer channels (could drop one we need)
                    debug("skipping %s (number of channels different from %s)", upload_rgb_mode, src_rgb_mode)
                    continue
                ok = has_same_channels(upload_rgb_mode, src_rgb_mode)
                debug("testing %s as byteswap alternative to %s : %s", upload_rgb_mode, src_rgb_mode, ok)
                if not ok:
                    continue
                debug("RGB 2 YUV: using upload mode %s to support %s via generated CL kernel byteswapping", upload_rgb_mode, src_rgb_mode)
                #easier than in YUV 2 RGB above, we just need to work out the starting positions of the RGB pixels:
                spos = rgb_mode_to_indexes(src_rgb_mode)     #ie: BGRX -> [2,1,0,3]
                uli = rgb_mode_to_indexes(upload_rgb_mode)   #ie: RGBX -> [0,1,2,3]
                virt_mode = indexes_to_rgb_mode([uli[x] for x in spos])   #ie: [2,1,0,3]
                debug("RGB 2 YUV: virtual mode for %s: %s", src_rgb_mode, virt_mode)
                add_rgb_to_yuv(src_rgb_mode, virt_mode, upload_rgb_mode, channel_order)
                break
            if src_rgb_mode not in found_rgb:
                #not matched:
                log("RGB 2 YUV: channel order %s is not supported: we don't have a byteswapping alternative", src_rgb_mode)
                continue

    debug("RGB 2 YUV conversions=%s", sorted(RGB_to_YUV_KERNELS.keys()))
    #debug("RGB 2 YUV kernels=%s", RGB_to_YUV_KERNELS)
    debug("RGB 2 YUV kernels=%s", sorted(list(set([x[0] for x in RGB_to_YUV_KERNELS.values()]))))
    return RGB_to_YUV_KERNELS

KERNELS_DEFS = {}
def regen_kernels():
    global KERNELS_DEFS
    KERNELS_DEFS = {}
    gen_kernels()
def gen_kernels():
    """
    The code here is complicated by the fact that we don't know
    in advance what image modes are supported where...
    So we try to generate the minimum set of kernels that will allow
    us to handle the greatest combination of inputs and outputs.
    See both gen_xxx_to_xxx methods for details.
    """
    global KERNELS_DEFS
    YUV_to_RGB_KERNELS = gen_yuv_to_rgb()
    RGB_to_YUV_KERNELS = gen_rgb_to_yuv()

    KERNELS_DEFS = RGB_to_YUV_KERNELS.copy()
    KERNELS_DEFS.update(YUV_to_RGB_KERNELS)
    debug("all supported conversions=%s", sorted(KERNELS_DEFS.keys()))
    #work out the unique kernels we have generated (kname -> ksrc)
    NAMES_TO_KERNELS = {}
    for name, _, _, kernel in KERNELS_DEFS.values():
        NAMES_TO_KERNELS[name] = kernel
    return NAMES_TO_KERNELS


program = None
def rebuild_kernels():
    global program
    program = None
    build_kernels()
def build_kernels():
    global program
    if program is not None:
        return
    select_device()
    NAMES_TO_KERNELS = gen_kernels()
    with warnings.catch_warnings(record=True) as w:
        def dump_warnings(logfn):
            build_warnings = [x for x in w if x.category==pyopencl.CompilerWarning]
            if len(build_warnings)>0:
                logfn("%s build warnings:", len(build_warnings))
                for x in build_warnings:
                    debug(str(x))
            logfn("all warnings:%s", "\n* ".join(set([str(x) for x in w])))
        try:
            warnings.simplefilter("always")
            debug("building %s OpenCL kernels: %s", len(NAMES_TO_KERNELS), ", ".join(sorted(NAMES_TO_KERNELS.keys())))
            program = pyopencl.Program(context, "\n".join(NAMES_TO_KERNELS.values()))
            program.build()
            dump_warnings(debug)
        except Exception, e:
            error("cannot build the OpenCL program: %s", e, exc_info=True)
            dump_warnings(log.warn)
            raise ImportError("cannot build the OpenCL program: %s" % e)


from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs


def init_module():
    build_kernels()

def get_type():
    return "opencl"

def get_version():
    return pyopencl.version.VERSION_TEXT

def get_input_colorspaces():
    build_kernels()
    return sorted(list(set([src for (src, _) in KERNELS_DEFS.keys()])))

def get_output_colorspaces(input_colorspace):
    build_kernels()
    return sorted(list(set([dst for (src, dst) in KERNELS_DEFS.keys() if src==input_colorspace])))

def validate_in_out(in_colorspace, out_colorspace):
    assert in_colorspace in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    assert out_colorspace in get_output_colorspaces(in_colorspace), "invalid output colorspace: %s (must be one of %s for input %s)" % (out_colorspace, get_output_colorspaces(in_colorspace), in_colorspace)

def get_spec(in_colorspace, out_colorspace):
    validate_in_out(in_colorspace, out_colorspace)
    return codec_spec(ColorspaceConverter, codec_type=get_type(), speed=100, setup_cost=10, cpu_cost=10, gpu_cost=50, min_w=128, min_h=128, can_scale=True)


class ColorspaceConverter(object):

    def __init__(self):
        global context, program
        build_kernels()
        self.src_width = 0
        self.src_height = 0
        self.src_format = ""
        self.dst_width = 0
        self.dst_height = 0
        self.dst_format = ""
        self.time = 0
        self.frames = 0
        self.context = None
        self.program = None
        self.queue = None
        self.channel_order = None
        self.sampler = None
        self.kernel_function = None
        self.kernel_function_name = None
        self.do_convert_image = None

    def init_context(self, src_width, src_height, src_format,
                           dst_width, dst_height, dst_format, csc_speed=100):  #@DuplicatedSignature
        debug("init_context%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format, csc_speed))
        validate_in_out(src_format, dst_format)
        self.src_width = src_width
        self.src_height = src_height
        self.src_format = src_format
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.dst_format = dst_format
        self.init_with_device()

    def init_with_device(self):
        global context, program
        self.context = context
        self.program = program
        self.queue = pyopencl.CommandQueue(self.context)
        fm = pyopencl.filter_mode.NEAREST
        self.sampler = pyopencl.Sampler(self.context, False, pyopencl.addressing_mode.CLAMP_TO_EDGE, fm)
        k_def = KERNELS_DEFS.get((self.src_format, self.dst_format))
        assert k_def, "no kernel found for %s to %s" % (self.src_format, self.dst_format)
        self.kernel_function_name, _, self.channel_order, src = k_def
        if self.src_format.endswith("P"):
            #yuv 2 rgb:
            self.do_convert_image = self.convert_image_yuv
        else:
            #rgb 2 yuv:
            self.do_convert_image = self.convert_image_rgb
        debug("init_context(..) kernel source=%s", src)
        self.kernel_function = getattr(self.program, self.kernel_function_name)
        debug("init_context(..) channel order=%s, filter mode=%s", CHANNEL_ORDER_TO_STR.get(self.channel_order, self.channel_order), FILTER_MODE_TO_STR.get(fm, fm))
        debug("init_context(..) kernel_function %s: %s", self.kernel_function_name, self.kernel_function)
        assert self.kernel_function

    def get_info(self):
        info = {"frames"    : self.frames,
                "src_width" : self.src_width,
                "src_height": self.src_height,
                "src_format": self.src_format,
                "dst_width" : self.dst_width,
                "dst_height": self.dst_height,
                "dst_format": self.dst_format}
        if self.frames>0 and self.time>0:
            pps = float(self.src_width) * float(self.src_height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __str__(self):
        if self.queue is None:
            return "opencl(uninitialized or closed)"
        return "opencl(%s %sx%s - %s %sx%s)" % (self.src_format, self.src_width, self.src_height,
                                                 self.dst_format, self.dst_width, self.dst_height)

    def is_closed(self):
        return False

    def __del__(self):                  #@DuplicatedSignature
        self.clean()

    def get_src_width(self):
        return self.src_width

    def get_src_height(self):
        return self.src_height

    def get_src_format(self):
        return self.src_format

    def get_dst_width(self):
        return self.dst_width

    def get_dst_height(self):
        return self.dst_height

    def get_dst_format(self):
        return self.dst_format

    def get_type(self):
        return  "opencl"


    def clean(self):                        #@DuplicatedSignature
        debug("clean() queue=%s", self.queue)
        if self.queue:
            self.queue.finish()
            self.queue = None
            self.kernel_function = None


    def get_work_sizes(self, wwidth, wheight):
        #ensure the local and global work size are valid, see:
        #http://stackoverflow.com/questions/3957125/questions-about-global-and-local-work-size
        local_w, local_h = 64, 64
        #debug("max_work_item_sizes=%s, max_work_group_size=%s", selected_device.max_work_item_sizes, selected_device.max_work_group_size)
        maxw_w, maxw_h = selected_device.max_work_item_sizes[:2]
        while local_w*local_h>selected_device.max_work_group_size or local_w>maxw_w or local_h>maxw_h:
            if local_w>maxw_w:
                local_w /= 2
            if local_h>maxw_h:
                local_h /= 2
            if local_w*local_h>selected_device.max_work_group_size:
                #prefer h<w for local work:
                if local_h>=local_w:
                    local_h /= 2
                else:
                    local_w /= 2
        globalWorkSize = (roundup(wwidth, local_w), roundup(wheight, local_h))
        localWorkSize = local_w, local_h
        return globalWorkSize, localWorkSize


    def convert_image(self, image, retry=0):
        global context, program
        if self.do_convert_image==None:
            raise Exception("not initialized!")
        if self.context!=context:
            debug("old context=%s, new context=%s", self.context, context)
            log.info("using new OpenCL context (context changed)")
            self.init_with_device()
        #we should be able to compare program!=self.program
        #but it has been reported that this does not work in some cases
        #so the code below is a more obscure way of doing the same thing
        #which unfortunately only works on PyOpenCL versions 2013.2 and later
        #Note: at the moment, program only changes when the context does,
        #so this will probably *never* even fire, for now at least.
        elif hasattr(self.program, "int_ptr") and self.program.int_ptr!=program.int_ptr:
            debug("old program=%s (int_ptr=%s), new program=%s (int_ptr=%s)", self.program, self.program.int_ptr, program, program.int_ptr)
            log.info("using new OpenCL context (program changed)")
            self.init_with_device()
        try:
            return self.do_convert_image(image)
        except pyopencl.LogicError, e:
            if retry>0:
                raise e
            log.warn("OpenCL error: %s", e)
            self.reinit()
            return self.convert_image(image, retry+1)

    def reinit(self):
        log.info("re-initializing OpenCL")
        reselect_device()
        regen_kernels()
        rebuild_kernels()
        self.init_with_device()

    def convert_image_yuv(self, image):
        start = time.time()
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        strides = image.get_rowstride()
        pixels = image.get_pixels()
        assert iplanes==ImageWrapper._3_PLANES, "we only handle planar data as input!"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        assert len(strides)==len(pixels)==3, "invalid number of planes or strides (should be 3)"
        assert width>=self.src_width and height>=self.src_height, "expected source image with dimensions of at least %sx%s but got %sx%s" % (self.src_width, self.src_height, width, height)

        #adjust work dimensions for subsampling:
        #(we process N pixels at a time in each dimension)
        divs = get_subsampling_divs(self.src_format)
        wwidth = dimdiv(self.dst_width, max(x_div for x_div, _ in divs))
        wheight = dimdiv(self.dst_height, max(y_div for _, y_div in divs))
        globalWorkSize, localWorkSize  = self.get_work_sizes(wwidth, wheight)

        kernelargs = [self.queue, globalWorkSize, localWorkSize]

        iformat = pyopencl.ImageFormat(pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8)
        input_images = []
        for i in range(3):
            _, y_div = divs[i]
            plane = pixels[i]
            if type(plane)==str:
                flags = mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR
            else:
                flags = mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR
            shape = strides[i], self.src_height/y_div
            iimage = pyopencl.Image(self.context, flags, iformat, shape=shape, hostbuf=plane)
            input_images.append(iimage)

        #output image:
        oformat = pyopencl.ImageFormat(self.channel_order, pyopencl.channel_type.UNORM_INT8)
        oimage = pyopencl.Image(self.context, mem_flags.WRITE_ONLY, oformat, shape=(self.dst_width, self.dst_height))

        kernelargs += input_images + [numpy.int32(self.src_width), numpy.int32(self.src_height),
                       numpy.int32(self.dst_width), numpy.int32(self.dst_height),
                       self.sampler, oimage]

        kstart = time.time()
        debug("convert_image(%s) calling %s%s after upload took %.1fms",
              image, self.kernel_function_name, tuple(kernelargs), 1000.0*(kstart-start))
        self.kernel_function(*kernelargs)
        self.queue.finish()
        #free input images:
        for iimage in input_images:
            iimage.release()
        kend = time.time()
        debug("%s took %.1fms", self.kernel_function, 1000.0*(kend-kstart))

        out_array = numpy.empty(self.dst_width*self.dst_height*4, dtype=numpy.byte)
        pyopencl.enqueue_read_image(self.queue, oimage, (0, 0), (self.dst_width, self.dst_height), out_array)
        self.queue.finish()
        debug("readback using %s took %.1fms", CHANNEL_ORDER_TO_STR.get(self.channel_order), 1000.0*(time.time()-kend))
        self.time += time.time()-start
        self.frames += 1
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, out_array.data, self.dst_format, 24, self.dst_width*4, planes=ImageWrapper.PACKED)


    def convert_image_rgb(self, image):
        start = time.time()
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        stride = image.get_rowstride()
        pixels = image.get_pixels()
        #debug("convert_image(%s) planes=%s, pixels=%s, size=%s", image, iplanes, type(pixels), len(pixels))
        assert iplanes==ImageWrapper.PACKED, "we only handle packed data as input!"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        assert width>=self.src_width and height>=self.src_height, "expected source image with dimensions of at least %sx%s but got %sx%s" % (self.src_width, self.src_height, width, height)

        #adjust work dimensions for subsampling:
        #(we process N pixels at a time in each dimension)
        divs = get_subsampling_divs(self.dst_format)
        wwidth = dimdiv(self.dst_width, max([x_div for x_div, _ in divs]))
        wheight = dimdiv(self.dst_height, max([y_div for _, y_div in divs]))
        globalWorkSize, localWorkSize  = self.get_work_sizes(wwidth, wheight)

        #input image:
        iformat = pyopencl.ImageFormat(self.channel_order, pyopencl.channel_type.UNSIGNED_INT8)
        shape = (stride/4, self.src_height)
        debug("convert_image() input image format=%s, shape=%s, work size: local=%s, global=%s", iformat, shape, localWorkSize, globalWorkSize)
        if type(pixels)==str:
            #str is not a buffer, so we have to copy the data
            #alternatively, we could copy it first ourselves using this:
            #pixels = numpy.fromstring(pixels, dtype=numpy.byte).data
            #but I think this would be even slower
            flags = mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR
        else:
            flags = mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR
        iimage = pyopencl.Image(self.context, flags, iformat, shape=shape, hostbuf=pixels)

        kernelargs = [self.queue, globalWorkSize, localWorkSize,
                      iimage, numpy.int32(self.src_width), numpy.int32(self.src_height),
                      numpy.int32(self.dst_width), numpy.int32(self.dst_height),
                      self.sampler]

        #calculate plane strides and allocate output buffers:
        strides = []
        out_buffers = []
        out_sizes = []
        for i in range(3):
            x_div, y_div = divs[i]
            p_stride = roundup(self.dst_width / x_div, max(2, localWorkSize[0]))
            p_height = roundup(self.dst_height / y_div, 2)
            p_size = p_stride * p_height
            #debug("output buffer for channel %s: stride=%s, height=%s, size=%s", i, p_stride, p_height, p_size)
            out_buf = pyopencl.Buffer(self.context, mem_flags.WRITE_ONLY, p_size)
            out_buffers.append(out_buf)
            kernelargs += [out_buf, numpy.int32(p_stride)]
            strides.append(p_stride)
            out_sizes.append(p_size)

        kstart = time.time()
        debug("convert_image(%s) calling %s%s after %.1fms", image, self.kernel_function_name, tuple(kernelargs), 1000.0*(kstart-start))
        self.kernel_function(*kernelargs)
        self.queue.finish()
        #free input image:
        iimage.release()
        kend = time.time()
        debug("%s took %.1fms", self.kernel_function_name, 1000.0*(kend-kstart))

        #read back:
        pixels = []
        for i in range(3):
            out_array = numpy.empty(out_sizes[i], dtype=numpy.byte)
            pixels.append(out_array.data)
            pyopencl.enqueue_read_buffer(self.queue, out_buffers[i], out_array, is_blocking=False)
        readstart = time.time()
        debug("queue read events took %.1fms (3 planes of size %s, with strides=%s)", 1000.0*(readstart-kend), out_sizes, strides)
        self.queue.finish()
        readend = time.time()
        debug("wait for read events took %.1fms", 1000.0*(readend-readstart))
        #free output buffers:
        for out_buf in out_buffers:
            out_buf.release()
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, pixels, self.dst_format, 24, strides, planes=ImageWrapper._3_PLANES)
