#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import logging

from xpra.util.env import envbool


def silence_info(module, logger="log"):
    return LoggerSilencer(module, logger, logging.INFO)


def silence_warn(module, logger="log"):
    return LoggerSilencer(module, logger, logging.WARN)


def silence_error(module, logger="log"):
    return LoggerSilencer(module, logger, logging.ERROR)


# to silence warnings triggered by the tests:


class LoggerSilencer:

    def __init__(self, module, logger="log", level=0):
        self.module = module
        self.logger = logger
        self.level = level
        self.saved = 0

    def __enter__(self):
        if not envbool("XPRA_TEST_DEBUG", 0):
            logger = getattr(self.module, self.logger)
            self.saved = logger.min_level
            setattr(logger, "min_level", self.level)

    def __exit__(self, *_args):
        logger = getattr(self.module, self.logger)
        setattr(logger, "min_level", self.saved)

    def __repr__(self):
        return "LoggerSilencer"


def get_free_tcp_port() -> int:
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port
