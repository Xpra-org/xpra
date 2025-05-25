#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import sys

from xpra.auth.sys_auth_base import log
from xpra.auth.sqlauthbase import SQLAuthenticator, DatabaseUtilBase, run_dbutil


def url_path_to_dict(path: str) -> dict[str, str]:
    pattern = (
        r'^'
        r'((?P<schema>.+?)://)?'
        r'((?P<user>.+?)(:(?P<password>.*?))?@)?'
        r'(?P<host>.*?)'
        r'(:(?P<port>\d+?))?'
        r'(?P<path>/.*?)?'
        r'(?P<query>[?].*?)?'
        r'$'
    )
    regex = re.compile(pattern)
    m = regex.match(path)
    return m.groupdict() if m is not None else {}


def db_from_uri(uri: str):
    d = url_path_to_dict(uri)
    log("settings for uri=%s : %s", uri, d)
    import mysql.connector as mysql  # pylint: disable=import-outside-toplevel
    db = mysql.connect(
        host=d.get("host", "localhost"),
        # port = int(d.get("port", 3306)),
        user=d.get("user", ""),
        passwd=d.get("password", ""),
        database=(d.get("path") or "").lstrip("/") or "xpra",
    )
    return db


class Authenticator(SQLAuthenticator):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.uri = kwargs.get("uri", "")
        assert self.uri, "missing database uri"

    def db_cursor(self, sql: str, *sqlargs):
        db = db_from_uri(self.uri)
        cursor = db.cursor()
        cursor.execute(sql, sqlargs)
        # keep reference to db,
        # so it doesn't get garbage collected just yet:
        cursor.db = db
        log("db_cursor(%s)=%s", sqlargs, cursor)
        return cursor

    def __repr__(self):
        return "mysql"


class MySQLDatabaseUtil(DatabaseUtilBase):

    def __init__(self, uri):
        super().__init__(uri)
        import mysql.connector as mysql
        assert mysql.paramstyle == "pyformat"
        self.param = "%s"

    def exec_database_sql_script(self, cursor_cb, sql: str, *sqlargs):
        db = db_from_uri(self.uri)
        cursor = db.cursor()
        log("%s.execute%s", cursor, (sql, sqlargs))
        cursor.execute(sql, sqlargs)
        if cursor_cb:
            cursor_cb(cursor)
        db.commit()
        return cursor

    def get_authenticator_class(self) -> type:
        return Authenticator


def main(argv) -> int:
    return run_dbutil(MySQLDatabaseUtil, "databaseURI", argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
