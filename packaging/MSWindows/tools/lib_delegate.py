#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys


def main(argv=()) -> int:
    # add `Xpra/` and `Xpra/lib` to the %PATH%
    # then call the real EXE:
    app_dir, exe_name = os.path.split(argv[0])
    exe_name = os.path.normcase(exe_name)
    if exe_name.lower().endswith(".exe"):
        exe_name = exe_name[:-4]
    lib_dir = os.path.join(app_dir, "lib")
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for d in (lib_dir, app_dir):
        if d not in paths:
            paths.append(d)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(paths)
    # try harder to find the matching executable file:
    for ext in (".exe", "-1.0.exe", ""):
        actual_exe = os.path.join(lib_dir, f"{exe_name}{ext}")
        if os.path.exists(actual_exe):
            break
    from subprocess import run
    args = [actual_exe] + list(argv[1:])
    return run(args, stdin=None, stdout=sys.stdout, stderr=sys.stderr, shell=False, env=env).returncode


if __name__ == "__main__":
    v = main(sys.argv)
    sys.exit(v)
