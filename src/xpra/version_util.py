#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#tricky: use xpra.scripts.config to get to the python "platform" module
from xpra.scripts.config import python_platform
import sys
import os

import xpra
from xpra.util import updict, envbool
from xpra.os_util import get_linux_distribution
from xpra.log import Logger
log = Logger("util")

XPRA_VERSION = xpra.__version__     #@UndefinedVariable

def version_as_numbers(version):
    return [int(x) for x in version.split(".")]

def version_compat_check(remote_version):
    if remote_version is None:
        msg = "remote version not available!"
        log(msg)
        return msg
    rv = version_as_numbers(remote_version)
    lv = version_as_numbers(XPRA_VERSION)
    if rv==lv:
        log("identical remote version: %s", remote_version)
        return None
    if rv[0:3]<[0, 14, 10]:
        #this is the oldest version we support
        msg = "remote version %s is too old, sorry" % str(rv[:2])
        log(msg)
        return  msg
    if rv[0]>0:
        log("newer remote version %s may work, we'll see..", remote_version)
        return  None
    log("local version %s should be compatible with remote version: %s", XPRA_VERSION, remote_version)
    return None


def get_host_info():
    #this function is for non UI thread info
    info = {}
    try:
        import struct
        bits = struct.calcsize("P") * 8
        import socket
        info.update({
                    "pid"                   : os.getpid(),
                    "byteorder"             : sys.byteorder,
                    "hostname"              : socket.gethostname(),
                    "python"                : {
                                               "bits"                  : bits,
                                               "full_version"          : sys.version,
                                               "version"               : ".".join(str(x) for x in sys.version_info[:3]),
                                               },
                    })
    except:
        pass
    for x in ("uid", "gid"):
        if hasattr(os, "get%s" % x):
            try:
                info[x] = getattr(os, "get%s" % x)()
            except:
                pass
    return info

def get_version_info():
    props = {
             "version"  : XPRA_VERSION
             }
    try:
        from xpra.src_info import LOCAL_MODIFICATIONS, REVISION
        props["local_modifications"]    = LOCAL_MODIFICATIONS
        props["revision"]               = REVISION
    except ImportError as e:
        log.warn("missing some source information: %s", e)
    return props

def get_version_info_full():
    props = get_version_info()
    try:
        from xpra import build_info
        #rename these build info properties:
        for k,bk in {
                    "date"                 : "BUILD_DATE",
                    "time"                 : "BUILD_TIME",
                    "by"                   : "BUILT_ON",
                    "bit"                  : "BUILD_BIT",
                    "cpu"                  : "BUILD_CPU",
                    "compiler"             : "COMPILER_VERSION",
                    "nvcc"                 : "NVCC_VERSION",
                    "linker"               : "LINKER_VERSION",
                    "python"               : "PYTHON_VERSION",
                    "cython"               : "CYTHON_VERSION",
                  }.items():
            v = getattr(build_info, bk, None)
            if v:
                props[k] = v
        #record library versions:
        d = dict((k.lstrip("lib_"), getattr(build_info, k)) for k in dir(build_info) if k.startswith("lib_"))
        updict(props, "lib", d)
    except Exception as e:
        log.warn("missing some build information: %s", e)
    log("get_version_info_full()=%s", props)
    return props

def do_get_platform_info():
    from xpra.os_util import platform_name, platform_release
    pp = sys.modules.get("platform", python_platform)
    def get_processor_name():
        if pp.system() == "Windows":
            return pp.processor()
        elif pp.system() == "Darwin":
            os.environ['PATH'] = os.environ['PATH'] + os.pathsep + '/usr/sbin'
            command ="sysctl -n machdep.cpu.brand_string"
            import subprocess
            return subprocess.check_output(command).strip()
        elif pp.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                data = f.read()
            import re
            for line in data.split("\n"):
                if "model name" in line:
                    return re.sub(".*model name.*:", "", line,1).strip()
        assert False
    info = {}
    ld = get_linux_distribution()
    if ld:
        info["linux_distribution"] = ld
    release = platform_release(pp.release())
    info.update({
            ""          : sys.platform,
            "name"      : platform_name(sys.platform, info.get("linux_distribution") or release),
            "release"   : pp.release(),
            "sysrelease": release,
            "platform"  : pp.platform(),
            "machine"   : pp.machine(),
            "processor" : pp.processor(),
            "architecture" : pp.architecture(),
            })
    try:
        info["processor"] = get_processor_name()
    except:
        info["processor"] = pp.processor()
    return info
#cache the output:
platform_info_cache = None
def get_platform_info():
    global platform_info_cache
    if platform_info_cache is None:
        platform_info_cache = do_get_platform_info()
    return platform_info_cache


def get_version_from_url(url):
    e = None
    try:
        import urllib2
    except ImportError as e:
        log("get_version_from_url(%s) urllib2 not found: %s", url, e)
        return None
    try:
        response = urllib2.urlopen(url)
        latest_version = response.read().rstrip("\n\r")
        latest_version_no = tuple(int(y) for y in latest_version.split("."))
        log("get_version_from_url(%s)=%s", url, latest_version_no)
        return latest_version_no
    except urllib2.HTTPError as e:
        log("get_version_from_url(%s)", url, exc_info=True)
        if hasattr(e, "code") and e.code==404:
            log("no version at url=%s", url)
        else:
            log("Error retrieving URL '%s': %s", url, e)
    except urllib2.URLError as e:
        log("get_version_from_url(%s)", url, exc_info=True)
        log("Error retrieving URL '%s': %s", url, e)
    except Exception, e:
        log("get_version_from_url(%s)", url, exc_info=True)
        log("Error retrieving URL '%s': %s", url, e)
    return None

def version_update_check():
    FAKE_NEW_VERSION = envbool("XPRA_FAKE_NEW_VERSION", False)
    from xpra.os_util import WIN32
    if WIN32:
        #no idea how to make it verify the certificate properly
        #so don't bother
        CURRENT_VERSION_URL = "http://xpra.org/CURRENT_VERSION"
    else:
        CURRENT_VERSION_URL = "https://xpra.org/CURRENT_VERSION"
    PLATFORM_FRIENDLY_NAMES = {
        "linux2"    : "LINUX",
        "win"       : "WINDOWS",
        "darwin"    : "OSX",
        }
    our_version_no = tuple(int(y) for y in XPRA_VERSION.split("."))
    platform_name = PLATFORM_FRIENDLY_NAMES.get(sys.platform, sys.platform)
    arch = get_platform_info().get("machine")
    latest_version_no = None
    if arch:
        latest_version_no = get_version_from_url("%s_%s_%s?%s" % (CURRENT_VERSION_URL, platform_name, arch, XPRA_VERSION))
    if not latest_version_no:
        latest_version_no = get_version_from_url("%s_%s?%s" % (CURRENT_VERSION_URL, platform_name, XPRA_VERSION))
    if not latest_version_no:
        latest_version_no = get_version_from_url("%s?%s" % (CURRENT_VERSION_URL, XPRA_VERSION))
    if latest_version_no is None:
        log("version_update_check() failed to contact version server")
        return None
    elif latest_version_no>our_version_no or FAKE_NEW_VERSION:
        log("version_update_check() newer version found! local version is %s and the latest version available is %s", our_version_no, latest_version_no)
        #latest_version = ".".join([str(x) for x in latest_version_no])
        return latest_version_no
    else:
        return False
