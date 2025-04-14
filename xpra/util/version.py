#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import socket
import platform
from typing import Any, Final

import xpra
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.os_util import BITS, POSIX, WIN32, OSX
from xpra.util.io import get_util_logger
from xpra.util.system import get_linux_distribution, platform_release, platform_name
from xpra.common import FULL_INFO

XPRA_VERSION: Final[str] = xpra.__version__
XPRA_NUMERIC_VERSION: tuple[int] = xpra.__version_info__

CHECK_SSL: bool = envbool("XPRA_VERSION_CHECK_SSL", True)
SSL_CAFILE: str = ""
if WIN32:
    try:
        import certifi

        SSL_CAFILE = certifi.where()
    except (ImportError, AttributeError):
        get_util_logger().error("failed to locate SSL ca file", exc_info=True)
SSL_CAFILE = os.environ.get("XPRA_SSL_CAFILE", SSL_CAFILE)


def log(msg, *args, **kwargs) -> None:
    get_util_logger().debug(msg, *args, **kwargs)


def warn(msg, *args, **kwargs) -> None:
    get_util_logger().warn(msg, *args, **kwargs)


def vparts(vstr: str, n=1) -> str:
    return ".".join(vstr.split(".")[:n])


def version_str() -> str:
    rstr = revision_str()
    return XPRA_VERSION if not rstr else XPRA_VERSION + "-" + rstr


def full_version_str() -> str:
    rstr = version_str()
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.src_info import BRANCH
    except ImportError:
        pass
    else:
        if BRANCH == "master":
            rstr += " beta"
    try:
        from xpra.build_info import build
        btype = build["type"]
        if btype == "light":
            rstr += " (light build)"
    except (ImportError, KeyError):
        pass
    return rstr


def caps_to_version(caps: typedict) -> str:
    return caps.strget("version", "0") + "-" + caps_to_revision(caps)


def caps_to_revision(caps: typedict) -> str:
    revision = caps.intget("revision")
    local_modifications = caps.intget("local_modifications")
    commit = caps.strget("commit")
    branch = caps.strget("branch")
    return make_revision_str(revision, local_modifications, branch, commit)


def revision_str() -> str:
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS, BRANCH, COMMIT
    except ImportError:
        pass
    else:
        return make_revision_str(REVISION, LOCAL_MODIFICATIONS, BRANCH, COMMIT)
    return ""


def make_revision_str(revision, local_modifications, branch, commit) -> str:
    rstr = ""
    try:
        if isinstance(revision, int):
            rstr += f"r{revision}"
        if isinstance(local_modifications, int) and local_modifications > 0:
            rstr += "M"
        if branch == "master" and commit:
            rstr += f" ({commit})"
    except TypeError:
        get_util_logger().debug("make_revision_str%s", (revision, local_modifications, branch, commit), exc_info=True)
    return rstr


def version_compat_check(remote_version) -> str | None:
    if not remote_version:
        msg = "remote version is not available"
        log(msg)
        return msg
    try:
        rv = parse_version(remote_version)
    except ValueError:
        warn(f"Warning: failed to parse remote version {remote_version!r}")
        return None
    rvstr = ".".join(str(part) for part in rv)
    if rv == XPRA_NUMERIC_VERSION:
        log(f"identical remote version: {rvstr!r}")
        return None
    if rv[:2] == XPRA_NUMERIC_VERSION[:2]:
        log(f"identical major.minor in remote version: {rvstr!r}")
        return None
    try:
        if rv[0:2] < (3, 0):
            # this is the oldest version we support
            msg = f"remote version {rvstr!r} is too old, sorry"
            log(msg)
            return msg
        if rv[0:2] < (3, 1, 9):
            warn(f"Warning: remote version {rvstr!r} is outdated and buggy")
            return None
    except TypeError as e:
        msg = f"invalid remote version {rvstr!r}: {e}"
        log(msg)
        return msg
    if rv[0] > 0:
        log(f"newer remote version {rvstr!r} should work, we'll see..")
        return None
    log(f"local version {XPRA_VERSION!r} should be compatible with remote version {rvstr!r}")
    return None


def get_host_info(full_info: int = 1) -> dict[str, Any]:
    # this function is for non UI thread info
    info: dict[str, Any] = {}
    if full_info > 1:
        info |= {
            "byteorder": sys.byteorder,
            "python": {
                "bits": BITS,
                "full_version": sys.version,
                "version": ".".join(str(x) for x in sys.version_info[:3]),
            },
        }
    if full_info > 0:
        try:
            hostname = socket.gethostname()
            if hostname:
                info["hostname"] = hostname
        except OSError:
            pass
        if POSIX:
            info |= {
                "uid": os.getuid(),
                "gid": os.getgid(),
            }
    return info


def get_version_info(full: int = 1) -> dict[str, Any]:
    info: dict[str, Any] = {"version": vparts(XPRA_VERSION, full + 1)}
    if full > 0:
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.src_info import LOCAL_MODIFICATIONS, REVISION, COMMIT, BRANCH
            for k, v in {
                "local_modifications": LOCAL_MODIFICATIONS,
                "revision": REVISION,
                "branch": BRANCH,
                "commit": COMMIT,
            }.items():
                if v is not None and v != "unknown":
                    info[k] = v
        except ImportError as e:
            warn("missing some source information: %s", e)
        info.update(get_build_info(full))
    return info


def get_build_info(full: int = 1) -> dict[str, Any]:
    info: dict[str, Any] = {}

    try:
        from xpra import build_info  # pylint: disable=import-outside-toplevel
    except ImportError:
        return {}

    build = getattr(build_info, "build", {})

    def add_attrs(attrs: dict[str, str]) -> None:
        for k, type_info in attrs.items():
            v = build.get(k, None)
            if v is not None:
                if type_info.endswith("_VERSION"):
                    v = parse_version(v)
                info[k] = v

    try:
        add_attrs({
            "date": "BUILD_DATE",
            "time": "BUILD_TIME",
        })
        if full > 0:
            add_attrs({
                "bit": "BUILD_BIT",
                "cpu": "BUILD_CPU",
                "type": "BUILD_TYPE",
                "compiler": "COMPILER_VERSION",
                "nvcc": "NVCC_VERSION",
                "linker": "LINKER_VERSION",
                "python": "PYTHON_VERSION",
                "cython": "CYTHON_VERSION",
            })
        if full > 1:
            # record library versions:
            info["lib"] = {k.lstrip("lib_"): parse_version(getattr(build_info, k))
                           for k in dir(build_info) if k.startswith("lib_")}
    except Exception as e:
        warn("missing some build information: %s", e)
    log(f"get_build_info({full})={info}")
    return info


def parse_version(v) -> tuple[Any]:
    if isinstance(v, str) and v:
        def maybeint(value: str) -> int | str:
            try:
                return int(value)
            except ValueError:
                return value

        v = tuple(maybeint(x) for x in v.split("-")[0].split("."))
    return tuple(v or ())


def vtrim(v, parts=FULL_INFO + 1):
    if isinstance(v, (list, tuple)):
        return v[:parts]
    return v


def dict_version_trim(d, parts=FULL_INFO + 1) -> dict:
    """
    trims version numbers from info dictionaries
    """

    def vfilt(k, v):
        if k.endswith("version") and isinstance(v, (list, tuple)):
            v = vtrim(v, parts)
        elif isinstance(v, dict):
            return k, dict_version_trim(v, parts)
        return k, v

    return dict(vfilt(k, v) for k, v in d.items())


def do_get_platform_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    if POSIX and not OSX:
        ld = get_linux_distribution()
        ldvalid = tuple(x for x in ld if x not in ("", "unknown", "n/a"))
        if ldvalid:
            info["linux_distribution"] = ld
    try:
        release = platform_release(platform.release())
    except OSError:
        log("do_get_platform_info()", exc_info=True)
        release = "unknown"
    info |= {
        "": sys.platform,
        "name": platform_name(sys.platform, info.get("linux_distribution") or release),
        "release": platform.release(),
        "sysrelease": release,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "architecture": platform.architecture(),
    }
    try:
        from xpra.util.system import get_processor_name
        info["processor"] = get_processor_name()
    except Exception:
        log("failed to query processor", exc_info=True)
    return info


# cache the output:
platform_info_cache = None


def get_platform_info() -> dict[str, Any]:
    global platform_info_cache
    if platform_info_cache is None:
        platform_info_cache = do_get_platform_info()
    return platform_info_cache


def get_version_from_url(url: str) -> tuple[int, ...]:
    try:
        import ssl
        from urllib.request import urlopen
        from urllib.error import HTTPError
    except ImportError as e:
        log("get_version_from_url(%s) urllib2 not found: %s", url, e)
        return ()
    try:
        context = ssl.create_default_context(cafile=SSL_CAFILE)
        response = urlopen(url, context=context)
        latest_version = response.read().rstrip(b"\n\r")
        latest_version_no = tuple(int(y) for y in latest_version.split(b"."))
        log("get_version_from_url(%s)=%s", url, latest_version_no)
        return latest_version_no
    except HTTPError as e:
        log(f"get_version_from_url({url!r}) {e}", exc_info=e.code != 404)
    except Exception:
        get_util_logger().error(f"Error accessing {url!r}", exc_info=True)
    return ()


PLATFORM_FRIENDLY_NAMES: dict[str, str] = {
    "linux2": "LINUX",
    "win": "WINDOWS",
    "darwin": "OSX",
}


def get_branch() -> str:
    BRANCH = os.environ.get("XPRA_CURRENT_VERSION_BRANCH", "")
    if BRANCH:
        return BRANCH
    try:
        from xpra.src_info import BRANCH
        return BRANCH
    except ImportError as e:
        log(f"unknown branch: {e}")
    return ""


def get_latest_version() -> bool | None | tuple[int, ...]:
    CURRENT_VERSION_URL = ("https" if CHECK_SSL else "http") + "://xpra.org/CURRENT_VERSION"
    BRANCH = get_branch()
    branch_strs = []
    if BRANCH not in ("", "master"):
        branch_parts = BRANCH.split(".")            # ie: "v6.2.x" -> ["v6", "2", "x"]
        if branch_parts[-1] == "x":
            branch_parts = branch_parts[:-1]        # ie: ["v6", "2"]
        branch_strs.append("_" + "_".join(branch_parts[:2]))    # ie: "_v6_2"
        if len(branch_parts) >= 2:
            branch_strs.append("_" + branch_parts[0])           # ie: "_v6"
    branch_strs.append("")
    platname = PLATFORM_FRIENDLY_NAMES.get(sys.platform, sys.platform)
    arch = get_platform_info().get("machine")
    for branch_str in branch_strs:
        for url in (
            f"{CURRENT_VERSION_URL}{branch_str}_{platname}_{arch}?{XPRA_VERSION}",
            f"{CURRENT_VERSION_URL}{branch_str}_{platname}?{XPRA_VERSION}",
            f"{CURRENT_VERSION_URL}{branch_str}?{XPRA_VERSION}",
        ):
            latest_version_no = get_version_from_url(url)
            if latest_version_no:
                return latest_version_no
    return ()


def version_update_check() -> bool | None | tuple[int, ...]:
    FAKE_NEW_VERSION = envbool("XPRA_FAKE_NEW_VERSION", False)
    latest_version_no = get_latest_version()
    if not latest_version_no:
        log("version_update_check() failed to contact version server")
        return None
    if latest_version_no > XPRA_NUMERIC_VERSION or FAKE_NEW_VERSION:
        log("version_update_check() newer version found")
        log(f" local version is {XPRA_NUMERIC_VERSION} and the latest version available is {latest_version_no}")
        return latest_version_no
    return False
