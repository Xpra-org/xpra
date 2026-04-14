#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.platform import platform_import


def get_backends() -> list[Callable]:
    return []


platform_import(globals(), "notification", False, "get_backends")


def main(argv: list[str]) -> int:
    from xpra.log import consume_verbose_argv
    from xpra.platform import program_context
    with program_context("Notifications", "Notifications"):
        consume_verbose_argv(argv, "util", "notify")
        backends = get_backends()
        print("found %i backends:", len(backends))
        for backend in backends:
            print(backend)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
