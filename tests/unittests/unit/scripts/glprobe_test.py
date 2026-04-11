#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch, MagicMock
from subprocess import TimeoutExpired

from xpra.exit_codes import ExitCode
from xpra.util.env import nomodule_context
from xpra.scripts.glprobe import (
    OPENGL_PROBE_TIMEOUT,
    run_opengl_probe,
    run_glprobe,
    do_run_glcheck,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc(stdout="", returncode=0, timeout=False):
    """Build a mock subprocess whose communicate() returns fixed output."""
    proc = MagicMock()
    proc.returncode = returncode
    if timeout:
        # First call (with timeout=) raises TimeoutExpired; second returns empty strings.
        proc.communicate.side_effect = [
            TimeoutExpired(cmd="xpra", timeout=1),
            ("", ""),
        ]
    else:
        proc.communicate.return_value = (stdout, "")
    return proc


def _run_probe_with(stdout="", returncode=0, timeout=False):
    """Run run_opengl_probe() with a fully mocked subprocess environment."""
    proc = _make_proc(stdout=stdout, returncode=returncode, timeout=timeout)
    with patch("xpra.scripts.glprobe.find_spec", return_value=object()), \
         patch("xpra.scripts.glprobe.Popen", return_value=proc), \
         patch("xpra.scripts.glprobe.get_exec_env", return_value={}), \
         patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]), \
         patch("xpra.net.subprocess_wrapper.exec_kwargs", return_value={}):
        return run_opengl_probe()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConstant(unittest.TestCase):

    def test_probe_timeout_is_positive_int(self):
        assert isinstance(OPENGL_PROBE_TIMEOUT, int)
        assert OPENGL_PROBE_TIMEOUT > 0


class TestRunOpenglProbeNoOpenGL(unittest.TestCase):
    """When the OpenGL Python package is absent the probe must fail fast."""

    def test_missing_opengl_message(self):
        with patch("xpra.scripts.glprobe.find_spec", return_value=None):
            msg, props = run_opengl_probe()
        assert msg.startswith("error:"), f"unexpected message: {msg!r}"
        assert props.get("success") is False
        assert "error" in props

    def test_missing_opengl_no_subprocess(self):
        with patch("xpra.scripts.glprobe.find_spec", return_value=None), \
             patch("xpra.scripts.glprobe.Popen") as mock_popen:
            run_opengl_probe()
        mock_popen.assert_not_called()


class TestRunOpenglProbeParsing(unittest.TestCase):
    """Stdout output parsing: key=value pairs, type coercions."""

    def test_empty_stdout(self):
        msg, props = _run_probe_with(stdout="", returncode=0)
        assert isinstance(props, dict)

    def test_boolean_true_coercion(self):
        _, props = _run_probe_with(stdout="success=True\nsafe=True\n", returncode=0)
        assert props["success"] is True
        assert props["safe"] is True

    def test_boolean_false_coercion(self):
        _, props = _run_probe_with(stdout="success=False\n", returncode=0)
        assert props["success"] is False

    def test_size_coercion_to_int(self):
        _, props = _run_probe_with(stdout="texture-size=4096\n", returncode=0)
        assert props["texture-size"] == 4096
        assert isinstance(props["texture-size"], int)

    def test_dims_coercion_to_tuple(self):
        _, props = _run_probe_with(stdout="screen-dims=1920, 1080\n", returncode=0)
        assert props["screen-dims"] == (1920, 1080)

    def test_dims_invalid_stays_string(self):
        _, props = _run_probe_with(stdout="screen-dims=notanumber\n", returncode=0)
        # invalid dims: kept as string
        assert isinstance(props["screen-dims"], str)

    def test_size_invalid_stays_string(self):
        _, props = _run_probe_with(stdout="texture-size=big\n", returncode=0)
        assert isinstance(props["texture-size"], str)

    def test_plain_string_value(self):
        _, props = _run_probe_with(stdout="vendor=NVIDIA\n", returncode=0)
        assert props["vendor"] == "NVIDIA"

    def test_lines_without_equals_ignored(self):
        _, props = _run_probe_with(stdout="not-a-kv-pair\n", returncode=0)
        assert "not-a-kv-pair" not in props

    def test_value_with_equals_sign(self):
        # Only split on the first '='
        _, props = _run_probe_with(stdout="renderer=NVIDIA GeForce=GTX\n", returncode=0)
        assert props["renderer"] == "NVIDIA GeForce=GTX"


class TestRunOpenglProbeMessage(unittest.TestCase):
    """probe_message() classification of subprocess outcome."""

    def test_success(self):
        msg, _ = _run_probe_with(
            stdout="success=True\nsafe=True\n",
            returncode=0,
        )
        assert msg == "success", f"unexpected: {msg!r}"

    def test_warning_when_not_safe(self):
        msg, _ = _run_probe_with(
            stdout="success=True\nsafe=False\n",
            returncode=0,
        )
        assert msg.startswith("warning:"), f"unexpected: {msg!r}"

    def test_error_when_not_success(self):
        msg, _ = _run_probe_with(
            stdout="success=False\n",
            returncode=0,
        )
        assert msg.startswith("error:"), f"unexpected: {msg!r}"

    def test_error_field_takes_priority(self):
        msg, _ = _run_probe_with(
            stdout="error=driver blacklisted\nsuccess=True\nsafe=True\n",
            returncode=0,
        )
        assert msg == "error:driver blacklisted", f"unexpected: {msg!r}"

    def test_crash_on_returncode_1(self):
        msg, _ = _run_probe_with(stdout="", returncode=1)
        assert msg == "crash", f"unexpected: {msg!r}"

    def test_failed_on_nonzero_returncode(self):
        msg, _ = _run_probe_with(stdout="", returncode=2)
        assert msg.startswith("failed:"), f"unexpected: {msg!r}"

    def test_failed_on_signal_returncode(self):
        # Return code > 128 means killed by a signal
        msg, _ = _run_probe_with(stdout="", returncode=139)  # 128 + SIGSEGV(11)
        assert msg.startswith("failed:"), f"unexpected: {msg!r}"

    def test_timeout(self):
        msg, _ = _run_probe_with(timeout=True)
        assert msg == "timeout", f"unexpected: {msg!r}"

    def test_disabled(self):
        msg, _ = _run_probe_with(
            stdout="success=True\nsafe=True\nenable=False\nmessage=manually disabled\n",
            returncode=0,
        )
        assert msg.startswith("disabled:"), f"unexpected: {msg!r}"

    def test_popen_exception(self):
        with patch("xpra.scripts.glprobe.find_spec", return_value=object()), \
             patch("xpra.scripts.glprobe.Popen", side_effect=OSError("not found")), \
             patch("xpra.scripts.glprobe.get_exec_env", return_value={}), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]), \
             patch("xpra.net.subprocess_wrapper.exec_kwargs", return_value={}):
            msg, props = run_opengl_probe()
        assert msg == "failed", f"unexpected: {msg!r}"
        assert "message" in props


class TestRunGlprobeExitCodes(unittest.TestCase):
    """run_glprobe() maps do_run_glcheck() output to the correct ExitCode."""

    def _call(self, props):
        opts = MagicMock()
        with patch("xpra.scripts.glprobe.do_run_glcheck", return_value=props), \
             patch("xpra.scripts.glprobe.signal"):   # avoid touching real signal handlers
            return run_glprobe(opts, show=False)

    def test_ok(self):
        assert self._call({"success": True, "safe": True}) == ExitCode.OK

    def test_unsafe(self):
        assert self._call({"success": True, "safe": False}) == ExitCode.OPENGL_UNSAFE

    def test_failure_when_not_success(self):
        assert self._call({"success": False}) == ExitCode.FAILURE

    def test_failure_when_empty_props(self):
        assert self._call({}) == ExitCode.FAILURE


class TestDoRunGlcheck(unittest.TestCase):
    """do_run_glcheck() gracefully handles missing OpenGL support."""

    def test_returns_failure_dict_when_opengl_window_missing(self):
        opts = MagicMock()
        opts.opengl = "auto"
        with nomodule_context("xpra.opengl.window"), \
             patch("xpra.scripts.glprobe.use_tty", return_value=False):
            result = do_run_glcheck(opts)
        assert result.get("success") is False
        assert "message" in result

    def test_returns_dict(self):
        opts = MagicMock()
        opts.opengl = "no"
        with nomodule_context("xpra.opengl.window"), \
             patch("xpra.scripts.glprobe.use_tty", return_value=False):
            result = do_run_glcheck(opts)
        assert isinstance(result, dict)

    def test_logging_level_restored_on_exception(self):
        import logging
        original_level = logging.root.getEffectiveLevel()
        opts = MagicMock()
        opts.opengl = "auto"
        with nomodule_context("xpra.opengl.window"), \
             patch("xpra.scripts.glprobe.use_tty", return_value=False), \
             patch("xpra.scripts.glprobe.is_debug_enabled", return_value=False):
            do_run_glcheck(opts)
        assert logging.root.getEffectiveLevel() == original_level


def main():
    unittest.main()


if __name__ == "__main__":
    main()
