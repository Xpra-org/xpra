#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from collections.abc import Iterable

# default implementation uses pycups
from xpra.common import noop
from xpra.platform import platform_import
from xpra.util.str_fn import print_nested_dict, pver
from xpra.util.env import envbool
from xpra.log import Logger, consume_verbose_argv

log = Logger("printing")

RAW_MODE = envbool("XPRA_PRINTER_RAW", False)


def get_printers() -> dict[str, Any]:
    return {}


def get_printer_attributes(_name: str) -> list:
    return []


def get_default_printer() -> str:
    return ""


def print_files(printer: str, filenames: Iterable[str], title: str, options: dict):
    raise RuntimeError("no print implementation available")


def printing_finished(_printpid) -> bool:
    return True


def init_printing(printers_modified_callback=noop) -> None:  # pylint: disable=unused-argument
    """ overridden in platform code """


def cleanup_printing() -> None:
    """ overridden in platform code """


DEFAULT_MIMETYPES = ["application/pdf", "application/postscript"]

MIMETYPES: list[str] | None = None


def get_mimetypes() -> list[str]:
    global MIMETYPES
    if MIMETYPES is None:
        v = os.environ.get("XPRA_PRINTING_MIMETYPES", )
        if v is not None:
            MIMETYPES = v.split(",")
        else:
            MIMETYPES = DEFAULT_MIMETYPES
        if RAW_MODE:
            MIMETYPES.append("raw")
        # make it easier to test different mimetypes:
        PREFERRED_MIMETYPE = os.environ.get("XPRA_PRINTING_PREFERRED_MIMETYPE")
        if PREFERRED_MIMETYPE:
            if PREFERRED_MIMETYPE in MIMETYPES:
                MIMETYPES.remove(PREFERRED_MIMETYPE)
                MIMETYPES.insert(0, PREFERRED_MIMETYPE)
            else:
                log.warn("Warning: ignoring invalid preferred printing mimetype: %s", PREFERRED_MIMETYPE)
                log.warn(" allowed mimetypes: %s", MIMETYPES)
    log("get_mimetype()=%s", MIMETYPES)
    return MIMETYPES


def get_info() -> dict[str, Any]:
    return default_get_info()


def default_get_info() -> dict[str, Any]:
    return {
        "mimetypes": {
            "": get_mimetypes(),
            "default": DEFAULT_MIMETYPES,
        }
    }


platform_import(globals(), "printing", False,
                "init_printing",
                "cleanup_printing",
                "get_printers",
                "get_default_printer",
                "print_files",
                "printing_finished",
                "get_info",
                "DEFAULT_MIMETYPES")


def main(argv) -> int:
    # pylint: disable=import-outside-toplevel
    consume_verbose_argv(argv, "printing")
    from xpra.util.str_fn import nonl

    def dump_dict(d):
        pk = None
        try:
            for pk, pv in d.items():
                try:
                    if isinstance(pv, bytes):
                        sv = pv.decode("utf8")
                    else:
                        sv = nonl(pver(pv))
                except Exception:
                    sv = repr(pv)
                print(f"        {pk:32} : {sv}")
        except Exception as e:
            print(f"        error on {pk}: {e}")
            print(f"        raw attributes: {d}")

    def dump_info(d):
        print("System Configuration:")
        print_nested_dict(d)

    def dump_printers(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("Printers:")
            print(f"* {k}")
            dump_dict(v)
            attr = get_printer_attributes(k)
            if attr:
                print(" attributes:")
                for a in attr:
                    print(f"        {a}")

    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.util.str_fn import csv
    with program_context("Printing", "Printing"):
        enable_color()
        try:
            init_printing()
        except Exception as e:
            print("Error: initializing the printing tool")
            print(f" {e}")
        if len(argv) <= 1:
            dump_printers(get_printers())
            print("")
            dump_info(get_info())
            return 0
        printers = get_printers()
        if not printers:
            print("Cannot print: no printers found")
            return 1
        if len(argv) == 2:
            filename = argv[1]
            if not os.path.exists(filename):
                print(f"Cannot print file {filename!r}: file does not exist")
                return 1
            printer = get_default_printer()  # pylint: disable=assignment-from-none
            if not printer:
                printer = list(printers.keys())[0]
                if len(printers) > 1:
                    print("More than one printer found: " + csv(printer.keys()))
            print(f"Using printer {printer!r}")
            filenames = [filename]
        if len(argv) > 2:
            printer = argv[1]
            if printer not in printers:
                print(f"Invalid printer {printer!r}")
                return 1
            filenames = argv[2:]
            for filename in filenames:
                if not os.path.exists(filename):
                    print(f"File {filename!r} does not exist")
                    return 1
        print("Printing: " + csv(filenames))
        print_files(printer, filenames, "Print Command", {})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
