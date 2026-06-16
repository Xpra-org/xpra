#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import TypeAlias

from xpra.util.env import get_saved_env
from xpra.auth.sys_auth_base import log, DEFAULT_UID, DEFAULT_GID
from xpra.os_util import POSIX
from xpra.util.parsing import parse_str_dict

SessionData: TypeAlias = tuple[int, int, list[str], dict[str, str], dict[str, str]]
AuthLine: TypeAlias = tuple[str, str, int, int, list[str], dict[str, str], dict[str, str]]


def parse_uid(v) -> int:
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            log(f"uid {v!r} is not an integer")
    if POSIX:
        try:
            import pwd  # pylint: disable=import-outside-toplevel
            return pwd.getpwnam(v or DEFAULT_UID).pw_uid
        except Exception as e:
            log(f"parse_uid({v})", exc_info=True)
            log.error(f"Error: cannot find uid of {v!r}: {e}")
        return os.getuid()
    return -1


def parse_gid(v) -> int:
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            log(f"gid {v!r} is not an integer")
    if POSIX:
        try:
            import grp  # pylint: disable=import-outside-toplevel
            return grp.getgrnam(v or DEFAULT_GID).gr_gid
        except Exception as e:
            log(f"parse_gid({v})", exc_info=True)
            log.error(f"Error: cannot find gid of {v!r}: {e}")
        return os.getgid()
    return -1


def get_auth_exec_env(display="auto") -> dict[str, str]:
    env = os.environ.copy()
    # remove usless vars:
    for k in ("LS_COLORS", ""):
        env.pop(k, "")
    if display == "auto":
        # if the server was started from an existing display,
        # show the OTP there
        saved_env = get_saved_env()
        for key in ("DISPLAY", "WAYLAND_DISPLAY"):
            if key in saved_env:
                env[key] = saved_env[key]
    elif display:
        env["DISPLAY"] = display
    return env


def parse_auth_line(line: str) -> AuthLine:
    fields = line.split("|")
    if len(fields) < 2:
        raise ValueError(f"not enough fields: {len(fields)}, minimum is 2")
    log(f"found {len(fields)} fields")
    username = fields[0]
    password = fields[1]
    if len(fields) >= 5:
        uid = parse_uid(fields[2])
        gid = parse_gid(fields[3])
        displays = fields[4].split(",")
    else:
        uid = parse_uid(None)
        gid = parse_gid(None)
        displays = []
    env_options: dict[str, str] = {}
    session_options: dict[str, str] = {}
    if len(fields) >= 6:
        env_options = parse_str_dict(fields[5], ";")
    if len(fields) >= 7:
        session_options = parse_str_dict(fields[6], ";")
    return username, password, uid, gid, displays, env_options, session_options


def parse_filedata(data: str, password_filename: str = "", allow_plain: bool = False,
                   reject_duplicates: bool = False) -> str | dict[str, AuthLine]:
    data = data.strip()
    if not data:
        return "" if allow_plain else {}
    lines = [x.strip() for x in data.splitlines() if x.strip() and not x.strip().startswith("#")]
    if allow_plain and not any("|" in x for x in lines):
        return "\n".join(lines)
    auth_data: dict[str, AuthLine] = {}
    for i, line in enumerate(lines, start=1):
        log(f"line {i}: {line!r}")
        try:
            entry = parse_auth_line(line)
        except Exception as e:
            log("parsing error", exc_info=True)
            log.error(f"Error parsing password file {password_filename!r} at line {i}:")
            log.error(f" {line!r}")
            log.estr(e)
            continue
        username = entry[0]
        if reject_duplicates and username in auth_data:
            log.error(f"Error: duplicate entry for username {username!r} in {password_filename!r}")
            continue
        auth_data[username] = entry
    log(f"parsed auth data from file {password_filename!r}: {auth_data}")
    return auth_data
