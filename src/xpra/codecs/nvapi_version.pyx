# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.log import Logger
log = Logger("encoder", "nvenc")

from libc.stdint cimport uint32_t


cdef extern from "nvapi.h":
    #define NVAPI_SHORT_STRING_MAX      64
    int NVAPI_SHORT_STRING_MAX
    ctypedef uint32_t NvU32
    ctypedef char[64] NvAPI_ShortString
    ctypedef uint32_t NVAPI_INTERFACE
    ctypedef uint32_t NvAPI_Status

    ctypedef struct NV_DISPLAY_DRIVER_VERSION:
        NvU32              version                  # Structure version
        NvU32              drvVersion
        NvU32              bldChangeListNum
        NvAPI_ShortString  szBuildBranchString
        NvAPI_ShortString  szAdapterString

    NvAPI_Status NvAPI_Initialize()
    NvAPI_Status NvAPI_Unload()
    NvAPI_Status NvAPI_GetErrorMessage(NvAPI_Status nr,NvAPI_ShortString szDesc)
    NvAPI_Status NvAPI_SYS_GetDriverAndBranchVersion(NvU32* pDriverVersion, NvAPI_ShortString szBuildBranchString)

def raiseNVAPI(r, msg):
    if r!=0:
        raise Exception("error %s %s" % (r, msg))

def get_driver_version():
    cdef NvAPI_Status r
    r = NvAPI_Initialize()
    raiseNVAPI(r, "NvAPI_Initialize")
    cdef NvU32 driverVersion
    cdef NvAPI_ShortString buildBranch
    try:
        r = NvAPI_SYS_GetDriverAndBranchVersion(&driverVersion, buildBranch)
        raiseNVAPI(r, "NvAPI_SYS_GetDriverAndBranchVersion")
        log("DriverVersion: %s", driverVersion)
        log("Build Branch: %s", buildBranch)
        return [driverVersion//100, driverVersion%100, str(buildBranch)]
    finally:
        r = NvAPI_Unload()
        raiseNVAPI(r, "NvAPI_Unload")

def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    from xpra.platform import program_context
    with program_context("Nvidia-Info", "Nvidia Info"):
        log.info("%s", get_driver_version())

if __name__ == "__main__":
    main()
