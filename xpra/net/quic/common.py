# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import time
from typing import Dict
from email.utils import formatdate

from xpra.util import envint
from xpra.os_util import strtobytes

SERVER_NAME = "xpra/aioquic"
USER_AGENT = "xpra/aioquic"

MAX_DATAGRAM_FRAME_SIZE = envint("XPRA_MAX_DATAGRAM_FRAME_SIZE", 65536)

def http_date():
    """ GMT date in a format suitable for http headers """
    return formatdate(time(), usegmt=True)

def binary_headers(headers : Dict):
    """ aioquic expects the headers as a list of binary pairs """
    return [(strtobytes(k), strtobytes(v)) for k,v in headers.items()]


def override_aioquic_logger():
    from xpra.log import Logger, is_debug_enabled
    import logging
    logger = logging.getLogger("quic")
    logger.propagate = False
    logger.handlers.clear()
    aioquic_logger = Logger("quic", "verbose")
    if is_debug_enabled("quic"):
        aioquic_logger.setLevel(logging.DEBUG)
    else:
        aioquic_logger.setLevel(logging.WARN)
    logger.addHandler(aioquic_logger)               # type: ignore
