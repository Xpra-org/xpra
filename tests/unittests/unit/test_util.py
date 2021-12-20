#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def silence_info(module, logger="log"):
    return LoggerSilencer(module, ("info", ), logger)

def silence_warn(module, logger="log"):
    return LoggerSilencer(module, ("warn", ), logger)

def silence_error(module, logger="log"):
    return LoggerSilencer(module, ("error", ), logger)

#to silence warnings triggered by the tests:
from xpra.log import Logger
class SilencedLogger(Logger):
    def __init__(self, silence=("error", "warn", "info")):
        super().__init__()
        def nolog(*_args, **_kwargs):
            pass    #silence any output
        for x in silence:
            setattr(self, x, nolog)


class LoggerSilencer:

    def __init__(self, module, silence=("error", "warn", "info"), logger="log"):
        self.module = module
        self.logger = logger
        self.silence = silence
        self.saved = None
    def __enter__(self):
        self.saved = getattr(self.module, self.logger)
        setattr(self.module, self.logger, SilencedLogger(self.silence))
    def __exit__(self, *_args):
        setattr(self.module, self.logger, self.saved)
    def __repr__(self):
        return "LoggerSilencer"
