#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint32_t, uintptr_t

from xpra.log import Logger

log = Logger("wayland", "keyboard")


cdef int handle_client_data(int fd, uint32_t mask, void *data) noexcept:
    """Handle data from the internal client"""
    cdef InternalClient client = <InternalClient> data

    if mask & WL_EVENT_READABLE:
        # Dispatch pending events from the client
        if client._client_display != NULL:
            # Prepare to read
            if wl_display_prepare_read(client._client_display) == 0:
                # Read events
                wl_display_read_events(client._client_display)
                # Dispatch them
                wl_display_dispatch_pending(client._client_display)
            else:
                # Someone else is reading, just dispatch pending
                wl_display_dispatch_pending(client._client_display)

    if mask & (WL_EVENT_HANGUP | WL_EVENT_ERROR):
        # Connection closed or error
        return 0

    return 1


cdef class InternalClient:
    """
    An internal Wayland client that connects to the compositor's own display.
    This allows creating keyboard resources without external clients.
    """

    def __cinit__(self, uintptr_t server_display_ptr, uintptr_t event_loop_ptr):
        """
        Create an internal client connection.

        Args:
            server_display_ptr: Pointer to the server's wl_display
        """
        cdef int sv[2]

        log("InternalClient(%#x)", server_display_ptr)
        self._server_display = <wl_display*> server_display_ptr
        self._server_fd = -1
        self._client_fd = -1
        self._server_client = NULL
        self._client_display = NULL
        self._event_loop = <wl_event_loop*> event_loop_ptr

        # Create a socketpair for communication
        if socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, sv) < 0:
            raise OSError("Failed to create socketpair")

        self._server_fd = sv[0]
        self._client_fd = sv[1]
        log("socketpair=%i,%i", sv[0], sv[1])

        # Create server-side client from the socket
        self._server_client = wl_client_create(self._server_display, self._server_fd)
        log("server_client=%#x", <uintptr_t> self._server_client)
        if self._server_client == NULL:
            close(self._server_fd)
            close(self._client_fd)
            raise RuntimeError("Failed to create server-side client")

        # Connect client-side to the socket
        self._client_display = wl_display_connect_to_fd(self._client_fd)
        log("client_display=%#x", <uintptr_t> self._client_display)
        if self._client_display == NULL:
            wl_client_destroy(self._server_client)
            close(self._client_fd)
            raise RuntimeError("Failed to connect client to server")

        cdef int client_display_fd = wl_display_get_fd(self._client_display)
        self._client_event_source = wl_event_loop_add_fd(self._event_loop, client_display_fd, WL_EVENT_READABLE,
                                                         handle_client_data, <void*>self)

        if self._client_event_source == NULL:
            wl_display_disconnect(self._client_display)
            wl_client_destroy(self._server_client)
            raise RuntimeError("Failed to add client to event loop")

        # Flush any initial messages (non-blocking)
        wl_display_flush(self._client_display)

    def __dealloc__(self):
        self.cleanup()

    def cleanup(self):
        """Clean up the internal client connection"""
        if self._client_display != NULL:
            wl_display_disconnect(self._client_display)
            self._client_display = NULL

        if self._server_client != NULL:
            wl_client_destroy(self._server_client)
            self._server_client = NULL

        # Note: wl_client_destroy closes the server_fd
        # wl_display_disconnect closes the client_fd

    @property
    def server_client(self):
        """Get the server-side wl_client pointer"""
        return <uintptr_t> self._server_client

    @property
    def client_display(self):
        """Get the client-side wl_display pointer"""
        return <uintptr_t> self._client_display

    def dispatch(self):
        """
        Dispatch pending client events (non-blocking).

        Returns:
            True if successful, False on error
        """
        if self._client_display == NULL:
            return False

        # Flush any pending requests
        if wl_display_flush(self._client_display) < 0:
            return False

        # Dispatch any pending events (non-blocking)
        if wl_display_dispatch_pending(self._client_display) < 0:
            return False

        return True

    def roundtrip(self):
        """
        Do a roundtrip (wait for all pending events).

        WARNING: This can block! Use sparingly and not during initialization.

        Returns:
            True if successful, False on error
        """
        if self._client_display == NULL:
            return False

        return wl_display_roundtrip(self._client_display) >= 0

    def flush(self):
        """
        Flush pending requests to the server.

        Returns:
            True if successful, False on error
        """
        if self._client_display == NULL:
            return False

        return wl_display_flush(self._client_display) >= 0
