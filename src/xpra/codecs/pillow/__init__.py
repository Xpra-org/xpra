# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import logging
PIL_DEBUG = os.environ.get("XPRA_PIL_DEBUG", "0")=="1"
if PIL_DEBUG:
    from xpra.log import Logger
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
PIL_VERSION = PIL.PILLOW_VERSION
if hasattr(Image, "DEBUG"):
    #for older versions (pre 3.0), use Image.DEBUG flag:
    Image.DEBUG = int(PIL_DEBUG)
Image.init()
