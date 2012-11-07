# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import glob
import socket
import errno
import stat
import time

o0700 = 448     #0o700

class ServerSockInUse(Exception):
    pass

class DotXpra(object):
    def __init__(self, sockdir=None, confdir=None):
        self._confdir = os.path.expanduser(confdir or "~/.xpra")
        self._sockdir = os.path.expanduser(sockdir or "~/.xpra")
        if not os.path.exists(self._confdir):
            os.mkdir(self._confdir, o0700)
        if not os.path.exists(self._sockdir):
            os.mkdir(self._sockdir, o0700)
        self._prefix = "%s-" % (socket.gethostname(),)

    def confdir(self):
        return self._confdir

    def _normalize_local_display_name(self, local_display_name):
        if not local_display_name.startswith(":"):
            local_display_name = ":" + local_display_name
        if "." in local_display_name:
            local_display_name = local_display_name[:local_display_name.rindex(".")]
        assert local_display_name.startswith(":")
        for char in local_display_name[1:]:
            assert char in "0123456789"
        return local_display_name

    def make_path(self, local_display_name, dirpath ):
        local_display_name = self._normalize_local_display_name(local_display_name)
        return os.path.join( dirpath , self._prefix + local_display_name[1:])

    def socket_path(self, local_display_name):
        return self.make_path(local_display_name, self._sockdir)

    def conf_path(self, local_display_name):
        return self.make_path(local_display_name, self._confdir)

    LIVE = "LIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"
    def server_state(self, local_display_name):
        path = self.socket_path(local_display_name)
        if not os.path.exists(path):
            return self.DEAD
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(5)
        try:
            sock.connect(path)
        except socket.error, e:
            err = e.args[0]
            if err==errno.ECONNREFUSED:
                #could be the server is starting up
                return self.UNKNOWN
            if err in (errno.EWOULDBLOCK, errno.ENOENT):
                return self.DEAD
        else:
            sock.close()
            return self.LIVE
        return self.UNKNOWN

    # Same as socket_path, but preps for the server:
    def server_socket_path(self, local_display_name, clobber, wait_for_unknown=0):
        if not clobber:
            state = self.server_state(local_display_name)
            counter = 0
            while state==self.UNKNOWN and counter<wait_for_unknown:
                counter += 1
                time.sleep(1)
                state = self.server_state(local_display_name)
            if state not in (self.DEAD, self.UNKNOWN):
                raise ServerSockInUse((state, local_display_name))
        path = self.socket_path(local_display_name)
        if os.path.exists(path):
            os.unlink(path)
        return path

    def sockets(self):
        results = []
        base = os.path.join(self._sockdir, self._prefix)
        potential_sockets = glob.glob(base + "*")
        for path in potential_sockets:
            if stat.S_ISSOCK(os.stat(path).st_mode):
                local_display = ":" + path[len(base):]
                state = self.server_state(local_display)
                results.append((state, local_display))
        return results
