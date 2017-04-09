#!/usr/bin/env python

import gtk


def colored_cursor(size=64, x=32, y=32):
	#create a custom cursor:
	#first get a colormap and then allocate the colors
	#black and white for drawing on the bitmaps:
	pm = gtk.gdk.Pixmap(None, size, size, 1)
	mask = gtk.gdk.Pixmap(None, size, size, 1)
	colormap = gtk.gdk.colormap_get_system()
	black = colormap.alloc_color('black')
	white = colormap.alloc_color('white')
	# Create two GCs - one each for black and white:
	bgc = pm.new_gc(foreground=black)
	wgc = pm.new_gc(foreground=white)
	# Use the black gc to clear the pixmap and mask:
	mask.draw_rectangle(bgc,True,0,0,size,size)
	pm.draw_rectangle(bgc,True,0,0,size,size)
	# Use the white gc to set the bits in the pixmap and mask:
	pm.draw_arc(wgc,True,0,2,size,size/2,0,360*64)
	mask.draw_rectangle(wgc,True,0,0,size,size)
	# Then create and set the cursor using unallocated colors:
	green = gtk.gdk.color_parse('green')
	red = gtk.gdk.color_parse('red')
	return gtk.gdk.Cursor(pm,mask,green,red, x, y)

def main():
	cursor = colored_cursor()
	win = gtk.Window(gtk.WINDOW_TOPLEVEL)
	win.connect("delete_event", gtk.mainquit)
	win.set_title("Cursor Hotspot Test")
	win.set_size_request(320, 240)
	def onclick (box, event):
		print("%s" % ((event.x, event.y), ))
	btn = gtk.Button("hello")
	btn.connect('button-press-event', onclick)
	win.add(btn)
	win.show_all()
	win.get_window().set_cursor(cursor)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
