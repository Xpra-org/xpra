# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#default implementation using pycups
import sys
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
ADD_LOCAL_PRINTERS = os.environ.get("XPRA_ADD_LOCAL_PRINTERS", "0")=="1"
PRINTER_PREFIX = ""
if ADD_LOCAL_PRINTERS:
    #this prevents problems where we end up deleting local printers!
    PRINTER_PREFIX = "Xpra:"
PRINTER_PREFIX = os.environ.get("XPRA_PRINTER_PREFIX", PRINTER_PREFIX)

DEFAULT_CUPS_DBUS = str(int(not sys.platform.startswith("darwin")))
CUPS_DBUS = os.environ.get("XPRA_CUPS_DBUS", DEFAULT_CUPS_DBUS)=="1"
POLLING_DELAY = int(os.environ.get("XPRA_CUPS_POLLING_DELAY", "60"))
log("pycups settings: DEFAULT_CUPS_DBUS=%s, CUPS_DBUS=%s, POLLING_DELAY=%s", DEFAULT_CUPS_DBUS, CUPS_DBUS, POLLING_DELAY)
log("pycups settings: PRINTER_PREFIX=%s, ADD_LOCAL_PRINTERS=%s", PRINTER_PREFIX, ADD_LOCAL_PRINTERS)
log("pycups settings: PPD_FILE=%s, ALLOW=%s", PPD_FILE, ALLOW)
log("pycups settings: FORWARDER_TMPDIR=%s", FORWARDER_TMPDIR)


#allows us to inject the lpadmin command
def set_lpadmin_command(lpadmin):
    global LPADMIN
    LPADMIN = lpadmin

def validate_setup():
    #very simple check
    if PPD_FILE and (not os.path.exists(PPD_FILE) or not os.path.isfile(PPD_FILE)):
        log.warn("Printer forwarding cannot be enabled, the PPD file '%s' is missing", PPD_FILE)
        return False
    return True


def exec_lpadmin(args):
    command = shlex.split(LPADMIN)+args
    def preexec():
        os.setsid()
    log("exec_lpadmin(%s) command=%s", args, command)
    proc = subprocess.Popen(command, stdin=None, stdout=None, stderr=None, shell=False, close_fds=True, preexec_fn=preexec)
    #use the global child reaper to make sure this doesn't end up as a zombie
    from xpra.child_reaper import getChildReaper
    cr = getChildReaper()
    def check_returncode(proc):
        returncode = proc.returncode
        if returncode is not None and returncode!=0:
            log.warn("lpadmin failed and returned error code: %s", returncode)
            log.warn("you may want to check that this user has the required permissions for using this command")
    cr.add_process(proc, "lpadmin", command, ignore=True, forget=True, callback=check_returncode)
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


dbus_init = None
printers_modified_callback = None
DBUS_PATH="/com/redhat/PrinterSpooler"
DBUS_IFACE="com.redhat.PrinterSpooler"
def handle_dbus_signal(*args):
    global printers_modified_callback
    log("handle_dbus_signal(%s) printers_modified_callback=%s", args, printers_modified_callback)
    printers_modified_callback()

def init_dbus_listener():
    if not CUPS_DBUS:
        return False
    global dbus_init
    log("init_dbus_listener() dbus_init=%s", dbus_init)
    if dbus_init is None:
        try:
            from xpra.x11.dbus_common import init_system_bus
            system_bus = init_system_bus()
            log("system bus: %s", system_bus)
            sig_match = system_bus.add_signal_receiver(handle_dbus_signal, path=DBUS_PATH, dbus_interface=DBUS_IFACE)
            log("system_bus.add_signal_receiver(..)=%s", sig_match)
            dbus_init = True
        except Exception:
            if sys.platform.startswith("darwin"):
                log("no dbus on osx")
            else:
                log.error("failed to initialize dbus cups event listener", exc_info=True)
            dbus_init = False
    return dbus_init

def check_printers():
    global printers_modified_callback
    #we don't actually check anything here and just
    #fire the callback every time, relying in client_base
    #to notice that nothing has changed and avoid sending the same printers to the server
    log("check_printers() printers_modified_callback=%s", printers_modified_callback)
    printers_modified_callback()
    schedule_polling_timer()

_polling_timer = None
def schedule_polling_timer():
    #fallback to polling:
    import threading
    global _polling_timer
    _polling_timer = threading.Timer(POLLING_DELAY, check_printers)
    _polling_timer.start()

def init_printing(callback):
    global printers_modified_callback
    log("init_printing(%s) printers_modified_callback=%s", callback, printers_modified_callback)
    printers_modified_callback = callback
    if not init_dbus_listener():
        log("init_printing(%s) will use polling", callback)
        schedule_polling_timer()

def cleanup_printing():
    global _polling_timer
    try:
        _polling_timer.cancel()
        _polling_timer = None
    except:
        pass


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
