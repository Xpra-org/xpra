# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time
import os.path

from xpra.util import envbool
from xpra.os_util import memoryview_to_bytes, WIN32, LINUX
from xpra.log import Logger, add_debug_category

log = Logger("encoder", "nvfbc")

USE_NVFBC_CUDA = envbool("XPRA_NVFBC_CUDA", False)


def get_capture_module():
    if WIN32:
        from xpra.codecs.nvidia.nvfbc import fbc_capture_win   #@UnresolvedImport @UnusedImport
        return fbc_capture_win
    if LINUX:
        from xpra.codecs.nvidia.nvfbc import fbc_capture_linux #@UnresolvedImport @Reimport
        return fbc_capture_linux
    return None

def get_capture_instance(cuda=USE_NVFBC_CUDA):
    fbc_module = get_capture_module()
    if not fbc_module:
        return None
    fbc_module.init_nvfbc_library()
    if cuda:
        return fbc_module.NvFBC_CUDACapture()     #@UndefinedVariable
    return fbc_module.NvFBC_SysCapture()      #@UndefinedVariable


def main(argv):
    if "-v" in argv or "--verbose" in argv:
        log.enable_debug()
        add_debug_category("nvfbc")

    from xpra.platform import program_context
    with program_context("NvFBC-Capture", "NvFBC Capture"):
        from xpra.platform.paths import get_download_dir
        from xpra.util import print_nested_dict
        fbc_capture = get_capture_module()
        if not fbc_capture:
            raise RuntimeError("nvfbc is not supported on this platform")
        fbc_capture.init_module()
        if WIN32:
            try:
                if "enable" in argv[1:]:
                    fbc_capture.set_enabled(True)
                    log.info("nvfbc capture enabled")
                elif "disable" in argv[1:]:
                    fbc_capture.set_enabled(False)
                    log.info("nvfbc capture disabled")
            except Exception as e:
                log(f"set_enabled for {argv} failed", exc_info=True)
                log.error("Error: cannot enable or disable NvFBC:")
                log.estr(e)
                log.error(" you may need to run this command as administrator")
                return 1
        log.info("Info:")
        print_nested_dict(fbc_capture.get_info(), print_fn=log.info)
        log.info("Status:")
        print_nested_dict(fbc_capture.get_status(), print_fn=log.info)
        try:
            log("creating test capture instance")
            c = get_capture_instance()
            log("Capture=%s", c)
            c.init_context()
            assert c.refresh()
        except Exception as e:
            log("Capture()", exc_info=True)
            log.error("Error: failed to create test capture instance:")
            log.estr(e)
            return 1
        image = c.get_image()
        assert image
        from PIL import Image
        w = image.get_width()
        h = image.get_height()
        pixels = memoryview_to_bytes(image.get_pixels())
        stride = image.get_rowstride()
        rgb_format = image.get_pixel_format()
        try:
            img = Image.frombuffer("RGB", (w, h), pixels, "raw", rgb_format, stride, 1)
            filename = os.path.join(os.path.expanduser(get_download_dir()),
                                    "screenshot-%s-%i.png" % (rgb_format, time.time()))
            img.save(filename, "png")
            log.info("screenshot saved to %s", filename)
            return 0
        except Exception as e:
            log.warn("Error: failed to save %s:", rgb_format)
            log.warn(" %s", e)
            return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
