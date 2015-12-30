#!/usr/bin/env python
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
from threading import Lock

from xpra.util import engs
from xpra.log import Logger
log = Logger("printing")


SIMULATE_PRINT_FAILURE = os.environ.get("XPRA_SIMULATE_PRINT_FAILURE", "0")=="1"

ALLOW = os.environ.get("XPRA_PRINTER_ALLOW", getpass.getuser())
RAW_MODE = os.environ.get("XPRA_PRINTER_RAW", "0")=="1"
GENERIC = os.environ.get("XPRA_PRINTERS_GENERIC", "1")=="1"
FORWARDER_TMPDIR = os.environ.get("XPRA_FORWARDER_TMPDIR", os.environ.get("TMPDIR", "/tmp"))
#the mimetype to use for clients that do not specify one
#(older clients just assumed postscript)
DEFAULT_MIMETYPE = os.environ.get("XPRA_PRINTER_DEFAULT_MIMETYPE", "application/postscript")

LPADMIN = "lpadmin"
LPINFO = "lpinfo"
FORWARDER_BACKEND = "xpraforwarder"

SKIPPED_PRINTERS = os.environ.get("XPRA_SKIPPED_PRINTERS", "Cups-PDF").split(",")

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
log("pycups settings: FORWARDER_TMPDIR=%s", FORWARDER_TMPDIR)
log("pycups settings: SKIPPED_PRINTERS=%s", SKIPPED_PRINTERS)

MIMETYPE_TO_PRINTER = {"application/postscript" : "Generic PostScript Printer",
                       "application/pdf"        : "Generic PDF Printer"}
MIMETYPE_TO_PPD = {"application/postscript"     : "CUPS-PDF.ppd",
                   "application/pdf"            : "Generic-PDF_Printer-PDF.ppd"}


DEFAULT_CUPS_OPTIONS = {}
dco = os.environ.get("XPRA_DEFAULT_CUPS_OPTIONS", "fit-to-page=True")
if dco:
    for opt in dco.split(","):
        opt = opt.strip(" ")
        parts = opt.split("=", 1)
        if len(parts)!=2:
            log.warn("Warning: invalid cups option: '%s'", opt)
            continue
        #is it a boolean?
        k,v = parts
        DEFAULT_CUPS_OPTIONS[k] = v
    log("DEFAULT_CUPS_OPTIONS=%s", DEFAULT_CUPS_OPTIONS)


#allows us to inject the lpadmin and lpinfo commands from the config file
def set_lpadmin_command(lpadmin):
    global LPADMIN
    LPADMIN = lpadmin

def set_lpinfo_command(lpinfo):
    global LPINFO
    LPINFO = lpinfo


def find_ppd_file(short_name, filename):
    ev = os.environ.get("XPRA_%s_PPD" % short_name)
    if ev and os.path.exists(ev):
        log("using environment override for %s ppd file: %s", short_name, ev)
        return ev
    paths = ["/usr/share/cups/model",           #used on Fedora and others
             "/usr/share/ppd/cups-pdf",         #used on Ubuntu
             "/usr/share/ppd/cupsfilters",
             "/usr/local/share/cups/model",     #install from source with /usr/local prefix
             #if your distro uses something else, please file a bug so we can add it
            ]
    for p in paths:
        f = os.path.join(p, filename)
        if os.path.exists(f):
            return f
    log("cannot find %s in %s", filename, paths)
    return None


def get_lpinfo_drv(make_and_model):
    command = shlex.split(LPINFO)+["--make-and-model", make_and_model, "-m"]
    def preexec():
        os.setsid()
    log("get_lpinfo_drv(%s) command=%s", make_and_model, command)
    proc = subprocess.Popen(command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, close_fds=True, preexec_fn=preexec)
    #use the global child reaper to make sure this doesn't end up as a zombie
    from xpra.child_reaper import getChildReaper
    from xpra.util import nonl
    cr = getChildReaper()
    cr.add_process(proc, "lpinfo", command, ignore=True, forget=True)
    out, err = proc.communicate()
    if proc.wait()!=0:
        log.warn("Warning: lpinfo command failed and returned %s", proc.returncode)
        log.warn(" command used: '%s'", command)
        return None
    if sys.version_info[0]>=3:
        try:
            out = out.decode()
        except:
            out = str(out)
    log("lpinfo out=%s", nonl(out))
    log("lpinfo err=%s", nonl(err))
    if err:
        log.warn("Warning: lpinfo command produced some warnings:")
        log.warn(" '%s'", nonl(err))
    for line in out.splitlines():
        if line.startswith("drv://"):
            return line.split(" ")[0]
    return None


UNPROBED_PRINTER_DEFS = {}
def add_printer_def(mimetype, definition):
    if definition.startswith("drv://"):
        UNPROBED_PRINTER_DEFS[mimetype] = ["-m", definition]
    elif definition.lower().endswith("ppd"):
        if os.path.exists(definition):
            UNPROBED_PRINTER_DEFS[mimetype] = ["-P", definition]
        else:
            log.warn("Warning: ppd file '%s' does not exist", definition)
    else:
        log.warn("Warning: invalid printer definition for %s:", mimetype)
        log.warn(" '%s' is not a valid driver or ppd file", definition)


PRINTER_DEF = None
PRINTER_DEF_LOCK = Lock()
def get_printer_definitions():
    global PRINTER_DEF, PRINTER_DEF_LOCK, UNPROBED_PRINTER_DEFS, MIMETYPE_TO_PRINTER
    with PRINTER_DEF_LOCK:
        if PRINTER_DEF is not None:
            return PRINTER_DEF
        log("get_printer_definitions() UNPROBED_PRINTER_DEFS=%s, GENERIC=%s", UNPROBED_PRINTER_DEFS, GENERIC)
        from xpra.platform.printing import get_mimetypes
        mimetypes = get_mimetypes()
        #first add the user-supplied definitions:
        PRINTER_DEF = UNPROBED_PRINTER_DEFS.copy()
        #raw mode if supported:
        if RAW_MODE:
            PRINTER_DEF["raw"] = ["-o", "raw"]
        #now probe for generic printers via lpinfo:
        if GENERIC:
            for mt in mimetypes:
                if mt in PRINTER_DEF:
                    continue    #we have a pre-defined one already
                x = MIMETYPE_TO_PRINTER.get(mt)
                if not x:
                    log.warn("Warning: unknown mimetype '%s', cannot find printer definition", mt)
                    continue
                drv = get_lpinfo_drv(x)
                if drv:
                    #ie: ["-m", "drv:///sample.drv/generic.ppd"]
                    PRINTER_DEF[mt] = ["-m", drv]
        #fallback to locating ppd files:
        for mt in mimetypes:
            if mt in PRINTER_DEF:
                continue        #we have a generic or pre-defined one already
            x = MIMETYPE_TO_PPD.get(mt)
            if not x:
                log.warn("Warning: unknown mimetype '%s', cannot find corresponding PPD file", mt)
                continue
            f = find_ppd_file(mt.replace("application/", "").upper(), x)
            if f:
                #ie: ["-P", "/usr/share/cups/model/Generic-PDF_Printer-PDF.ppd"]
                PRINTER_DEF[mt] = ["-P", f]
        log("pycups settings: PRINTER_DEF=%s", PRINTER_DEF)
    return PRINTER_DEF


def validate_setup():
    #very simple check: at least one ppd file exists
    defs = get_printer_definitions()
    if not defs:
        log.warn("Warning: no printer definitions found, cannot enable printing")
        return False
    #check for SELinux
    try:
        if os.path.exists("/sys/fs/selinux"):
            log("SELinux is present")
            from xpra.os_util import load_binary_file
            enforce = load_binary_file("/sys/fs/selinux/enforce")
            log("SELinux enforce=%s", enforce)
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
    if not mimetypes:
        log.error("Error: no mimetypes specified for printer %s", name)
        return
    #find a matching definition:
    mimetype, printer_def = None, None
    defs = get_printer_definitions()
    for mt in mimetypes:
        printer_def = defs.get(mt)
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
               "-u", "allow:%s" % ALLOW]+printer_def
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
    if printers_modified_callback:
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

def init_printing(callback=None):
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
    all_printers = get_all_printers()
    return dict((k,v) for k,v in all_printers.items() if k not in SKIPPED_PRINTERS)

def get_all_printers():
    conn = cups.Connection()
    printers = conn.getPrinters()
    log("pycups.get_all_printers()=%s", printers)
    return printers

def get_default_printer():
    conn = cups.Connection()
    return conn.getDefault()

def get_printer_attributes(name):
    conn = cups.Connection()
    return conn.getPrinterAttributes(name)


def print_files(printer, filenames, title, options):
    if printer not in get_printers():
        raise Exception("invalid printer: '%s'" % printer)
    log("pycups.print_files%s", (printer, filenames, title, options))
    actual_options = DEFAULT_CUPS_OPTIONS.copy()
    actual_options.update(options)
    if SIMULATE_PRINT_FAILURE:
        log.warn("Warning: simulating print failure")
        conn = None
        printpid = -1
    else:
        conn = cups.Connection()
        printpid = conn.printFiles(printer, filenames, title, actual_options)
    if printpid<=0:
        log.error("Error: pycups printing on '%s' failed for file%s", printer, engs(filenames))
        for f in filenames:
            log.error(" %s", f)
        log.error(" using cups server connection: %s", conn)
        if actual_options:
            log.error(" printer options:")
            for k,v in actual_options.items():
                log.error("  %-24s : %s", k, v)
    else:
        log("pycups %s.printFiles%s=%s", conn, (printer, filenames, title, actual_options), printpid)
    return printpid

def printing_finished(printpid):
    conn = cups.Connection()
    f = conn.getJobs().get(printpid, None) is None
    log("pycups.printing_finished(%s)=%s", printpid, f)
    return f


PRINTER_STATE = {
                3   : "idle",
                4   : "printing",
                5   : "stopped",
                 }


def get_info():
    from xpra.platform.printing import get_mimetypes, DEFAULT_MIMETYPES
    return {
            "mimetypes"         : get_mimetypes(),
            "mimetypes.default" : DEFAULT_MIMETYPES,
            "simulate-failure"  : SIMULATE_PRINT_FAILURE,
            "allow-user"        : ALLOW,
            "raw-mode"          : RAW_MODE,
            "generic"           : GENERIC,
            "tmpdir"            : FORWARDER_TMPDIR,
            "mimetype.default"  : DEFAULT_MIMETYPE,
            "lpadmin"           : LPADMIN,
            "lpinfo"            : LPINFO,
            "forwarder"         : FORWARDER_BACKEND,
            "skipped-printers"  : SKIPPED_PRINTERS,
            "add-local-printers": ADD_LOCAL_PRINTERS,
            "printer-prefix"    : PRINTER_PREFIX,
            "cups-dbus.default" : DEFAULT_CUPS_DBUS,
            "cups-dbus"         : CUPS_DBUS,
            "cups-dbus.poll-delay" : POLLING_DELAY,
            "mimetypes.printers": MIMETYPE_TO_PRINTER,
            "mimetypes.ppd"     : MIMETYPE_TO_PPD,
            "cups.default-options"  : DEFAULT_CUPS_OPTIONS,
            "printers.predefined" : UNPROBED_PRINTER_DEFS,
            "printers"          : get_printer_definitions(),
            }


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

    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("PyCUPS Printing"):
        enable_color()
        validate_setup()
        log.info("")
        log.info("printer definitions:")
        for k,v in get_printer_definitions().items():
            log.info("* %-32s: %s", k, v)
        log.info("")
        log.info("local printers:")
        printers = get_printers()
        for k,d in get_all_printers().items():
            log.info("* %s%s", k, [" (NOT EXPORTED)", ""][int(k in printers)])
            for pk, pv in d.items():
                if pk=="printer-state" and pv in PRINTER_STATE:
                    pv = "%s (%s)" % (pv, PRINTER_STATE.get(pv))
                log.info("    %-32s: %s", pk, pv)


if __name__ == "__main__":
    main()
