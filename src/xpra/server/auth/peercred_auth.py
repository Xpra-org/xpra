# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.platform.dotxpra_common import osexpand
from xpra.os_util import get_peercred, get_group_id, POSIX
from xpra.util import csv
assert init and log #tests will disable logging from here


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        SysAuthenticator.__init__(self, username)
        log("peercred.Authenticator(%s, %s)", username, kwargs)
        self.uid = -1
        self.gid = -1
        if not POSIX:
            log.warn("Warning: peercred authentication is not supported on %s", os.name)
            return
        connection = kwargs.get("connection", None)
        uids = kwargs.get("uid")
        gids = kwargs.get("gid")
        allow_uids = None
        allow_gids = None
        if uids:
            allow_uids = []
            for x in uids.split(","):
                x = osexpand(x.strip())
                try:
                    allow_uids.append(int(x))
                except:
                    import pwd
                    try:
                        pw = pwd.getpwnam(x)
                        uids.append(pw.pw_uid)
                    except KeyError as e:
                        log.warn("Warning: unknown username '%s'", x)
            log("peercred: allow_uids(%s)=%s", uids, allow_uids)
        if gids:
            allow_gids = []
            for x in gids.split(","):
                x = osexpand(x.strip())
                try:
                    allow_gids.append(int(x))
                except:
                    gid = get_group_id(x)
                    if gid>=0:
                        allow_gids.append(gid)
                    else:
                        log.warn("Warning: unknown group '%s'", x)
            log("peercred: allow_gids(%s)=%s", gids, allow_gids)
        try:
            from xpra.net.bytestreams import SocketConnection
            if connection and isinstance(connection, SocketConnection):
                sock = connection._socket
                peercred = get_peercred(sock)
                log("get_peercred(%s)=%s", sock, peercred)
                if not peercred:
                    log.warn("Warning: failed to get peer credentials on %s", sock)
                    return
                _, uid, gid = peercred
                if allow_uids is not None and uid not in allow_uids:
                    log.warn("Warning: peercred access denied,")
                    log.warn(" uid %i is not in the whitelist: %s", uid, csv(allow_uids))
                elif allow_gids is not None and gid not in allow_gids:
                    log.warn("Warning: peercred access denied,")
                    log.warn(" gid %i is not in the whitelist: %s", gid, csv(allow_gids))
                else:
                    self.uid = uid
                    self.gid = gid
            else:
                log("peercred: invalid connection '%s' (not a socket connection)", connection)
        except Exception as e:
            log.error("Error: cannot get peer uid")
            log.error(" %s", e)

    def get_uid(self):
        return self.uid

    def get_gid(self):
        return self.gid


    def requires_challenge(self):
        #if we didn't find the peercred,
        #pretend to require a challenge and fail it:
        return self.uid<0

    def authenticate(self, _challenge_response, _client_salt=None):
        return False

    def __repr__(self):
        return "peercred"
