# This file is part of Xpra.
# Copyright (C) 2016-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Callable

from xpra.os_util import bytestostr
from xpra.server.auth.sys_auth_base import SysAuthenticator


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        self.value : str = bytestostr(kwargs.pop("value", None))
        super().__init__(**kwargs)
        self.authenticate_check : Callable = self.authenticate_hmac

    def __repr__(self):
        return "password"

    def get_password(self) -> str:
        return self.value
