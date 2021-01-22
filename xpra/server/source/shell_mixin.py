# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
from contextlib import redirect_stdout, redirect_stderr

from xpra.util import typedict
from xpra.scripts.config import TRUE_OPTIONS
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("exec")


class ShellMixin(StubSourceMixin):

    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        return caps.boolget("shell", False)

    def __init__(self, *_args):
        self._server = None
        self.shell_enabled = False
        self.saved_logging_handler = None
        self.log_records = []
        self.log_thread = None

    def init_from(self, protocol, server):
        self._server = server
        try:
            options = protocol._conn.options
            shell = options.get("shell", "")
            self.shell_enabled = shell.lower() in TRUE_OPTIONS
        except AttributeError:
            options = {}
            self.shell_enabled = False
        log("init_from(%s, %s) shell_enabled(%s)=%s", protocol, server, options, self.shell_enabled)

    def get_caps(self) -> dict:
        return {"shell" : self.shell_enabled}

    def get_info(self) -> dict:
        return {"shell" : self.shell_enabled}

    def shell_exec(self, code):
        stdout, stderr = self.do_shell_exec(code)
        log("shell_exec(%s) stdout=%r", code, stdout)
        log("shell_exec(%s) stderr=%r", code, stderr)
        if stdout is not None:
            self.send("shell-reply", 1, stdout)
        if stderr:
            self.send("shell-reply", 2, stderr)
        return stdout, stderr

    def do_shell_exec(self, code):
        log("shell_exec(%r)", code)
        try:
            assert self.shell_enabled, "shell support is not available with this connection"
            _globals = {
                "connection" : self,
                "server"    : self._server,
                "log"       : log,
                }
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout):
                with redirect_stderr(stderr):
                    exec(code, _globals, {})
            return stdout.getvalue().encode("utf8"), stderr.getvalue().encode("utf8")
        except Exception as e:
            log("shell_exec(..)", exc_info=True)
            log.error("Error running %r:", code)
            log.error(" %s", e)
            return None, str(e)
