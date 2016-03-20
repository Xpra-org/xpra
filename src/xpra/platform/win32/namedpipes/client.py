#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2009-2015 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import sys
from threading import Thread

from xpra.log import Logger
log = Logger("shadow", "win32")

from xpra.platform.win32.namedpipes.common import PipeReader, PipeWriter, log as clog
from win32file import CreateFile, CloseHandle, GENERIC_READ, GENERIC_WRITE, OPEN_EXISTING	#@UnresolvedImport
from win32api import Sleep		#@UnresolvedImport

ERROR_PIPE_ENDED = 109
ERROR_FILE_NOT_FOUND = 2

class NamedPipeClient(Thread):
	def __init__(self, pipe_name, packet_handler=None, messages=[]):
		Thread.__init__(self, name="NamedPipeClient")
		self.pipe_name = pipe_name
		self.pipeHandle = None
		self.packet_handler = packet_handler
		self.messages = messages
		self.exit_code = None
		self.reader = None
		self.writer = None

	def stop(self):
		self.exit_code = 0
		for x in (self.reader, self.writer):
			if x:
				x.stop()

	def run(self):
		try:
			self.do_run()
		except Exception:
			log.error("run()", exc_info=True)
		finally:
			log("run() will cleanup %s", self.pipeHandle)
			if self.pipeHandle:
				CloseHandle(self.pipeHandle)
				self.pipeHandle = None
		log("run() ended")

	def do_run(self):
		log("do_run()")
		self.pipeHandle = CreateFile(self.pipe_name,
                              GENERIC_READ | GENERIC_WRITE,
                              0, None,
                              OPEN_EXISTING,
                              0, None)
		self.reader = PipeReader(self.pipeHandle, self.packet_handler)
		self.reader.start()
		self.writer = PipeWriter(self.pipeHandle)
		self.writer.start()
		self.send(*self.messages)
		log("do_run() sleeping")
		Sleep(1000)
		log("do_run() ended")

	def send(self, *msgs):
		log("send%s", msgs)
		for msg in msgs:
			self.writer.send(msg)


def main():
	import os
	from xpra.platform import program_context
	from xpra.platform.win32 import console_event_catcher
	from xpra.log import enable_color
	PIPE_NAME = os.environ.get("XPRA_NAMEDPIPE", "\\\\.\\pipe\\Xpra")
	if not PIPE_NAME.find("\\")>=0:
		PIPE_NAME = "\\\\.\\pipe\\"+PIPE_NAME
	log.info("using named pipe %s", PIPE_NAME)
	log.enable_debug()
	clog.enable_debug()
	with program_context("Named Pipe Listener"):
		enable_color()
		try:
			client = NamedPipeClient(PIPE_NAME, None, sys.argv[1:])
			def stop(*args):
				client.stop()
				sys.exit(0)
			with console_event_catcher(stop):
				client.start()
			log("waiting for client thread to join")
			client.join()
			log("all done")
		except Exception:
			log.error("stopped", exc_info=True)

if __name__ == "__main__":
	main()
