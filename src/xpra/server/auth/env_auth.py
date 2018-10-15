# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        self.var_name = kwargs.pop("name", "XPRA_PASSWORD")
        SysAuthenticator.__init__(self, username, **kwargs)
        self.authenticate = self.authenticate_hmac

    def __repr__(self):
        return "env"

    def get_password(self):
        return os.environ.get(self.var_name)
