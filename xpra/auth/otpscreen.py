# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import string
import random
from time import monotonic
from subprocess import Popen
from collections.abc import Sequence, Callable

from xpra.auth.common import get_exec_env
from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.platform.paths import get_nodock_command
from xpra.util.objects import typedict


def gen_secret(mode: str, count: int) -> str:
    if mode in ("digits", "numeric"):
        options = string.digits
    elif mode in ("alpha", "chars", "characters"):
        options = string.ascii_uppercase
    elif mode == "alphanumeric":
        options = string.ascii_uppercase + string.digits
    else:
        raise RuntimeError(f"unsupported mode {mode!r}")
    return "".join(random.choice(options) for _ in range(count))


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log("otpscreen.Authenticator(%s)", kwargs)
        self.mode = kwargs.pop("mode", "digits")
        self.count = int(kwargs.pop("count", 6))
        self.timeout = int(kwargs.pop("timeout", 120))
        self.display = kwargs.pop("display", "auto")
        super().__init__(**kwargs)
        self.uid = -1
        self.gid = -1
        self.secret = ""
        self.valid_until = 0.0
        self.authenticate_check: Callable = self.authenticate_hmac
        self.otp_dialog = None

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def requires_challenge(self) -> bool:
        return True

    def get_password(self) -> str:
        return self.secret

    def authenticate_otp(self, caps: typedict) -> bool:
        self.stop_otp_dialog()
        return self.authenticate_hmac(caps)

    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:
        if self.salt is not None:
            log.error("Error: authentication challenge already sent!")
            return b"", ""
        self.secret = gen_secret(self.mode, self.count)
        log(f"secret is {self.secret!r}")
        self.valid_until = monotonic() + self.timeout
        cmd = get_nodock_command() + ["otp", self.secret, str(self.timeout)]
        env = get_exec_env(self.display)
        log("otp dialog: Popen(%s, %s)", cmd, env)
        self.otp_dialog = Popen(cmd, env=env)
        from xpra.util.child_reaper import get_child_reaper
        get_child_reaper().add_process(self.otp_dialog, "otp-dialog", cmd, ignore=True, forget=True)
        return super().do_get_challenge(digests)

    def cleanup(self):
        self.stop_otp_dialog()

    def stop_otp_dialog(self) -> None:
        proc = self.otp_dialog
        log("stop_otp_dialog() otp_dialog=%s", proc)
        if proc and proc.poll() is None:
            proc.terminate()

    def __repr__(self):
        return "otpscreen"
