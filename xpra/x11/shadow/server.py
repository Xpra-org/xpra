#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.base import ServerBase
from xpra.net.compression import Compressed
from xpra.common import NotificationID
from xpra.os_util import gi_import
from xpra.util.system import is_Wayland, get_loaded_kernel_modules
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.shadow_server_base import ShadowServerBase, try_setup_capture
from xpra.x11.shadow.filter import window_matches
from xpra.x11.shadow.model import X11ShadowModel
from xpra.log import Logger

log = Logger("x11", "shadow")

GObject = gi_import("GObject")


class ShadowX11Server(GTKShadowServerBase):

    def __init__(self, attrs: dict[str, str]):
        GTKShadowServerBase.__init__(self, attrs)
        self.session_type = "X11 shadow"
        self.modify_keymap = False
        self.backend = attrs.get("backend", "x11")
        self.session_files: list[str] = []

    def init(self, opts) -> None:
        GTKShadowServerBase.init(self, opts)
        self.modify_keymap = opts.keyboard_layout.lower() in ("client", "auto")
        self.session_files.append("xauthority")

    def set_keymap(self, server_source, force: bool = False) -> None:
        if self.readonly:
            return
        if self.modify_keymap:
            ServerBase.set_keymap(self, server_source, force)
        else:
            ShadowServerBase.set_keymap(self, server_source, force)

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
            ss.may_notify(NotificationID.SHADOWWAYLAND,
                          "Wayland Shadow Server",
                          "This shadow session seems to be running under wayland,\n"
                          "the screen scraping will probably come up empty",
                          icon_name="unticked")

    def do_get_cursor_data(self) -> tuple[Any, Any]:
        return super().get_cursor_data()

    def send_initial_data(self, ss, c, send_ui: bool, share_count: int) -> None:
        super().send_initial_data(ss, c, send_ui, share_count)
        if getattr(ss, "ui_client", True) and getattr(ss, "send_windows", True):
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
                ss.may_notify(nid, title, body, icon_name="server")
        except Exception as e:
            ss.may_notify(nid, "Shadow Error", f"Error shadowing the display:\n{e}", icon_name="bugs")

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        capabilities["server_type"] = "X11 Shadow"
        return capabilities

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_threaded_info(proto, **kwargs)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/bindings/x11-shadow"
        return info

    def do_make_screenshot_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        from xpra.x11.shadow.backends import setup_gtk_capture
        capture = setup_gtk_capture()
        w, h, encoding, rowstride, data = capture.take_screenshot()
        assert encoding == "png"  # use fixed encoding for now
        # pylint: disable=import-outside-toplevel
        return "screenshot", w, h, encoding, rowstride, Compressed(encoding, data)
