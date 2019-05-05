#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import csv, parse_simple_dict
from xpra.os_util import getuid, getgid
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here


class SQLAuthenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        self.password_query = kwargs.pop("password_query", "SELECT password FROM users WHERE username=(%s)")
        self.sessions_query = kwargs.pop("sessions_query",
                                         "SELECT uid, gid, displays, env_options, session_options "+
                                         "FROM users WHERE username=(%s) AND password=(%s)")
        SysAuthenticator.__init__(self, username, **kwargs)
        self.authenticate = self.authenticate_hmac

    def db_cursor(self, *sqlargs):
        raise NotImplementedError()

    def get_passwords(self):
        cursor = self.db_cursor(self.password_query, (self.username,))
        data = cursor.fetchall()
        if not data:
            log.info("username '%s' not found in sqlauth database", self.username)
            return None
        return tuple(str(x[0]) for x in data)

    def get_sessions(self):
        cursor = self.db_cursor(self.sessions_query, (self.username, self.password_used or ""))
        data = cursor.fetchone()
        if not data:
            return None
        return self.parse_session_data(data)

    def parse_session_data(self, data):
        try:
            uid = data[0]
            gid = data[1]
            displays = []
            env_options = {}
            session_options = {}
            if len(data)>2:
                displays = [x.strip() for x in str(data[2]).split(",")]
            if len(data)>3:
                env_options = parse_simple_dict(str(data[3]), ";")
            if len(data)>4:
                session_options = parse_simple_dict(str(data[4]), ";")
        except Exception as e:
            log("parse_session_data() error on row %s", data, exc_info=True)
            log.error("Error: sqlauth database row parsing problem:")
            log.error(" %s", e)
            return None
        return uid, gid, displays, env_options, session_options


class DatabaseUtilBase(object):

    def __init__(self, uri):
        self.uri = uri
        self.param = "?"

    def exec_database_sql_script(self, cursor_cb, *sqlargs):
        raise NotImplementedError()

    def create(self):
        sql = ("CREATE TABLE users ("
               "username VARCHAR(255) NOT NULL, "
               "password VARCHAR(255), "
               "uid VARCHAR(63), "
               "gid VARCHAR(63), "
               "displays VARCHAR(8191), "
               "env_options VARCHAR(8191), "
               "session_options VARCHAR(8191))")
        self.exec_database_sql_script(None, sql)

    def add_user(self, username, password, uid=getuid(), gid=getgid(),
                 displays="", env_options="", session_options=""):
        sql = "INSERT INTO users(username, password, uid, gid, displays, env_options, session_options) "+\
              "VALUES(%s, %s, %s, %s, %s, %s, %s)" % ((self.param,)*7)
        self.exec_database_sql_script(None, sql,
                                        (username, password, uid, gid, displays, env_options, session_options))

    def remove_user(self, username, password=None):
        sql = "DELETE FROM users WHERE username=%s" % self.param
        sqlargs = (username, )
        if password:
            sql += " AND password=%s" % self.param
            sqlargs = (username, password)
        self.exec_database_sql_script(None, sql, sqlargs)

    def list_users(self):
        fields = ("username", "password", "uid", "gid", "displays", "env_options", "session_options")
        def fmt(values, sizes):
            s = ""
            for i, field in enumerate(values):
                if i==0:
                    s += "|"
                s += ("%s" % field).rjust(sizes[i])+"|"
            return s
        def cursor_callback(cursor):
            rows = cursor.fetchall()
            if not rows:
                print("no rows found")
                cursor.close()
                return
            print("%i rows found:" % len(rows))
            #calculate max size for each field:
            sizes = [len(x)+1 for x in fields]
            for row in rows:
                for i, value in enumerate(row):
                    sizes[i] = max(sizes[i], len(str(value))+1)
            total = sum(sizes)+len(fields)+1
            print("-"*total)
            print(fmt((field.replace("_", " ") for field in fields), sizes))
            print("-"*total)
            for row in rows:
                print(fmt(row, sizes))
            cursor.close()
        sql = "SELECT %s FROM users" % csv(fields)
        self.exec_database_sql_script(cursor_callback, sql)

    def authenticate(self, username, password):
        auth_class = self.get_authenticator_class()
        a = auth_class(username, self.uri)
        passwords = a.get_passwords()
        assert passwords
        log("authenticate: got %i passwords", len(passwords))
        assert password in passwords
        a.password_used = password
        sessions = a.get_sessions()
        assert sessions
        print("success, found sessions: %s" % (sessions, ))

    def get_authenticator_class(self):
        raise NotImplementedError()


def run_dbutil(DatabaseUtilClass=DatabaseUtilBase, conn_str="databaseURI", argv=()):
    def usage(msg="invalid number of arguments"):
        print(msg)
        print("usage:")
        print(" %s %s create" % (argv[0], conn_str))
        print(" %s %s list" % (argv[0], conn_str))
        print(" %s %s add username password [uid, gid, displays, env_options, session_options]" % (argv[0], conn_str))
        print(" %s %s remove username [password]" % (argv[0], conn_str))
        print(" %s %s authenticate username password" % (argv[0], conn_str))
        return 1
    from xpra.platform import program_context
    with program_context("SQL Auth", "SQL Auth"):
        l = len(argv)
        if l<3:
            return usage()
        uri = argv[1]
        dbutil = DatabaseUtilClass(uri)
        cmd = argv[2]
        if cmd=="create":
            if l!=3:
                return usage()
            dbutil.create()
        elif cmd=="add":
            if l<5 or l>10:
                return usage()
            dbutil.add_user(*argv[3:])
        elif cmd=="remove":
            if l not in (4, 5):
                return usage()
            dbutil.remove_user(*argv[3:])
        elif cmd=="list":
            if l!=3:
                return usage()
            dbutil.list_users()
        elif cmd=="authenticate":
            if l!=5:
                return usage()
            dbutil.authenticate(*argv[3:])
        else:
            return usage("invalid command '%s'" % cmd)
    return 0
