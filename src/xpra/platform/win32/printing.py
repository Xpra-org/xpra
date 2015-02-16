# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("printing")

import win32print       #@UnresolvedImport
import win32api         #@UnresolvedImport


def get_printers():
    printers = {}
    #default_printer = win32print.GetDefaultPrinter()
    for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 1):
        flags, desc, name, comment = p
        log("found printer: %s, %s, %s, %s", flags, desc, name, comment)
        #phandle = win32print.OpenPrinter(name)
        #win32print.ClosePrinter(phandle)
        printers[name] = {"printer-info"            : desc,
                          "printer-make-and-model"  : comment}
    log("printers=%s", printers)
    return printers

def print_files(printer, filenames, title, options):
    #AcroRd32.exe /N /T PdfFile PrinterName [ PrinterDriver [ PrinterPort ] ]
    for f in filenames:
        #win32api.ShellExecute(0, "print", f, '/d:"%s"' % printer, ".", 0)
        #win32api.ShellExecute(0, "printto", f, '"%s"' % printer, ".", 0)
        win32api.ShellExecute(0, "print", f, '/d:"%s"' % printer, ".", 0)
