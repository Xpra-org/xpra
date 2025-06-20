#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from xpra.os_util import POSIX
from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class FileMixinTest(ServerMixinTest):

    def create_test_sockets(self):
        if not POSIX:
            return ()
        # socktype, socket, sockpath, cleanup_socket
        return [
            ("socket", None, "/fake/path", None)
        ]

    def test_fileprint(self):
        from xpra.server.subsystem import file as filesubsystem
        opts = AdHocStruct()
        opts.file_transfer = "yes"
        opts.file_size_limit = 10
        opts.printing = "yes"
        opts.open_files = "no"
        opts.open_url = "yes"
        opts.open_command = ""
        opts.lpadmin = "/usr/sbin/lpadmin"
        opts.lpinfo = "/usr/sbin/lpinfo"
        opts.add_printer_options = ""
        opts.postscript_printer = ""
        opts.pdf_printer = ""
        with silence_info(filesubsystem):
            self._test_mixin_class(filesubsystem.FileServer, opts)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
