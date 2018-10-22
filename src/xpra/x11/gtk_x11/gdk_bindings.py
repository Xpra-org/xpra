# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import is_gtk3, try_import_GdkX11
if is_gtk3():
    try_import_GdkX11()
    from xpra.x11.gtk3 import gdk_bindings
else:
    from xpra.x11.gtk2 import gdk_bindings

get_pywindow                = gdk_bindings.get_pywindow
get_xatom                   = gdk_bindings.get_xatom
add_event_receiver          = gdk_bindings.add_event_receiver
remove_event_receiver       = gdk_bindings.remove_event_receiver 
get_children                = gdk_bindings.get_children
init_x11_filter             = gdk_bindings.init_x11_filter
cleanup_x11_filter          = gdk_bindings.cleanup_x11_filter
cleanup_all_event_receivers = gdk_bindings.cleanup_all_event_receivers
get_pywindow                = gdk_bindings.get_pywindow
get_xvisual                 = gdk_bindings.get_xvisual
