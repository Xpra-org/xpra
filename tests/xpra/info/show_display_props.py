#!/usr/bin/env python

import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

display = Gdk.Display.get_default()
print("display=%s" % display)
print("supports_cursor_alpha=%s" % display.supports_cursor_alpha())
print("supports_composite=%s" %  display.supports_composite())
for i in range(display.get_n_screens()):
    screen = display.get_screen(i)
    print("screen(%s)=%s"% (i, screen))
    print("screen(%s) size: %sx%s / %sx%s (mm)" % (i, screen.get_width(), screen.get_height(), screen.get_width_mm(), screen.get_height_mm()))
    rgba_visual = screen.get_rgba_visual()
    print("screen(%s).get_rgba_visual()=%s" % (i, rgba_visual))
    if rgba_visual:
        print("rgba_visual: %s" % rgba_visual)
    sys_visual = screen.get_system_visual()
    print("screen(%s).get_system_visual()=%s" % (i, sys_visual))
    print("system_visual: %s" % (sys_visual))
    root = screen.get_root_window()
    print("screen(%s) root window: %s" % (i, root.get_geometry()))

print("")
root = Gdk.get_default_root_window()
print("default root window: %s" % str(root.get_geometry()))
