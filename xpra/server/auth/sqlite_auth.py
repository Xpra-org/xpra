#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util import parse_simple_dict
from xpra.server.auth.sys_auth_base import init, log, parse_uid, parse_gid
from xpra.server.auth.sqlauthbase import SQLAuthenticator, DatabaseUtilBase, run_dbutil
assert init and log #tests will disable logging from here


class Authenticator(SQLAuthenticator):

    def __init__(self, username, filename="sqlite.sdb", **kwargs):
        SQLAuthenticator.__init__(self, username, **kwargs)
        if filename and not os.path.isabs(filename):
            exec_cwd = kwargs.get("exec_cwd", os.getcwd())
            filename = os.path.join(exec_cwd, filename)
        self.filename = filename
        self.password_query = kwargs.pop("password_query", "SELECT password FROM users WHERE username=(?)")
        self.sessions_query = kwargs.pop("sessions_query",
                                         "SELECT uid, gid, displays, env_options, session_options "+
                                         "FROM users WHERE username=(?) AND password=(?)")
        self.authenticate = self.authenticate_hmac

    def __repr__(self):
        return "sqlite"

    def db_cursor(self, *sqlargs):
        if not os.path.exists(self.filename):
            log.error("Error: sqlauth cannot find the database file '%s'", self.filename)
            return None
        import sqlite3
        db = sqlite3.connect(self.filename)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute(*sqlargs)
        log("db_cursor(%s)=%s", sqlargs, cursor)
        return cursor

    def parse_session_data(self, data):
        try:
            uid = parse_uid(data["uid"])
            gid = parse_gid(data["gid"])
            displays = []
            env_options = {}
            session_options = {}
            if data["displays"]:
                displays = [x.strip() for x in str(data["displays"]).split(",")]
            if data["env_options"]:
                env_options = parse_simple_dict(str(data["env_options"]), ";")
            if data["session_options"]:
                session_options=parse_simple_dict(str(data["session_options"]), ";")
        except Exception as e:
            log("get_sessions() error on row %s", data, exc_info=True)
            log.error("Error: sqlauth database row parsing problem:")
            log.error(" %s", e)
            return None
        return uid, gid, displays, env_options, session_options


class SqliteDatabaseUtil(DatabaseUtilBase):

    def __init__(self, uri):
        DatabaseUtilBase.__init__(self, uri)
        import sqlite3
        assert sqlite3.paramstyle=="qmark"
        self.param = "?"

    def exec_database_sql_script(self, cursor_cb, *sqlargs):
        import sqlite3
        db = sqlite3.connect(self.uri)
        cursor = db.cursor()
        log("%s.execute%s", cursor, sqlargs)
        cursor.execute(*sqlargs)
        if cursor_cb:
            cursor_cb(cursor)
        db.commit()
        return cursor

    def get_authenticator_class(self):
        return Authenticator


def main(argv):
    return run_dbutil(SqliteDatabaseUtil, "filename", argv)

if __name__ == "__main__":
    sys.exit(main(sys.argv))
