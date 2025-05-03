# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any

from xpra.platform import platform_import


class NOGLContext:
    def __init__(self, _alpha=False):
        raise NotImplementedError()


GLContext = NOGLContext


def check_support() -> dict[str, Any]:
    if not GLContext:
        raise RuntimeError("no GLContext available")
    return GLContext().check_support()  # pylint: disable=not-callable


platform_import(globals(), "gl_context", False, "GLContext", "check_support")


def main() -> int:
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    from xpra.util.str_fn import print_nested_dict
    from xpra.log import enable_color, Logger, consume_verbose_argv
    with program_context("OpenGL Native Context Check"):
        gui_init()
        enable_color()
        consume_verbose_argv(sys.argv, "opengl")
        log = Logger("opengl")
        if not GLContext:
            log.error("Error: no GLContext available on %s", sys.platform)
            return 1
        try:
            props = check_support()
        except Exception:
            log.error("%s().check_support()", exc_info=True)
            return 1
        log.info("")
        log.info("OpenGL properties:")
        print_nested_dict(props)
        return 0


if __name__ == "__main__":
    sys.exit(main())
