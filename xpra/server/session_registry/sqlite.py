# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.server.session_registry.sqlbase import SQLRegistry
from xpra.log import Logger

log = Logger("auth")


class Registry(SQLRegistry):
    NAME = "sqlite"
    DEFAULT_QUERY = ("SELECT uid, gid, displays, env_options, session_options "
                     "FROM users WHERE username=(?)")

    def __init__(self, **options):
        super().__init__(**options)
        filename = options.get("filename", "sqlite.sdb")
        if filename and not os.path.isabs(filename):
            cwd = options.get("exec_cwd") or os.getcwd()
            filename = os.path.join(cwd, filename)
        self.filename = filename

    def db_cursor(self, sql: str, *sqlargs):
        if not os.path.exists(self.filename):
            log.error(f"Error: sqlite session registry: database file {self.filename!r} not found")
            return None
        import sqlite3  # pylint: disable=import-outside-toplevel
        db = sqlite3.connect(self.filename)
        cursor = db.cursor()
        cursor.execute(sql, sqlargs)
        return cursor
