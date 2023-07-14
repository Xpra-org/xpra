#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2014-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Dict, Any, Optional, List

#default implementation uses pycups
from xpra.platform import platform_import
from xpra.util import envbool, print_nested_dict
from xpra.os_util import WIN32
from xpra.log import Logger

log = Logger("printing")

RAW_MODE = envbool("XPRA_PRINTER_RAW", False)


def get_printers() -> Dict[str,Any]:
    return {}

def get_printer_attributes(_name:str) -> List:
    return []

def get_default_printer() -> str:
    return ""

def print_files(printer:Dict, filenames, title:str, options):
    raise RuntimeError("no print implementation available")

def printing_finished(_printpid) -> bool:
    return True

def init_printing(printers_modified_callback=None) -> None:     #pylint: disable=unused-argument
    """ overridden in platform code """

def cleanup_printing() -> None:
    """ overridden in platform code """


DEFAULT_MIMETYPES = ["application/pdf", "application/postscript"]

MIMETYPES : Optional[List[str]] = None
def get_mimetypes():
    global MIMETYPES
    if MIMETYPES is None:
        v = os.environ.get("XPRA_PRINTING_MIMETYPES", )
        if v is not None:
            MIMETYPES = v.split(",")
        else:
            MIMETYPES = DEFAULT_MIMETYPES
        if RAW_MODE:
            MIMETYPES.append("raw")
        #make it easier to test different mimetypes:
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


def get_info() -> Dict[str,Any]:
    return default_get_info()

def default_get_info() -> Dict[str,Any]:
    return {
            "mimetypes" :   {
                ""         : get_mimetypes(),
                "default"  : DEFAULT_MIMETYPES,
                }
            }


#default implementation uses pycups:
if not WIN32:
    #pycups is not available on win32
    try:
        from xpra.platform.pycups_printing import (
            get_printers,
            print_files,
            printing_finished,
            init_printing,
            cleanup_printing,
            get_info,
            )
        assert get_printers and print_files and printing_finished and init_printing, cleanup_printing   # type: ignore[truthy-function]
    except Exception as pycupse:
        log("cannot load pycups", exc_info=True)
        log.warn("Warning: printer forwarding disabled:")
        log.warn(" %s", pycupse)

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
    if "-v" in argv or "--verbose" in argv:
        from xpra.log import add_debug_category, enable_debug_for
        add_debug_category("printing")
        enable_debug_for("printing")
        try:
            argv.remove("-v")
        except ValueError:
            pass
        try:
            argv.remove("--verbose")
        except ValueError:
            pass

    from xpra.util import nonl, pver
    def dump_dict(d):
        pk = None
        try:
            for pk,pv in d.items():
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
    from xpra.util import csv
    with program_context("Printing", "Printing"):
        enable_color()
        try:
            init_printing()
        except Exception as e:
            print("Error: initializing the printing tool")
            print(f" {e}")
        if len(argv)<=1:
            dump_printers(get_printers())
            print("")
            dump_info(get_info())
            return 0
        printers = get_printers()
        if not printers:
            print("Cannot print: no printers found")
            return 1
        if len(argv)==2:
            filename = argv[1]
            if not os.path.exists(filename):
                print(f"Cannot print file {filename!r}: file does not exist")
                return 1
            printer = get_default_printer()     #pylint: disable=assignment-from-none
            if not printer:
                printer = list(printers.keys())[0]
                if len(printers)>1:
                    print("More than one printer found: "+csv(printer.keys()))
            print(f"Using printer {printer!r}")
            filenames = [filename]
        if len(argv)>2:
            printer = argv[1]
            if printer not in printers:
                print(f"Invalid printer {printer!r}")
                return 1
            filenames = argv[2:]
            for filename in filenames:
                if not os.path.exists(filename):
                    print(f"File {filename!r} does not exist")
                    return 1
        print("Printing: "+csv(filenames))
        print_files(printer, filenames, "Print Command", {})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
