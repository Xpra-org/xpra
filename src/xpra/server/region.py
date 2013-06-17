# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


#if gtk is loaded, we use gtk.gdk.Region
#except for old gtk versions which lack "gtk.gdk.Region().get_rectangles()"
#alternatively, we just keep the regions in a list
#(which isn't as good since we don't merge rectangles
#or discard subsets, but better than carrying ugly crufty code
#just for those outdated pygtk versions..)

import os
import sys

try_gdk = sys.modules.get("gtk.gdk") is not None and os.environ.get("XPRA_FAKE_OLD_PYGTK", "0")=="0"
if try_gdk:
    import gtk.gdk
    tmp_region = gtk.gdk.Region()
    try_gdk = hasattr(tmp_region, "get_rectangles")
    del tmp_region

if try_gdk:
    def new_region():
        return gtk.gdk.Region()
    def add_rectangle(region, x, y, w, h):
        rectangle = gtk.gdk.Rectangle(x, y, w, h)
        region.union_with_rect(rectangle)
    def get_rectangles(region):
        return region.get_rectangles()

else:
    #FIXME: add region merging, etc
    def new_region():
        return list()
    def add_rectangle(region, rectangle):
        if rectangle not in region:
            region.append(rectangle)
    def get_rectangles(region):
        return region
