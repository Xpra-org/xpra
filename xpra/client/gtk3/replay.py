# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.client.base.replay import Replay
from xpra.util.objects import typedict
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

    def send(self, packet_type:str, *args, **kwargs) -> None:
        log("ignoring request to send %r", packet_type)

    @staticmethod
    def no_scaling(*args):
        if len(args) == 1:
            return args[0]
        return args

    @staticmethod
    def get_window_frame_sizes(*_args) -> dict[str, Any]:
        return {}

    def make_client_window(self, wid: int, geometry: tuple[int, int, int, int], metadata: typedict):
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
        return ClientWindow(self, group_leader, wid,
                            geometry,
                            backing_size,
                            metadata, override_redirect, client_props,
                            border, max_window_size, pixel_depth, headerbar="no")

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
        return int(replay.run())


def main() -> int:
    from xpra.scripts.config import make_defaults_struct
    return do_main(make_defaults_struct())


if __name__ == "__main__":
    main()
