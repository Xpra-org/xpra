# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal

from xpra.exit_codes import ExitCode, ExitValue


def os_signal(_sig, _frame) -> None:
    sys.exit(ExitCode.IO_ERROR)


def main(args) -> ExitValue:
    from xpra.platform import program_context
    with program_context("Wait-for-X11", "Wait for X11"):
        signal.signal(signal.SIGINT, os_signal)
        signal.signal(signal.SIGTERM, os_signal)
        from xpra.x11.bindings.wait_for_x_server import wait_for_x_server
        if args:
            display = args[0]
        else:
            display = os.environ.get("DISPLAY", "")
        try:
            wait_for_x_server(display)
            return ExitCode.OK
        except SystemExit as e:  # NOSONAR @SuppressWarnings("python:S5727")
            return e.code or 0
        except RuntimeError as e:
            sys.stderr.write(f"{e}\n")
            sys.stderr.flush()
            return ExitCode.FAILURE


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
