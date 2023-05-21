# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position, ungrouped-imports
from xpra.x11.gtk3 import gdk_bindings  #@UnresolvedImport

get_pywindow                = gdk_bindings.get_pywindow
get_xatom                   = gdk_bindings.get_xatom
add_event_receiver          = gdk_bindings.add_event_receiver
remove_event_receiver       = gdk_bindings.remove_event_receiver
add_fallback_receiver       = gdk_bindings.add_fallback_receiver
remove_fallback_receiver    = gdk_bindings.remove_fallback_receiver
add_catchall_receiver       = gdk_bindings.add_catchall_receiver
remove_catchall_receiver    = gdk_bindings.remove_catchall_receiver
init_x11_filter             = gdk_bindings.init_x11_filter
cleanup_x11_filter          = gdk_bindings.cleanup_x11_filter
cleanup_all_event_receivers = gdk_bindings.cleanup_all_event_receivers
get_pywindow                = gdk_bindings.get_pywindow
get_xvisual                 = gdk_bindings.get_xvisual
get_pyatom                  = gdk_bindings.get_pyatom
add_x_event_parser          = gdk_bindings.add_x_event_parser
add_x_event_signal          = gdk_bindings.add_x_event_signal
add_x_event_type_name       = gdk_bindings.add_x_event_type_name


from xpra.gtk_common.gtk3 import gdk_bindings as common_bindings   #@UnresolvedImport, @UnusedImport, @Reimport

get_display_for             = common_bindings.get_display_for
calc_constrained_size       = common_bindings.calc_constrained_size
