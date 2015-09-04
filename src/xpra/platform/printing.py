#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os

#default implementation uses pycups
from xpra.log import Logger
log = Logger("printing")

MIMETYPES = [
             "application/pdf",
             "application/postscript",
            ]
#make it easier to test different mimetypes:
PREFERRED_MIMETYPE = os.environ.get("XPRA_PRINTING_PREFERRED_MIMETYPE")
if os.environ.get("XPRA_PRINTER_RAW", "0")=="1":
    MIMETYPES.append("raw")
if PREFERRED_MIMETYPE:
    if PREFERRED_MIMETYPE in MIMETYPES:
        MIMETYPES.remove(PREFERRED_MIMETYPE)
        MIMETYPES.insert(0, PREFERRED_MIMETYPE)
    else:
        log.warn("Warning: ignoring invalid preferred printing mimetype: %s", PREFERRED_MIMETYPE)
        log.warn(" allowed mimetypes: %s", MIMETYPES)


def err(*args):
    log.error(*args)

def get_printers():
    return {}

def print_files(printer, filenames, title, options):
    raise Exception("no print implementation available")

def printing_finished(printpid):
    return True

def init_printing(printers_modified_callback=None):
    pass

def cleanup_printing():
    pass

#default implementation uses pycups:
from xpra.platform import platform_import
try:
    from xpra.platform.pycups_printing import get_printers, print_files, printing_finished, init_printing, cleanup_printing
    assert get_printers and print_files and printing_finished and init_printing, cleanup_printing
except Exception as e:
    #ignore the error on win32:
    if not sys.platform.startswith("win"):
        err("Error: printing disabled:")
        err(" %s", e)

platform_import(globals(), "printing", False,
                "init_printing",
                "cleanup_printing",
                "get_printers",
                "print_files",
                "printing_finished",
                "MIMETYPES")


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category, enable_debug_for
        add_debug_category("printing")
        enable_debug_for("printing")
        try:
            sys.argv.remove("-v")
        except:
            pass
        try:
            sys.argv.remove("--verbose")
        except:
            pass

    from xpra.util import nonl, pver
    def print_dict(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %s : %s" % (k.ljust(32), nonl(pver(v))))
    from xpra.platform import init, clean
    from xpra.log import enable_color
    try:
        init("Printing", "Printing")
        enable_color()
        if len(sys.argv)<3:
            print_dict(get_printers())
        else:
            printer = sys.argv[1]
            print_files(printer, sys.argv[2:], "Print Command", {})
    finally:
        clean()


if __name__ == "__main__":
    main()
