# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.log import Logger
log = Logger("encoder", "nvenc")

def identify_nvidia_module_version():
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
