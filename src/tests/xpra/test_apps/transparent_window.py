#!/usr/bin/env python

import sys
import pygtk
pygtk.require('2.0')
import gtk
from gtk import gdk
import cairo

# This program shows you how to create semi-transparent windows,
# without any of the historical screenshot hacks. It requires
# a modern system, with a compositing manager. I use xcompmgr
# and the nvidia drivers with RenderAccel, and it works well.
#
# I'll take you through each step as we go. Minimal GTK+ knowledge is
# assumed.

# Only some X servers support alpha channels. Always have a fallback
supports_alpha = False

def clicked(widget, event):
    # toggle window manager frames
    widget.set_decorated(not widget.get_decorated())

# This is called when we need to draw the windows contents
def expose(widget, event):
    global supports_alpha

    cr = widget.window.cairo_create()

    if supports_alpha == True:
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.0) # Transparent
    else:
        cr.set_source_rgb(1.0, 1.0, 1.0) # Opaque white

    # Draw the background
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.paint()

    # Draw a circle
    (width, height) = widget.get_size()
    cr.set_source_rgba(1.0, 0.2, 0.2, 0.6)
    # Python <2.4 doesn't have conditional expressions
    if width < height:
        radius = float(width)/2 - 0.8
    else:
        radius = float(height)/2 - 0.8

    cr.arc(float(width)/2, float(height)/2, radius, 0, 2.0*3.14)
    cr.fill()
    cr.stroke()
    return False

def screen_changed(widget, old_screen=None):

    global supports_alpha

    # To check if the display supports alpha channels, get the colormap
    screen = widget.get_screen()
    colormap = screen.get_rgba_colormap()
    display = screen.get_display()
    if not display.supports_composite():
        print 'Your display does not support compositing!'
        colormap = screen.get_rgb_colormap()
        supports_alpha = False
    elif colormap == None:
        print 'Your screen does not support alpha channels! (no rgba colormap)'
        colormap = screen.get_rgb_colormap()
        supports_alpha = False
    else:
        print 'Your screen supports alpha channels!'
        supports_alpha = True

    # Now we have a colormap appropriate for the screen, use it
    widget.set_colormap(colormap)

    return False

def main(args):
    win = gtk.Window()

    win.set_title('Alpha Demo')
    win.connect('delete-event', gtk.main_quit)

    # Tell GTK+ that we want to draw the windows background ourself.
    # If we don't do this then GTK+ will clear the window to the
    # opaque theme default color, which isn't what we want.
    win.set_app_paintable(True)

    # The X server sends us an expose event when the window becomes
    # visible on screen. It means we need to draw the contents.  On a
    # composited desktop expose is normally only sent when the window
    # is put on the screen. On a non-composited desktop it can be
    # sent whenever the window is uncovered by another.
    #
    # The screen-changed event means the display to which we are
    # drawing changed. GTK+ supports migration of running
    # applications between X servers, which might not support the
    # same features, so we need to check each time.

    win.connect('expose-event', expose)
    win.connect('screen-changed', screen_changed)

    # toggle title bar on click - we add the mask to tell
    # X we are interested in this event
    win.set_decorated(False)
    win.add_events(gdk.BUTTON_PRESS_MASK)
    win.connect('button-press-event', clicked)

    # initialize for the current display
    screen_changed(win)

    # Run the program
    win.show_all()
    gtk.main()

    return True


if __name__ == '__main__':
    sys.exit(main(sys.argv))
