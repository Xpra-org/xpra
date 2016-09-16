# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import logging
from xpra.util import envbool
from xpra.log import Logger

PIL_DEBUG = envbool("XPRA_PIL_DEBUG", False)
if PIL_DEBUG:
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
assert PIL is not None and Image is not None, "failed to load Pillow"
try:
    PIL_VERSION = PIL.PILLOW_VERSION
except:
    PIL_VERSION = Image.VERSION
if hasattr(Image, "DEBUG"):
    #for older versions (pre 3.0), use Image.DEBUG flag:
    Image.DEBUG = int(PIL_DEBUG)
if PIL_VERSION<'2':
    log = Logger("encoder", "pillow")
    log.warn("Warning: your version of Python Imaging Library is well out of date")
    log.warn(" version %s is not supported, your mileage may vary", PIL_VERSION)
Image.init()
