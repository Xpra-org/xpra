# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.auth.sys_auth_base import SysAuthenticator


class Authenticator(SysAuthenticator):

    def __repr__(self):
        return "allow"

    def get_password(self) -> str:
        return None

    def authenticate(self, _challenge_response=None, _client_salt=None) -> bool:
        return True
