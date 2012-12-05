#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
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
	def __init__(self, application_name, notify_callback, exit_callback, command_callback=None, iconPathName=None):
		self.application_name = application_name
		self.notify_callback = notify_callback
		self.exit_callback = exit_callback
		self.command_callback = command_callback
		self.closed = False
		message_map = {
			win32con.WM_DESTROY: self.OnDestroy,
			win32con.WM_COMMAND: self.OnCommand,
			win32con.WM_USER+20: self.OnTaskbarNotify,
		}
		# Register the Window class.
		wc = WNDCLASS()
		self.hinst = wc.hInstance = GetModuleHandle(None)
		wc.lpszClassName = "win32StatusIcon"
		wc.lpfnWndProc = message_map # could also specify a wndproc.
		classAtom = RegisterClass(wc)
		# Create the Window.
		style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU
		self.hwnd = CreateWindow(classAtom, self.application_name+" StatusIcon Window", style, \
		0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT, \
		0, 0, self.hinst, None)
		UpdateWindow(self.hwnd)
		hicon = self.win32LoadIcon(iconPathName)
		flags = NIF_ICON | NIF_MESSAGE | NIF_TIP
		nid = (self.hwnd, 0, flags, win32con.WM_USER+20, hicon, self.application_name)
		Shell_NotifyIcon(NIM_ADD, nid)

	def set_icon(self, iconPathName):
		new_icon = self.win32LoadIcon(iconPathName)
		flags = NIF_ICON | NIF_MESSAGE | NIF_TIP
		nid = (self.hwnd, 0, flags, win32con.WM_USER+20, new_icon, self.application_name)
		Shell_NotifyIcon(NIM_MODIFY, nid)

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
		log.debug("OnDestroy(%s,%s,%s,%s)", hwnd, msg, wparam, lparam)
		if self.closed:
			return
		self.closed = True
		try:
			nid = (self.hwnd, 0)
			Shell_NotifyIcon(NIM_DELETE, nid)
			self.exit_callback()
		except Exception, e:
			log.error("OnDestroy error: %s", e)

	def OnTaskbarNotify(self, hwnd, msg, wparam, lparam):
		log.debug("OnTaskbarNotify(%s,%s,%s,%s)", hwnd, msg, wparam, lparam)
		if lparam==win32con.WM_LBUTTONUP or lparam==win32con.WM_RBUTTONUP:
			self.notify_callback(hwnd)
		return 1

	def close(self):
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
