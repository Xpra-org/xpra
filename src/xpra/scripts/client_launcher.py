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
SITE_URL = "http://xpra.org/"
SITE_DOMAIN = "xpra.org"
SUBPROCESS_CREATION_FLAGS = 0
APP_DIR = os.getcwd()
ICONS_DIR = None
GPL2 = "Your installation may be corrupted, the license text for GPL version 2 could not be found,\nplease refer to:\nhttp://www.gnu.org/licenses/gpl-2.0.txt"


def valid_dir(path):
	try:
		return path and os.path.exists(path) and os.path.isdir(path)
	except:
		return False

def get_icon_from_file(filename):
	try:
		if not os.path.exists(filename):
			print("%s does not exist" % filename)
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

def get_icon(name):
	global ICONS_DIR
	if not ICONS_DIR:
		print("ICONS_DIR not defined!")
		return	None
	filename = os.path.join(ICONS_DIR, name)
	if not os.path.exists(filename):
		print("%s does not exist" % filename)
		return	None
	if not os.path.isfile(filename):
		print("%s is not a file!" % filename)
		return	None
	return get_icon_from_file(filename)


prepare_window = None
"""
	Start of crappy platform workarounds
	SUBPROCESS_CREATION_FLAGS is for win32 to avoid creating DOS windows for console applications
	ICONS_DIR is for location the icons
"""
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
		if rsc:
			RESOURCES = "/Resources/"
			CONTENTS = "/Contents/"
			i = rsc.rfind(RESOURCES)
			if i>0:
				rsc = rsc[:i+len(RESOURCES)]
			i = rsc.rfind(CONTENTS)
			if i>0:
				APP_DIR = rsc[:i+len(CONTENTS)]
			ICONS_DIR = os.path.join(rsc, "share", "xpra", "icons")
			gpl2_file = os.path.join(rsc, "share", "xpra", "COPYING")
			if os.path.exists(gpl2_file):
				try:
					f = open(gpl2_file, mode='rb')
					GPL2 = f.read()
				finally:
					if f:
						f.close()

		def prepare_window_osx(window):
			def quit_launcher(*args):
				gtk.main_quit()
			osxapp = gtk_osxapplication.OSXApplication()
			icon = get_icon("xpra.png")
			if icon:
				osxapp.set_dock_icon_pixbuf(icon)
			#menu:
			menu = gtk.MenuBar()

			# Quit (will be hidden - see below)
			quit_item = gtk.MenuItem("Quit")
			quit_item.connect("activate", quit_launcher)
			menu.add(quit_item)
	
			# Add to the application menu:
			item = gtk.MenuItem("About")
			item.show()
			global about_dialog
			about_dialog = None
			def about(*args):
				import webbrowser
				global about_dialog, GPL2
				if about_dialog:
					about_dialog.show()
					about_dialog.present()
					return
				dialog = gtk.AboutDialog()
				def on_website_hook(dialog, web, *args):
					''' called when the website item is selected '''
					webbrowser.open(SITE_URL)
				def on_email_hook(dialog, mail, *args):
					webbrowser.open("mailto://shifter-users@lists.devloop.org.uk")
				gtk.about_dialog_set_url_hook(on_website_hook)
				gtk.about_dialog_set_email_hook(on_email_hook)
				dialog.set_name("Xpra")
				from xpra import __version__
				dialog.set_version(__version__)
				dialog.set_copyright('Copyright (c) 2012, Nagafix Ltd')
				dialog.set_authors(('Antoine Martin <antoine@nagafix.co.uk>',''))
				dialog.set_license(str(GPL2))
				dialog.set_website(SITE_URL)
				dialog.set_website_label(SITE_DOMAIN)
				dialog.set_logo(get_icon("xpra.png"))
				dialog.set_program_name(APPLICATION_NAME)
				def response(*args):
					dialog.destroy()
					global about_dialog
					about_dialog = None
				dialog.connect("response", response)
				about_dialog = dialog
				dialog.show()
			item.connect("activate", about)
			item.show()
			
			#now set the dock/main menu
			menu.show_all()
			quit_item.hide()
			menu.hide()
			# We need to add it to a widget (otherwise it just does not work)
			window.vbox.add(menu)
			osxapp.set_menu_bar(menu)
			osxapp.insert_app_menu_item(item, 0)
			osxapp.ready()
		prepare_window = prepare_window_osx
	except Exception, e:
		print("error setting up menu: %s" % e)
else:
	#/usr/share/xpra
	APP_DIR = os.path.join(sys.exec_prefix, "share", "xpra")
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

ENCODING_OPTIONS = [ "jpeg", "x264", "png", "rgb24", "vpx" ]
try:
	from xpra.scripts.main import ENCODINGS
	ENCODING_OPTIONS = ENCODINGS
except:
	pass

# find the default encoding (below list is in our hard-coded preferred order):
DEFAULT_ENCODING = ENCODING_OPTIONS[0]
for enc in [ "png", "x264", "vpx", "jpeg", "rgb24" ]:
	if enc in ENCODING_OPTIONS:
		DEFAULT_ENCODING = enc
		break

XPRA_COMPRESSION_OPTIONS = [LOSSY_5, LOSSY_20, LOSSY_50, LOSSY_90]
XPRA_COMPRESSION_OPTIONS_DICT = {LOSSY_5 : 5,
						LOSSY_20 : 20,
						LOSSY_50 : 50,
						LOSSY_90 : 90
						}

# Default connection options
from xpra.scripts.main import read_xpra_defaults
defaults = read_xpra_defaults()
def default_str(varname, default_value, valid_values=None):
	if varname not in defaults:
		return default_value
	v = defaults.get(varname)
	if valid_values is not None and v not in valid_values:
		return default_value
	return v
def str_to_int(s, default_value):
	try:
		return int(s)
	except:
		return default_value
def default_int(varname, default_value):
	if varname not in defaults:
		return default_value
	return str_to_int(defaults.get(varname), default_value)
def str_to_bool(v, default_value):
	if type(v)==str:
		v = v.lower()
	if v in ["yes", "true", "1"]:
		return  True
	if v in ["no", "false", "0"]:
		return  False
	return default_value
def default_bool(varname, default_value):
	if varname not in defaults:
		return default_value
	v = defaults.get(varname)
	return str_to_bool(v, default_value)

from wimpiggy.util import AdHocStruct
xpra_opts = AdHocStruct()
xpra_opts.encoding = default_str("encoding", DEFAULT_ENCODING, ENCODING_OPTIONS)
xpra_opts.jpegquality = default_int("jpegquality", 90)
xpra_opts.host = defaults.get("host", "127.0.0.1")
xpra_opts.port = default_int("port", 10000)
xpra_opts.mode = default_str("mode", "tcp", ["tcp", "ssh"])
xpra_opts.debug = default_bool("debug", False)
xpra_opts.no_tray = default_bool("debug", False)
xpra_opts.dock_icon = default_str("dock-icon", "")
xpra_opts.tray_icon = default_str("tray-icon", "")
xpra_opts.window_icon = default_str("window-icon", "")
xpra_opts.password_file = default_str("password-file", "")
xpra_opts.clipboard = default_bool("clipboard", True)
xpra_opts.pulseaudio = default_bool("pulseaudio", True)
xpra_opts.mmap = default_bool("mmap", True)
xpra_opts.mmap_group = default_bool("mmap-group", False)
xpra_opts.readonly = default_bool("readonly", False)
xpra_opts.keyboard_sync = default_bool("keyboard-sync", True)
xpra_opts.compression_level = default_int("compression", 3)
xpra_opts.send_pings = default_bool("pings", False)
xpra_opts.dpi = default_int("dpi", 96)
xpra_opts.cursors = default_bool("cursors", True)
xpra_opts.bell = default_bool("bell", True)
xpra_opts.notifications = default_bool("notifications", True)
#these would need testing/work:
xpra_opts.auto_refresh_delay = 0.0
xpra_opts.max_bandwidth = 0.0
xpra_opts.key_shortcuts = ["Meta+Shift+F4:quit"]
#these cannot be set in the xpra.conf (would not make sense):
xpra_opts.autoconnect = False


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
		icon_pixbuf = get_icon("xpra.png")
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
		for option in ENCODING_OPTIONS:
			self.encoding_combo.append_text(option)
		self.encoding_combo.set_active(ENCODING_OPTIONS.index(xpra_opts.encoding))
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
		connect_icon = get_icon("retry.png")
		if connect_icon:
			self.button.set_image(scaled_image(connect_icon, 24))
		vbox.pack_start(self.button)

		def accel_close(*args):
			gtk.main_quit()

		add_close_accel(self.window, accel_close)
		self.window.vbox = vbox

		self.window.add(vbox)
		self.window.show_all()

		global prepare_window
		if prepare_window:
			prepare_window(self.window)

	def show(self):
		self.window.show()
		self.window.present()
		self.encoding_changed()

	def run(self):
		self.show()
		gtk.main()

	def encoding_changed(self, *args):
		is_jpeg = self.encoding_combo.get_active_text()=="jpeg"
		if is_jpeg:
			self.jpeg_combo.show()
			self.jpeg_label.show()
		else:
			self.jpeg_combo.hide()
			self.jpeg_label.hide()

	def set_info_text(self, text):
		if self.info:
			gobject.idle_add(self.info.set_text, text)

	def connect_clicked(self, *args):
		self.update_options_from_gui()
		self.do_connect()

	def do_connect(self):
		if xpra_opts.mode=="tcp" and not sys.platform.startswith("win"):
			""" Use built-in connector (faster and gives feedback) - does not work on win32... (dunno why) """
			self.connect_tcp()
		else:
			self.launch_xpra()

	def connect_tcp(self):
		thread.start_new_thread(self.do_connect_tcp, ())
	
	def do_connect_tcp(self):
		def set_sensitive(s):
			gobject.idle_add(self.window.set_sensitive, s)
		set_sensitive(False)
		self.set_info_text("Connecting.")
		host = xpra_opts.host
		port = xpra_opts.port
		self.set_info_text("Connecting..")
		try:
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.settimeout(10)
			self.set_info_text("Connecting...")
			sock.connect((host, int(port)))
		except Exception, e:
			self.set_info_text("Socket error: %s" % e)
			set_sensitive(True)
			print("error %s" % e)
			return
		self.set_info_text("Connection established")
		try:
			from xpra.bytestreams import SocketConnection
			global socket_wrapper
			socket_wrapper = SocketConnection(sock, sock.getsockname(), sock.getpeername())
		except Exception, e:
			self.set_info_text("Xpra Client error: %s" % e)
			set_sensitive(True)
			print("Xpra Client error: %s" % e)
			return
		gobject.idle_add(self.window.hide)
		# launch Xpra client in the same gtk.main():
		from wimpiggy.util import gtk_main_quit_on_fatal_exceptions_enable
		gtk_main_quit_on_fatal_exceptions_enable()
		opts = AdHocStruct()
		opts.clipboard = xpra_opts.clipboard
		opts.pulseaudio = xpra_opts.pulseaudio
		opts.password_file = xpra_opts.password_file
		opts.title = "@title@ on @client-machine@"
		opts.encoding = xpra_opts.encoding
		opts.jpegquality = xpra_opts.jpegquality
		opts.max_bandwidth = xpra_opts.max_bandwidth
		opts.auto_refresh_delay = xpra_opts.auto_refresh_delay
		opts.key_shortcuts = xpra_opts.key_shortcuts
		opts.compression_level = xpra_opts.compression_level
		from xpra.platform import DEFAULT_SSH_CMD
		opts.ssh = DEFAULT_SSH_CMD
		opts.remote_xpra = ".xpra/run-xpra"
		opts.debug = xpra_opts.debug
		opts.no_tray = xpra_opts.no_tray
		opts.dock_icon = xpra_opts.dock_icon
		opts.tray_icon = xpra_opts.tray_icon
		opts.window_icon = xpra_opts.window_icon
		opts.readonly = xpra_opts.readonly
		opts.session_name = "Xpra session"
		opts.mmap = xpra_opts.mmap
		opts.mmap_group = xpra_opts.mmap_group
		opts.keyboard_sync = xpra_opts.keyboard_sync
		opts.send_pings = xpra_opts.send_pings
		opts.dpi = xpra_opts.dpi
		opts.cursors = xpra_opts.cursors
		opts.bell = xpra_opts.bell
		opts.notifications = xpra_opts.notifications
		import logging
		logging.root.setLevel(logging.INFO)
		logging.root.addHandler(logging.StreamHandler(sys.stderr))

		def start_XpraClient():
			app = XpraClient(socket_wrapper, opts)
			app.run()
			self.window.show()
			self.window.set_sensitive(True)
		gobject.idle_add(start_XpraClient)

	def launch_xpra(self):
		thread.start_new_thread(self.do_launch_xpra, ())

	def do_launch_xpra(self):
		""" Launches Xpra in a new process """
		gobject.idle_add(self.window.hide)
		try:
			self.set_info_text("Launching")
			process = self.start_xpra_process()
			gobject.idle_add(self.window.hide)
			out,err = process.communicate()
			print("stdout=%s" % out)
			print("stderr=%s" % err)
			ret = process.wait()
			def show_result(out, err):
				if len(out)>255:
					out = "..."+out[len(out)-255:]
				if len(err)>255:
					err = "..."+err[len(err)-255:]
				info = "command terminated with exitcode %s" % ret
				if out:
					info += ",\noutput:\n%s" % out
				if err:
					info += ",\nerror:\n%s" % err
				#red only for non-zero returncode:
				if ret!=0:
					color_obj = gtk.gdk.color_parse("red")
				else:
					color_obj = gtk.gdk.color_parse("black")
				if color_obj:
					self.info.modify_fg(gtk.STATE_NORMAL, color_obj)
				self.set_info_text(info)
				self.show()
			gobject.idle_add(show_result, out, err)
		except Exception, e:
			print("error: %s" % e)
			gobject.idle_add(self.show)
			self.set_info_text("Error launching: %s" % (e))

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
		propDef = propLine.strip()
		if len(propDef) == 0:
			continue
		if propDef[0] in ( '!', '#' ):
			continue
		if propDef.find(":=")>0:
			props = propDef.split(":=", 1)
		elif propDef.find("=")>0:
			props = propDef.split("=", 1)
		else:
			continue
		assert len(props)==2
		name = props[0].strip()
		value = props[1].strip()
		propDict[name] = value
	propFile.close()

	for prop in ["host", "encoding", "mode"]:
		val = propDict.get(prop)
		if val:
			setattr(xpra_opts, prop, val)
	xpra_opts.port = str_to_int(propDict.get("port"), 10000)
	xpra_opts.autoconnect = str_to_bool(propDict.get("autoconnect"), False)
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
	try:
		if xpra_opts.autoconnect:
			#file says we should connect, do that only:
			process = app.start_xpra_process()
			return process.wait()
		else:
			app.create_window()
			app.run()
	except KeyboardInterrupt:
		pass
	if xpra_opts.password_file:
		os.unlink(xpra_opts.password_file)
	return 0

if __name__ == "__main__":
	v = main()
	sys.exit(v)
