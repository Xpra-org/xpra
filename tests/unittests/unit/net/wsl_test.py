#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

from xpra.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.net import wsl
from xpra.os_util import WIN32

# stands in for `wsl.exe ... --exec xpra _proxy`: copies stdin to stdout, byte for byte
ECHO = [sys.executable, "-c", (
    "import sys\n"
    "i, o = sys.stdin.buffer, sys.stdout.buffer\n"
    "while (b := i.read1(65536)):\n"
    "    o.write(b); o.flush()\n"
)]
FAIL = [sys.executable, "-c", (
    "import sys\n"
    "sys.stderr.write('xpra: command not found\\n'); sys.stderr.flush()\n"
    "sys.exit(127)\n"
)]


def make_opts():
    from xpra.scripts.parsing import make_defaults_struct
    return make_defaults_struct()


def parse(uri: str) -> dict:
    from xpra.scripts.parsing import parse_display_name
    with patch.object(wsl, "WIN32", True):
        return parse_display_name(make_opts(), uri)


class TestParseURI(unittest.TestCase):

    def test_netloc(self):
        for netloc, expected in {
            "": ("", ""),
            "Ubuntu": ("", "Ubuntu"),
            "alice@Ubuntu": ("alice", "Ubuntu"),
            "Ubuntu-24.04": ("", "Ubuntu-24.04"),
            "My%20Distro": ("", "My Distro"),
            "j%40doe@Debian": ("j@doe", "Debian"),
        }.items():
            self.assertEqual(wsl.parse_wsl_netloc(netloc), expected, f"for {netloc!r}")

    def test_rejected(self):
        for netloc in ("alice:secret@Ubuntu", ":secret@Ubuntu", "Ubuntu:22", "@Ubuntu"):
            with self.assertRaises(ValueError, msg=f"{netloc!r} should be rejected"):
                wsl.parse_wsl_netloc(netloc)

    def test_display_name(self):
        desc = parse("wsl://Ubuntu/100")
        self.assertEqual(desc["type"], "wsl")
        self.assertEqual(desc["distribution"], "Ubuntu")
        self.assertNotIn("username", desc)
        self.assertNotIn("password", desc)
        self.assertEqual(desc["display"], "100")
        self.assertEqual(desc["display_as_args"], ["100"])
        self.assertEqual(desc["proxy_command"], ["_proxy"])

    def test_case_and_encoding_preserved(self):
        desc = parse("wsl://alice@Ubuntu%2024.04/100")
        self.assertEqual(desc["distribution"], "Ubuntu 24.04")
        self.assertEqual(desc["username"], "alice")
        desc = parse("wsl://openSUSE-Tumbleweed/")
        self.assertEqual(desc["distribution"], "openSUSE-Tumbleweed")
        self.assertEqual(desc["display_as_args"], [])

    def test_default_distribution(self):
        desc = parse("wsl:///100")
        self.assertEqual(desc["distribution"], "")
        self.assertEqual(desc["display"], "100")

    def test_password_and_port_rejected(self):
        for uri in ("wsl://alice:secret@Ubuntu/100", "wsl://Ubuntu:22/100"):
            with self.assertRaises(ValueError):
                parse(uri)

    def test_unsupported_platform(self):
        from xpra.scripts.parsing import parse_display_name
        with patch.object(wsl, "WIN32", False):
            with self.assertRaises(InitExit) as cm:
                parse_display_name(make_opts(), "wsl://Ubuntu/100")
        self.assertEqual(cm.exception.status, ExitCode.UNSUPPORTED)
        with patch.object(wsl, "WIN32", False):
            with self.assertRaises(InitExit):
                wsl.list_distributions()
            with self.assertRaises(InitExit):
                wsl.connect_to({"type": "wsl"})

    def test_uri_roundtrip(self):
        from xpra.net.connect import display_desc_to_uri
        for uri in ("wsl://Ubuntu/100", "wsl://alice@Ubuntu/100", "wsl:///100", "wsl://alice@/100", "wsl://My%20Distro/7"):
            self.assertEqual(display_desc_to_uri(parse(uri)), uri)
        # reconnecting to a display which was only discovered after starting:
        desc = parse("wsl://Ubuntu/")
        desc["display"] = ":12"
        self.assertEqual(display_desc_to_uri(desc), "wsl://Ubuntu/12")


class TestCommand(unittest.TestCase):

    def test_defaults_omitted(self):
        cmd = wsl.get_wsl_command({"proxy_command": ["_proxy"], "display_as_args": ["100"]})
        self.assertEqual(cmd, [wsl.WSL_COMMAND, "--exec", "xpra", "_proxy", "100"])

    def test_selectors(self):
        cmd = wsl.get_wsl_command(parse("wsl://alice@Ubuntu%2024.04/100"))
        self.assertEqual(cmd, [wsl.WSL_COMMAND, "--distribution", "Ubuntu 24.04", "--user", "alice",
                               "--exec", "xpra", "_proxy", "100"])

    def test_start(self):
        desc = parse("wsl://Ubuntu/100")
        desc["proxy_command"] = ["_proxy_start"]
        desc["display_as_args"] = [":100", "--start=xterm -fa 'Mono'"]
        cmd = wsl.get_wsl_command(desc)
        # no shell is involved, so the arguments are passed as they are:
        self.assertEqual(cmd[-3:], ["_proxy_start", ":100", "--start=xterm -fa 'Mono'"])

    def test_invalid_argument(self):
        with self.assertRaises(ValueError):
            wsl.get_wsl_command({"display_as_args": [100]})


@unittest.skipUnless(WIN32, "WSL commands are only available on MS Windows")
class TestWSLCommands(unittest.TestCase):

    def test_decode(self):
        self.assertEqual(wsl.decode_wsl_output("Ubuntu\r\nDebian\r\n".encode("utf-16-le")), "Ubuntu\r\nDebian\r\n")
        self.assertEqual(wsl.decode_wsl_output(b"\xff\xfe" + "Ubuntu".encode("utf-16-le")), "Ubuntu")
        self.assertEqual(wsl.decode_wsl_output("Ubuntu\n".encode("utf8")), "Ubuntu\n")

    def run_patched(self, fn, result=None, side_effect=None):
        with patch.object(wsl, "WIN32", True), patch.object(wsl, "run", return_value=result, side_effect=side_effect) as run:
            return fn(), run

    def test_list_distributions(self):
        out = "Ubuntu\r\n\r\nDebian\r\n".encode("utf-16-le")
        distros, run = self.run_patched(wsl.list_distributions, CompletedProcess([], 0, out, b""))
        self.assertEqual(distros, ["Ubuntu", "Debian"])
        self.assertEqual(run.call_args[0][0], [wsl.WSL_COMMAND, "--list", "--quiet"])
        self.assertEqual(run.call_args[1]["env"]["WSL_UTF8"], "1")

    def test_list_failures(self):
        for kwargs in (
            {"result": CompletedProcess([], 1, b"", "no distributions installed".encode("utf-16-le"))},
            {"side_effect": FileNotFoundError("wsl.exe")},
            {"side_effect": TimeoutExpired("wsl.exe", 1)},
        ):
            with self.assertRaises(InitExit):
                self.run_patched(wsl.list_distributions, **kwargs)

    def test_check_xpra(self):
        found = CompletedProcess([], 0, b"/usr/bin/xpra\n", b"")
        msg, run = self.run_patched(lambda: wsl.check_xpra("Ubuntu", "alice"), found)
        self.assertEqual(msg, "")
        self.assertEqual(run.call_args[0][0][:5], [wsl.WSL_COMMAND, "--distribution", "Ubuntu", "--user", "alice"])
        missing = CompletedProcess([], wsl.COMMAND_NOT_FOUND, b"", b"")
        msg, _ = self.run_patched(lambda: wsl.check_xpra("Ubuntu"), missing)
        self.assertIn("'xpra' was not found in Ubuntu", msg)
        self.assertIn("curl https://xpra.org/get-xpra.sh | bash", msg)
        broken = CompletedProcess([], 1, b"", b"There is no distribution with the supplied name.")
        msg, _ = self.run_patched(lambda: wsl.check_xpra("Nope"), broken)
        self.assertIn("no distribution", msg)
        msg, _ = self.run_patched(wsl.check_xpra, side_effect=FileNotFoundError("wsl.exe"))
        self.assertIn("is WSL installed", msg)

    def test_check_command(self):
        missing = CompletedProcess([], wsl.COMMAND_NOT_FOUND, b"", b"")
        msg, run = self.run_patched(lambda: wsl.check_command("my app", "Ubuntu"), missing)
        self.assertEqual(msg, "'my app' was not found in Ubuntu")
        # the command name is quoted for the shell:
        self.assertIn("command -v 'my app'", run.call_args[0][0][-1])


class TestKeepalive(unittest.TestCase):

    def test_command(self):
        cmd = wsl.get_keepalive_command("Ubuntu", "alice", interval=3)
        self.assertEqual(cmd[:7], [wsl.WSL_COMMAND, "--distribution", "Ubuntu", "--user", "alice", "--exec", "sh"])
        self.assertEqual(cmd[7:], ["-c", wsl.KEEPALIVE_SCRIPT, "sh", "3"])
        self.assertEqual(wsl.get_keepalive_command()[:3], [wsl.WSL_COMMAND, "--exec", "sh"])
        self.assertEqual(wsl.get_keepalive_command(interval=0)[-1], "1")

    def test_enabled(self):
        self.assertTrue(wsl.is_keepalive_enabled({}))
        for value in ("no", "off", "0", "false"):
            self.assertFalse(wsl.is_keepalive_enabled({"keepalive": value}))
        self.assertTrue(wsl.is_keepalive_enabled({"keepalive": "yes"}))
        with patch.object(wsl, "WSL_KEEPALIVE", False):
            self.assertFalse(wsl.is_keepalive_enabled({}))
            self.assertTrue(wsl.is_keepalive_enabled({"keepalive": "yes"}))

    @unittest.skipUnless(sys.platform == "win32", "process creation flags are specific to MS Windows")
    def test_start_without_breakaway(self):
        import subprocess
        started = []

        def popen(cmd, **kwargs):
            flags = kwargs["creationflags"]
            if flags & subprocess.CREATE_BREAKAWAY_FROM_JOB:
                raise PermissionError("access denied")
            started.append(flags)
            return type("FakeProcess", (), {"pid": 1})()
        with patch.object(wsl, "Popen", side_effect=popen):
            self.assertIsNotNone(wsl.start_keepalive("Ubuntu"))
        self.assertEqual(len(started), 1)
        self.assertTrue(started[0] & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(started[0] & subprocess.CREATE_NEW_PROCESS_GROUP)
        with patch.object(wsl, "Popen", side_effect=OSError("no wsl")):
            self.assertIsNone(wsl.start_keepalive("Ubuntu"))


@unittest.skipUnless(os.path.exists("/proc/self/cmdline") and shutil.which("sh"),
                     "the keepalive script runs in a Linux distribution")
class TestKeepaliveScript(unittest.TestCase):

    def setUp(self):
        self.runtime_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.runtime_dir, True)
        os.mkdir(os.path.join(self.runtime_dir, "xpra"))
        self.processes = []
        self.addCleanup(self.kill_all)

    def kill_all(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def spawn(self, cmd, **kwargs):
        proc = subprocess.Popen(cmd, **kwargs)
        self.processes.append(proc)
        return proc

    def fake_server(self, display: str, cmdline_marker="xpra"):
        # a long-running process with `xpra` on its command line, and its `server.pid`:
        proc = self.spawn([sys.executable, "-c", "import time; time.sleep(60)", cmdline_marker])
        session_dir = os.path.join(self.runtime_dir, "xpra", display)
        os.makedirs(session_dir, exist_ok=True)
        with open(os.path.join(session_dir, "server.pid"), "w") as f:
            f.write(f"{proc.pid}\n")
        return proc

    def keepalive(self):
        env = dict(os.environ, XDG_RUNTIME_DIR=self.runtime_dir)
        return self.spawn(["sh", "-c", wsl.KEEPALIVE_SCRIPT, "sh", "1"], env=env)

    def assert_running(self, proc, duration=1.5):
        with self.assertRaises(subprocess.TimeoutExpired):
            proc.wait(duration)

    def test_no_servers(self):
        self.assertEqual(self.keepalive().wait(5), 0)
        # a pid file left behind by a server which is gone, or reused by another process:
        self.fake_server("100", cmdline_marker="other").kill()
        self.fake_server("101", cmdline_marker="other")
        self.assertEqual(self.keepalive().wait(5), 0)

    def test_lifetime(self):
        first = self.fake_server("100")
        second = self.fake_server("101")
        keepalive = self.keepalive()
        self.assert_running(keepalive)
        first.kill()
        first.wait()
        # still one session left:
        self.assert_running(keepalive)
        second.kill()
        second.wait()
        self.assertEqual(keepalive.wait(5), 0)

    @unittest.skipUnless(shutil.which("flock"), "flock is not installed")
    def test_single_instance(self):
        self.fake_server("100")
        keepalive = self.keepalive()
        self.assert_running(keepalive, 0.5)
        # a second instance gives up once the lock wait expires:
        self.assertEqual(self.keepalive().wait(10), 0)
        self.assertIsNone(keepalive.poll())


@unittest.skipUnless(WIN32, "the WSL bridge is only available on MS Windows")
class TestBridge(unittest.TestCase):

    def setUp(self):
        # never leave a real `wsl.exe` running after the tests:
        patcher = patch.object(wsl, "start_keepalive")
        self.start_keepalive = patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self, cmd, **kwargs):
        desc = {"type": "wsl", "distribution": "Ubuntu", "display": "100"}
        desc.update(kwargs.pop("desc", {}))
        with patch.object(wsl, "WIN32", True), patch.object(wsl, "get_wsl_command", return_value=cmd):
            return wsl.connect_to(desc, **kwargs)

    def close_and_wait(self, conn) -> None:
        proc = conn.bridge.process
        conn.close()
        proc.wait(wsl.WSL_EXIT_TIMEOUT + 5)

    def test_keepalive_after_connection(self):
        conn = self.connect(ECHO)
        self.assertEqual(self.roundtrip(conn, b"hello"), b"hello")
        self.close_and_wait(conn)
        self.start_keepalive.assert_called_once_with("Ubuntu", "")

    def test_no_keepalive_without_server(self):
        # the server never responded, so there is nothing to keep alive:
        conn = self.connect(ECHO, fail_cb=lambda msg: None)
        self.close_and_wait(conn)
        self.start_keepalive.assert_not_called()

    def test_keepalive_disabled(self):
        conn = self.connect(ECHO, desc={"keepalive": "no"})
        self.assertEqual(self.roundtrip(conn, b"hello"), b"hello")
        self.close_and_wait(conn)
        self.start_keepalive.assert_not_called()
        with patch.object(wsl, "WSL_KEEPALIVE", False):
            conn = self.connect(ECHO)
            self.assertEqual(self.roundtrip(conn, b"hello"), b"hello")
            self.close_and_wait(conn)
        self.start_keepalive.assert_not_called()

    def roundtrip(self, conn, data: bytes) -> bytes:
        from threading import Thread
        writer = Thread(target=self.write_all, args=(conn, data), daemon=True)
        writer.start()
        received = b""
        while len(received) < len(data):
            chunk = conn.read(65536)
            if not chunk:
                break
            received += chunk
        writer.join(10)
        return received

    @staticmethod
    def write_all(conn, data: bytes) -> None:
        view = memoryview(data)
        while view:
            view = view[conn.write(view):]

    def test_binary_integrity(self):
        conn = self.connect(ECHO)
        try:
            self.assertEqual(conn.socktype, "wsl")
            self.assertEqual(conn.target, "wsl://Ubuntu/100")
            for data in (
                b"\0" * 1024,
                b"\r\n\n\r\r\n\x1a\x03\x04\0",
                bytes(range(256)) * 16,
                # large payload, more than any pipe buffer:
                bytes(range(256)) * 32 * 1024,
            ):
                self.assertEqual(self.roundtrip(conn, data), data)
        finally:
            conn.close()

    def test_close_reaps(self):
        conn = self.connect(ECHO)
        proc = conn.bridge.process
        self.assertIsNone(proc.poll())
        conn.close()
        deadline = time.monotonic() + wsl.WSL_EXIT_TIMEOUT + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIsNotNone(proc.poll(), "bridge process should have been terminated")

    def test_process_failure(self):
        from xpra.net.bytestreams import ConnectionClosedException
        failures = []
        conn = self.connect(FAIL, fail_cb=failures.append)
        try:
            conn.bridge.process.wait(10)
            # let the stderr reader catch up:
            deadline = time.monotonic() + 5
            while not conn.bridge.diagnostics and time.monotonic() < deadline:
                time.sleep(0.1)
            with self.assertRaises(ConnectionClosedException):
                conn.read(1)
            # only reported once:
            with self.assertRaises(ConnectionClosedException):
                conn.write(b"x")
        finally:
            conn.close()
        self.assertEqual(len(failures), 1)
        self.assertIn("exit code 127", failures[0])
        self.assertIn("xpra: command not found", failures[0])

    def test_xpra_missing_message(self):
        bridge = wsl.WSLBridge([wsl.WSL_COMMAND, "--distribution", "Ubuntu", "--exec", "xpra", "_proxy", "100"])
        bridge.diagnostics.append("<3>WSL (865 - Relay) ERROR: CreateProcessCommon:875: execvpe(xpra) failed: No such file or directory")
        message = bridge.get_error_message(1, False)
        self.assertIn("execvpe(xpra) failed", message)
        self.assertIn("curl https://xpra.org/get-xpra.sh | bash", message)
        # other failures are shown as they are, without installation instructions:
        bridge.diagnostics.clear()
        bridge.diagnostics.append("Error: no such display :100")
        message = bridge.get_error_message(1, False)
        self.assertIn("no such display", message)
        self.assertNotIn("curl https://xpra.org/get-xpra.sh | bash", message)

    def test_server_log_paths(self):
        bridge = wsl.WSLBridge([wsl.WSL_COMMAND, "--distribution", "Ubuntu", "--exec", "xpra", "_proxy_start", ":105"])
        self.assertEqual(bridge.get_server_log_paths(), [])
        bridge.diagnostics.append("Entering daemon mode; any further errors will be reported to:")
        bridge.diagnostics.append("  '/run/user/1000/xpra/105/server.log.new'")
        self.assertEqual(bridge.get_server_log_paths(),
                         ["/run/user/1000/xpra/105/server.log.new", "/run/user/1000/xpra/105/server.log"])
        log_output = CompletedProcess([], 0, b"xpra initialization error:\ninvalid port number: 1\n", b"")
        with patch.object(wsl, "run", return_value=log_output) as run:
            message = bridge.get_startup_failure_message()
        # the log is read from the same distribution, as the same user:
        self.assertEqual(run.call_args[0][0][:4], [wsl.WSL_COMMAND, "--distribution", "Ubuntu", "--exec"])
        self.assertIn("did not respond", message)
        self.assertIn("invalid port number: 1", message)

    def test_missing_wsl(self):
        with self.assertRaises(InitExit) as cm:
            self.connect(["this-command-does-not-exist-xpra-wsl.exe"])
        self.assertIn("is WSL installed", str(cm.exception))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
