# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
from typing import Any
from contextlib import redirect_stdout, redirect_stderr

from xpra.util.objects import typedict
from xpra.util.parsing import TRUE_OPTIONS
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("exec")


class ShellConnection(StubClientConnection):

    PREFIX = "shell"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget(ShellConnection.PREFIX, False)

    def __init__(self, *_args):
        super().__init__()
        self._server = None
        self.shell_enabled = False
        self.saved_logging_handler = None
        self.log_records = []
        self.log_thread = None

    def init_from(self, protocol, server) -> None:
        self._server = server
        try:
            options = protocol._conn.options
            shell = options.get("shell", "")
            self.shell_enabled = shell.lower() in TRUE_OPTIONS
        except AttributeError:
            options = {}
            self.shell_enabled = False
        log("init_from(%s, %s) shell_enabled(%s)=%s", protocol, server, options, self.shell_enabled)

    def get_caps(self) -> dict[str, Any]:
        return {ShellConnection.PREFIX: self.shell_enabled}

    def get_info(self) -> dict[str, Any]:
        return {ShellConnection.PREFIX: self.shell_enabled}

    def shell_exec(self, code: str) -> tuple[str, str]:
        stdout, stderr = self.do_shell_exec(code)
        log("shell_exec(%s) stdout=%r", code, stdout)
        log("shell_exec(%s) stderr=%r", code, stderr)
        if stdout is not None:
            self.send("shell-reply", 1, stdout)
        if stderr:
            self.send("shell-reply", 2, stderr)
        return stdout, stderr

    def do_shell_exec(self, code) -> tuple[str, str]:
        log("shell_exec(%r)", code)
        if not self.shell_enabled:
            return "shell support is not available with this connection", ""
        try:
            _globals = {
                "connection": self,
                "server": self._server,
                "log": log,
            }
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exec(code, _globals, {})  # pylint: disable=exec-used
            return stdout.getvalue(), stderr.getvalue()
        except Exception as e:
            log("shell_exec(..)", exc_info=True)
            log.error("Error running %r:", code)
            log.estr(e)
            return "", str(e)
