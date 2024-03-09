#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from importlib import import_module


def main(argv) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.util import print_nested_dict, numpy_import_lock
    from xpra.platform import program_context
    with program_context("CUDA-Info", "CUDA Info"):
        from xpra.log import Logger, enable_color
        enable_color()
        log = Logger("cuda")
        if "-v" in argv or "--verbose" in argv:
            log.enable_debug()
        with numpy_import_lock:
            for component in (
                "xpra.codecs",
                "xpra.codecs.nvidia",
                "pycuda",
                "pycuda.driver",
                "xpra.codecs.nvidia.cuda.context",
            ):
                try:
                    module = import_module(component)
                except ImportError as e:
                    log.error(f"Error: the `{component}` component failed to load")
                    log.estr(e)
                    if component == "pycuda.driver":
                        log.error(" this usually happens if the CUDA library is not installed or not found")
                    return 1
                else:
                    log.debug(f"loaded {component}={module}")
        from xpra.codecs.nvidia import cuda_context
        pycuda_info = cuda_context.get_pycuda_info()
        log.info("pycuda_info")
        print_nested_dict(pycuda_info, print_fn=log.info)
        log.info("cuda_info")
        print_nested_dict(cuda_context.get_cuda_info(), print_fn=log.info)
        log.info("preferences:")
        print_nested_dict(cuda_context.get_prefs(), print_fn=log.info)
        log.info("device automatically selected:")
        log.info(" %s", cuda_context.device_info(cuda_context.select_device()[1]))
    return 0


if __name__ == "__main__":
    v = main(sys.argv)
    sys.exit(v)
