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
cdef struct owner_listener:
    wl_listener listener
    void *owner


cdef inline void *owner_of(wl_listener *l) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<owner_listener*>0).listener - <char*>0)
    return (<owner_listener*>(<char*>l - offset)).owner


cdef inline void attach_listener(owner_listener *listeners, int slot, void *owner,
        wl_notify_func_t notify, wl_signal *signal) noexcept nogil:
    listeners[slot].owner = owner
    listeners[slot].listener.notify = notify
    wl_signal_add(signal, &listeners[slot].listener)


# Shared dispatcher: every ListenerObject's listeners point at this; it casts
# the wl_listener back to the owning ListenerObject and invokes the virtual
# `dispatch` method.
cdef void listener_dispatch(wl_listener *listener, void *data) noexcept


cdef class ListenerObject:
    """Base class for objects that own a heap-allocated array of wlroots
    listeners.

    Subclasses pass the slot count to `__init__` (the only constructor arg
    that travels to this base) and override `dispatch()` to route slot
    indices to behaviour. All listener bookkeeping (allocation, attach,
    detach, free) lives here so subclasses don't repeat it.
    """
    cdef owner_listener *listeners
    cdef int n_listeners

    cdef inline void add_listener(self, int slot, wl_signal *signal) noexcept
    cdef inline int slot_of(self, wl_listener *l) noexcept nogil
    cdef inline void _detach_slot(self, int slot) noexcept nogil
    cdef inline void _detach_all(self) noexcept nogil
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
