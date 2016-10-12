# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket

SOCKET_HOSTNAME = os.environ.get("XPRA_SOCKET_HOSTNAME", socket.gethostname())
PREFIX = "%s-" % (SOCKET_HOSTNAME,)

LIVE = "LIVE"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"

def osexpand(s, actual_username="", uid=0, gid=0):
    if len(actual_username)>0 and s.startswith("~/"):
        #replace "~/" with "~$actual_username/"
        s = "~%s/%s" % (actual_username, s[2:])
    v = os.path.expandvars(os.path.expanduser(s))
    if os.name=="posix":
        v = v.replace("$UID", str(uid or os.getuid()))
        v = v.replace("$GID", str(gid or os.getgid()))
    if len(actual_username)>0:
        for k in ("USERNAME", "USER"):
            v = v.replace("$%s" % k, actual_username)
            v = v.replace("${%s}" % k, actual_username)
    return v
