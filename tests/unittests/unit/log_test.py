#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import logging
import unittest

from xpra.log import Logger, escape_log_message


class LogEscapeTest(unittest.TestCase):

    def capture(self, fn, *args) -> str:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.root.addHandler(handler)
        try:
            fn(*args)
        finally:
            logging.root.removeHandler(handler)
        return stream.getvalue()

    def test_escape(self):
        self.assertEqual(escape_log_message("%s", "plain text\twith a tab"), "plain text\twith a tab")
        self.assertEqual(escape_log_message("%s", "a\x1b[2Jb\x00c\x9bd"), "a\\x1b[2Jb\\x00c\\x9bd")
        self.assertEqual(escape_log_message("%s", "name\u202etxt.exe"), "name\\u202etxt.exe")
        self.assertEqual(escape_log_message("%s", "one\r\ntwo"), "one\\x0d\\ntwo")
        # line breaks from the format string are kept:
        self.assertEqual(escape_log_message("first\nsecond %s", "first\nsecond x"), "first\nsecond x")

    def test_xpra_logger(self):
        log = Logger("test-log-escape")
        output = self.capture(log.info, "hostname=%s", "host\x1b[2J\n2026-10-20 12:00:00 forged line")
        self.assertEqual(output, "hostname=host\\x1b[2J\\n2026-10-20 12:00:00 forged line\n")

    def test_stdlib_logger(self):
        output = self.capture(logging.getLogger("test-log-escape").warning, "value=%s", "\u202eevil")
        self.assertEqual(output, "value=\\u202eevil\n")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
