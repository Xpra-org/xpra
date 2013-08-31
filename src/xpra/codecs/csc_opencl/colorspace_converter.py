# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_OPENCL_DEBUG")
error = log.error

import os
import warnings
import numpy
assert bytearray
import pyopencl             #@UnresolvedImport

PREFERRED_DEVICE_TYPE = os.environ.get("XPRA_OPENCL_DEVICE_TYPE", "GPU")
PREFERRED_DEVICE_NAME = os.environ.get("XPRA_OPENCL_DEVICE_NAME", "")
PREFERRED_DEVICE_PLATFORM = os.environ.get("XPRA_OPENCL_PLATFORM", "")


opencl_platforms = pyopencl.get_platforms()
if len(opencl_platforms)==0:
    raise ImportError("no OpenCL platforms found!")
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

context = None
try:
    if selected_device:
        log.info("using platform: %s", platform_info(selected_platform))
        log.info("using device: %s", device_info(selected_device))
        debug("max_work_group_size=%s", selected_device.max_work_group_size)
        debug("max_work_item_dimensions=%s", selected_device.max_work_item_dimensions)
        debug("max_work_item_sizes=%s", selected_device.max_work_item_sizes)
        context = pyopencl.Context([selected_device])
    else:
        context = pyopencl.create_some_context(interactive=False)
    assert context is not None
except Exception, e:
    error("cannot create an OpenCL context: %s", e, exc_info=True)
    raise ImportError("cannot create an OpenCL context: %s" % e)

from xpra.codecs.csc_opencl.opencl_kernels import RGB_2_YUV_KERNELS, YUV_2_RGB_KERNELS
program = None
try:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        all_kernels = "\n".join(YUV_2_RGB_KERNELS.values() + RGB_2_YUV_KERNELS.values())
        program = pyopencl.Program(context, all_kernels)
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


from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs

#YUV formats we have generated kernels for:
COLORSPACES_SRC_YUV = sorted(list(set([src for (src, dst) in YUV_2_RGB_KERNELS.keys()])))
#RGB: limited to the formats OpenCL supports:
#CL_RGBA, CL_BGRA, CL_ARGB, CL_RGB, CL_RGBx
#(but we add BGRX since we just ignore the channel anyway)
#disabled because of problems with: RGB, RGBx
COLORSPACES_SRC_RGB = ["RGBA", "BGRA", "RGBX", "BGRX"]

COLORSPACES_SRC = COLORSPACES_SRC_YUV + COLORSPACES_SRC_RGB


CHANNEL_ORDER = {
                  "RGBA"    : pyopencl.channel_order.RGBA,
                  "RGBX"    : pyopencl.channel_order.RGBA,
                  "BGRA"    : pyopencl.channel_order.BGRA,
                  "BGRX"    : pyopencl.channel_order.BGRA,
                  "RGBX"    : pyopencl.channel_order.RGBA,
                  #"RGB"     : pyopencl.channel_order.RGB,
                  }


def get_version():
    return pyopencl.version.VERSION_TEXT

def get_input_colorspaces():
    return COLORSPACES_SRC

def get_output_colorspaces(input_colorspace):
    if input_colorspace in COLORSPACES_SRC_RGB:
        return RGB_2_YUV_KERNELS.keys()
    return [dst for (src, dst) in YUV_2_RGB_KERNELS.keys() if src==input_colorspace]

def validate_in_out(in_colorspace, out_colorspace):
    assert in_colorspace in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    assert out_colorspace in get_output_colorspaces(in_colorspace), "invalid output colorspace: %s (must be one of %s for input %s)" % (out_colorspace, get_output_colorspaces(in_colorspace), in_colorspace)

def get_spec(in_colorspace, out_colorspace):
    validate_in_out(in_colorspace, out_colorspace)
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    return codec_spec(ColorspaceConverter, speed=100, setup_cost=10, cpu_cost=10, gpu_cost=50, min_w=16, min_h=16, can_scale=False)


class ColorspaceConverter(object):

    def __init__(self):
        self.src_width = 0
        self.src_height = 0
        self.src_format = ""
        self.dst_width = 0
        self.dst_height = 0
        self.dst_format = ""
        self.time = 0
        self.frames = 0
        self.queue = None
        self.kernel_function = None

    def init_context(self, src_width, src_height, src_format,
                           dst_width, dst_height, dst_format):    #@DuplicatedSignature
        global context
        validate_in_out(src_format, dst_format)
        self.src_width = src_width
        self.src_height = src_height
        self.src_format = src_format
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.dst_format = dst_format
        self.queue = pyopencl.CommandQueue(context)
        if src_format in COLORSPACES_SRC_RGB:
            #rgb 2 yuv:
            src = RGB_2_YUV_KERNELS[dst_format]
            kernel_name = "RGB_2_%s" % dst_format
            self.convert_image = self.convert_image_rgb
        else:
            #yuv 2 rgb:
            src = YUV_2_RGB_KERNELS[(src_format, dst_format)]
            kernel_name =  "%s_2_%s" % (src_format, dst_format)
            self.convert_image = self.convert_image_yuv
        debug("init_context(..) kernel source=%s", src)
        self.kernel_function = getattr(program, kernel_name)
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

    def __dealloc__(self):                  #@DuplicatedSignature
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


    def convert_image_yuv(self, image):
        global program
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        strides = image.get_rowstride()
        pixels = image.get_pixels()
        debug("convert_image(%s) planes=%s", image, iplanes)
        assert iplanes==ImageWrapper._3_PLANES, "we only handle planar data as input!"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        assert len(strides)==len(pixels)==3, "invalid number of planes or strides (should be 3)"
        mf = pyopencl.mem_flags

        #ensure the local and global work size are valid, see:
        #http://stackoverflow.com/questions/3957125/questions-about-global-and-local-work-size
        chunk = 64
        while chunk**2>selected_device.max_work_group_size or chunk>min(selected_device.max_work_item_sizes):
            chunk /= 2
        localWorkSize = (chunk, chunk)
        globalWorkSize = (roundup(width, localWorkSize[0]), roundup(height, localWorkSize[1]))

        kernelargs = [self.queue, globalWorkSize, localWorkSize]

        #output image:
        oformat = pyopencl.ImageFormat(pyopencl.channel_order.RGBA, pyopencl.channel_type.UNORM_INT8)
        oimage = pyopencl.Image(context, mf.WRITE_ONLY, oformat, shape=(width, height))

        #convert input buffers to numpy arrays then OpenCL Buffers:
        for i in range(3):
            in_array = numpy.frombuffer(pixels[i], dtype=numpy.byte)
            flags = mf.READ_ONLY | mf.COPY_HOST_PTR
            in_buf = pyopencl.Buffer(context, flags, hostbuf=in_array)
            kernelargs.append(in_buf)
            kernelargs.append(numpy.int32(strides[i]))
        kernelargs += [numpy.int32(width), numpy.int32(height), oimage]

        debug("convert_image(%s) calling %s%s", image, self.kernel_function, kernelargs)
        self.kernel_function(*kernelargs)
        out_array = numpy.empty(width*height*4, dtype=numpy.byte)
        read = pyopencl.enqueue_read_image(self.queue, oimage, origin=(0, 0), region=(width, height), hostbuf=out_array)
        read.wait()
        self.queue.finish()
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, out_array.data, self.dst_format, 24, strides, planes=ImageWrapper.PACKED_RGB)


    def convert_image_rgb(self, image):
        global program
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        stride = image.get_rowstride()
        pixels = image.get_pixels()
        debug("convert_image(%s) planes=%s, pixels=%s, size=%s", image, iplanes, type(pixels), len(pixels))
        assert iplanes==ImageWrapper.PACKED_RGB, "we only handle packed rgb as input!"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        mf = pyopencl.mem_flags
        divs = get_subsampling_divs(self.dst_format)
        #the x and y divs also tell us how many pixels we process at a time:
        x_unit = max([x_div for x_div, _ in divs])
        y_unit = max([y_div for _, y_div in divs])

        #ensure the local and global work size are valid, see:
        #http://stackoverflow.com/questions/3957125/questions-about-global-and-local-work-size
        chunk = 64
        while chunk**2>selected_device.max_work_group_size or chunk>min(selected_device.max_work_item_sizes):
            chunk /= 2
        localWorkSize = (chunk, chunk)
        globalWorkSize = (roundup(width/x_unit, localWorkSize[0]), roundup(height/y_unit, localWorkSize[1]))

        #input image:
        bpp = len(self.src_format)
        #UNSIGNED_INT8 / UNORM_INT8
        co = CHANNEL_ORDER[self.src_format]
        iformat = pyopencl.ImageFormat(co, pyopencl.channel_type.UNSIGNED_INT8)
        shape = (stride/bpp, height)
        debug("convert_image() input image format=%s, shape=%s", iformat, shape)
        if type(pixels)==str:
            flags = mf.READ_ONLY | mf.COPY_HOST_PTR
        else:
            flags = mf.READ_ONLY | mf.USE_HOST_PTR
        iimage = pyopencl.Image(context, flags, iformat, shape=shape, hostbuf=pixels)

        kernelargs = [self.queue, globalWorkSize, localWorkSize, iimage, numpy.int32(width), numpy.int32(height)]

        #calculate plane strides and allocate output buffers:
        strides = []
        out_buffers = []
        out_sizes = []
        for i in range(3):
            x_div, y_div = divs[i]
            p_stride = roundup(width / x_div, max(2, chunk/2))
            p_height = roundup(height / y_div, 2)
            p_size = p_stride * p_height
            #debug("output buffer for channel %s: stride=%s, height=%s, size=%s", i, p_stride, p_height, p_size)
            out_buf = pyopencl.Buffer(context, mf.WRITE_ONLY, p_size)
            out_buffers.append(out_buf)
            kernelargs += [out_buf, numpy.int32(p_stride)]
            strides.append(p_stride)
            out_sizes.append(p_size)

        debug("convert_image(%s) calling %s%s", image, self.kernel_function, kernelargs)
        self.kernel_function(*kernelargs)

        #read back:
        pixels = []
        read_events = []
        for i in range(3):
            out_array = numpy.zeros(out_sizes[i], dtype=numpy.byte)
            pixels.append(out_array.data)
            read = pyopencl.enqueue_read_buffer(self.queue, out_buffers[i], out_array)
            read_events.append(read)
        #for i in range(3):
        #    read_events[i].wait()
        pyopencl.wait_for_events(read_events)
        self.queue.finish()
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, pixels, self.dst_format, 24, strides, planes=ImageWrapper._3_PLANES)
