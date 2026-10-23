#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Build and source information for configuration tools."""

import sys
from xpra import config


def get_build_info() -> list[str]:
    info = []
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS, BRANCH, COMMIT
        info.append(f"revision {REVISION}")
        if COMMIT:
            info.append(f"commit {COMMIT} from {BRANCH} branch")
        try:
            mods = int(LOCAL_MODIFICATIONS)
            info.append(f"with {mods} local changes")
        except ValueError:
            pass
    except Exception as e:
        config.warn(f"Error: could not find the source information: {e}")
    try:
        from xpra.build_info import build
    except ImportError as e:
        config.warn(f"Error: could not find the build information: {e}")
        build = {}
    info.append(build.get("type", "") + " build")
    info.insert(0, "")
    einfo = "Python " + ".".join(str(v) for v in sys.version_info[:2])
    if machine := build.get("machine", ""):
        einfo += ", "+machine
    else:
        if bit := build.get("bit"):
            einfo += f", {bit}"
    info.insert(0, einfo)
    by = build.get("by", "")
    on = build.get("on", "")
    if by and on:
        info.append(f"built on {on} by {by}")
    date = build.get("date", "")
    time = build.get("time", "")
    if date and time:
        info.append(f"{date} {time}")
    cython = build.get("cython", "unknown")
    compiler = build.get("compiler", "unknown")
    if cython != "unknown" or compiler != "unknown":
        info.append("")
    if cython != "unknown":
        info.append(f"using Cython {cython}")
    if compiler != "unknown":
        cv = compiler.replace("Optimizing Compiler Version", "Optimizing Compiler\nVersion")
        info += cv.splitlines()
    return info
