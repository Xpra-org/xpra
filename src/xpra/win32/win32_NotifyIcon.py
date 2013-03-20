#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Low level support for the "system tray" on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"

#@PydevCodeAnalysisIgnore

from win32api import *
# Try and use XP features, so we get alpha-blending etc.
try:
	from winxpgui import *
except ImportError:
	from win32gui import *
import win32con

import sys, os

from wimpiggy.log import Logger
log = Logger()

class win32NotifyIcon:
	def __init__(self, title, notify_callback, exit_callback, command_callback=None, iconPathName=None):
		self.title = title[:127]
		self.notify_callback = notify_callback
		self.exit_callback = exit_callback
		self.command_callback = command_callback
		self.current_icon = None
		self.closed = False
		self._message_id = win32con.WM_USER+20		#a message id we choose
		message_map = {
			win32con.WM_DESTROY	: self.OnDestroy,
			win32con.WM_COMMAND	: self.OnCommand,
			self._message_id	: self.OnTaskbarNotify,
		}
		# Register the Window class.
		wc = WNDCLASS()
		self.hinst = wc.hInstance = GetModuleHandle(None)
		wc.lpszClassName = "win32StatusIcon"
		wc.lpfnWndProc = message_map # could also specify a wndproc.
		classAtom = RegisterClass(wc)
		# Create the Window.
		style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU
		self.hwnd = CreateWindow(classAtom, self.title+" StatusIcon Window", style, \
		0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT, \
		0, 0, self.hinst, None)
		UpdateWindow(self.hwnd)
		self.current_icon = self.win32LoadIcon(iconPathName)
		Shell_NotifyIcon(NIM_ADD, self.make_nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))

	def make_nid(self, flags):
		return (self.hwnd, 0, flags, self._message_id, self.current_icon, self.title)

	def set_blinking(self, on):
		#FIXME: implement blinking on win32 using a timer
		pass

	def set_tooltip(self, name):
		self.title = name[:127]
		Shell_NotifyIcon(NIM_MODIFY, self.make_nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))

	def set_icon(self, iconPathName):
		self.current_icon = self.win32LoadIcon(iconPathName)
		Shell_NotifyIcon(NIM_MODIFY, self.make_nid(NIF_ICON))

	def win32LoadIcon(self, iconPathName):
		icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
		try:
			return	LoadImage(self.hinst, iconPathName, win32con.IMAGE_ICON, 0, 0, icon_flags)
		except Exception, e:
			log.error("Failed to load icon at %s: %s", iconPathName, e)
			return	LoadIcon(0, win32con.IDI_APPLICATION)

	def OnCommand(self, hwnd, msg, wparam, lparam):
		log.debug("OnCommand(%s,%s,%s,%s)", hwnd, msg, wparam, lparam)
		cid = LOWORD(wparam)
		if self.command_callback:
			self.command_callback(self.hwnd, cid)

	def OnDestroy(self, hwnd, msg, wparam, lparam):
		log.debug("OnDestroy(%s,%s,%s,%s) closed=%s, exit_callback=%s",
				hwnd, msg, wparam, lparam, self.closed, self.exit_callback)
		if self.closed:
			return
		self.closed = True
		try:
			nid = (self.hwnd, 0)
			log.debug("OnDestroy(..) calling Shell_NotifyIcon(NIM_DELETE, %s)", nid)
			Shell_NotifyIcon(NIM_DELETE, nid)
			log.debug("OnDestroy(..) calling exit_callback=%s", self.exit_callback)
			if self.exit_callback:
				self.exit_callback()
		except:
			log.error("OnDestroy(..)", exc_info=True)

	def OnTaskbarNotify(self, hwnd, msg, wparam, lparam):
		log.debug("OnTaskbarNotify(%s,%s,%s,%s)", hwnd, msg, wparam, lparam)
		if lparam==win32con.WM_LBUTTONUP or lparam==win32con.WM_RBUTTONUP:
			self.notify_callback(hwnd)
		return 1

	def close(self):
		log.debug("win32NotifyIcon.close() exit_callback=%s", self.exit_callback)
		self.exit_callback = None
		self.OnDestroy(0, None, None, None)

	def get_geometry(self):
		return	GetWindowRect(self.hwnd)


def main():
	def notify_callback(hwnd):
		menu = CreatePopupMenu()
		AppendMenu( menu, win32con.MF_STRING, 1024, "Generate balloon")
		AppendMenu( menu, win32con.MF_STRING, 1025, "Exit")
		pos = GetCursorPos()
		SetForegroundWindow(hwnd)
		TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos[0], pos[1], 0, hwnd, None)
		PostMessage(hwnd, win32con.WM_NULL, 0, 0)

	def command_callback(hwnd, cid):
		if cid == 1024:
			from winswitch.ui.win32_balloon import notify
			notify(hwnd, "hello", "world")
		elif cid == 1025:
			print("Goodbye")
			DestroyWindow(hwnd)
		else:
			print("OnCommand for ID=%s" % cid)

	def win32_quit():
		PostQuitMessage(0) # Terminate the app.

	iconPathName = os.path.abspath(os.path.join( sys.prefix, "pyc.ico"))
	w=win32StatusIcon(notify_callback, win32_quit, command_callback, iconPathName)
	print("win32StatusIcon=%s" % w)
	PumpMessages()


if __name__=='__main__':
	main()
