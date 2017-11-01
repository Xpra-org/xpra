#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util import repr_ellipsized
from xpra.platform.win32.common import GetDeviceCaps
from xpra.platform.win32 import win32con
from xpra.platform.win32.win32_printing import GDIPrinterContext, DOCINFO, StartDocA, EndDoc, LPCSTR
from ctypes.wintypes import HDC
from ctypes import WinDLL, c_void_p, Structure, c_int, c_uint, c_ulong, c_char_p, cast, pointer, POINTER

LIBPDFIUMDLL = os.environ.get("XPRA_LIBPDFIUMDLL", "libpdfium.dll")
try:
	pdfium = WinDLL(LIBPDFIUMDLL, use_last_error=True)
except WindowsError as e:		#@UndefinedVariable
	raise ImportError("cannot load %s: %s" % (LIBPDFIUMDLL, e))

class FPDF_LIBRARY_CONFIG(Structure):
	_fields_ = [
		("m_pUserFontPaths",	c_void_p),
		("version",				c_int),
		("m_pIsolate",			c_void_p),
		("m_v8EmbedderSlot",	c_uint),
		]

FPDF_DOCUMENT = c_void_p
FPDF_PAGE = c_void_p

FPDF_DestroyLibrary = pdfium.FPDF_DestroyLibrary
FPDF_InitLibraryWithConfig = pdfium.FPDF_InitLibraryWithConfig
FPDF_InitLibraryWithConfig.argtypes = [POINTER(FPDF_LIBRARY_CONFIG)]
FPDF_GetLastError = pdfium.FPDF_GetLastError
FPDF_GetLastError.restype = c_ulong
FPDF_GetPageCount = pdfium.FPDF_GetPageCount
FPDF_GetPageCount.argtypes = [FPDF_DOCUMENT]
FPDF_GetPageCount.restype = c_int
FPDF_LoadPage = pdfium.FPDF_LoadPage
FPDF_LoadPage.argtypes = [FPDF_DOCUMENT, c_int]
FPDF_RenderPage = pdfium.FPDF_RenderPage
FPDF_RenderPage.argtypes = [HDC, FPDF_PAGE, c_int, c_int, c_int, c_int, c_int, c_int]
FPDF_LoadMemDocument = pdfium.FPDF_LoadMemDocument
FPDF_LoadMemDocument.restype = FPDF_DOCUMENT
FPDF_LoadMemDocument.argtypes = [c_void_p, c_int, c_void_p]
FPDF_CloseDocument = pdfium.FPDF_CloseDocument
FPDF_CloseDocument.argtypes = [FPDF_DOCUMENT]

FPDF_ERR_SUCCESS = 0	# No error.
FPDF_ERR_UNKNOWN = 1    # Unknown error.
FPDF_ERR_FILE = 2 		# File not found or could not be opened.
FPDF_ERR_FORMAT = 3     # File not in PDF format or corrupted.
FPDF_ERR_PASSWORD = 4   # Password required or incorrect password.
FPDF_ERR_SECURITY = 5   # Unsupported security scheme.
FPDF_ERR_PAGE = 6       # Page not found or content error.
FPDF_ERR_XFALOAD = 7    # Load XFA error.
FPDF_ERR_XFALAYOUT = 8  # Layout XFA error.

ERROR_STR = {
	#FPDF_ERR_SUCCESS : No error.
	FPDF_ERR_UNKNOWN 	: "Unknown error",
	FPDF_ERR_FILE 		: "File not found or could not be opened",
	FPDF_ERR_FORMAT		: "File not in PDF format or corrupted",
	FPDF_ERR_PASSWORD 	: "Password required or incorrect password",
	FPDF_ERR_SECURITY 	: "Unsupported security scheme",
	FPDF_ERR_PAGE 		: "Page not found or content error",
	FPDF_ERR_XFALOAD 	: "Load XFA error",
	FPDF_ERR_XFALAYOUT 	: "Layout XFA error",
	}

FPDF_ANNOT = 0x01
FPDF_LCD_TEXT = 0x02
FPDF_NO_NATIVETEXT = 0x04
FPDF_GRAYSCALE = 0x08
FPDF_DEBUG_INFO = 0x80
FPDF_NO_CATCH = 0x100
FPDF_RENDER_LIMITEDIMAGECACHE = 0x200
FPDF_RENDER_FORCEHALFTONE = 0x400
FPDF_PRINTING = 0x800
FPDF_RENDER_NO_SMOOTHTEXT = 0x1000
FPDF_RENDER_NO_SMOOTHIMAGE = 0x2000
FPDF_RENDER_NO_SMOOTHPATH = 0x4000
FPDF_REVERSE_BYTE_ORDER = 0x10

def get_error():
	global ERROR_STR
	v = FPDF_GetLastError()
	return ERROR_STR.get(v, v)

def do_print_pdf(hdc, title="PDF Print Test", pdf_data=None):
	assert pdf_data, "no pdf data"
	from xpra.log import Logger
	log = Logger("printing", "win32")
	log("pdfium=%s", pdfium)
	buf = c_char_p(pdf_data)
	log("pdf data buffer: %s", repr_ellipsized(pdf_data))
	log("FPDF_InitLibraryWithConfig=%s", FPDF_InitLibraryWithConfig)
	config = FPDF_LIBRARY_CONFIG()
	config.m_pUserFontPaths = None
	config.version = 2
	config.m_pIsolate = None
	config.m_v8EmbedderSlot = 0
	FPDF_InitLibraryWithConfig(config)
	x = 0
	y = 0
	w = GetDeviceCaps(hdc, win32con.HORZRES)
	h = GetDeviceCaps(hdc, win32con.VERTRES)
	rotate = 0
	log("printer device size: %ix%i", w, h)
	flags = FPDF_PRINTING | FPDF_DEBUG_INFO
	try:
		doc = FPDF_LoadMemDocument(cast(buf, c_void_p), len(pdf_data), None)
		if not doc:
			log.error("Error: FPDF_LoadMemDocument failed, error: %s", get_error())
			return -1
		log("FPDF_LoadMemDocument(..)=%s", doc)
		count = FPDF_GetPageCount(doc)
		log("FPDF_GetPageCount(%s)=%s", doc, count)
		docinfo = DOCINFO()
		docinfo.lpszDocName = LPCSTR("%s\0" % title)
		jobid = StartDocA(hdc, pointer(docinfo))
		if jobid<0:
			log.error("Error: StartDocA failed: %i", jobid)
			return jobid
		log("StartDocA()=%i", jobid)
		try:
			for i in range(count):
				page = FPDF_LoadPage(doc, i)
				if not page:
					log.error("Error: FPDF_LoadPage failed for page %i, error: %s", i, get_error())
					return -2
				log("FPDF_LoadPage()=%s page %i loaded", page, i)
				FPDF_RenderPage(hdc, page, x, y, w, h, rotate, flags)
				log("FPDF_RenderPage page %i rendered", i)
		finally:
			EndDoc(hdc)
	finally:
		FPDF_DestroyLibrary()
	return jobid

def print_pdf(printer_name, title, pdf_data):
	with GDIPrinterContext(printer_name) as hdc:
		return do_print_pdf(hdc, title, pdf_data)


EXIT = False
JOBS_INFO = {}
def watch_print_job_status():
	global JOBS_INFO, EXIT
	from xpra.log import Logger
	log = Logger("printing", "win32")
	log("wait_for_print_job_end()")
	#log("wait_for_print_job_end(%i)", print_job_id)
	from xpra.platform.win32.printer_notify import wait_for_print_job_info, job_status
	while not EXIT:
		info = wait_for_print_job_info(timeout=1.0)
		if not info:
			continue
		log("wait_for_print_job_info()=%s", info)
		for nd in info:
			job_id, key, value = nd
			if key=='job_status':
				value = job_status(value)
			log("job_id=%s, key=%s, value=%s", job_id, key, value)
			JOBS_INFO.setdefault(job_id, {})[key] = value


def main():
	global JOBS_INFO, EXIT
	if len(sys.argv) not in (2, 3, 4):
		print("usage: %s /path/to/document.pdf [printer-name] [document-title]" % sys.argv[0])
		return -3
	filename = sys.argv[1]
	with open(filename, 'rb') as f:
		pdf_data = f.read()

	if len(sys.argv)==2:
		from xpra.platform.win32.printing import get_printers
		printers = get_printers()
		printer_name = printers.keys()[0]
	if len(sys.argv) in (3, 4):
		printer_name = sys.argv[2]
	if len(sys.argv)==4:
		title = sys.argv[3]
	else:
		title = os.path.basename(filename)

	import time
	from xpra.util import csv
	from xpra.log import Logger
	log = Logger("printing", "win32")

	#start a new thread before submitting the document,
	#because otherwise the job may complete before we can get its status
	from threading import Thread
	t = Thread(target=watch_print_job_status, name="watch print job status")
	t.daemon = True
	t.start()

	job_id = print_pdf(printer_name, title, pdf_data)
	if job_id<0:
		return job_id
	#wait for job to end:
	job_status = None
	while True:
		job_info = JOBS_INFO.get(job_id, {})
		log("job_info[%i]=%s", job_id, job_info)
		v = job_info.get("job_status")
		if v!=job_status:
			log.info("print job status: %s", csv(v))
			job_status = v
			if "OFFLINE" in job_status or "DELETING" in job_status:
				EXIT = True
				break
		time.sleep(1.0)
	return 0


if __name__ == "__main__":
	sys.exit(main())
