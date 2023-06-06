# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import ByteString

from xpra.util import envbool
from xpra.log import Logger

log = Logger("codec")

SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")


def may_save_image(coding:str, data:ByteString, now:float=0):
    if SAVE_TO_FILE:    # pragma: no cover
        now = now or monotonic()
        ext = coding.lower().replace("/", "-")
        filename = f"./{now}.{ext}"
        with open(filename, "wb") as f:
            f.write(data)
        log.info("saved %7i bytes to %s", len(data), filename)
