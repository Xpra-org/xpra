# This file is part of Xpra.
# Copyright (C) 2022-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.string cimport memset
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
from time import monotonic

from xpra.util import csv
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.nvidia.cuda_errors import cudacheck, CUDA_ERRORS
from xpra.codecs.nvidia.cuda_context import get_default_device_context
from xpra.log import Logger
log = Logger("encoder", "nvdec")

#we can import pycuda safely here,
#because importing cuda_context will have imported it with the lock
from pycuda.driver import Memcpy2D, mem_alloc_pitch, memcpy_dtoh
import numpy

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

ctypedef int CUresult
ctypedef void* CUstream
ctypedef void* CUcontext
ctypedef void* CUvideodecoder
ctypedef void* CUvideoctxlock

cdef extern from "cuviddec.h":
    ctypedef enum cudaVideoCodec:
        cudaVideoCodec_MPEG1
        cudaVideoCodec_MPEG2
        cudaVideoCodec_MPEG4
        cudaVideoCodec_VC1
        cudaVideoCodec_H264
        cudaVideoCodec_JPEG
        cudaVideoCodec_H264_SVC
        cudaVideoCodec_H264_MVC
        cudaVideoCodec_HEVC
        cudaVideoCodec_VP8
        cudaVideoCodec_VP9
        cudaVideoCodec_AV1
        cudaVideoCodec_NumCodecs
        #Uncompressed YUV
        cudaVideoCodec_YUV420       #Y,U,V (4:2:0)
        cudaVideoCodec_YV12         #Y,V,U (4:2:0)
        cudaVideoCodec_NV12         #Y,UV  (4:2:0)
        cudaVideoCodec_YUYV         #YUYV/YUY2 (4:2:2)
        cudaVideoCodec_UYVY         #UYVY (4:2:2)
    ctypedef enum cudaVideoChromaFormat:
        cudaVideoChromaFormat_Monochrome
        cudaVideoChromaFormat_420
        cudaVideoChromaFormat_422
        cudaVideoChromaFormat_444
    ctypedef enum cudaVideoCreateFlags:
        cudaVideoCreate_Default         #Default operation mode: use dedicated video engines
        cudaVideoCreate_PreferCUDA      #Use CUDA-based decoder (requires valid vidLock object for multi-threading)
        cudaVideoCreate_PreferDXVA      #Go through DXVA internally if possible (requires D3D9 interop)
        cudaVideoCreate_PreferCUVID     #Use dedicated video engines directly

    ctypedef enum cuvidDecodeStatus:
        cuvidDecodeStatus_Invalid           #Decode status is not valid
        cuvidDecodeStatus_InProgress        #Decode is in progress
        cuvidDecodeStatus_Success           #Decode is completed without any errors
        #// 3 to 7 enums are reserved for future use
        cuvidDecodeStatus_Error             #Decode is completed with an error (error is not concealed)
        cuvidDecodeStatus_Error_Concealed   #Decode is completed with an error and error is concealed

    ctypedef struct CUVIDDECODECAPS:
        cudaVideoCodec          eCodecType              #IN: cudaVideoCodec_XXX
        cudaVideoChromaFormat   eChromaFormat           #IN: cudaVideoChromaFormat_XXX
        unsigned int            nBitDepthMinus8         #IN: The Value "BitDepth minus 8"
        unsigned int            reserved1[3]            #Reserved for future use - set to zero

        unsigned char           bIsSupported            #OUT: 1 if codec supported, 0 if not supported
        unsigned char           nNumNVDECs              #OUT: Number of NVDECs that can support IN params
        unsigned short          nOutputFormatMask       #OUT: each bit represents corresponding cudaVideoSurfaceFormat enum
        unsigned int            nMaxWidth               #OUT: Max supported coded width in pixels
        unsigned int            nMaxHeight              #OUT: Max supported coded height in pixels
        unsigned int            nMaxMBCount             #OUT: Max supported macroblock count
                                                        #CodedWidth*CodedHeight/256 must be <= nMaxMBCount
        unsigned short          nMinWidth               #OUT: Min supported coded width in pixels
        unsigned short          nMinHeight              #OUT: Min supported coded height in pixels
        unsigned char           bIsHistogramSupported   #OUT: 1 if Y component histogram output is supported, 0 if not
                                                        #Note: histogram is computed on original picture data before
                                                        #any post-processing like scaling, cropping, etc. is applied
        unsigned char           nCounterBitDepth        #OUT: histogram counter bit depth
        unsigned short          nMaxHistogramBins       #OUT: Max number of histogram bins
        unsigned int            reserved3[10]           #Reserved for future use - set to zero

    ctypedef enum cudaVideoDeinterlaceMode:
        cudaVideoDeinterlaceMode_Weave      #Weave both fields (no deinterlacing)
        cudaVideoDeinterlaceMode_Bob        #Drop one field
        cudaVideoDeinterlaceMode_Adaptive   #Adaptive deinterlacing

    ctypedef enum cudaVideoSurfaceFormat:
        cudaVideoSurfaceFormat_NV12                     #Semi-Planar YUV [Y plane followed by interleaved UV plane]
        cudaVideoSurfaceFormat_P016                     #16 bit Semi-Planar YUV [Y plane followed by interleaved UV plane].
                                                        #Can be used for 10 bit(6LSB bits 0), 12 bit (4LSB bits 0)
        cudaVideoSurfaceFormat_YUV444                   #Planar YUV [Y plane followed by U and V planes]
        cudaVideoSurfaceFormat_YUV444_16Bit             #16 bit Planar YUV [Y plane followed by U and V planes].
                                                        #Can be used for 10 bit(6LSB bits 0), 12 bit (4LSB bits 0)

    ctypedef struct CUVIDDECODECREATEINFO:
        unsigned long ulWidth               #IN: Coded sequence width in pixels
        unsigned long ulHeight              #IN: Coded sequence height in pixels
        unsigned long ulNumDecodeSurfaces   #IN: Maximum number of internal decode surfaces
        cudaVideoCodec CodecType            #IN: cudaVideoCodec_XXX
        cudaVideoChromaFormat ChromaFormat  #IN: cudaVideoChromaFormat_XXX
        unsigned long ulCreationFlags       #IN: Decoder creation flags (cudaVideoCreateFlags_XXX)
        unsigned long bitDepthMinus8        #IN: The value "BitDepth minus 8"
        unsigned long ulIntraDecodeOnly     #IN: Set 1 only if video has all intra frames (default value is 0). This will
                                            #optimize video memory for Intra frames only decoding. The support is limited
                                            #to specific codecs - H264, HEVC, VP9, the flag will be ignored for codecs which
                                            #are not supported. However decoding might fail if the flag is enabled in case
                                            #of supported codecs for regular bit streams having P and/or B frames.
        unsigned long ulMaxWidth            #Coded sequence max width in pixels used with reconfigure Decoder
        unsigned long ulMaxHeight           #IN: Coded sequence max height in pixels used with reconfigure Decoder
        unsigned long Reserved1             #Reserved for future use - set to zero
        #struct {
        #    short left;
        #    short top;
        #    short right;
        #    short bottom;
        #} display_area;
        cudaVideoSurfaceFormat OutputFormat         #IN: cudaVideoSurfaceFormat_XXX
        cudaVideoDeinterlaceMode DeinterlaceMode    #IN: cudaVideoDeinterlaceMode_XXX
        unsigned long ulTargetWidth                 #IN: Post-processed output width (Should be aligned to 2)
        unsigned long ulTargetHeight                #IN: Post-processed output height (Should be aligned to 2)
        unsigned long ulNumOutputSurfaces           #IN: Maximum number of output surfaces simultaneously mapped
        CUvideoctxlock vidLock                      #IN: If non-NULL, context lock used for synchronizing ownership of
                                                    #the cuda context. Needed for cudaVideoCreate_PreferCUDA decode
        #struct {
        #    short left;
        #    short top;
        #    short right;
        #    short bottom;
        #} target_rect;
        unsigned long enableHistogram               #IN: enable histogram output, if supported
        unsigned long Reserved2[4]                  #Reserved for future use - set to zero

    ctypedef struct CUVIDPICPARAMS:
        int PicWidthInMbs                           #IN: Coded frame size in macroblocks
        int FrameHeightInMbs                        #IN: Coded frame height in macroblocks
        int CurrPicIdx                              #IN: Output index of the current picture
        int field_pic_flag                          #IN: 0=frame picture, 1=field picture
        int bottom_field_flag                       #IN: 0=top field, 1=bottom field (ignored if field_pic_flag=0)
        int second_field                            #IN: Second field of a complementary field pair
        #Bitstream data
        unsigned int nBitstreamDataLen              #IN: Number of bytes in bitstream data buffer
        const unsigned char *pBitstreamData         #IN: Ptr to bitstream data for this picture (slice-layer)
        unsigned int nNumSlices                     #IN: Number of slices in this picture
        const unsigned int *pSliceDataOffsets       #IN: nNumSlices entries, contains offset of each slice within 
                                                    #the bitstream data buffer
        int ref_pic_flag                            #IN: This picture is a reference picture
        int intra_pic_flag                          #IN: This picture is entirely intra coded
        unsigned int Reserved[30]                   #Reserved for future use
        #IN: Codec-specific data in union

    ctypedef struct CUVIDPROCPARAMS:
        int progressive_frame                       #IN: Input is progressive (deinterlace_mode will be ignored)
        int second_field                            #IN: Output the second field (ignored if deinterlace mode is Weave)
        int top_field_first                         #IN: Input frame is top field first (1st field is top, 2nd field is bottom)
        int unpaired_field                          #IN: Input only contains one field (2nd field is invalid)
        #The fields below are used for raw YUV input
        unsigned int reserved_flags                 #Reserved for future use (set to zero)
        unsigned int reserved_zero                  #Reserved (set to zero)
        unsigned long long raw_input_dptr           #IN: Input CUdeviceptr for raw YUV extensions
        unsigned int raw_input_pitch                #IN: pitch in bytes of raw YUV input (should be aligned appropriately)
        unsigned int raw_input_format               #IN: Input YUV format (cudaVideoCodec_enum)
        unsigned long long raw_output_dptr          #IN: Output CUdeviceptr for raw YUV extensions
        unsigned int raw_output_pitch               #IN: pitch in bytes of raw YUV output (should be aligned appropriately)
        unsigned int Reserved1                      #Reserved for future use (set to zero)
        CUstream output_stream                      #IN: stream object used by cuvidMapVideoFrame
        unsigned int Reserved[46]                   #Reserved for future use (set to zero)
        unsigned long long *histogram_dptr          #OUT: Output CUdeviceptr for histogram extensions
        void *Reserved2[1]                          #Reserved for future use (set to zero)

    ctypedef struct CUVIDGETDECODESTATUS:
        cuvidDecodeStatus decodeStatus
        unsigned int reserved[31]
        void *pReserved[8]

    CUresult cuvidGetDecoderCaps(CUVIDDECODECAPS *pdc)
    CUresult cuvidCreateDecoder(CUvideodecoder *phDecoder, CUVIDDECODECREATEINFO *pdci)
    CUresult cuvidDestroyDecoder(CUvideodecoder hDecoder)
    CUresult cuvidDecodePicture(CUvideodecoder hDecoder, CUVIDPICPARAMS *pPicParams)
    CUresult cuvidGetDecodeStatus(CUvideodecoder hDecoder, int nPicIdx, CUVIDGETDECODESTATUS* pDecodeStatus)

    #CUresult cuvidMapVideoFrame(CUvideodecoder hDecoder, int nPicIdx,
    #                            unsigned int *pDevPtr, unsigned int *pPitch,
    #                            CUVIDPROCPARAMS *pVPP)
    #CUresult CUDAAPI cuvidUnmapVideoFrame(CUvideodecoder hDecoder, unsigned int DevPtr)
    CUresult cuvidMapVideoFrame64(CUvideodecoder hDecoder, int nPicIdx, unsigned long long *pDevPtr,
                                             unsigned int *pPitch, CUVIDPROCPARAMS *pVPP)
    CUresult cuvidUnmapVideoFrame64(CUvideodecoder hDecoder, unsigned long long DevPtr)

    #we don't use threads, so no need for this:
    CUresult cuvidCtxLockCreate(CUvideoctxlock *pLock, CUcontext ctx)
    CUresult cuvidCtxLockDestroy(CUvideoctxlock lck)
    CUresult cuvidCtxLock(CUvideoctxlock lck, unsigned int reserved_flags)
    CUresult cuvidCtxUnlock(CUvideoctxlock lck, unsigned int reserved_flags)

DECODE_STATUS_STR = {
    cuvidDecodeStatus_Invalid       : "invalid",
    cuvidDecodeStatus_InProgress    : "in-progress",
    cuvidDecodeStatus_Success       : "success",
    cuvidDecodeStatus_Error         : "error",
    cuvidDecodeStatus_Error_Concealed : "error-concealed",
    }

CODEC_NAMES = {
    cudaVideoCodec_MPEG1    : "mpeg1",
    cudaVideoCodec_MPEG2    : "mpeg2",
    cudaVideoCodec_MPEG4    : "mpeg4",
    cudaVideoCodec_VC1      : "vc1",
    cudaVideoCodec_H264     : "h264",
    cudaVideoCodec_JPEG     : "jpeg",
    cudaVideoCodec_H264_SVC : "h264-svc",
    cudaVideoCodec_H264_MVC : "h264-mvc",
    cudaVideoCodec_HEVC     : "hevc",
    cudaVideoCodec_VP8      : "vp8",
    cudaVideoCodec_VP9      : "vp9",
    cudaVideoCodec_AV1      : "av1",
    }

CHROMA_NAMES = {
    cudaVideoChromaFormat_Monochrome    : "monochrome",
    cudaVideoChromaFormat_420           : "420",
    cudaVideoChromaFormat_422           : "422",
    cudaVideoChromaFormat_444           : "444",
    }

SURFACE_NAMES = {
    cudaVideoSurfaceFormat_NV12     : "NV12",
    cudaVideoSurfaceFormat_P016     : "P016",
    cudaVideoSurfaceFormat_YUV444   : "YUV444P",
    cudaVideoSurfaceFormat_YUV444_16Bit : "YUV444P16",
    }


def init_module():
    log("nvdec.init_module()")

def cleanup_module():
    log("nvdec.cleanup_module()")

def get_version():
    return (0, )

def get_type():
    return "nvdec"

def get_info():
    return {
        "version"   : get_version(),
        }

def get_encodings():
    #return ("jpeg", "h264")
    return ("jpeg", )

def get_input_colorspaces(encoding):
    #return ("YUV420P", "YUV422P", "YUV444P")
    return ("YUV420P", )

def get_output_colorspace(encoding, csc):
    return "NV12"


cdef class Decoder:
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned long frames
    cdef object colorspace
    cdef object encoding
    cdef CUvideodecoder context

    cdef object __weakref__

    def init_context(self, encoding, width, height, colorspace):
        log("nvdec.Decoder.init_context%s", (encoding, width, height, colorspace))
        self.encoding = encoding
        self.colorspace = colorspace
        self.width = width
        self.height = height
        self.init_nvdec()

    def init_nvdec(self):
        cdef CUVIDDECODECREATEINFO pdci
        pdci.ulWidth = self.width
        pdci.ulHeight = self.height
        pdci.ulNumDecodeSurfaces = 2
        if self.encoding=="h264":
            pdci.CodecType = cudaVideoCodec_H264_SVC
        elif self.encoding=="jpeg":
            pdci.CodecType = cudaVideoCodec_JPEG
        else:
            raise ValueError(f"invalid encoding {self.encoding!r}")
        if self.colorspace=="YUV420P":
            pdci.ChromaFormat = cudaVideoChromaFormat_420
        elif self.colorspace=="YUV422P":
            pdci.ChromaFormat = cudaVideoChromaFormat_422
        elif self.colorspace=="YUV444P":
            pdci.ChromaFormat = cudaVideoChromaFormat_444
        else:
            raise ValueError(f"invalid colorspace {self.colorspace!r}")
        pdci.ulCreationFlags = cudaVideoCreate_PreferCUDA
        #cudaVideoCreate_PreferCUVID     #Use dedicated video engines directly
        pdci.bitDepthMinus8 = 0
        pdci.ulIntraDecodeOnly = 0
        pdci.ulMaxWidth = roundup(self.width, 16)
        pdci.ulMaxHeight = roundup(self.height, 16)
        pdci.OutputFormat = cudaVideoSurfaceFormat_NV12
        #cudaVideoSurfaceFormat_YUV444_16Bit
        pdci.DeinterlaceMode = cudaVideoDeinterlaceMode_Weave
        pdci.ulTargetWidth = roundup(self.width, 2)
        pdci.ulTargetHeight = roundup(self.height, 2)
        pdci.ulNumOutputSurfaces = 1
        pdci.vidLock = NULL
        pdci.enableHistogram = 0
        cdef CUresult r = cuvidCreateDecoder(&self.context, &pdci)
        cudacheck(r, "creating decoder returned error")

    def __repr__(self):
        return f"nvdec({self.encoding})"

    def get_info(self) -> dict:
        return {
                "type"      : self.get_type(),
                "width"     : self.width,
                "height"    : self.height,
                "encoding"  : self.encoding,
                "frames"    : int(self.frames),
                "colorspace": self.colorspace,
                }

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context==NULL

    def get_encoding(self) -> str:
        return self.encoding

    def get_type(self) -> str:
        return  "nvdec"

    def __dealloc__(self):
        self.clean()

    def clean(self):
        cdef CUresult r = 0
        if self.context!=NULL:
            r = cuvidDestroyDecoder(self.context)
            if r:
                log.warn(f"Warning: error {r} destroying decoder")
            self.context = NULL
        self.width = 0
        self.height = 0
        self.colorspace = ""
        self.encoding = ""


    def decompress_image(self, data, options=None):
        log(f"decompress_image({len(data)} bytes, {options})")
        cdef CUVIDPICPARAMS pic
        pic.PicWidthInMbs = 16      #??
        pic.FrameHeightInMbs = 16   #??
        pic.CurrPicIdx = self.frames
        pic.field_pic_flag = 0
        pic.nBitstreamDataLen = len(data)
        pic.pBitstreamData = data
        pic.nNumSlices = 1  #??
        pic.ref_pic_flag = self.frames==0                            #IN: This picture is a reference picture
        pic.intra_pic_flag = self.frames==0
        self.frames += 1
        cdef CUresult r = cuvidDecodePicture(self.context, &pic)
        cudacheck(r, "GPU picture decoding returned error")
        cdef CUVIDGETDECODESTATUS status
        cdef int pic_idx = 0
        r = cuvidGetDecodeStatus(self.context, pic_idx, &status)
        if r:
            raise RuntimeError(f"GPU decoding status returned error {r}")
        sinfo = DECODE_STATUS_STR.get(status.decodeStatus, status.decodeStatus)
        log(f"decompress_image: {sinfo}")
        if status.decodeStatus not in (
            cuvidDecodeStatus_InProgress,
            cuvidDecodeStatus_Success,
            cuvidDecodeStatus_Error_Concealed,
            ):
            raise RuntimeError(f"GPU decoding: {sinfo}")
        #map it as a CUDA buffer:
        cdef CUVIDPROCPARAMS map_params
        memset(&map_params, 0, sizeof(CUVIDPROCPARAMS))
        stream = (options or {}).get("stream", None)
        if stream:
            map_params.output_stream = <CUstream> (<uintptr_t> stream.handle)
        cdef unsigned long long dev_ptr
        cdef unsigned int pitch
        r = cuvidMapVideoFrame64(self.context, pic_idx, &dev_ptr, &pitch, &map_params)
        cudacheck(r, "GPU mapping of picture buffer error")
        log(f"mapped picture {pic_idx} at {dev_ptr:x}, pitch={pitch}")
        try:
            yuv_buf, yuv_pitch = mem_alloc_pitch(self.width, roundup(self.height, 2)*3//2, 4)
            copy = Memcpy2D()
            copy.set_src_device(dev_ptr)
            copy.src_x_in_bytes = 0
            copy.src_y = 0
            copy.src_pitch = pitch
            copy.width_in_bytes = self.width
            copy.height = roundup(self.height, 2)*3//2
            copy.set_dst_device(yuv_buf)
            copy.dst_x_in_bytes = 0
            copy.dst_y = 0
            copy.dst_pitch = yuv_pitch
            copy(aligned=False)
            rowstrides = [yuv_pitch, yuv_pitch]
            image = ImageWrapper(0, 0, self.width, self.height,
                                 yuv_buf, "NV12", 24, rowstrides, 3, ImageWrapper.PLANAR_2)
            self.frames += 1
            return image
        finally:
            r = cuvidUnmapVideoFrame64(self.context, dev_ptr)
            cudacheck(r, "error unmapping video frame")


def download_from_gpu(buf, size_t size):
    log("nvdec download_from_gpu%s", (buf, size))
    start = monotonic()
    cdef MemBuf pixels = getbuf(size, False)
    memcpy_dtoh(pixels, buf)
    end = monotonic()
    log("nvdec downloaded %i bytes in %ims", size, 1000*(end-start))
    return pixels

def decompress(encoding, img_data, width, height, rgb_format, options=None):
    #decompress using the default device,
    #and download the pixel data from the GPU:
    dev = get_default_device_context()
    if not dev:
        raise RuntimeError("no cuda device found")
    with dev as cuda_context:
        log("cuda_context=%s for device=%s", cuda_context, dev.get_info())
        return decompress_and_download(encoding, img_data, rgb_format, options)

def decompress_and_download(encoding, img_data, width, height, options=None):
    img = decompress_with_device(encoding, img_data, width, height, options)
    cuda_buffer = img.get_pixels()
    rowstrides = img.get_rowstride()
    assert len(rowstrides)==2 and rowstrides[0]==rowstrides[1]
    stride = rowstrides[0]
    assert img.get_pixel_format()=="NV12"
    height = img.get_height()
    size = roundup(height, 2)*stride*3//2
    y_size = stride*height
    uv_start = roundup(height, 2)*stride
    uv_size = stride*(height//2)
    nv12_buf = download_from_gpu(cuda_buffer, size)
    pixels = memoryview(nv12_buf)
    planes = pixels[:y_size], pixels[uv_start:uv_start+uv_size]
    cuda_buffer.free()
    img.set_pixels(planes)
    return img

def decompress_with_device(encoding, img_data, width, height, options=None):
    cdef Decoder decoder = Decoder()
    try:
        decoder.init_context(encoding, width, height, "YUV420P")
        return decoder.decompress_image(img_data, options)
    finally:
        decoder.clean()


def selftest(full=False):
    from xpra.codecs.nvidia.nv_util import has_nvidia_hardware, get_nvidia_module_version
    if not has_nvidia_hardware():
        raise ImportError("no nvidia GPU device found")
    get_nvidia_module_version(True)

    dev = get_default_device_context()
    if not dev:
        raise RuntimeError("no device found")

    cdef CUVIDDECODECAPS caps
    cdef CUresult r
    cdef Decoder decoder

    codec_ok = {}
    codec_failed = []
    with dev as cuda_context:
        log("cuda_context=%s for device=%s", cuda_context, dev.get_info())

        for codec_i, codec_name in CODEC_NAMES.items():
            chroma_ok= []
            chroma_failed = []
            for chroma_i, chroma_name in CHROMA_NAMES.items():
                memset(&caps, 0, sizeof(CUVIDDECODECAPS))
                caps.eCodecType = codec_i
                caps.eChromaFormat = chroma_i
                caps.nBitDepthMinus8 = 0
                r = cuvidGetDecoderCaps(&caps)
                if r:
                    chroma_failed.append(chroma_name)
                    log(f"decoder caps for {codec_name} + {chroma_name} returned error %s", CUDA_ERRORS.get(r, r))
                    continue
                if not caps.bIsSupported:
                    chroma_failed.append(chroma_name)
                    #log(f"{codec_name} + {chroma_name} is not supported on this GPU")
                    continue
                if caps.nMaxWidth<4096 or caps.nMaxHeight<4096:
                    chroma_failed.append(chroma_name)
                    log(f"{codec_name} maximum dimension is only {caps.nMaxWidth}x{caps.nMaxHeight}")
                    continue
                oformats = tuple(name for sfi, name in SURFACE_NAMES.items() if caps.nOutputFormatMask & (1<<sfi))
                log(f"output formats for {codec_name} + {chroma_name}: %s", csv(oformats))
                if "NV12" in oformats:
                    chroma_ok.append(chroma_name)
                else:
                    log(f"{codec_name} does not support NV12 surface")
            if chroma_ok:
                codec_ok[codec_name] = chroma_ok
            else:
                codec_failed.append(codec_name)
        log(f"codecs failed: {codec_failed}")
        log(f"codecs supported: {codec_ok}")
        #decoder = Decoder()
        #decoder.init_context("h264", 512, 256, "YUV420P")
        #decoder.clean()
        #if "h264" not in codec_ok and "jpeg" not in codec_ok:
        if "jpeg" not in codec_ok:
            raise RuntimeError("no jpeg decoding")

        from xpra.codecs.codec_checks import testdecoder
        from xpra.codecs.nvidia import nvdec
        testdecoder(nvdec.decoder, full)
