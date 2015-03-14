# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.log import Logger
log = Logger("encoder", "nvenc")


def identify_nvidia_module_version():
    if os.name!="posix":
        return None
    from xpra.os_util import load_binary_file
    v = load_binary_file("/proc/driver/nvidia/version")
    if not v:
        log.warn("Nvidia kernel module not installed?")
        return []
    KSTR = "Kernel Module"
    p = v.find(KSTR)
    if not p:
        log.warn("unknown Nvidia kernel module version")
        return []
    v = v[p+len(KSTR):].strip().split(" ")[0]
    try:
        numver = [int(x) for x in v.split(".")]
        log.info("Nvidia kernel module version %s", v)
        return numver
    except Exception as e:
        log.warn("failed to parse Nvidia kernel module version '%s': %s", v, e)
    return []

nvidia_module_version = None
def get_nvidia_module_version(probe=True):
    global nvidia_module_version
    if nvidia_module_version is None and probe:
        nvidia_module_version = identify_nvidia_module_version()
    return nvidia_module_version

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
            from xpra.platform.paths import get_default_conf_dir, get_system_conf_dir, get_user_conf_dir
            dirs = [get_default_conf_dir(), get_system_conf_dir(), get_user_conf_dir()]
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

    from xpra.platform import init, clean
    try:
        init("Nvidia-Info", "Nvidia Info")
        #this will log the version number:
        identify_nvidia_module_version()
        log.info("NVENC license keys:")
        for v in (0, 3, 4):
            keys = get_nvenc_license_keys(v)
            log.info("* version %s: %s key(s)", v or "common", len(keys))
            for k in keys:
                log.info("  %s", k)
    finally:
        clean()

if __name__ == "__main__":
    main()
