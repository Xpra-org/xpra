# This file is part of Xpra.
# Copyright (C) 2016-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import logging
logging.getLogger("comtypes").setLevel(logging.INFO)

import comtypes                                         #@UnresolvedImport
assert comtypes
from comtypes import client                  #@UnresolvedImport


class QuietenLogging(object):

    def __init__(self, *_args):
        self.loggers = [logging.getLogger(x) for x in ("comtypes.client._code_cache", "comtypes.client._generate")]
        self.saved_levels = [x.getEffectiveLevel() for x in self.loggers]
        self.verbose = getattr(client._generate, "__verbose__", None)

    def __enter__(self):
        client._generate.__verbose__ = False
        for logger in self.loggers:
            logger.setLevel(logging.WARNING)

    def __exit__(self, *_args):
        if self.verbose is not None:
            client._generate.__verbose__ = self.verbose
        for i, logger in enumerate(self.loggers):
            logger.setLevel(self.saved_levels[i])
