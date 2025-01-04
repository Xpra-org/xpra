# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.platform import platform_import


def get_posix_sys_info() -> dict[str, dict[str, dict[str, int]]]:
    meminfo: dict[str, dict[str, int]] = {}
    try:
        import resource
        for k, constant in {
            "server": "RUSAGE_SELF",
            "children": "RUSAGE_CHILDREN",
            "total": "RUSAGE_BOTH",
        }.items():
            try:
                v = getattr(resource, constant)
            except (NameError, AttributeError):
                continue
            stats = resource.getrusage(v)
            kinfo: dict[str, int] = {}
            meminfo[k] = kinfo
            for var in (
                    "utime", "stime", "maxrss",
                    "ixrss", "idrss", "isrss",
                    "minflt", "majflt", "nswap",
                    "inblock", "oublock",
                    "msgsnd", "msgrcv",
                    "nsignals", "nvcsw", "nivcsw",
            ):
                value = getattr(stats, "ru_%s" % var)
                if isinstance(value, float):
                    value = int(value)
                kinfo[var] = value
    except OSError:  # pragma: no cover
        from xpra.util.io import get_util_logger
        get_util_logger().error("Error getting memory usage info", exc_info=True)
    return {
        "memory": meminfo,
    }


def get_sys_info() -> dict:
    from xpra.common import FULL_INFO
    if os.name == "posix" and FULL_INFO > 1:
        return get_posix_sys_info()
    return {}  # pragma: no cover


def get_version_info() -> dict:
    return {}


def _get_pwd():
    if os.name != "posix":  # pragma: no cover
        return None
    try:
        import pwd
        user_id = os.getuid()
        return pwd.getpwuid(user_id)
    except KeyError:  # pragma: no cover
        return None


def get_username() -> str:
    p = _get_pwd()
    if p:
        return p.pw_name
    # pragma: no cover
    try:
        import getpass
        return getpass.getuser()
    except OSError:
        pass
    return ""


def get_name() -> str:
    p = _get_pwd()
    if p:
        return p.pw_gecos.replace(",", "")
    # pragma: no cover
    return ""


def get_user_info() -> dict[str, str]:
    return {
        "username": get_username(),
        "name": get_name(),
    }


platform_import(globals(), "info", False,
                "get_sys_info",
                "get_version_info",
                "get_username",
                "get_name")
