# This file is part of Parti.
# Copyright (C) 2009-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

""" client_launcher.py

This is a simple GUI for starting the xpra client.

"""

import sys
import os.path
import tempfile
import inspect
import shlex
import logging
logging.basicConfig(format="%(asctime)s %(message)s")

try:
	import _thread	as thread		#@UnresolvedImport @UnusedImport (python3)
except:
	import thread					#@Reimport

from wimpiggy.gobject_compat import import_gtk, import_gdk, import_gobject, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
import pango
import gobject
import webbrowser

from wimpiggy.util import gtk_main_quit_on_fatal_exceptions_enable
gtk_main_quit_on_fatal_exceptions_enable()
from xpra.scripts.config import ENCODINGS, get_build_info, read_config, make_defaults_struct, validate_config
from xpra.gtk_util import set_tooltip_text, add_close_accel, scaled_image
from xpra.scripts.main import connect_to
from xpra.client import XpraClient

EXEC_DEBUG = os.environ.get("XPRA_EXEC_DEBUG", "0")=="1"

APPLICATION_NAME = "Xpra Launcher"
SITE_DOMAIN = "xpra.org"
SITE_URL = "http://%s/" % SITE_DOMAIN
APP_DIR = os.getcwd()
ICONS_DIR = None
GPL2 = None


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

def get_icon_filename(name):
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
	return filename

def get_icon(name):
	filename = get_icon_filename(name)
	if not filename:
		return	None
	return get_icon_from_file(filename)

global about_dialog
about_dialog = None
def about(*args):
	global about_dialog, GPL2
	if about_dialog:
		about_dialog.show()
		about_dialog.present()
		return
	xpra_icon = get_icon("xpra.png")
	dialog = gtk.AboutDialog()
	if not is_gtk3():
		def on_website_hook(dialog, web, *args):
			''' called when the website item is selected '''
			webbrowser.open(SITE_URL)
		def on_email_hook(dialog, mail, *args):
			webbrowser.open("mailto://shifter-users@lists.devloop.org.uk")
		gtk.about_dialog_set_url_hook(on_website_hook)
		gtk.about_dialog_set_email_hook(on_email_hook)
		if xpra_icon:
			dialog.set_icon(xpra_icon)
	dialog.set_name("Xpra")
	from xpra import __version__
	dialog.set_version(__version__)
	dialog.set_authors(('Antoine Martin <antoine@devloop.org.uk>',
						'Nathaniel Smith <njs@pobox.com>',
						'Serviware - Arthur Huillet <ahuillet@serviware.com>'))
	dialog.set_license(GPL2 or "Your installation may be corrupted, the license text for GPL version 2 could not be found,\nplease refer to:\nhttp://www.gnu.org/licenses/gpl-2.0.txt")
	dialog.set_comments("\n".join(get_build_info()))
	dialog.set_website(SITE_URL)
	dialog.set_website_label(SITE_DOMAIN)
	if xpra_icon:
		dialog.set_logo(xpra_icon)
	if hasattr(dialog, "set_program_name"):
		dialog.set_program_name(APPLICATION_NAME)
	def response(*args):
		dialog.destroy()
		global about_dialog
		about_dialog = None
	dialog.connect("response", response)
	about_dialog = dialog
	dialog.show()


def load_license(gpl2_file):
	global GPL2
	if os.path.exists(gpl2_file):
		try:
			f = open(gpl2_file, mode='rb')
			GPL2 = f.read()
		finally:
			if f:
				f.close()
	return GPL2 is not None


prepare_window = None
"""
	Start of crappy platform workarounds
	ICONS_DIR is for location the icons
"""
if sys.platform.startswith("win"):
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
		gpl2_file = os.path.join(APP_DIR, "COPYING")
		load_license(gpl2_file)
elif sys.platform.startswith("darwin"):
	rsc = None
	try:
		import gtkosx_application		#@UnresolvedImport
		rsc = gtkosx_application.gtkosx_application_get_resource_path()
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
			load_license(gpl2_file)

		def prepare_window_osx(window):
			def quit_launcher(*args):
				gtk.main_quit()
			from xpra.darwin.gui import get_OSXApplication, setup_menubar, osx_ready
			setup_menubar(quit_launcher)

			osxapp = get_OSXApplication()
			icon_filename = get_icon_filename("xpra.png")
			if icon_filename:
				pixbuf = gtk.gdk.pixbuf_new_from_file(icon_filename)
				osxapp.set_dock_icon_pixbuf(pixbuf)
			osx_ready()
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

if not GPL2:
	for x in set([APP_DIR, sys.exec_prefix+"/share/xpra", "/usr/share/xpra", "/usr/local/share/xpra"]):
		gpl2_file = os.path.join(x, "COPYING")
		if load_license(gpl2_file):
			break



LOSSY_5 = "lowest quality"
LOSSY_20 = "low quality"
LOSSY_50 = "average quality"
LOSSY_90 = "best lossy quality"

DEFAULT_ENCODING = ENCODINGS[0]

XPRA_COMPRESSION_OPTIONS = [LOSSY_5, LOSSY_20, LOSSY_50, LOSSY_90]
XPRA_COMPRESSION_OPTIONS_DICT = {LOSSY_5 : 5,
						LOSSY_20 : 20,
						LOSSY_50 : 50,
						LOSSY_90 : 90
						}

# Default connection options
config = make_defaults_struct()


class ApplicationWindow:

	def	__init__(self):
		pass

	def create_window(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.connect("destroy", self.destroy)
		self.window.set_default_size(400, 300)
		self.window.set_border_width(20)
		self.window.set_title(APPLICATION_NAME)
		self.window.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color(red=65535, green=65535, blue=65535))
		icon_pixbuf = get_icon("xpra.png")
		if icon_pixbuf:
			self.window.set_icon(icon_pixbuf)
		self.window.set_position(gtk.WIN_POS_CENTER)

		vbox = gtk.VBox(False, 0)
		vbox.set_spacing(15)

		# Title
		hbox = gtk.HBox(False, 0)
		if icon_pixbuf:
			logo_button = gtk.Button("")
			settings = logo_button.get_settings()
			settings.set_property('gtk-button-images', True)
			logo_button.connect("clicked", about)
			set_tooltip_text(logo_button, "About")
			image = gtk.Image()
			image.set_from_pixbuf(icon_pixbuf)
			logo_button.set_image(image)
			hbox.pack_start(logo_button, expand=False, fill=False)
		label = gtk.Label("Connect to xpra server")
		label.modify_font(pango.FontDescription("sans 13"))
		hbox.pack_start(label, expand=True, fill=True)
		vbox.pack_start(hbox)

		# Mode:
		hbox = gtk.HBox(False, 20)
		hbox.set_spacing(20)
		hbox.pack_start(gtk.Label("Mode: "))
		self.mode_combo = gtk.combo_box_new_text()
		self.mode_combo.get_model().clear()
		self.mode_combo.append_text("TCP")
		self.mode_combo.append_text("TCP + AES")
		self.mode_combo.append_text("SSH")
		if config.mode == "tcp":
			self.mode_combo.set_active(0)
		elif config.mode == "tcp + aes":
			self.mode_combo.set_active(1)
		else:
			self.mode_combo.set_active(2)
		self.mode_combo.connect("changed", self.mode_changed)
		hbox.pack_start(self.mode_combo)
		vbox.pack_start(hbox)

		# Encoding:
		hbox = gtk.HBox(False, 20)
		hbox.set_spacing(20)
		hbox.pack_start(gtk.Label("Encoding: "))
		self.encoding_combo = gtk.combo_box_new_text()
		self.encoding_combo.get_model().clear()
		for option in ENCODINGS:
			self.encoding_combo.append_text(option)
		self.encoding_combo.set_active(ENCODINGS.index(config.encoding))
		hbox.pack_start(self.encoding_combo)
		vbox.pack_start(hbox)

		# JPEG:
		hbox = gtk.HBox(False, 20)
		hbox.set_spacing(20)
		self.jpeg_label = gtk.Label("Compression: ")
		hbox.pack_start(self.jpeg_label)
		self.quality_combo = gtk.combo_box_new_text()
		self.quality_combo.get_model().clear()
		for option in XPRA_COMPRESSION_OPTIONS:
			self.quality_combo.append_text(option)
		self.quality_combo.set_active(2)
		hbox.pack_start(self.quality_combo)
		vbox.pack_start(hbox)
		self.encoding_combo.connect("changed", self.encoding_changed)

		# Username@Host:Port
		hbox = gtk.HBox(False, 0)
		hbox.set_spacing(5)
		self.username_entry = gtk.Entry(max=128)
		self.username_entry.set_width_chars(16)
		self.username_entry.set_text(config.username)
		self.username_label = gtk.Label("@")
		self.host_entry = gtk.Entry(max=128)
		self.host_entry.set_width_chars(24)
		self.host_entry.set_text(config.host)
		self.port_entry = gtk.Entry(max=5)
		self.port_entry.set_width_chars(5)
		self.port_entry.set_text(str(config.port))
		hbox.pack_start(self.username_entry)
		hbox.pack_start(self.username_label)
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
		self.password_entry.connect("changed", self.password_ok)
		self.password_label = gtk.Label("Password: ")
		hbox.pack_start(self.password_label)
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

		# Buttons:
		hbox = gtk.HBox(False, 20)
		vbox.pack_start(hbox)
		# Connect button:
		self.button = gtk.Button("Connect")
		self.button.connect("clicked", self.connect_clicked)
		connect_icon = get_icon("retry.png")
		if connect_icon:
			self.button.set_image(scaled_image(connect_icon, 24))
		hbox.pack_start(self.button)

		def accel_close(*args):
			gtk.main_quit()
		add_close_accel(self.window, accel_close)
		vbox.show_all()
		self.window.vbox = vbox
		self.window.add(vbox)

		global prepare_window
		if prepare_window:
			prepare_window(self.window)

	def show(self):
		self.mode_changed()
		self.window.show()
		self.window.present()
		self.encoding_changed()

	def run(self):
		gtk.main()

	def mode_changed(self, *args):
		ssh = self.mode_combo.get_active_text()=="SSH"
		if ssh:
			self.username_entry.show()
			self.username_label.show()
			self.port_entry.set_text("")
		else:
			self.username_entry.hide()
			self.username_label.hide()
			self.port_entry.set_text("%s" % config.port)
		if not ssh or sys.platform.startswith("win") or sys.platform.startswith("darwin"):
			#password cannot be used with ssh
			#(except on win32 with plink, and on osx via the SSH_ASKPASS hack)
			self.password_label.show()
			self.password_entry.show()
		else:
			self.password_label.hide()
			self.password_entry.hide()

	def encoding_changed(self, *args):
		uses_quality_option = self.encoding_combo.get_active_text() in ["jpeg", "webp", "x264"]
		if uses_quality_option:
			self.quality_combo.show()
			self.jpeg_label.show()
		else:
			self.quality_combo.hide()
			self.jpeg_label.hide()

	def set_info_text(self, text):
		if self.info:
			gobject.idle_add(self.info.set_text, text)

	def set_sensitive(self, s):
		gobject.idle_add(self.window.set_sensitive, s)


	def connect_clicked(self, *args):
		self.update_options_from_gui()
		self.do_connect()

	def do_connect(self):
		thread.start_new_thread(self.connect_builtin, ())

	def connect_builtin(self):
		try:
			self.do_connect_builtin()
		except Exception, e:
			self.set_sensitive(True)
			print("%s" % e)
			import traceback
			traceback.print_stack()

	def do_connect_builtin(self):
		self.set_sensitive(False)
		self.set_info_text("Connecting.")
		#cooked vars used by connect_to
		params = {"type"	: config.mode}
		if config.mode=="ssh":
			remote_xpra = config.remote_xpra.split()
			if config.socket_dir:
				remote_xpra.append("--socket-dir=%s" % config.socket_dir)
			params["remote_xpra"] = remote_xpra
			if config.port and config.port>0:
				params["display"] = ":%s" % config.port
				params["display_as_args"] = [params["display"]]
			else:
				params["display"] = "auto"
				params["display_as_args"] = []
			full_ssh = shlex.split(config.ssh)
			password = config.password
			username = config.username
			host = config.host
			upos = host.find("@")
			if upos>=0:
				#found at sign: username@host
				username = host[:upos]
				host = host[upos+1:]
				ppos = username.find(":")
				if ppos>=0:
					#found separator: username:password@host
					password = username[ppos+1:]
					username = username[:ppos]
			if username:
				params["username"] = username
				full_ssh += ["-l", username]
			full_ssh += ["-T", host]
			params["full_ssh"] = full_ssh
			params["password"] = password
			params["display_name"] = "ssh:%s:%s" % (config.host, config.port)
		elif config.mode=="unix-domain":
			params["display"] = ":%s" % config.port
			params["display_name"] = "unix-domain:%s" % config.port
		else:
			#tcp:
			params["host"] = config.host
			params["port"] = int(config.port)
			params["display_name"] = "tcp:%s:%s" % (config.host, config.port)

		#print("connect_to(%s)" % params)
		self.set_info_text("Connecting...")
		try:
			conn = connect_to(params, self.set_info_text)
		except Exception, e:
			self.set_sensitive(True)
			self.set_info_color(True)
			self.set_info_text(str(e))
			gobject.idle_add(self.window.show)
			return
		gobject.idle_add(self.window.hide)

		def start_XpraClient():
			app = XpraClient(conn, config)
			if config.password:
				#pass the password to the class directly:
				app.password = config.password
			#override exit code:
			warn_and_quit_save = app.warn_and_quit
			def warn_and_quit_override(exit_code, warning):
				app.cleanup()
				password_warning = warning.find("invalid password")>=0
				if password_warning:
					self.password_warning()
				err = exit_code!=0 or password_warning
				self.set_info_color(err)
				self.set_info_text(warning)
				if err:
					def ignore_further_quit_events(*args):
						pass
					app.warn_and_quit = ignore_further_quit_events
					self.set_sensitive(True)
					gobject.idle_add(self.window.show)
				else:
					app.warn_and_quit = warn_and_quit_save
					self.destroy()
					gtk.main_quit()
			app.warn_and_quit = warn_and_quit_override
		gobject.idle_add(start_XpraClient)

	def password_ok(self, *args):
		color_obj = gtk.gdk.color_parse("black")
		self.password_entry.modify_text(gtk.STATE_NORMAL, color_obj)

	def password_warning(self, *args):
		color_obj = gtk.gdk.color_parse("red")
		self.password_entry.modify_text(gtk.STATE_NORMAL, color_obj)
		self.password_entry.grab_focus()

	def set_info_color(self, is_error=False):
		if is_error:
			color_obj = gtk.gdk.color_parse("red")
		else:
			color_obj = gtk.gdk.color_parse("black")
		if color_obj:
			self.info.modify_fg(gtk.STATE_NORMAL, color_obj)


	def update_options_from_gui(self):
		config.host = self.host_entry.get_text()
		config.port = self.port_entry.get_text()
		config.username = self.username_entry.get_text()
		config.encoding = self.encoding_combo.get_active_text()
		config.quality = XPRA_COMPRESSION_OPTIONS_DICT.get(self.quality_combo.get_active_text())
		mode_enc = self.mode_combo.get_active_text()
		if mode_enc.startswith("TCP"):
			config.mode = "tcp"
			if mode_enc.find("AES")>0:
				config.encryption = "AES"
		else:
			config.mode = "ssh"
		config.password = self.password_entry.get_text()

	def destroy(self, *args):
		self.window.destroy()
		self.window = None
		gtk.main_quit()

def create_password_file(password):
	pass_file = tempfile.NamedTemporaryFile()
	pass_file.write("%s" % password)
	pass_file.flush()
	return pass_file

def update_options_from_file(filename):
	propDict = read_config(filename)
	options = validate_config(propDict)
	for k,v in options.items():
		setattr(config, k, v)


def main():
	if len(sys.argv) == 2:
		update_options_from_file(sys.argv[1])
	app = ApplicationWindow()
	app.create_window()
	try:
		if config.autoconnect:
			#file says we should connect,
			#do that only (not showing UI unless something goes wrong):
			gobject.idle_add(app.do_connect)
		if not config.autoconnect or config.debug:
			app.show()
		app.run()
	except KeyboardInterrupt:
		pass
	if config.password_file and os.path.exists(config.password_file):
		os.unlink(config.password_file)
	return 0


if __name__ == "__main__":
	v = main()
	sys.exit(v)
