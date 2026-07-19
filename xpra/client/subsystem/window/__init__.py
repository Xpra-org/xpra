# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.client.base.stub import StubClientSubsystem
from xpra.util.objects import typedict
from xpra.exit_codes import ExitValue, ExitCode


def get_window_client_base_classes() -> tuple[type, ...]:
    from xpra.client.base import features

    from xpra.client.subsystem.window.manager import WindowManagerClient
    classes: list[type] = [WindowManagerClient]
    from xpra.client.subsystem.window.bell import WindowBell
    classes.append(WindowBell)
    from xpra.client.subsystem.window.border import WindowBorderClient
    classes.append(WindowBorderClient)
    from xpra.client.subsystem.window.close import WindowClose
    classes.append(WindowClose)
    from xpra.client.subsystem.window.draw import WindowDraw
    classes.append(WindowDraw)
    from xpra.client.subsystem.window.focus import WindowFocus
    classes.append(WindowFocus)
    if features.pointer:
        from xpra.client.subsystem.window.pointer import WindowPointer
        classes.append(WindowPointer)
    from xpra.client.subsystem.window.grab import WindowGrab
    classes.append(WindowGrab)
    from xpra.client.subsystem.window.signalwatcher import WindowSignalWatcher
    classes.append(WindowSignalWatcher)
    if features.tray:
        from xpra.client.subsystem.window.tray import WindowTray
        classes.append(WindowTray)
    from xpra.client.subsystem.window.wheel import WindowWheel
    classes.append(WindowWheel)
    from xpra.client.subsystem.window.window_icon import WindowIcon
    classes.append(WindowIcon)
    return tuple(classes)


WINDOW_CLIENT_BASES = get_window_client_base_classes()
WindowClientClass = type("WindowClientClass", WINDOW_CLIENT_BASES, {"__slots__": ()})


class WindowClient(WindowClientClass):
    __slots__ = (
        "_button_state", "_draw_counter", "_focused", "_id_to_window", "_pid_to_signalwatcher",
        "_signalwatcher_to_wids", "_win32_events", "_window_to_id", "_window_with_grab", "auto_refresh_delay",
        "bell_enabled", "border", "border_str", "client_supports_bell", "client_supports_system_tray",
        "input_devices", "lost_focus_timer", "max_window_size", "min_window_size", "modal_windows",
        "overlay_image", "pixel_counter", "pixel_depth", "pointer_grabbed", "poll_pointer_position",
        "poll_pointer_timer", "server_bell", "server_input_devices", "server_precise_wheel",
        "server_window_frame_extents", "server_window_signals", "server_window_states", "wheel_deltax",
        "wheel_deltay", "wheel_map", "wheel_smooth", "window_close_action", "windows_enabled",
    )

    PREFIX = "window"
    # owned by the leaf classes muxed into this composite (manager.py, bell.py),
    # but declared here since that's what `self.__signals__` resolves to at runtime:
    __signals__ = ["new-window", "bell-toggled"]

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        for bc in WINDOW_CLIENT_BASES:
            bc.__init__(self)

    def init(self, opts) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.init(self, opts)

    def init_ui(self, opts) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.init_ui(self, opts)

    def load(self) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.load(self)

    def preload_decode(self) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.preload_decode(self)

    def parse_server_capabilities(self, c: typedict) -> bool:
        for bc in WINDOW_CLIENT_BASES:
            if not bc.parse_server_capabilities(self, c):
                return False
        return True

    def setup_connection(self, conn) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.setup_connection(self, conn)

    def cleanup(self) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.cleanup(self)

    def get_info(self) -> dict[str, Any]:
        info: dict[Any, Any] = {}
        for bc in WINDOW_CLIENT_BASES:
            info.update(bc.get_info(self))
        return {WindowClient.PREFIX: info}

    def get_caps(self) -> dict[str, Any]:
        caps: dict[Any, Any] = {}
        for bc in WINDOW_CLIENT_BASES:
            caps.update(bc.get_caps(self))
        return caps

    def init_authenticated_packet_handlers(self) -> None:
        for bc in WINDOW_CLIENT_BASES:
            bc.init_authenticated_packet_handlers(self)

    def run(self) -> ExitValue:
        for bc in WINDOW_CLIENT_BASES:
            bc.run(self)
        return ExitCode.OK
