# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time
import os.path

from xpra.log import Logger
log = Logger("encoder", "nvfbc")

def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    from xpra.platform import program_context
    with program_context("NvFBC-Capture", "NvFBC Capture"):
        from xpra.platform.paths import get_download_dir
        from xpra.util import print_nested_dict
        from xpra.codecs.nvfbc.fbc_capture import NvFBC_SysCapture, init_nvfbc_library, get_info, get_status #@UnresolvedImport
        init_nvfbc_library()
        log.info("Info:")
        print_nested_dict(get_info(), print_fn=log.info)
        log.info("Status:")
        print_nested_dict(get_status(), print_fn=log.info)
        try:
            log("creating test capture class")
            c = NvFBC_SysCapture()
            log("Capture=%s", c)
            c.init_context()
        except Exception as e:
            log("Capture()", exc_info=True)
            log.error("Error: failed to create test capture instance:")
            log.error(" %s", e)
            return 1
        image = c.get_image()
        assert image
        from PIL import Image
        w = image.get_width()
        h = image.get_height()
        pixels = image.get_pixels()
        stride = image.get_rowstride()
        rgb_format = image.get_pixel_format()
        try:
            img = Image.frombuffer("RGB", (w, h), pixels, "raw", rgb_format, stride, 1)
            filename = os.path.join(get_download_dir(), "screenshot-%s-%i.png" % (rgb_format, time.time()))
            img.save(filename, "png")
            log.info("screenshot saved to %s", filename)
            return 0
        except Exception as e:
            log.warn("not saved %s: %s", rgb_format, e)
            return 1


if __name__ == "__main__":
    sys.exit(main())
