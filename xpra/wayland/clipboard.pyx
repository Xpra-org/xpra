#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

import os
from collections import defaultdict

from libc.stdint cimport uintptr_t, uint32_t
from libc.stdlib cimport calloc, free, malloc
from libc.string cimport memcpy
from cpython.ref cimport Py_INCREF, Py_DECREF

from xpra.clipboard.common import ClipboardCallback
from xpra.clipboard.proxy import ClipboardProxyCore
from xpra.gtk.clipboard import GTK_Clipboard, GTKClipboardProxy
from xpra.os_util import gi_import
from xpra.util.gobject import n_arg_signal, one_arg_signal
from xpra.util.str_fn import Ellipsizer, bytestostr
from xpra.log import Logger

from xpra.wayland.wlroots cimport (
    wl_array_add,
    wl_display, wl_display_next_serial,
    wlr_seat, wlr_seat_set_primary_selection,
    wlr_primary_selection_source, wlr_primary_selection_source_impl,
    wlr_primary_selection_source_init, wlr_primary_selection_source_destroy,
    wlr_primary_selection_source_send,
)


GLib = gi_import("GLib")
GObject = gi_import("GObject")

log = Logger("wayland", "clipboard")


cdef wlr_primary_selection_source_impl PRIMARY_SOURCE_IMPL


cdef bytes bstr(value):
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf8")


cdef void add_mime_type(wlr_primary_selection_source *source, bytes mime):
    cdef char **slot
    cdef char *value
    cdef size_t size
    if source == NULL or not mime:
        return
    size = len(mime) + 1
    value = <char*> malloc(size)
    if value == NULL:
        raise MemoryError("failed to allocate primary selection mime type")
    memcpy(value, <const char*> mime, size - 1)
    value[size - 1] = 0
    slot = <char**> wl_array_add(&source.mime_types, sizeof(char*))
    if slot == NULL:
        free(value)
        raise MemoryError("failed to append primary selection mime type")
    slot[0] = value


cdef tuple source_mime_types(wlr_primary_selection_source *source):
    cdef char **values
    cdef size_t count
    cdef size_t i
    if source == NULL:
        return ()
    values = <char**> source.mime_types.data
    count = source.mime_types.size // sizeof(char*)
    return tuple(values[i].decode("utf8", "replace") for i in range(count) if values[i] != NULL)


cdef void primary_source_send(wlr_primary_selection_source *source, const char *mime_type, int fd) noexcept:
    try:
        owner = <object> source.data if source != NULL and source.data != NULL else None
        if owner is None:
            os.close(fd)
            return
        owner.send(mime_type.decode("utf8", "replace") if mime_type != NULL else "", fd)
    except Exception:
        log.error("Error sending primary selection contents", exc_info=True)
        try:
            os.close(fd)
        except OSError:
            pass


cdef void primary_source_destroy(wlr_primary_selection_source *source) noexcept:
    try:
        owner = <object> source.data if source != NULL and source.data != NULL else None
        if owner is not None:
            source.data = NULL
            owner.destroyed()
            Py_DECREF(owner)
    except Exception:
        log.error("Error destroying primary selection source", exc_info=True)
    free(source)


cdef class WaylandPrimarySource:
    cdef wlr_primary_selection_source *source
    cdef object proxy
    cdef object target_data

    def __cinit__(self):
        self.source = NULL
        self.proxy = None
        self.target_data = {}

    def __init__(self, proxy, targets, target_data=None):
        cdef bytes mime
        if PRIMARY_SOURCE_IMPL.send == NULL:
            PRIMARY_SOURCE_IMPL.send = primary_source_send
            PRIMARY_SOURCE_IMPL.destroy = primary_source_destroy
        self.proxy = proxy
        self.target_data = target_data or {}
        self.source = <wlr_primary_selection_source*> calloc(1, sizeof(wlr_primary_selection_source))
        if self.source == NULL:
            raise MemoryError("failed to allocate primary selection source")
        wlr_primary_selection_source_init(self.source, &PRIMARY_SOURCE_IMPL)
        Py_INCREF(self)
        self.source.data = <void*> self
        for target in targets or ():
            mime = bstr(target)
            add_mime_type(self.source, mime)

    def ptr(self) -> int:
        return <uintptr_t> self.source

    def destroy(self) -> None:
        cdef wlr_primary_selection_source *source = self.source
        if source != NULL:
            self.source = NULL
            wlr_primary_selection_source_destroy(source)

    def destroyed(self) -> None:
        proxy = self.proxy
        self.source = NULL
        self.proxy = None
        if proxy is not None:
            proxy.primary_source_destroyed(self)

    def send(self, mime_type: str, fd: int) -> None:
        proxy = self.proxy
        if proxy is None:
            os.close(fd)
            return
        proxy.send_remote_contents(mime_type, fd, self.target_data)


cdef class WaylandPrimarySelection:
    cdef wlr_seat *seat
    cdef wl_display *display

    def __init__(self, uintptr_t display_ptr, uintptr_t seat_ptr):
        self.display = <wl_display*> display_ptr
        self.seat = <wlr_seat*> seat_ptr

    def set_source(self, WaylandPrimarySource source) -> None:
        cdef uint32_t serial
        if self.display == NULL or self.seat == NULL:
            return
        serial = wl_display_next_serial(self.display)
        wlr_seat_set_primary_selection(self.seat, source.source, serial)

    def clear(self) -> None:
        cdef uint32_t serial
        if self.display == NULL or self.seat == NULL:
            return
        serial = wl_display_next_serial(self.display)
        wlr_seat_set_primary_selection(self.seat, NULL, serial)

    def source_targets(self, uintptr_t source_ptr) -> tuple:
        return source_mime_types(<wlr_primary_selection_source*> source_ptr)

    def send_source(self, uintptr_t source_ptr, str target, int fd) -> None:
        cdef bytes mime = bstr(target)
        cdef wlr_primary_selection_source *source = <wlr_primary_selection_source*> source_ptr
        if source == NULL:
            os.close(fd)
            return
        wlr_primary_selection_source_send(source, <const char*> mime, fd)


class WaylandPrimaryClipboardProxy(ClipboardProxyCore, GObject.GObject):
    __gsignals__ = {
        "send-clipboard-token": one_arg_signal,
        "send-clipboard-request": n_arg_signal(2),
    }

    def __init__(self, selection, compositor):
        ClipboardProxyCore.__init__(self, selection)
        GObject.GObject.__init__(self)
        self.compositor = compositor
        self.primary = WaylandPrimarySelection(compositor.get_display_ptr(), compositor.get_seat_ptr())
        self.local_source_ptr = 0
        self.remote_source = None
        self.remote_source_ptr = 0
        self.targets = ()
        self.target_data = {}
        self.pending_reads = {}
        self.pending_writes = defaultdict(list)
        compositor.connect("primary-selection", self.primary_selection_changed)

    def __repr__(self):
        return "WaylandPrimaryClipboardProxy(%s)" % self._selection

    def cleanup(self) -> None:
        super().cleanup()
        for rfd, (_, source_id, _) in tuple(self.pending_reads.items()):
            self.pending_reads.pop(rfd, None)
            GLib.source_remove(source_id)
            try:
                os.close(rfd)
            except OSError:
                pass
        for fds in tuple(self.pending_writes.values()):
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.pending_writes.clear()
        if self.remote_source:
            self.remote_source.destroy()
            self.remote_source = None
            self.remote_source_ptr = 0

    def primary_selection_changed(self, source_ptr: int) -> None:
        log("primary_selection_changed(%#x) remote=%#x", source_ptr, self.remote_source_ptr)
        self.local_source_ptr = source_ptr
        if source_ptr == self.remote_source_ptr:
            return
        if source_ptr == 0:
            self.targets = ()
            self.target_data = {}
            return
        self.targets = self.primary.source_targets(source_ptr)
        self.target_data = {}
        self.do_owner_changed()

    def primary_source_destroyed(self, source) -> None:
        if source is self.remote_source:
            self.remote_source = None
            self.remote_source_ptr = 0

    def do_owner_changed(self) -> None:
        if not self._enabled:
            return
        self.schedule_emit_token()

    def schedule_emit_token(self, min_delay=0) -> None:
        self._have_token = False
        targets = self.targets if (self._want_targets or self._greedy_client) else ()
        self.emit("send-clipboard-token", (targets,))

    def get_contents(self, target: str, got_contents: ClipboardCallback) -> None:
        log("get_contents(%s, %s) source=%#x", target, got_contents, self.local_source_ptr)
        if target == "TARGETS":
            got_contents("ATOM", 32, self.targets)
            return
        if target_data := self.target_data.get(target):
            dtype, dformat, data = target_data
            got_contents(dtype, dformat, data)
            return
        source_ptr = self.local_source_ptr
        if not source_ptr or source_ptr == self.remote_source_ptr:
            got_contents(target, 0, b"")
            return
        rfd, wfd = os.pipe()
        os.set_blocking(rfd, False)
        data = bytearray()

        def io_callback(fd, condition):
            if condition & GLib.IO_IN:
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    return True
                if chunk:
                    data.extend(chunk)
                    return True
            self.pending_reads.pop(fd, None)
            try:
                os.close(fd)
            except OSError:
                pass
            got_contents(target, 8, bytes(data))
            return False

        source_id = GLib.io_add_watch(rfd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, io_callback)
        self.pending_reads[rfd] = (data, source_id, got_contents)
        self.primary.send_source(source_ptr, target, wfd)
        try:
            os.close(wfd)
        except OSError:
            pass

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got_token(%s, %s, claim=%s)", targets, Ellipsizer(target_data), claim)
        self.targets = tuple(bytestostr(x) for x in (targets or ()))
        self.target_data = target_data or {}
        if not claim or not self._can_receive:
            return
        if not self.targets and not self.target_data:
            if self.remote_source:
                self.remote_source.destroy()
                self.remote_source = None
                self.remote_source_ptr = 0
            self._have_token = False
            return
        source = WaylandPrimarySource(self, self.targets or self.target_data.keys(), self.target_data)
        self.remote_source = source
        self.remote_source_ptr = source.ptr()
        self.primary.set_source(source)
        self._have_token = True

    def send_remote_contents(self, target: str, fd: int, target_data=None) -> None:
        if target_data and target in target_data:
            dtype, dformat, data = target_data[target]
            self.write_fd(fd, data)
            return
        self.pending_writes[target].append(fd)
        self.emit("send-clipboard-request", self._selection, target)

    def got_contents(self, target: str, dtype="", dformat=0, data=b"") -> None:
        if target == "TARGETS" and data:
            self.targets = tuple(bytestostr(x) for x in data)
        fds = self.pending_writes.pop(target, ())
        for fd in fds:
            self.write_fd(fd, data or b"")

    @staticmethod
    def write_fd(fd: int, data) -> None:
        try:
            if isinstance(data, str):
                data = data.encode("utf8")
            elif isinstance(data, memoryview):
                data = bytes(data)
            os.write(fd, data or b"")
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


GObject.type_register(WaylandPrimaryClipboardProxy)


class WaylandClipboard(GTK_Clipboard):

    def __init__(self, *args, compositor=None, **kwargs):
        self.compositor = compositor
        super().__init__(*args, **kwargs)
        if compositor is not None:
            self.local_want_targets = tuple(dict.fromkeys((*self.local_want_targets, "PRIMARY")))

    def __repr__(self):
        return "WaylandClipboard"

    def make_proxy(self, selection):
        if selection == "PRIMARY" and self.compositor is not None:
            proxy = WaylandPrimaryClipboardProxy(selection, self.compositor)
        else:
            proxy = GTKClipboardProxy(selection)
        proxy.set_want_targets(self.proxy_want_targets(selection))
        proxy.set_direction(self.can_send, self.can_receive)
        proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
        proxy.connect("send-clipboard-request", self._send_clipboard_request_handler)
        return proxy
