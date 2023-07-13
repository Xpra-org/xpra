# This file is part of Xpra.
# Copyright (C) 2016-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import logging
from typing import Any

from xpra.util import envbool

SILENCE_COMTYPES = envbool("XPRA_SILENCE_COMTYPES", True)
if SILENCE_COMTYPES:
    logging.getLogger("comtypes").setLevel(logging.INFO)
COMTYPES_NOGENDIR = envbool("XPRA_COMTYPES_NOGENDIR", False)


def comtypes_init() -> None:
    #pylint: disable=import-outside-toplevel
    from comtypes import client                  #@UnresolvedImport
    if COMTYPES_NOGENDIR:
        client.gen_dir = None
    from comtypes import CoInitialize               #@UnresolvedImport
    CoInitialize()


def find_tlb_file(filename:str="DirectShow.tlb") -> str:
    #try to load tlb files from various directories,
    #depending on how xpra was packaged, installed locally,
    #or even run from the source directory:
    from xpra.platform.paths import get_app_dir  # pylint: disable=import-outside-toplevel
    app_dir = get_app_dir()
    dirs = [
        app_dir,
        os.path.join(app_dir, "win32"),
        os.path.join(app_dir, "share", "xpra"),
        os.path.join(os.environ.get("MINGW_PREFIX", ""), "share", "xpra"),
        ]
    #ie: "DirectShow.tlb" -> "XPRA_DIRECTSHOW_TLB"
    env_name = "XPRA_" + filename.replace(".", "_").upper()
    filenames = [os.environ.get(env_name)] + [os.path.join(d, filename) for d in dirs]
    for f in filenames:
        if f and os.path.exists(f):
            return f
    return ""


class QuietenLogging:

    def __init__(self, *_args):
        self.loggers = [logging.getLogger(x) for x in ("comtypes.client._code_cache", "comtypes.client._generate")]
        self.saved_levels = [x.getEffectiveLevel() for x in self.loggers]
        self._generate : Any = None

    def __enter__(self):
        if not SILENCE_COMTYPES:
            return
        for logger in self.loggers:
            logger.setLevel(logging.WARNING)
        self.verbose = None
        from comtypes import client                  #@UnresolvedImport pylint: disable=import-outside-toplevel
        gen = getattr(client, "_generate", None)
        self._generate = gen
        if gen:
            self.verbose = getattr(gen, "__verbose__", None)
            if self.verbose is not None:
                gen.__verbose__ = False

    def __exit__(self, *_args):
        if not SILENCE_COMTYPES:
            return
        gen = self._generate
        if gen and self.verbose is not None:
            gen.__verbose__ = self.verbose
        for i, logger in enumerate(self.loggers):
            logger.setLevel(self.saved_levels[i])


class CIMV2_Query(QuietenLogging):

    def __init__(self, query):
        self.query = query
        super().__init__()

    def __enter__(self):
        super().__enter__()
        from comtypes.client import CreateObject        #@UnresolvedImport pylint: disable=import-outside-toplevel
        o = CreateObject("WbemScripting.SWbemLocator")
        s = o.ConnectServer(".", "root\\cimv2")
        return s.ExecQuery(self.query)
