#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import sys

from xpra.server.auth.sys_auth_base import init, log
from xpra.server.auth.sqlauthbase import SQLAuthenticator, DatabaseUtilBase, run_dbutil
assert init and log #tests will disable logging from here


def url_path_to_dict(path):
    pattern = (r'^'
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
    d = m.groupdict() if m is not None else None
    return d

def db_from_uri(uri):
    d = url_path_to_dict(uri)
    log("settings for uri=%s : %s", uri, d)
    import mysql.connector as mysql  #@UnresolvedImport
    db = mysql.connect(
        host = d.get("host", "localhost"),
        #port = int(d.get("port", 3306)),
        user = d.get("user", ""),
        passwd = d.get("password", ""),
        database = (d.get("path") or "").lstrip("/") or "xpra",
    )
    return db


class Authenticator(SQLAuthenticator):

    def __init__(self, username, uri, **kwargs):
        SQLAuthenticator.__init__(self, username, **kwargs)
        self.uri = uri

    def db_cursor(self, *sqlargs):
        db = db_from_uri(self.uri)
        cursor = db.cursor()
        cursor.execute(*sqlargs)
        #keep reference to db so it doesn't get garbage collected just yet:
        cursor.db = db
        log("db_cursor(%s)=%s", sqlargs, cursor)
        return cursor

    def __repr__(self):
        return "mysql"


class MySQLDatabaseUtil(DatabaseUtilBase):

    def __init__(self, uri):
        DatabaseUtilBase.__init__(self, uri)
        import mysql.connector as mysql  #@UnresolvedImport
        assert mysql.paramstyle=="pyformat"
        self.param = "%s"

    def exec_database_sql_script(self, cursor_cb, *sqlargs):
        db = db_from_uri(self.uri)
        cursor = db.cursor()
        log("%s.execute%s", cursor, sqlargs)
        cursor.execute(*sqlargs)
        if cursor_cb:
            cursor_cb(cursor)
        db.commit()
        return cursor

    def get_authenticator_class(self):
        return Authenticator


def main():
    return run_dbutil(MySQLDatabaseUtil, "databaseURI", sys.argv)

if __name__ == "__main__":
    sys.exit(main())
