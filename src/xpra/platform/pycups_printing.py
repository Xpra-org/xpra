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
RAW_MODE = os.environ.get("XPRA_PRINTER_RAW", "0")=="1"
FORWARDER_TMPDIR = os.environ.get("XPRA_FORWARDER_TMPDIR", os.environ.get("TMPDIR", "/tmp"))
#the mimetype to use for clients that do not specify one
#(older clients just assumed postscript)
DEFAULT_MIMETYPE = os.environ.get("XPRA_PRINTER_DEFAULT_MIMETYPE", "application/postscript")

LPADMIN = "lpadmin"
FORWARDER_BACKEND = "xpraforwarder"

def find_ppd_file(short_name, filename):
    ev = os.environ.get("XPRA_%s_PPD" % short_name)
    if ev and os.path.exists(ev):
        log("using environment override for %s ppd file: %s", short_name, ev)
        return ev
    paths = ["/usr/share/cups/model",           #used on Fedora and others
              "/usr/share/ppd/cups-pdf",        #used on Ubuntu
              "/usr/share/ppd/cupsfilters",
              "/usr/local/share/cups/model",    #install from source with /usr/local prefix
              #if your distro uses something else, please file a bug so we can add it
            ]
    for p in paths:
        f = os.path.join(p, filename)
        if os.path.exists(f):
            return f
    log("cannot find %s in %s", filename, paths)
    return None


PRINTER_DEF = {}
if RAW_MODE:
    PRINTER_DEF["raw"] = ["-o", "raw"]
for mt,x in {"application/postscript"   : "CUPS-PDF.ppd",
             "application/pdf"          : "Generic-PDF_Printer-PDF.ppd"}.items():
    f = find_ppd_file(mt.replace("application/", "").upper(), x)
    if f:
        PRINTER_DEF[mt] = ["-P", f]

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
log("pycups settings: ALLOW=%s", ALLOW)
log("pycups settings: PRINTER_DEF=%s", PRINTER_DEF)
log("pycups settings: FORWARDER_TMPDIR=%s", FORWARDER_TMPDIR)


#allows us to inject the lpadmin command
def set_lpadmin_command(lpadmin):
    global LPADMIN
    LPADMIN = lpadmin

def validate_setup():
    #very simple check: at least one ppd file exists
    if not PRINTER_DEF:
        log.warn("No PPD files found, cannot enable printing")
        return False
    #check for SELinux
    try:
        if os.path.exists("/sys/fs/selinux"):
            log("SELinux is present")
            from xpra.os_util import load_binary_file
            enforce = load_binary_file("/sys/fs/selinux/enforce")
            log("enforce=%s", enforce)
            if enforce=="1":
                log.warn("SELinux is running in enforcing mode")
                log.warn(" printer forwarding is unlikely to work without a policy")
            else:
                log("SELinux is present but not in enforcing mode")
    except Exception as e:
        log.error("Error checking for the presence of SELinux:")
        log.error(" %s", e)
    return True


def exec_lpadmin(args, success_cb=None):
    command = shlex.split(LPADMIN)+args
    def preexec():
        os.setsid()
    log("exec_lpadmin(%s) command=%s", args, command)
    proc = subprocess.Popen(command, stdin=None, stdout=None, stderr=None, shell=False, close_fds=True, preexec_fn=preexec)
    #use the global child reaper to make sure this doesn't end up as a zombie
    from xpra.child_reaper import getChildReaper
    cr = getChildReaper()
    def check_returncode(proc_cb):
        returncode = proc.poll()
        log("returncode(%s)=%s", command, returncode)
        if returncode!=0:
            log.warn("lpadmin failed and returned error code: %s", returncode)
            from xpra.platform import get_username
            log.warn(" verify that user '%s' has all the required permissions", get_username())
            log.warn(" for running: '%s'", LPADMIN)
        elif success_cb:
            success_cb()
    cr.add_process(proc, "lpadmin", command, ignore=True, forget=True, callback=check_returncode)
    if proc.poll() not in (None, 0):
        raise Exception("lpadmin command '%s' failed and returned %s" % (command, proc.poll()))


def sanitize_name(name):
    import string
    name = name.replace(" ", "-")
    valid_chars = "-_.:%s%s" % (string.ascii_letters, string.digits)
    return ''.join(c for c in name if c in valid_chars)

def add_printer(name, options, info, location, attributes={}, success_cb=None):
    log("add_printer%s", (name, options, info, location, attributes, success_cb))
    mimetypes = options.get("mimetypes", [DEFAULT_MIMETYPE])
    #find a matching definition:
    mimetype, printer_def = None, None
    for mt in mimetypes:
        printer_def = PRINTER_DEF.get(mt)
        if printer_def:
            log("using printer definition '%s' for %s", printer_def, mt)
            #ie: printer_def = ["-P", "/path/to/CUPS-PDF.ppd"]
            mimetype = mt
            attributes["mimetype"] = mimetype
            break
    if not printer_def:
        log.error("Error: cannot add printer '%s':", name)
        log.error(" the printing system does not support %s", " or ".join(mimetypes))
        return
    command = ["-p", PRINTER_PREFIX+sanitize_name(name),
               "-E",
               "-v", FORWARDER_BACKEND+":"+FORWARDER_TMPDIR+"?"+urllib.urlencode(attributes),
               "-D", info,
               "-L", location,
               "-o", "printer-is-shared=false",
               "-u", "allow:%s" % ALLOW]
    #add attributes:
    log("pycups_printing adding printer: %s", command)
    exec_lpadmin(command, success_cb=success_cb)

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
            from xpra.dbus.common import init_system_bus
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
    from threading import Timer
    global _polling_timer
    _polling_timer = Timer(POLLING_DELAY, check_printers)
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
