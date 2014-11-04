#!/usr/bin/env python

import gtk
import gobject

width = 400
height = 200

def main():
	other = gtk.Window(gtk.WINDOW_TOPLEVEL)
	other.set_title("Other")
	other.set_size_request(width/2, height/2)
	other.connect("delete_event", gtk.mainquit)
	other.show_all()

	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)
	def add_button(title, callback):
		hbox = gtk.HBox(False, 0)
		vbox.pack_start(hbox, expand=False, fill=False, padding=10)
		btn = gtk.Button(title)
		hbox.pack_start(btn, expand=False, fill=False, padding=10)
		def on_clicked(*args):
			def after_delay():
				print("**********************************************\nCALLING %s" % callback)
				callback()
				print("DONE\n**********************************************")
			gobject.timeout_add(5*1000, after_delay)
		btn.connect("clicked", on_clicked)
	add_button("raise Main in 5 seconds", window.present)
	add_button("raise Other in 5 seconds", other.present)
	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
