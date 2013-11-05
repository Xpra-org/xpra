#!/usr/bin/env python

import gtk

def change_callback(self, window, entry):
	print("text=%s" % entry.get_text())
	window.set_title(entry.get_text())

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox()
	hbox = gtk.HBox()
	w_e = gtk.Entry(max=64)
	hbox.add(w_e)
	hbox.add(gtk.Label("x"))
	h_e = gtk.Entry(max=64)
	hbox.add(h_e)
	set_size_btn = gtk.Button("set size")
	def set_size(*args):
		w = int(w_e.get_text())
		h = int(h_e.get_text())
		print("resizing to %s x %s" % (w, h))
		window.resize(w, h)
	set_size_btn.connect('clicked', set_size)
	hbox.add(set_size_btn)
	vbox.add(hbox)

	btn = gtk.Button("auto resize me")
	def resize(*args):
		global width, height
		width = max(200, (width+20) % 600)
		height = max(200, (height+20) % 400)
		print("resizing to %s x %s" % (width, height))
		window.resize(width, height)
	btn.connect('clicked', resize)
	vbox.add(btn)
	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
