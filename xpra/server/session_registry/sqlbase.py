# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Common SQL session registry: reads the same `users` table schema as
`xpra.auth.sqlauthbase`:

    uid VARCHAR, gid VARCHAR, displays VARCHAR,
    env_options VARCHAR, session_options VARCHAR

Subclasses provide the `db_cursor()` connection. Lookup is by username only;
the password column is not consulted — authentication happens separately.
"""

from xpra.util.parsing import parse_str_dict
from xpra.auth.common import parse_uid, parse_gid
from xpra.server.session_registry import Session, SessionRegistry
from xpra.log import Logger

log = Logger("auth")


class SQLRegistry(SessionRegistry):

    DEFAULT_QUERY = ("SELECT uid, gid, displays, env_options, session_options "
                     "FROM users WHERE username=(?)")

    def __init__(self, **options):
        super().__init__(**options)
        self.sessions_query: str = options.get("sessions_query", self.DEFAULT_QUERY)

    def db_cursor(self, sql: str, *sqlargs):  # pragma: no cover
        raise NotImplementedError

    def parse_row(self, data) -> Session | None:
        try:
            uid = parse_uid(data[0])
            gid = parse_gid(data[1])
            displays: list[str] = []
            env_options: dict[str, str] = {}
            session_options: dict[str, str] = {}
            if len(data) > 2 and data[2]:
                displays = [x.strip() for x in str(data[2]).split(",") if x.strip()]
            if len(data) > 3 and data[3]:
                env_options = parse_str_dict(str(data[3]), ";")
            if len(data) > 4 and data[4]:
                session_options = parse_str_dict(str(data[4]), ";")
        except Exception as e:
            log("parse_row(%s)", data, exc_info=True)
            log.error(f"Error: SQL session registry row parsing problem: {e}")
            return None
        return Session(uid=uid, gid=gid, displays=displays,
                       env_options=env_options, session_options=session_options)

    def lookup(self, authenticator) -> Session | None:
        username = getattr(authenticator, "username", "")
        if not username:
            return None
        cursor = self.db_cursor(self.sessions_query, username)
        if cursor is None:
            return None
        data = cursor.fetchone()
        log("%s.lookup(%s) row=%s", self, username, data)
        if not data:
            return None
        return self.parse_row(data)
