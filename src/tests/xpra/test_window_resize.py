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
	btn = gtk.Button("resize me")
	def resize(*args):
		global width, height
		width = max(200, (width+20) % 600)
		height = max(200, (height+20) % 400)
		print("resizing to %s x %s" % (width, height))
		window.resize(width, height)
	btn.connect('clicked', resize)
	window.add(btn)
	window.show_all()
	gtk.main()
	return 0

if __name__ == "__main__":
	main()

