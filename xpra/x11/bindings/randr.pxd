# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display

cdef dict get_monitor_properties(Display *display)
#cdef get_crtc_info(Display *display, XRRScreenResources *rsc, RRCrtc crtc)
#cdef get_output_properties(Display *display, RROutput output)
#cdef get_output_info(Display *display, XRRScreenResources *rsc, RROutput output)
#cdef get_mode_info(XRRModeInfo *mi, with_sync : bool)

cdef dict get_all_screen_properties(Display *display)
