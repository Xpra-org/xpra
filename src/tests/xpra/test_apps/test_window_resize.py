#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib	#pylint: disable=wrong-import-position


def make_window(OR=False):
	class State(object):
		pass
	state = State()
	state.counter = 0
	state.width = 400-OR*100
	state.height = 200-OR*50
	window = Gtk.Window()
	window.set_size_request(state.width, state.height)
	window.connect("delete_event", Gtk.main_quit)
	window.set_title("OR=%s" % OR)
	window.set_position(Gtk.WindowPosition.CENTER)
	vbox = Gtk.VBox()
	hbox = Gtk.HBox()
	w_e = Gtk.Entry()
	w_e.set_max_length(64)
	hbox.add(w_e)
	hbox.add(Gtk.Label("x"))
	h_e = Gtk.Entry()
	h_e.set_max_length(64)
	hbox.add(h_e)
	set_size_btn = Gtk.Button("set size")
	def set_size(*_args):
		w = int(w_e.get_text())
		h = int(h_e.get_text())
		print("resizing to %s x %s" % (w, h))
		window.resize(w, h)
	set_size_btn.connect('clicked', set_size)
	hbox.add(set_size_btn)
	vbox.add(hbox)

	btn = Gtk.Button(label="auto resize me")
	def resize(*_args):
		state.width = max(200, (state.width+20) % 600)
		state.height = max(200, (state.height+20) % 400)
		print("resizing to %s x %s" % (state.width, state.height))
		window.resize(state.width, state.height)
	btn.connect('clicked', resize)
	vbox.add(btn)

	btn = Gtk.Button(label="fast resize")
	def do_resize_fast():
		width = max(200, (state.width+1) % 600)
		height = max(200, (state.height+1) % 400)
		print("resizing to %s x %s" % (width, height))
		window.resize(width, height)
		state.counter -= 1
		return state.counter>0
	def resize_fast(*_args):
		state.counter = 200
		GLib.idle_add(do_resize_fast)
	btn.connect('clicked', resize_fast)
	vbox.add(btn)

	window.add(vbox)
	window.realize()
	window.get_window().set_override_redirect(OR)
	window.show_all()

def main():
	make_window(False)
	make_window(True)
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
