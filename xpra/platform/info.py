# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.platform import platform_import


def get_posix_sys_info():
    info = {}
    try:
        import resource
        for k, constant in {
            "server"    : "RUSAGE_SELF",
            "children"  : "RUSAGE_CHILDREN",
            "total"     : "RUSAGE_BOTH",
            }.items():
            try:
                v = getattr(resource, constant)
            except (NameError, AttributeError):
                continue
            stats = resource.getrusage(v)
            minfo = info.setdefault("memory", {}).setdefault(k, {})
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
                minfo[var] = value
    except Exception:
        from xpra.os_util import get_util_logger
        get_util_logger().error("Error getting memory usage info", exc_info=True)
    return info

def get_sys_info():
    if os.name=="posix":
        return get_posix_sys_info()
    return {}

def get_version_info():
    return {}

def _get_pwd():
    try:
        import pwd
        USER_ID = os.getuid()
        return pwd.getpwuid(USER_ID)
    except Exception:
        return None

def get_username():
    p = _get_pwd()
    if p is None:
        return ""
    return p.pw_name

def get_name():
    p = _get_pwd()
    if p is None:
        return ""
    return p.pw_gecos.replace(",", "")

def get_user_info():
    return {
            "username"  : get_username(),
            "name"      : get_name()
            }

platform_import(globals(), "info", False,
                "get_sys_info",
                "get_version_info",
                "get_username",
                "get_name")
