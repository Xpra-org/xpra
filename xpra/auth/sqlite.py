#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util.parsing import parse_str_dict
from xpra.auth.common import SessionData, parse_uid, parse_gid
from xpra.auth.sys_auth_base import log
from xpra.auth.sqlauthbase import SQLAuthenticator, DatabaseUtilBase, run_dbutil


class Authenticator(SQLAuthenticator):

    def __init__(self, filename="sqlite.sdb", **kwargs):
        super().__init__(**kwargs)
        if filename and not os.path.isabs(filename):
            exec_cwd = kwargs.get("exec_cwd", os.getcwd())
            filename = os.path.join(exec_cwd, filename)
        self.filename = filename
        self.password_query = kwargs.pop("password_query", "SELECT password FROM users WHERE username=(?)")
        self.sessions_query = kwargs.pop("sessions_query",
                                         "SELECT uid, gid, displays, env_options, session_options "
                                         "FROM users WHERE username=(?) AND password=(?)")
        self.authenticate_check = self.authenticate_hmac

    def __repr__(self):
        return "sqlite"

    def db_cursor(self, sql: str, *sqlargs):
        if not os.path.exists(self.filename):
            log.error("Error: sqlauth cannot find the database file '%s'", self.filename)
            return None
        import sqlite3  # pylint: disable=import-outside-toplevel
        db = sqlite3.connect(self.filename)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute(sql, sqlargs)
        log("db_cursor(%s)=%s", sqlargs, cursor)
        return cursor

    def parse_session_data(self, data) -> SessionData | None:
        try:
            uid = parse_uid(data["uid"])
            gid = parse_gid(data["gid"])
            displays: list[str] = []
            env_options: dict[str, str] = {}
            session_options: dict[str, str] = {}
            if data["displays"]:
                displays = [x.strip() for x in str(data["displays"]).split(",") if x.strip()]
            if data["env_options"]:
                env_options = parse_str_dict(str(data["env_options"]), ";")
            if data["session_options"]:
                session_options = parse_str_dict(str(data["session_options"]), ";")
        except Exception as e:
            log("get_sessions() error on row %s", data, exc_info=True)
            log.error("Error: sqlauth database row parsing problem:")
            log.estr(e)
            return None
        return uid, gid, displays, env_options, session_options


class SqliteDatabaseUtil(DatabaseUtilBase):

    def __init__(self, uri):
        super().__init__(uri)
        import sqlite3  # pylint: disable=import-outside-toplevel
        assert sqlite3.paramstyle == "qmark"
        self.param = "?"

    def exec_database_sql_script(self, cursor_cb, sql: str, *sqlargs):
        import sqlite3  # pylint: disable=import-outside-toplevel
        db = sqlite3.connect(self.uri)
        cursor = db.cursor()
        log("%s.execute%s", cursor, (sql, sqlargs))
        cursor.execute(sql, *sqlargs)
        if cursor_cb:
            cursor_cb(cursor)
        db.commit()
        return cursor

    def get_authenticator_class(self) -> type:
        return Authenticator


def main(argv) -> int:
    return run_dbutil(SqliteDatabaseUtil, "filename", argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
