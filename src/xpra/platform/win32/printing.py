# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("printing")

import os.path
import subprocess
from xpra.platform.win32 import constants as win32con
from xpra.util import csv, envint


#allows us to skip some printers we don't want to export
SKIPPED_PRINTERS = os.environ.get("XPRA_SKIPPED_PRINTERS", "Microsoft XPS Document Writer,Fax").split(",")


PRINTER_ENUM_VALUES = {
    "DEFAULT"       : 1,
    "LOCAL"         : 2,
    "CONNECTIONS"   : 4,
    "NAME"          : 8,
    "REMOTE"        : 16,
    "SHARED"        : 32,
    "NETWORK"       : 64,
    "EXPAND"        : 16384,
    "CONTAINER"     : 32768,
    "ICON1"         : 65536*1,
    "ICON2"         : 65536*2,
    "ICON3"         : 65536*3,
    "ICON4"         : 65536*4,
    "ICON5"         : 65536*5,
    "ICON6"         : 65536*6,
    "ICON7"         : 65536*7,
    "ICON8"         : 65536*8,
    }
PRINTER_ENUM_NAMES = dict((v,k) for k,v in PRINTER_ENUM_VALUES.items())
log("PRINTER_ENUM_VALUES: %s", PRINTER_ENUM_VALUES)

PRINTER_LEVEL = envint("XPRA_WIN32_PRINTER_LEVEL", 1)
#DEFAULT_PRINTER_FLAGS = "LOCAL"
DEFAULT_PRINTER_FLAGS = "LOCAL,SHARED+NETWORK+CONNECTIONS"
PRINTER_FLAGS = [x.strip() for x in os.environ.get("XPRA_WIN32_PRINTER_FLAGS", DEFAULT_PRINTER_FLAGS).split(",")]
log("PRINTER_FLAGS=%s", csv(PRINTER_FLAGS))
VALID_PRINTER_FLAGS = ("LOCAL", "SHARED", "CONNECTIONS", "NETWORK", "REMOTE")
PRINTER_ENUMS = []
for v in PRINTER_FLAGS:                     #ie: "SHARED+NETWORK+CONNECTIONS"
    flags = v.replace('|','+').split("+")   #ie: ["SHARED", "NETWORK", "CONNECTIONS"]
    values = []
    for flag in flags:                      #ie: "SHARED"
        if flag not in VALID_PRINTER_FLAGS:
            log.warn("Warning: the following printer flag is invalid and will be ignored: %s", flag)
        else:
            values.append(flag)             #ie: "SHARED"
    PRINTER_ENUMS.append(values)
log("PRINTER_ENUMS=%s", PRINTER_ENUMS)


#emulate pycups job id
JOB_ID = 0
PROCESSES = {}

GSVIEW_DIR = None
GSPRINT_EXE = None
GSWINXXC_EXE = None
printers_modified_callback = None
def init_printing(callback=None):
    global printers_modified_callback, GSVIEW_DIR, GSPRINT_EXE, GSWINXXC_EXE
    log("init_printing(%s) printers_modified_callback=%s", callback, printers_modified_callback)
    printers_modified_callback = callback
    #ensure we can find gsprint.exe in a subdirectory:
    from xpra.platform.paths import get_app_dir
    GSVIEW_DIR = os.path.join(get_app_dir(), "gsview")
    assert os.path.exists(GSVIEW_DIR) and os.path.isdir(GSVIEW_DIR), "cannot find gsview directory in '%s'" % GSVIEW_DIR
    GSPRINT_EXE = os.path.join(GSVIEW_DIR, "gsprint.exe")
    assert os.path.exists(GSPRINT_EXE), "cannot find gsprint.exe in '%s'" % GSVIEW_DIR
    for bits in (32, 64):
        GSWINXXC_EXE = os.path.join(GSVIEW_DIR, "gswin%sc.exe" % bits)
        if os.path.exists(GSWINXXC_EXE):
            break
    assert os.path.exists(GSWINXXC_EXE), "cannot find gswin??c.exe in '%s'" % GSVIEW_DIR
    try:
        init_winspool_listener()
    except Exception:
        log.error("Error: failed to register for print spooler changes", exc_info=True)

def init_winspool_listener():
    from xpra.platform.win32.win32_events import get_win32_event_listener
    get_win32_event_listener().add_event_callback(win32con.WM_DEVMODECHANGE, on_devmodechange)

def on_devmodechange(wParam, lParam):
    global printers_modified_callback
    log("on_devmodechange(%s, %s) printers_modified_callback=%s", wParam, lParam, printers_modified_callback)
    #from ctypes import c_wchar_p
    #name = c_wchar_p(lParam)
    #log("device changed: %s", name)
    if lParam>0 and printers_modified_callback:
        printers_modified_callback()


def EnumPrinters(flags, name=None, level=PRINTER_LEVEL):
    import ctypes
    from ctypes.wintypes import BYTE, DWORD, LPCWSTR

    winspool = ctypes.WinDLL('winspool.drv', use_last_error=True)
    msvcrt = ctypes.cdll.msvcrt

    class PRINTER_INFO(ctypes.Structure):
        _fields_ = [
            ("Flags", DWORD),
            ("pDescription", LPCWSTR),
            ("pName", LPCWSTR),
            ("pComment", LPCWSTR),
        ]

    # Invoke once with a NULL pointer to get buffer size.
    info = ctypes.POINTER(BYTE)()
    pcbNeeded = DWORD(0)
    pcReturned = DWORD(0)  # the number of PRINTER_INFO_1 structures retrieved
    r = winspool.EnumPrintersW(DWORD(flags), name, DWORD(level), ctypes.byref(info), DWORD(0), ctypes.byref(pcbNeeded), ctypes.byref(pcReturned))
    log("EnumPrintersW(..)=%i pcbNeeded=%i", r, pcbNeeded.value)
    if pcbNeeded.value<=0:
        log("EnumPrinters probe failed for flags=%i, level=%i, pcbNeeded=%i", flags, level, pcbNeeded.value)
        return []

    bufsize = pcbNeeded.value
    buf = msvcrt.malloc(bufsize)
    if buf==0:
        log.error("Error: cannot enumerate printers, malloc failed")
        return []

    r = winspool.EnumPrintersW(DWORD(flags), name, DWORD(level), buf, bufsize, ctypes.byref(pcbNeeded), ctypes.byref(pcReturned))
    log("EnumPrintersW(..)=%i pcReturned=%i", r, pcReturned.value)
    if r==0:
        log.error("Error: EnumPrinters failed")
        return []
    info = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO))
    printers = []
    for i in range(pcReturned.value):
        v = int(info[i].Flags), str(info[i].pDescription), str(info[i].pName), str(info[i].pComment)
        log("EnumPrintersW(..) [%i]=%s", i, v)
        printers.append(v)
    msvcrt.free(buf)
    return printers

def get_info():
    from xpra.platform.printing import default_get_info
    i = default_get_info()
    #win32 extras:
    i.update({
        "skipped-printers"      : SKIPPED_PRINTERS,
        "printer-level"         : PRINTER_LEVEL,
        "default-printer-flags" : DEFAULT_PRINTER_FLAGS,
        "printer-flags"         : PRINTER_FLAGS,
        "commands" : {
            "gsview"    : GSPRINT_EXE or "",
            "gswin"     : GSWINXXC_EXE or "",
            },
        })
    return i

def get_printers():
    global PRINTER_ENUMS, PRINTER_ENUM_VALUES, SKIPPED_PRINTERS, PRINTER_LEVEL, GSVIEW_DIR
    printers = {}
    if not GSVIEW_DIR:
        #without gsprint, we can't handle printing!
        log("get_printers() gsview is missing, not querying any printers")
        return printers
    #default_printer = GetDefaultPrinter()
    for penum in PRINTER_ENUMS:
        try:
            eprinters = []
            enum_values = [PRINTER_ENUM_VALUES.get(x, 0) for x in penum]
            enum_val = sum(enum_values)
            log("enum(%s)=%s=%s", penum, "+".join(str(x) for x in enum_values), enum_val)
            assert enum_val is not None, "invalid printer enum %s" % penum
            log("querying %s printers with level=%s", penum, PRINTER_LEVEL)
            for p in EnumPrinters(enum_val, None, PRINTER_LEVEL):
                flags, desc, name, comment = p
                if name in SKIPPED_PRINTERS:
                    log("skipped printer: %s, %s, %s, %s", flags, desc, name, comment)
                    continue
                if name in printers:
                    log("skipped duplicate printer: %s, %s, %s, %s", flags, desc, name, comment)
                    continue
                log("found printer: %s, %s, %s, %s", flags, desc, name, comment)
                #strip duplicated and empty strings from the description:
                desc_els = []
                [desc_els.append(x) for x in desc.split(",") if (x and not desc_els.count(x))]
                info = {"printer-info"            : ",".join(desc_els),
                        "type"                    : penum}
                if comment:
                    info["printer-make-and-model"] = comment
                printers[name] = info
                eprinters.append(name)
            log("%s printers: %s", penum, eprinters)
        except Exception as e:
            log.warn("Warning: failed to query %s printers: %s", penum, e)
            log("query error", exc_info=True)
    log("win32.get_printers()=%s", printers)
    return printers

def print_files(printer, filenames, title, options):
    log("win32.print_files%s", (printer, filenames, title, options))
    global JOB_ID, PROCESSES, GSVIEW_DIR, GSPRINT_EXE, GSWINXXC_EXE
    assert GSVIEW_DIR, "cannot print files without gsprint!"
    processes = []
    for filename in filenames:
        #command = ["C:\\Program Files\\Xpra\\gsview\\gsprint.exe"]
        command = [GSPRINT_EXE, "-ghostscript", GSWINXXC_EXE, "-colour"]
        if printer:
            command += ["-printer", printer]
        command += [filename]
        log("print command: %s", command)
        #add gsview directory
        PATH = os.environ.get("PATH")
        os.environ["PATH"] = str(PATH+";"+GSVIEW_DIR)
        log("environment: %s", os.environ)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.Popen(command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=GSVIEW_DIR, startupinfo=startupinfo)
        process.print_filename = filename
        #we just let it run, no need for reaping the process on win32
        processes.append(process)
    JOB_ID +=1
    PROCESSES[JOB_ID] = processes
    log("win32.print_files(..)=%s (%s)", JOB_ID, processes)
    return JOB_ID

def printing_finished(jobid):
    global PROCESSES
    processes = PROCESSES.get(jobid)
    if not processes:
        log.warn("win32.printing_finished(%s) job not found!", jobid)
        return True
    log("win32.printing_finished(%s) processes: %s", jobid, [x.print_filename for x in processes])
    pending = [proc.print_filename for proc in processes if proc.poll() is None]
    log("win32.printing_finished(%s) still pending: %s", jobid, pending)
    #return finished when all the processes have terminated
    return len(pending)==0
