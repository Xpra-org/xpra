# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.util.objects import typedict


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log("http_header.Authenticator(%s)", kwargs)
        self.uid = -1
        self.gid = -1
        self.property = kwargs.pop("property", "X-Forwarded-Proto")
        self.value = str(kwargs.pop("value", "https"))
        connection = kwargs.get("connection", None)
        self.headers = getattr(connection, "options", {}).get("http-headers", {})
        log(f"http-headers({connection})={self.headers}")
        super().__init__(**kwargs)

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def requires_challenge(self) -> bool:
        return False

    def authenticate(self, caps: typedict) -> bool:  # pylint: disable=arguments-differ
        value = self.headers.get(self.property, "")
        log(f"{self.property!r}={value!r}, expected {self.value!r}")
        return value == self.value

    def __repr__(self):
        return "capability"
