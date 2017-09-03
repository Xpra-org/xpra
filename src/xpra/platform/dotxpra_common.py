# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket

from xpra.os_util import shellsub

SOCKET_HOSTNAME = os.environ.get("XPRA_SOCKET_HOSTNAME", socket.gethostname())
PREFIX = "%s-" % (SOCKET_HOSTNAME,)

LIVE = "LIVE"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"
INACCESSIBLE = "INACCESSIBLE"

def osexpand(s, actual_username="", uid=0, gid=0):
    if len(actual_username)>0 and s.startswith("~/"):
        #replace "~/" with "~$actual_username/"
        s = "~%s/%s" % (actual_username, s[2:])
    v = os.path.expandvars(os.path.expanduser(s))
    if os.name=="posix":
        v = shellsub(v, {
            "UID"   : uid or os.geteuid(),
            "GID"   : gid or os.getegid(),
            })
    if len(actual_username)>0:
        v = shellsub(v, {
            "USERNAME"  : actual_username,
            "USER"      : actual_username,
            })
    return v
