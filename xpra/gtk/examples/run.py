# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from importlib import import_module

from xpra.util.str_fn import csv
from xpra.exit_codes import ExitValue
from xpra.scripts.config import InitException, InitInfo

ALL_EXAMPLES = (
    "bell", "clicks",
    "colors-gradient", "colors-plain", "colors",
    "cursors",
    "file-chooser",
    "fontrendering",
    "grabs",
    "header-bar",
    "initiate-moveresize",
    "text-entry",
    "transparent-colors",
    "transparent-window",
    "tray",
    "window-focus", "window-geometry-hints",
    "window-opacity", "window-overrideredirect",
    "window-states", "window-title",
    "window-transient",
    "opengl",
    "view-keyboard", "view-clipboard",
)


def run_example(args) -> ExitValue:
    if not args or args[0] not in ALL_EXAMPLES:
        raise InitInfo(f"usage: xpra example testname\nvalid names: {csv(sorted(ALL_EXAMPLES))}")
    example = args[0]
    classname = example.replace("-", "_")
    modpath = f"xpra.gtk.dialogs.{classname}" if example in ("view-keyboard", "view-clipboard")\
        else f"xpra.gtk.examples.{classname}"
    try:
        module = import_module(modpath)
    except ImportError as e:
        raise InitException(f"failed to import example {classname}: {e}") from None
    return module.main(args)


def main(argv: list[str]) -> int:
    from xpra.platform import program_context
    with program_context("xpra-example", "Xpra Example"):
        return run_example(argv[1:])


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
