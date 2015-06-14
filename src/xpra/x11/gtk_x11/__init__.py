# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#We must import "*" or things will fail in mysterious ways!
try:
    #this is now optional because GTK3 does not have the bindings
    from xpra.x11.gtk_x11.gdk_bindings import *
except:
    pass