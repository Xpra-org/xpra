# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The `wsl://` transport: carries the regular xpra protocol over the stdio pipes of a `wsl.exe` process,
which runs `xpra _proxy` (or `_proxy_start`) in the selected distribution, as the selected Linux user.
No TCP listener, password or ssh server is involved.

    wsl://Ubuntu/100            distribution "Ubuntu", WSL's default user for it
    wsl://alice@Ubuntu/100      Linux user "alice"
    wsl:///100                  WSL's default distribution
"""

import os
import shlex
from collections import deque
from collections.abc import Callable, Sequence
from subprocess import PIPE, Popen, run, TimeoutExpired
from typing import Any
from urllib import parse

from xpra.common import noop
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode
from xpra.os_util import WIN32
from xpra.util.env import envint
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("network", "wsl")

WSL_COMMAND = os.environ.get("XPRA_WSL_COMMAND", "wsl.exe")
WSL_XPRA = os.environ.get("XPRA_WSL_XPRA", "xpra")
WSL_LIST_TIMEOUT = envint("XPRA_WSL_LIST_TIMEOUT", 30)
WSL_CHECK_TIMEOUT = envint("XPRA_WSL_CHECK_TIMEOUT", 60)
WSL_EXIT_TIMEOUT = envint("XPRA_WSL_EXIT_TIMEOUT", 5)
# how many lines of `stderr` we keep for error messages:
WSL_DIAGNOSTIC_LINES = envint("XPRA_WSL_DIAGNOSTIC_LINES", 20)
# how many lines of the server log we show when the server fails to start:
WSL_SERVER_LOG_LINES = envint("XPRA_WSL_SERVER_LOG_LINES", 10)

DEFAULT_DISPLAY = "100"
# exit code used by `check_command`:
COMMAND_NOT_FOUND = 3

INSTALL_INSTRUCTIONS = (
    "install Xpra in the WSL distribution using the automatic setup script:",
    " curl https://xpra.org/get-xpra.sh | bash",
    "the default Debian and Ubuntu repositories provide outdated or broken downstream packages that do not work with current Xpra clients.",
    "see https://github.com/Xpra-org/xpra/wiki/Distribution-Packages",
    "for manual repository setup, see https://xpra-org.github.io/xpra/Download/Linux.html",
)


def check_platform() -> None:
    if not WIN32:
        raise InitExit(ExitCode.UNSUPPORTED, "wsl connections are only supported on MS Windows")


def parse_wsl_netloc(netloc: str) -> tuple[str, str]:
    """
    Returns the Linux username and the distribution name from the location part of a `wsl://` URI,
    either may be empty to use WSL's configured default.
    We don't use `urlparse`'s `hostname` since it lowercases it, and distribution names are case-sensitive.
    """
    username = ""
    distribution = netloc
    if "@" in netloc:
        username, distribution = netloc.rsplit("@", 1)
        if ":" in username:
            raise ValueError("wsl connections do not use passwords")
        username = parse.unquote(username)
        if not username:
            raise ValueError("empty wsl username")
    if ":" in distribution:
        raise ValueError("wsl connections do not use ports")
    return username, parse.unquote(distribution)


def get_wsl_selector_args(distribution: str = "", username: str = "") -> list[str]:
    args = []
    if distribution:
        args += ["--distribution", distribution]
    if username:
        args += ["--user", username]
    return args


def get_wsl_command(display_desc: dict[str, Any]) -> list[str]:
    # ie: ["wsl.exe", "--distribution", "Ubuntu", "--exec", "xpra", "_proxy_start", "--start=xterm", ":100"]
    cmd = [WSL_COMMAND]
    cmd += get_wsl_selector_args(display_desc.get("distribution", ""), display_desc.get("username", ""))
    cmd += ["--exec", display_desc.get("remote_xpra_command", WSL_XPRA)]
    cmd += list(display_desc.get("proxy_command", ["_proxy"]))
    cmd += list(display_desc.get("display_as_args", ()))
    for x in cmd:
        if not isinstance(x, str):
            raise ValueError(f"argument is not a string: {x!r} ({type(x)}), found in command: {cmd}")
    return cmd


def wsl_target_string(distribution: str, username: str = "", display: str = "") -> str:
    target = "wsl://"
    if username:
        target += parse.quote(username, safe="") + "@"
    target += parse.quote(distribution, safe="")
    return target + "/" + display.lstrip(":")


def get_wsl_env() -> dict[str, str]:
    env = os.environ.copy()
    # without this, `wsl.exe` writes its own messages using UTF-16:
    env["WSL_UTF8"] = "1"
    return env


def get_popen_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"env": get_wsl_env()}
    if WIN32:
        from subprocess import CREATE_NO_WINDOW  # @UnresolvedImport
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return kwargs


def decode_wsl_output(data: bytes) -> str:
    # older versions of WSL ignore `WSL_UTF8` and use UTF-16, with or without a BOM:
    if data.startswith(b"\xff\xfe") or (len(data) >= 2 and b"\0" in data):
        return data.decode("utf-16-le", errors="replace").lstrip("\ufeff")
    return data.decode("utf8", errors="replace").lstrip("\ufeff")


def list_distributions(timeout: int = WSL_LIST_TIMEOUT) -> list[str]:
    """
    Returns the installed distributions, in the order that `wsl.exe --list --quiet` gives them.
    Raises `InitExit` if WSL cannot be used.
    This can take a while if WSL has to start, so the GUI must not call it from the UI thread.
    """
    check_platform()
    cmd = [WSL_COMMAND, "--list", "--quiet"]
    try:
        proc = run(cmd, stdin=PIPE, capture_output=True, timeout=timeout, **get_popen_kwargs())
    except OSError as e:
        raise InitExit(ExitCode.COMPONENT_MISSING, f"failed to run {WSL_COMMAND!r}, is WSL installed? {e}") from None
    except TimeoutExpired:
        raise InitExit(ExitCode.CONNECTION_FAILED, f"{WSL_COMMAND!r} did not list distributions within {timeout} seconds") from None
    out = decode_wsl_output(proc.stdout)
    if proc.returncode != 0:
        message = decode_wsl_output(proc.stderr).strip() or out.strip() or f"exit code {proc.returncode}"
        raise InitExit(ExitCode.COMPONENT_MISSING, f"failed to list WSL distributions: {message}")
    return [line.strip() for line in out.splitlines() if line.strip()]


def check_command(command: str, distribution: str = "", username: str = "", timeout: int = WSL_CHECK_TIMEOUT,
                  instructions: Sequence[str] = ()) -> str:
    """
    Verifies that `command` can be found in the distribution,
    returns an empty string if it can, or an error message.
    """
    check_platform()
    cmd = [WSL_COMMAND] + get_wsl_selector_args(distribution, username)
    # `command -v` exits with 1 or 127 depending on the shell,
    # and `wsl.exe` uses 1 for its own errors, so use a distinctive exit code:
    cmd += ["--exec", "sh", "-c", f"command -v {shlex.quote(command)} || exit {COMMAND_NOT_FOUND}"]
    target = distribution or "the default distribution"
    try:
        proc = run(cmd, stdin=PIPE, capture_output=True, timeout=timeout, **get_popen_kwargs())
    except OSError as e:
        return f"failed to run {WSL_COMMAND!r}, is WSL installed? {e}"
    except TimeoutExpired:
        return f"{target} did not respond within {timeout} seconds"
    log("check_command%s=%s", (command, distribution, username), proc)
    if proc.returncode == 0 and decode_wsl_output(proc.stdout).strip():
        return ""
    if proc.returncode == COMMAND_NOT_FOUND:
        return "\n".join((f"{command!r} was not found in {target}", ) + tuple(instructions))
    message = decode_wsl_output(proc.stderr).strip() or decode_wsl_output(proc.stdout).strip()
    return f"failed to run a command in {target}: {message or 'exit code %s' % proc.returncode}"


def check_xpra(distribution: str = "", username: str = "", timeout: int = WSL_CHECK_TIMEOUT) -> str:
    """
    Verifies that xpra can be found in the distribution,
    returns an empty string if it can, or an error message with installation instructions.
    """
    return check_command(WSL_XPRA, distribution, username, timeout, INSTALL_INSTRUCTIONS)


class WSLBridge:
    """
    Owns the `wsl.exe` process carrying the connection:
    drains its `stderr` so it can never block on a full pipe and keeps the last lines for diagnostics,
    and terminates and reaps it when the connection is closed.
    The xpra server itself is daemonized in the distribution, so it outlives the bridge.
    """

    def __init__(self, cmd: Sequence[str]):
        self.cmd = list(cmd)
        self.process: Popen | None = None
        self.diagnostics: deque[str] = deque(maxlen=WSL_DIAGNOSTIC_LINES)

    def start(self) -> Popen:
        log("starting wsl bridge: %s", shlex.join(self.cmd))
        try:
            # binary pipes, no console and no shell, so the data is not translated:
            self.process = Popen(self.cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, bufsize=0, **get_popen_kwargs())
        except OSError as e:
            raise InitExit(ExitCode.CONNECTION_FAILED,
                           f"failed to run {self.cmd[0]!r}, is WSL installed? {e}") from None
        start_thread(self.drain_stderr, "wsl-stderr-reader", daemon=True)
        return self.process

    def drain_stderr(self) -> None:
        stderr = self.process.stderr
        while True:
            try:
                line = stderr.readline()
            except (OSError, ValueError):
                log("drain_stderr()", exc_info=True)
                break
            if not line:
                break
            if s := decode_wsl_output(line.rstrip(b"\r\n")).rstrip():
                log("wsl: %s", s)
                self.diagnostics.append(s)

    def poll(self) -> int | None:
        return self.process.poll() if self.process else None

    def command_not_found(self) -> bool:
        # WSL's relay reports a missing command as: "execvpe(xpra) failed: No such file or directory"
        if "--exec" not in self.cmd:
            return False
        command = self.cmd[self.cmd.index("--exec") + 1]
        return any(f"execvpe({command}) failed" in line for line in self.diagnostics)

    def get_error_message(self, exit_code: int, had_connected: bool) -> str:
        if had_connected:
            message = f"the WSL bridge process has terminated with exit code {exit_code}"
        else:
            message = f"failed to start xpra in WSL (exit code {exit_code})"
        lines = [message] + list(self.diagnostics)
        if self.command_not_found() or (not had_connected and not self.diagnostics):
            lines += list(INSTALL_INSTRUCTIONS)
        return "\n".join(lines)

    def get_server_log_paths(self) -> list[str]:
        # once the server daemonizes, its errors only go to its log file, which is announced on stderr:
        # "Entering daemon mode; any further errors will be reported to:"
        # "  '/run/user/1000/xpra/105/server.log.new'"
        paths = []
        for line in self.diagnostics:
            path = line.strip().strip("'\"")
            if path.startswith("/") and ".log" in path:
                paths.append(path)
                if path.endswith(".new"):
                    # the file is renamed once the server has started:
                    paths.append(path[:-len(".new")])
        return paths

    def get_server_log(self, lines: int = WSL_SERVER_LOG_LINES) -> list[str]:
        paths = self.get_server_log_paths()
        if not paths or "--exec" not in self.cmd:
            return []
        script = f'for f in "$@"; do if [ -f "$f" ]; then tail -n {lines:d} "$f"; exit 0; fi; done'
        cmd = self.cmd[:self.cmd.index("--exec")] + ["--exec", "sh", "-c", script, "sh"] + paths
        try:
            proc = run(cmd, stdin=PIPE, capture_output=True, timeout=WSL_EXIT_TIMEOUT, **get_popen_kwargs())
        except (OSError, TimeoutExpired):
            log("get_server_log()", exc_info=True)
            return []
        return [line.rstrip() for line in decode_wsl_output(proc.stdout).splitlines() if line.strip()]

    def get_startup_failure_message(self) -> str:
        lines = ["the xpra server in WSL did not respond"] + list(self.diagnostics)
        if server_log := self.get_server_log():
            lines += ["server log:"] + server_log
        return "\n".join(lines)

    def stop(self) -> None:
        proc = self.process
        if not proc:
            return
        # terminate first: on MS Windows, closing a pipe blocks while another thread is reading from it,
        # and the process exiting is what makes that read return
        if proc.poll() is None:
            log("terminating wsl bridge %s", proc.pid)
            try:
                proc.terminate()
            except OSError:
                log("error terminating %s", proc, exc_info=True)
        start_thread(self.reap, "wsl-bridge-reaper", daemon=True)

    def reap(self) -> None:
        proc = self.process
        try:
            proc.wait(WSL_EXIT_TIMEOUT)
        except TimeoutExpired:
            log.warn(f"Warning: the WSL bridge process {proc.pid} did not exit, killing it")
            proc.kill()
            proc.wait()
        log("wsl bridge %s exited with %s", proc.pid, proc.returncode)


def connect_to(display_desc: dict[str, Any], debug_cb: Callable = noop, fail_cb: Callable = noop):
    check_platform()
    from xpra.net.bytestreams import TwoFileConnection, ConnectionClosedException
    distribution = display_desc.get("distribution", "")
    username = display_desc.get("username", "")
    display = display_desc.get("display", "")
    cmd = get_wsl_command(display_desc)
    debug_cb("starting WSL bridge")
    bridge = WSLBridge(cmd)
    child = bridge.start()
    target = wsl_target_string(distribution, username, display)

    def report(message: str) -> None:
        # only report the first error:
        if "wsl_abort" in display_desc:
            return
        display_desc["wsl_abort"] = True
        debug_cb(message)
        fail_cb(message)
        for i, line in enumerate(message.splitlines()):
            log.error(("Error: " if i == 0 else " ") + line)
        log.error(f" for {target}")
        log.error(" the command line used was:")
        log.error(" " + shlex.join(cmd))

    def abort_test(action: str) -> None:
        exit_code = child.poll()
        if exit_code is None:
            return
        had_connected = conn.input_bytecount > 0 or conn.output_bytecount > 0
        report(bridge.get_error_message(exit_code, had_connected))
        raise ConnectionClosedException(f"cannot {action} using WSL")

    def close() -> None:
        # ie: `_proxy_start` keeps waiting for a server which failed to start after daemonizing,
        # so we give up on it without ever hearing from it, and its errors are in the server log:
        if not conn.input_bytecount and "wsl_abort" not in display_desc:
            report(bridge.get_startup_failure_message())
        bridge.stop()

    info = {
        "distribution": distribution or "default",
        "username": username or "default",
        "command": cmd,
    }
    conn = TwoFileConnection(child.stdin, child.stdout, abort_test, target=target,
                             socktype="wsl", close_cb=close, info=info)
    conn.endpoint = target
    # failures of the child process are detected by `abort_test`,
    # and `connection_delay` bounds the startup, which may include booting the distribution:
    conn.timeout = 0
    if timeout := display_desc.get("timeout"):
        conn.connection_delay = int(timeout)
    conn.process = (child, "wsl", cmd)
    conn.bridge = bridge
    return conn
