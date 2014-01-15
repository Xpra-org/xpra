# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def gtk2main():
    import pygtk
    pygtk.require('2.0')
    import gtk
    if gtk.main_level()==0:
        gtk.gdk.threads_init()
        try:
            gtk.threads_enter()
            gtk.main()
        finally:
            gtk.threads_leave()
