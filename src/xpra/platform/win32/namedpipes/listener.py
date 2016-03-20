#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2009-2015 Antoine Martin <antoine@nagafix.co.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from threading import Thread

from xpra.log import Logger
log = Logger("network", "win32")

from xpra.platform.win32.namedpipes.common import PipeReader, PipeWriter, log as clog

import pywintypes, winerror			#@UnresolvedImport
from win32event import CreateEvent, SetEvent, WaitForMultipleObjects, WAIT_OBJECT_0, INFINITE						#@UnresolvedImport
from win32file import CloseHandle, FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_FLAG_OVERLAPPED, FILE_ALL_ACCESS		#@UnresolvedImport
from win32pipe import CreateNamedPipe, ConnectNamedPipe, PIPE_ACCESS_DUPLEX, PIPE_TYPE_MESSAGE, PIPE_READMODE_BYTE, PIPE_UNLIMITED_INSTANCES	#@UnresolvedImport
from win32api import error			#@UnresolvedImport
from ntsecuritycon import SECURITY_CREATOR_SID_AUTHORITY, SECURITY_WORLD_SID_AUTHORITY, SECURITY_WORLD_RID, SECURITY_CREATOR_OWNER_RID	#@UnresolvedImport


class NamedPipeListener(Thread):
	def __init__(self, pipe_name, new_connection_cb):
		Thread.__init__(self, name="NamedPipeListener")
		self.pipe_name = pipe_name
		self.new_connection_cb = new_connection_cb

		self.hWaitStop = CreateEvent(None, 0, 0, None)
		self.overlapped = pywintypes.OVERLAPPED()
		self.overlapped.hEvent = CreateEvent(None,0,0,None)
		self.exit_loop = False
		self.terminated = False

	def stop(self):
		log("%s.stop()", self)
		if self.exit_loop:
			return
		self.exit_loop = True
		self.hWaitStop.close()

	def CreatePipeSecurityObject(self):
		# Create a security object giving World read/write access,
		# but only "Owner" modify access.
		sa = pywintypes.SECURITY_ATTRIBUTES()
		sidEveryone = pywintypes.SID()
		sidEveryone.Initialize(SECURITY_WORLD_SID_AUTHORITY,1)
		sidEveryone.SetSubAuthority(0, SECURITY_WORLD_RID)
		sidCreator = pywintypes.SID()
		sidCreator.Initialize(SECURITY_CREATOR_SID_AUTHORITY,1)
		sidCreator.SetSubAuthority(0, SECURITY_CREATOR_OWNER_RID)
		acl = pywintypes.ACL()
		acl.AddAccessAllowedAce(FILE_GENERIC_READ|FILE_GENERIC_WRITE, sidEveryone)
		acl.AddAccessAllowedAce(FILE_ALL_ACCESS, sidCreator)
		sa.SetSecurityDescriptorDacl(1, acl, 0)
		return sa

	def run(self):
		try:
			self.do_run()
		except Exception:
			log.error("run()", exc_info=True)
		finally:
			self.terminated = True

	def do_run(self):
		while not self.exit_loop:
			sa = self.CreatePipeSecurityObject()
			pipeHandle = CreateNamedPipe(self.pipe_name,
					PIPE_ACCESS_DUPLEX| FILE_FLAG_OVERLAPPED,
					PIPE_TYPE_MESSAGE | PIPE_READMODE_BYTE,
					PIPE_UNLIMITED_INSTANCES,	   # max instances
					0, 0, 6000, sa)
			if self.exit_loop:
				break
			try:
				hr = ConnectNamedPipe(pipeHandle, self.overlapped)
			except error as e:
				log.error("error connecting pipe: %s", e)
				CloseHandle(pipeHandle)
				break
			log("connected to pipe")
			if self.exit_loop:
				break
			if hr==winerror.ERROR_PIPE_CONNECTED:
				# Client is already connected - signal event
				SetEvent(self.overlapped.hEvent)
			rc = WaitForMultipleObjects((self.hWaitStop, self.overlapped.hEvent), 0, INFINITE)
			log("wait ended with rc=%s, exit_loop=%s", rc, self.exit_loop)
			if rc==WAIT_OBJECT_0 or self.exit_loop:
				# Stop event
				break
			else:
				self.new_connection_cb(self, pipeHandle)


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
		listener = None
		try:
			def new_connection(listener, pipeHandle):
				# Pipe event - spawn thread to deal with it.
				listener.writer = PipeWriter(pipeHandle)
				listener.writer.start()
				def packet_handler(data):
					log.info("packet_handler(%s)", data)
					listener.writer.send(data)
				listener.reader = PipeReader(pipeHandle, packet_handler)
				listener.reader.start()
			listener = NamedPipeListener(PIPE_NAME, new_connection)
			listener.reader = None
			listener.writer = None
			def stop(*args):
				log.warn("stop%s", args)
				listener.stop()
				for x in (listener.reader, listener.writer):
					if x:
						x.stop()
			import signal
			signal.signal(signal.SIGINT, stop)
			signal.signal(signal.SIGTERM, stop)
			with console_event_catcher(stop):
				listener.start()
		except Exception:
			log.error("%s stopped", listener, exc_info=True)
			if listener:
				listener.stop()
		if listener:
			listener.join()
		import sys
		sys.exit(0)

if __name__ == "__main__":
	main()
