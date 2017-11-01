# This file is part of Xpra.
# Copyright (C) 2013 eryksun
# https://stackoverflow.com/questions/15748386/how-to-catch-printer-event-in-python
# License:
# https://creativecommons.org/licenses/by-sa/3.0/legalcode


import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL('kernel32.dll', use_last_error=True)
winspool = ctypes.WinDLL('winspool.drv', use_last_error=True)

# define LPHANDLE, PDWORD, and PWORD for Python 2
if not hasattr(wintypes, 'LPHANDLE'):
    setattr(wintypes, 'LPHANDLE', ctypes.POINTER(wintypes.HANDLE))
if not hasattr(wintypes, 'PDWORD'):
    setattr(wintypes, 'PDWORD', ctypes.POINTER(wintypes.DWORD))
if not hasattr(wintypes, 'PWORD'):
    setattr(wintypes, 'PWORD', ctypes.POINTER(wintypes.WORD))

INFINITE = -1
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT  = 0x00000102
WAIT_FAILED   = 0xFFFFFFFF
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

PRINTER_CHANGE_ADD_PRINTER               = 0x00000001
PRINTER_CHANGE_SET_PRINTER               = 0x00000002
PRINTER_CHANGE_DELETE_PRINTER            = 0x00000004
PRINTER_CHANGE_FAILED_CONNECTION_PRINTER = 0x00000008
PRINTER_CHANGE_PRINTER                   = 0x000000FF

PRINTER_CHANGE_ADD_JOB                   = 0x00000100
PRINTER_CHANGE_SET_JOB                   = 0x00000200
PRINTER_CHANGE_DELETE_JOB                = 0x00000400
PRINTER_CHANGE_WRITE_JOB                 = 0x00000800
PRINTER_CHANGE_JOB                       = 0x0000FF00

PRINTER_CHANGE_ADD_FORM                  = 0x00010000
PRINTER_CHANGE_SET_FORM                  = 0x00020000
PRINTER_CHANGE_DELETE_FORM               = 0x00040000
PRINTER_CHANGE_FORM                      = 0x00070000

PRINTER_CHANGE_ADD_PORT                  = 0x00100000
PRINTER_CHANGE_CONFIGURE_PORT            = 0x00200000
PRINTER_CHANGE_DELETE_PORT               = 0x00400000
PRINTER_CHANGE_PORT                      = 0x00700000

PRINTER_CHANGE_ADD_PRINT_PROCESSOR       = 0x01000000
PRINTER_CHANGE_DELETE_PRINT_PROCESSOR    = 0x04000000
PRINTER_CHANGE_PRINT_PROCESSOR           = 0x07000000
PRINTER_CHANGE_SERVER                    = 0x08000000 # NT 6.1+

PRINTER_CHANGE_ADD_PRINTER_DRIVER        = 0x10000000
PRINTER_CHANGE_SET_PRINTER_DRIVER        = 0x20000000
PRINTER_CHANGE_DELETE_PRINTER_DRIVER     = 0x40000000
PRINTER_CHANGE_PRINTER_DRIVER            = 0x70000000

PRINTER_CHANGE_ALL                       = 0x7F77FFFF
PRINTER_CHANGE_TIMEOUT                   = 0x80000000

PRINTER_NOTIFY_CATEGORY_ALL = 0x00
PRINTER_NOTIFY_CATEGORY_3D  = 0x01

PRINTER_NOTIFY_TYPE = 0x00
JOB_NOTIFY_TYPE     = 0x01

PRINTER_NOTIFY_FIELD_SERVER_NAME            = 0x00 # not supported
PRINTER_NOTIFY_FIELD_PRINTER_NAME           = 0x01
PRINTER_NOTIFY_FIELD_SHARE_NAME             = 0x02
PRINTER_NOTIFY_FIELD_PORT_NAME              = 0x03
PRINTER_NOTIFY_FIELD_DRIVER_NAME            = 0x04
PRINTER_NOTIFY_FIELD_COMMENT                = 0x05
PRINTER_NOTIFY_FIELD_LOCATION               = 0x06
PRINTER_NOTIFY_FIELD_DEVMODE                = 0x07
PRINTER_NOTIFY_FIELD_SEPFILE                = 0x08
PRINTER_NOTIFY_FIELD_PRINT_PROCESSOR        = 0x09
PRINTER_NOTIFY_FIELD_PARAMETERS             = 0x0A
PRINTER_NOTIFY_FIELD_DATATYPE               = 0x0B
PRINTER_NOTIFY_FIELD_SECURITY_DESCRIPTOR    = 0x0C
PRINTER_NOTIFY_FIELD_ATTRIBUTES             = 0x0D
PRINTER_NOTIFY_FIELD_PRIORITY               = 0x0E
PRINTER_NOTIFY_FIELD_DEFAULT_PRIORITY       = 0x0F
PRINTER_NOTIFY_FIELD_START_TIME             = 0x10
PRINTER_NOTIFY_FIELD_UNTIL_TIME             = 0x11
PRINTER_NOTIFY_FIELD_STATUS                 = 0x12
PRINTER_NOTIFY_FIELD_STATUS_STRING          = 0x13 # not supported
PRINTER_NOTIFY_FIELD_CJOBS                  = 0x14
PRINTER_NOTIFY_FIELD_AVERAGE_PPM            = 0x15
PRINTER_NOTIFY_FIELD_TOTAL_PAGES            = 0x16 # not supported
PRINTER_NOTIFY_FIELD_PAGES_PRINTED          = 0x17 # not supported
PRINTER_NOTIFY_FIELD_TOTAL_BYTES            = 0x18 # not supported
PRINTER_NOTIFY_FIELD_BYTES_PRINTED          = 0x19 # not supported
PRINTER_NOTIFY_FIELD_OBJECT_GUID            = 0x1A
PRINTER_NOTIFY_FIELD_FRIENDLY_NAME          = 0x1B # NT 6.0+
PRINTER_NOTIFY_FIELD_BRANCH_OFFICE_PRINTING = 0x1C # NT 6.2+

JOB_NOTIFY_FIELD_PRINTER_NAME        = 0x00
JOB_NOTIFY_FIELD_MACHINE_NAME        = 0x01
JOB_NOTIFY_FIELD_PORT_NAME           = 0x02
JOB_NOTIFY_FIELD_USER_NAME           = 0x03
JOB_NOTIFY_FIELD_NOTIFY_NAME         = 0x04
JOB_NOTIFY_FIELD_DATATYPE            = 0x05
JOB_NOTIFY_FIELD_PRINT_PROCESSOR     = 0x06
JOB_NOTIFY_FIELD_PARAMETERS          = 0x07
JOB_NOTIFY_FIELD_DRIVER_NAME         = 0x08
JOB_NOTIFY_FIELD_DEVMODE             = 0x09
JOB_NOTIFY_FIELD_STATUS              = 0x0A
JOB_NOTIFY_FIELD_STATUS_STRING       = 0x0B
JOB_NOTIFY_FIELD_SECURITY_DESCRIPTOR = 0x0C # not supported
JOB_NOTIFY_FIELD_DOCUMENT            = 0x0D
JOB_NOTIFY_FIELD_PRIORITY            = 0x0E
JOB_NOTIFY_FIELD_POSITION            = 0x0F
JOB_NOTIFY_FIELD_SUBMITTED           = 0x10
JOB_NOTIFY_FIELD_START_TIME          = 0x11
JOB_NOTIFY_FIELD_UNTIL_TIME          = 0x12
JOB_NOTIFY_FIELD_TIME                = 0x13
JOB_NOTIFY_FIELD_TOTAL_PAGES         = 0x14
JOB_NOTIFY_FIELD_PAGES_PRINTED       = 0x15
JOB_NOTIFY_FIELD_TOTAL_BYTES         = 0x16
JOB_NOTIFY_FIELD_BYTES_PRINTED       = 0x17
JOB_NOTIFY_FIELD_REMOTE_JOB_ID       = 0x18

PRINTER_NOTIFY_OPTIONS_REFRESH = 0x01
PRINTER_NOTIFY_INFO_DISCARDED  = 0x01

JOB_STATUS_PAUSED            = 0x00000001
JOB_STATUS_ERROR             = 0x00000002
JOB_STATUS_DELETING          = 0x00000004
JOB_STATUS_SPOOLING          = 0x00000008
JOB_STATUS_PRINTING          = 0x00000010
JOB_STATUS_OFFLINE           = 0x00000020
JOB_STATUS_PAPEROUT          = 0x00000040
JOB_STATUS_PRINTED           = 0x00000080
JOB_STATUS_DELETED           = 0x00000100
JOB_STATUS_BLOCKED_DEVQ      = 0x00000200
JOB_STATUS_USER_INTERVENTION = 0x00000400
JOB_STATUS_RESTART           = 0x00000800
JOB_STATUS_COMPLETE          = 0x00001000
JOB_STATUS_RETAINED          = 0x00002000
JOB_STATUS_RENDERING_LOCALLY = 0x00004000
JOB_STATUS_ALL               = 0x00007FFF

JOB_STATUS_STRING = {
    JOB_STATUS_PAUSED:   'PAUSED',
    JOB_STATUS_ERROR:    'ERROR',
    JOB_STATUS_DELETING: 'DELETING',
    JOB_STATUS_SPOOLING: 'SPOOLING',
    JOB_STATUS_PRINTING: 'PRINTING',
    JOB_STATUS_OFFLINE:  'OFFLINE',
    JOB_STATUS_PAPEROUT: 'PAPEROUT',
    JOB_STATUS_PRINTED:  'PRINTED',
    JOB_STATUS_DELETED:  'DELETED',
    JOB_STATUS_BLOCKED_DEVQ: 'BLOCKED_DEVQ',
    JOB_STATUS_USER_INTERVENTION: 'USER_INTERVENTION',
    JOB_STATUS_RESTART:  'RESTART',
    JOB_STATUS_COMPLETE: 'COMPLETE',
    JOB_STATUS_RETAINED: 'RETAINED',
    JOB_STATUS_RENDERING_LOCALLY: 'RENDERING_LOCALLY'}

class SYSTEMTIME(ctypes.Structure):
    _fields_ = (('wYear',         wintypes.WORD),
                ('wMonth',        wintypes.WORD),
                ('wDayOfWeek',    wintypes.WORD),
                ('wDay',          wintypes.WORD),
                ('wHour',         wintypes.WORD),
                ('wMinute',       wintypes.WORD),
                ('wSecond',       wintypes.WORD),
                ('wMilliseconds', wintypes.WORD))
    @property
    def as_datetime(self):
        from datetime import datetime
        return datetime(self.wYear, self.wMonth, self.wDay,
                        self.wHour, self.wMinute, self.wSecond,
                        self.wMilliseconds * 1000)

class PRINTER_NOTIFY_OPTIONS_TYPE(ctypes.Structure):
    _fields_ = (('Type',      wintypes.WORD),
                ('Reserved0', wintypes.WORD),
                ('Reserved1', wintypes.DWORD),
                ('Reserved2', wintypes.DWORD),
                ('Count',     wintypes.DWORD),
                ('_pFields',  wintypes.PWORD))
    def __init__(self, Type=JOB_NOTIFY_TYPE, pFields=None):
        super(PRINTER_NOTIFY_OPTIONS_TYPE, self).__init__(Type)
        if pFields is not None:
            self.pFields = pFields
    @property
    def pFields(self):
        ptr_t = ctypes.POINTER(wintypes.WORD * self.Count)
        return ptr_t(self._pFields.contents)[0]
    @pFields.setter
    def pFields(self, pFields):
        self.Count = len(pFields)
        self._pFields = pFields

PPRINTER_NOTIFY_OPTIONS_TYPE = ctypes.POINTER(PRINTER_NOTIFY_OPTIONS_TYPE)

class PRINTER_NOTIFY_OPTIONS(ctypes.Structure):
    _fields_ = (('Version', wintypes.DWORD),
                ('Flags',   wintypes.DWORD),
                ('Count',   wintypes.DWORD),
                ('_pTypes', PPRINTER_NOTIFY_OPTIONS_TYPE))
    def __init__(self, Flags=0, pTypes=None):
        super(PRINTER_NOTIFY_OPTIONS, self).__init__(2, Flags)
        if pTypes is not None:
            self.pTypes = pTypes
    @property
    def pTypes(self):
        ptr_t = ctypes.POINTER(PRINTER_NOTIFY_OPTIONS_TYPE * self.Count)
        return ptr_t(self._pTypes.contents)[0]
    @pTypes.setter
    def pTypes(self, types):
        if isinstance(types, PRINTER_NOTIFY_OPTIONS_TYPE):
            self.Count = 1
            self._pTypes = ctypes.pointer(types)
        else:
            self.Count = len(types)
            self._pTypes = types

PPRINTER_NOTIFY_OPTIONS = ctypes.POINTER(PRINTER_NOTIFY_OPTIONS)

class PRINTER_NOTIFY_INFO_DATA(ctypes.Structure):
    class _NOTIFY_DATA(ctypes.Union):
        class  _DATA(ctypes.Structure):
            _fields_ = (('cbBuf', wintypes.DWORD),
                        ('pBuf',  wintypes.LPVOID))
        _fields_ = (('adwData', wintypes.DWORD * 2),
                    ('Data',    _DATA))
    _fields_ = (('Type',        wintypes.WORD),
                ('Field',       wintypes.WORD),
                ('Reserved',    wintypes.DWORD),
                ('Id',          wintypes.DWORD),
                ('_NotifyData', _NOTIFY_DATA))
    @property
    def _data_as_string(self):
        if self._NotifyData.Data.pBuf:
            return ctypes.c_wchar_p(self._NotifyData.Data.pBuf).value
        return u""
    @property
    def _data_as_datetime(self):
        if self._NotifyData.Data.pBuf:
            t = SYSTEMTIME.from_address(self._NotifyData.Data.pBuf)
        else:
            t = SYSTEMTIME()
        return t.as_datetime
    @property
    def NotifyData(self):
        if self.Type == JOB_NOTIFY_TYPE:
            if self.Field == JOB_NOTIFY_FIELD_PRINTER_NAME:
                return 'job_printer_name', self._data_as_string
            if self.Field == JOB_NOTIFY_FIELD_MACHINE_NAME:
                return 'job_machine_name', self._data_as_string
            if self.Field == JOB_NOTIFY_FIELD_USER_NAME:
                return 'job_user_name', self._data_as_string
            elif self.Field == JOB_NOTIFY_FIELD_STATUS:
                return 'job_status', self._NotifyData.adwData[0]
            elif self.Field == JOB_NOTIFY_FIELD_DOCUMENT:
                return 'job_document', self._data_as_string
            elif self.Field == JOB_NOTIFY_FIELD_PRIORITY:
                return 'job_priority', self._NotifyData.adwData[0]
            elif self.Field == JOB_NOTIFY_FIELD_POSITION:
                return 'job_position', self._NotifyData.adwData[0]
            elif self.Field == JOB_NOTIFY_FIELD_SUBMITTED:
                return 'job_submitted', self._data_as_datetime
            elif self.Field == JOB_NOTIFY_FIELD_PAGES_PRINTED:
                return 'job_pages_printed', self._NotifyData.adwData[0]
            elif self.Field == JOB_NOTIFY_FIELD_BYTES_PRINTED:
                return 'job_bytes_printed', self._NotifyData.adwData[0]
        # else return a copy of NotifyData
        data = self._NOTIFY_DATA.from_buffer_copy(self._NotifyData)
        if data.Data.pBuf:
            buf_t = ctypes.c_char * data.Data.cbBuf
            buf_src = buf_t.from_address(data.Data.pBuf)
            buf_cpy = buf_t.from_buffer_copy(buf_src)
            buf_ptr = ctypes.c_void_p(ctypes.addressof(buf_cpy))
            data.Data.pBuf = buf_ptr
        return (self.Type, self.Field), data

class PRINTER_NOTIFY_INFO(ctypes.Structure):
    _fields_ = (('Version', wintypes.DWORD),
                ('Flags',   wintypes.DWORD),
                ('Count',   wintypes.DWORD),
                ('_aData',  PRINTER_NOTIFY_INFO_DATA * 1))
    @property
    def aData(self):
        ptr_t = ctypes.POINTER(PRINTER_NOTIFY_INFO_DATA * self.Count)
        return ptr_t(self._aData[0])[0]

PPRINTER_NOTIFY_INFO = ctypes.POINTER(PRINTER_NOTIFY_INFO)
PPPRINTER_NOTIFY_INFO = ctypes.POINTER(PPRINTER_NOTIFY_INFO)

class PPRINTER_NOTIFY_INFO_GC(PPRINTER_NOTIFY_INFO):
    """PRINTER_NOTIFY_INFO * that Windows deallocates"""
    _type_ = PRINTER_NOTIFY_INFO
    _freed = False
    def __del__(self,
                FreePrinterNotifyInfo=winspool.FreePrinterNotifyInfo):
        if self and not self._freed:
            FreePrinterNotifyInfo(self)
            self._freed = True

def check_bool(result, func, args):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return args

def check_ihv(result, func, args):
    if result == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return args

def check_idv(result, func, args):
    if result == WAIT_FAILED:
        raise ctypes.WinError(ctypes.get_last_error())
    return args

winspool.OpenPrinterW.errcheck = check_bool
winspool.OpenPrinterW.argtypes = (
    wintypes.LPWSTR,   # _In_  pPrinterName
    wintypes.LPHANDLE, # _Out_ phPrinter
    wintypes.LPVOID)   # _In_  pDefault

winspool.ClosePrinter.errcheck = check_bool
winspool.ClosePrinter.argtypes = (
    wintypes.HANDLE,) # _In_ hPrinter

winspool.FindFirstPrinterChangeNotification.errcheck = check_ihv
winspool.FindFirstPrinterChangeNotification.restype = wintypes.HANDLE
winspool.FindFirstPrinterChangeNotification.argtypes = (
    wintypes.HANDLE, # _In_ hPrinter
    wintypes.DWORD,  #      fdwFilter
    wintypes.DWORD,  #      fdwOptions
    PPRINTER_NOTIFY_OPTIONS) # _In_opt_ pPrinterNotifyOptions

winspool.FindNextPrinterChangeNotification.errcheck = check_bool
winspool.FindNextPrinterChangeNotification.argtypes = (
    wintypes.HANDLE, # _In_      hChange
    wintypes.PDWORD, # _Out_opt_ pdwChange
    PPRINTER_NOTIFY_OPTIONS, # _In_opt_  pPrinterNotifyOptions
    PPPRINTER_NOTIFY_INFO)   # _Out_opt_ ppPrinterNotifyInfo

winspool.FindClosePrinterChangeNotification.errcheck = check_bool
winspool.FindClosePrinterChangeNotification.argtypes = (
    wintypes.HANDLE,) # _In_ hChange

winspool.FreePrinterNotifyInfo.errcheck = check_bool
winspool.FreePrinterNotifyInfo.argtypes = (
    PPRINTER_NOTIFY_INFO,) # _In_ pPrinterNotifyInfo

kernel32.WaitForSingleObject.errcheck = check_idv
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = (
    wintypes.HANDLE, # _In_ hHandle
    wintypes.DWORD)  # _In_ dwMilliseconds

def wait_for_print_job(filter=PRINTER_CHANGE_ADD_JOB,
                       timeout=INFINITE,
                       printer_name=None):
    if timeout != INFINITE:
        timeout = int(timeout * 1000)
    hPrinter = wintypes.HANDLE()
    dwChange = wintypes.DWORD()
    winspool.OpenPrinterW(printer_name, ctypes.byref(hPrinter), None)
    try:
        hChange = winspool.FindFirstPrinterChangeNotification(
                    hPrinter, filter, 0, None)
        try:
            if (kernel32.WaitForSingleObject(hChange, timeout) !=
                WAIT_OBJECT_0): return
            winspool.FindNextPrinterChangeNotification(
                hChange, ctypes.byref(dwChange), None, None)
            return dwChange.value
        finally:
            winspool.FindClosePrinterChangeNotification(hChange)
    finally:
        winspool.ClosePrinter(hPrinter)

DEFAULT_FIELDS = (
    JOB_NOTIFY_FIELD_PRINTER_NAME,
    JOB_NOTIFY_FIELD_STATUS,
    JOB_NOTIFY_FIELD_DOCUMENT,
    JOB_NOTIFY_FIELD_PRIORITY,
    JOB_NOTIFY_FIELD_POSITION,
    JOB_NOTIFY_FIELD_SUBMITTED)

def wait_for_print_job_info(fields=DEFAULT_FIELDS,
                            timeout=INFINITE,
                            printer_name=None):
    if timeout != INFINITE:
        timeout = int(timeout * 1000)
    hPrinter = wintypes.HANDLE()
    fields = (wintypes.WORD * len(fields))(*fields)
    opt = PRINTER_NOTIFY_OPTIONS(
            pTypes=PRINTER_NOTIFY_OPTIONS_TYPE(
                    Type=JOB_NOTIFY_TYPE, pFields=fields))
    pinfo = PPRINTER_NOTIFY_INFO_GC() # note: GC subclass
    result = []
    winspool.OpenPrinterW(printer_name, ctypes.byref(hPrinter), None)
    try:
        hChange = winspool.FindFirstPrinterChangeNotification(
                    hPrinter, 0, 0, ctypes.byref(opt))
        try:
            if (kernel32.WaitForSingleObject(hChange, timeout) !=
                WAIT_OBJECT_0): return result
            winspool.FindNextPrinterChangeNotification(
                hChange, None, None, ctypes.byref(pinfo))
            for data in pinfo[0].aData:
                if data.Type != JOB_NOTIFY_TYPE:
                    continue
                nd = (data.Id,) + data.NotifyData
                result.append(nd)
            return result
        finally:
            winspool.FindClosePrinterChangeNotification(hChange)
    finally:
        winspool.ClosePrinter(hPrinter)

def job_status(status, nfmt='%#010x'):
    if status == 0:
        return []
    strings = []
    for state, string in JOB_STATUS_STRING.items():
        if status & state:
            strings.append(string)
            status &= ~state
            if not status:
                break
    if status:
        strings.append(nfmt % status)
    return strings

def job_status_string(status, nfmt='%#010x'):
    return ','.join(job_status(status, nfmt))
