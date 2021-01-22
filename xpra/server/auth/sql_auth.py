#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.server.auth.sqlauthbase import SQLAuthenticator, DatabaseUtilBase, run_dbutil
from xpra.server.auth.sys_auth_base import log


class Authenticator(SQLAuthenticator):

    def __init__(self, username, uri, **kwargs):
        super().__init__(username, **kwargs)
        self.uri = uri

    def db_cursor(self, *sqlargs):
        from sqlalchemy import create_engine    #@UnresolvedImport
        db = create_engine(self.uri)
        cursor = db.cursor()
        cursor.execute(*sqlargs)
        #keep reference to db so it doesn't get garbage collected just yet:
        cursor.db = db
        log("db_cursor(%s)=%s", sqlargs, cursor)
        return cursor

    def __repr__(self):
        return "sql"


class SQLDatabaseUtil(DatabaseUtilBase):

    def __init__(self, uri):
        super().__init__(uri)
        #from sqlalchemy import create_engine    #@UnresolvedImport
        #db = create_engine(self.uri)
        self.param = os.environ.get("PARAMSTYLE", "%s")

    def exec_database_sql_script(self, cursor_cb, *sqlargs):
        from sqlalchemy import create_engine    #@UnresolvedImport
        db = create_engine(self.uri)
        log("%s.execute%s", db, sqlargs)
        result = db.execute(*sqlargs)
        log("result=%s", result)
        if cursor_cb:
            cursor_cb(result)
        return result

    def get_authenticator_class(self):
        return Authenticator


def main():
    return run_dbutil(SQLDatabaseUtil, "databaseURI", sys.argv)

if __name__ == "__main__":
    sys.exit(main())
