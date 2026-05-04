# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from libc.stdlib cimport calloc, free

from xpra.wayland.wlroots cimport wl_listener, wl_signal, wl_list_remove


cdef void listener_dispatch(wl_listener *listener, void *data) noexcept:
    cdef ListenerObject obj = <ListenerObject> owner_of(listener)
    obj.dispatch(listener, data)


cdef class ListenerObject:

    def __cinit__(self):
        # Listeners array is allocated lazily in __init__ (when the slot
        # count is known). All cdef pointer/int fields are zero-initialised
        # by Cython's tp_alloc, so listeners==NULL and n_listeners==0 here.
        pass

    def __init__(self, int n_listeners):
        if n_listeners <= 0:
            raise ValueError("ListenerObject n_listeners must be > 0, got %i" % n_listeners)
        if self.listeners != NULL:
            raise RuntimeError("listener object is already allocated!")
        self.listeners = <owner_listener*> calloc(n_listeners, sizeof(owner_listener))
        if self.listeners == NULL:
            raise MemoryError("failed to allocate %i wl_listeners" % n_listeners)
        self.n_listeners = n_listeners

    def __dealloc__(self):
        # Idempotent: subclass destroy paths typically detach already, this
        # guards the case where a Python caller held a reference past destroy.
        self._detach_all()
        if self.listeners != NULL:
            free(self.listeners)
            self.listeners = NULL
        self.n_listeners = 0

    cdef inline void add_listener(self, int slot, wl_signal *signal) noexcept:
        if self.listeners == NULL:
            raise RuntimeError("cannot add listener: object not initialized")
        self.listeners[slot].owner = <void*>self
        self.listeners[slot].listener.notify = listener_dispatch
        wl_signal_add(signal, &self.listeners[slot].listener)

    cdef inline int slot_of(self, wl_listener *l) noexcept nogil:
        # Pointer arithmetic recovers the slot index from the wl_listener
        # address. Works because owner_listener.listener is the first field
        # of each entry (so &xl == &xl.listener).
        return <int>((<char*>l - <char*>self.listeners) / sizeof(owner_listener))

    cdef inline void _detach_slot(self, int slot) noexcept nogil:
        cdef owner_listener *listeners = self.listeners
        if listeners == NULL or slot < 0 or slot >= self.n_listeners:
            return
        if listeners[slot].listener.link.next != NULL:
            wl_list_remove(&listeners[slot].listener.link)
            listeners[slot].listener.link.next = NULL
            listeners[slot].listener.link.prev = NULL

    cdef inline void _detach_all(self) noexcept nogil:
        cdef int i
        if self.listeners == NULL:
            return
        for i in range(self.n_listeners):
            self._detach_slot(i)

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        # Subclass override. Default is a no-op so an unwired listener
        # firing doesn't crash, just logs nothing.
        pass
