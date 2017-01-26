#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os

#default implementation uses pycups
from xpra.util import envbool, print_nested_dict
from xpra.os_util import WIN32
from xpra.log import Logger
log = Logger("printing")

RAW_MODE = envbool("XPRA_PRINTER_RAW", False)

py3 = sys.version >= '3'
if py3:
    unicode = str       #@ReservedAssignment


def err(*args, **kwargs):
    log.error(*args, **kwargs)

def get_printers():
    return {}

def get_printer_attributes(name):
    return []

def get_default_printer():
    return None

def print_files(printer, filenames, title, options):
    raise Exception("no print implementation available")

def printing_finished(printpid):
    return True

def init_printing(printers_modified_callback=None):
    pass

def cleanup_printing():
    pass


DEFAULT_MIMETYPES = ["application/pdf", "application/postscript"]

MIMETYPES = None
def get_mimetypes():
    global MIMETYPES, DEFAULT_MIMETYPES
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


def get_info():
    return default_get_info

def default_get_info():
    return {
            "mimetypes" :   {
                ""         : get_mimetypes(),
                "default"  : DEFAULT_MIMETYPES,
                }
            }


#default implementation uses pycups:
from xpra.platform import platform_import
if not WIN32:
    #pycups is not available on win32
    try:
        from xpra.platform.pycups_printing import get_printers, print_files, printing_finished, init_printing, cleanup_printing, get_info
        assert get_printers and print_files and printing_finished and init_printing, cleanup_printing
    except Exception as e:
        err("Error: printing disabled:")
        err(" %s", e)

platform_import(globals(), "printing", False,
                "init_printing",
                "cleanup_printing",
                "get_printers",
                "get_default_printer",
                "print_files",
                "printing_finished",
                "get_info",
                "DEFAULT_MIMETYPES")


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
    def dump_dict(d):
        pk = None
        try:
            for pk,pv in d.items():
                try:
                    if type(pv)==unicode:
                        sv = pv.encode("utf8")
                    else:
                        sv = nonl(pver(pv))
                except Exception as e:
                    sv = repr(pv)
                print("        %s : %s" % (pk.ljust(32), sv))
        except Exception as e:
            print("        error on %s: %s" % (pk, e))
            print("        raw attributes: " % d)
    def dump_info(d):
        print("System Configuration:")
        print_nested_dict(d)
    def dump_printers(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("Printers:")
            print("* %s" % k)
            dump_dict(v)
            attr = get_printer_attributes(k)
            if attr:
                print(" attributes:")
                for a in attr:
                    print("        %s" % a)
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.util import csv
    with program_context("Printing", "Printing"):
        enable_color()
        try:
            init_printing()
        except Exception as e:
            print("Error: initializing the printing tool")
            print(" %s" % e)
        if len(sys.argv)<=1:
            dump_printers(get_printers())
            print("")
            dump_info(get_info())
            return 0
        printers = get_printers()
        if len(printers)==0:
            print("Cannot print: no printers found")
            return 1
        if len(sys.argv)==2:
            filename = sys.argv[1]
            if not os.path.exists(filename):
                print("Cannot print file '%s': file does not exist" % filename)
                return 1
            printer = get_default_printer()
            if not printer:
                printer = printers.keys()[0]
                if len(printers)>1:
                    print("More than one printer found: %s", csv(printer.keys()))
            print("Using printer '%s'" % printer)
            filenames = [filename]
        if len(sys.argv)>2:
            printer = sys.argv[1]
            if printer not in printers:
                print("Invalid printer '%s'" % printer)
                return 1
            filenames = sys.argv[2:]
            for filename in filenames:
                if not os.path.exists(filename):
                    print("File '%s' does not exist" % filename)
                    return 1
        print("Printing: %s" % csv(filenames))
        print_files(printer, filenames, "Print Command", {})
        return 0


if __name__ == "__main__":
    sys.exit(main())
