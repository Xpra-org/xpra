# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.env import envbool, envint, first_time
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("posix", "dbus", "events")


DBUS_SCREENSAVER = envbool("XPRA_DBUS_SCREENSAVER", True)
DBUS_LOGIN1 = envbool("XPRA_DBUS_LOGIN1", True)
DBUS_UPOWER = envbool("XPRA_DBUS_UPOWER", True)
FAKE_POWER_EVENTS = envint("XPRA_FAKE_POWER_EVENTS", 0)

bus_signal_match: dict[tuple[str, Callable], list[Callable[[], None]]] = {}


def load_dbus() -> bool:
    loaded = "xpra.dbus" in sys.modules
    try:
        import xpra.dbus
        assert xpra.dbus
    except ImportError:
        log("load_dbus()", exc_info=True)
        if not loaded:
            log.info("no dbus support")
        return False

    try:
        from xpra.dbus.common import init_system_bus, init_session_bus
        log(f"loaded init functions: {init_system_bus}, {init_session_bus}")
    except ImportError as e:
        log("system_bus()", exc_info=True)
        log.error("Error: the xpra dbus bindings are missing,")
        log.error(" cannot setup event listeners:")
        log.estr(e)
        return False

    try:
        import dbus
        assert dbus
        return True
    except ImportError as e:
        log("system_bus()", exc_info=True)
        if first_time("no-dbus"):
            log.warn("Warning: cannot setup dbus signals")
            log.warn(f" {e}")
    return False


def get_system_bus():
    if not load_dbus():
        return None
    from xpra.dbus.common import init_system_bus
    return init_system_bus()


def get_session_bus():
    if not load_dbus():
        return None
    from xpra.dbus.common import init_session_bus
    return init_session_bus()


UPOWER_BUS_NAME = "org.freedesktop.UPower"
UPOWER_IFACE_NAME = UPOWER_BUS_NAME

LOGIN1_BUS_NAME = "org.freedesktop.login1"
LOGIN1_IFACE_NAME = f"{LOGIN1_BUS_NAME}.Manager"

SCREENSAVER_BUS_NAME = "org.gnome.ScreenSaver"
SCREENSAVER_IFACE_NAME = SCREENSAVER_BUS_NAME


def add_bus_handler(get_bus: Callable, callback: Callable, signal: str, iface: str, bus_name: str) -> Callable | None:
    # ie: add_bus_handler(system_bus, "Sleeping", UPOWER_IFACE_NAME, UPOWER_BUS_NAME)
    try:
        bus = get_bus()
    except Exception as e:
        log("add_bus_handler%s", (get_bus, callback, signal, iface, bus_name), exc_info=True)
        log.warn(f"Warning: no bus for {signal!r}: {e}")
        return None
    if not bus:
        return None
    log(f"{bus}.add_signal_receiver({callback}, {signal!r}, {iface!r}, {bus_name!r})")
    try:
        match = bus.add_signal_receiver(callback, signal, iface, bus_name)
    except (ValueError, RuntimeError) as e:
        log(f"failed to add bus handler for {signal!r}: {e}")
        return None
    if not match:
        return None

    def cleanup() -> None:
        bus._clean_up_signal_match(match)
    return cleanup


def add_handler(event: str, handler: Callable) -> None:
    log(f"add_handler({event!r}, {handler})")

    def forward(*args) -> None:
        log(f"event: {event!r}, calling {handler}")
        try:
            handler(args)
        except Exception as e:
            log.error(f"Error handling {event!r} event")
            log.error(f" using {handler}:")
            log.estr(e)

    def add(*args):
        cleanup = add_bus_handler(*args)
        if cleanup:
            bus_signal_match.setdefault((event, handler), []).append(cleanup)

    # (deprecated - may not be available) UPower events:
    if DBUS_UPOWER:
        if event == "suspend":
            add(get_system_bus, forward, "Sleeping", UPOWER_IFACE_NAME, UPOWER_BUS_NAME)
        elif event == "resume":
            add(get_system_bus, forward, "Resuming", UPOWER_IFACE_NAME, UPOWER_BUS_NAME)
        else:
            log(f"unsupported posix event: {event!r}")
            return

    if DBUS_LOGIN1:
        # same event via login1:
        if event in ("suspend", "resume"):
            def prepare_for_sleep(suspend) -> None:
                if (suspend and event == "suspend") or (not suspend and event == "resume"):
                    forward(suspend)
            add(get_system_bus, prepare_for_sleep, "PrepareForSleep", LOGIN1_IFACE_NAME, LOGIN1_BUS_NAME)

    if DBUS_SCREENSAVER:
        def active_changed(active) -> None:
            log("ActiveChanged(%s)", active)
            if (active and event == "suspend") or (not active and event == "resume"):
                forward(active)
        add(get_session_bus, active_changed, "ActiveChanged", SCREENSAVER_IFACE_NAME, SCREENSAVER_BUS_NAME)

    if FAKE_POWER_EVENTS:
        def emit_fake_event() -> bool:
            log.warn("Warning: faking %r event", event)
            forward()
            return False

        def faker() -> bool:
            # each event type will have its own delay offset:
            delay = sum(ord(c)*50 for c in event) % (1000 * FAKE_POWER_EVENTS)
            GLib.timeout_add(delay, emit_fake_event)
            return True

        source = GLib.timeout_add(FAKE_POWER_EVENTS * 1000, faker)

        def cleanup() -> None:
            GLib.source_remove(source)

        bus_signal_match.setdefault((event, handler), []).append(cleanup)


def remove_handler(event: str, handler: Callable) -> None:
    remove = bus_signal_match.get((event, handler), ())
    log(f"remove_handler({event!r}, {handler}) calling {remove}")
    for x in remove:
        x()
