# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import PIL                      #@UnresolvedImport
from PIL import Image           #@UnresolvedImport
assert PIL is not None and Image is not None, "failed to load Pillow"
PIL_VERSION = PIL.PILLOW_VERSION

import os
if os.environ.get("XPRA_PIL_DEBUG", "0")=="1":
    from xpra.log import Logger
    log = Logger("encoder", "pillow")
    log.info("enabling PIL.DEBUG")
    Image.DEBUG = 1
Image.init()
