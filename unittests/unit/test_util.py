#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def silence_info(logger):
    return LoggerSilencer(logger, ("info", ))

def silence_warn(logger):
    return LoggerSilencer(logger, ("warn", ))

def silence_error(logger):
    return LoggerSilencer(logger, ("error", ))


class LoggerSilencer:

    def __init__(self, logger, silence=("error", "warn", "info")):
        self.logger = logger
        self.silence = silence
        self.saved = []
    def __enter__(self):
        self.saved = []
        for x in self.silence:
            self.saved.append(getattr(self.logger, x, None))
            setattr(self.logger, x, self.logger.debug)
    def __exit__(self, *_args):
        for i, x in enumerate(self.silence):
            setattr(self.logger, x, self.saved[i])
    def __repr__(self):
        return "LoggerSilencer"
