#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.log import Logger
log = Logger("encoder", "nvenc")
from xpra.util import pver

IGNORE_NVIDIA_DRIVER_BLACKLIST = os.environ.get("XPRA_IGNORE_NVIDIA_DRIVER_BLACKLIST", "0")=="1"


def get_nvml_driver_version():
    try:
        from pynvml import nvmlInit, nvmlShutdown, nvmlSystemGetDriverVersion
        try:
            nvmlInit()
            v = nvmlSystemGetDriverVersion()
            log("nvmlSystemGetDriverVersion=%s", v)
            return v.split(".")
        except Exception as e:
            log.warn("Warning: failed to query the NVidia kernel module version via NVML:")
            log.warn(" %s", e)
        finally:
            nvmlShutdown()
    except ImportError as e:
        log("cannot use nvml to query the kernel module version:")
        log(" %s", e)
    return ""


def get_proc_driver_version():
    from xpra.os_util import load_binary_file
    proc_file = "/proc/driver/nvidia/version"
    v = load_binary_file(proc_file)
    if not v:
        log.warn("Warning: NVidia kernel module not installed?")
        log.warn(" cannot open '%s'", proc_file)
        return ""
    KSTR = "Kernel Module"
    p = v.find(KSTR)
    if not p:
        log.warn("unknown NVidia kernel module version")
        return ""
    v = v[p+len(KSTR):].strip().split(" ")[0]
    v = v.split(".")
    return v


def identify_nvidia_module_version():
    if os.name!="posix":
        if not sys.platform.startswith("win"):
            log.warn("Warning: unable to identify the NVidia driver version on this platform")
            return None
        #try the nvapi call:
        try:
            from xpra.codecs.nvapi_version import get_driver_version    #@UnresolvedImport
            v = get_driver_version()
            log("NVAPI get_driver_version()=%s", v)
        except Exception as e:
            log.warn("failed to get the driver version through NVAPI:")
            log.warn(" %s", e)
    else:
        v = get_nvml_driver_version() or get_proc_driver_version()
    #only keep numeric values:
    numver = []
    try:
        for x in v:
            try:
                numver.append(int(x))
            except ValueError:
                if len(numver)==0:
                    raise
        if numver:
            log.info("NVidia driver version %s", pver(numver))
            return numver
    except Exception as e:
        log.warn("failed to parse Nvidia driver version '%s': %s", v, e)
    return []

nvidia_module_version = None
def get_nvidia_module_version(probe=True):
    global nvidia_module_version
    if nvidia_module_version is None and probe:
        nvidia_module_version = identify_nvidia_module_version()
    return nvidia_module_version


def is_blacklisted():
    v = get_nvidia_module_version(True)
    def wouldfail():
        if IGNORE_NVIDIA_DRIVER_BLACKLIST:
            log.warn("Warning: the driver blacklist has been ignored")
            return False
        return True
    try:
        if v[0]<350:
            return False
        if v[0]==352 and v[1]<=30:
            return wouldfail()
        if v[0]==355 and v[1]<=6:
            return wouldfail()
    except Exception as e:
        log.warn("Warning: error checking driver version:")
        log.warn(" %s", e)
    return None     #we don't know: unreleased / untested

nvenc_license_keys = {}
def get_nvenc_license_keys(nvenc_version=0):
    global nvenc_license_keys
    keys = nvenc_license_keys.get(nvenc_version)
    if keys is not None:
        return keys
    env_keys = os.environ.get("XPRA_NVENC_CLIENT_KEY", "")
    if env_keys:
        keys = [x.strip() for x in os.environ.get("XPRA_NVENC_CLIENT_KEY", "").split(",")]
        log("using nvenc keys from environment variable XPRA_NVENC_CLIENT_KEY: %s", nvenc_license_keys)
    else:
        #try the license file
        keys = []
        try:
            #see read_xpra_defaults for an explanation of paths
            from xpra.platform.paths import get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs
            dirs = get_default_conf_dirs() + get_system_conf_dirs() + get_user_conf_dirs()
            for d in dirs:
                if not d:
                    continue
                keys_file = os.path.join(d, "nvenc%s.keys" % (nvenc_version or ""))
                keys_file = os.path.expanduser(keys_file)
                if not os.path.exists(keys_file):
                    log("get_nvenc_license_keys(%s) '%s' does not exist", nvenc_version, keys_file)
                    continue
                log("loading nvenc%s keys from %s", nvenc_version, keys_file)
                with open(keys_file, "rU") as f:
                    for line in f:
                        sline = line.strip().rstrip('\r\n').strip()
                        if len(sline) == 0:
                            log("skipping empty line")
                            continue
                        if sline[0] in ( '!', '#' ):
                            log("skipping comments")
                            continue
                        keys.append(sline)
                        log("added key: %s", sline)
        except Exception as e:
            log.error("error loading nvenc license keys: %s", e, exc_info=True)
    nvenc_license_keys[nvenc_version] = keys
    log("get_nvenc_license_keys(%s)=%s", nvenc_version, keys)
    return keys


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    from xpra.platform import program_context
    with program_context("Nvidia-Info", "Nvidia Info"):
        #this will log the version number:
        get_nvidia_module_version()
        if is_blacklisted():
            log.warn("Warning: this driver version is blacklisted")
        log.info("NVENC license keys:")
        for v in (0, 3, 4):
            keys = get_nvenc_license_keys(v)
            log.info("* version %s: %s key(s)", v or "common", len(keys))
            for k in keys:
                log.info("  %s", k)


if __name__ == "__main__":
    main()
