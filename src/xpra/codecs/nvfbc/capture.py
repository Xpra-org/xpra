# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time
import os.path

from xpra.util import envbool
from xpra.log import Logger, add_debug_category
log = Logger("encoder", "nvfbc")

USE_NVFBC_CUDA = envbool("XPRA_NVFBC_CUDA", False)


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
        add_debug_category("nvfbc")

    from xpra.platform import program_context
    with program_context("NvFBC-Capture", "NvFBC Capture"):
        from xpra.platform.paths import get_download_dir
        from xpra.util import print_nested_dict
        from xpra.os_util import WIN32, LINUX
        if WIN32:
            from xpra.codecs.nvfbc import fbc_capture_win as fbc_capture      #@UnresolvedImport @UnusedImport
        elif LINUX:
            from xpra.codecs.nvfbc import fbc_capture_linux as fbc_capture      #@UnresolvedImport @Reimport
        else:
            raise Exception("nvfbc is not support on %s" % sys.platform)
        fbc_capture.init_module()
        log.info("Info:")
        print_nested_dict(fbc_capture.get_info(), print_fn=log.info)
        log.info("Status:")
        print_nested_dict(fbc_capture.get_status(), print_fn=log.info)
        try:
            log("creating test capture class")
            if USE_NVFBC_CUDA:
                c = fbc_capture.NvFBC_CUDACapture()     #@UndefinedVariable
            else:
                c = fbc_capture.NvFBC_SysCapture()      #@UndefinedVariable
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
            filename = os.path.join(os.path.expanduser(get_download_dir()), "screenshot-%s-%i.png" % (rgb_format, time.time()))
            img.save(filename, "png")
            log.info("screenshot saved to %s", filename)
            return 0
        except Exception as e:
            log.warn("Error: not saved %s:", rgb_format)
            log.warn(" %s", e)
            return 1


if __name__ == "__main__":
    sys.exit(main())
