# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from subprocess import Popen
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.util.str_fn import std, alnum, bytestostr
from xpra.util.env import envint, shellsub, first_time
from xpra.os_util import OSX, gi_import
from xpra.scripts.config import TRUE_OPTIONS
from xpra.util.child_reaper import getChildReaper
from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.platform.features import EXECUTABLE_EXTENSION

GLib = gi_import("GLib")

TIMEOUT = envint("XPRA_EXEC_AUTH_TIMEOUT", 600)


def get_default_auth_dialog() -> str:
    if os.name == "posix":
        auth_dialog = "/usr/libexec/xpra/auth_dialog"
    else:
        from xpra.platform.paths import get_app_dir  # pylint: disable=import-outside-toplevel
        auth_dialog = os.path.join(get_app_dir(), "auth_dialog")
    if EXECUTABLE_EXTENSION:
        # ie: add ".exe" on MS Windows
        auth_dialog += "." + EXECUTABLE_EXTENSION
    log(f"auth_dialog={auth_dialog!r}")
    if not os.path.exists(auth_dialog) and first_time("auth-dialog-not-found"):
        log.warn(f"Warning: authentication dialog command {auth_dialog!r} does not exist")
    return auth_dialog


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log(f"exec.Authenticator({kwargs})")
        self.command = shlex.split(kwargs.pop("command", "${auth_dialog} ${info} ${timeout}"))
        self.require_challenge = kwargs.pop("require-challenge", "no").lower() in TRUE_OPTIONS
        self.timeout = kwargs.pop("timeout", TIMEOUT)
        self.timer = 0
        self.proc = None
        self.timeout_event = False
        if not self.command:
            self.command = [get_default_auth_dialog(), ]
        connection = kwargs.get("connection")
        if not connection:
            raise ValueError("connection object is missing")
        log(f"exec connection info: {connection}")
        self.connection_str = str(connection)
        super().__init__(**kwargs)

    def requires_challenge(self) -> bool:
        return self.require_challenge

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        assert self.require_challenge
        if "xor" not in digests:
            log.error("Error: kerberos authentication requires the 'xor' digest")
            return b"", ""
        return super().get_challenge(("xor", ))

    def validate_caps(self, caps: typedict) -> bool:
        if not self.require_challenge:
            return True
        return super().validate_caps(caps)

    def default_authenticate_check(self, caps: typedict) -> bool:
        info = f"Connection request from {self.connection_str}"
        subs = {
            "auth_dialog": get_default_auth_dialog(),
            "info": info,
            "timeout": self.timeout,
            "username": alnum(self.username),
            "prompt": std(self.prompt),
        }
        if self.require_challenge:
            subs["password"] = bytestostr(self.unxor_response(caps))
        cmd = tuple(shellsub(v, subs) for v in self.command)
        log(f"authenticate(..) shellsub({self.command}={cmd}")
        # [self.command, info, str(self.timeout)]
        try:
            with Popen(cmd) as proc:
                self.proc = proc
                log(f"authenticate(..) Popen({cmd})={proc}")
                # if required, make sure we kill the command when it times out:
                if self.timeout > 0:
                    self.timer = GLib.timeout_add(self.timeout * 1000, self.command_timedout)
                    if not OSX:
                        # python on macos may set a 0 returncode when we use poll()
                        # so we cannot use the ChildReaper on macos,
                        # and we can't cancel the timer
                        getChildReaper().add_process(proc, "exec auth", cmd, True, True, self.command_ended)
        except OSError as e:
            log(f"error running {cmd!r}", exc_info=True)
            log.error("Error: cannot run exec authentication module command")
            log.error(f" {cmd!r}")
            log.estr(e)
            return False
        v = proc.returncode
        log(f"authenticate(..) returncode({cmd})={v}")
        if self.timeout_event:
            return False
        return v == 0

    def command_ended(self, *args) -> None:
        t = self.timer
        log(f"exec auth.command_ended{args} timer={t}")
        if t:
            self.timer = 0
            GLib.source_remove(t)

    def command_timedout(self) -> None:
        proc = self.proc
        log(f"exec auth.command_timedout() proc={proc}")
        self.timeout_event = True
        self.timer = 0
        if proc:
            try:
                proc.terminate()
            except Exception:
                log(f"error trying to terminate exec auth process {proc}", exc_info=True)

    def __repr__(self):
        return "exec"
