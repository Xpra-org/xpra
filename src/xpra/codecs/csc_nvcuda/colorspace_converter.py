# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_CUDA_DEBUG")
error = log.error

import numpy
import time
import ctypes
import sys
assert bytearray
import pycuda               #@UnresolvedImport
from pycuda import driver   #@UnresolvedImport
driver.init()

def log_sys_info():
    log.info("PyCUDA version=%s", ".".join([str(x) for x in driver.get_version()]))
    log.info("PyCUDA driver version=%s", driver.get_driver_version())

def device_info(d):
    return "%s @ %s" % (d.name(), d.pci_bus_id())

def select_device():
    ngpus = driver.Device.count()
    log.info("PyCUDA found %s devices:", ngpus)
    device = None
    for i in range(ngpus):
        d = driver.Device(i)
        host_mem = d.get_attribute(driver.device_attribute.CAN_MAP_HOST_MEMORY)
        pre = "-"
        if host_mem:
            pre = "+"
        log.info(" %s %s", pre, device_info(d))
        #debug("CAN_MAP_HOST_MEMORY=%s", host_mem)
        #attr = d.get_attributes()
        #debug("compute_capability=%s, attributes=%s", d.compute_capability(), attr)
        if host_mem and device is None:
            device = d
    return device
assert select_device() is not None

context = None
context_wrapper = None
#ensure we cleanup:
class CudaContextWrapper(object):

    def __init__(self, context):
        self.context = context

    def __del__(self):
        self.cleanup()
    
    def cleanup(self):
        if self.context:
            self.context.detach()
            self.context = None

def init_context():
    global context, context_wrapper
    log_sys_info()
    device = select_device()
    context = device.make_context(flags=driver.ctx_flags.SCHED_YIELD | driver.ctx_flags.MAP_HOST)
    debug("testing with context=%s", context)
    debug("api version=%s", context.get_api_version())
    free, total = driver.mem_get_info()
    debug("using device %s",  device_info(device))
    debug("memory: free=%sMB, total=%sMB",  int(free/1024/1024), int(total/1024/1024))
    #context.pop()
    context_wrapper = CudaContextWrapper(context)
    context.pop()

def find_lib(basename):
    try:
        if sys.platform == "win32":
            libname = basename+".dll"
        else:
            libname = basename+".so"
        return ctypes.cdll.LoadLibrary(libname)
    except Exception, e:
        debug("could not find %s: %s", basename, e)
        return None

_NPP_LIBRARY_NAMES = ["libnppi",    #CUDA5.5
                      "libnpp"]     #CUDA5.0
_NPP_LIBRARIES = []
for name in _NPP_LIBRARY_NAMES:
    lib = find_lib(name)
    if lib:
        _NPP_LIBRARIES.append(lib)
if len(_NPP_LIBRARIES)==0:
    raise ImportError("failed to load npp library - check your library path")

#try to get the npp version:
class NppLibraryVersion(ctypes.Structure):
    _fields_ = [("major", ctypes.c_int),
                ("minor", ctypes.c_int),
                ("build", ctypes.c_int)]
try:
    nppGetLibVersion = None
    for lib in _NPP_LIBRARIES:
        if hasattr(lib, "nppGetLibVersion"):
            nppGetLibVersion = getattr(lib, "nppGetLibVersion")
    if nppGetLibVersion:
        nppGetLibVersion.argtypes = []
        nppGetLibVersion.restype = ctypes.POINTER(NppLibraryVersion)
        v = nppGetLibVersion().contents
        log.info("found npp library version %s.%s.%s", v.major, v.minor, v.build)
except:
    log.warn("error getting npp version", exc_info=True)


class NppiSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int),
                ("height", ctypes.c_int)]

def Npp8u_p(buf):
    return ctypes.cast(int(buf), ctypes.c_void_p)

RGB_to_YUV444P_argtypes = [ctypes.c_void_p, ctypes.c_int, (ctypes.c_void_p)*3, ctypes.c_int, NppiSize]
RGB_to_YUV42xP_argtypes = [ctypes.c_void_p, ctypes.c_int, (ctypes.c_void_p)*3, (ctypes.c_int)*3, NppiSize]

YUV444P_to_RGB_argtypes = [(ctypes.c_void_p)*3, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, NppiSize]
YUV42xP_to_RGB_argtypes = [(ctypes.c_void_p)*3, (ctypes.c_int)*3, ctypes.c_void_p, ctypes.c_int, NppiSize]
CONSTANT_ALPHA = ctypes.c_uint8


COLORSPACES_MAP_STR  = {
        #("RGBX",    "YUV444P")  : ("nppiRGBToYCbCr_8u_C3P3R",       RGB_to_YUV444P_argtypes),
        ("RGBA",    "YUV444P")  : ("nppiRGBToYCbCr_8u_AC4P3R",      RGB_to_YUV444P_argtypes),
        #("YUV444P", "RGB")      : ("nppiYCbCrToRGB_8u_P3C3R",       YUV444P_to_RGB_argtypes),
        #("YUV444P", "BGR")      : ("nppiYCbCrToBGR_8u_P3C3R",       YUV444P_to_RGB_argtypes),
        ("YUV444P", "RGBX")     : ("nppiYCbCrToRGB_8u_P3C4R",       YUV444P_to_RGB_argtypes+[CONSTANT_ALPHA]),
        ("YUV444P", "BGRX")     : ("nppiYCbCrToBGR_8u_P3C4R",       YUV444P_to_RGB_argtypes+[CONSTANT_ALPHA]),
        #BGR / BGRA: need nppiSwap(Channels before one of the above
        #("RGBX",    "YUV422P")  : ("nppiRGBToYCbCr422_8u_C3P3R",    RGB_to_YUV42xP_argtypes),
        #("BGRX",    "YUV422P")  : ("nppiBGRToYCbCr422_8u_C3P3R",    RGB_to_YUV42xP_argtypes),
        ("BGRX",    "YUV422P")  : ("nppiBGRToYCbCr422_8u_AC4P3R",   RGB_to_YUV42xP_argtypes),
        
        #("YUV422P", "RGB")      : ("nppiYCbCr422ToRGB_8u_P3C3R",    YUV42xP_to_RGB_argtypes),
        #("YUV422P", "BGR")      : ("nppiYCbCr422ToBGR_8u_P3C3R",    YUV42xP_to_RGB_argtypes),
        #YUV420P:
        #("RGBX",    "YUV420P")  : ("nppiRGBToYCbCr420_8u_C3P3R",    RGB_to_YUV42xP_argtypes),
        #("BGRX",    "YUV420P")  : ("nppiBGRToYCbCr420_8u_C3P3R",    RGB_to_YUV42xP_argtypes),
        ("RGBX",    "YUV420P")  : ("nppiRGBToYCrCb420_8u_AC4P3R",   RGB_to_YUV42xP_argtypes),
        ("BGRX",    "YUV420P")  : ("nppiBGRToYCbCr420_8u_AC4P3R",   RGB_to_YUV42xP_argtypes),
        #("YUV420P", "RGB")      : ("nppiYCbCr420ToRGB_8u_P3C3R",    YUV42xP_to_RGB_argtypes),
        #("YUV420P", "BGR")      : ("nppiYCbCr420ToBGR_8u_P3C3R",    YUV42xP_to_RGB_argtypes),
        #("YUV420P", "RGBX")     : ("nppiYCrCb420ToRGB_8u_P3C4R",    YUV42xP_to_RGB_argtypes),
        #("YUV420P", "BGRX")     : ("nppiYCbCr420ToBGR_8u_P3C4R",    YUV42xP_to_RGB_argtypes),
        }
#ie:
#BGR to YUV420P:
#NppStatus nppiBGRToYCbCr420_8u_C3P3R (const Npp8u *pSrc, int nSrcStep, Npp8u *pDst[3], int rDstStep[3], NppiSize oSizeROI)
#pSrc Source-Image Pointer.
#nSrcStep Source-Image Line Step.
#pDst Destination-Planar-Image Pointer Array.
#rDstStep Destination-Planar-Image Line Step Array.
#oSizeROI Region-of-Interest (ROI). (struct with width and height)
#Returns:
#Image Data Related Error Codes, ROI Related Error Codes

#For YUV444P:
#NppStatus nppiRGBToYCbCr_8u_C3P3R(const Npp8u * pSrc, int nSrcStep, Npp8u * pDst[3], int nDstStep, NppiSize oSizeROI);
#(only one nDstStep!

#YUV420P to RGB:
#NppStatus nppiYCbCrToRGB_8u_P3C3R(const Npp8u * const pSrc[3], int nSrcStep, Npp8u * pDst, int nDstStep, NppiSize oSizeROI);
#YUV444P to RGB:
#NppStatus nppiYCrCb420ToRGB_8u_P3C4R(const Npp8u * const pSrc[3],int rSrcStep[3], Npp8u * pDst, int nDstStep, NppiSize oSizeROI);
#Those with alpha add:
#Npp8u nAval


NPP_NO_OPERATION_WARNING = 1
NPP_DIVIDE_BY_ZERO_WARNING = 6
NPP_AFFINE_QUAD_INCORRECT_WARNING = 28
NPP_WRONG_INTERSECTION_ROI_WARNING = 29
NPP_WRONG_INTERSECTION_QUAD_WARNING = 30
NPP_DOUBLE_SIZE_WARNING = 35
NPP_MISALIGNED_DST_ROI_WARNING = 10000

WARNINGS = {
    NPP_NO_OPERATION_WARNING :  "Indicates that no operation was performed",
    NPP_DIVIDE_BY_ZERO_WARNING: "Divisor is zero however does not terminate the execution",
    NPP_AFFINE_QUAD_INCORRECT_WARNING:  "Indicates that the quadrangle passed to one of affine warping functions doesn't have necessary properties. First 3 vertices are used, the fourth vertex discarded",
    NPP_WRONG_INTERSECTION_ROI_WARNING: "The given ROI has no interestion with either the source or destination ROI. Thus no operation was performed",
    NPP_WRONG_INTERSECTION_QUAD_WARNING:"The given quadrangle has no intersection with either the source or destination ROI. Thus no operation was performed",
    NPP_DOUBLE_SIZE_WARNING:    "Image size isn't multiple of two. Indicates that in case of 422/411/420 sampling the ROI width/height was modified for proper processing",
    NPP_MISALIGNED_DST_ROI_WARNING: "Speed reduction due to uncoalesced memory accesses warning"
    }
NPP_STEP_ERROR = -14
NPP_NOT_EVEN_STEP_ERROR = -108

ERRORS = {
    NPP_STEP_ERROR : "Step is less or equal zero",
    NPP_NOT_EVEN_STEP_ERROR :   "Step value is not pixel multiple",
          }


YUV_INDEX_TO_PLANE = {
                      0 : "Y",
                      1 : "U",
                      2 : "V"
                      }


def roundup(n, m):
    return (n + m - 1) & ~(m - 1)


COLORSPACES_MAP = {}
for k, f_def in COLORSPACES_MAP_STR.items():
    fn, argtypes = f_def
    try:
        for lib in _NPP_LIBRARIES:
            if hasattr(lib, fn):
                cfn = getattr(lib, fn)
                debug("found %s for %s in %s: %s", fn, k, lib, cfn)
                COLORSPACES_MAP[k] = (fn, cfn)
                #set argument types and return type:
                cfn.restype = ctypes.c_int
                cfn.argtypes = argtypes
    except:
        log.error("could not load '%s', conversion disabled: %s", fn, k)


def get_type():
    return "nvcuda"

def get_version():
    return pycuda.VERSION_TEXT

def get_input_colorspaces():
    return sorted(set([src for src, _ in COLORSPACES_MAP.keys()]))

def get_output_colorspaces(input_colorspace):
    return sorted(set(dst for src,dst in COLORSPACES_MAP.keys() if src==input_colorspace))

def validate_in_out(in_colorspace, out_colorspace):
    assert in_colorspace in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    assert out_colorspace in get_output_colorspaces(in_colorspace), "invalid output colorspace: %s (must be one of %s for input %s)" % (out_colorspace, get_output_colorspaces(in_colorspace), in_colorspace)

def get_spec(in_colorspace, out_colorspace):
    validate_in_out(in_colorspace, out_colorspace)
    return codec_spec(ColorspaceConverter, codec_type=get_type(), speed=100, setup_cost=10, cpu_cost=10, gpu_cost=50, min_w=128, min_h=128, can_scale=False)


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
        self.kernel_function = None
        self.context = None

    def init_context(self, src_width, src_height, src_format,
                           dst_width, dst_height, dst_format, speed=100):  #@DuplicatedSignature
        validate_in_out(src_format, dst_format)
        init_context()
        self.src_width = src_width
        self.src_height = src_height
        self.src_format = src_format
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.dst_format = dst_format
        self.context = context
        k = (src_format, dst_format)
        npp_fn = COLORSPACES_MAP.get(k)
        assert npp_fn is not None, "invalid pair: %s" % k
        self.kernel_function_name, cfn = npp_fn
        debug("init_context%s npp conversion function=%s (%s)", (src_width, src_height, src_format, dst_width, dst_height, dst_format), self.kernel_function_name, cfn)
        self.kernel_function = cfn
        if src_format.find("YUV")>=0:
            self.convert_image_fn = self.convert_image_yuv
        else:
            self.convert_image_fn = self.convert_image_rgb
        debug("init_context(..) convert_image=%s", self.convert_image)

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
        if self.context is None:
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


    def clean(self):                        #@DuplicatedSignature
        log.info("%s.clean() context=%s", self, self.context)
        if self.context:
            self.context = None

    def convert_image(self, image):
        try:
            self.context.push()
            return self.convert_image_fn(image)
        finally:
            self.context.pop()

    def convert_image_yuv(self, image):
        global program
        start = time.time()
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        strides = image.get_rowstride()
        pixels = image.get_pixels()
        debug("convert_image(%s) planes=%s, pixels=%s, size=%s", image, iplanes, type(pixels), len(pixels))
        assert iplanes==ImageWrapper._3_PLANES, "must use planar YUV as input"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)
        assert len(strides)==len(pixels)==3, "invalid number of planes (%s) or strides (%s), should be 3" % (len(strides), len(pixels))

        #YUV444P argtypes = [(ctypes.c_void_p)*3, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, NppiSize]
        #YUV42xP argtypes = [(ctypes.c_void_p)*3, (ctypes.c_int)*3, ctypes.c_void_p, ctypes.c_int, NppiSize]
        in_t = self.kernel_function.argtypes[0]            #always: (ctypes.c_void_p)*3
        in_strides_t = self.kernel_function.argtypes[1]    #(ctypes.c_int)*3 OR ctypes.c_int

        divs = get_subsampling_divs(self.src_format)

        stream = driver.Stream()
        #copy each plane to the GPU:
        upload_start = time.time()
        locked_mem = []         #reference to pinned memory
        in_bufs = []            #GPU side yuv channels
        in_strides = []         #GPU side strides
        for i in range(3):
            x_div, y_div = divs[i]
            stride = strides[i]
            assert stride >= width/x_div, \
                "invalid stride %s is smaller than plane %s width %s/%s" % (stride, YUV_INDEX_TO_PLANE.get(i, i), width, x_div)
            in_height = height/y_div
            plane = pixels[i]
            assert len(plane)>=stride*in_height

            mem = numpy.frombuffer(plane, dtype=numpy.byte)
            if True:
                #keeping stride as it is:
                in_buf = driver.mem_alloc(len(plane))
                in_bufs.append(in_buf)
                in_strides.append(stride)
                hmem = driver.register_host_memory(mem, driver.mem_host_register_flags.DEVICEMAP)
                pycuda.driver.memcpy_htod_async(in_buf, mem, stream)
            else:
                #change stride to what we get from mem_alloc_pitch:
                in_buf, in_stride = driver.mem_alloc_pitch(stride, in_height, 4)
                in_bufs.append(in_buf)
                in_strides.append(in_stride)
                hmem = driver.register_host_memory(mem, driver.mem_host_register_flags.DEVICEMAP)
                locked_mem.append(hmem)
                copy = driver.Memcpy2D()
                copy.set_src_host(hmem)
                copy.set_dst_device(in_buf)
                copy.src_pitch = stride
                copy.dst_pitch = in_stride
                copy.width_in_bytes = stride
                copy.height = in_height
                copy(stream)
        stream.synchronize()
        #all the copying is complete, we can unpin the host memory:
        for hmem in locked_mem:
            hmem.base.unregister()
        upload_end = time.time()
        debug("%s pixels now on GPU at %s, took %.1fms", sum([len(plane) for plane in pixels]), in_bufs, upload_end-upload_start)

        #allocate output RGB buffer on CPU:
        out_buf, out_stride = driver.mem_alloc_pitch(width*4, height, 4)
        src = in_t(*[Npp8u_p(in_buf) for in_buf in in_bufs])
        if in_strides_t==ctypes.c_int:
            #one stride for all planes (this must be YUV444P)
            assert len(set(in_strides))==1, "expected only one stride: %s" % str(in_strides)
            in_strides = [in_strides[0]]
        debug("in_strides=%s, out_stride=%s", in_strides, out_stride)
        kargs = [src, in_strides_t(*in_strides), Npp8u_p(out_buf), ctypes.c_int(out_stride), NppiSize(width, height)]
        if self.kernel_function.argtypes[-1]==CONSTANT_ALPHA:
            #add hardcoded constant alpha:
            kargs.append(ctypes.c_uint8(255))
        debug("calling %s%s", self.kernel_function_name, tuple(kargs))
        kstart = time.time()
        v = self.kernel_function(*kargs)
        #we can now free the GPU source planes:
        for in_buf in in_bufs:
            in_buf.free()
        if v<0:
            log.error("%s%s returned an error: %s", self.kernel_function_name, kargs, ERRORS.get(v, v))
            return None
        elif v>0 and v!=NPP_DOUBLE_SIZE_WARNING:
            #positive return-codes indicate warnings:
            warning = WARNINGS.get(v, "unknown")
            log.warn("%s returned a warning %s: %s", self.kernel_function_name, v, warning)
        kend = time.time()
        debug("%s took %.1fms", self.kernel_function_name, (kend-kstart)*1000.0)

        self.frames += 1

        read_start = time.time()
        gpu_size = out_stride*height
        min_size = width*4*height
        if gpu_size<=2*min_size:
            #direct full buffer async copy with GPU padding:
            pixels = driver.pagelocked_empty(stride*height, dtype=numpy.byte)
            driver.memcpy_dtoh_async(pixels, out_buf, stream)
        else:
            #we don't want the crazy large GPU padding, so we do it ourselves:
            stride = width*4
            pixels = driver.pagelocked_empty(stride*height, dtype=numpy.byte)
            copy = driver.Memcpy2D()
            copy.set_src_device(out_buf)
            copy.set_dst_host(pixels)
            copy.src_pitch = out_stride
            copy.dst_pitch = stride
            copy.width_in_bytes = width*4
            copy.height = height
            copy(stream)
        stream.synchronize()

        #the pixels have been copied, we can free the GPU output memory:
        out_buf.free()
        self.context.synchronize()
        read_end = time.time()
        debug("read back took %.1fms, total time: %.1f", (read_end-read_start)*1000.0, 1000.0*(time.time()-start))
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, pixels.data, self.dst_format, 24, out_stride, planes=ImageWrapper.PACKED_RGB)


    def convert_image_rgb(self, image):
        global program
        start = time.time()
        iplanes = image.get_planes()
        width = image.get_width()
        height = image.get_height()
        stride = image.get_rowstride()
        pixels = image.get_pixels()
        debug("convert_image(%s) planes=%s, pixels=%s, size=%s", image, iplanes, type(pixels), len(pixels))
        assert iplanes==ImageWrapper.PACKED_RGB, "must use packed rgb as input"
        assert image.get_pixel_format()==self.src_format, "invalid source format: %s (expected %s)" % (image.get_pixel_format(), self.src_format)

        divs = get_subsampling_divs(self.dst_format)

        #copy packed rgb pixels to GPU:
        upload_start = time.time()
        stream = driver.Stream()
        mem = numpy.frombuffer(pixels, dtype=numpy.byte)
        if True:
            #keeping stride as it is:
            #the non async/pinned version is simple but slower:
            # gpu_image = driver.to_device(pixels)
            #followed by:
            # gpu_image.free()
            in_buf = driver.mem_alloc(len(pixels))
            in_stride = stride
            hmem = driver.register_host_memory(mem, driver.mem_host_register_flags.DEVICEMAP)
            pycuda.driver.memcpy_htod_async(in_buf, mem, stream)
        else:
            in_buf, in_stride = driver.mem_alloc_pitch(stride, height, 4)
            hmem = driver.register_host_memory(mem, driver.mem_host_register_flags.DEVICEMAP)
            copy = driver.Memcpy2D()
            copy.set_src_host(hmem)
            copy.set_dst_device(in_buf)
            copy.src_pitch = stride
            copy.dst_pitch = in_stride
            copy.width_in_bytes = width*4
            copy.height = height
            copy(stream)

        #YUV444P argtypes = [ctypes.c_void_p, ctypes.c_int, (ctypes.c_void_p)*3, ctypes.c_int, NppiSize]
        #YUV42xP argtypes = [ctypes.c_void_p, ctypes.c_int, (ctypes.c_void_p)*3, (ctypes.c_int)*3, NppiSize]
        out_t = self.kernel_function.argtypes[2]            #always: (ctypes.c_void_p)*3
        out_strides_t = self.kernel_function.argtypes[3]    #(ctypes.c_int)*3 OR ctypes.c_int
        out_bufs = []
        out_strides = []
        out_sizes = []
        for i in range(3):
            x_div, y_div = divs[i]
            out_stride = roundup(width/x_div, 4)
            out_height = roundup(height/y_div, 2)
            out_buf, out_stride = driver.mem_alloc_pitch(out_stride, out_height, 4)
            out_bufs.append(out_buf)
            out_strides.append(out_stride)
            out_sizes.append((out_stride, out_height))
        dest = out_t(*[ctypes.cast(int(out_buf), ctypes.c_void_p) for out_buf in out_bufs])
        if out_strides_t==ctypes.c_int:
            #one stride for all planes (this must be YUV444P)
            assert len(set(out_strides))==1, "more than one stride where only one expected in: %s" % out_strides
            out_strides = [out_strides[0]]
        kargs = [Npp8u_p(in_buf), ctypes.c_int(stride), dest, out_strides_t(*out_strides), NppiSize(width, height)]
        #ensure copying has finished:
        stream.synchronize()
        #we can now unpin the host memory:
        hmem.base.unregister()
        debug("allocation took %.1fms", 1000.0*(time.time() - upload_start))

        debug("calling %s%s", self.kernel_function_name, tuple(kargs))
        kstart = time.time()
        v = self.kernel_function(*kargs)
        #we can now free the GPU source buffer:
        in_buf.free()
        if v<0:
            log.error("%s%s returned an error: %s", self.kernel_function_name, kargs, ERRORS.get(v, v))
            return None
        elif v>0 and v!=NPP_DOUBLE_SIZE_WARNING:
            #positive return-codes indicate warnings:
            warning = WARNINGS.get(v, "unknown")
            log.warn("%s returned a warning %s: %s", self.kernel_function_name, v, warning)
        kend = time.time()
        debug("%s took %.1fms", self.kernel_function_name, (kend-kstart)*1000.0)
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
        context.synchronize()
        read_end = time.time()
        debug("read back took %.1fms, total time: %.1f", (read_end-read_start)*1000.0, 1000.0*(time.time()-start))
        return ImageWrapper(0, 0, self.dst_width, self.dst_height, pixels, self.dst_format, 24, out_strides, planes=ImageWrapper._3_PLANES)
