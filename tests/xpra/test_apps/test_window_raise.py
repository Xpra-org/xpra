#!/usr/bin/env python3

import gi

gi.require_version('Gtk', '3.0')  # @UndefinedVariable
from gi.repository import Gtk, GLib	#pylint: disable=wrong-import-position @UnresolvedImport

width = 400
height = 200

def main():
	other = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	other.set_title("Other")
	other.set_size_request(width/2, height/2)
	other.connect("delete_event", Gtk.main_quit)
	other.show_all()

	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(homogeneous=False, spacing=0)
	def add_button(title, callback):
		hbox = Gtk.HBox(homogeneous=False, spacing=0)
		vbox.pack_start(hbox, expand=False, fill=False, padding=10)
		btn = Gtk.Button(label=title)
		hbox.pack_start(btn, expand=False, fill=False, padding=10)
		def on_clicked(*_args):
			def after_delay():
				print("**********************************************\nCALLING %s" % callback)
				callback()
				print("DONE\n**********************************************")
			GLib.timeout_add(5*1000, after_delay)
		btn.connect("clicked", on_clicked)
	add_button("raise Main in 5 seconds", window.present)
	add_button("raise Other in 5 seconds", other.present)
	window.add(vbox)
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
