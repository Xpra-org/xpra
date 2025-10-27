# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.util.str_fn import csv
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("x11", "bindings", "events")
GObject = gi_import("GObject")

event_receivers_map: dict[int, set] = {}
fallback_receivers: dict[str, list] = {}
catchall_receivers: dict[str, list] = {}
debug_route_events: list[int] = []


def add_event_receiver(xid: int, receiver, max_receivers=3) -> None:
    receivers = event_receivers_map.setdefault(xid, set())
    if 0 < max_receivers < len(receivers):
        from xpra.x11.window_info import window_info
        log.warn("Warning: already too many event receivers")
        log.warn(f" for {window_info(xid)!r}: {len(receivers)}")
        log.warn(f" adding {receiver!r} to {receivers}", backtrace=True)
    receivers.add(receiver)


def remove_event_receiver(xid: int, receiver) -> None:
    receivers = event_receivers_map.get(xid)
    if receivers is None:
        return
    receivers.discard(receiver)
    if not receivers:
        event_receivers_map.pop(xid)


def add_catchall_receiver(signal: str, handler) -> None:
    catchall_receivers.setdefault(signal, []).append(handler)
    log("add_catchall_receiver(%s, %s) -> %s", signal, handler, catchall_receivers)


def remove_catchall_receiver(signal: str, handler) -> None:
    receivers = catchall_receivers.get(signal)
    if receivers:
        receivers.remove(handler)
    log("remove_catchall_receiver(%s, %s) -> %s", signal, handler, catchall_receivers)


def add_fallback_receiver(signal: str, handler) -> None:
    fallback_receivers.setdefault(signal, []).append(handler)
    log("add_fallback_receiver(%s, %s) -> %s", signal, handler, fallback_receivers)


def remove_fallback_receiver(signal: str, handler) -> None:
    receivers = fallback_receivers.get(signal, [])
    if receivers:
        receivers.remove(handler)
    log("remove_fallback_receiver(%s, %s) -> %s", signal, handler, fallback_receivers)


# and change this debugging on the fly, programmatically:
def add_debug_route_event(event_type: int) -> None:
    debug_route_events.append(event_type)


def remove_debug_route_event(event_type: int) -> None:
    debug_route_events.remove(event_type)


def set_debug_events() -> None:
    from xpra.x11.bindings.events import names_to_event_type
    global debug_route_events
    XPRA_X11_DEBUG_EVENTS = os.environ.get("XPRA_X11_DEBUG_EVENTS", "")
    debug_set = set()
    ignore_set = set()
    for n in XPRA_X11_DEBUG_EVENTS.split(","):
        name = n.strip()
        if len(name)==0:
            continue
        if name[0]=="-":
            event_set = ignore_set
            name = name[1:]
        else:
            event_set = debug_set
        if name in ("*", "all"):
            events = names_to_event_type.keys()
        elif name in names_to_event_type:
            events = [name]
        else:
            log("unknown X11 debug event type: %s", name)
            continue
        # add to correct set:
        for e in events:
            event_set.add(e)
    events = debug_set.difference(ignore_set)
    debug_route_events = [names_to_event_type.get(x) for x in events]
    if len(events)>0:
        log.warn("debugging of X11 events enabled for:")
        log.warn(" %s", csv(events))
        log.warn(" event codes: %s", csv(debug_route_events))


def cleanup_all_event_receivers() -> None:
    event_receivers_map.clear()


def _maybe_send_event(debug: bool, handlers: Sequence | set, signal: str, event, hinfo="window") -> None:
    if not handlers:
        if debug:
            log.info("  no handler registered for %s (%s)", hinfo, handlers)
        return
    # Copy the 'handlers' list, because signal handlers might cause items
    # to be added or removed from it while we are iterating:
    for handler in tuple(handlers):
        signals = GObject.signal_list_names(handler)
        if signal in signals:
            if debug:
                log.info("  forwarding event to a %s %s handler's %s signal", type(handler).__name__, hinfo, signal)
            handler.emit(signal, event)
            if debug:
                log.info("  forwarded")
        elif debug:
            log.info("  not forwarding to %s handler, it has no %r signal", type(handler).__name__, signal)
            log.info("     only: %s", tuple(f"{s!r}" for s in signals))


def route_event(etype: int, event, signal: str, parent_signal: str) -> None:
    # Sometimes we get GDK events with event.window == None, because they are
    # for windows we have never created a GdkWindow object for, and GDK
    # doesn't do so just for this event.  As far as I can tell this only
    # matters for override redirect windows when they disappear, and we don't
    # care about those anyway.
    debug = etype in debug_route_events
    if debug:
        log.info(f"{event}")
    handlers: Sequence | set = ()
    if event.window == event.delivered_to:
        window = event.window
        if signal:
            if debug:
                log.info(f"  delivering {signal!r} to window itself: {window:x}")
            if window:
                handlers = event_receivers_map.get(window, ())
                _maybe_send_event(debug, handlers, signal, event, "window %#x" % window)
        elif debug:
            log.info(f"  received event on window {window:x} itself but have no signal for that")
    else:
        window = event.delivered_to
        if parent_signal:
            if not window:
                if debug:
                    log.info(f"  event.delivered_to={window}, ignoring")
            else:
                if debug:
                    log.info(f"  delivering {parent_signal!r} to parent window: {window:x}")
                handlers = event_receivers_map.get(window, ())
                _maybe_send_event(debug, handlers, parent_signal, event, "parent window %#x" % window)
        else:
            if debug:
                log.info(f"  received event on parent window {window:x} but have no parent signal")

    # fallback only fires if nothing else has fired yet:
    if not handlers:
        if signal:
            handlers = fallback_receivers.get(signal, ())
            _maybe_send_event(debug, handlers, signal, event, "fallback-signal")
        if parent_signal:
            handlers = fallback_receivers.get(parent_signal, ())
            _maybe_send_event(debug, handlers, parent_signal, event, "fallback-parent-signal")

    # always fire those:
    if signal:
        handlers = catchall_receivers.get(signal, ())
        _maybe_send_event(debug, handlers, signal, event, "catchall-signal")
    if parent_signal:
        handlers = catchall_receivers.get(parent_signal, ())
        _maybe_send_event(debug, handlers, parent_signal, event, "catchall-parent-signal")
