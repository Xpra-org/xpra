#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2009-2015 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from threading import Thread

from xpra.log import Logger
log = Logger("network", "win32")

import win32con, winerror			#@UnresolvedImport
from win32file import ReadFile, WriteFile, CloseHandle		#@UnresolvedImport
from win32file import SetFilePointer, FILE_BEGIN, FlushFileBuffers	#@UnresolvedImport
from win32pipe import DisconnectNamedPipe					#@UnresolvedImport
from win32api import GetCurrentProcess, DuplicateHandle, GetCurrentThread, error		#@UnresolvedImport


def ApplyIgnoreError(fn, *args):
	try:
		return apply(fn, args)
	except error: # Ignore win32api errors.
		return None

class PipeHandler(Thread):
	def __init__(self, name, pipeHandle):
		Thread.__init__(self, name=name)
		self.setDaemon(True)
		self.pipeHandle = pipeHandle
		self.exit_loop = False

	def run(self):
		log.info("%s() started for %s", self.getName(), self.pipeHandle)
		try:
			procHandle = GetCurrentProcess()
			self.thread_handle = DuplicateHandle(procHandle, GetCurrentThread(), procHandle, 0, 0, win32con.DUPLICATE_SAME_ACCESS)
		except error:
			log.error("Error setting up pipe %s", self.pipeHandle)
			return
		try:
			return self.do_run()
		except error:
			log.error("Error on pipe %s", self.pipeHandle, exc_info=True)
		finally:
			ApplyIgnoreError(DisconnectNamedPipe, self.pipeHandle)
			ApplyIgnoreError(CloseHandle, self.pipeHandle)

	def stop(self):
		self.exit_loop = True

	def _send(self, msg):
		log("_send(%s)", msg)
		# A secure service would handle (and ignore!) errors writing to the
		# pipe, but for the sake of this demo we dont (if only to see what errors
		# we can get when our clients break at strange times :-)
		WriteFile(self.pipeHandle, msg)
		FlushFileBuffers(self.pipeHandle)

class PipeReader(PipeHandler):
	def __init__(self, pipeHandle, packet_handler=None):
		PipeHandler.__init__(self, "PipeReader", pipeHandle)
		self.packet_handler = packet_handler

	def do_run(self):
		log("do_run()")
		try:
			#SetFilePointer(self.pipeHandle, 0, FILE_BEGIN)
			# Create a loop, reading large data.  If we knew the data stream
			# was small, a simple ReadFile would do.
			while not self.exit_loop:
				d = ''
				hr = winerror.ERROR_MORE_DATA
				while hr==winerror.ERROR_MORE_DATA:
					hr, thisd = ReadFile(self.pipeHandle, 256)
					d = d + thisd
				log("read '%s'", d)
				if self.packet_handler:
					self.packet_handler(d)
				#self._send("")
			return True
		except error:
			# Client disconnection - do nothing
			return False


class PipeWriter(PipeHandler):
	def __init__(self, pipeHandle):
		PipeHandler.__init__(self, "PipeWriter", pipeHandle)
		from Queue import Queue
		self.packet_queue = Queue()	#maxlen=1

	def do_run(self):
		while not self.exit_loop:
			msg = self.packet_queue.get()
			self._send(msg)

	def send(self, msg):
		log("send(%s) adding to queue, size=%s", msg, self.packet_queue.qsize())
		self.packet_queue.put(msg)
