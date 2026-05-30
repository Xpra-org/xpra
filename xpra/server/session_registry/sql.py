# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.session_registry.sqlbase import SQLRegistry
from xpra.log import Logger

log = Logger("auth")


class Registry(SQLRegistry):
    NAME = "sql"
    DEFAULT_QUERY = ("SELECT uid, gid, displays, env_options, session_options "
                     "FROM users WHERE username=(%s)")

    def __init__(self, **options):
        super().__init__(**options)
        self.uri = options.get("uri", "")
        if not self.uri:
            raise ValueError("sql session registry: missing 'uri' option")

    def db_cursor(self, sql: str, *sqlargs):
        from sqlalchemy import create_engine  # pylint: disable=import-outside-toplevel
        db = create_engine(self.uri)
        cursor = db.cursor()
        cursor.execute(sql, sqlargs)
        cursor.db = db
        return cursor
