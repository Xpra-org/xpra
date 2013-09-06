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
log.info("PyOpenCL loaded, header version: %s", ".".join([str(x) for x in pyopencl.get_cl_header_version()]))
log.info("PyOpenCL OpenGL support: %s", pyopencl.have_gl())
log.info("found %s OpenCL platforms:", len(opencl_platforms))

def device_info(d):
    dtype = pyopencl.device_type.to_string(d.type)
    return "%s: %s (%s / %s)" % (dtype, d.name.strip(), d.version, d.opencl_c_version)
def platform_info(platform):
    return "%s (%s)" % (platform.name, platform.vendor)

selected_device = None
selected_platform = None
for platform in opencl_platforms:
    devices = platform.get_devices()
    log.info("* %s - %s devices:", platform_info(platform), len(devices))
    for d in devices:
        p = "-"
        if d.available and d.compiler_available and d.get_info(pyopencl.device_info.IMAGE_SUPPORT):
            p = "+"
            dtype = pyopencl.device_type.to_string(d.type)
            if selected_device is None and dtype==PREFERRED_DEVICE_TYPE and \
                (len(PREFERRED_DEVICE_NAME)==0 or d.name.find(PREFERRED_DEVICE_NAME)>=0) and \
                (len(PREFERRED_DEVICE_PLATFORM)==0 or str(platform.name).find(PREFERRED_DEVICE_PLATFORM)>=0):
                selected_device = d
                selected_platform = platform
        log.info(" %s %s", p, device_info(d))

if selected_device:
    log.info("using platform: %s", platform_info(selected_platform))
    log.info("using device: %s", device_info(selected_device))
    debug("max_work_group_size=%s", selected_device.max_work_group_size)
    debug("max_work_item_dimensions=%s", selected_device.max_work_item_dimensions)
    debug("max_work_item_sizes=%s", selected_device.max_work_item_sizes)


context = None
def init_context():
    global context, selected_device,selected_platform
    if context is not None:
        return
    if selected_device:
        context = pyopencl.Context([selected_device])
    else:
        context = pyopencl.create_some_context(interactive=False)
    assert context is not None


KERNELS_DEFS = {}
def gen_kernels():
    global context, KERNELS_DEFS
    from xpra.codecs.csc_opencl.opencl_kernels import gen_yuv_to_rgb_kernels, gen_rgb_to_yuv_kernels
    #TODO: we could handle other formats here and manage the channel swap ourselves
    #(most of the code to do this is already implemented in the kernel generators)
    def has_image_format(image_formats, channel_order, channel_type):
        for iformat in image_formats:
            if iformat.channel_order==channel_order and iformat.channel_data_type==channel_type:
                return True
        return False
    IN_CHANNEL_ORDER = {
                      "RGBA"    : pyopencl.channel_order.RGBA,
                      "RGBX"    : pyopencl.channel_order.RGBA,
                      "BGRA"    : pyopencl.channel_order.BGRA,
                      "BGRX"    : pyopencl.channel_order.BGRA,
                      "RGBX"    : pyopencl.channel_order.RGBx,
                      "RGB"     : pyopencl.channel_order.RGB,
                      }

    #for YUV to RGB support we need to be able to handle the channel_order in WRITE_ONLY mode:
    YUV_to_RGB_KERNELS = {}
    sif = pyopencl.get_supported_image_formats(context, mem_flags.WRITE_ONLY,  pyopencl.mem_object_type.IMAGE2D)
    debug("get_supported_image_formats(WRITE_ONLY, IMAGE2D)=%s", sif)
    for rgb_mode, channel_order in IN_CHANNEL_ORDER.items():
        if not has_image_format(sif, channel_order, pyopencl.channel_type.UNSIGNED_INT8):
            debug("YUV 2 RGB: channel order %s is not supported in WRITE_ONLY mode", rgb_mode)
            continue
        kernels = gen_yuv_to_rgb_kernels(rgb_modes=["RGBX"])
        for key, k_def in kernels.items():
            src, dst = key
            kname, ksrc = k_def
            #note: "RGBX" isn't actually used (yet?)
            YUV_to_RGB_KERNELS[(src, rgb_mode)] = (kname, "RGBX", channel_order, ksrc)
    debug("YUV 2 RGB conversions=%s", sorted(YUV_to_RGB_KERNELS.keys()))
    #debug("YUV 2 RGB kernels=%s", YUV_to_RGB_KERNELS)
    debug("YUV 2 RGB kernels=%s", set([x[0] for x in YUV_to_RGB_KERNELS.values()]))

    #for RGB to YUV support we need to be able to handle the channel_order,
    #with READ_ONLY and both with COPY_HOST_PTR and USE_HOST_PTR since we
    #do not know in advance which one we can use..
    #TODO: enable channel_order anyway and use COPY as fallback?
    RGB_to_YUV_KERNELS = {}
    sif_copy = pyopencl.get_supported_image_formats(context, mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR,  pyopencl.mem_object_type.IMAGE2D)
    debug("get_supported_image_formats(READ_ONLY | COPY_HOST_PTR, IMAGE2D)=%s", sif)
    sif_use = pyopencl.get_supported_image_formats(context, mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR,  pyopencl.mem_object_type.IMAGE2D)
    debug("get_supported_image_formats(READ_ONLY | USE_HOST_PTR, IMAGE2D)=%s", sif)
    if not has_image_format(sif_copy, pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8) or \
       not has_image_format(sif_use, pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8):
        log.error("cannot convert to yuv without support for R channel!")
    else:
        for rgb_mode, channel_order in IN_CHANNEL_ORDER.items():
            errs = []
            if not has_image_format(sif_copy, channel_order, pyopencl.channel_type.UNSIGNED_INT8):
                errs.append("COPY_HOST_PTR")
            if not has_image_format(sif_use, channel_order, pyopencl.channel_type.UNSIGNED_INT8):
                errs.append("USE_HOST_PTR")
            if len(errs)>0:
                debug("RGB 2 YUV: channel order %s is not supported in READ_ONLY mode(s): %s", rgb_mode, " or ".join(errs))
                continue
            #we hardcode RGB here since we currently handle byteswapping
            #via the channel_order only for now:
            kernels = gen_rgb_to_yuv_kernels(rgb_modes=["RGB"])
            #debug("kernels(%s)=%s", rgb_mode, kernels)
            for key, k_def in kernels.items():
                src, dst = key
                kname, ksrc = k_def
                #note: "RGBX" isn't actually used (yet?)
                RGB_to_YUV_KERNELS[(rgb_mode, dst)] = (kname, "RGB", channel_order, ksrc)
    debug("RGB 2 YUV conversions=%s", sorted(RGB_to_YUV_KERNELS.keys()))
    #debug("RGB 2 YUV kernels=%s", RGB_to_YUV_KERNELS)
    debug("RGB 2 YUV kernels=%s", set([x[0] for x in RGB_to_YUV_KERNELS.values()]))

    KERNELS_DEFS = RGB_to_YUV_KERNELS.copy()
    KERNELS_DEFS.update(YUV_to_RGB_KERNELS)
    debug("all conversions=%s", KERNELS_DEFS.keys())
    #work out the unique kernels we have generated (kname -> ksrc)
    NAMES_TO_KERNELS = {}
    for name, _, _, kernel in KERNELS_DEFS.values():
        NAMES_TO_KERNELS[name] = kernel
    return NAMES_TO_KERNELS


program = None
def build_kernels():
    global program
    if program is not None:
        return
    init_context()
    NAMES_TO_KERNELS = gen_kernels()
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            log.info("building %s kernels: %s", len(NAMES_TO_KERNELS), ", ".join(NAMES_TO_KERNELS.keys()))
            program = pyopencl.Program(context, "\n".join(NAMES_TO_KERNELS.values()))
            program.build()
            log.debug("all warnings:%s", "\n* ".join([str(x) for x in w]))
            build_warnings = [x for x in w if x.category==pyopencl.CompilerWarning]
            if len(build_warnings)>0:
                debug("%s build warnings:", len(build_warnings))
                for x in build_warnings:
                    debug(str(x))
    except Exception, e:
        error("cannot build the OpenCL program: %s", e, exc_info=True)
        raise ImportError("cannot build the OpenCL program: %s" % e)


def roundup(n, m):
    return (n + m - 1) & ~(m - 1)

def dimdiv(dim, div):
    #when we divide a dimensions by the subsampling
    #we want to round up so as to include the last
    #pixel when we hit odd dimensions
    return roundup(dim/div, div)


from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs


def get_type():
    return "opencl"

def get_version():
    return pyopencl.version.VERSION_TEXT

def get_input_colorspaces():
    build_kernels()
    return [src for (src, _) in KERNELS_DEFS.keys()]

def get_output_colorspaces(input_colorspace):
    build_kernels()
    return [dst for (src, dst) in KERNELS_DEFS.keys() if src==input_colorspace]

def validate_in_out(in_colorspace, out_colorspace):
    assert in_colorspace in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    assert out_colorspace in get_output_colorspaces(in_colorspace), "invalid output colorspace: %s (must be one of %s for input %s)" % (out_colorspace, get_output_colorspaces(in_colorspace), in_colorspace)

def get_spec(in_colorspace, out_colorspace):
    validate_in_out(in_colorspace, out_colorspace)
    return codec_spec(ColorspaceConverter, codec_type=get_type(), speed=100, setup_cost=10, cpu_cost=10, gpu_cost=50, min_w=128, min_h=128, can_scale=False)


class ColorspaceConverter(object):

    def __init__(self):
        build_kernels()
        self.src_width = 0
        self.src_height = 0
        self.src_format = ""
        self.dst_width = 0
        self.dst_height = 0
        self.dst_format = ""
        self.time = 0
        self.frames = 0
        self.queue = None
        self.channel_order = None
        self.kernel_function = None
        self.kernel_function_name = None

    def init_context(self, src_width, src_height, src_format,
                           dst_width, dst_height, dst_format, csc_speed=100):  #@DuplicatedSignature
        global context
        validate_in_out(src_format, dst_format)
        self.src_width = src_width
        self.src_height = src_height
        self.src_format = src_format
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.dst_format = dst_format
        self.queue = pyopencl.CommandQueue(context)
        k_def = KERNELS_DEFS.get((src_format, dst_format))
        assert k_def, "no kernel found for %s to %s" % (src_format, dst_format)
        self.kernel_function_name, _, self.channel_order, src = k_def
        if src_format.endswith("P"):
            #yuv 2 rgb:
            self.convert_image = self.convert_image_yuv
        else:
            #rgb 2 yuv:
            self.convert_image = self.convert_image_rgb
        debug("init_context(..) kernel source=%s", src)
        self.kernel_function = getattr(program, self.kernel_function_name)
        debug("init_context(..) kernel_function=%s", self.kernel_function)
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
            return "opencl(uninitialized)"
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
        if self.queue:
            self.queue.finish()
            self.queue = None
            self.kernel_function = None

    def convert_image(self, image):
        #we override this method during init_context
        raise Exception("not initialized!")


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


    def convert_image_yuv(self, image):
        global program
        start = time.time()
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        strides = image.get_rowstride()
        pixels = image.get_pixels()
        assert iplanes==ImageWrapper._3_PLANES, "we only handle planar data as input!"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        assert len(strides)==len(pixels)==3, "invalid number of planes or strides (should be 3)"

        #adjust work dimensions for subsampling:
        #(we process N pixels at a time in each dimension)
        divs = get_subsampling_divs(self.src_format)
        wwidth = dimdiv(width, max(x_div for x_div, _ in divs))
        wheight = dimdiv(height, max(y_div for _, y_div in divs))
        globalWorkSize, localWorkSize  = self.get_work_sizes(wwidth, wheight)

        kernelargs = [self.queue, globalWorkSize, localWorkSize]

        #output image:
        oformat = pyopencl.ImageFormat(self.channel_order, pyopencl.channel_type.UNORM_INT8)
        oimage = pyopencl.Image(context, mem_flags.WRITE_ONLY, oformat, shape=(width, height))

        iformat = pyopencl.ImageFormat(pyopencl.channel_order.R, pyopencl.channel_type.UNSIGNED_INT8)
        #convert input buffers to numpy arrays then OpenCL Buffers:
        for i in range(3):
            _, y_div = divs[i]
            plane = pixels[i]
            if type(plane)==str:
                flags = mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR
            else:
                flags = mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR
            shape = strides[i], height/y_div
            iimage = pyopencl.Image(context, flags, iformat, shape=shape, hostbuf=plane)
            kernelargs.append(iimage)
            kernelargs.append(numpy.int32(strides[i]))

        kernelargs += [numpy.int32(width), numpy.int32(height), oimage]

        kstart = time.time()
        debug("convert_image(%s) calling %s%s after %.1fms", image, self.kernel_function_name, tuple(kernelargs), 1000.0*(kstart-start))
        self.kernel_function(*kernelargs)
        kend = time.time()
        debug("%s took %.1fms", self.kernel_function, 1000.0*(kend-kstart))

        out_array = numpy.empty(width*height*4, dtype=numpy.byte)
        pyopencl.enqueue_read_image(self.queue, oimage, origin=(0, 0), region=(width, height), hostbuf=out_array, is_blocking=True)
        self.queue.finish()
        debug("readback took %.1fms", 1000.0*(time.time()-kend))
        self.time += time.time()-start
        self.frames += 1
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, out_array.data, self.dst_format, 24, strides, planes=ImageWrapper.PACKED_RGB)


    def convert_image_rgb(self, image):
        global program
        start = time.time()
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        stride = image.get_rowstride()
        pixels = image.get_pixels()
        #debug("convert_image(%s) planes=%s, pixels=%s, size=%s", image, iplanes, type(pixels), len(pixels))
        assert iplanes==ImageWrapper.PACKED_RGB, "we only handle packed rgb as input!"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)

        #adjust work dimensions for subsampling:
        #(we process N pixels at a time in each dimension)
        divs = get_subsampling_divs(self.dst_format)
        wwidth = dimdiv(width, max([x_div for x_div, _ in divs]))
        wheight = dimdiv(height, max([y_div for _, y_div in divs]))
        globalWorkSize, localWorkSize  = self.get_work_sizes(wwidth, wheight)

        #input image:
        bpp = len(self.src_format)
        iformat = pyopencl.ImageFormat(self.channel_order, pyopencl.channel_type.UNSIGNED_INT8)
        shape = (stride/bpp, height)
        debug("convert_image() input image format=%s, shape=%s, work size: local=%s, global=%s", iformat, shape, localWorkSize, globalWorkSize)
        if type(pixels)==str:
            #str is not a buffer, so we have to copy the data
            #alternatively, we could copy it first ourselves using this:
            #pixels = numpy.fromstring(pixels, dtype=numpy.byte).data
            #but I think this would be even slower
            flags = mem_flags.READ_ONLY | mem_flags.COPY_HOST_PTR
        else:
            flags = mem_flags.READ_ONLY | mem_flags.USE_HOST_PTR
        iimage = pyopencl.Image(context, flags, iformat, shape=shape, hostbuf=pixels)

        kernelargs = [self.queue, globalWorkSize, localWorkSize, iimage, numpy.int32(width), numpy.int32(height)]

        #calculate plane strides and allocate output buffers:
        strides = []
        out_buffers = []
        out_sizes = []
        for i in range(3):
            x_div, y_div = divs[i]
            p_stride = roundup(width / x_div, max(2, localWorkSize[0]))
            p_height = roundup(height / y_div, 2)
            p_size = p_stride * p_height
            #debug("output buffer for channel %s: stride=%s, height=%s, size=%s", i, p_stride, p_height, p_size)
            out_buf = pyopencl.Buffer(context, mem_flags.WRITE_ONLY, p_size)
            out_buffers.append(out_buf)
            kernelargs += [out_buf, numpy.int32(p_stride)]
            strides.append(p_stride)
            out_sizes.append(p_size)

        kstart = time.time()
        debug("convert_image(%s) calling %s%s after %.1fms", image, self.kernel_function_name, tuple(kernelargs), 1000.0*(kstart-start))
        self.kernel_function(*kernelargs)
        kend = time.time()
        debug("%s took %.1fms", self.kernel_function_name, 1000.0*(kend-kstart))

        #read back:
        pixels = []
        read_events = []
        for i in range(3):
            out_array = numpy.empty(out_sizes[i], dtype=numpy.byte)
            pixels.append(out_array.data)
            read = pyopencl.enqueue_read_buffer(self.queue, out_buffers[i], out_array, is_blocking=False)
            read_events.append(read)
        readstart = time.time()
        debug("queue read events took %.1fms (3 planes of size %s, with strides=%s)", 1000.0*(readstart-kend), out_sizes, strides)
        pyopencl.wait_for_events(read_events)
        self.queue.finish()
        readend = time.time()
        debug("wait for read events took %.1fms", 1000.0*(readend-readstart))
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, pixels, self.dst_format, 24, strides, planes=ImageWrapper._3_PLANES)
