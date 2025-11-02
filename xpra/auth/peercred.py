# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.auth.sys_auth_base import SysAuthenticator, log
from xpra.os_util import get_group_id, getuid, POSIX
from xpra.util.env import osexpand
from xpra.net.common import get_peercred
from xpra.net.bytestreams import SocketConnection
from xpra.util.parsing import TRUE_OPTIONS
from xpra.util.objects import typedict
from xpra.util.str_fn import csv


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log("peercred.Authenticator(%s)", kwargs)
        self.uid = -1
        self.gid = -1
        self.peercred_check = False
        if not POSIX:
            log.warn("Warning: peercred authentication is not supported on %r", os.name)
            return
        connection = kwargs.get("connection", None)
        uids = kwargs.pop("uid", "")
        gids = kwargs.pop("gid", "")
        allow_owner = kwargs.pop("allow-owner", "yes").lower() in TRUE_OPTIONS
        self.check_peercred(connection, uids, gids, allow_owner)
        super().__init__(**kwargs)

    def check_peercred(self, connection, uids="", gids="", allow_owner: bool = False) -> None:
        allow_uids = allow_gids = None
        if uids:
            allow_uids = []
            for x in uids.split(":"):
                if not x.strip():
                    continue
                x = osexpand(x.strip())
                try:
                    allow_uids.append(int(x))
                except ValueError:
                    import pwd  # pylint: disable=import-outside-toplevel
                    try:
                        pw = pwd.getpwnam(x)
                        allow_uids.append(pw.pw_uid)
                    except KeyError:
                        log.warn("Warning: unknown username '%s'", x)
            log("peercred: allow_uids(%s)=%s", uids, allow_uids)
        if gids:
            allow_gids = []
            for x in gids.split(":"):
                if not x.strip():
                    continue
                x = osexpand(x.strip())
                try:
                    allow_gids.append(int(x))
                except ValueError:
                    gid = get_group_id(x)
                    if gid >= 0:
                        allow_gids.append(gid)
                    else:
                        log.warn("Warning: unknown group '%s'", x)
            log("peercred: allow_gids(%s)=%s", gids, allow_gids)
        self.do_check_peercred(connection, allow_uids, allow_gids, allow_owner)

    def do_check_peercred(self, connection, allow_uids=None, allow_gids=None, allow_owner=False):
        try:
            if connection and isinstance(connection, SocketConnection):
                sock = connection._socket
                peercred = get_peercred(sock)
                log("get_peercred(%s)=%s", sock, peercred)
                if not peercred:
                    log.warn("Warning: failed to get peer credentials on %s", sock)
                    return
                _, uid, gid = peercred

                def check() -> bool:
                    if allow_owner and uid == getuid():
                        log(f"matched owner: {uid}")
                        return True
                    if allow_uids is not None and uid in allow_uids:
                        log(f"matched uid: {uid} from allow list: %s", csv(allow_uids))
                        return True
                    if allow_gids is not None and gid in allow_gids:
                        log(f"matched gid: {gid} from allow list: %s", csv(allow_gids))
                        return True
                    log.warn("Warning: peercred access denied,")
                    if allow_owner:
                        log.warn(f" does not match owner {uid}")
                    if allow_uids:
                        log.warn(" does not match allowed uids %s", csv(allow_uids))
                    if allow_gids:
                        log.warn(" does not match allowed gids %s", csv(allow_gids))
                    return False

                if check():
                    self.peercred_check = True
                    self.uid = uid
                    self.gid = gid
            else:
                log("peercred: invalid connection '%s' (not a socket connection)", connection)
        except Exception as e:
            log("peercred", exc_info=True)
            log.error("Error: cannot get peer uid")
            log.estr(e)

    def get_uid(self) -> int:
        return self.uid

    def get_gid(self) -> int:
        return self.gid

    def requires_challenge(self) -> bool:
        return False

    def authenticate(self, _caps: typedict) -> bool:  # pylint: disable=arguments-differ
        return self.peercred_check

    def __repr__(self):
        return "peercred"
