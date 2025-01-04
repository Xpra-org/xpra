#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger

log = Logger("dbus")


def dbus_exception_wrap(fn, info="cannot setup dbus instance"):
    try:
        v = fn()
        log(f"dbus_exception_wrap() {fn}()={v}")
        return v
    except ImportError as e:
        log("%s", exc_info=True)
        log.warn(f"Warning: {info}")
        log.warn(f" {e}")
    except Exception as e:
        log("%s", exc_info=True)
        if str(e).find("org.freedesktop.DBus.Error.NoServer") < 0:
            log.error("dbus server error", exc_info=True)
        log.error(f"Error: {info}")
        # split on ":" unless it is quoted:
        tmp = "-XX-" * 10
        msg = str(e).replace("':'", tmp)
        for x in msg.split(":"):
            log.error("  %s", x.replace(tmp, "':'").strip())
    return None
