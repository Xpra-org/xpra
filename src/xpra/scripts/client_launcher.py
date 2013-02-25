#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2009-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

""" client_launcher.py

This is a simple GUI for starting the xpra client.

"""

import sys
import shlex

try:
	import _thread	as thread		#@UnresolvedImport @UnusedImport (python3)
except:
	import thread					#@Reimport

from wimpiggy.gobject_compat import import_gtk, import_gdk, import_gobject
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
import pango


from wimpiggy.util import gtk_main_quit_on_fatal_exceptions_enable
gtk_main_quit_on_fatal_exceptions_enable()
from xpra.scripts.config import ENCODINGS, read_config, make_defaults_struct, validate_config
from xpra.gtk_util import set_tooltip_text, add_close_accel, scaled_image, set_prgname
from xpra.scripts.about import about
from xpra.scripts.main import connect_to
from xpra.platform import get_icon
from xpra.client import XpraClient
from wimpiggy.log import Logger
log = Logger()


APPLICATION_NAME = "Xpra Launcher"
SITE_DOMAIN = "xpra.org"
SITE_URL = "http://%s/" % SITE_DOMAIN
GPL2 = None
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


class ApplicationWindow:

	def	__init__(self):
		# Default connection options
		self.config = make_defaults_struct()

	def create_window(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.connect("destroy", self.destroy)
		self.window.set_default_size(400, 300)
		self.window.set_border_width(20)
		self.window.set_title(APPLICATION_NAME)
		self.window.modify_bg(gtk.STATE_NORMAL, gdk.Color(red=65535, green=65535, blue=65535))
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
		label.modify_font(pango.FontDescription("sans 14"))
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
		if self.config.mode == "tcp":
			self.mode_combo.set_active(0)
		elif self.config.mode == "tcp + aes":
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
		self.encoding_combo.set_active(ENCODINGS.index(self.config.encoding))
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
		self.username_entry.set_text(self.config.username)
		self.username_entry.connect("changed", self.validate)
		self.username_label = gtk.Label("@")
		self.host_entry = gtk.Entry(max=128)
		self.host_entry.set_width_chars(24)
		self.host_entry.set_text(self.config.host)
		self.host_entry.connect("changed", self.validate)
		self.port_entry = gtk.Entry(max=5)
		self.port_entry.set_width_chars(5)
		self.port_entry.set_text(str(self.config.port))
		self.port_entry.connect("changed", self.validate)
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
		self.password_entry.connect("changed", self.validate)
		self.password_label = gtk.Label("Password: ")
		hbox.pack_start(self.password_label)
		hbox.pack_start(self.password_entry)
		vbox.pack_start(hbox)

		# Info Label
		self.info = gtk.Label()
		self.info.set_line_wrap(True)
		self.info.set_size_request(360, -1)
		color_obj = gdk.color_parse("red")
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
		self.mode_changed()
		self.encoding_changed()
		self.validate()

	def validate(self, *args):
		self.update_options_from_gui()
		ssh = self.mode_combo.get_active_text()=="SSH"
		errs = []
		host = self.config.host
		errs.append((self.host_entry, not bool(host), "specify the host"))
		if ssh and not self.config.port:
			port = 0		#port optional with ssh
		else:
			try:
				port = int(self.config.port)
			except:
				port = -1
		errs.append((self.port_entry, port<0 or port>=2**16, "invalid port number"))
		err_text = []
		for w, e, text in errs:
			self.set_widget_bg_color(w, e)
			if e:
				err_text.append(text)
		log.debug("validate(%s) err_text=%s, errs=%s", args, err_text, errs)
		self.set_info_text(", ".join(err_text))
		self.set_info_color(len(err_text)>0)
		self.button.set_sensitive(len(err_text)==0)
		return errs

	def show(self):
		self.window.show()
		self.window.present()

	def run(self):
		gtk.main()

	def mode_changed(self, *args):
		ssh = self.mode_combo.get_active_text()=="SSH"
		self.port_entry.set_text("")
		if ssh:
			self.username_entry.show()
			self.username_label.show()
		else:
			self.username_entry.hide()
			self.username_label.hide()
			if self.config.port>0:
				self.port_entry.set_text("%s" % self.config.port)
		if not ssh or sys.platform.startswith("win") or sys.platform.startswith("darwin"):
			#password cannot be used with ssh
			#(except on win32 with plink, and on osx via the SSH_ASKPASS hack)
			self.password_label.show()
			self.password_entry.show()
		else:
			self.password_label.hide()
			self.password_entry.hide()
		self.validate()

	def encoding_changed(self, *args):
		uses_quality_option = self.encoding_combo.get_active_text() in ["jpeg", "webp", "x264"]
		if uses_quality_option:
			self.quality_combo.show()
			self.jpeg_label.show()
		else:
			self.quality_combo.hide()
			self.jpeg_label.hide()

	def reset_errors(self):
		self.set_sensitive(True)
		self.set_info_text("")
		for widget in (self.info, self.password_entry, self.username_entry, self.host_entry, self.port_entry):
			self.set_widget_fg_color(self.info, False)
			self.set_widget_bg_color(widget, False)

	def set_info_text(self, text):
		if self.info:
			gobject.idle_add(self.info.set_text, text)

	def set_info_color(self, is_error=False):
		self.set_widget_fg_color(self.info, is_error)


	def set_sensitive(self, s):
		gobject.idle_add(self.window.set_sensitive, s)

	def connect_clicked(self, *args):
		self.update_options_from_gui()
		self.do_connect()

	def do_connect(self):
		try:
			self.connect_builtin()
		except:
			self.set_sensitive(True)
			log.error("cannot connect:", exc_info=True)

	def connect_builtin(self):
		#cooked vars used by connect_to
		params = {"type"	: self.config.mode}
		if self.config.mode=="ssh":
			remote_xpra = self.config.remote_xpra.split()
			if self.config.socket_dir:
				remote_xpra.append("--socket-dir=%s" % self.config.socket_dir)
			params["remote_xpra"] = remote_xpra
			if self.config.port and self.config.port>0:
				params["display"] = ":%s" % self.config.port
				params["display_as_args"] = [params["display"]]
			else:
				params["display"] = "auto"
				params["display_as_args"] = []
			full_ssh = shlex.split(self.config.ssh)
			password = self.config.password
			username = self.config.username
			host = self.config.host
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
			params["display_name"] = "ssh:%s:%s" % (self.config.host, self.config.port)
		elif self.config.mode=="unix-domain":
			params["display"] = ":%s" % self.config.port
			params["display_name"] = "unix-domain:%s" % self.config.port
		else:
			#tcp:
			params["host"] = self.config.host
			params["port"] = int(self.config.port)
			params["display_name"] = "tcp:%s:%s" % (self.config.host, self.config.port)

		#print("connect_to(%s)" % params)
		self.set_info_text("Connecting...")
		thread.start_new_thread(self.do_connect_builtin, (params,))

	def ssh_failed(self, message):
		self.set_info_text(message)
		self.set_info_color(True)

	def do_connect_builtin(self, params):
		self.set_info_text("Connecting.")
		self.set_sensitive(False)
		try:
			conn = connect_to(params, self.set_info_text, ssh_fail_cb=self.ssh_failed)
		except Exception, e:
			self.set_sensitive(True)
			self.set_info_color(True)
			self.set_info_text(str(e))
			gobject.idle_add(self.window.show)
			return
		gobject.idle_add(self.window.hide)

		def start_XpraClient():
			app = XpraClient(conn, self.config)
			if self.config.password:
				#pass the password to the class directly:
				app.password = self.config.password
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
		color_obj = gdk.color_parse("black")
		self.password_entry.modify_text(gtk.STATE_NORMAL, color_obj)

	def password_warning(self, *args):
		color_obj = gdk.color_parse("red")
		self.password_entry.modify_text(gtk.STATE_NORMAL, color_obj)
		self.password_entry.grab_focus()

	def set_widget_bg_color(self, widget, is_error=False):
		if is_error:
			color_obj = gdk.color_parse("red")
		else:
			color_obj = gdk.color_parse("white")
		if color_obj:
			widget.modify_base(gtk.STATE_NORMAL, color_obj)

	def set_widget_fg_color(self, widget, is_error=False):
		if is_error:
			color_obj = gdk.color_parse("red")
		else:
			color_obj = gdk.color_parse("black")
		if color_obj:
			widget.modify_fg(gtk.STATE_NORMAL, color_obj)


	def update_options_from_gui(self):
		self.config.host = self.host_entry.get_text()
		self.config.port = self.port_entry.get_text()
		self.config.username = self.username_entry.get_text()
		self.config.encoding = self.encoding_combo.get_active_text()
		self.config.quality = XPRA_COMPRESSION_OPTIONS_DICT.get(self.quality_combo.get_active_text())
		mode_enc = self.mode_combo.get_active_text()
		if mode_enc.startswith("TCP"):
			self.config.mode = "tcp"
			if mode_enc.find("AES")>0:
				self.config.encryption = "AES"
		else:
			self.config.mode = "ssh"
		self.config.password = self.password_entry.get_text()

	def destroy(self, *args):
		self.window.destroy()
		self.window = None
		gtk.main_quit()

	def update_options_from_file(self, filename):
		props = read_config(filename)
		options = validate_config(props)
		for k,v in options.items():
			setattr(self.config, k, v)


def main():
	set_prgname("Xpra-Launcher")
	app = ApplicationWindow()
	if len(sys.argv) == 2:
		app.update_options_from_file(sys.argv[1])
	app.create_window()
	try:
		if app.config.autoconnect:
			#file says we should connect,
			#do that only (not showing UI unless something goes wrong):
			gobject.idle_add(app.do_connect)
		if not app.config.autoconnect or app.config.debug:
			app.reset_errors()
			app.show()
		app.run()
	except KeyboardInterrupt:
		pass
	return 0


if __name__ == "__main__":
	import logging
	logging.basicConfig(format="%(asctime)s %(message)s")
	logging.root.addHandler(logging.StreamHandler(sys.stdout))
	logging.root.setLevel(logging.INFO)
	v = main()
	sys.exit(v)
