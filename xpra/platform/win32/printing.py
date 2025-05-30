# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import subprocess
from typing import Any
from collections.abc import Callable, Iterable, Sequence

from xpra.platform.win32 import constants as win32con
from xpra.util.objects import reverse_dict
from xpra.util.str_fn import csv, bytestostr
from xpra.util.env import envint, envbool
from xpra.platform.paths import get_app_dir
from xpra.log import Logger

log = Logger("printing")

# allows us to skip some printers we don't want to export
WINSPOOL_LISTENER = envbool("XPRA_WINSPOOL_LISTENER", True)
SKIPPED_PRINTERS = os.environ.get("XPRA_SKIPPED_PRINTERS", "Microsoft XPS Document Writer,Fax").split(",")
PRINTER_LEVEL = envint("XPRA_WIN32_PRINTER_LEVEL", 1)
DEFAULT_PRINTER_FLAGS = "LOCAL,SHARED+NETWORK+CONNECTIONS"
PRINTER_FLAGS = [x.strip() for x in os.environ.get("XPRA_WIN32_PRINTER_FLAGS", DEFAULT_PRINTER_FLAGS).split(",")]

DEFAULT_MIMETYPES = ["application/pdf", ]

PRINTER_ENUM_VALUES = {
    "DEFAULT": 1,
    "LOCAL": 2,
    "CONNECTIONS": 4,
    "NAME": 8,
    "REMOTE": 16,
    "SHARED": 32,
    "NETWORK": 64,
    "EXPAND": 16384,
    "CONTAINER": 32768,
    "ICON1": 65536 * 1,
    "ICON2": 65536 * 2,
    "ICON3": 65536 * 3,
    "ICON4": 65536 * 4,
    "ICON5": 65536 * 5,
    "ICON6": 65536 * 6,
    "ICON7": 65536 * 7,
    "ICON8": 65536 * 8,
}
PRINTER_ENUM_NAMES = reverse_dict(PRINTER_ENUM_VALUES)
log("PRINTER_ENUM_VALUES: %s", PRINTER_ENUM_VALUES)

log("PRINTER_FLAGS=%s", csv(PRINTER_FLAGS))
VALID_PRINTER_FLAGS = ("LOCAL", "SHARED", "CONNECTIONS", "NETWORK", "REMOTE")


def get_printer_enums() -> Sequence[str]:
    printer_enums = []
    for v in PRINTER_FLAGS:  # ie: "SHARED+NETWORK+CONNECTIONS"
        flags = v.replace('|', '+').split("+")  # ie: ["SHARED", "NETWORK", "CONNECTIONS"]
        values = []
        for flag in flags:  # ie: "SHARED"
            if flag not in VALID_PRINTER_FLAGS:
                log.warn("Warning: the following printer flag is invalid and will be ignored: %s", flag)
            else:
                values.append(flag)  # ie: "SHARED"
        printer_enums.append(values)
    return tuple(printer_enums)


PRINTER_ENUMS = get_printer_enums()
log("PRINTER_ENUMS=%s", PRINTER_ENUMS)

# emulate pycups job id
JOB_ID = 0
PROCESSES = {}

printers_modified_callback: Callable | None = None


def init_printing(callback=None):
    global printers_modified_callback
    log("init_printing(%s) printers_modified_callback=%s", callback, printers_modified_callback)
    printers_modified_callback = callback
    if WINSPOOL_LISTENER:
        try:
            init_winspool_listener()
        except Exception:
            log.error("Error: failed to register for print spooler changes", exc_info=True)


def init_winspool_listener() -> None:
    from xpra.platform.win32.events import get_win32_event_listener
    get_win32_event_listener().add_event_callback(win32con.WM_DEVMODECHANGE, on_devmodechange)


def on_devmodechange(wParam, lParam) -> None:
    global printers_modified_callback
    log("on_devmodechange(%s, %s) printers_modified_callback=%s", wParam, lParam, printers_modified_callback)
    # from ctypes import c_wchar_p
    # name = c_wchar_p(lParam)
    # log("device changed: %s", name)
    if lParam > 0 and printers_modified_callback:
        printers_modified_callback()


def EnumPrinters(flags, name=None, level=PRINTER_LEVEL):
    from ctypes import (
        WinDLL,  # @UnresolvedImport
        byref, addressof, cast, Structure, POINTER,
    )
    from ctypes.wintypes import BYTE, BOOL, DWORD, LPCWSTR, LPBYTE, LPDWORD

    winspool = WinDLL('winspool.drv', use_last_error=True)
    EnumPrintersW = winspool.EnumPrintersW
    EnumPrintersW.restype = BOOL
    EnumPrintersW.argtypes = [DWORD, LPCWSTR, DWORD, LPBYTE, DWORD, LPDWORD, LPDWORD]

    class PRINTER_INFO(Structure):
        _fields_ = [
            ("Flags", DWORD),
            ("pDescription", LPCWSTR),
            ("pName", LPCWSTR),
            ("pComment", LPCWSTR),
        ]

    # Invoke once with a NULL pointer to get buffer size.
    info = BYTE(0)
    pcbNeeded = DWORD(0)
    pcReturned = DWORD(0)  # the number of PRINTER_INFO_1 structures retrieved
    r = EnumPrintersW(DWORD(flags), name, DWORD(level), byref(info), DWORD(0), byref(pcbNeeded), byref(pcReturned))
    log("EnumPrintersW(..)=%i pcbNeeded=%i", r, pcbNeeded.value)
    if pcbNeeded.value <= 0:
        log("EnumPrinters probe failed for flags=%i, level=%i, pcbNeeded=%i", flags, level, pcbNeeded.value)
        return []

    bufsize = int(pcbNeeded.value)
    # noinspection PyCallingNonCallable,PyTypeChecker
    buf = (BYTE * bufsize)()
    pPrinterEnum = cast(addressof(buf), LPBYTE)
    log("EnumPrinters into buf %s", pPrinterEnum)
    r = EnumPrintersW(DWORD(flags), name, DWORD(level), pPrinterEnum, DWORD(bufsize), byref(pcbNeeded),
                      byref(pcReturned))
    log("EnumPrintersW(..)=%i pcReturned=%i", r, pcReturned.value)
    if r == 0:
        log.error("Error: EnumPrinters failed")
        return []
    info = cast(pPrinterEnum, POINTER(PRINTER_INFO))
    printers = []
    for i in range(pcReturned.value):
        v = int(info[i].Flags), str(info[i].pDescription), str(info[i].pName), str(info[i].pComment)
        log("EnumPrintersW(..) [%i]=%s", i, v)
        printers.append(v)
    del buf
    return printers


def get_info() -> dict[str, Any]:
    from xpra.platform.printing import default_get_info
    i = default_get_info()
    # win32 extras:
    i.update({
        "skipped-printers": SKIPPED_PRINTERS,
        "printer-level": PRINTER_LEVEL,
        "default-printer-flags": DEFAULT_PRINTER_FLAGS,
        "printer-flags": PRINTER_FLAGS,
    })
    return i


def get_printers() -> dict[str, dict[str, Any]]:
    global PRINTER_ENUMS, PRINTER_ENUM_VALUES, SKIPPED_PRINTERS, PRINTER_LEVEL
    printers = {}
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
                    log("skipped printer: %#x, %s, %s, %s", flags, desc, name, comment)
                    continue
                if name in printers:
                    log("skipped duplicate printer: %#x, %s, %s, %s", flags, desc, name, comment)
                    continue
                log("found printer: %#x, %s, %s, %s", flags, desc, name, comment)
                # strip duplicated and empty strings from the description:
                desc_els = []
                for x in desc.split(","):
                    if x and not desc_els.count(x):
                        desc_els.append(x)
                info = {
                    "printer-info": bytestostr(",".join(desc_els)),
                    "type": penum,
                }
                if comment:
                    info["printer-make-and-model"] = comment
                printers[name] = info
                eprinters.append(name)
            log("%s printers: %s", penum, eprinters)
        except Exception as e:
            log.warn("Warning: failed to query %s printers:", penum)
            log.warn(" %s", e)
            log("query error", exc_info=True)
            del e
    log("win32.get_printers()=%s", printers)
    return printers


def print_files(printer: str, filenames: Iterable[str], title: str, options: dict) -> int:
    log("win32.print_files%s", (printer, filenames, title, options))
    global JOB_ID, PROCESSES
    processes = []
    for filename in filenames:
        cwd = get_app_dir()
        command = ["PDFIUM_Print.exe", filename, printer, title]
        log("print command: %s", command)
        startupinfo = subprocess.STARTUPINFO()  # @UndefinedVariable
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # @UndefinedVariable
        startupinfo.wShowWindow = 0  # aka win32.con.SW_HIDE
        process = subprocess.Popen(command, stdout=sys.stdout, stderr=sys.stderr, cwd=cwd, startupinfo=startupinfo)
        process.print_filename = filename
        # we just let it run, no need for reaping the process on win32
        processes.append(process)
    JOB_ID += 1
    PROCESSES[JOB_ID] = processes
    log("win32.print_files(..)=%s (%s)", JOB_ID, processes)
    return JOB_ID


def printing_finished(jobid: int) -> bool:
    global PROCESSES
    processes = PROCESSES.get(jobid)
    if not processes:
        log.warn("win32.printing_finished(%s) job not found!", jobid)
        return True
    log("win32.printing_finished(%s) processes: %s", jobid, [x.print_filename for x in processes])
    pending = [proc.print_filename for proc in processes if proc.poll() is None]
    log("win32.printing_finished(%s) still pending: %s", jobid, pending)
    # return finished when all the processes have terminated
    return len(pending) == 0
