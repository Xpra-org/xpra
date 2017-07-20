#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("printing", "win32")

from xpra.platform.win32.common import CreateDCA, DeleteDC, gdi32

from ctypes import cdll, WinDLL, c_void_p, Structure, cast, c_char, c_int, pointer
from ctypes.wintypes import POINTER, HDC, HANDLE, BOOL, BYTE, LPCSTR, DWORD, WORD

CHAR = BYTE
LPHANDLE = PHANDLE = POINTER(HANDLE)
LPBYTE = POINTER(BYTE)
LPDWORD = POINTER(DWORD)
LPPRINTER_DEFAULTS = c_void_p
PSECURITY_DESCRIPTOR = HANDLE

msvcrt = cdll.msvcrt
winspool = WinDLL('winspool.drv', use_last_error=True)
OpenPrinterA = winspool.OpenPrinterA
OpenPrinterA.restype = BOOL
OpenPrinterA.argtypes = [LPCSTR, LPHANDLE, LPPRINTER_DEFAULTS]
ClosePrinter = winspool.ClosePrinter
ClosePrinter.restype = BOOL
ClosePrinter.argtypes = [HANDLE]
GetPrinterA = winspool.GetPrinterA
GetPrinterA.restype = BOOL
GetPrinterA.argtypes = [HANDLE, DWORD, c_void_p, DWORD, LPDWORD]

class DOCINFO(Structure):
	_fields_ = [
		("cbSize",		c_int),
		("lpszDocName",	LPCSTR),
		("lpszOutput",	LPCSTR),
		("lpszDatatype",LPCSTR),
		("fwType",		DWORD),
		]

LPDOCINFO = POINTER(DOCINFO)
StartDocA = gdi32.StartDocA
StartDocA.argtypes = [HDC, LPDOCINFO]
EndDoc = gdi32.EndDoc
EndDoc.argtypes = [HDC]
EndDoc.restype = int
StartPage = gdi32.StartPage
StartPage.argtypes = [HDC]
EndPage = gdi32.EndPage
EndPage.argtypes = [HDC]
TextOutA = gdi32.TextOutA
TextOutA.restype = BOOL
TextOutA.argtypes = [HDC, c_int, c_int, LPCSTR, c_int]

CCHDEVICENAME = 32

class DEVMODE(Structure):
	_fields_ = [
		("dmDeviceName",	c_char*CCHDEVICENAME),
		("dmSpecVersion",	WORD),
		("dmDriverVersion",	WORD),
		("dmSize",			WORD),
		("dmDriverExtra",	WORD),
		("dmFields",		DWORD),
		]
LPDEVMODE = POINTER(DEVMODE)

class PRINTER_INFO_1(Structure):
	_fields_ = [
		("Flags",			DWORD),
		("pDescription",	LPCSTR),
		("pName",			LPCSTR),
		("pComment",		LPCSTR),
		]
class PRINTER_INFO_2(Structure):
	_fields_ = [
		("pServerName",			LPCSTR),
		("pPrinterName",		LPCSTR),
		("pShareName",			LPCSTR),
		("pPortName",			LPCSTR),
		("pDriverName",			LPCSTR),
		("pComment",			LPCSTR),
		("pLocation",			LPCSTR),
		("pDevMode",			LPDEVMODE),
		("pSepFile",			LPCSTR),
		("pPrintProcessor",		LPCSTR),
		("pDatatype",			LPCSTR),
		("pParameters",			LPCSTR),
		("pSecurityDescriptor",	PSECURITY_DESCRIPTOR),
		("Attributes",			DWORD),
		("Priority",			DWORD),
		("DefaultPriority",		DWORD),
		("StartTime",			DWORD),
		("UntilTime",			DWORD),
		("Status",				DWORD),
		("cJobs",				DWORD),
		("AveragePPM",			DWORD),
		]
class PRINTER_INFO_8(Structure):
	_fields_ = [
		("pDevMode",			LPDEVMODE),
		]
class PRINTER_INFO_9(Structure):
	_fields_ = [
		("pDevMode",			LPDEVMODE),
		]


class GDIPrinterContext(object):

	def __init__(self, printer_name):
		self.printer_name = printer_name
		self.handle = None
		self.buf = None
		self.info1 = None
		self.info2 = None
		self.info8 = None
		self.info9 = None
		self.hdc = None

	def __enter__(self):
		self.handle = HANDLE()
		name = LPCSTR(self.printer_name)
		if not OpenPrinterA(name, pointer(self.handle), None):
			raise Exception("failed to open printer %s" % self.printer_name)
		log("OpenPrinter: handle=%#x", self.handle.value)
		size = DWORD(0)
		GetPrinterA(self.handle, 1, None, 0, pointer(size))
		if size.value==0:
			raise Exception("GetPrinterA PRINTER_INFO_1 failed for '%s'" % self.printer_name)
		log("GetPrinter: PRINTER_INFO_1 size=%#x", size.value)
		self.info1 = msvcrt.malloc(size.value)
		if not GetPrinterA(self.handle, 1, self.info1, size.value, pointer(size)):
			raise Exception("GetPrinterA PRINTER_INFO_1 failed for '%s'", self.printer_name)
		info = cast(self.info1, POINTER(PRINTER_INFO_1))
		log(" flags=%#x" % info[0].Flags)
		log(" name=%#s" % info[0].pName)
		log(" description=%s" % info[0].pDescription)
		log(" comment=%s" % info[0].pComment)

		size = DWORD(0)
		GetPrinterA(self.handle, 2, None, 0, pointer(size))
		if size.value==0:
			raise Exception("GetPrinterA PRINTER_INFO_2 failed for '%s'", self.printer_name)
		log("GetPrinter: PRINTER_INFO_2 size=%#x", size.value)
		self.info2 = msvcrt.malloc(size.value)
		if GetPrinterA(self.handle, 2, self.info2, size.value, pointer(size)):
			info = cast(self.info2, POINTER(PRINTER_INFO_2))
			log(" driver=%#s" % info[0].pDriverName)

		size = DWORD(0)
		GetPrinterA(self.handle, 8, None, 0, pointer(size))
		if size.value==0:
			raise Exception("GetPrinter: PRINTER_INFO_8 failed for '%s'" % self.printer_name)
		self.info8 = msvcrt.malloc(size.value)
		if GetPrinterA(self.handle, 8, self.info8, size.value, pointer(size)):
			info = cast(self.info8, POINTER(PRINTER_INFO_8))
			if info[0] and info[0].pDevMode:
				devmode = cast(info[0].pDevMode, POINTER(DEVMODE))
				log("PRINTER_INFO_8: devmode=%s" % devmode)
				log("PRINTER_INFO_8: device name='%s'" % devmode[0].dmDeviceName)

		size = DWORD(0)
		GetPrinterA(self.handle, 9, None, 0, pointer(size))
		if size.value==0:
			raise Exception("GetPrinter: PRINTER_INFO_9 failed for '%s'" % self.printer_name)
		log("GetPrinter: PRINTER_INFO_9 size=%#x" % size.value)
		self.info9 = msvcrt.malloc(size.value)
		if GetPrinterA(self.handle, 9, self.info9, size.value, pointer(size)):
			info = cast(self.info9, POINTER(PRINTER_INFO_9))
			if info[0] and info[0].pDevMode:
				devmode = cast(info[0].pDevMode, POINTER(DEVMODE))
				log("PRINTER_INFO_9: devmode=%s" % devmode)
				log("PRINTER_INFO_9: device name=%s" % devmode[0].dmDeviceName)
		assert devmode, "failed to query a DEVMODE for %s" % self.printer_name
		self.hdc = CreateDCA(None, name, None, devmode)
		log("CreateDCA(..)=%#x", self.hdc)
		return self.hdc

	def __exit__(self, exc_type, exc_val, exc_tb):
		log("GDIPrintContext(%s).exit%s hdc=%s, info=%s, handle=%s", self.printer_name, (exc_type, exc_val, exc_tb), self.hdc, (self.info1, self.info2, self.info8, self.info9), self.handle)
		if self.hdc:
			DeleteDC(self.hdc)
			self.hdc = None
		if self.info1:
			msvcrt.free(self.info1)
			self.info1 = None
		if self.info2:
			msvcrt.free(self.info2)
			self.info2 = None
		if self.info8:
			msvcrt.free(self.info8)
			self.info8 = None
		if self.info9:
			msvcrt.free(self.info9)
			self.info9 = None
		if self.handle:
			ClosePrinter(self.handle)
			self.handle = None

	def __repr__(self):
		return "GDIPrinterContext(%s)" % self.printer_name


def main(argv):
	import datetime
	if len(argv)==1:
		from xpra.platform.win32.printing import get_printers
		printers = get_printers()
		log("printers: %s", printers)
		printer_name = printers.keys()[0]
	elif len(argv)==2:
		printer_name = argv[1]
	else:
		log.error("usage: %s [printer-name]", argv[0])
		return 1

	title = "Test Page"
	log.warn("HELLO1")
	x = GDIPrinterContext(printer_name)
	log.warn("HELLO GDIPrinterContext: %s", x)

	with GDIPrinterContext(printer_name) as hdc:
		log("hdc=%s", hdc)
		docinfo = DOCINFO()
		docinfo.lpszDocName = LPCSTR("%s\0" % title)
		log("StartDocA(%#x, %s)", hdc, docinfo)
		r = StartDocA(hdc, pointer(docinfo))
		if r<0:
			log.error("StartDocA failed: %i", r)
			return r
		log("StartDocA()=%i" % r)
		r = StartPage(hdc)
		if r<0:
			log.error("StartPage failed: %i", r)
			return r
		x, y = 100, 100
		s = "Test Page printed at %s" % (datetime.datetime.now())
		if not TextOutA(hdc, x, y, LPCSTR(s), len(s)):
			log.error("TextOutA failed")
			return 1
		r = EndPage(hdc)
		if r<0:
			log.error("EndPage failed: %i", r)
			return r
		r = EndDoc(hdc)
		if r<0:
			log.error("EndDoc failed: %i" % r)
			return r
		log("EndDoc()=%i" % r)
		return 0


if __name__ == "__main__":
	import sys
	sys.exit(main(sys.argv))
