# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Lazy Gtk loading for the win32 backend.

The backend starts with the `gi` Gtk modules blocked (`no_gi_gtk_modules`) so
that none of the client initialization can pull Gtk in. Nothing is ever imported
by that block - it only poisons the `sys.modules` entries - so it can be undone
on demand, which is what `load_gtk` does the first time a Gtk menu or dialog is
needed.

There is no separate "Gtk main loop" to start: `Gtk.main()` is a `GLib.MainLoop`
on the default main context, and the backend is already running one of those
(see `XpraWin32Client.run_loop`), so widgets are serviced by the loop we have.
The one thing that does need care is `Gdk`'s win32 event source - see
`xpra.client.win32.glib.iterate_main_context`.
"""

from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32", "gtk")

GLib = gi_import("GLib")

GDK_EVENT_SOURCE_NAME = "GDK Win32 event source"

# tri-state: None until `load_gtk` has run, then True / False
_loaded: bool | None = None


def is_loaded() -> bool:
    """Has Gtk been loaded for this client? (never loads it - see `load_gtk`)"""
    return _loaded is True


def _next_source_id(context) -> int:
    """
    The id the context will hand out next, learnt by attaching and immediately
    destroying a throwaway source (GLib has no accessor for it).
    """
    source = GLib.Idle()
    source_id = source.attach(context)
    source.destroy()
    return source_id


def _find_gdk_event_source(context, first: int, last: int):
    for source_id in range(first, last):
        try:
            source = context.find_source_by_id(source_id)
        except Exception:  # the id may have been reused or freed
            continue
        if source is not None and source.get_name() == GDK_EVENT_SOURCE_NAME:
            return source
    return None


def load_gtk() -> bool:
    """
    Unblock and initialize Gtk, and make the modal-loop pump aware of `Gdk`'s
    event source. Returns False if Gtk is unusable, so callers can fall back to
    the native implementation. Safe to call more than once.
    """
    global _loaded
    if _loaded is not None:
        return _loaded
    _loaded = False
    try:
        from xpra.scripts.main import allow_gi_gtk_modules
        allow_gi_gtk_modules()
        context = GLib.MainContext.default()
        # `Gtk.init_check` attaches `Gdk`'s event source to the default context,
        # so bracket it to find out which source ids it created:
        first = _next_source_id(context)
        Gtk = gi_import("Gtk")
        if not Gtk.init_check()[0]:
            log.warn("Warning: failed to initialize Gtk")
            return False
        last = _next_source_id(context)
    except ImportError as e:
        log("load_gtk()", exc_info=True)
        log.warn("Warning: Gtk is not available")
        log.warn(" %s", e)
        return False
    gdk_source = _find_gdk_event_source(context, first, last)
    log("load_gtk() source ids %i..%i, %s=%s", first, last - 1, GDK_EVENT_SOURCE_NAME, gdk_source)
    if gdk_source is None:
        # not fatal: only the modal-loop pump needs it, so warn and carry on
        log.warn(f"Warning: {GDK_EVENT_SOURCE_NAME!r} not found")
        log.warn(" moving or resizing a window may become unresponsive")
    else:
        from xpra.client.win32.glib import set_gdk_event_source
        set_gdk_event_source(gdk_source)
    _loaded = True
    return True
