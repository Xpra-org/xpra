# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import time
from email.utils import formatdate

from aioquic import __version__ as aioquic_version

from xpra.util.env import envint
from xpra.util.str_fn import strtobytes
from xpra.util.version import parse_version

aioquic_version_info = parse_version(aioquic_version)
if aioquic_version_info < (1, 9):
    # callers turn this into "cannot use quic sockets: ..."
    raise ImportError(f"aioquic {aioquic_version} is too old, version 1.9.0 or later is required")

SERVER_NAME = "xpra/aioquic"
USER_AGENT = "xpra/aioquic"

MAX_DATAGRAM_FRAME_SIZE = envint("XPRA_MAX_DATAGRAM_FRAME_SIZE", 65536)


def http_date() -> str:
    """ GMT date in a format suitable for http headers """
    return formatdate(time(), usegmt=True)


def binary_headers(headers: dict) -> list[tuple[bytes, bytes]]:
    """ aioquic expects the headers as a list of binary pairs """
    return [(strtobytes(k), strtobytes(v)) for k, v in headers.items()]


def override_aioquic_logger() -> None:
    from xpra.log import Logger, is_debug_enabled
    import logging
    logger = logging.getLogger("quic")
    logger.propagate = False
    logger.handlers.clear()
    # warning: don't use 'quic' as first argument to Logger
    # as this would create a logging loop
    aioquic_logger = Logger("network", "quic", "verbose")
    assert aioquic_logger._logger != logger
    if is_debug_enabled("quic"):
        aioquic_logger.setLevel(logging.DEBUG)
    else:
        aioquic_logger.setLevel(logging.WARN)
    logger.addHandler(aioquic_logger)  # type: ignore
