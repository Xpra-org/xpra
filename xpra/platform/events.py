#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Callable, Sequence

from xpra.platform import platform_import


EVENTS: Sequence[str] = ("suspend", "resume", )


def add_handler(event: str, handler: Callable) -> None:
    raise NotImplementedError


def remove_handler(event: str, handler: Callable) -> None:
    raise NotImplementedError


platform_import(globals(), "events", True, "add_handler", "remove_handler")


def main(argv: list[str]) -> int:
    from xpra.os_util import gi_import
    from xpra.platform import program_context, init
    from xpra.log import Logger, enable_color, consume_verbose_argv
    log = Logger("events")
    with program_context("Event-Listener"):
        enable_color()
        consume_verbose_argv(argv, "all")
        init()

        def handler(event: str, args):
            log.info(f"{event!r} {args}")

        for event in EVENTS:
            add_handler(event, handler)

        GLib = gi_import("GLib")
        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            pass
        for event in EVENTS:
            remove_handler(event, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
