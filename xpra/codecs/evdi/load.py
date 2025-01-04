#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from subprocess import Popen, TimeoutExpired
from xpra.os_util import LINUX
from xpra.util.io import which

from xpra.log import Logger

log = Logger("evdi")


def load_evdi_module(device_count=1):
    log(f"load_evdi_module({device_count})")
    if not LINUX:
        log("evdi is only supported on Linux")
        return False
    modprobe = which("modprobe")
    if not modprobe:
        log.warn("Warning: cannot load evdi, 'modprobe' was not found")
        return False
    cmd = [modprobe, "evdi", f"initial_device_count={device_count}"]
    try:
        with Popen(cmd, shell=False) as proc:
            out, err = proc.communicate(None, 10)
            if out:
                log(f"stdout({cmd})={out!r}")
            if err:
                log(f"stderr({cmd})={err!r}")
            return proc.poll() == 0
    except TimeoutExpired:
        log.error("Error: 'modprobe evdi' timed out")
    except OSError:
        log.error("Error: failed to execute %s", " ".join(cmd), exc_info=True)
    return False


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.log import enable_color, consume_verbose_argv
    from xpra.platform import program_context
    with program_context("evdi loader"):
        enable_color()
        consume_verbose_argv(sys.argv, "evdi")
        print(f"module loaded: {load_evdi_module()}")


if __name__ == "__main__":
    main()
