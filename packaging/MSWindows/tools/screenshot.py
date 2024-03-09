#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys


def main(argv=()) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Screenshot", "Screenshot"):
        from xpra.platform.win32 import gdi_screen_capture
        return gdi_screen_capture.main(argv)


if __name__ == "__main__":
    v = main(sys.argv)
    sys.exit(v)
