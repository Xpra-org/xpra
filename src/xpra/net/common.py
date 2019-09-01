# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import repr_ellipsized
from xpra.log import Logger
log = Logger("network")

class ConnectionClosedException(Exception):
    pass


def get_log_packets(exclude=False):
    lp = os.environ.get("XPRA_LOG_PACKETS")
    if not lp:
        return None
    pt = []
    for x in lp.split(","):
        if x.startswith("-")==exclude:
            pt.append(x[int(exclude):])
    return tuple(pt)

LOG_PACKETS = get_log_packets()
NOLOG_PACKETS = get_log_packets(True)

def _may_log_packet(packet_type, packet):
    if packet_type in NOLOG_PACKETS:
        return
    if packet_type in LOG_PACKETS or "*" in LOG_PACKETS:
        s = str(packet)
        if len(s)>200:
            s = repr_ellipsized(s, 200)
        log.info(s)

def noop(*_args):
    pass

if LOG_PACKETS or NOLOG_PACKETS:
    may_log_packet = _may_log_packet
else:
    may_log_packet = noop
log.info("may_log_packet=%s", may_log_packet)
