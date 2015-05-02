#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_glib, import_gtk
glib = import_glib()
gtk = import_gtk()

def change_callback(self, window, entry):
	print("text=%s" % entry.get_text())
	window.set_title(entry.get_text())

def make_window(OR=False):
	class State(object):
		pass
	state = State()
	state.counter = 0
	state.width = 400-OR*100
	state.height = 200-OR*50
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(state.width, state.height)
	window.connect("delete_event", gtk.mainquit)
	window.set_title("OR=%s" % OR)
	window.set_position(gtk.WIN_POS_CENTER)
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
		state.width = max(200, (state.width+20) % 600)
		state.height = max(200, (state.height+20) % 400)
		print("resizing to %s x %s" % (state.width, state.height))
		window.resize(state.width, state.height)
	btn.connect('clicked', resize)
	vbox.add(btn)

	btn = gtk.Button("fast resize")
	def do_resize_fast():
		width = max(200, (state.width+1) % 600)
		height = max(200, (state.height+1) % 400)
		print("resizing to %s x %s" % (width, height))
		window.resize(width, height)
		state.counter -= 1
		return state.counter>0
	def resize_fast(*args):
		state.counter = 200
		glib.idle_add(do_resize_fast)
	btn.connect('clicked', resize_fast)
	vbox.add(btn)

	window.add(vbox)
	window.realize()
	window.window.set_override_redirect(OR)
	window.show_all()

def main():
	make_window(False)
	make_window(True)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
