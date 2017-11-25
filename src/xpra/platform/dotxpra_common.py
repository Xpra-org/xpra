# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket

SOCKET_HOSTNAME = os.environ.get("XPRA_SOCKET_HOSTNAME", socket.gethostname())
PREFIX = "%s-" % (SOCKET_HOSTNAME,)

LIVE = "LIVE"
DEAD = "DEAD"
UNKNOWN = "UNKNOWN"
INACCESSIBLE = "INACCESSIBLE"
