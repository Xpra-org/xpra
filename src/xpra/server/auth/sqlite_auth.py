#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os

from xpra.util import parse_simple_dict, csv, engs
from xpra.os_util import getuid, getgid
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log, parse_uid, parse_gid
assert init and log #tests will disable logging from here

def init(opts):
    pass


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        filename = kwargs.pop("filename", 'sqlite.sdb')
        if filename and not os.path.isabs(filename):
            exec_cwd = kwargs.get("exec_cwd", os.getcwd())
            filename = os.path.join(exec_cwd, filename)
        self.filename = filename
        self.password_query = kwargs.pop("password_query", "SELECT password FROM users WHERE username=(?)")
        self.sessions_query = kwargs.pop("sessions_query", "SELECT uid, gid, displays, env_options, session_options FROM users WHERE username=(?)")
        SysAuthenticator.__init__(self, username, **kwargs)
        self.authenticate = self.authenticate_hmac

    def __repr__(self):
        return "sqlite"

    def get_passwords(self):
        if not os.path.exists(self.filename):
            log.error("Error: sqlauth cannot find the database file '%s'", self.filename)
            return None
        log("sqlauth.get_password() found database file '%s'", self.filename)
        import sqlite3
        try:
            conn = sqlite3.connect(self.filename)
            cursor = conn.cursor()
            cursor.execute(self.password_query, [self.username])
            data = cursor.fetchall()
        except sqlite3.DatabaseError as e:
            log("get_password()", exc_info=True)
            log.error("Error: sqlauth database access problem:")
            log.error(" %s", e)
            return None
        if not data:
            log.info("username '%s' not found in sqlauth database", self.username)
            return None
        return tuple(str(x[0]) for x in data)

    def get_sessions(self):
        import sqlite3
        try:
            conn = sqlite3.connect(self.filename)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(self.sessions_query, [self.username])
            data = cursor.fetchone()
        except sqlite3.DatabaseError as e:
            log("get_sessions()", exc_info=True)
            log.error("Error: sqlauth database access problem:")
            log.error(" %s", e)
            return None
        try:
            uid = parse_uid(data["uid"])
            gid = parse_gid(data["gid"])
            displays = []
            env_options = {}
            session_options = {}
            if data["displays"]:
                displays = [x.strip() for x in str(data[2]).split(",")]
            if data["env_options"]:
                env_options = parse_simple_dict(str(data[3]), ";")
            if data["session_options"]:
                session_options=parse_simple_dict(str(data[4]), ";")
        except Exception as e:
            log("get_sessions() error on row %s", data, exc_info=True)
            log.error("Error: sqlauth database row parsing problem:")
            log.error(" %s", e)
            return None
        return uid, gid, displays, env_options, session_options


def exec_database_sql_script(cursor_cb, filename, *sqlargs):
    log("exec_database_sql_script%s", (cursor_cb, filename, sqlargs))
    import sqlite3
    try:
        conn = sqlite3.connect(filename)
        cursor = conn.cursor()
        cursor.execute(*sqlargs)
        if cursor_cb:
            cursor_cb(cursor)
        conn.commit()
        conn.close()
        return 0
    except sqlite3.DatabaseError as e:
        log.error("Error: database access problem:")
        log.error(" %s", e)
        return 1


def create(filename):
    if os.path.exists(filename):
        log.error("Error: database file '%s' already exists", filename)
        return 1
    sql = ("CREATE TABLE users ("
           "username VARCHAR NOT NULL, "
           "password VARCHAR, "
           "uid INTEGER NOT NULL, "
           "gid INTEGER NOT NULL, "
           "displays VARCHAR, "
           "env_options VARCHAR, "
           "session_options VARCHAR)")
    return exec_database_sql_script(None, filename, sql)

def add_user(filename, username, password, uid=getuid(), gid=getgid(), displays="", env_options="", session_options=""):
    sql = "INSERT INTO users(username, password, uid, gid, displays, env_options, session_options) VALUES(?, ?, ?, ?, ?, ?, ?)"
    return exec_database_sql_script(None, filename, sql, (username, password, uid, gid, displays, env_options, session_options))

def remove_user(filename, username, password=None):
    sql = "DELETE FROM users WHERE username=?"
    sqlargs = (username, )
    if password:
        sql += " AND password=?"
        sqlargs = (username, password)
    return exec_database_sql_script(None, filename, sql, sqlargs)

def list_users(filename):
    fields = ["username", "password", "uid", "gid", "displays", "env_options", "session_options"]
    def cursor_callback(cursor):
        rows = cursor.fetchall()
        if len(rows)==0:
            print("no rows found")
            return
        print("%i rows found:" % len(rows))
        print(csv(fields))
        for row in rows:
            print(csv(row))
    sql = "SELECT %s FROM users" % csv(fields)
    return exec_database_sql_script(cursor_callback, filename, sql)

def authenticate(filename, username, password):
    a = Authenticator(username, filename=filename)
    passwords = a.get_passwords()
    assert passwords
    assert password in passwords
    sessions = a.get_sessions()
    assert sessions
    print("success, found %i session%s: %s" % (len(sessions), engs(sessions), sessions))
    return 0

def main(argv):
    def usage(msg="invalid number of arguments"):
        print(msg)
        print("usage:")
        print(" %s databasefile create" % sys.argv[0])
        print(" %s databasefile list" % sys.argv[0])
        print(" %s databasefile add username password [uid, gid, displays, env_options, session_options" % sys.argv[0])
        print(" %s databasefile remove username [password]" % sys.argv[0])
        print(" %s databasefile authenticate username password" % sys.argv[0])
        return 1
    from xpra.platform import program_context
    with program_context("SQL Auth", "SQL Auth"):
        l = len(argv)
        if l<3:
            return usage()
        filename = argv[1]
        cmd = argv[2]
        if cmd=="create":
            if l!=3:
                return usage()
            return create(filename)
        elif cmd=="add":
            if l<5 or l>10:
                return usage()
            return add_user(filename, *argv[3:])
        elif cmd=="remove":
            if l not in (4, 5):
                return usage()
            return remove_user(filename, *argv[3:])
        elif cmd=="list":
            if l!=3:
                return usage()
            return list_users(filename)
        elif cmd=="authenticate":
            if l!=5:
                return usage()
            return authenticate(filename, *argv[3:])
        else:
            return usage("invalid command '%s'" % cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
