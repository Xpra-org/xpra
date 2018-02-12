#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk
from xpra.gtk_common.gtk_util import get_pixbuf_from_data
gtk = import_gtk()
gdk = import_gdk()


class CursorWindow(gtk.Window):

	def __init__(self, width=200, height=100, title="", cursor=None):
		gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
		self.connect("delete_event", gtk.mainquit)
		self.set_title(title)
		self.set_size_request(width, height)
		self.show()
		self.get_window().set_cursor(cursor)

def colored_cursor():
	#create a custom cursor:
	#first get a colormap and then allocate the colors
	#black and white for drawing on the bitmaps:
	size = 64
	pm = gdk.Pixmap(None, size, size, 1)
	mask = gdk.Pixmap(None, size, size, 1)
	colormap = gdk.colormap_get_system()
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
	green = gdk.color_parse('green')
	red = gdk.color_parse('red')
	return gdk.Cursor(pm,mask,green,red,5,5)

def small_empty_cursor():
	#same as xterm when pressing a modifier key
	w, h = 6, 13
	rgb_data = b"\0"*w*h*4
	pixbuf = get_pixbuf_from_data(rgb_data, True, w, h, w*4)
	return gdk.Cursor(gdk.display_get_default(), pixbuf, 0, 11)


def main():
	CursorWindow(title="colored cursor", cursor=colored_cursor()).show_all()
	CursorWindow(title="X cursor", cursor=gdk.Cursor(gdk.X_CURSOR)).show_all()
	CursorWindow(title="small empty cursor", cursor=small_empty_cursor()).show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
