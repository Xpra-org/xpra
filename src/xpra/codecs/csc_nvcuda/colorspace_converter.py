#@PydevCodeAnalysisIgnore
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#Not sure why force builtins fails on PyCUDA but not on PyOpenCL...

from xpra.log import Logger
log = Logger("csc", "cuda")

import threading
import numpy
import time

from xpra.codecs.cuda_common.cuda_context import get_pycuda_version, get_pycuda_info, driver, select_device, compile_all, reset_state, get_CUDA_function, device_info
from xpra.codecs.csc_nvcuda.CUDA_kernels import gen_rgb_to_yuv_kernels
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs


COLORSPACES_MAP = {
                   "BGRA" : ("YUV420P", "YUV422P", "YUV444P"),
                   "BGRX" : ("YUV420P", "YUV422P", "YUV444P"),
                   "RGBA" : ("YUV420P", "YUV422P", "YUV444P"),
                   "RGBX" : ("YUV420P", "YUV422P", "YUV444P"),
                   }


def gen_all_kernels():
    """
        Generates the source code for all the kernels.
        Returns a dictionary:
        * key:    (src_format, dst_format)
        * value:  (function_name, kernel_src)
    """
    kernels = {}
    for rgb_format, yuv_formats in COLORSPACES_MAP.items():
        m = gen_rgb_to_yuv_kernels(rgb_format, yuv_formats)
        kernels.update(m)
    _kernel_names_ = sorted(set([x[0] for x in kernels.values()]))
    log.info("%s csc_nvcuda kernels: %s", len(_kernel_names_), ", ".join(_kernel_names_))
    return kernels
KERNELS_MAP = {}


init_done = False
def init_module():
    """
        Pre-compiles all the kernels on all the devices
    """
    global init_done
    if init_done:
        return
    global KERNELS_MAP
    if len(KERNELS_MAP)==0:
        KERNELS_MAP = gen_all_kernels()
    for function_name, kernel_src in KERNELS_MAP.values():
        compile_all(function_name, kernel_src)
    init_done = True

def cleanup_module():
    log("csc_nvcuda.cleanup_module()")
    global init_done, KERNELS_MAP
    if not init_done:
        return
    reset_state()
    KERNELS_MAP = {}
    init_done = False


KERNEL_cubins = {}
def get_CUDA_csc_function(device_id, src_format, dst_format):
    """
        Retrieves the CUDA function to call for the given
        CSC conversion.
        Should use a pre-compiled kernel, but may compile one
        if needed.
    """
    init_module()
    k = KERNELS_MAP.get((src_format, dst_format))
    assert k is not None, "no kernel found for %s to %s" % (src_format, dst_format)
    function_name, kernel_src = k
    CUDA_function = get_CUDA_function(device_id, function_name, kernel_src)
    return function_name, CUDA_function

def roundup(n, m):
    return (n + m - 1) & ~(m - 1)



def get_type():
    return "nvcuda"

def get_version():
    return get_pycuda_version()

def get_info():
    return get_pycuda_info()


def get_input_colorspaces():
    return sorted(COLORSPACES_MAP.keys())

def get_output_colorspaces(input_colorspace):
    return sorted(COLORSPACES_MAP.get(input_colorspace))

def validate_in_out(in_colorspace, out_colorspace):
    assert in_colorspace in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    assert out_colorspace in get_output_colorspaces(in_colorspace), "invalid output colorspace: %s (must be one of %s for input %s)" % (out_colorspace, get_output_colorspaces(in_colorspace), in_colorspace)

def get_spec(in_colorspace, out_colorspace):
    validate_in_out(in_colorspace, out_colorspace)
    return codec_spec(ColorspaceConverter, codec_type=get_type(),
                      speed=100, setup_cost=10, cpu_cost=10, gpu_cost=50,
                      min_w=2, min_h=2, can_scale=False)


class ColorspaceConverter(object):
    """
        Colourspace conversion module using pycuda.
    """

    def __init__(self):
        self.init_vars()

    def clean(self):                        #@DuplicatedSignature
        log("%s.clean() context=%s", self, self.cuda_context)
        if self.cuda_context:
            self.cuda_context.detach()
            self.cuda_context = None
        self.init_vars()

    def init_vars(self):
        self.src_width = 0
        self.src_height = 0
        self.src_format = ""
        self.dst_width = 0
        self.dst_height = 0
        self.dst_format = ""
        self.device_id = 0
        self.time = 0
        self.frames = 0
        self.cuda_device = None
        self.cuda_device_info = {}
        self.pycuda_info = {}
        self.cuda_context = None
        self.max_block_sizes = 0
        self.max_grid_sizes = 0
        self.max_threads_per_block = 0
        self.kernel_function = None
        self.kernel_function_name = None
        self.convert_image_fn = None

    def init_context(self, src_width, src_height, src_format,
                           dst_width, dst_height, dst_format, speed=100):  #@DuplicatedSignature
        validate_in_out(src_format, dst_format)
        self.src_width = src_width
        self.src_height = src_height
        self.src_format = src_format
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.dst_format = dst_format
        assert self.src_width==self.dst_width and self.src_height==self.dst_height, "scaling is not supported! (%sx%s to %sx%s)" % (self.src_width, self.src_height, self.dst_width, self.dst_height)

        self.init_cuda()

    def init_cuda(self):
        self.device_id, self.cuda_device = select_device()
        log("init_cuda() device_id=%s, device info: %s", self.device_id, device_info(self.cuda_device))
        #use alias to make code easier to read:
        d = self.cuda_device
        da = driver.device_attribute
        fa = driver.function_attribute
        cf = driver.ctx_flags
        self.cuda_context = self.cuda_device.make_context(flags=cf.SCHED_AUTO | cf.MAP_HOST)
        try:
            log("init_cuda() cuda_device=%s, cuda_context=%s, thread=%s", self.cuda_device, self.cuda_context, threading.currentThread())
            #compile/get kernel:
            self.kernel_function_name, self.kernel_function = get_CUDA_csc_function(self.device_id, self.src_format, self.dst_format)

            self.max_block_sizes = d.get_attribute(da.MAX_BLOCK_DIM_X), d.get_attribute(da.MAX_BLOCK_DIM_Y), d.get_attribute(da.MAX_BLOCK_DIM_Z)
            self.max_grid_sizes = d.get_attribute(da.MAX_GRID_DIM_X), d.get_attribute(da.MAX_GRID_DIM_Y), d.get_attribute(da.MAX_GRID_DIM_Z)
            log("max_block_sizes=%s", self.max_block_sizes)
            log("max_grid_sizes=%s", self.max_grid_sizes)

            self.max_threads_per_block = self.kernel_function.get_attribute(fa.MAX_THREADS_PER_BLOCK)
            log("max_threads_per_block=%s", self.max_threads_per_block)

            #query info with device context active, and cache it for later:
            self.pycuda_info = get_pycuda_info()
            self.cuda_device_info = {
                "context.api_version"   : self.cuda_context.get_api_version(),
                "device.name"           : d.name(),
                "device.pci_bus_id"     : d.pci_bus_id(),
                }
        finally:
            self.cuda_context.pop()

        self.convert_image_fn = self.convert_image_rgb
        log("init_context(..) convert_image=%s", self.convert_image)


    def __repr__(self):
        return "csc_nvcuda(%s)" % self.get_info(False)

    def get_info(self, detailed=True):
        info = {"frames"       : self.frames,
                "src_width"    : self.src_width,
                "src_height"   : self.src_height,
                "src_format"   : self.src_format,
                "dst_width"    : self.dst_width,
                "dst_height"   : self.dst_height,
                "dst_format"   : self.dst_format}
        if detailed:
            info.update(self.pycuda_info)
            info.update(self.cuda_device_info)
            if self.frames>0 and self.time>0:
                pps = float(self.src_width) * float(self.src_height) * float(self.frames) / self.time
                info["total_time_ms"] = int(self.time*1000.0)
                info["pixels_per_second"] = int(pps)
        return info

    def __str__(self):
        if self.cuda_context is None:
            return "nvcuda(uninitialized)"
        return "nvcuda(%s %sx%s - %s %sx%s)" % (self.src_format, self.src_width, self.src_height,
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
        return  "nvcuda"


    def convert_image(self, image):
        try:
            self.cuda_context.push()
            log("convert_image(%s) calling %s with context %s pushed on thread %s", image, self.convert_image_fn, self.cuda_context, threading.currentThread())
            return self.convert_image_fn(image)
        finally:
            self.cuda_context.pop()

    def convert_image_rgb(self, image):
        global program
        start = time.time()
        iplanes = image.get_planes()
        w = image.get_width()
        h = image.get_height()
        stride = image.get_rowstride()
        pixels = image.get_pixels()
        log("convert_image(%s) planes=%s, pixels=%s, size=%s", image, iplanes, type(pixels), len(pixels))
        assert iplanes==ImageWrapper.PACKED, "must use packed format as input"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        divs = get_subsampling_divs(self.dst_format)

        #copy packed rgb pixels to GPU:
        upload_start = time.time()
        stream = driver.Stream()
        mem = numpy.frombuffer(pixels, dtype=numpy.byte)
        in_buf = driver.mem_alloc(len(pixels))
        hmem = driver.register_host_memory(mem, driver.mem_host_register_flags.DEVICEMAP)
        driver.memcpy_htod_async(in_buf, mem, stream)

        out_bufs = []
        out_strides = []
        out_sizes = []
        for i in range(3):
            x_div, y_div = divs[i]
            out_stride = roundup(self.dst_width/x_div, 4)
            out_height = roundup(self.dst_height/y_div, 2)
            out_buf, out_stride = driver.mem_alloc_pitch(out_stride, out_height, 4)
            out_bufs.append(out_buf)
            out_strides.append(out_stride)
            out_sizes.append((out_stride, out_height))
        #ensure uploading has finished:
        stream.synchronize()
        #we can now unpin the host memory:
        hmem.base.unregister()
        log("allocation and upload took %.1fms", 1000.0*(time.time() - upload_start))

        kstart = time.time()
        kargs = [in_buf, numpy.int32(stride)]
        for i in range(3):
            kargs.append(out_bufs[i])
            kargs.append(numpy.int32(out_strides[i]))
        blockw, blockh = 16, 16
        #figure out how many pixels we process at a time in each dimension:
        xdiv = max([x[0] for x in divs])
        ydiv = max([x[1] for x in divs])
        gridw = max(1, w/blockw/xdiv)
        if gridw*2*blockw<w:
            gridw += 1
        gridh = max(1, h/blockh/ydiv)
        if gridh*2*blockh<h:
            gridh += 1
        log("calling %s%s, with grid=%s, block=%s", self.kernel_function_name, tuple(kargs), (gridw, gridh), (blockw, blockh, 1))
        self.kernel_function(*kargs, block=(blockw,blockh,1), grid=(gridw, gridh))

        #we can now free the GPU source buffer:
        in_buf.free()
        kend = time.time()
        log("%s took %.1fms", self.kernel_function_name, (kend-kstart)*1000.0)
        self.frames += 1

        #copy output YUV channel data to host memory:
        read_start = time.time()
        pixels = []
        strides = []
        for i in range(3):
            x_div, y_div = divs[i]
            out_size = out_sizes[i]
            #direct full plane async copy keeping current GPU padding:
            plane = driver.aligned_empty(out_size, dtype=numpy.byte)
            driver.memcpy_dtoh_async(plane, out_bufs[i], stream)
            pixels.append(plane.data)
            stride = out_strides[min(len(out_strides)-1, i)]
            strides.append(stride)
        stream.synchronize()
        #the copying has finished, we can now free the YUV GPU memory:
        #(the host memory will be freed by GC when 'pixels' goes out of scope)
        for out_buf in out_bufs:
            out_buf.free()
        self.cuda_context.synchronize()
        read_end = time.time()
        log("strides=%s", strides)
        log("read back took %.1fms, total time: %.1f", (read_end-read_start)*1000.0, 1000.0*(time.time()-start))
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, pixels, self.dst_format, 24, strides, planes=ImageWrapper._3_PLANES)
