# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.auth.sys_auth_base import SysAuthenticator


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        self.var_name = kwargs.pop("name", "XPRA_PASSWORD")
        super().__init__(**kwargs)
        self.authenticate_check = self.authenticate_hmac

    def __repr__(self):
        return "env"

    def get_password(self) -> str:
        return os.environ.get(self.var_name, "")
