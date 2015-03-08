# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#default implementation using pycups
import os
import cups
import subprocess
import shlex
import getpass
import urllib


from xpra.log import Logger
log = Logger("printing")

ALLOW = os.environ.get("XPRA_PRINTER_ALLOW", getpass.getuser())
LPADMIN = "lpadmin"
FORWARDER_BACKEND = "xpraforwarder"
FORWARDER_TMPDIR = os.environ.get("XPRA_FORWARDER_TMPDIR", os.environ.get("TMPDIR", "/tmp"))
PPD_FILE = os.environ.get("XPRA_PPD_FILE", "/usr/share/cups/model/CUPS-PDF.ppd")

#PRINTER_PREFIX = "Xpra:"
PRINTER_PREFIX = os.environ.get("XPRA_PRINTER_PREFIX", "")


#allows us to inject the lpadmin command
def set_lpadmin_command(lpadmin):
    global LPADMIN
    LPADMIN = lpadmin


def exec_lpadmin(args):
    command = shlex.split(LPADMIN)+args
    def preexec():
        os.setsid()
    proc = subprocess.Popen(command, stdin=None, stdout=None, stderr=None, shell=False, close_fds=True, preexec_fn=preexec)
    #use the global child reaper to make sure this doesn't end up as a zombie
    from xpra.child_reaper import getChildReaper
    cr = getChildReaper()
    cr.add_process(proc, "lpadmin", command, ignore=True, forget=True)
    assert proc.poll() in (None, 0)


def sanitize_name(name):
    import string
    name = name.replace(" ", "-")
    valid_chars = "-_.:%s%s" % (string.ascii_letters, string.digits)
    return ''.join(c for c in name if c in valid_chars)

def add_printer(name, options, info, location, attributes={}):
    log("add_printer(%s, %s)", name, options)
    command = ["-p", PRINTER_PREFIX+sanitize_name(name),
               "-E",
               "-v", FORWARDER_BACKEND+":"+FORWARDER_TMPDIR+"?"+urllib.urlencode(attributes),
               "-D", info,
               "-L", location,
               "-o", "printer-is-shared=false",
               "-u", "allow:%s" % ALLOW]
    if PPD_FILE:
        command += ["-P", PPD_FILE]
    else:
        command += ["-o", "raw"]
    log("pycups_printing adding printer: %s", command)
    exec_lpadmin(command)

def remove_printer(name):
    log("remove_printer(%s)", name)
    exec_lpadmin(["-x", PRINTER_PREFIX+sanitize_name(name)])


dbus_init = False
printers_modified_callback = None
DBUS_PATH="/com/redhat/PrinterSpooler"
DBUS_IFACE="com.redhat.PrinterSpooler"
def handle_dbus_signal(*args):
    global printers_modified_callback
    log.info("handle_dbus_signal(%s) printers_modified_callback=%s", args, printers_modified_callback)
    printers_modified_callback()

def init_dbus_listener():
    global dbus_init
    log("init_dbus_listener() dbus_init=%s", dbus_init)
    if dbus_init:
        return
    dbus_init = True
    try:
        from xpra.x11.dbus_common import  init_system_bus
        system_bus = init_system_bus()
        log("system bus: %s", system_bus)
        sig_match = system_bus.add_signal_receiver(handle_dbus_signal, path=DBUS_PATH, dbus_interface=DBUS_IFACE)
        log("system_bus.add_signal_receiver(..)=%s", sig_match)
    except Exception:
        log.error("failed to initialize dbus cups event listener", exc_info=True)

def on_printers_modified(callback):
    global printers_modified_callback
    log("on_printers_modified(%s) printers_modified_callback=%s", callback, printers_modified_callback)
    printers_modified_callback = callback
    init_dbus_listener()


def get_printers():
    conn = cups.Connection()
    printers = conn.getPrinters()
    log("pycups.get_printers()=%s", printers)
    return printers

def print_files(printer, filenames, title, options):
    if printer not in get_printers():
        raise Exception("invalid printer: '%s'" % printer)
    log("pycups.print_files%s", (printer, filenames, title, options))
    conn = cups.Connection()
    printpid = conn.printFiles(printer, filenames, title, options)
    log("pycups.print_files%s=%s", (printer, filenames, title, options), printpid)
    assert printpid>0, "printing failed and returned job id %s" % printpid
    return printpid

def printing_finished(printpid):
    conn = cups.Connection()
    f = conn.getJobs().get(printpid, None) is None
    log("pycups.printing_finished(%s)=%s", printpid, f)
    return f
