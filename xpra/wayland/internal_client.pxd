#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint32_t, int32_t


cdef extern from "wayland-server-core.h":
    cdef struct wl_display:
        pass

    cdef struct wl_client:
        pass

    cdef struct wl_event_loop:
        pass

    cdef struct wl_resource:
        pass

    cdef struct wl_event_source:
        pass

    ctypedef int (*wl_event_loop_fd_func_t)(int fd, uint32_t mask, void *data)

    # Create a client from a file descriptor
    wl_client* wl_client_create(wl_display *display, int fd)

    void wl_client_destroy(wl_client *client)

    wl_display* wl_client_get_display(wl_client *client)

    wl_event_source* wl_event_loop_add_fd(wl_event_loop *loop, int fd, uint32_t mask,
                                          wl_event_loop_fd_func_t func, void *data)
    void wl_event_source_remove(wl_event_source *source)

    # Event mask flags
    cdef enum:
        WL_EVENT_READABLE = 0x01
        WL_EVENT_WRITABLE = 0x02
        WL_EVENT_HANGUP = 0x04
        WL_EVENT_ERROR = 0x08


cdef extern from "wayland-client.h":
    # Note: This is a different wl_display (client-side)
    cdef struct wl_display:
        pass

    cdef struct wl_proxy:
        pass

    cdef struct wl_registry:
        pass

    wl_display* wl_display_connect_to_fd(int fd)
    void wl_display_disconnect(wl_display *display)
    int wl_display_dispatch(wl_display *display)
    int wl_display_dispatch_pending(wl_display *display)
    int wl_display_flush(wl_display *display)
    int wl_display_roundtrip(wl_display *display)
    int wl_display_get_fd(wl_display *display)
    int wl_display_prepare_read(wl_display *display)
    int wl_display_read_events(wl_display *display)
    void wl_display_cancel_read(wl_display *display)


cdef extern from "unistd.h":
    int socketpair(int domain, int type, int protocol, int sv[2])
    int close(int fd)

    # Socket constants
    int AF_UNIX
    int SOCK_STREAM


cdef extern from "sys/socket.h":
    int SOCK_CLOEXEC


cdef class InternalClient:
    cdef int _server_fd
    cdef int _client_fd
    cdef wl_client *_server_client      # Server-side client handle
    cdef wl_display *_client_display    # Client-side display handle
    cdef wl_display *_server_display    # Server-side display
    cdef wl_event_loop *_event_loop
    cdef wl_event_source *_client_event_source
