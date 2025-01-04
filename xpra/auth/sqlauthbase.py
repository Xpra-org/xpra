#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.util.str_fn import csv
from xpra.util.parsing import parse_str_dict
from xpra.os_util import getuid, getgid
from xpra.auth.common import SessionData
from xpra.auth.sys_auth_base import SysAuthenticator, log


class SQLAuthenticator(SysAuthenticator):
    CLIENT_USERNAME = True

    def __init__(self, **kwargs):
        self.password_query: str = kwargs.pop("password_query", "SELECT password FROM users WHERE username=(%s)")
        self.sessions_query: str = kwargs.pop("sessions_query",
                                              "SELECT uid, gid, displays, env_options, session_options FROM users WHERE username=(%s) AND password=(%s)")  # noqa: E501
        super().__init__(**kwargs)
        self.authenticate_check = self.authenticate_hmac

    def db_cursor(self, *sqlargs):
        raise NotImplementedError()

    def get_passwords(self) -> Sequence[str]:
        cursor = self.db_cursor(self.password_query, (self.username,))
        data = cursor.fetchall()
        if not data:
            log.info("username {self.username!r} was not found in SQL authentication database")
            return ()
        return tuple(str(x[0]) for x in data)

    def get_sessions(self) -> SessionData | None:
        cursor = self.db_cursor(self.sessions_query, (self.username, self.password_used or ""))
        data = cursor.fetchone()
        if not data:
            return None
        return self.parse_session_data(data)

    def parse_session_data(self, data) -> SessionData | None:
        displays: list[str] = []
        env_options: dict[str, str] = {}
        session_options: dict[str, str] = {}
        try:
            uid = int(data[0] or "0")
            gid = int(data[1] or "0")
            if len(data) > 2:
                displays = [x.strip() for x in str(data[2]).split(",")]
            if len(data) > 3:
                env_options = parse_str_dict(str(data[3]), ";")
            if len(data) > 4:
                session_options = parse_str_dict(str(data[4]), ";")
        except Exception as e:
            log("parse_session_data() error on row %s", data, exc_info=True)
            log.error("Error: sqlauth database row parsing problem:")
            log.estr(e)
            uid = self.get_uid()
            gid = self.get_gid()
        return uid, gid, displays, env_options, session_options


class DatabaseUtilBase:

    def __init__(self, uri: str):
        self.uri = uri
        self.param = "?"

    def exec_database_sql_script(self, cursor_cb, *sqlargs):
        raise NotImplementedError()

    def create(self) -> None:
        sql = ("CREATE TABLE users ("
               "username VARCHAR(255) NOT NULL, "
               "password VARCHAR(255), "
               "uid VARCHAR(63), "
               "gid VARCHAR(63), "
               "displays VARCHAR(8191), "
               "env_options VARCHAR(8191), "
               "session_options VARCHAR(8191))")
        self.exec_database_sql_script(None, sql)

    def add_user(self, username: str, password: str, uid: int = getuid(), gid: int = getgid(),
                 displays="", env_options="", session_options="") -> None:
        sql = "INSERT INTO users(username, password, uid, gid, displays, env_options, session_options) " \
              "VALUES(%s, %s, %s, %s, %s, %s, %s)" % ((self.param,) * 7)
        self.exec_database_sql_script(None, sql,
                                      (username, password, uid, gid, displays, env_options, session_options))

    def remove_user(self, username: str, password: str = "") -> None:
        sql = "DELETE FROM users WHERE username=%s" % self.param
        sqlargs: Sequence[str] = (username,)
        if password:
            sql += " AND password=%s" % self.param
            sqlargs = (username, password)
        self.exec_database_sql_script(None, sql, sqlargs)

    def list_users(self) -> None:
        fields = ("username", "password", "uid", "gid", "displays", "env_options", "session_options")

        def fmt(values, sizes):
            s = ""
            for i, field in enumerate(values):
                if i == 0:
                    s += "|"
                s += ("%s" % field).rjust(sizes[i]) + "|"
            return s

        def cursor_callback(cursor):
            rows = cursor.fetchall()
            if not rows:
                print("no rows found")
                cursor.close()
                return
            print("%i rows found:" % len(rows))
            # calculate max size for each field:
            sizes = [len(x) + 1 for x in fields]
            for row in rows:
                for i, value in enumerate(row):
                    sizes[i] = max(sizes[i], len(str(value)) + 1)
            total = sum(sizes) + len(fields) + 1
            print("-" * total)
            print(fmt((field.replace("_", " ") for field in fields), sizes))
            print("-" * total)
            for row in rows:
                print(fmt(row, sizes))
            cursor.close()

        sql = "SELECT %s FROM users" % csv(fields)
        self.exec_database_sql_script(cursor_callback, sql)

    def authenticate(self, username: str, password: str) -> None:
        auth_class = self.get_authenticator_class()
        a = auth_class(username, self.uri)
        passwords = a.get_passwords()
        assert passwords
        log("authenticate: got %i passwords", len(passwords))
        assert password in passwords
        a.password_used = password
        sessions = a.get_sessions()
        assert sessions, "no sessions found"
        log("sql authentication success, found sessions: %s", sessions)

    def get_authenticator_class(self) -> type:
        raise NotImplementedError()


def run_dbutil(database_util_class=DatabaseUtilBase, conn_str="databaseURI", argv=()) -> int:
    def usage(msg="invalid number of arguments"):
        print(msg)
        print("usage:")
        print(" %s %s create" % (argv[0], conn_str))
        print(" %s %s list" % (argv[0], conn_str))
        print(" %s %s add username password [uid, gid, displays, env_options, session_options]" % (argv[0], conn_str))
        print(" %s %s remove username [password]" % (argv[0], conn_str))
        print(" %s %s authenticate username password" % (argv[0], conn_str))
        return 1

    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("SQL Auth", "SQL Auth"):
        nargs = len(argv)
        if nargs < 3:
            return usage()
        uri = argv[1]
        dbutil = database_util_class(uri)
        cmd = argv[2]
        if cmd == "create":
            if nargs != 3:
                return usage()
            dbutil.create()
        elif cmd == "add":
            if nargs < 5 or nargs > 10:
                return usage()
            dbutil.add_user(*argv[3:])
        elif cmd == "remove":
            if nargs not in (4, 5):
                return usage()
            dbutil.remove_user(*argv[3:])
        elif cmd == "list":
            if nargs != 3:
                return usage()
            dbutil.list_users()
        elif cmd == "authenticate":
            if nargs != 5:
                return usage()
            dbutil.authenticate(*argv[3:])
        else:
            return usage("invalid command '%s'" % cmd)
    return 0
