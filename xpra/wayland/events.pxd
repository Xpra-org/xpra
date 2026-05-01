# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.wayland.wlroots cimport (
    wl_listener, wl_signal_add, wl_signal, wl_notify_func_t,
)


# A wl_listener wrapped with a back-pointer to the struct it belongs to.
# `listener` MUST be the first field so &xl.listener and &xl share the same
# address; owner_of() recovers the owner regardless of which event fired.
cdef struct xpra_listener:
    wl_listener listener
    void *owner


cdef inline void *owner_of(wl_listener *l) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_listener*>0).listener - <char*>0)
    return (<xpra_listener*>(<char*>l - offset)).owner


cdef inline void attach_listener(xpra_listener *listeners, int slot, void *owner,
        wl_notify_func_t notify, wl_signal *signal) noexcept nogil:
    listeners[slot].owner = owner
    listeners[slot].listener.notify = notify
    wl_signal_add(signal, &listeners[slot].listener)
