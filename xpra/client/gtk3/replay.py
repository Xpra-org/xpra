# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from types import FrameType

from xpra.exit_codes import ExitValue
from xpra.util.glib import install_signal_handlers
from xpra.util.objects import typedict
from xpra.client.base.replay import Replay, WindowModel
from xpra.net import common as net_common
from xpra.common import noop
from xpra.log import Logger

log = Logger("client")

net_common.BACKWARDS_COMPATIBLE = False


class GtkReplay(Replay):

    def __init__(self, options):
        Replay.__init__(self, options)
        from xpra.codecs.loader import load_codec
        load_codec("dec_pillow")
        # fake client methods:
        self.xscale = self.yscale = 1
        self.default_cursor_data = self._load_default_cursor()
        self.server_window_frame_extents = False
        self.wheel_smooth = False
        self.encoding_defaults = {}
        self.readonly = True
        self.title = "replay: @title@"
        self.find_window = noop
        self.update_focus = noop
        self.sp = self.sx = self.sy = self.srect = self.no_scaling
        self.cx = self.cy = self.no_scaling
        self.fsx = self.fsy = self.no_scaling

    def __repr__(self):
        return "GtkReplay"

    def run(self) -> ExitValue:
        install_signal_handlers("replay", self.handle_app_signal)
        return super().run()

    def handle_app_signal(self, signum: int, _frame: FrameType = None) -> None:
        self.quit(128 - signum)

    def send(self, packet_type:str, *args, **kwargs) -> None:
        log("ignoring request to send %r", packet_type)

    @staticmethod
    def no_scaling(*args):
        if len(args) == 1:
            return args[0]
        return args

    @staticmethod
    def _load_default_cursor() -> tuple:
        import os.path
        from xpra.platform.paths import get_icon_dir
        filename = os.path.join(get_icon_dir(), "cross.png")
        if os.path.exists(filename):
            try:
                from PIL import Image
                img = Image.open(filename).convert("RGBA")
                w, h = img.size
                pixels = img.tobytes("raw", "BGRA")
                return "raw", 0, 0, w, h, w // 2, h // 2, 0, pixels, "cross"
            except Exception as e:
                log("failed to load default cursor from %r: %s", filename, e)
        return ()

    @staticmethod
    def get_window_frame_sizes(*_args) -> dict[str, Any]:
        return {}

    def make_client_window(self, wid: int, geometry: tuple[int, int, int, int], metadata: typedict):
        if wid == 0:
            return WindowModel(wid)

        def get_window_base_classes() -> tuple[type, ...]:
            from xpra.client.gtk3.window.base import GTKClientWindowBase
            from xpra.client.gtk3.window.pointer import PointerWindow
            WINDOW_BASES: list[type] = [GTKClientWindowBase, PointerWindow]
            return tuple(WINDOW_BASES)

        from xpra.client.gtk3.window import factory
        factory.get_window_base_classes = get_window_base_classes
        from xpra.client.gtk3.window.window import ClientWindow
        group_leader = None
        backing_size = geometry[2:4]
        override_redirect = metadata.boolget("override-redirect", False)
        client_props = typedict()
        from xpra.client.gui.window_border import WindowBorder
        border = WindowBorder()
        max_window_size = 2 ** 15, 2 ** 15
        pixel_depth = metadata.intget("pixel-depth", 24)
        window = ClientWindow(self, group_leader, wid,
                              geometry,
                              backing_size,
                              metadata, override_redirect, client_props,
                              border, max_window_size, pixel_depth, headerbar="no")
        # new_backing() was already called during __init__ and read default_cursor_data
        # from the window, which didn't have it yet — patch both window and backing now:
        window.default_cursor_data = self.default_cursor_data
        if window._backing:
            window._backing.default_cursor_data = self.default_cursor_data
        return window

    @staticmethod
    def get_root_size() -> tuple[int, int]:
        from xpra.gtk.util import get_root_size
        return get_root_size()

    def client_toolkit(self) -> str:
        raise "gtk replay"


def do_main(options) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Replay"):
        replay = GtkReplay(options)
        replay.load()
        return int(replay.run())


def main() -> int:
    from xpra.scripts.config import make_defaults_struct
    return do_main(make_defaults_struct())


if __name__ == "__main__":
    main()
