# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import time
from email.utils import formatdate
from xpra.util import envint

SERVER_NAME = "xpra/aioquic"
USER_AGENT = "xpra/aioquic"

MAX_DATAGRAM_FRAME_SIZE = envint("XPRA_MAX_DATAGRAM_FRAME_SIZE", 65536)

def http_date():
    """ GMT date in a format suitable for http headers """
    return formatdate(time(), usegmt=True)
