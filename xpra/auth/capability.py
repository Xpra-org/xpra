# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.util.objects import typedict


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log("capability.Authenticator(%s)", kwargs)
        self.uid = -1
        self.gid = -1
        self.property = kwargs.pop("property", "display")
        self.value = str(kwargs.pop("value", ""))
        # connection = kwargs.get("connection", None)
        super().__init__(**kwargs)

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def requires_challenge(self) -> bool:
        return False

    def authenticate(self, caps: typedict) -> bool:  # pylint: disable=arguments-differ
        value = caps.strget(self.property, "")
        log("capability.authenticate(..) %r=%r (value required: %r)",
            self.property, value, self.value)
        return value == self.value

    def __repr__(self):
        return "capability"
