#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def silence_info(module):
    return LoggerSilencer(module, ("info", ))

def silence_warn(module):
    return LoggerSilencer(module, ("warn", ))

def silence_error(module):
    return LoggerSilencer(module, ("error", ))

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

    def __init__(self, module, silence=("error", "warn", "info")):
        self.module = module
        self.silence = silence
        self.saved = None
    def __enter__(self):
        self.saved = self.module.log
        self.module.log = SilencedLogger(self.silence)
    def __exit__(self, *_args):
        self.module.log = self.saved
    def __repr__(self):
        return "LoggerSilencer"
