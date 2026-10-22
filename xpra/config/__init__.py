#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


"""Configuration errors and shared diagnostic hooks.

Metadata, validation, defaults, and file loading live in separate modules so
callers can import the pieces they need without discovering host settings.
"""

from xpra.common import noop
from xpra.exit_codes import ExitValue


def warn(msg: str) -> None:
    from xpra.util.io import stderr_print
    stderr_print(msg)


# The server, launcher, and configuration tool may redirect these hooks.
debug = noop


class InitException(Exception):
    pass


class InitInfo(Exception):
    pass


class InitExit(Exception):
    def __init__(self, status: ExitValue, msg):
        self.status = status
        super().__init__(msg)
