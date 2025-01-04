#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# default implementation using pycups
import sys
import os
import time
import string
import tempfile
from subprocess import PIPE, Popen
import shlex
from threading import Lock
from typing import Any
from collections.abc import Callable, Iterable
from cups import Connection  # @UnresolvedImport

from xpra.common import DEFAULT_XDG_DATA_DIRS, noop
from xpra.os_util import OSX
from xpra.util.str_fn import bytestostr
from xpra.util.parsing import parse_simple_dict
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.log import Logger

log = Logger("printing")

SIMULATE_PRINT_FAILURE = envint("XPRA_SIMULATE_PRINT_FAILURE")

RAW_MODE = envbool("XPRA_PRINTER_RAW", False)
GENERIC = envbool("XPRA_PRINTERS_GENERIC", True)
FORWARDER_TMPDIR = os.environ.get("XPRA_FORWARDER_TMPDIR", tempfile.gettempdir())
# the mimetype to use for clients that do not specify one
# (older clients just assumed postscript)
DEFAULT_MIMETYPE = os.environ.get("XPRA_PRINTER_DEFAULT_MIMETYPE", "application/pdf")

LPADMIN = "lpadmin"
LPINFO = "lpinfo"
ADD_OPTIONS = ["-E", "-o printer-is-shared=false", "-u allow:$USER"]

FORWARDER_BACKEND = "xpraforwarder"

SKIPPED_PRINTERS = os.environ.get("XPRA_SKIPPED_PRINTERS", "Cups-PDF").split(",")
CUPS_OPTIONS_WHITELIST = os.environ.get("XPRA_CUPS_OPTIONS_WHITELIST", "Resolution,PageSize").split(",")

# PRINTER_PREFIX = "Xpra:"
ADD_LOCAL_PRINTERS = envbool("XPRA_ADD_LOCAL_PRINTERS", False)
PRINTER_PREFIX = ""
if ADD_LOCAL_PRINTERS:
    # this prevents problems where we end up deleting local printers!
    PRINTER_PREFIX = "Xpra:"
PRINTER_PREFIX = os.environ.get("XPRA_PRINTER_PREFIX", PRINTER_PREFIX)

DEFAULT_CUPS_DBUS = int(not OSX)
CUPS_DBUS = envint("XPRA_CUPS_DBUS", DEFAULT_CUPS_DBUS)
POLLING_DELAY = envint("XPRA_CUPS_POLLING_DELAY", 60)
log("pycups settings: DEFAULT_CUPS_DBUS=%s, CUPS_DBUS=%s, POLLING_DELAY=%s",
    DEFAULT_CUPS_DBUS, CUPS_DBUS, POLLING_DELAY)
log("pycups settings: PRINTER_PREFIX=%s, ADD_LOCAL_PRINTERS=%s",
    PRINTER_PREFIX, ADD_LOCAL_PRINTERS)
log("pycups settings: FORWARDER_TMPDIR=%s", FORWARDER_TMPDIR)
log("pycups settings: SKIPPED_PRINTERS=%s", SKIPPED_PRINTERS)

MIMETYPE_TO_PRINTER = {
    "application/postscript": "Generic PostScript Printer",
    "application/pdf": "Generic PDF Printer",
}
MIMETYPE_TO_PPD = {
    "application/postscript": "CUPS-PDF.ppd",
    "application/pdf": "Generic-PDF_Printer-PDF.ppd",
}

dco = os.environ.get("XPRA_DEFAULT_CUPS_OPTIONS", "fit-to-page=True")
DEFAULT_CUPS_OPTIONS = parse_simple_dict(dco)
log("DEFAULT_CUPS_OPTIONS=%s", DEFAULT_CUPS_OPTIONS)


# allows us to inject the lpadmin and lpinfo commands from the config file
def set_lpadmin_command(lpadmin: str) -> None:
    global LPADMIN
    LPADMIN = lpadmin


def set_add_printer_options(options: list[str]) -> None:
    global ADD_OPTIONS
    ADD_OPTIONS = options


def set_lpinfo_command(lpinfo: str) -> None:
    global LPINFO
    LPINFO = lpinfo


def find_ppd_file(short_name: str, filename: str) -> str:
    ev = os.environ.get(f"XPRA_{short_name}_PPD")
    if ev and os.path.exists(ev):
        log("using environment override for %s ppd file: %s", short_name, ev)
        return ev
    paths = []
    for p in os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS).split(":"):
        if os.path.exists(p) and os.path.isdir(p):
            paths.append(os.path.join(p, "cups", "model"))  # used on Fedora and others
            paths.append(os.path.join(p, "ppd", "cups-pdf"))  # used on Fedora and others
            paths.append(os.path.join(p, "ppd", "cupsfilters"))
    log("find ppd file: paths=%s", paths)
    for p in paths:
        f = os.path.join(p, filename)
        if os.path.exists(f) and os.path.isfile(f):
            return f
    log("cannot find %s in %s", filename, paths)
    return ""


def get_lpinfo_drv(make_and_model: str) -> str:
    if not LPINFO:
        log.error("Error: lpinfo command is not defined")
        return ""
    command = shlex.split(LPINFO) + ["--make-and-model", make_and_model, "-m"]
    log("get_lpinfo_drv(%s) command=%s", make_and_model, command)
    try:
        proc = Popen(command, stdout=PIPE, stderr=PIPE, start_new_session=True, universal_newlines=True)
    except Exception as e:
        log("get_lp_info_drv(%s) lpinfo command %s failed", make_and_model, command, exc_info=True)
        log.error("Error: lpinfo command failed to run")
        log.estr(e)
        log.error(" command used: '%s'", " ".join(command))
        return ""
    # use the global child reaper to make sure this doesn't end up as a zombie
    from xpra.util.child_reaper import getChildReaper
    cr = getChildReaper()
    cr.add_process(proc, "lpinfo", command, ignore=True, forget=True)
    from xpra.util.thread import start_thread

    def watch_lpinfo() -> None:
        # give it 15 seconds to run:
        for _ in range(15):
            if proc.poll() is not None:
                return  # finished already
            time.sleep(1)
        if proc.poll() is not None:
            return
        log.warn("Warning: lpinfo command is taking too long,")
        log.warn(" is the cups server running?")
        try:
            proc.terminate()
        except Exception as e:
            log("%s.terminate()", proc, exc_info=True)
            log.error("Error: failed to terminate lpinfo command")
            log.estr(e)

    start_thread(watch_lpinfo, "lpinfo watcher", daemon=True)
    out, err = proc.communicate()
    if proc.wait() != 0:
        log.warn("Warning: lpinfo command failed and returned %s", proc.returncode)
        log.warn(" command used: '%s'", " ".join(command))
        return ""
    log("lpinfo out=%r", out)
    log("lpinfo err=%r", err)
    if err:
        log.warn("Warning: lpinfo command produced some warnings:")
        log.warn(" %r", err)
    for line in out.splitlines():
        if line.startswith("drv://"):
            return line.split(" ")[0]
    return ""


UNPROBED_PRINTER_DEFS: dict[str, list[str]] = {}


def add_printer_def(mimetype: str, definition: str) -> None:
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


PRINTER_DEF: dict[str, list[str]] | None = None
PRINTER_DEF_LOCK = Lock()


def get_printer_definitions() -> dict[str, list[str]]:
    global PRINTER_DEF
    with PRINTER_DEF_LOCK:
        if PRINTER_DEF is not None:
            return PRINTER_DEF
        log("get_printer_definitions() UNPROBED_PRINTER_DEFS=%s, GENERIC=%s", UNPROBED_PRINTER_DEFS, GENERIC)
        from xpra.platform.printing import get_mimetypes
        mimetypes = get_mimetypes()
        # first add the user-supplied definitions:
        PRINTER_DEF = UNPROBED_PRINTER_DEFS.copy()
        # raw mode if supported:
        if RAW_MODE:
            PRINTER_DEF["raw"] = ["-o", "raw"]
        # now probe for generic printers via lpinfo:
        if GENERIC:
            for mt in mimetypes:
                if mt in PRINTER_DEF:
                    continue  # we have a pre-defined one already
                x = MIMETYPE_TO_PRINTER.get(mt)
                if not x:
                    log.warn("Warning: unknown mimetype '%s', cannot find printer definition", mt)
                    continue
                drv = get_lpinfo_drv(x)
                if drv:
                    # ie: ["-m", "drv:///sample.drv/generic.ppd"]
                    PRINTER_DEF[mt] = ["-m", drv]
        # fallback to locating ppd files:
        for mt in mimetypes:
            if mt in PRINTER_DEF:
                continue  # we have a generic or pre-defined one already
            x = MIMETYPE_TO_PPD.get(mt)
            if not x:
                log.warn("Warning: unknown mimetype '%s', cannot find corresponding PPD file", mt)
                continue
            f = find_ppd_file(mt.replace("application/", "").upper(), x)
            if f:
                # ie: ["-P", "/usr/share/cups/model/Generic-PDF_Printer-PDF.ppd"]
                PRINTER_DEF[mt] = ["-P", f]
        log("pycups settings: PRINTER_DEF=%s", PRINTER_DEF)
    return PRINTER_DEF


def get_printer_definition(mimetype: str) -> str:
    v = get_printer_definitions().get("application/%s" % mimetype)
    if not v:
        return ""
    if len(v) != 2:
        return ""
    if v[0] not in ("-m", "-P"):
        return ""
    return v[1]  # ie: /usr/share/ppd/cupsfilters/Generic-PDF_Printer-PDF.ppd


def exec_lpadmin(args: Iterable[str], success_cb: Callable = noop) -> None:
    # pylint: disable=import-outside-toplevel
    command = shlex.split(LPADMIN) + list(args)
    log("exec_lpadmin(%s) command=%s", args, command)
    proc = Popen(command, start_new_session=True)
    # use the global child reaper to make sure this doesn't end up as a zombie
    from xpra.util.child_reaper import getChildReaper
    cr = getChildReaper()

    def check_returncode(_proc_cb) -> None:
        returncode = proc.poll()
        log("returncode(%s)=%s", command, returncode)
        if returncode != 0:
            log.warn("lpadmin failed and returned error code: %s", returncode)
            from xpra.platform.info import get_username
            log.warn(" verify that user '%s' has all the required permissions", get_username())
            log.warn(" for running: '%s'", LPADMIN)
            log.warn(" full command: %s", " ".join(f"{x!r}" for x in command))
        else:
            success_cb()

    cr.add_process(proc, "lpadmin", command, ignore=True, forget=True, callback=check_returncode)
    if proc.poll() not in (None, 0):
        raise RuntimeError(f"lpadmin command {command!r} failed and returned {proc.poll()}")


def sanitize_name(name: str) -> str:
    name = name.replace(" ", "-")
    valid_chars = f"-_.:{string.ascii_letters}{string.digits}"
    return ''.join(c for c in name if c in valid_chars)


def add_printer(name: str, options: typedict, info: str, location: str,
                attributes: dict, success_cb: Callable = noop) -> None:
    log("add_printer%s", (name, options, info, location, attributes, success_cb))
    mimetypes = options.strtupleget("mimetypes", (DEFAULT_MIMETYPE,))
    if not mimetypes:
        log.error(f"Error: no mimetypes specified for printer {name!r}")
        return
    xpra_printer_name = PRINTER_PREFIX + sanitize_name(name)
    if xpra_printer_name in get_all_printers():
        log.warn(f"Warning: not adding duplicate printer {name!r}")
        return
    # find a matching definition:
    mimetype, printer_def = None, None
    defs = get_printer_definitions()
    for mt in mimetypes:
        printer_def = defs.get(mt)
        if printer_def:
            log("using printer definition '%s' for %s", printer_def, mt)
            # ie: printer_def = ["-P", "/path/to/CUPS-PDF.ppd"]
            mimetype = mt
            attributes["mimetype"] = mimetype
            break
    if not printer_def:
        log.error("Error: cannot add printer '%s':", name)
        log.error(" the printing system does not support %s", " or ".join(mimetypes))
        return
    from urllib.parse import urlencode  # pylint: disable=import-outside-toplevel
    command = [
        "-p", xpra_printer_name,
        "-v", FORWARDER_BACKEND + ":" + FORWARDER_TMPDIR + "?" + urlencode(attributes),
        "-D", info,
        "-L", location,
    ]
    if ADD_OPTIONS:
        # ie: ["-E", "-o printer-is-shared=false", "-u allow:$USER"]
        for opt in ADD_OPTIONS:
            parts = shlex.split(opt)  # ie: "-u allow:$USER" -> ["-u", "allow:$USER"]
            for part in parts:  # ie: "allow:$USER"
                command.append(os.path.expandvars(part))
    command += printer_def
    # add attributes:
    log("pycups_printing adding printer: %s", command)
    exec_lpadmin(command, success_cb=success_cb)


def remove_printer(name: str) -> None:
    log("remove_printer(%s)", name)
    exec_lpadmin(["-x", PRINTER_PREFIX + sanitize_name(name)])


dbus_init = None
printers_modified_callback: Callable | None = None
DBUS_PATH = "/com/redhat/PrinterSpooler"
DBUS_IFACE = "com.redhat.PrinterSpooler"


def handle_dbus_signal(*args) -> None:
    log("handle_dbus_signal(%s) printers_modified_callback=%s", args, printers_modified_callback)
    if printers_modified_callback:
        printers_modified_callback()


def init_dbus_listener() -> bool:
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
        except ImportError as e:
            log.warn("Warning: cannot watch for printer device changes,")
            log.warn(" the dbus bindings seem to be missing:")
            log.warn(" %s", e)
            dbus_init = False
        except Exception:
            if OSX:
                log("no dbus on osx")
            else:
                log.error("failed to initialize dbus cups event listener", exc_info=True)
            dbus_init = False
    return bool(dbus_init)


def check_printers() -> None:
    # we don't actually check anything here and just
    # fire the callback every time, relying in client_base
    # to notice that nothing has changed and avoid sending the same printers to the server
    log("check_printers() printers_modified_callback=%s", printers_modified_callback)
    if printers_modified_callback:
        printers_modified_callback()
    schedule_polling_timer()


_polling_timer = 0


def schedule_polling_timer() -> None:
    # fallback to polling:
    cancel_polling_timer()
    from threading import Timer
    global _polling_timer
    _polling_timer = Timer(POLLING_DELAY, check_printers)
    _polling_timer.start()
    log("schedule_polling_timer() timer=%s", _polling_timer)


def cancel_polling_timer() -> None:
    global _polling_timer
    pt = _polling_timer
    log("cancel_polling_timer() timer=%s", pt)
    if pt:
        try:
            _polling_timer = 0
            pt.cancel()
        except Exception:
            log("error cancelling polling timer %s", pt, exc_info=True)


def init_printing(callback=noop) -> None:
    global printers_modified_callback
    log("init_printing(%s) printers_modified_callback=%s", callback, printers_modified_callback)
    printers_modified_callback = callback
    if not init_dbus_listener():
        log("init_printing(%s) will use polling", callback)
        schedule_polling_timer()


def cleanup_printing() -> None:
    cancel_polling_timer()


def get_printers() -> dict[str, dict]:
    all_printers = get_all_printers()
    return {k: v for k, v in all_printers.items() if k not in SKIPPED_PRINTERS}


def get_all_printers() -> dict[str, dict]:
    conn = Connection()
    printers = conn.getPrinters()
    log("pycups.get_all_printers()=%s", printers)
    return printers


def get_default_printer() -> str:
    conn = Connection()
    return conn.getDefault() or ""


def get_printer_attributes(name: str) -> dict[str, str | Iterable[str]]:
    conn = Connection()
    return conn.getPrinterAttributes(name)


def print_files(printer: str, filenames: Iterable[str], title: str, options: dict) -> int:
    if printer not in get_printers():
        raise ValueError("invalid printer: '%s'" % printer)
    log("pycups.print_files%s", (printer, filenames, title, options))
    actual_options = DEFAULT_CUPS_OPTIONS.copy()
    s = bytestostr
    used_options = {s(k): s(v) for k, v in options.items() if s(k) in CUPS_OPTIONS_WHITELIST}
    unused_options = {s(k): s(v) for k, v in options.items() if s(k) not in CUPS_OPTIONS_WHITELIST}
    log("used options=%s", used_options)
    log("unused options=%s", unused_options)
    actual_options.update(used_options)
    if SIMULATE_PRINT_FAILURE:
        log.warn("Warning: simulating print failure")
        conn = None
        printpid = -1
    else:
        conn = Connection()
        log("calling printFiles on %s", conn)
        printpid = conn.printFiles(printer, list(filenames), title, actual_options)
    if printpid <= 0:
        log.error(f"Error: pycups printing on {printer!r} failed for files")
        for f in filenames:
            log.error(" %s", f)
        log.error(" using cups server connection: %s", conn)
        if actual_options:
            log.error(" printer options:")
            for k, v in actual_options.items():
                log.error("  %-24s : %s", k, v)
    else:
        log("pycups %s.printFiles%s=%s", conn, (printer, filenames, title, actual_options), printpid)
    return printpid


def printing_finished(printpid: int) -> bool:
    conn = Connection()
    f = conn.getJobs().get(printpid, None) is None
    log("pycups.printing_finished(%s)=%s", printpid, f)
    return f


PRINTER_STATE: dict[int, str] = {
    3: "idle",
    4: "printing",
    5: "stopped",
}


def get_info() -> dict[str, Any]:
    from xpra.platform.printing import get_mimetypes, DEFAULT_MIMETYPES
    return {
        "mimetypes": {
            "": get_mimetypes(),
            "default": DEFAULT_MIMETYPES,
            "printers": MIMETYPE_TO_PRINTER,
            "ppd": MIMETYPE_TO_PPD,
        },
        "mimetype": {
            "default": DEFAULT_MIMETYPE,
        },
        "simulate-failure": SIMULATE_PRINT_FAILURE,
        "raw-mode": RAW_MODE,
        "generic": GENERIC,
        "tmpdir": FORWARDER_TMPDIR,
        "lpadmin": LPADMIN,
        "lpinfo": LPINFO,
        "forwarder": FORWARDER_BACKEND,
        "skipped-printers": SKIPPED_PRINTERS,
        "add-local-printers": ADD_LOCAL_PRINTERS,
        "printer-prefix": PRINTER_PREFIX,
        "cups-dbus": {
            "": CUPS_DBUS,
            "default": DEFAULT_CUPS_DBUS,
            "poll-delay": POLLING_DELAY,
        },
        "cups.default-options": DEFAULT_CUPS_OPTIONS,
        "printers": {
            "": get_printer_definitions(),
            "predefined": UNPROBED_PRINTER_DEFS,
        },
    }


def main() -> None:
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("PyCUPS Printing"):
        enable_color()
        consume_verbose_argv(sys.argv, "printing")
        defs = get_printer_definitions()
        log.info("validation: %s", bool(defs))
        log.info("")
        log.info("printer definitions:")
        for k, v in defs.items():
            log.info("* %-32s: %s", k, v)
        log.info("")
        log.info("local printers:")
        try:
            printers = get_printers()
        except RuntimeError as e:
            log.error("Error accessing the printing system")
            log.estr(e)
        else:
            for k, d in get_all_printers().items():
                log.info("* %s%s", k, [" (NOT EXPORTED)", ""][int(k in printers)])
                for pk, pv in d.items():
                    if pk == "printer-state" and pv in PRINTER_STATE:
                        pv = "%s (%s)" % (pv, PRINTER_STATE.get(pv))
                    log.info("    %-32s: %s", pk, pv)


if __name__ == "__main__":
    main()
