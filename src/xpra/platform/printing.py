# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

#default implementation uses pycups
from xpra.log import Logger
log = Logger("printing")

def err(*args):
    log.error(*args)

def get_printers():
    return {}

def print_files(printer, filenames, title, options):
    raise Exception("no print implementation available")

def printing_finished(printpid):
    return True
    

#default implementation uses pycups:
from xpra.platform import platform_import
try:
    from xpra.platform.pycups_printing import get_printers, print_files, printing_finished
    assert get_printers and print_files and printing_finished
except Exception as e:
    #ignore the error on win32:
    if not sys.platform.startswith("win"):
        err("cannot use pycups for printing: %s", e)

platform_import(globals(), "printing", False,
                "get_printers",
                "print_files",
                "printing_finished")


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category
        add_debug_category("util")

    from xpra.util import nonl, pver
    def print_dict(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %s : %s" % (k.ljust(32), nonl(pver(v))))
    from xpra.platform import init, clean
    try:
        init("Printing", "Printing")
        print_dict(get_printers())
    finally:
        clean()

if __name__ == "__main__":
    main()
