# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import os
import sys
from time import monotonic
from typing import Any, Dict

from xpra.os_util import WIN32
from xpra.util.str_fn import csv
from xpra.common import roundup
from xpra.codecs.constants import TransientCodecException, CodecStateException
from xpra.codecs.image import ImageWrapper
from xpra.codecs.nvidia.cuda.image import CUDAImageWrapper
from xpra.codecs.nvidia.util import get_nvidia_module_version, get_cards, get_license_keys, parse_nvfbc_hex_key

from xpra.log import Logger
log = Logger("encoder", "nvfbc")

#we can import pycuda safely here,
#because importing CUDAImageWrapper will have imported pycuda with the lock
try:
    from pycuda import driver
    from xpra.codecs.nvidia.cuda.context import select_device, device_info
    from xpra.codecs.nvidia.cuda.errors import get_error_name
except ImportError:
    raise
except Exception as e:
    log.error("Error: NvFBC requires CUDA", exc_info=True)
    raise ImportError("NvFBC requires CUDA: %s" % e) from None

import ctypes
from ctypes import wintypes

from libc.stdint cimport uintptr_t, uint8_t, int64_t   # pylint: disable=syntax-error
from libc.string cimport memset, memcpy
from xpra.buffers.membuf cimport padbuf, MemBuf

DEFAULT_PIXEL_FORMAT = os.environ.get("XPRA_NVFBC_DEFAULT_PIXEL_FORMAT", "RGB")
CLIENT_KEYS_STRS = get_license_keys(basefilename="nvfbc")


ctypedef unsigned long DWORD
ctypedef int BOOL


cdef extern from "NvFBC/nvFBC.h":
    ctypedef int NVFBCRESULT
    ctypedef unsigned long NvU32

    int NVFBC_DLL_VERSION
    int NVFBC_GLOBAL_FLAGS_NONE
    #deprecated:
    #int NVFBC_GLOBAL_FLAGS_STEREO_BUFFER
    int NVFBC_GLOBAL_FLAGS_NO_INITIAL_REFRESH
    int NVFBC_GLOBAL_FLAGS_NO_DEVICE_RESET_TOGGLE

    int NVFBC_CREATE_PARAMS_VER
    int NVFBC_STATUS_VER
    int NVFBC_CURSOR_CAPTURE_PARAMS_VER

    NVFBCRESULT NVFBC_SUCCESS
    NVFBCRESULT NVFBC_ERROR_GENERIC                     # Unexpected failure in NVFBC.
    NVFBCRESULT NVFBC_ERROR_INVALID_PARAM               # One or more of the parameters passed to NvFBC are invalid [This include NULL pointers].
    NVFBCRESULT NVFBC_ERROR_INVALIDATED_SESSION         # NvFBC session is invalid. Client needs to recreate session.
    NVFBCRESULT NVFBC_ERROR_PROTECTED_CONTENT           # Protected content detected. Capture failed.
    NVFBCRESULT NVFBC_ERROR_DRIVER_FAILURE              # GPU driver returned failure to process NvFBC command.
    NVFBCRESULT NVFBC_ERROR_CUDA_FAILURE                # CUDA driver returned failure to process NvFBC command.
    NVFBCRESULT NVFBC_ERROR_UNSUPPORTED                 # API Unsupported on this version of NvFBC.
    NVFBCRESULT NVFBC_ERROR_HW_ENC_FAILURE              # HW Encoder returned failure to process NVFBC command.
    NVFBCRESULT NVFBC_ERROR_INCOMPATIBLE_DRIVER         # NVFBC is not compatible with this version of the GPU driver.
    NVFBCRESULT NVFBC_ERROR_UNSUPPORTED_PLATFORM        # NVFBC is not supported on this platform.
    NVFBCRESULT NVFBC_ERROR_OUT_OF_MEMORY               # Failed to allocate memory.
    NVFBCRESULT NVFBC_ERROR_INVALID_PTR                 # A NULL pointer was passed.
    NVFBCRESULT NVFBC_ERROR_INCOMPATIBLE_VERSION        # An API was called with a parameter struct that has an incompatible version. Check dwVersion field of parameter struct.
    NVFBCRESULT NVFBC_ERROR_OPT_CAPTURE_FAILURE         # Desktop Capture failed.
    NVFBCRESULT NVFBC_ERROR_INSUFFICIENT_PRIVILEGES     # User doesn't have appropriate previlages.
    NVFBCRESULT NVFBC_ERROR_INVALID_CALL                # NVFBC APIs called in wrong sequence.
    NVFBCRESULT NVFBC_ERROR_SYSTEM_ERROR                # Win32 error.
    NVFBCRESULT NVFBC_ERROR_INVALID_TARGET              # The target adapter idx can not be used for NVFBC capture. It may not correspond to an NVIDIA GPU, or may not be attached to desktop.
    NVFBCRESULT NVFBC_ERROR_NVAPI_FAILURE               # NvAPI Error
    NVFBCRESULT NVFBC_ERROR_DYNAMIC_DISABLE             # NvFBC is dynamically disabled. Cannot continue to capture
    NVFBCRESULT NVFBC_ERROR_IPC_FAILURE                 # NVFBC encountered an error in state management
    NVFBCRESULT NVFBC_ERROR_CURSOR_CAPTURE_FAILURE      # Hardware cursor capture failed


    ctypedef int NVFBC_STATE
    NVFBC_STATE NVFBC_STATE_DISABLE
    NVFBC_STATE NVFBC_STATE_ENABLE

    # Defines parameters that describe the grabbed data,
    # and provides detailed information about status of the NVFBC session.
    ctypedef struct NvFBCFrameGrabInfo:
        DWORD   dwWidth                 #[out] Indicates the current width of captured buffer.
        DWORD   dwHeight                #[out] Indicates the current height of captured buffer.
        DWORD   dwBufferWidth           #[out] Indicates the current width of the pixel buffer(padded width).
        DWORD   dwReserved              #[out] Reserved, do not use.
        BOOL    bOverlayActive          #[out] Is set to 1 if overlay was active.
        BOOL    bMustRecreate           #[out] Is set to 1 if the compressor must call NvBFC_Create again.
        BOOL    bFirstBuffer            #[out] Is set to 1 is this was the first capture call, or first call after a desktop mode change.
                                        # Relevant only for XOR and diff modes supported by NVFBCToSys interface.
        BOOL    bHWMouseVisible         #[out] Is set to 1 if HW cursor was enabled by OS at the time of the grab.
        BOOL    bProtectedContent       #[out] Is set to 1 if protected content was active (DXVA encryption Session).
        DWORD   dwDriverInternalError   #[out] To be used as diagnostic info if Grab() fails. Status is non-fatal if Grab() returns success.
                                        # Indicates the status code from lower layers. 0 or 0xFBCA11F9 indicates no error was returned.
        BOOL    bStereoOn               #[out] Is set to 1 if stereo was on.
        BOOL    bIGPUCapture            #[out] Is set to 1 if the captured frame is from iGPU. 0 if capture fails or if captured from dGPU*/
        DWORD   dwSourcePID             #[out] Indicates which process caused the last screen update that got grabbed*/
        DWORD   dwReserved3             #[out] Reserved, do not use.
        DWORD   bIsHDR                  #[out] Is set to 1 if grabbed content is in HDR format.
        #DWORD   bReservedBit1           #[out] Reserved, do not use.
        #DWORD   bReservedBits           #[out] Reserved, do not use.
        DWORD   dwWaitModeUsed          #[out] The mode used for this Grab operation (blocking or non-blocking), based on the grab flags passed by the application.
                                        # Actual blocking mode can differ from application's request if incorrect grab flags are passed.
        #NvU32   dwReserved2[11]         #[out] Resereved, should be set to 0.

    # Defines the parameters to be used with NvFBC_GetStatusEx API
    ctypedef struct NvFBCStatusEx:
        NvU32  dwVersion                #[in]  Struct version. Set to NVFBC_STATUS_VER.
        NvU32  bIsCapturePossible       #[out] Indicates if NvFBC feature is enabled.
        NvU32  bCurrentlyCapturing      #[out] Indicates if NVFBC is currently capturing for the Adapter ordinal specified in dwAdapterIdx.
        NvU32  bCanCreateNow            #[out] Deprecated. Do not use.
        NvU32  bSupportMultiHead        #[out] MultiHead grab supported.
        NvU32  bSupportConfigurableDiffMap     #[out] Difference map with configurable blocksize supported. Supported sizes 16x16, 32x32, 64x64, 128x128(default)
        NvU32  bSupportImageClassification     #[out] Generation of 'classification map' demarkating high frequency content in the captured image is supported
        #NvU32  bReservedBits            #[in]  Reserved, do not use.
        NvU32  dwNvFBCVersion           #[out] Indicates the highest NvFBC interface version supported by the loaded NVFBC library.
        NvU32  dwAdapterIdx             #[in]  Adapter Ordinal corresponding to the display to be grabbed. IGNORED if bCapturePID is set
        void*  pPrivateData             #[in]  optional **/
        NvU32  dwPrivateDataSize        #[in]  optional **/
        NvU32  dwReserved[59]           #[in]  Reserved. Should be set to 0.
        void*  pReserved[31]            #[in]  Reserved. Should be set to NULL.

    # Defines the parameters to be used with NvFBC_CreateEx API
    ctypedef struct NvFBCCreateParams:
        NvU32  dwVersion                #[in]  Struct version. Set to NVFBC_CREATE_PARAMS_VER.
        NvU32  dwInterfaceType          #[in]  ID of the NVFBC interface Type being requested.
        NvU32  dwMaxDisplayWidth        #[out] Max. display width allowed.
        NvU32  dwMaxDisplayHeight       #[out] Max. display height allowed.
        void*  pDevice                  #[in]  Device pointer.
        void*  pPrivateData             #[in]  Private data [optional].
        NvU32  dwPrivateDataSize        #[in]  Size of private data.
        NvU32  dwInterfaceVersion       #[in]  Version of the capture interface.
        void*  pNvFBC                   #[out] A pointer to the requested NVFBC object.
        NvU32  dwAdapterIdx             #[in]  Adapter Ordinal corresponding to the display to be grabbed. If pDevice is set, this parameter is ignored.
        NvU32  dwNvFBCVersion           #[out] Indicates the highest NvFBC interface version supported by the loaded NVFBC library.
        void*  cudaCtx                  #[in]  CUDA context created using cuD3D9CtxCreate with the D3D9 device passed as pDevice. Only used for NvFBCCuda interface.
                                        # It is mandatory to pass a valid D3D9 device if cudaCtx is passed. The call will fail otherwise.
                                        # Client must release NvFBCCuda object before destroying the cudaCtx.
        void*  pPrivateData2            #[in]  Private data [optional].
        NvU32  dwPrivateData2Size       #[in]  Size of private data.
        #NvU32  dwReserved[55]           #[in]  Reserved. Should be set to 0.
        #void*  pReserved[27]            #[in]  Reserved. Should be set to NULL.

    # Defines parameters for a Grab\Capture call to get HW cursor data in the NVFBCToSys capture session
    ctypedef struct NVFBC_CURSOR_CAPTURE_PARAMS:
        NvU32 dwVersion                 #[in]:  Struct version. Set to NVFBC_MOUSE_GRAB_INFO_VER
        NvU32 dwWidth                   #[out]: Width of mouse glyph captured
        NvU32 dwHeight                  #[out]: Height of mouse glyph captured
        NvU32 dwPitch                   #[out]: Pitch of mouse glyph captured
        NvU32 bIsHwCursor               #[out]: Tells if cursor is HW cursor or SW cursor. If set to 0, ignore height, width, pitch and pBits
        #NvU32 bReserved : 32           #[in]:  Reserved
        NvU32 dwPointerFlags            #[out]: Maps to DXGK_POINTERFLAGS::Value
        NvU32 dwXHotSpot                #[out]: Maps to DXGKARG_SETPOINTERSHAPE::XHot
        NvU32 dwYHotSpot                #[out]: Maps to DXGKARG_SETPOINTERSHAPE::YHot
        NvU32 dwUpdateCounter           #[out]: Cursor update Counter.
        NvU32 dwBufferSize              #[out]: Size of the buffer contaiing the captured cursor glyph.
        void * pBits                    #[out]: pointer to buffer containing the captured cursor glyph
        NvU32 dwReservedA[22]           #[in]:  Reserved. Set to 0
        void * pReserved[15]            #[in]:  Reserved. Set to 0

    # NVFBC API to set global overrides
    # param [in] dwFlags Global overrides for NVFBC. Use ::NVFBC_GLOBAL_FLAGS value.
    void NvFBC_SetGlobalFlags(DWORD dwFlags)

    # NVFBC API to create an NVFBC capture session.
    # Instantiates an interface identified by NvFBCCreateParams::dwInterfaceType.
    # param [inout] pCreateParams Pointer to a struct of type ::NvFBCCreateParams, typecast to void*
    # return An applicable ::NVFBCRESULT value.
    NVFBCRESULT NvFBC_CreateEx(void * pCreateParams)

    # NVFBC API to query Current NVFBC status.
    # Queries the status for the adapter pointed to by the NvFBCStatusEx::dwAdapterIdx parameter.
    # [inout] pCreateParams Pointer to a struct of type ::NvFBCStatusEx.
    # return An applicable ::NVFBCRESULT value.
    NVFBCRESULT NvFBC_GetStatusEx(NvFBCStatusEx *pNvFBCStatusEx)

    # NVFBC API to enable \ disable NVFBC feature.
    # param [in] nvFBCState Refer ::NVFBC_STATE
    # return An applicable ::NVFBCRESULT value.
    NVFBCRESULT NvFBC_Enable(NVFBC_STATE nvFBCState)

    # NVFBC API to query highest GRID SDK version supported by the loaded NVFBC library.
    # param [out] pVersion Pointer to a 32-bit integer to hold the supported GRID SDK version.
    # return An applicable ::NVFBCRESULT value.
    NVFBCRESULT NvFBC_GetSDKVersion(NvU32 * pVersion)


cdef extern from "NvFBC/nvFBCToSys.h":
    int NVFBC_TO_SYS
    int NVFBC_SHARED_CUDA
    int NVFBC_TOSYS_SETUP_PARAMS_VER
    int NVFBC_TOSYS_GRAB_FRAME_PARAMS_VER

    ctypedef int NVFBCToSysBufferFormat
    NVFBCToSysBufferFormat NVFBC_TOSYS_ARGB         # 32bpp, one byte per channel.
    NVFBCToSysBufferFormat NVFBC_TOSYS_RGB          # 24bpp, one byte per channel.
    NVFBCToSysBufferFormat NVFBC_TOSYS_YYYYUV420p   # 12bpp, the Y' channel at full resolution, U channel at half resolution (1 byte for four pixels), V channel at half resolution.
    NVFBCToSysBufferFormat NVFBC_TOSYS_RGB_PLANAR   # 24bpp, stored sequentially in memory as complete red channel, complete green channel, complete blue channel.
    NVFBCToSysBufferFormat NVFBC_TOSYS_XOR          # RGB format: 24bpp XOR�d with the prior frame.
    NVFBCToSysBufferFormat NVFBC_TOSYS_YUV444p      # Output Pixels in YUV444 planar format, i.e. separate 8-bpp Y, U, V planes with no subsampling.
    NVFBCToSysBufferFormat NVFBC_TOSYS_ARGB10       # RGB 10 bit format: A2B10G10R10, 32bpp.

    ctypedef int  NVFBCToSysGrabMode
    NVFBCToSysGrabMode NVFBC_TOSYS_SOURCEMODE_FULL  # Grab full res
    NVFBCToSysGrabMode NVFBC_TOSYS_SOURCEMODE_SCALE # Will convert current res to supplied resolution (dwTargetWidth and dwTargetHeight)
    NVFBCToSysGrabMode NVFBC_TOSYS_SOURCEMODE_CROP  # Native res, crops a subwindow, of dwTargetWidth and dwTargetHeight sizes, starting at dwStartX and dwStartY

    ctypedef int NVFBC_TOSYS_GRAB_FLAGS
    NVFBC_TOSYS_GRAB_FLAGS NVFBC_TOSYS_NOFLAGS      # Default (no flags set). Grabbing will wait for a new frame or HW mouse move.
    NVFBC_TOSYS_GRAB_FLAGS NVFBC_TOSYS_NOWAIT       # Grabbing will not wait for a new frame nor a HW cursor move.
    NVFBC_TOSYS_GRAB_FLAGS NVFBC_TOSYS_WAIT_WITH_TIMEOUT # Grabbing will wait for a new frame or HW mouse move with a maximum wait time of NVFBC_TOSYS_GRAB_FRAME_PARAMS::dwWaitTime millisecond

    ctypedef struct NVFBC_TOSYS_SETUP_PARAMS_V2:
        NvU32 dwVersion                             #[in]: Struct version. Set to NVFBC_TOSYS_SETUP_PARAMS_VER
        NvU32 bWithHWCursor                         #[in]: The client should set this to 1 if it requires the HW cursor to be composited on the captured image
        NvU32 bDiffMap                              #[in]: The client should set this to use the DiffMap feature
        NvU32 bEnableSeparateCursorCapture          #[in]: The client should set this to 1 if it wants to enable mouse capture in separate stream
        NvU32 bHDRRequest                           #[in]: The client should set this to 1 to request HDR capture
        NvU32 b16x16DiffMap                         #[in]: Valid only if bDiffMap is set. The client should set this to 1 it it wants to request 16x16 Diffmap, set it to 0 if it wants 128x128 Diffmap
        #NvU32 bReservedBits :27                     #[in]: Reserved. Set to 0
        NVFBCToSysBufferFormat eMode                #[in]: Output image format
        #NvU32 dwReserved1                           #[in]: Reserved. Set to 0
        void **ppBuffer                             #[out]: Container to hold NvFBC output buffers
        void **ppDiffMap                            #[out]: Container to hold NvFBC output diffmap buffers
        void  *hCursorCaptureEvent                  #[out]: Client should wait for mouseEventHandle event before calling MouseGrab function. */
        #NvU32 dwReserved[58]                        #[in]: Reserved. Set to 0
        #void *pReserved[29]                         #[in]: Reserved. Set to 0
    ctypedef NVFBC_TOSYS_SETUP_PARAMS_V2 NVFBC_TOSYS_SETUP_PARAMS

    ctypedef struct NVFBC_TOSYS_GRAB_FRAME_PARAMS_V1:
        NvU32 dwVersion                             #[in]: Struct version. Set to NVFBC_TOSYS_GRAB_FRAME_PARAMS_VER.
        NvU32 dwFlags                               #[in]: Special grabbing requests. This should be a bit-mask of NVFBC_TOSYS_GRAB_FLAGS values.
        NvU32 dwTargetWidth                         #[in]: Target image width. NvFBC will scale the captured image to fit taret width and height. Used with NVFBC_TOSYS_SOURCEMODE_SCALE and NVFBC_TOSYS_SOURCEMODE_CROP.
        NvU32 dwTargetHeight                        #[in]: Target image height. NvFBC will scale the captured image to fit taret width and height. Used with NVFBC_TOSYS_SOURCEMODE_SCALE and NVFBC_TOSYS_SOURCEMODE_CROP.
        NvU32 dwStartX                              #[in]: x-coordinate of starting pixel for cropping. Used with NVFBC_TOSYS_SOURCEMODE_CROP.
        NvU32 dwStartY                              #[in]: y-coordinate of starting pixel for cropping. Used with NVFBC_TOSYS_SOURCEMODE_CROP.
        NVFBCToSysGrabMode eGMode                   #[in]: Frame grab mode.
        NvU32 dwWaitTime                            #[in]: Time limit for NvFBCToSysGrabFrame() to wait until a new frame is available or a HW mouse moves. Use with NVFBC_TOSYS_WAIT_WITH_TIMEOUT
        NvFBCFrameGrabInfo *pNvFBCFrameGrabInfo     #[in/out]: Frame grab information and feedback from NvFBC driver.
        NvU32 dwReserved[56]                        #[in]: Reserved. Set to 0.
        void *pReserved[31]                         #[in]: Reserved. Set to NULL.
    ctypedef NVFBC_TOSYS_GRAB_FRAME_PARAMS_V1 NVFBC_TOSYS_GRAB_FRAME_PARAMS

    # Sets up NVFBC System Memory capture according to the provided parameters.
    # [in] pParam Pointer to a struct of type ::NVFBC_TOSYS_SETUP_PARAMS.
    ctypedef NVFBCRESULT (*NVFBCTOSYSSETUP) (NVFBC_TOSYS_SETUP_PARAMS *pParam) nogil
    # Captures the desktop and dumps the captured data to a System memory buffer.
    # If the API returns a failure, the client should check the return codes and
    # ::NvFBCFrameGrabInfo output fields to determine if the session needs to be re-created.
    # [inout] pParam Pointer to a struct of type ::NVFBC_TOSYS_GRAB_FRAME_PARAMS.
    ctypedef NVFBCRESULT (*NVFBCTOSYSGRABFRAME) (NVFBC_TOSYS_GRAB_FRAME_PARAMS *pParam) nogil
    # Captures HW cursor data whenever shape of mouse is changed
    # [inout] pParam Pointer to a struct of type ::NVFBC_CURSOR_CAPTURE_PARAMS
    ctypedef NVFBCRESULT (*NVFBCTOSYSCURSORCAPTURE) (NVFBC_CURSOR_CAPTURE_PARAMS *pParam) nogil
    # A high precision implementation of Sleep().
    # Can provide sub quantum (usually 16ms) sleep that does not burn CPU cycles.
    # [in] qwMicroSeconds The number of microseconds that the thread should sleep for.
    ctypedef NVFBCRESULT (*NVFBCTOSYSGPUBASEDCPUSLEEP) (int64_t qwMicroSeconds) nogil
    # Destroys the NVFBCToSys capture session.
    ctypedef NVFBCRESULT (*NVFBCTOSYSRELEASE) () nogil

    ctypedef struct NvFBCToSys:
        NVFBCTOSYSSETUP NvFBCToSysSetUp
        NVFBCTOSYSGRABFRAME NvFBCToSysGrabFrame
        NVFBCTOSYSCURSORCAPTURE NvFBCToSysCursorCapture
        NVFBCTOSYSGPUBASEDCPUSLEEP NvFBCToSysGPUBasedCPUSleep
        NVFBCTOSYSRELEASE NvFBCToSysRelease

cdef extern from "NvFBC/nvFBCCuda.h":
    int NVFBC_TOCUDA_NOFLAGS            # Default (no flags set). Grabbing will wait for a new frame or HW mouse move
    int NVFBC_TOCUDA_NOWAIT             # Grabbing will not wait for a new frame nor a HW cursor move.
    int NVFBC_TOCUDA_CPU_SYNC           # Does a cpu event signal when grab is complete
    int NVFBC_TOCUDA_WITH_HWCURSOR      # Grabs the HW cursor if any visible
    int NVFBC_TOCUDA_RESERVED_A         # reserved
    int NVFBC_TOCUDA_WAIT_WITH_TIMEOUT  # Grabbing will wait for a new frame or HW mouse move with a maximum wait time of NVFBC_CUDA_GRAB_FRAME_PARAMS::dwWaitTime millisecond

    ctypedef int NVFBCToCUDABufferFormat
    NVFBCToCUDABufferFormat NVFBC_TOCUDA_ARGB       # Output in 32-bit packed ARGB format
    NVFBCToCUDABufferFormat NVFBC_TOCUDA_ARGB10     # Output in 32-bit packed ARGB10 format (A2B10G10R10)

    ctypedef struct NVFBC_CUDA_SETUP_PARAMS_V1:
        NvU32 dwVersion                     # [in]: Struct version. Set to NVFBC_CUDA_SETUP_PARMS_VER
        NvU32 bEnableSeparateCursorCapture  # [in]: The client should set this to 1 if it wants to enable mouse capture separately from Grab()
        NvU32 bHDRRequest                   # [in]: The client should set this to 1 if it wants to request HDR capture
        #NvU32 bReserved                     # [in]: Reserved. Seto to 0
        void *hCursorCaptureEvent           # [out]: Event handle to be signalled when there is an update to the HW cursor state.
        NVFBCToCUDABufferFormat eFormat     # [in]: Output image format
        #NvU32 dwReserved[61]                # [in]: Reserved. Set to 0
        #void *pReserved[31]                 # [in]: Reserved. Set to NULL
    int NVFBC_CUDA_SETUP_PARAMS_V1_VER
    ctypedef NVFBC_CUDA_SETUP_PARAMS_V1 NVFBC_CUDA_SETUP_PARAMS

    ctypedef struct NVFBC_CUDA_GRAB_FRAME_PARAMS_V1:
        NvU32 dwVersion                     # [in]: Struct version. Set to NVFBC_CUDA_GRAB_FRAME_PARAMS_V1_VER
        NvU32 dwFlags                       # [in]: Flags for grab frame
        void *pCUDADeviceBuffer             # [in]: Output buffer
        NvFBCFrameGrabInfo *pNvFBCFrameGrabInfo # [in/out]: Frame grab configuration and feedback from NvFBC driver
        NvU32 dwWaitTime                    # [in] Time limit in millisecond to wait for a new frame or HW mouse move. Use with NVFBC_TOCUDA_WAIT_WITH_TIMEOUT
        #NvU32 dwReserved[61]                # [in]: Reserved. Set to 0
        #void *pReserved[30]                 # [in]: Reserved. Set to NULL
    int NVFBC_CUDA_GRAB_FRAME_PARAMS_V1_VER
    ctypedef NVFBC_CUDA_GRAB_FRAME_PARAMS_V1 NVFBC_CUDA_GRAB_FRAME_PARAMS

    # Returns the maximum buffer size, in bytes for allocating a CUDA buffer to hold output data generated by the NvFBCCuda interface
    # [out] pdwMaxBufSize Pointer to a 32-bit unsigned integer
    ctypedef NVFBCRESULT (*NVFBCCUDAGETMAXBUFFERSIZE) (NvU32 *pdwMaxBufSize) nogil
    #Performs initial setup
    # [in] pParams Pointer to a struct of type ::NVFBC_CUDA_SETUP_PARAMS
    ctypedef NVFBCRESULT (*NVFBCCUDASETUP) (NVFBC_CUDA_SETUP_PARAMS *pParams) nogil
    # Captures the desktop and dumps captured data to a CUDA buffer provided by the client
    # If the API returns a failure, the client should check the return codes and ::NvFBCFrameGrabInfo output fields to determine if the session needs to be re-created
    # [inout] pParams Pointer to a struct of type ::NVFBC_CUDA_GRAB_FRAME_PARAMS
    ctypedef NVFBCRESULT (*NVFBCCUDAGRABFRAME) (NVFBC_CUDA_GRAB_FRAME_PARAMS *pParams) nogil
    # A high precision implementation of Sleep()
    # Can provide sub quantum (usually 16ms) sleep that does not burn CPU cycles
    # [in] qwMicroSeconds The number of microseconds that the thread should sleep for.
    ctypedef NVFBCRESULT (*NVFBCCUDAGPUBASEDCPUSLEEP) (int64_t qwMicroSeconds) nogil
    # Captures HW cursor data whenever shape of mouse is changed
    # [inout] pParam Pointer to a struct of type ::NVFBC_TOSYS_GRAB_MOUSE_PARAMS
    ctypedef NVFBCRESULT (*NVFBCCUDACURSORCAPTURE) (NVFBC_CURSOR_CAPTURE_PARAMS *pParam) nogil
    # Destroys the NvFBCCuda capture session.
    ctypedef NVFBCRESULT (*NVFBCCUDARELEASE) ()


    ctypedef struct NvFBCCuda:
        NVFBCCUDAGETMAXBUFFERSIZE NvFBCCudaGetMaxBufferSize
        NVFBCCUDASETUP NvFBCCudaSetup
        NVFBCCUDAGRABFRAME NvFBCCudaGrabFrame
        NVFBCCUDAGPUBASEDCPUSLEEP NvFBCCudaGPUBasedCPUSleep
        NVFBCCUDACURSORCAPTURE NvFBCCudaCursorCapture
        NVFBCCUDARELEASE NvFBCCudaRelease


ERRORS: Dict[int, str] = {
    NVFBC_SUCCESS                       : "SUCCESS",
    NVFBC_ERROR_GENERIC                 : "GENERIC",
    NVFBC_ERROR_INVALID_PARAM           : "INVALID_PARAM",
    NVFBC_ERROR_INVALIDATED_SESSION     : "INVALIDATED_SESSION",
    NVFBC_ERROR_PROTECTED_CONTENT       : "PROTECTED_CONTENT",
    NVFBC_ERROR_DRIVER_FAILURE          : "DRIVER_FAILURE",
    NVFBC_ERROR_CUDA_FAILURE            : "CUDA_FAILURE",
    NVFBC_ERROR_UNSUPPORTED             : "UNSUPPORTED",
    NVFBC_ERROR_HW_ENC_FAILURE          : "HW_ENC_FAILURE",
    NVFBC_ERROR_INCOMPATIBLE_DRIVER     : "INCOMPATIBLE_DRIVER",
    NVFBC_ERROR_UNSUPPORTED_PLATFORM    : "UNSUPPORTED_PLATFORM",
    NVFBC_ERROR_OUT_OF_MEMORY           : "OUT_OF_MEMORY",
    NVFBC_ERROR_INVALID_PTR             : "INVALID_PTR",
    NVFBC_ERROR_INCOMPATIBLE_VERSION    : "INCOMPATIBLE_VERSION",
    NVFBC_ERROR_OPT_CAPTURE_FAILURE     : "OPT_CAPTURE_FAILURE",
    NVFBC_ERROR_INSUFFICIENT_PRIVILEGES : "INSUFFICIENT_PRIVILEGES",
    NVFBC_ERROR_INVALID_CALL            : "INVALID_CALL",
    NVFBC_ERROR_SYSTEM_ERROR            : "SYSTEM_ERROR",
    NVFBC_ERROR_INVALID_TARGET          : "INVALID_TARGET",
    NVFBC_ERROR_NVAPI_FAILURE           : "NVAPI_FAILURE",
    NVFBC_ERROR_DYNAMIC_DISABLE         : "DYNAMIC_DISABLE",
    NVFBC_ERROR_IPC_FAILURE             : "IPC_FAILURE",
    NVFBC_ERROR_CURSOR_CAPTURE_FAILURE  : "CURSOR_CAPTURE_FAILURE",
    }


cdef inline cvp(val):
    return ctypes.cast(<uintptr_t> val, ctypes.c_void_p)


class NvFBCException(Exception):
    def __init__(self, code, fn):
        self.function = fn
        self.code = code
        msg = "%s - returned %s" % (fn, ERRORS.get(code, code))
        super().__init__(msg)


cdef inline raiseNvFBC(NVFBCRESULT ret, msg):
    if ret!=0:
        raise NvFBCException(ret, msg)


NvFBC = None
cdef NvU32 version = 0
def init_nvfbc_library():
    global NvFBC
    if NvFBC is not None:
        return NvFBC
    if not WIN32:
        NvFBC = False
        raise RuntimeError(f"nvfbc is not supported on {sys.platform}")
    load = ctypes.WinDLL
    #we only support 64-bit:
    nvfbc_libname = "NvFBC64.dll"
    log("init_nvfbc_library() will try to load %s", nvfbc_libname)
    try:
        NvFBC = load(nvfbc_libname)
        log("init_nvfbc_library() %s(%s)=%s", load, nvfbc_libname, NvFBC)
    except Exception as e:
        NvFBC = False
        log("failed to load '%s'", nvfbc_libname, exc_info=True)
        raise ImportError("nvfbc: the required library %s cannot be loaded: %s" % (nvfbc_libname, e)) from None
    NvFBC.NvFBC_GetSDKVersion.argtypes = [ctypes.c_void_p]
    NvFBC.NvFBC_GetSDKVersion.restype = wintypes.INT
    NvFBC.NvFBC_GetStatusEx.argtypes = [ctypes.c_void_p]
    NvFBC.NvFBC_GetStatusEx.restype = wintypes.INT
    NvFBC.NvFBC_SetGlobalFlags.argtypes = [wintypes.DWORD]
    NvFBC.NvFBC_SetGlobalFlags.restype = wintypes.INT
    NvFBC.NvFBC_Enable.argtypes = [wintypes.INT]
    NvFBC.NvFBC_Enable.restype = wintypes.INT
    cdef NVFBCRESULT res = NvFBC.NvFBC_GetSDKVersion(cvp(<uintptr_t> &version))
    log("NvFBC_GetSDKVersion()=%i version=%i", res, version)
    raiseNvFBC(res, "NvFBC_GetSDKVersion")
    return NvFBC


def unload_library() -> None:
    global NvFBC
    NvFBC = None


def set_enabled(enabled : bool=True) -> None:
    lib = init_nvfbc_library()
    r = lib.NvFBC_Enable(int(enabled))
    raiseNvFBC(r, "NvFBC_Enable")



def get_status(int adapter=0) -> Dict[str, Any]:
    global NvFBC
    assert NvFBC
    cdef NvFBCStatusEx status
    memset(&status, 0, sizeof(NvFBCStatusEx))
    status.dwVersion = NVFBC_STATUS_VER
    status.dwAdapterIdx = adapter
    cdef NVFBCRESULT res = NvFBC.NvFBC_GetStatusEx(cvp(<uintptr_t> &status))
    log("NvFBC_GetStatusEx()=%i", res)
    raiseNvFBC(res, "NvFBC_GetStatusEx")
    s = {
        "capture-possible"      : bool(status.bIsCapturePossible),
        "currently-capturing"   : bool(status.bCurrentlyCapturing),
        "can-create-now"        : bool(status.bCanCreateNow),
        "support-multihead"     : bool(status.bSupportMultiHead),
        "support-diffmap"       : bool(status.bSupportConfigurableDiffMap),
        "version"               : int(status.dwNvFBCVersion),
        "adapter"               : int(status.dwAdapterIdx),
    }
    log("get_status()=%s", s)
    return s


def check_status() -> None:
    status = get_status()
    if not status.get("capture-possible"):
        try:
            set_enabled(True)
            #re-query the status:
            status = get_status()
            if status.get("capture-possible"):
                log.info("NvFBC capture has been enabled")
        except Exception as e:
            log.info("NvFBC capture cannot be enabled")
            log.info(f" {e}")
            log.info(f" you may need to run `NvFBC_capture.exe enable` as administrator")
        raise RuntimeError("NvFBC status error: capture is not possible")
    if status.get("currently-capturing"):
        raise TransientCodecException("NvFBC status error: currently capturing")
    if not status.get("can-create-now"):
        raise TransientCodecException("NvFBC status error: cannot create now")


def set_global_flags(DWORD flags) -> None:
    global NvFBC
    assert NvFBC
    cdef NVFBCRESULT res = NvFBC.NvFBC_SetGlobalFlags(flags)
    log("NvFBC_SetGlobalFlags(%i)=%i", flags, res)
    raiseNvFBC(res, "NvFBC_SetGlobalFlags")


def create_context(int width=-1, int height=-1, interface_type=NVFBC_TO_SYS) -> Dict[str, Any]:
    log("create_context(%i, %i, %s)", width, height, {NVFBC_TO_SYS : "SYS", NVFBC_SHARED_CUDA : "CUDA"}.get(interface_type))
    check_status()
    cdef NvFBCCreateParams create
    cdef NVFBCRESULT res = <NVFBCRESULT> 0
    cdef char* ckey
    keys = CLIENT_KEYS_STRS or [None]
    log("create_context() will try with keys: %s", csv(keys))
    assert len(keys)>0
    for key in keys:
        memset(&create, 0, sizeof(NvFBCCreateParams))
        create.dwVersion = NVFBC_CREATE_PARAMS_VER
        create.dwInterfaceType = interface_type
        create.dwMaxDisplayWidth = width
        create.dwMaxDisplayHeight = height
        #create.pDevice = 0
        create.dwInterfaceVersion = NVFBC_DLL_VERSION
        if key:
            binkey = parse_nvfbc_hex_key(key)
            ckey = binkey
            create.pPrivateData = <void*> ckey
            create.dwPrivateDataSize = len(ckey)
            log("create_context() key data=%#x, size=%i", <uintptr_t> ckey, len(ckey))
        res = NvFBC.NvFBC_CreateEx(cvp(<uintptr_t> &create))
        log("create_context() NvFBC_CreateEx()=%i for key=%s", res, key)
        if res==0:
            #success!
            break
    log("NvFBC_CreateEx(%#x)=%i", <uintptr_t> &create, res)
    raiseNvFBC(res, "NvFBC_CreateEx")
    info = {
        "max-display-width"     : create.dwMaxDisplayWidth,
        "max-display-height"    : create.dwMaxDisplayHeight,
        "version"               : create.dwNvFBCVersion,
        "context"               : <uintptr_t> create.pNvFBC,
        }
    log("NvFBC_CreateEx: %s", info)
    return info


cdef dict get_frame_grab_info(NvFBCFrameGrabInfo *grab_info):
    return {
        "width"             : int(grab_info.dwWidth),
        "height"            : int(grab_info.dwHeight),
        "stride"            : int(grab_info.dwBufferWidth),
        "overlay-active"    : bool(grab_info.bOverlayActive),
        "first-buffer"      : bool(grab_info.bFirstBuffer),
        "hw-mouse-visible"  : bool(grab_info.bHWMouseVisible),
        "protected-content" : bool(grab_info.bProtectedContent),
        "stereo"            : bool(grab_info.bStereoOn),
        "IGPU-capture"      : bool(grab_info.bIGPUCapture),
        "source-pid"        : int(grab_info.dwSourcePID),
        "HDR"               : bool(grab_info.bIsHDR),
        "wait-mode"         : int(grab_info.dwWaitModeUsed),
        }


def get_version() -> Sequence[int]:
    return (version, )


def get_type() -> str:
    return "nvfbc"


def get_info() -> Dict[str,Any]:
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


SYS_PIXEL_FORMAT_CONST: Dict[str, int] = {
    "BGRX"      : NVFBC_TOSYS_ARGB,
    "RGB"       : NVFBC_TOSYS_RGB,
    #"YUV420P"   : NVFBC_TOSYS_YYYYUV420p,
    #"RGBP"      : NVFBC_TOSYS_RGB_PLANAR,
    #NVFBC_TOSYS_XOR,
    #"YUV444P"   : NVFBC_TOSYS_YUV444p,
    "r210"      : NVFBC_TOSYS_ARGB10,
}


cdef class NvFBC_SysCapture:
    cdef NvFBCToSys *context
    cdef uint8_t *framebuffer
    cdef uint8_t setup
    cdef object pixel_format
    cdef NvFBCFrameGrabInfo grab_info
    cdef NVFBC_TOSYS_GRAB_FRAME_PARAMS grab

    cdef object __weakref__

    def init_context(self, int width=-1, int height=-1, pixel_format=DEFAULT_PIXEL_FORMAT) -> None:
        log("init_context(%i, %i, %s)", width, height, pixel_format)
        global SYS_PIXEL_FORMAT_CONST
        if pixel_format not in SYS_PIXEL_FORMAT_CONST:
            raise ValueError(f"unsupported pixel format {pixel_format!r}")
        self.pixel_format = pixel_format
        self.framebuffer = NULL
        info = create_context(-1, -1, NVFBC_TO_SYS)
        maxw = info["max-display-width"]
        maxh = info["max-display-height"]
        assert width<=maxw and height<=maxh, "display dimension %ix%i is too large, the maximum supported by this card and driver is %ix%i" % (width, height, maxw, maxh)
        self.context = <NvFBCToSys*> (<uintptr_t> info["context"])
        assert self.context!=NULL
        cdef NVFBC_TOSYS_SETUP_PARAMS params
        memset(&params, 0, sizeof(NVFBC_TOSYS_SETUP_PARAMS))
        params.dwVersion = NVFBC_TOSYS_SETUP_PARAMS_VER
        params.eMode = SYS_PIXEL_FORMAT_CONST[pixel_format]
        params.bWithHWCursor = False
        params.bDiffMap = False
        params.ppBuffer = <void**> &self.framebuffer
        params.ppDiffMap = NULL
        cdef NVFBCRESULT res = self.context.NvFBCToSysSetUp(&params)
        raiseNvFBC(res, "NvFBCToSysSetUp")
        self.setup = True

    def get_info(self) -> Dict[str,Any]:
        info = get_info()
        info["pixel-format"] = self.pixel_format
        return info

    def get_type(self) -> str:
        return "nvfbc-sys"

    def __repr__(self):
        return "NvFBC_SysCapture(%#x)" % (<uintptr_t> self.context)

    def __dealloc__(self):
        self.clean()

    def refresh(self) -> bool:
        assert self.context
        cdef double start = monotonic()
        memset(&self.grab_info, 0, sizeof(NvFBCFrameGrabInfo))
        memset(&self.grab, 0, sizeof(NVFBC_TOSYS_GRAB_FRAME_PARAMS))
        self.grab.dwVersion = NVFBC_TOSYS_GRAB_FRAME_PARAMS_VER
        self.grab.dwFlags = NVFBC_TOSYS_NOWAIT
        self.grab.dwTargetWidth = 0  #width
        self.grab.dwTargetHeight = 0 #height
        self.grab.dwStartX = 0
        self.grab.dwStartY = 0
        self.grab.eGMode = NVFBC_TOSYS_SOURCEMODE_FULL
        self.grab.pNvFBCFrameGrabInfo = &self.grab_info
        cdef NVFBCRESULT res
        with nogil:
            res = self.context.NvFBCToSysGrabFrame(&self.grab)
        if res!=0 and self.grab_info.dwDriverInternalError:
            raise CodecStateException("NvFBC driver internal error")
        if res==NVFBC_ERROR_DYNAMIC_DISABLE:
            raise CodecStateException("NvFBC capture has been disabled")
        if (res!=0 and self.grab_info.bMustRecreate) or res==NVFBC_ERROR_INVALIDATED_SESSION:
            raise TransientCodecException("NvFBC context invalidated")
        raiseNvFBC(res, "NvFBCToSysGrabFrame")
        log("NvFBCToSysGrabFrame() info=%s", get_frame_grab_info(&self.grab_info))
        return True

    def get_image(self, unsigned int x=0, unsigned int y=0, unsigned int width=0, unsigned int height=0) -> ImageWrapper:
        assert self.context
        log("nvfbc sys get_image%s", (x, y, width, height))
        if width==0:
            width = self.grab_info.dwWidth
        if height==0:
            height = self.grab_info.dwHeight
        assert x==0 and y==0 and width>0 and height>0
        assert x+width<=self.grab_info.dwWidth, "invalid capture width: %i+%i, capture size is only %i" % (x, width, self.grab_info.dwWidth)
        assert y+height<=self.grab_info.dwHeight, "invalid capture height: %i+%i, capture size is only %i" % (y, height, self.grab_info.dwHeight)
        cdef double start = monotonic()
        #TODO: only copy when the next frame is going to overwrite the buffer,
        #or when closing the context
        cdef unsigned int Bpp = len(self.pixel_format)    # ie: "BGR" -> 3
        cdef unsigned int grab_stride = self.grab_info.dwWidth*Bpp
        cdef unsigned int stride = grab_stride
        cdef size_t size
        cdef MemBuf buf
        cdef uintptr_t buf_ptr = 0
        cdef uintptr_t grab_ptr = <uintptr_t> (self.framebuffer+x*Bpp+y*grab_stride)
        if x>0 or y>0 or self.grab_info.dwWidth-width>16 or self.grab_info.dwHeight-height>16:
            #copy sub-image with smaller stride:
            stride = roundup(width*Bpp, 16)
            size = stride*height
            buf = padbuf(size, stride)
            buf_ptr = <uintptr_t> buf.get_mem()
            with nogil:
                for _ in range(height):
                    memcpy(<void *> buf_ptr, <void *> grab_ptr, width*Bpp)
                    grab_ptr += grab_stride
                    buf_ptr += stride
        else:
            #copy whole:
            size = self.grab_info.dwBufferWidth*self.grab_info.dwHeight*Bpp
            buf = padbuf(size, stride)
            buf_ptr = <uintptr_t> buf.get_mem()
            with nogil:
                memcpy(<void *> buf_ptr, <void *> grab_ptr, size)
        image = ImageWrapper(0, 0, width, height, memoryview(buf), self.pixel_format, Bpp*8, stride, Bpp)
        end = monotonic()
        log("image=%s buffer size=%i, (copy took %ims)", image, size, int((end-start)*1000))
        return image

    def clean(self) -> None:
        log("clean()")
        if self.setup:
            self.setup = False
            ctx = self.context
            if ctx:
                self.context = NULL
                ctx.NvFBCToSysRelease()


cdef class NvFBC_CUDACapture:
    cdef NvFBCCuda *context
    cdef uint8_t setup
    cdef object pixel_format
    cdef NvU32 max_buffer_size
    cdef int cuda_device_id
    cdef object cuda_device
    cdef object cuda_context
    cdef object cuda_device_buffer
    cdef NvFBCFrameGrabInfo grab_info
    cdef NVFBC_CUDA_GRAB_FRAME_PARAMS grab

    cdef object __weakref__

    def init_context(self, int width=-1, int height=-1, pixel_format="BGRX") -> None:
        log("init_context(%i, %i, %s)", width, height, pixel_format)
        if pixel_format not in ("BGRX", "r210"):
            raise ValueError(f"unsupported pixel format {pixel_format!r}")
        self.pixel_format = pixel_format
        #CUDA init:
        self.cuda_device_id, self.cuda_device = select_device()
        if not self.cuda_device:
            raise RuntimeError("no valid CUDA device")
        d = self.cuda_device
        self.cuda_context = d.make_context(flags=driver.ctx_flags.SCHED_AUTO | driver.ctx_flags.MAP_HOST)
        assert self.cuda_context, "failed to create a CUDA context for device %s" % device_info(d)
        self.cuda_context.pop()
        self.cuda_context.push()
        #NvFBC init:
        info = create_context(-1, -1, NVFBC_SHARED_CUDA)
        maxw = info["max-display-width"]
        maxh = info["max-display-height"]
        assert width<=maxw and height<=maxh, "display dimension %ix%i is too large, maximum supported by this card and driver is %ix%i" % (width, height, maxw, maxh)
        self.context = <NvFBCCuda*> (<uintptr_t> info["context"])
        assert self.context!=NULL
        self.context.NvFBCCudaGetMaxBufferSize(&self.max_buffer_size)
        log("NvFBCCudaGetMaxBufferSize: %#x", self.max_buffer_size)
        cdef NVFBC_CUDA_SETUP_PARAMS params
        memset(&params, 0, sizeof(NVFBC_CUDA_SETUP_PARAMS))
        params.dwVersion = NVFBC_CUDA_SETUP_PARAMS_V1_VER
        params.bEnableSeparateCursorCapture = 1
        params.bHDRRequest = 0
        if pixel_format=="BGRX":
            params.eFormat = NVFBC_TOCUDA_ARGB
        else:
            params.eFormat = NVFBC_TOCUDA_ARGB10
        cdef NVFBCRESULT res = self.context.NvFBCCudaSetup(&params)
        raiseNvFBC(res, "NvFBCCudaSetup")
        self.setup = True

    def get_info(self) -> Dict[str,Any]:
        info = get_info()
        info["pixel-format"] = self.pixel_format
        return info

    def get_type(self) -> str:
        return "nvfbc-cuda"

    def __repr__(self):
        return "NvFBC_CUDACapture(%#x)" % (<uintptr_t> self.context)

    def __dealloc__(self):
        self.clean()

    def refresh(self) -> bool:
        return True

    def get_image(self, unsigned int x=0, unsigned int y=0, unsigned int width=0, unsigned int height=0) -> SharedCUDAImageWrapper:
        assert self.context
        log("nvfbc cuda get_image%s", (x, y, width, height))
        if width==0:
            width = self.grab_info.dwWidth
        if height==0:
            height = self.grab_info.dwHeight
        assert x==0 and y==0 and width>0 and height>0
        cdef double start = monotonic()
        #allocate CUDA device memory:
        if not self.cuda_device_buffer:
            #TODO: choose a better size
            self.cuda_device_buffer = driver.mem_alloc(self.max_buffer_size)
            log("max_buffer_size=%#x, cuda device buffer=%s", self.max_buffer_size, self.cuda_device_buffer)
        #cuda_device_buffer, stride = self.cuda_device.mem_alloc_pitch(4096, 2160, 16)
        memset(&self.grab_info, 0, sizeof(NvFBCFrameGrabInfo))
        memset(&self.grab, 0, sizeof(NVFBC_CUDA_GRAB_FRAME_PARAMS))
        self.grab.dwVersion = NVFBC_CUDA_GRAB_FRAME_PARAMS_V1_VER
        ptr = <uintptr_t> int(self.cuda_device_buffer)
        self.grab.pCUDADeviceBuffer = <void*> ptr
        self.grab.pNvFBCFrameGrabInfo = &self.grab_info
        self.grab.dwFlags = NVFBC_TOCUDA_NOWAIT
        cdef NVFBCRESULT res
        with nogil:
            res = self.context.NvFBCCudaGrabFrame(&self.grab)
        if res<0:
            raiseNvFBC(res, "NvFBCToSysGrabFrame")
        elif res!=0:
            raise RuntimeError(f"CUDA Grab Frame failed: {get_error_name(res)}")
        cdef double end = monotonic()
        log("NvFBCCudaGrabFrame: info=%s, elapsed=%ims", get_frame_grab_info(&self.grab_info), int((end-start)*1000))
        assert x==0 and y==0 and width>0 and height>0
        assert x+width<=self.grab_info.dwWidth, "invalid capture width: %i+%i, capture size is only %i" % (x, width, self.grab_info.dwWidth)
        assert y+height<=self.grab_info.dwHeight, "invalid capture height: %i+%i, capture size is only %i" % (y, height, self.grab_info.dwHeight)
        Bpp = len(self.pixel_format)    # ie: "BGR" -> 3
        image = SharedCUDAImageWrapper(0, 0, width, height, None, self.pixel_format, Bpp*8, int(self.grab_info.dwBufferWidth*Bpp), Bpp, False, None)
        image.cuda_device_buffer = self.cuda_device_buffer
        image.cuda_context = self.cuda_context
        image.buffer_size = self.max_buffer_size
        return image

    def clean(self) -> None:
        log("clean()")
        cuda_context = self.cuda_context
        self.cuda_context = None
        if self.setup:
            self.setup = False
            if self.context:
                self.context.NvFBCCudaRelease()
                self.context = NULL
        if cuda_context:
            try:
                cuda_context.pop()
                cuda_context.detach()
            except:
                log("%s.pop() or detach()", cuda_context, exc_info=True)
        #don't free it - an imagewrapper may still use it:
        #TODO: we should invalidate it
        self.cuda_device_buffer = None


class SharedCUDAImageWrapper(CUDAImageWrapper):

    def free_cuda_device_buffer(self) -> None:
        # override so we only clear the reference,
        # the buffer is going to be re-used so we cannot free it
        self.cuda_device_buffer = None


def init_module(options: dict) -> None:
    log("nvfbc.init_module(%s)", options)
    init_nvfbc_library()


def cleanup_module() -> None:
    log("nvfbc.cleanup_module()")
    unload_library()


def selftest(full=False) -> None:
    pass
