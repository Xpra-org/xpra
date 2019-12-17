#!/usr/bin/env python

import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk  #pylint: disable=wrong-import-position

width = 400
height = 200

def make_win(title="Test Geometry Hints",
			min_width=-1, min_height=-1,
			max_width=-1, max_height=-1,
			base_width=-1, base_height=-1,
			width_inc=-1, height_inc=-1):
	window = Gtk.Window(title=title)
	window.connect("delete_event", Gtk.main_quit)
	geom = Gdk.Geometry()
	geom.base_width = base_width
	geom.base_height = base_height
	geom.width_inc = width_inc
	geom.height_inc = height_inc
	geom.min_width = min_width
	geom.min_height = min_height
	geom.max_width = max_width
	geom.max_height = max_height
	mask = 0
	if base_width>0 or base_height>0:
		mask |= Gdk.WindowHints.BASE_SIZE
	if width_inc>0 or height_inc>0:
		mask |= Gdk.WindowHints.RESIZE_INC
	if min_width>0 or min_height>0:
		mask |= Gdk.WindowHints.MIN_SIZE
	if max_width>0 or max_height>0:
		mask |= Gdk.WindowHints.MAX_SIZE
	window.set_geometry_hints(None, geom, Gdk.WindowHints(mask))
	window.show_all()
	if sys.platform.startswith("win"):
		fixup_window_style(window)

def fixup_window_style(window):
	from xpra.platform.win32.gui import get_window_handle
	from xpra.platform.win32.common import GetWindowLongW, SetWindowLongW
	from xpra.platform.win32 import win32con
	hwnd = get_window_handle(window)
	cur_style = GetWindowLongW(hwnd, win32con.GWL_STYLE)
	#re-add taskbar menu:
	style = cur_style
	if cur_style & win32con.WS_CAPTION:
		style |= win32con.WS_SYSMENU
		style |= win32con.WS_MAXIMIZEBOX
		style |= win32con.WS_MINIMIZEBOX
	if False:
		#not resizable
		style &= ~win32con.WS_MAXIMIZEBOX
		style &= ~win32con.WS_SIZEBOX
	if style!=cur_style:
		print("fixup_window_style() from %#x to %#x" % (cur_style, style))
		SetWindowLongW(hwnd, win32con.GWL_STYLE, style)

def main():
	#make_win("tiny", 0, 0, 5, 5)
	#make_win("standard", 0, 0, width, height)
	#make_win("half-or-more", width//2, height//2)
	make_win("half-to-twice", width//2, height//2, width*2, height*2)
	#apply_maxsize_hints(ClientWindow(1), {
	#    b'min_width': 132, b'min_height': 38,
	#    b'base_width': 19, b'base_height': 4,
	#    b'width_inc': 6, b'height_inc': 13,
	#    b'max_width': 32767, b'max_height': 32764,
	#}) found min: 132x38, max: 32767x32764
	#make_win("xterm-increment", 132, 38, 32767, 32764, 19, 4, 6, 13)
	make_win("xterm-increment", 132, 38, 0, 0, 19, 4, 6, 13)
	Gtk.main()


if __name__ == "__main__":
	main()
