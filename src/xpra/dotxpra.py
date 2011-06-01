# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import os.path
import glob
import socket
import errno
import stat

from xpra.platform import XPRA_LOCAL_SERVERS_SUPPORTED

class ServerSockInUse(Exception):
    pass

class DotXpra(object):
    def __init__(self, dir=None):
        assert XPRA_LOCAL_SERVERS_SUPPORTED
        if dir is None:
            dir = os.path.expanduser("~/.xpra")
        self._dir = dir
        if not os.path.exists(self._dir):
            os.mkdir(dir, 0700)
        self._prefix = "%s-" % (socket.gethostname(),)

    def dir(self):
        return self._dir

    def _normalize_local_display_name(self, local_display_name):
        if not local_display_name.startswith(":"):
            local_display_name = ":" + local_display_name
        if "." in local_display_name:
            local_display_name = local_display_name[:local_display_name.rindex(".")]
        assert local_display_name.startswith(":")
        for char in local_display_name[1:]:
            assert char in "0123456789"
        return local_display_name

    def socket_path(self, local_display_name):
        local_display_name = self._normalize_local_display_name(local_display_name)
        return os.path.join(self._dir, self._prefix + local_display_name[1:])

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
            if err in (errno.ECONNREFUSED, errno.ENOENT):
                return self.DEAD
        else:
            sock.close()
            return self.LIVE
        return self.UNKNOWN

    # Same as socket_path, but preps for the server:
    def server_socket_path(self, local_display_name, clobber):
        if not clobber:
            state = self.server_state(local_display_name)
            if state is not self.DEAD:
                raise ServerSockInUse, (state, local_display_name)
        path = self.socket_path(local_display_name)
        if os.path.exists(path):
            os.unlink(path)
        return path

    def sockets(self):
        results = []
        base = os.path.join(self._dir, self._prefix)
        potential_sockets = glob.glob(base + "*")
        for path in potential_sockets:
            if stat.S_ISSOCK(os.stat(path).st_mode):
                local_display = ":" + path[len(base):]
                state = self.server_state(local_display)
                results.append((state, local_display))
        return results
