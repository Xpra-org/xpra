# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True
from __future__ import absolute_import

import os
from weakref import WeakSet

from xpra.os_util import WIN32
from xpra.util import csv, roundup
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.nvfbc.cuda_image_wrapper import CUDAImageWrapper
from xpra.codecs.nv_util import get_nvidia_module_version, get_cards, get_license_keys, parse_nvfbc_hex_key

from xpra.log import Logger
log = Logger("encoder", "nvfbc")

try:
    from pycuda import driver
    from xpra.codecs.cuda_common.cuda_context import CUDA_ERRORS_INFO, select_device, device_info
except ImportError:
    raise
except:
    log.error("Error: NvFBC requires CUDA", exc_info=True)
    CUDA_ERRORS_INFO = {}
    select_device = None


from libc.stdint cimport uintptr_t, uint32_t, uint64_t
from xpra.monotonic_time cimport monotonic_time
from xpra.buffers.membuf cimport padbuf, MemBuf


SYS_PIXEL_FORMAT = os.environ.get("XPRA_NVFBC_SYS_PIXEL_FORMAT", "BGRX")
CUDA_PIXEL_FORMAT = os.environ.get("XPRA_NVFBC_CUDA_PIXEL_FORMAT", "BGRX")
CLIENT_KEYS_STRS = get_license_keys(basefilename="nvfbc")


ctypedef uintptr_t CUdeviceptr

cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num) nogil
    void * memset(void * ptr, int value, size_t num) nogil


cdef extern from "NvFBC.h":
    int NVFBC_VERSION_MAJOR
    int NVFBC_VERSION_MINOR

    ctypedef int NVFBCSTATUS

    NVFBCSTATUS NVFBC_SUCCESS
    NVFBCSTATUS NVFBC_ERR_API_VERSION           #This indicates that the API version between the client and the library is not compatible
    NVFBCSTATUS NVFBC_ERR_INTERNAL              #An internal error occurred
    NVFBCSTATUS NVFBC_ERR_INVALID_PARAM         #This indicates that one or more of the parameter passed to the API call is invalid
    NVFBCSTATUS NVFBC_ERR_INVALID_PTR           #This indicates that one or more of the pointers passed to the API call is invalid
    NVFBCSTATUS NVFBC_ERR_INVALID_HANDLE        #This indicates that the handle passed to the API call to identify the client is invalid
    NVFBCSTATUS NVFBC_ERR_MAX_CLIENTS           #This indicates that the maximum number of threaded clients of the same process has been reached.
                                                #The limit is 10 threads per process.
                                                #There is no limit on the number of process.
    NVFBCSTATUS NVFBC_ERR_UNSUPPORTED           #This indicates that the requested feature is not currently supported by the library.
    NVFBCSTATUS NVFBC_ERR_OUT_OF_MEMORY         #This indicates that the API call failed because it was unable to allocate
                                                #enough memory to perform the requested operation
    NVFBCSTATUS NVFBC_ERR_BAD_REQUEST           #This indicates that the API call was not expected.  This happens when
                                                #API calls are performed in a wrong order, such as trying to capture
                                                #a frame prior to creating a new capture session; or trying to set up
                                                #a capture to video memory although a capture session to system memory
                                                #was created.
    ctypedef int NVFBC_BOOL

    ctypedef int NVFBC_CAPTURE_TYPE
    NVFBC_CAPTURE_TYPE NVFBC_CAPTURE_TO_SYS
    NVFBC_CAPTURE_TYPE NVFBC_CAPTURE_SHARED_CUDA
    #NVFBC_CAPTURE_TYPE NVFBC_CAPTURE_TO_HW_ENCODER,
    NVFBC_CAPTURE_TYPE NVFBC_CAPTURE_TO_GL

    ctypedef int NVFBC_TRACKING_TYPE
    NVFBC_TRACKING_TYPE NVFBC_TRACKING_DEFAULT
    NVFBC_TRACKING_TYPE NVFBC_TRACKING_OUTPUT
    NVFBC_TRACKING_TYPE NVFBC_TRACKING_SCREEN

    ctypedef int NVFBC_BUFFER_FORMAT
    NVFBC_BUFFER_FORMAT NVFBC_BUFFER_FORMAT_ARGB    #Data will be converted to ARGB unsigned byte format. 32 bpp
    NVFBC_BUFFER_FORMAT NVFBC_BUFFER_FORMAT_BGRA    #Data will be converted to BGRA unsigned byte format. 32 bpp
    NVFBC_BUFFER_FORMAT NVFBC_BUFFER_FORMAT_RGB     #Data will be converted to RGB unsigned byte format. 24 bpp
    NVFBC_BUFFER_FORMAT NVFBC_BUFFER_FORMAT_YUV420P #Data will be converted to YUV 420 planar format using HDTV weights according to ITU-R BT.709.  12 bpp.
    NVFBC_BUFFER_FORMAT NVFBC_BUFFER_FORMAT_YUV444P #Data will be converted to YUV 444 planar format using HDTV weights according to ITU-R BT.709.  24 bpp

    ctypedef uint64_t NVFBC_SESSION_HANDLE

    ctypedef struct NVFBC_BOX:
        uint32_t x
        uint32_t y
        uint32_t w
        uint32_t h

    ctypedef struct NVFBC_SIZE:
        uint32_t w
        uint32_t h

    ctypedef struct NVFBC_FRAME_GRAB_INFO:
        uint32_t dwWidth        #Width of the captured frame
        uint32_t dwHeight       #Height of the captured frame
        uint32_t dwByteSize     #Size of the frame in bytes
        uint32_t dwCurrentFrame #Incremental ID of the current frame
        NVFBC_BOOL bIsNewFrame  #Whether the captured frame is a new frame.
                                #When not using blocking calls, it is possible to capture a frame that
                                #is identical to the previous one.  This parameter indicates that


    ctypedef struct NVFBC_CREATE_HANDLE_PARAMS:
        uint32_t dwVersion          #Must be set to NVFBC_CREATE_HANDLE_PARAMS_VER
        const void *privateData     #Application specific private information passed to the NvFBC session
        uint32_t privateDataSize    #Size of the application specific private information passed to the NvFBC session
        NVFBC_BOOL bExternallyManagedContext    #Whether NvFBC should not create and manage its own graphics context
        void *glxCtx                #GLX context that NvFBC should use internally to create pixmaps and make them current when creating a new capture session.
        void *glxFBConfig           #GLX framebuffer configuration
    uint32_t NVFBC_CREATE_HANDLE_PARAMS_VER

    ctypedef struct NVFBC_DESTROY_HANDLE_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_DESTROY_HANDLE_PARAMS_VER
    uint32_t NVFBC_DESTROY_HANDLE_PARAMS_VER

    DEF NVFBC_OUTPUT_NAME_LEN = 128
    ctypedef struct NVFBC_RANDR_OUTPUT_INFO:
        uint32_t dwId                       #Identifier of the RandR output
        char name[NVFBC_OUTPUT_NAME_LEN]    #Name of the RandR output, as reported by tools such as xrandr(1)
        NVFBC_BOX trackedBox                #Region of the X screen tracked by the RandR CRTC driving this RandR output

    DEF NVFBC_OUTPUT_MAX = 5
    ctypedef struct NVFBC_GET_STATUS_PARAMS:
        uint32_t dwVersion                  #[in] Must be set to NVFBC_GET_STATUS_PARAMS_VER
        NVFBC_BOOL bIsCapturePossible       #[out] Whether or not framebuffer capture is supported by the graphics driver
        NVFBC_BOOL bCurrentlyCapturing      #[out] Whether or not there is already a capture session on this system
        NVFBC_BOOL bCanCreateNow            #[out] Whether or not it is possible to create a capture session on this system
        NVFBC_SIZE screenSize               #[out] Size of the X screen (framebuffer)
        NVFBC_BOOL bXRandRAvailable         #[out] Whether the XRandR extension is available
        NVFBC_RANDR_OUTPUT_INFO outputs[NVFBC_OUTPUT_MAX]   #[out] Array of outputs connected to the X screen.
        uint32_t dwOutputNum                #[out] Number of outputs connected to the X screen
        uint32_t dwNvFBCVersion             #[out] Version of the NvFBC library running on this system
    uint32_t NVFBC_GET_STATUS_PARAMS_VER

    ctypedef struct NVFBC_CREATE_CAPTURE_SESSION_PARAMS:
        uint32_t dwVersion                  #[in] Must be set to NVFBC_CREATE_CAPTURE_SESSION_PARAMS_VER
        NVFBC_CAPTURE_TYPE eCaptureType     #Desired capture type
        NVFBC_TRACKING_TYPE eTrackingType   #[in] What region of the framebuffer should be tracked
        uint32_t dwOutputId                 #[in] ID of the output to track if eTrackingType is set to NVFBC_TRACKING_OUTPUT.
        NVFBC_BOX captureBox                #[in] Crop the tracked region
        NVFBC_SIZE frameSize                #[in] Desired size of the captured frame
        NVFBC_BOOL bWithCursor              #[in] Whether the mouse cursor should be composited to the frame
        NVFBC_BOOL bDisableAutoModesetRecovery  #[in] Whether NvFBC should not attempt to recover from modesets
    uint32_t NVFBC_CREATE_CAPTURE_SESSION_PARAMS_VER

    ctypedef struct NVFBC_DESTROY_CAPTURE_SESSION_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_DESTROY_CAPTURE_SESSION_PARAMS_VER
    uint32_t NVFBC_DESTROY_CAPTURE_SESSION_PARAMS_VER

    ctypedef struct NVFBC_BIND_CONTEXT_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_BIND_CONTEXT_PARAMS_VER
    uint32_t NVFBC_BIND_CONTEXT_PARAMS_VER

    ctypedef struct NVFBC_RELEASE_CONTEXT_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_RELEASE_CONTEXT_PARAMS_VER
    uint32_t NVFBC_RELEASE_CONTEXT_PARAMS_VER


    ctypedef int NVFBC_TOSYS_GRAB_FLAGS
    NVFBC_TOSYS_GRAB_FLAGS NVFBC_TOSYS_GRAB_FLAGS_NOFLAGS   #Default, capturing waits for a new frame or mouse move
    NVFBC_TOSYS_GRAB_FLAGS NVFBC_TOSYS_GRAB_FLAGS_NOWAIT    #Capturing does not wait for a new frame nor a mouse move
    NVFBC_TOSYS_GRAB_FLAGS NVFBC_TOSYS_GRAB_FLAGS_FORCE_REFRESH #Forces the destination buffer to be refreshed even if the frame has not changed since previous capture.

    ctypedef struct NVFBC_TOSYS_SETUP_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_TOSYS_SETUP_PARAMS_VER
        NVFBC_BUFFER_FORMAT eBufferFormat   #[in] Desired buffer format
        void **ppBuffer             #[out] Pointer to a pointer to a buffer in system memory
        NVFBC_BOOL bWithDiffMap     #[in] Whether differential maps should be generated
        void **ppDiffMap            #[out] Pointer to a pointer to a buffer in system memory
        uint32_t dwDiffMapScalingFactor #[in] Scaling factor of the differential maps
    uint32_t NVFBC_TOSYS_SETUP_PARAMS_VER

    ctypedef struct NVFBC_TOSYS_GRAB_FRAME_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_TOSYS_GRAB_FRAME_PARAMS_VER
        uint32_t dwFlags            #[in] Flags defining the behavior of this frame capture
        NVFBC_FRAME_GRAB_INFO *pFrameGrabInfo   #[out] Information about the captured frame
    uint32_t NVFBC_TOSYS_GRAB_FRAME_PARAMS_VER

    ctypedef int NVFBC_TOCUDA_FLAGS
    NVFBC_TOCUDA_FLAGS NVFBC_TOCUDA_GRAB_FLAGS_NOFLAGS
    NVFBC_TOCUDA_FLAGS NVFBC_TOCUDA_GRAB_FLAGS_NOWAIT
    NVFBC_TOCUDA_FLAGS NVFBC_TOCUDA_GRAB_FLAGS_FORCE_REFRESH

    ctypedef struct NVFBC_TOCUDA_SETUP_PARAMS:
        uint32_t dwVersion                  #[in] Must be set to NVFBC_TOCUDA_SETUP_PARAMS_VER
        NVFBC_BUFFER_FORMAT eBufferFormat   #[in] Desired buffer format
    uint32_t NVFBC_TOCUDA_SETUP_PARAMS_VER

    ctypedef struct NVFBC_TOCUDA_GRAB_FRAME_PARAMS:
        uint32_t dwVersion          #[in] Must be set to NVFBC_TOCUDA_GRAB_FRAME_PARAMS_VER
        uint32_t dwFlags            #[in] Flags defining the behavior of this frame capture
        void *pCUDADeviceBuffer     #[out] Pointer to a ::CUdeviceptr
        NVFBC_FRAME_GRAB_INFO *pFrameGrabInfo   #[out] Information about the captured frame
    uint32_t NVFBC_TOCUDA_GRAB_FRAME_PARAMS_VER

    ctypedef int NVFBC_TOGL_FLAGS
    NVFBC_TOGL_FLAGS NVFBC_TOGL_GRAB_FLAGS_NOFLAGS  #Default, capturing waits for a new frame or mouse move
    NVFBC_TOGL_FLAGS NVFBC_TOGL_GRAB_FLAGS_NOWAIT   #Capturing does not wait for a new frame nor a mouse move
    NVFBC_TOGL_FLAGS NVFBC_TOGL_GRAB_FLAGS_FORCE_REFRESH    #[in] Forces the destination buffer to be refreshed even if the frame has not changed since previous capture.

    DEF NVFBC_TOGL_TEXTURES_MAX = 2
    ctypedef struct NVFBC_TOGL_SETUP_PARAMS:
        uint32_t dwVersion                  #[in] Must be set to NVFBC_TOGL_SETUP_PARAMS_VER
        NVFBC_BUFFER_FORMAT eBufferFormat   #[in] Desired buffer format
        NVFBC_BOOL bWithDiffMap             #[in] Whether differential maps should be generated
        void **ppDiffMap                    #[out] Pointer to a pointer to a buffer in system memory
        uint32_t dwDiffMapScalingFactor     #[in] Scaling factor of the differential maps.
        uint32_t dwTextures[NVFBC_TOGL_TEXTURES_MAX]    #[out] List of GL textures that will store the captured frames
        uint32_t dwTexTarget                #[out] GL target to which the texture should be bound
        uint32_t dwTexFormat                #[out] GL format of the textures
        uint32_t dwTexType                  #[out] GL type of the textures
    uint32_t NVFBC_TOGL_SETUP_PARAMS_VER

    ctypedef struct NVFBC_TOGL_GRAB_FRAME_PARAMS:
        uint32_t dwVersion                  #[in] Must be set to NVFBC_TOGL_GRAB_FRAME_PARAMS_VER
        uint32_t dwFlags                    #[in] Flags defining the behavior of this frame capture
        uint32_t dwTextureIndex             #[out] Index of the texture storing the current frame
    uint32_t NVFBC_TOGL_GRAB_FRAME_PARAMS_VER

    const char* NvFBCGetLastErrorStr(const NVFBC_SESSION_HANDLE sessionHandle) nogil
    NVFBCSTATUS NvFBCCreateHandle(NVFBC_SESSION_HANDLE *pSessionHandle, NVFBC_CREATE_HANDLE_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCDestroyHandle(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_DESTROY_HANDLE_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCGetStatus(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_GET_STATUS_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCBindContext(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_BIND_CONTEXT_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCReleaseContext(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_RELEASE_CONTEXT_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCCreateCaptureSession(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_CREATE_CAPTURE_SESSION_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCDestroyCaptureSession(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_DESTROY_CAPTURE_SESSION_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCToSysSetUp(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOSYS_SETUP_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCToSysGrabFrame(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOSYS_GRAB_FRAME_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCToCudaSetUp(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOCUDA_SETUP_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCToCudaGrabFrame(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOCUDA_GRAB_FRAME_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCToGLSetUp(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOGL_SETUP_PARAMS *pParams) nogil
    NVFBCSTATUS NvFBCToGLGrabFrame(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOGL_GRAB_FRAME_PARAMS *pParams) nogil

    ctypedef const char* (* PNVFBCGETLASTERRORSTR)(const NVFBC_SESSION_HANDLE sessionHandle) nogil
    ctypedef NVFBCSTATUS (* PNVFBCCREATEHANDLE)(NVFBC_SESSION_HANDLE *pSessionHandle, NVFBC_CREATE_HANDLE_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCDESTROYHANDLE)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_DESTROY_HANDLE_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCBINDCONTEXT)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_BIND_CONTEXT_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCRELEASECONTEXT)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_RELEASE_CONTEXT_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCGETSTATUS)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_GET_STATUS_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCCREATECAPTURESESSION)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_CREATE_CAPTURE_SESSION_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCDESTROYCAPTURESESSION)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_DESTROY_CAPTURE_SESSION_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCTOSYSSETUP)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOSYS_SETUP_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCTOSYSGRABFRAME)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOSYS_GRAB_FRAME_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCTOCUDASETUP)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOCUDA_SETUP_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCTOCUDAGRABFRAME)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOCUDA_GRAB_FRAME_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOH264SETUP)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOH264_SETUP_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOH264GRABFRAME)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOH264_GRAB_FRAME_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOH264GETHEADER)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOH264_GET_HEADER_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOHWENCGETCAPS)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOHWENC_GET_CAPS_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOHWENCSETUP)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOHWENC_SETUP_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOHWENCGRABFRAME)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOHWENC_GRAB_FRAME_PARAMS *pParams) nogil
    #ctypedef NVFBCSTATUS (* PNVFBCTOHWENCGETHEADER)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOHWENC_GET_HEADER_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCTOGLSETUP)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOGL_SETUP_PARAMS *pParams) nogil
    ctypedef NVFBCSTATUS (* PNVFBCTOGLGRABFRAME)(const NVFBC_SESSION_HANDLE sessionHandle, NVFBC_TOGL_GRAB_FRAME_PARAMS *pParams) nogil

    ctypedef struct NVFBC_API_FUNCTION_LIST:
        uint32_t                                  dwVersion                     #[in] Must be set to NVFBC_VERSION
        PNVFBCGETLASTERRORSTR                     nvFBCGetLastErrorStr
        PNVFBCCREATEHANDLE                        nvFBCCreateHandle
        PNVFBCDESTROYHANDLE                       nvFBCDestroyHandle
        PNVFBCGETSTATUS                           nvFBCGetStatus
        PNVFBCCREATECAPTURESESSION                nvFBCCreateCaptureSession
        PNVFBCDESTROYCAPTURESESSION               nvFBCDestroyCaptureSession
        PNVFBCTOSYSSETUP                          nvFBCToSysSetUp
        PNVFBCTOSYSGRABFRAME                      nvFBCToSysGrabFrame
        PNVFBCTOCUDASETUP                         nvFBCToCudaSetUp
        PNVFBCTOCUDAGRABFRAME                     nvFBCToCudaGrabFrame
        #PNVFBCTOH264SETUP                         nvFBCToH264SetUp
        #PNVFBCTOH264GRABFRAME                     nvFBCToH264GrabFrame
        #PNVFBCTOH264GETHEADER                     nvFBCToH264GetHeader
        PNVFBCBINDCONTEXT                         nvFBCBindContext
        PNVFBCRELEASECONTEXT                      nvFBCReleaseContext
        #PNVFBCTOHWENCSETUP                        nvFBCToHwEncSetUp
        #PNVFBCTOHWENCGRABFRAME                    nvFBCToHwEncGrabFrame
        #PNVFBCTOHWENCGETHEADER                    nvFBCToHwEncGetHeader
        #PNVFBCTOHWENCGETCAPS                      nvFBCToHwEncGetCaps
        PNVFBCTOGLSETUP                           nvFBCToGLSetUp
        PNVFBCTOGLGRABFRAME                       nvFBCToGLGrabFrame
    uint32_t NVFBC_VERSION

    NVFBCSTATUS NvFBCCreateInstance(NVFBC_API_FUNCTION_LIST *pFunctionList)
    ctypedef NVFBCSTATUS (* PNVFBCCREATEINSTANCE)(NVFBC_API_FUNCTION_LIST *pFunctionList)


ERRORS = {
    NVFBC_SUCCESS               : "SUCCESS",
    NVFBC_ERR_API_VERSION       : "API_VERSION",
    NVFBC_ERR_INTERNAL          : "INTERNAL",
    NVFBC_ERR_INVALID_PARAM     : "INVALID_PARAM",
    NVFBC_ERR_INVALID_PTR       : "INVALID_PTR",
    NVFBC_ERR_INVALID_HANDLE    : "INVALID_HANDLE",
    NVFBC_ERR_MAX_CLIENTS       : "MAX_CLIENTS",
    }


cdef inline cvp(val):
    import ctypes
    return ctypes.cast(<uintptr_t> val, ctypes.c_void_p)


class NvFBCException(Exception):
    def __init__(self, code, fn):
        self.function = fn
        self.code = code
        msg = "%s - returned %s" % (fn, ERRORS.get(code, code))
        Exception.__init__(self, msg)

cdef raiseNvFBC(NVFBC_SESSION_HANDLE context, NVFBCSTATUS ret, msg):
    global INIT_DONE
    if ret==0:
        return
    cdef const char *err_str = NULL
    if context:
        assert INIT_DONE
        err_str = function_list.nvFBCGetLastErrorStr(context)
        if err_str!=NULL:
            raise NvFBCException(ret, msg+err_str)
    raise NvFBCException(ret, msg)


cdef NVFBC_API_FUNCTION_LIST function_list
INIT_DONE = False
def init_nvfbc_library():
    global INIT_DONE
    assert not INIT_DONE
    memset(&function_list, 0, sizeof(NVFBC_API_FUNCTION_LIST))
    function_list.dwVersion = NVFBC_VERSION
    cdef NVFBCSTATUS ret = NvFBCCreateInstance(&function_list)
    log("NvFBCCreateInstance(%#x)=%s", <uintptr_t> &function_list, ret)
    raiseNvFBC(0, ret, "NvFBCCreateInstance")
    INIT_DONE = True

def unload_library():
    global INIT_DONE
    assert INIT_DONE
    memset(&function_list, 0, sizeof(NVFBC_API_FUNCTION_LIST))
    INIT_DONE = False

def get_status():
    return {}

def get_context_status(NVFBC_SESSION_HANDLE context):
    cdef NVFBC_GET_STATUS_PARAMS status
    memset(&status, 0, sizeof(NVFBC_GET_STATUS_PARAMS))
    status.dwVersion = NVFBC_GET_STATUS_PARAMS_VER
    cdef NVFBCSTATUS ret = function_list.nvFBCGetStatus(context, &status)
    raiseNvFBC(context, ret, "NvFBCGetStatus")
    outputs = []
    cdef uint32_t i
    for i in range(status.dwOutputNum):
        oinfo = {
            "id"    : status.outputs[i].dwId,
            "name"  : status.outputs[i].name,
            }
        if status.outputs[i].trackedBox.w or status.outputs[i].trackedBox.h:
            oinfo["box"] = (status.outputs[i].trackedBox.x, status.outputs[i].trackedBox.y, status.outputs[i].trackedBox.w, status.outputs[i].trackedBox.h)
    info = {
        "capture-possible"      : bool(status.bIsCapturePossible),
        "currently-capturing"   : bool(status.bCurrentlyCapturing),
        "can-create-now"        : bool(status.bCanCreateNow),
        "randr"                 : bool(status.bXRandRAvailable),
        "screen-size"           : (status.screenSize.w, status.screenSize.h),
        "outputs"               : outputs,
        "version"               : status.dwNvFBCVersion,
        }
    log("get_context_status()=%s", info)
    return info

cdef get_frame_grab_info(NVFBC_FRAME_GRAB_INFO *grab_info):
    return {
        "width"             : int(grab_info.dwWidth),
        "height"            : int(grab_info.dwHeight),
        "size"              : int(grab_info.dwByteSize),
        "current-frame"     : int(grab_info.dwCurrentFrame),
        "new-frame"         : bool(grab_info.bIsNewFrame),
        }

cdef NVFBC_SESSION_HANDLE create_context() except 0xffffffff:
    cdef NVFBC_SESSION_HANDLE context = 0
    cdef NVFBC_CREATE_HANDLE_PARAMS params
    cdef NVFBCSTATUS ret = <NVFBCSTATUS> 0
    cdef char* ckey
    keys = CLIENT_KEYS_STRS or [None]
    log("create_context() will try with keys: %s", csv(keys))
    assert len(keys)>0
    for key in keys:
        memset(&params, 0, sizeof(NVFBC_CREATE_HANDLE_PARAMS))
        params.dwVersion = NVFBC_CREATE_HANDLE_PARAMS_VER
        if key:
            binkey = parse_nvfbc_hex_key(key)
            ckey = binkey
            params.privateData = <void*> ckey
            params.privateDataSize = len(ckey)
            log("create_context() key data=%#x, size=%i", <uintptr_t> ckey, len(ckey))
        ret = function_list.nvFBCCreateHandle(&context, &params)
        log("create_context() NvFBCCreateHandle()=%i for key=%s", ret, key)
        if ret==0:
            #success!
            break
    raiseNvFBC(context, ret, "NvFBCCreateHandle")
    log("NvFBCCreateHandle: handle=%#x", context)
    return context

cdef close_context(NVFBC_SESSION_HANDLE context):
    cdef NVFBC_DESTROY_HANDLE_PARAMS params
    params.dwVersion = NVFBC_DESTROY_HANDLE_PARAMS_VER
    cdef NVFBCSTATUS ret = function_list.nvFBCDestroyHandle(context, &params)
    raiseNvFBC(context, ret, "NvFBCDestroyHandle")

cdef create_capture_session(NVFBC_SESSION_HANDLE context, NVFBC_CAPTURE_TYPE capture_type, w=0, h=0):
    cdef NVFBC_CREATE_CAPTURE_SESSION_PARAMS create
    memset(&create, 0, sizeof(NVFBC_CREATE_CAPTURE_SESSION_PARAMS))
    create.dwVersion = NVFBC_CREATE_CAPTURE_SESSION_PARAMS_VER
    create.eCaptureType = capture_type  #NVFBC_CAPTURE_TO_SYS
    create.eTrackingType = NVFBC_TRACKING_SCREEN
    create.dwOutputId = 0
    #create.captureBox.x = ...
    if w>0 and h>0:
        create.frameSize.w = w
        create.frameSize.h = h
    create.bWithCursor = <NVFBC_BOOL> False
    create.bDisableAutoModesetRecovery = <NVFBC_BOOL> False
    cdef NVFBCSTATUS ret = function_list.nvFBCCreateCaptureSession(context, &create)
    raiseNvFBC(context, ret, "NvFBCCreateCaptureSession")
    log("NvFBCCreateCaptureSession() success")

cdef destroy_session(NVFBC_SESSION_HANDLE context):
    cdef NVFBC_DESTROY_CAPTURE_SESSION_PARAMS params
    memset(&params, 0, sizeof(NVFBC_DESTROY_CAPTURE_SESSION_PARAMS))
    params.dwVersion = NVFBC_DESTROY_CAPTURE_SESSION_PARAMS_VER
    cdef NVFBCSTATUS ret = function_list.nvFBCDestroyCaptureSession(context, &params)
    raiseNvFBC(context, ret, "NvFBCDestroyCaptureSession")
    log("NvFBCDestroyCaptureSession() success")


def get_version():
    return int(NVFBC_VERSION_MAJOR), int(NVFBC_VERSION_MINOR)

def get_type():
    return "nvfbc"

def get_info():
    info = {
            "type"              : "nvfbc",
            "version"           : get_version(),
            }
    cards = get_cards()
    if cards:
        info["cards"] = cards
    #only show the version if we have it already (don't probe now)
    v = get_nvidia_module_version(False)
    if v:
        info["kernel_module_version"] = v
    return info


PIXEL_FORMAT_CONST = {
    "XRGB"      : NVFBC_BUFFER_FORMAT_ARGB,
    "BGRX"      : NVFBC_BUFFER_FORMAT_BGRA,
    "RGB"       : NVFBC_BUFFER_FORMAT_RGB,
    "YUV420P"   : NVFBC_BUFFER_FORMAT_YUV420P,
    "YUV444P"   : NVFBC_BUFFER_FORMAT_YUV444P,
    }


cdef class NvFBC_SysCapture:
    cdef NVFBC_SESSION_HANDLE context
    cdef uintptr_t framebuffer
    cdef int has_context
    cdef int has_session
    cdef object pixel_format
    cdef NVFBC_FRAME_GRAB_INFO grab_info
    cdef NVFBC_TOSYS_GRAB_FRAME_PARAMS grab

    cdef object __weakref__

    def init_context(self, int width=-1, int height=-1, pixel_format=SYS_PIXEL_FORMAT):
        log("init_context(%i, %i, %s)", width, height, pixel_format)
        global PIXEL_FORMAT_CONST, INIT_DONE
        assert INIT_DONE, "module not initialized"
        if pixel_format not in PIXEL_FORMAT_CONST:
            raise Exception("unsupported pixel format '%s'" % pixel_format)
        cdef NVFBC_BUFFER_FORMAT buffer_format = PIXEL_FORMAT_CONST[pixel_format]
        log("NVFBC_BUFFER_FORMAT for %s: %i", pixel_format, buffer_format)
        self.pixel_format = pixel_format
        self.context = create_context()
        self.has_context = True
        get_context_status(self.context)
        create_capture_session(self.context, NVFBC_CAPTURE_TO_SYS)
        self.has_session = True
        cdef NVFBC_TOSYS_SETUP_PARAMS params
        memset(&params, 0, sizeof(NVFBC_TOSYS_SETUP_PARAMS))
        params.dwVersion = NVFBC_TOSYS_SETUP_PARAMS_VER
        params.eBufferFormat = buffer_format
        params.ppBuffer = <void**> &self.framebuffer
        params.bWithDiffMap = <NVFBC_BOOL> False
        params.ppDiffMap = NULL
        params.dwDiffMapScalingFactor = 1
        ret = function_list.nvFBCToSysSetUp(self.context, &params)
        log("nvFBCToSysSetUp()=%i", ret)
        self.raiseNvFBC(ret, "NvFBCToSysSetUp")

    def raiseNvFBC(self, NVFBCSTATUS ret, msg):
        raiseNvFBC(self.context, ret, msg)

    def get_info(self):
        info = get_info()
        info["pixel-format"] = self.pixel_format
        return info

    def get_type(self):
        return  "nvfbc-sys"

    def __repr__(self):
        return "NvFBC_SysCapture(%#x)" % (<uintptr_t> self.context)

    def __dealloc__(self):
        self.clean()

    def refresh(self):
        cdef double start = monotonic_time()
        memset(&self.grab_info, 0, sizeof(NVFBC_FRAME_GRAB_INFO))
        memset(&self.grab, 0, sizeof(NVFBC_TOSYS_GRAB_FRAME_PARAMS))
        self.grab.dwVersion = NVFBC_TOSYS_GRAB_FRAME_PARAMS_VER
        self.grab.dwFlags = NVFBC_TOSYS_GRAB_FLAGS_NOWAIT
        self.grab.pFrameGrabInfo = &self.grab_info
        cdef NVFBCSTATUS ret
        with nogil:
            ret = function_list.nvFBCToSysGrabFrame(self.context, &self.grab)
        self.raiseNvFBC(ret, "NvFBCToSysGrabFrame")
        log("NvFBCToSysGrabFrame(%#x)=%i", <uintptr_t> &self.grab, ret)
        cdef double end = monotonic_time()
        log("NvFBCToSysGrabFrame: framebuffer=%#x, info=%s, elapsed=%ims", <uintptr_t> self.framebuffer, get_frame_grab_info(&self.grab_info), int((end-start)*1000))
        return bool(self.grab_info.bIsNewFrame)

    def get_image(self, unsigned int x=0, unsigned int y=0, unsigned int width=0, unsigned int height=0):
        log("get_image%s", (x, y, width, height))
        assert x>=0 and y>=0 and width>0 and height>0
        assert x+width<=self.grab_info.dwWidth, "invalid capture width: %i+%i, capture size is only %i" % (x, width, self.grab_info.dwWidth)
        assert y+height<=self.grab_info.dwHeight, "invalid capture height: %i+%i, capture size is only %i" % (y, height, self.grab_info.dwHeight)
        cdef double start = monotonic_time()
        #TODO: only copy when the next frame is going to overwrite the buffer,
        #or when closing the context
        cdef unsigned int Bpp = len(self.pixel_format)    # ie: "BGR" -> 3
        cdef unsigned int grab_stride = self.grab_info.dwWidth*Bpp
        cdef unsigned int stride = grab_stride
        cdef MemBuf buf
        cdef uintptr_t buf_ptr = 0
        cdef uintptr_t grab_ptr = <uintptr_t> (self.framebuffer+x*Bpp+y*grab_stride)
        if x>0 or y>0 or self.grab_info.dwWidth-width>16 or self.grab_info.dwHeight-height>16:
            #copy sub-image with smaller stride:
            stride = roundup(width*Bpp, 16)
            buf = padbuf(stride*height, stride)
            buf_ptr = <uintptr_t> buf.get_mem()
            with nogil:
                for _ in range(height):
                    memcpy(<void *> buf_ptr, <void *> grab_ptr, width*Bpp)
                    grab_ptr += grab_stride
                    buf_ptr += stride
        else:
            #copy whole:
            size = self.grab_info.dwByteSize
            buf = padbuf(size, stride)
            buf_ptr = <uintptr_t> buf.get_mem()
            with nogil:
                memcpy(<void *> buf_ptr, <void *> grab_ptr, size)
        image = ImageWrapper(0, 0, width, height, memoryview(buf), self.pixel_format, Bpp*8, stride, Bpp)
        end = monotonic_time()
        log("image=%s buffer len=%i, (copy took %ims)", image, len(buf), int((end-start)*1000))
        return image

    def clean(self):                        #@DuplicatedSignature
        log("clean()")
        if self.has_context:
            if self.has_session:
                destroy_session(self.context)
            self.has_context = False
            close_context(self.context)


cdef class NvFBC_CUDACapture:
    cdef NVFBC_SESSION_HANDLE context
    cdef int setup
    cdef object pixel_format
    cdef int cuda_device_id
    cdef object cuda_device
    cdef object cuda_context
    cdef CUdeviceptr cuDevicePtr
    cdef NVFBC_FRAME_GRAB_INFO grab_info
    cdef NVFBC_TOCUDA_GRAB_FRAME_PARAMS grab
    cdef unsigned long frames
    cdef object images

    cdef object __weakref__

    def init_context(self, int width=-1, int height=-1, pixel_format=CUDA_PIXEL_FORMAT):
        log("init_context(%i, %i, %s)", width, height, pixel_format)
        assert select_device, "CUDA is missing"
        if pixel_format not in PIXEL_FORMAT_CONST:
            raise Exception("unsupported pixel format '%s'" % pixel_format)
        cdef NVFBC_BUFFER_FORMAT buffer_format = PIXEL_FORMAT_CONST[pixel_format]
        self.pixel_format = pixel_format
        #CUDA init:
        self.cuda_device_id, self.cuda_device = select_device()
        if not self.cuda_device:
            raise Exception("no valid CUDA device")
        d = self.cuda_device
        cf = driver.ctx_flags
        self.images = WeakSet()
        self.frames = 0
        self.cuDevicePtr = 0
        self.cuda_context = d.make_context(flags=cf.SCHED_AUTO)
        assert self.cuda_context, "failed to create a CUDA context for device %s" % device_info(d)
        self.context = create_context()
        get_context_status(self.context)
        create_capture_session(self.context, NVFBC_CAPTURE_SHARED_CUDA)
        cdef NVFBC_TOCUDA_SETUP_PARAMS params
        memset(&params, 0, sizeof(NVFBC_TOCUDA_SETUP_PARAMS))
        params.dwVersion = NVFBC_TOCUDA_SETUP_PARAMS_VER
        params.eBufferFormat = buffer_format
        cdef NVFBCSTATUS res = <NVFBCSTATUS> function_list.nvFBCToCudaSetUp(self.context, &params)
        self.raiseNvFBC(res, "NvFBCCudaSetup")
        log("nvFBCToCudaSetUp()=%i", res)
        self.setup = True

    def raiseNvFBC(self, NVFBCSTATUS ret, msg):
        raiseNvFBC(self.context, ret, msg)

    def get_info(self):
        info = get_info()
        info["pixel-format"] = self.pixel_format
        return info

    def get_type(self):
        return  "nvfbc-cuda"

    def __repr__(self):
        return "NvFBC_CUDACapture(%#x)" % (<uintptr_t> self.context)

    def __dealloc__(self):
        self.clean()

    def refresh(self):
        cdef double start = monotonic_time()
        memset(&self.grab_info, 0, sizeof(NVFBC_FRAME_GRAB_INFO))
        memset(&self.grab, 0, sizeof(NVFBC_TOCUDA_GRAB_FRAME_PARAMS))
        self.grab.dwVersion = NVFBC_TOCUDA_GRAB_FRAME_PARAMS_VER
        self.grab.pCUDADeviceBuffer = &self.cuDevicePtr
        self.grab.pFrameGrabInfo = &self.grab_info
        self.grab.dwFlags = NVFBC_TOCUDA_GRAB_FLAGS_NOWAIT
        cdef NVFBCSTATUS res
        with nogil:
            res = function_list.nvFBCToCudaGrabFrame(self.context, &self.grab)
        if res<0:
            self.raiseNvFBC(res, "NvFBCToSysGrabFrame")
        elif res!=0:
            raise Exception("CUDA Grab Frame failed: %s" % CUDA_ERRORS_INFO.get(res, res))
        cdef double end = monotonic_time()
        log("NvFBCCudaGrabFrame: cuDevicePtr=%#x, info=%s, elapsed=%ims", <uintptr_t> self.cuDevicePtr, get_frame_grab_info(&self.grab_info), int((end-start)*1000))
        return bool(self.grab_info.bIsNewFrame)

    def get_image(self, unsigned int x=0, unsigned int y=0, unsigned int width=0, unsigned int height=0):
        log("nvfbc cuda get_image%s", (x, y, width, height))
        assert self.cuDevicePtr
        assert x>=0 and y>=0 and width>0 and height>0
        assert x+width<=self.grab_info.dwWidth, "invalid capture width: %i+%i, capture size is only %i" % (x, width, self.grab_info.dwWidth)
        assert y+height<=self.grab_info.dwHeight, "invalid capture height: %i+%i, capture size is only %i" % (y, height, self.grab_info.dwHeight)
        #allocate CUDA device memory:
        cdef int Bpp = len(self.pixel_format)    # ie: "BGR" -> 3
        stream = driver.Stream()
        cdef int src_pitch = int(self.grab_info.dwWidth*Bpp)
        dst_pitch = roundup(width*Bpp, 16)
        buffer_size = height*dst_pitch
        cuda_device_buffer = driver.mem_alloc(buffer_size)
        assert cuda_device_buffer
        free, total = driver.mem_get_info()
        log("nvfbc cuda buffer_size=%s, cuda device buffer=%#x, pitch=%i - device memory: free=%iMB, total=%iMB", buffer_size, int(cuda_device_buffer), dst_pitch, free//1024//1024, total//1024//1024)
        log("Memcpy2D: from %#x to %#x, size=%s, frame=%i, allocated images: %i", int(self.cuDevicePtr), int(cuda_device_buffer), buffer_size, self.frames, len(self.images))
        copy = driver.Memcpy2D()
        copy.set_src_device(int(self.cuDevicePtr))
        copy.src_x_in_bytes = x*Bpp
        copy.src_y = y
        copy.src_pitch = src_pitch
        copy.width_in_bytes = width*Bpp
        copy.height = height
        copy.set_dst_device(cuda_device_buffer)
        copy.dst_x_in_bytes = 0
        copy.dst_y = 0
        copy.dst_pitch = dst_pitch
        copy(stream)
        image = CUDAImageWrapper(0, 0, width, height, None, self.pixel_format, Bpp*8, dst_pitch, Bpp, ImageWrapper.PACKED, False, None)
        image.stream = stream
        image.cuda_device_buffer = cuda_device_buffer
        image.cuda_context = self.cuda_context
        image.buffer_size = buffer_size
        self.frames += 1
        self.images.add(image)
        return image

    def clean(self):                        #@DuplicatedSignature
        cuda_context = self.cuda_context
        self.cuda_context = None
        cdef NVFBC_SESSION_HANDLE context = self.context
        self.context = 0
        images = tuple(self.images)
        log("%s.clean() setup=%s, cuDevicePtr=%#x, cuda_context=%s, nvfbc context=%#x, images=%s", self, self.setup, self.cuDevicePtr, cuda_context, context, images)
        self.cuDevicePtr = 0
        self.images = WeakSet()
        for image in images:
            image.clean()
        if cuda_context:
            try:
                cuda_context.push()
            except:
                log("%s.push()", cuda_context, exc_info=True)
        if self.setup:
            self.setup = False
            if context:
                close_context(context)
        if cuda_context:
            try:
                cuda_context.pop()
                cuda_context.detach()
            except:
                log("%s.pop() or detach()", cuda_context, exc_info=True)


def init_module():
    log("nvfbc.init_module()")
    init_nvfbc_library()

def cleanup_module():
    log("nvfbc.cleanup_module()")
    unload_library()

def selftest(full=False):
    pass
