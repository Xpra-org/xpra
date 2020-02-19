# This file is part of Xpra.
# Copyright (C) 2015-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-order
#pylint: disable=wrong-import-position

import os
import logging

from xpra.util import envbool
from xpra.log import Logger

PIL_DEBUG = envbool("XPRA_PIL_DEBUG", False)
if PIL_DEBUG:   # pragma: no cover
    log = Logger("encoder", "pillow")
    log.info("enabling PIL.DEBUG")
    level = logging.DEBUG
else:
    level = logging.INFO

#newer versions use this logger,
#we must initialize it before we load the class:
for x in ("Image", "PngImagePlugin", "WebPImagePlugin", "JpegImagePlugin"):
    logger = logging.getLogger("PIL.%s" % x)
    logger.setLevel(level)

import PIL                      #@UnresolvedImport
from PIL import Image           #@UnresolvedImport
assert PIL is not None and Image is not None
Image.init()
