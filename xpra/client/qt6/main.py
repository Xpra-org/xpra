#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import signal


def main(args) -> int:
    from PyQt6.QtWidgets import QApplication
    if len(args) != 3:
        print("usage: %s host port" % (args[0], ))
        from xpra.exit_codes import ExitCode
        sys.exit(ExitCode.UNSUPPORTED)
    app = QApplication([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    host = args[1]
    port = int(args[2])
    from xpra.client.qt6.client import Qt6Client
    client = Qt6Client()
    client.connect(host, port)
    app.applicationStateChanged.connect(client.state_changed)
    #app.focusChanged.connect
    return app.exec()


if __name__ == "__main__":
    main(sys.argv)
