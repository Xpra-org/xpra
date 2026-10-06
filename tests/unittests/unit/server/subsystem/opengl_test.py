#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.server.subsystem.opengl import OpenGLInfo, OPENGL_PROBE_RUN_WAIT_TIME


class OpenGLProbeTest(unittest.TestCase):

    def query(self, wrapper: list[str]):
        command = SimpleNamespace(get_full_child_command=lambda cmd: wrapper + list(cmd))
        server = SimpleNamespace(subsystems={"command": command}, get_child_env=lambda: {"XPRA_RUN_WAIT_TIME": "0"})
        info = OpenGLInfo(server)
        info.display = ":99"
        with patch("xpra.platform.paths.get_xpra_command", return_value=["xpra"]), \
             patch("xpra.server.subsystem.opengl.probe_opengl_module", return_value={"error": "missing"}) as module, \
             patch("xpra.server.subsystem.opengl.run_opengl_probe", return_value={"success": "True"}) as probe:
            return info.query_opengl(), module, probe

    def test_local_probe(self):
        props, module, probe = self.query([])
        self.assertEqual(props, {"error": "missing"})
        module.assert_called_once()
        probe.assert_not_called()

    def test_wrapped_probe(self):
        # the wrapper may run the probe elsewhere: skip the local module check and wait for the result
        props, module, probe = self.query(["xpra", "run", "socket:///tmp/runner", "--"])
        self.assertEqual(props, {"success": "True"})
        module.assert_not_called()
        cmd, env, display = probe.call_args.args
        self.assertEqual(cmd, ["xpra", "run", "socket:///tmp/runner", "--", "xpra", "opengl", "--opengl=force"])
        self.assertEqual(env["XPRA_RUN_WAIT_TIME"], str(OPENGL_PROBE_RUN_WAIT_TIME))
        self.assertEqual(display, ":99")


if __name__ == "__main__":
    unittest.main()
