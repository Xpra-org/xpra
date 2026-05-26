#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import may_notify_client
from xpra.constants import NotificationID
from xpra.os_util import gi_import
from xpra.server.common import get_sources_by_type
from xpra.util.gobject import one_arg_signal
from xpra.util.system import is_Wayland, get_loaded_kernel_modules
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.shadow_server_base import try_setup_capture
from xpra.x11.shadow.filter import window_matches
from xpra.x11.shadow.model import X11ShadowModel
from xpra.log import Logger

log = Logger("x11", "shadow")

GObject = gi_import("GObject")


class ShadowX11Server(GTKShadowServerBase):
    # X11 dispatch signals consumed by the bell / cursor subsystems.
    # Declared here (not on the subsystems) because X11 dispatch requires
    # a GObject receiver - see `BellServer` / `XCursorServer` docstrings.
    __gsignals__ = dict(GTKShadowServerBase.__gsignals__)
    __gsignals__.update({
        "x11-xkb-event": one_arg_signal,
        "x11-cursor-event": one_arg_signal,
    })

    def __init__(self, attrs: dict[str, str]):
        GTKShadowServerBase.__init__(self, attrs)
        self.session_type = "X11 shadow"
        self.backend = attrs.get("backend", "x11")

    def get_display_subsystem_class(self) -> type:
        from xpra.x11.shadow.display import X11ShadowDisplayManager
        return X11ShadowDisplayManager

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.x11.shadow.keyboard import X11ShadowKeyboardManager
        return X11ShadowKeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.x11.shadow.pointer import X11ShadowPointerManager
        return X11ShadowPointerManager

    def get_cursor_subsystem_class(self) -> type:
        from xpra.x11.subsystem.cursor import XCursorServer
        return XCursorServer

    def init(self, opts) -> None:
        GTKShadowServerBase.init(self, opts)
        if sf := self.get_subsystem("session-files"):
            sf.session_files.append("xauthority")

    def set_initial_resolution(self) -> None:
        # shadow servers must not change the host display resolution
        pass

    def cleanup(self) -> None:
        GTKShadowServerBase.cleanup(self)
        from xpra.x11.xroot_props import root_del
        for prop in ("XPRA_SERVER_UUID", "XPRA_SERVER_MODE"):
            try:
                root_del(prop)
            except Exception:
                log("cleanup() failed to remove X11 attribute", exc_info=True)

    def setup_capture(self):
        from xpra.x11.shadow.backends import CAPTURE_BACKENDS
        capture = try_setup_capture(CAPTURE_BACKENDS, self.backend)
        log(f"setup_capture() {self.backend} : {capture}")
        return capture

    def get_root_window_model_class(self) -> type:
        return X11ShadowModel

    def makeDynamicWindowModels(self):
        assert self.window_matches
        rwmc = self.get_root_window_model_class()
        from xpra.gtk.util import get_default_root_window
        root = get_default_root_window()

        def model_class(title, geometry):
            model = rwmc(root, self.capture, title, geometry)
            model.dynamic_property_names.append("size-constraints")
            return model

        return window_matches(self.window_matches, model_class)

    def client_startup_complete(self, ss) -> None:
        super().client_startup_complete(ss)
        log("is_Wayland()=%s", is_Wayland())
        if is_Wayland():
            may_notify_client(ss, NotificationID.SHADOWWAYLAND,
                              "Wayland Shadow Server",
                              "This shadow session seems to be running under wayland,\n"
                              "the screen scraping will probably come up empty",
                              icon_name="unticked")

    def send_initial_data(self, ss) -> None:
        super().send_initial_data(ss)
        try:
            from xpra.server.source.window import WindowsConnection
        except ImportError:
            window_sources = ()
        else:
            window_sources = get_sources_by_type(self, WindowsConnection)
        if window_sources:
            self.verify_capture(ss)

    def verify_capture(self, ss) -> None:
        log(f"verify_capture({ss})")
        nid = NotificationID.DISPLAY
        try:
            from xpra.x11.shadow.backends import setup_gtk_capture
            capture = setup_gtk_capture()
            bdata = capture.take_screenshot()[-1]
            title = body = ""
            if any(b != 0 for b in bdata):
                log("verify_capture(%s) succeeded", ss)
            else:
                log.warn("Warning: shadow screen capture is blank")
                body = "The shadow display capture is blank"
                if get_loaded_kernel_modules("vboxguest", "vboxvideo"):
                    body += "\nthis may be caused by the VirtualBox video driver."
                if is_Wayland():
                    body += "Wayland sessions cannot be shadowed in X11 mode."
                title = "Shadow Capture Failure"
            log("verify_capture: title=%r, body=%r", title, body)
            if title and body:
                may_notify_client(ss, nid, title, body, icon_name="server")
        except Exception as e:
            may_notify_client(ss, nid, "Shadow Error", f"Error shadowing the display:\n{e}", icon_name="bugs")

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        capabilities["server_type"] = "X11 Shadow"
        return capabilities

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_threaded_info(proto, **kwargs)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/bindings/x11-shadow"
        return info
