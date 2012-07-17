# This file is part of Parti.
# Copyright (C) 2009-2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

""" client_launcher.py

This is a simple GUI for starting the xpra client.

"""

import sys
import os.path
import tempfile
import inspect

try:
	import _thread	as thread		#@UnresolvedImport @UnusedImport (python3)
except:
	import thread					#@Reimport
import subprocess

import pygtk
pygtk.require('2.0')
import gtk
import pango
import gobject

import socket
from xpra.client import XpraClient

APPLICATION_NAME = "Xpra Launcher"


def valid_dir(path):
	try:
		return path and os.path.exists(path) and os.path.isdir(path)
	except:
		return False

"""
	Start of crappy platform workarounds
	SUBPROCESS_CREATION_FLAGS is for win32 to avoid creating DOS windows for console applications
	ICONS_DIR is for location the icons
"""
SUBPROCESS_CREATION_FLAGS = 0
APP_DIR = os.getcwd()
ICONS_DIR = None
if sys.platform.startswith("win"):
	try:
		import win32process			#@UnresolvedImport
		SUBPROCESS_CREATION_FLAGS = win32process.CREATE_NO_WINDOW
	except:
		pass		#tried our best...

	if getattr(sys, 'frozen', ''):
		#on win32 we must send stdout to a logfile to prevent an alert box on exit shown by py2exe
		#UAC in vista onwards will not allow us to write where the software is installed, so place the log file in "~/Application Data"
		appdata = os.environ.get("APPDATA")
		if not os.path.exists(appdata):
			os.mkdir(appdata)
		log_path = os.path.join(appdata, "Xpra")
		if not os.path.exists(log_path):
			os.mkdir(log_path)
		log_file = os.path.join(log_path, "Xpra.log")
		sys.stdout = open(log_file, "a")
		sys.stderr = sys.stdout
		APP_DIR = os.path.dirname(sys.executable)
		ICONS_DIR = os.path.join(APP_DIR, "icons")
elif sys.platform.startswith("darwin"):
	rsc = None
	try:
		import gtk_osxapplication		#@UnresolvedImport
		rsc = gtk_osxapplication.quartz_application_get_resource_path()
	except:
		pass
	if rsc:
		CONTENTS = "/Contents/"
		i = rsc.rfind(CONTENTS)
		if i>0:
			APP_DIR = rsc[:i+len(CONTENTS)]
		ICONS_DIR = os.path.join(rsc, "icons")
if not ICONS_DIR or not os.path.exists(ICONS_DIR):
	if not valid_dir(APP_DIR):
		APP_DIR = os.path.dirname(inspect.getfile(sys._getframe(1)))
	if not valid_dir(APP_DIR):
		APP_DIR = os.path.dirname(sys.argv[0])
	if not valid_dir(APP_DIR):
		APP_DIR = os.getcwd()
	for x in ["%s/icons" % APP_DIR, "/usr/local/share/icons", "/usr/share/icons"]:
		if os.path.exists(x):
			ICONS_DIR = x
			break


LOSSY_5 = "lowest quality"
LOSSY_20 = "low quality"
LOSSY_50 = "average quality"
LOSSY_90 = "best lossy quality"

XPRA_ENCODING_OPTIONS = [ "jpeg", "x264", "png", "rgb24", "vpx" ]
try:
	from xpra.scripts.main import ENCODINGS
	XPRA_ENCODING_OPTIONS = ENCODINGS
except:
	pass

XPRA_COMPRESSION_OPTIONS = [LOSSY_5, LOSSY_20, LOSSY_50, LOSSY_90]
XPRA_COMPRESSION_OPTIONS_DICT = {LOSSY_5 : 5,
						LOSSY_20 : 20,
						LOSSY_50 : 50,
						LOSSY_90 : 90
						}

# Default connection options
from wimpiggy.util import AdHocStruct
xpra_opts = AdHocStruct()
xpra_opts.encoding = "png"
xpra_opts.jpegquality = 90
xpra_opts.host = "127.0.0.1"
xpra_opts.port = 16010
xpra_opts.mode = "tcp"
xpra_opts.autoconnect = False
xpra_opts.no_tray = False
xpra_opts.password_file = False



def get_icon_from_file(filename):
	try:
		if not os.path.exists(filename):
			return	None
		f = open(filename, mode='rb')
		data = f.read()
		f.close()
		loader = gtk.gdk.PixbufLoader()
		loader.write(data)
		loader.close()
	except Exception, e:
		print("get_icon_from_file(%s) %s" % (filename, e))
		return	None
	pixbuf = loader.get_pixbuf()
	return pixbuf

def add_close_accel(window, callback):
	# key accelerators
	accel_group = gtk.AccelGroup()
	accel_group.connect_group(ord('w'), gtk.gdk.CONTROL_MASK, gtk.ACCEL_LOCKED, callback)
	window.add_accel_group(accel_group)
	accel_group = gtk.AccelGroup()
	key, mod = gtk.accelerator_parse('<Alt>F4')
	accel_group.connect_group(key, mod, gtk.ACCEL_LOCKED, callback)
	window.add_accel_group(accel_group)

def scaled_image(pixbuf, icon_size):
	return	gtk.image_new_from_pixbuf(pixbuf.scale_simple(icon_size,icon_size,gtk.gdk.INTERP_BILINEAR))


class ApplicationWindow:

	def	__init__(self):
		pass
	
	def create_window(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.connect("destroy", self.destroy)
		self.window.set_default_size(400, 300)
		self.window.set_border_width(20)
		self.window.set_title(APPLICATION_NAME)
		icon_pixbuf = get_icon_from_file(os.path.join(ICONS_DIR, "xpra.png"))
		if icon_pixbuf:
			self.window.set_icon(icon_pixbuf)
		self.window.set_position(gtk.WIN_POS_CENTER)

		vbox = gtk.VBox(False, 0)
		vbox.set_spacing(15)

		# Title
		hbox = gtk.HBox(False, 0)
		if icon_pixbuf:
			image = gtk.Image()
			image.set_from_pixbuf(icon_pixbuf)
			hbox.pack_start(image)
		label = gtk.Label("Connect to xpra server")
		label.modify_font(pango.FontDescription("sans 13"))
		hbox.pack_start(label)
		vbox.pack_start(hbox)

		# Mode:
		hbox = gtk.HBox(False, 20)
		hbox.set_spacing(20)
		hbox.pack_start(gtk.Label("Mode: "))
		self.mode_combo = gtk.combo_box_new_text()
		self.mode_combo.get_model().clear()
		self.mode_combo.append_text("tcp")
		if not sys.platform.startswith("win"):
			#when we fix the build on win32 to include putty
			#this can be enabled again:
			self.mode_combo.append_text("ssh")
		if xpra_opts.mode == "tcp" or sys.platform.startswith("win"):
			self.mode_combo.set_active(0)
		else:
			self.mode_combo.set_active(1)
		def mode_changed(*args):
			if self.mode_combo.get_active_text()=="ssh":
				self.port_entry.set_text("22")
			else:
				self.port_entry.set_text("%s" % xpra_opts.port)
		self.mode_combo.connect("changed", mode_changed)
		hbox.pack_start(self.mode_combo)
		vbox.pack_start(hbox)

		# Encoding:
		hbox = gtk.HBox(False, 20)
		hbox.set_spacing(20)
		hbox.pack_start(gtk.Label("Encoding: "))
		self.encoding_combo = gtk.combo_box_new_text()
		self.encoding_combo.get_model().clear()
		for option in XPRA_ENCODING_OPTIONS:
			self.encoding_combo.append_text(option)
		self.encoding_combo.set_active(XPRA_ENCODING_OPTIONS.index(xpra_opts.encoding))
		hbox.pack_start(self.encoding_combo)
		vbox.pack_start(hbox)

		# JPEG:
		hbox = gtk.HBox(False, 20)
		hbox.set_spacing(20)
		self.jpeg_label = gtk.Label("JPEG Compression: ")
		hbox.pack_start(self.jpeg_label)
		self.jpeg_combo = gtk.combo_box_new_text()
		self.jpeg_combo.get_model().clear()
		for option in XPRA_COMPRESSION_OPTIONS:
			self.jpeg_combo.append_text(option)
		self.jpeg_combo.set_active(2)
		hbox.pack_start(self.jpeg_combo)
		vbox.pack_start(hbox)
		self.encoding_combo.connect("changed", self.encoding_changed)

		# Host:Port
		hbox = gtk.HBox(False, 0)
		hbox.set_spacing(5)
		self.host_entry = gtk.Entry(max=128)
		self.host_entry.set_width_chars(40)
		self.host_entry.set_text(xpra_opts.host)
		self.port_entry = gtk.Entry(max=5)
		self.port_entry.set_width_chars(5)
		self.port_entry.set_text(str(xpra_opts.port))
		hbox.pack_start(self.host_entry)
		hbox.pack_start(gtk.Label(":"))
		hbox.pack_start(self.port_entry)
		vbox.pack_start(hbox)

		# Password
		hbox = gtk.HBox(False, 0)
		hbox.set_spacing(20)
		self.password_entry = gtk.Entry(max=128)
		self.password_entry.set_width_chars(30)
		self.password_entry.set_text("")
		self.password_entry.set_visibility(False)
		hbox.pack_start(gtk.Label("Password: "))
		hbox.pack_start(self.password_entry)
		vbox.pack_start(hbox)

		# Info Label
		self.info = gtk.Label()
		self.info.set_line_wrap(True)
		self.info.set_size_request(360, -1)
		color_obj = gtk.gdk.color_parse("red")
		if color_obj:
			self.info.modify_fg(gtk.STATE_NORMAL, color_obj)
		vbox.pack_start(self.info)

		# Connect button:
		self.button = gtk.Button("Connect")
		self.button.connect("clicked", self.connect_clicked, None)
		connect_icon = get_icon_from_file(os.path.join(ICONS_DIR, "retry.png"))
		if connect_icon:
			self.button.set_image(scaled_image(connect_icon, 24))
		vbox.pack_start(self.button)

		def accel_close(*args):
			gtk.main_quit()

		add_close_accel(self.window, accel_close)

		self.window.add(vbox)

	def run(self):
		self.window.show_all()
		self.encoding_changed()
		gtk.main()

	def encoding_changed(self, *args):
		is_jpeg = self.encoding_combo.get_active_text()=="jpeg"
		if is_jpeg:
			self.jpeg_combo.show()
			self.jpeg_label.show()
		else:
			self.jpeg_combo.hide()
			self.jpeg_label.hide()

	def do_connect(self):
		if xpra_opts.mode=="tcp" and not sys.platform.startswith("win"):
			""" Use built-in connector (faster and gives feedback) - does not work on win32... (dunno why) """
			self.connect_tcp()
		else:
			self.launch_xpra()

	def connect_clicked(self, *args):
		self.update_options_from_gui()
		self.do_connect()

	def connect_tcp(self):
		self.info.set_text("Connecting.")
		host = xpra_opts.host
		port = xpra_opts.port
		self.info.set_text("Connecting..")
		try:
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.info.set_text("Connecting...")
			sock.connect((host, int(port)))
		except Exception, e:
			self.info.set_text("Socket error: %s" % e)
			print("error %s" % e)
			return
		self.info.set_text("Connection established")
		try:
			from xpra.protocol import SocketConnection
			global socket_wrapper
			socket_wrapper = SocketConnection(sock, "xprahost")
		except Exception, e:
			self.info.set_text("Xpra Client error: %s" % e)
			print("Xpra Client error: %s" % e)
			return
		self.window.hide()
		# launch Xpra client in the same gtk.main():
		from wimpiggy.util import gtk_main_quit_on_fatal_exceptions_enable
		gtk_main_quit_on_fatal_exceptions_enable()
		opts = AdHocStruct()
		opts.clipboard = True
		opts.pulseaudio = True
		opts.password_file = xpra_opts.password_file
		opts.title = "@title@ on @client-machine@"
		opts.encoding = xpra_opts.encoding
		opts.jpegquality = xpra_opts.jpegquality
		opts.max_bandwidth = 0.0
		opts.auto_refresh_delay = 0.0
		opts.key_shortcuts = []
		opts.compression_level = 3
		from xpra.platform import DEFAULT_SSH_CMD
		opts.ssh = DEFAULT_SSH_CMD
		opts.remote_xpra = ".xpra/run-xpra"
		opts.debug = None
		opts.no_tray = False
		opts.dock_icon = None
		opts.tray_icon = None
		opts.window_icon = None
		opts.readonly = False
		opts.session_name = "Xpra session"
		opts.mmap = True
		opts.keyboard_sync = True
		opts.send_pings = False

		import logging
		logging.root.setLevel(logging.INFO)
		logging.root.addHandler(logging.StreamHandler(sys.stderr))

		app = XpraClient(socket_wrapper, opts)
		app.run()

	def launch_xpra(self):
		thread.start_new_thread(self.do_launch_xpra, ())

	def do_launch_xpra(self):
		""" Launches Xpra in a new process """
		self.window.hide()
		try:
			self.info.set_text("Launching")
			process = self.start_xpra_process()
			(out,err) = process.communicate()
			print("stdout=%s" % out)
			print("stderr=%s" % err)
			ret = process.wait()
			def show_result(out, err):
				if len(out)>255:
					out = "..."+out[len(out)-255:]
				if len(err)>255:
					err = "..."+err[len(err)-255:]
				self.info.set_text("command terminated with status %s,\noutput:\n%s\nerror:\n%s" % (ret, out, err))
				self.window.show_all()
			gobject.idle_add(show_result, out, err)
		except Exception, e:
			print("error: %s" % e)
			self.info.set_text("Error launching: %s" % (e))

	def start_xpra_process(self):
		#ret = os.system(" ".join(args))
		cmd = "xpra"
		if sys.platform.startswith("win"):
			if hasattr(sys, "frozen"):
				exedir = os.path.dirname(sys.executable)
			else:
				exedir = os.path.dirname(sys.argv[0])
			cmd = os.path.join(exedir, "xpra.exe")
			if not os.path.exists(cmd):
				self.info.set_text("Xpra command not found!")
				return
		uri = "%s:%s:%s" % (xpra_opts.mode, xpra_opts.host, xpra_opts.port)
		args = [cmd, "attach", uri]
		args.append("--encoding=%s" % xpra_opts.encoding)
		if xpra_opts.encoding=="jpeg":
			args.append("--jpeg-quality=%s" % xpra_opts.jpegquality)
		if xpra_opts.password_file:
			args.append("--password-file=%s" % xpra_opts.password_file)
		print("Running %s" % args)
		process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, creationflags=SUBPROCESS_CREATION_FLAGS)
		return process

	def update_options_from_gui(self):
		xpra_opts.host = self.host_entry.get_text()
		xpra_opts.port = self.port_entry.get_text()
		xpra_opts.encoding = self.encoding_combo.get_active_text()
		xpra_opts.jpegquality = XPRA_COMPRESSION_OPTIONS_DICT.get(self.jpeg_combo.get_active_text())
		xpra_opts.mode = self.mode_combo.get_active_text()
		password = self.password_entry.get_text()
		if len(password) > 0:
			xpra_opts.password_file = create_password_file(password)

	def destroy(self, *args):
		gtk.main_quit()

def create_password_file(password):
	pass_file = tempfile.NamedTemporaryFile(delete = False)
	pass_file.write("%s\n" % password)
	xpra_opts.password_file=pass_file.name
	pass_file.close()
	return pass_file.name

def update_options_from_file(filename):
	propFile = open(filename, "rU")
	propDict = dict()
	for propLine in propFile:
		propDef= propLine.strip()
		if len(propDef) == 0:
			continue
		if propDef[0] in ( '!', '#' ):
			continue
		punctuation = [ propDef.find(c) for c in ':= ' ] + [ len(propDef) ]
		found = min( [ pos for pos in punctuation if pos != -1 ] )
		name= propDef[:found].rstrip()
		value= propDef[found:].lstrip(":= ").rstrip()
		propDict[name] = value
	propFile.close()

	for prop in ["host", "port", "encoding", "jpegquality", "mode", "autoconnect"]:
		val = propDict.get(prop)
		if val:
			setattr(xpra_opts, prop, val)
	val = propDict.get("password")
	if val:
		xpra_opts.password_file = create_password_file(val)

def main():
	try:
		import glib
		glib.set_application_name(APPLICATION_NAME)
	except:
		pass

	if len(sys.argv) == 2:
		update_options_from_file(sys.argv[1])
	app = ApplicationWindow()
	if xpra_opts.autoconnect == "True":
		#file says we should connect, do that only:
		process = app.start_xpra_process()
		return process.wait()
	else:
		app.create_window()
		app.run()
	if xpra_opts.password_file:
		os.unlink(xpra_opts.password_file)
	return 0

if __name__ == "__main__":
	v = main()
	sys.exit(v)
