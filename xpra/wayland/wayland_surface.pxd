# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.wayland.events cimport ListenerObject
from xpra.wayland.wlroots cimport wlr_surface


cdef unsigned long next_wid() noexcept


cdef class WaylandSurface(ListenerObject):
    """Base class for any wlroots surface-bearing role wrapper.

    Owns the parts of the lifecycle that don't depend on what specific role
    (xdg_toplevel, xdg_popup, subsurface, ...) wraps the underlying wlr_surface:
    pixel capture, frame_done, instance signals (connect/_emit), wid alloc,
    and a single shared registry keyed by the wl_surface pointer.

    Subclasses populate `self.wlr_surface` once the role-specific struct is
    known, then call `register()` to add themselves to the registry. They MUST
    null `self.wlr_surface` in their destroy path before any reference outside
    the registry can outlive wlroots' free of the underlying struct.
    """
    cdef wlr_surface *wlr_surface         # the actual wl_surface (NULL once destroyed)
    cdef readonly unsigned long wid       # xpra-assigned numeric id, lives forever
    cdef dict _callbacks                  # {event_name: [callable, ...]}

    cdef void register(self)              # add self to module-level `surfaces`
    cdef void unregister(self)            # remove from `surfaces`; safe to call twice

    cdef _emit_args(self, str event, tuple args)
