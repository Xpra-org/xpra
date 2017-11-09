# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

GLContext = None

def check_support():
    return GLContext().check_support()


from xpra.platform import platform_import
platform_import(globals(), "gl_context", False, "GLContext", "check_support")


def main():
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    from xpra.util import print_nested_dict
    from xpra.log import enable_color, Logger
    with program_context("OpenGL Native Context Check"):
        gui_init()
        enable_color()
        log = Logger("opengl")
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        if verbose:
            log.enable_debug()
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
