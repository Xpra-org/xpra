# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Default session registry: delegate to `authenticator.get_sessions()`.

This preserves the historical behaviour: the authentication module is also
the source of truth for session lookup. Selecting this backend (or none at
all, since it is the default) means existing `multifile`/`sql*` deployments
work unchanged.
"""

from xpra.server.session_registry import Session, SessionRegistry
from xpra.log import Logger

log = Logger("auth")


class Registry(SessionRegistry):
    NAME = "auth"

    def lookup(self, authenticator, client_caps=None) -> Session | None:
        data = authenticator.get_sessions()
        log("%s.lookup(%s) authenticator.get_sessions()=%s", self, authenticator, data)
        return Session.from_tuple(data)
