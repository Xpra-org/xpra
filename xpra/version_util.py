#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import socket
import platform
from typing import Any, Dict, Tuple, Optional

#tricky: use xpra.scripts.config to get to the python "platform" module
import xpra
from xpra.util import envbool, typedict, get_util_logger
from xpra.os_util import get_linux_distribution, BITS, POSIX, WIN32
from xpra.common import FULL_INFO

XPRA_VERSION = xpra.__version__     #@UndefinedVariable

CHECK_SSL : bool = envbool("XPRA_VERSION_CHECK_SSL", True)
SSL_CAFILE : str = ""
if WIN32:
    try:
        import certifi  #@UnresolvedImport
        SSL_CAFILE = certifi.where()
    except (ImportError, AttributeError):
        get_util_logger().error("failed to locate SSL ca file", exc_info=True)
SSL_CAFILE = os.environ.get("XPRA_SSL_CAFILE", SSL_CAFILE)


def log(msg, *args, **kwargs) -> None:
    get_util_logger().debug(msg, *args, **kwargs)
def warn(msg, *args, **kwargs) -> None:
    get_util_logger().warn(msg, *args, **kwargs)


def vparts(vstr:str, n=1) -> str:
    return ".".join(vstr.split(".")[:n])


def version_str() -> str:
    rstr = revision_str()
    return XPRA_VERSION if not rstr else XPRA_VERSION+"-"+rstr

def full_version_str() -> str:
    rstr = version_str()
    try:
        from xpra.src_info import BRANCH  # pylint: disable=import-outside-toplevel
    except ImportError:
        pass
    else:
        if BRANCH=="master":
            rstr += " beta"
    return rstr

def caps_to_version(caps : typedict) -> str:
    return caps.strget("version", "0")+"-"+caps_to_revision(caps)

def caps_to_revision(caps : typedict) -> str:
    revision = caps.strget("revision")
    local_modifications = caps.intget("local_modifications")
    commit = caps.strget("commit")
    branch = caps.strget("branch")
    return make_revision_str(revision, local_modifications, branch, commit)

def revision_str() -> str:
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS, BRANCH, COMMIT  #pylint: disable=import-outside-toplevel
    except ImportError:
        pass
    else:
        return make_revision_str(REVISION, LOCAL_MODIFICATIONS, BRANCH, COMMIT)
    return ""

def make_revision_str(revision, local_modifications, branch, commit) -> str:
    rstr = ""
    try:
        if isinstance(revision, int):
            rstr += "r%i" % revision
        if isinstance(local_modifications, int) and local_modifications>0:
            rstr += "M"
        if branch=="master" and commit:
            rstr += " (%s)" % commit
    except TypeError:
        get_util_logger().debug("make_revision_str%s", (revision, local_modifications, branch, commit), exc_info=True)
    return rstr


def version_compat_check(remote_version) -> Optional[str]:
    if remote_version is None:
        msg = "remote version not available!"
        log(msg)
        return msg
    try:
        rv = parse_version(remote_version)
    except ValueError:
        warn(f"Warning: failed to parse remote version {remote_version!r}")
        return None
    try:
        lv = parse_version(XPRA_VERSION)
    except ValueError:
        warn(f"Warning: failed to parse local version {XPRA_VERSION!r}")
        return None
    if rv==lv:
        log("identical remote version: %s", remote_version)
        return None
    if rv[0:2]<(3, 0):
        #this is the oldest version we support
        msg = f"remote version {rv[:2]} is too old, sorry"
        log(msg)
        return msg
    if rv[0]>0:
        log(f"newer remote version {remote_version} should work, we'll see..")
        return None
    log(f"local version {XPRA_VERSION!r} should be compatible with remote version {remote_version!r}")
    return None


def get_host_info(full_info:int=1) -> Dict[str, Any]:
    #this function is for non UI thread info
    info : Dict[str, Any] = {}
    if full_info>1:
        info.update({
        "byteorder"             : sys.byteorder,
        "python"                : {
            "bits"                  : BITS,
            "full_version"          : sys.version,
            "version"               : ".".join(str(x) for x in sys.version_info[:3]),
            },
        })
    if full_info>0:
        try:
            hostname = socket.gethostname()
            if hostname:
                info["hostname"] = hostname
        except OSError:
            pass
        if POSIX:
            info.update({
                "uid"   : os.getuid(),
                "gid"   : os.getgid(),
                })
    return info

def get_version_info(full:int=1) -> Dict[str, Any]:
    info : Dict[str, Any] = {"version" : vparts(XPRA_VERSION, full+1)}
    if full>0:
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.src_info import LOCAL_MODIFICATIONS, REVISION, COMMIT, BRANCH
            for k,v in {
                "local_modifications"   : LOCAL_MODIFICATIONS,
                "revision"              : REVISION,
                "branch"                : BRANCH,
                "commit"                : COMMIT,
                }.items():
                if v is not None and v!="unknown":
                    info[k] = v
        except ImportError as e:
            warn("missing some source information: %s", e)
    if full>1:
        info["build"] = get_build_info()
    return info

def get_build_info(full:int=1) -> Dict[str, Any]:
    info : Dict[str, Any] = {}
    try:
        from xpra import build_info  # pylint: disable=import-outside-toplevel
        #rename these build info properties:
        for k,bk in {
                    "date"                 : "BUILD_DATE",
                    "time"                 : "BUILD_TIME",
                    "bit"                  : "BUILD_BIT",
                    "cpu"                  : "BUILD_CPU",
                    "compiler"             : "COMPILER_VERSION",
                    "nvcc"                 : "NVCC_VERSION",
                    "linker"               : "LINKER_VERSION",
                    "python"               : "PYTHON_VERSION",
                    "cython"               : "CYTHON_VERSION",
                  }.items():
            v = getattr(build_info, bk, None)
            if v is not None:
                if bk.endswith("_VERSION"):
                    v = parse_version(v)
                info[k] = v
        #record library versions:
        if full>1:
            info["lib"] = dict((k.lstrip("lib_"), parse_version(getattr(build_info, k))) for k in dir(build_info) if k.startswith("lib_"))
    except Exception as e:
        warn("missing some build information: %s", e)
    log(f"get_build_info({full})={info}")
    return info

def parse_version(v) -> Tuple[Any, ...]:
    if isinstance(v, str):
        def maybeint(v):
            try:
                return int(v)
            except ValueError:
                return v
        v = tuple(maybeint(x) for x in v.split("-")[0].split("."))
    return tuple(v or ())

def vtrim(v, parts=FULL_INFO+1):
    if isinstance(v, (list, tuple)):
        return v[:parts]
    return v

def dict_version_trim(d, parts=FULL_INFO+1):
    """
    trims version numbers from info dictionaries
    """
    def vfilt(k, v):
        if k.endswith("version") and isinstance(v, (list, tuple)):
            v = vtrim(v, parts)
        elif isinstance(v, dict):
            return k, dict_version_trim(v, parts)
        return k, v
    return dict(vfilt(k,v) for k,v in d.items())


def do_get_platform_info() -> Dict[str, Any]:
    # pylint: disable=import-outside-toplevel
    from xpra.os_util import platform_name, platform_release
    pp = sys.modules.get("platform", platform)
    def get_processor_name():
        if pp.system() == "Windows":
            return pp.processor()
        if pp.system() == "Darwin":
            os.environ['PATH'] = os.environ['PATH'] + os.pathsep + '/usr/sbin'
            command = ["sysctl", "-n", "machdep.cpu.brand_string"]
            from subprocess import check_output
            return check_output(command).strip()
        if pp.system() == "Linux":
            with open("/proc/cpuinfo", "r", encoding="latin1") as f:
                data = f.read()
            import re
            for line in data.split("\n"):
                if "model name" in line:
                    return re.sub(".*model name.*:", "", line, count=1).strip()
        return pp.processor()
    info : Dict[str, Any] = {}
    ld = get_linux_distribution()
    if ld:
        info["linux_distribution"] = ld
    try:
        release = platform_release(pp.release())
    except OSError:
        log("do_get_platform_info()", exc_info=True)
        release = "unknown"
    info.update({
            ""          : sys.platform,
            "name"      : platform_name(sys.platform, info.get("linux_distribution") or release),
            "release"   : pp.release(),
            "sysrelease": release,
            "platform"  : pp.platform(),
            "machine"   : pp.machine(),
            "architecture" : pp.architecture(),
            "processor" : get_processor_name(),
            })
    return info
#cache the output:
platform_info_cache = None
def get_platform_info():
    global platform_info_cache
    if platform_info_cache is None:
        platform_info_cache = do_get_platform_info()
    return platform_info_cache


def get_version_from_url(url) -> Optional[Tuple[int,...]]:
    try:
        from urllib.request import urlopen
    except ImportError as e:
        log("get_version_from_url(%s) urllib2 not found: %s", url, e)
        return None
    try:
        response = urlopen(url, cafile=SSL_CAFILE)
        latest_version = response.read().rstrip(b"\n\r")
        latest_version_no = tuple(int(y) for y in latest_version.split(b"."))
        log("get_version_from_url(%s)=%s", url, latest_version_no)
        return latest_version_no
    except Exception as e:
        log("get_version_from_url(%s)", url, exc_info=True)
        if getattr(e, "code", 0)==404:
            log("no version at url=%s", url)
        else:
            log("Error retrieving URL '%s': %s", url, e)
    return None

def version_update_check():
    FAKE_NEW_VERSION = envbool("XPRA_FAKE_NEW_VERSION", False)
    CURRENT_VERSION_URL = ("https" if CHECK_SSL else "http") + "://xpra.org/CURRENT_VERSION"
    PLATFORM_FRIENDLY_NAMES = {
        "linux2"    : "LINUX",
        "win"       : "WINDOWS",
        "darwin"    : "OSX",
        }
    our_version_no = tuple(int(y) for y in XPRA_VERSION.split("."))
    platform_name = PLATFORM_FRIENDLY_NAMES.get(sys.platform, sys.platform)
    arch = get_platform_info().get("machine")
    for url in (
        f"{CURRENT_VERSION_URL}_{platform_name}_{arch}?{XPRA_VERSION}",
        f"{CURRENT_VERSION_URL}_{platform_name}?{XPRA_VERSION}",
        f"{CURRENT_VERSION_URL}?{XPRA_VERSION}",
        ):
        latest_version_no = get_version_from_url(url)
        if latest_version_no:
            break
    if latest_version_no is None:
        log("version_update_check() failed to contact version server")
        return None
    if latest_version_no>our_version_no or FAKE_NEW_VERSION:
        log("version_update_check() newer version found")
        log(" local version is {our_version_no} and the latest version available is {latest_version_no}")
        return latest_version_no
    return False
