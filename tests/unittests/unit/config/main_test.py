#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from xpra.config import __main__ as tool
from xpra.config.types import dict_to_config


class ConfigToolTest(unittest.TestCase):

    def test_default_output(self):
        output = io.StringIO()
        with patch("xpra.platform.program_context", return_value=nullcontext()), patch("xpra.log.enable_color"), \
             patch("xpra.log.consume_verbose_argv", return_value=False), \
             patch.object(tool, "make_defaults_struct", return_value=dict_to_config({"quality": 72, "lock": None, "start": ["xterm"]})), \
             redirect_stdout(output):
            tool.main(["Config_info"])
        text = output.getvalue()
        self.assertIn("Default Configuration:", text)
        self.assertRegex(text, r"quality\s+: 72")
        self.assertRegex(text, r"lock\s+: Auto")
        self.assertRegex(text, r"start\s+: xterm")

    def test_file_and_missing_file_output(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "test.conf"
            file.write_text("title=supplied\nquality=72\n")
            output = io.StringIO()
            with patch("xpra.platform.program_context", return_value=nullcontext()), patch("xpra.log.enable_color"), \
                 patch("xpra.log.consume_verbose_argv", return_value=True), patch("xpra.config.debug"), redirect_stdout(output):
                tool.main(["Config_info", str(file), str(file) + ".missing"])
            text = output.getvalue()
            self.assertIn("supplied", text)
            self.assertIn("Error: file not found", text)


if __name__ == "__main__":
    unittest.main()
