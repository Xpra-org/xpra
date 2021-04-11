# This file is part of Xpra.
# Copyright (C) 2016-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import logging
from xpra.util import envbool

SILENCE_COMTYPES = envbool("XPRA_SILENCE_COMTYPES", True)
if SILENCE_COMTYPES:
    logging.getLogger("comtypes").setLevel(logging.INFO)


class QuietenLogging(object):

    def __init__(self, *_args):
        self.loggers = [logging.getLogger(x) for x in ("comtypes.client._code_cache", "comtypes.client._generate")]
        self.saved_levels = [x.getEffectiveLevel() for x in self.loggers]

    def __enter__(self):
        if not SILENCE_COMTYPES:
            return
        for logger in self.loggers:
            logger.setLevel(logging.WARNING)
        self.verbose = None
        from comtypes import client                  #@UnresolvedImport
        gen = getattr(client, "_generate", None)
        if gen:
            self.verbose = getattr(gen, "__verbose__", None)
            if self.verbose is not None:
                gen.__verbose__ = False

    def __exit__(self, *_args):
        if not SILENCE_COMTYPES:
            return
        if self.verbose is not None:
            from comtypes import client                  #@UnresolvedImport
            gen = getattr(client, "_generate", None)
            if gen:
                gen.__verbose__ = self.verbose
        for i, logger in enumerate(self.loggers):
            logger.setLevel(self.saved_levels[i])
