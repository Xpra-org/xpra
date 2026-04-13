# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Entry point for the `xpra webcam-client` subcommand.
Spawned by the server when webcam forwarding is requested but v4l2loopback
is not available.  Connects back to the server over the unix socket,
authenticates with a one-time token, receives compressed webcam frames
and displays them in a GTK window.
"""

import sys
from typing import Any


def main(params: dict[str, Any]) -> int:
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init, set_default_icon

    with program_context("webcam-client", "Webcam"):
        set_default_icon("webcam.png")
        gui_init()
        from xpra.client.gtk3.webcam_window import main as window_main
        return window_main(params)


if __name__ == "__main__":
    sys.exit(main({}))
