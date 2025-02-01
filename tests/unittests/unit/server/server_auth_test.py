#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import unittest
from time import sleep

from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait
from xpra.util.str_fn import strtobytes
from xpra.exit_codes import ExitCode
from unit.server_test_util import ServerTestUtil, estr, log


class ServerAuthTest(ServerTestUtil):

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        cls.xvfb = cls.start_Xvfb()
        cls.display = cls.xvfb.display

    @classmethod
    def tearDownClass(cls):
        cls.xvfb.terminate()
        ServerTestUtil.tearDownClass()

    def _test_auth(self, auth="fail", uri_prefix="", exit_code=0, password=None):
        display = self.xvfb.display
        log("starting test server on %s", display)
        server_args = ["--bind=noabstract", f"--auth={auth}", "--use-display=yes"]
        server = self.check_fast_start_server(display, *server_args)
        # we should always be able to get the version:
        display_uri = uri_prefix + display
        client = self.run_xpra(["version", display_uri])
        assert pollwait(client, 5) == 0, f"version client failed to connect using {display_uri}"
        if client.poll() is None:
            client.terminate()
        # try to connect
        cmd = ["info", display_uri]
        f = None
        try:
            if password:
                f = self._temp_file(strtobytes(password))
                filename = os.path.abspath(f.name)
                cmd += [f"--password-file={filename}"]
                cmd += [f"--challenge-handlers=file:filename={filename}"]
            client = self.run_xpra(cmd)
            r = pollwait(client, 5)
        finally:
            if f:
                f.close()
                self.delete_temp_file(f)

        exit_code_error = r != exit_code
        if exit_code_error:
            log.warn("Server Process Pipes:")
            log.warn(f" for server args={server_args}")
            self.show_proc_pipes(server)
            log.warn("Client Process Pipes:")
            log.warn(f" for client args={cmd}")
            self.show_proc_pipes(client)

        if client.poll() is None:
            client.terminate()

        try:
            server.terminate()
        finally:
            sleep(2)
            self.run_xpra(["clean-sockets"])
        if exit_code_error:
            raise RuntimeError(f"{auth!r} test error: expected info client to return {estr(exit_code)}"
                               f" but got {estr(r)}"
                               f" for server with args={shlex.join(server_args)}"
                               f" and client command: {shlex.join(cmd)}")

    def test_fail(self):
        self._test_auth("fail", "", ExitCode.CONNECTION_FAILED)

    def test_reject(self):
        self._test_auth("reject", "", ExitCode.PASSWORD_REQUIRED)

    def test_none(self):
        self._test_auth("none", "", ExitCode.OK)
        self._test_auth("none", "", ExitCode.OK, "foo")

    def test_allow(self):
        self._test_auth("allow", "", ExitCode.PASSWORD_REQUIRED)
        self._test_auth("allow", "", ExitCode.OK, "foo")

    def test_file(self):
        from xpra.os_util import get_hex_uuid
        password = get_hex_uuid()
        f = self._temp_file(strtobytes(password))
        filename = os.path.abspath(f.name)
        try:
            self._test_auth("file", "", ExitCode.PASSWORD_REQUIRED)
            self._test_auth(f"file:filename={filename}", "", ExitCode.PASSWORD_REQUIRED)
            self._test_auth(f"file:filename={filename}", "", ExitCode.OK, password)
            self._test_auth(f"file:filename={filename}", "", ExitCode.AUTHENTICATION_FAILED, password+"A")
        finally:
            f.close()

    def test_multifile(self):
        from xpra.platform.info import get_username
        username = get_username()
        from xpra.os_util import get_hex_uuid
        password = get_hex_uuid()
        displays = ""
        data = "%s|%s|%i|%i|%s||" % (username, password, os.getuid(), os.getgid(), displays)
        f = self._temp_file(strtobytes(data))
        filename = os.path.abspath(f.name)
        try:
            self._test_auth("multifile", "", ExitCode.PASSWORD_REQUIRED)
            self._test_auth(f"multifile:filename={filename}", "", ExitCode.PASSWORD_REQUIRED)
            self._test_auth(f"multifile:filename={filename}", "", ExitCode.OK, password)
            self._test_auth(f"multifile:filename={filename}", "", ExitCode.AUTHENTICATION_FAILED, password+"A")
        finally:
            f.close()


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
