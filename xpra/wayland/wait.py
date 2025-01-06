# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.exit_codes import ExitCode


def main(args) -> ExitCode:
    from xpra.platform import program_context
    with program_context("Wait-for-Wayland", "Wait for Wayland"):
        from xpra.wayland.wait_for_display import wait_for_wayland_display
        if args:
            display = args[0]
        else:
            display = os.environ.get("WAYLAND_DISPLAY", "")
        try:
            wait_for_wayland_display(display)
            return ExitCode.OK
        except RuntimeError as e:
            sys.stderr.write(f"{e}\n")
            sys.stderr.flush()
            return ExitCode.FAILURE


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
