#!/usr/bin/env python

import gtk.gdk

display = gtk.gdk.display_get_default()
print("display=%s" % display)
print("supports_cursor_alpha=%s" % display.supports_cursor_alpha())
print("supports_composite=%s" %  display.supports_composite())
for i in range(display.get_n_screens()):
    screen = display.get_screen(i)
    print("screen(%s)=%s"% (i, screen))
    print("screen(%s) size: %sx%s / %sx%s (mm)" % (i, screen.get_width(), screen.get_height(), screen.get_width_mm(), screen.get_height_mm()))
    print("screen(%s).get_rgba_colormap()=%s" % (i, screen.get_rgba_colormap()))
    rgba_visual = screen.get_rgba_visual()
    print("screen(%s).get_rgba_visual()=%s" % (i, rgba_visual))
    if rgba_visual:
        for a in ("bits_per_rgb", "colormap_size", "depth", "type"):
            print("rgba_visual.%s: %s" % (a, getattr(rgba_visual, a)))
    sys_visual = screen.get_system_visual()
    print("screen(%s).get_system_visual()=%s" % (i, sys_visual))
    for a in ("bits_per_rgb", "colormap_size", "depth", "type"):
        print("system_visual.%s: %s" % (a, getattr(sys_visual, a)))
    root = screen.get_root_window()
    print("screen(%s) root window: %s" % (i, root.get_geometry()))

print("")
root = gtk.gdk.get_default_root_window()
print("default root window: %s" % str(root.get_geometry()))
