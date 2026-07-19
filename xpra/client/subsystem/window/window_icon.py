# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import time

from xpra.common import noop
from xpra.net.common import Packet
from xpra.util.str_fn import memoryview_to_bytes
from xpra.os_util import OSX
from xpra.util.system import is_Ubuntu
from xpra.util.env import envint, envbool, first_time
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

log = Logger("window")

DYNAMIC_TRAY_ICON: bool = envbool("XPRA_DYNAMIC_TRAY_ICON", not OSX and not is_Ubuntu())
ICON_OVERLAY: int = envint("XPRA_ICON_OVERLAY", 50)
ICON_SHRINKAGE: int = envint("XPRA_ICON_SHRINKAGE", 75)


def get_save_window_icons() -> bool:
    if not envbool("XPRA_SAVE_WINDOW_ICONS", False):
        return False
    # icons are decoded from the decode thread, which runs under a seccomp filter
    # that blocks file access - writing there would kill the process (see Seccomp.md):
    try:
        from xpra.seccomp import is_enabled
    except ImportError:
        return True
    if is_enabled():
        log.warn("Warning: 'XPRA_SAVE_WINDOW_ICONS' is ignored because seccomp is enabled")
        return False
    return True


SAVE_WINDOW_ICONS: bool = get_save_window_icons()


def load_overlay_image(icon_filename: str):
    if ICON_OVERLAY < 0:
        return None
    from xpra.platform.paths import get_icon_filename
    if icon_filename and not os.path.isabs(icon_filename):
        icon_filename = get_icon_filename(icon_filename)
    if not icon_filename or not os.path.exists(icon_filename):
        icon_filename = get_icon_filename("xpra")
    log("window icon overlay: %s", icon_filename)
    if not icon_filename:
        return None
    # pylint: disable=import-outside-toplevel
    # make sure Pillow's PNG image loader doesn't spam the output with debug messages:
    import logging
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO)
    try:
        from PIL import Image
    except ImportError:
        log.info("window icon overlay requires python-pillow")
        return None
    with log.trap_error(f"Error: failed to load overlay icon {icon_filename!r}"):
        img = Image.open(icon_filename)
        img.load()
        return img


class WindowIcon(StubClientSubsystem):
    __slots__ = ()

    def __init__(self):
        self.overlay_image = None

    def init(self, opts) -> None:
        self.overlay_image = load_overlay_image(opts.tray_icon)
        log("overlay_image=%s", self.overlay_image)

    def preload_decode(self) -> None:
        # `window_icon_image` runs on the decode thread, where a first-time import
        # would be blocked by the seccomp filter - so do them here instead:
        try:
            from PIL import Image
            from xpra.codecs.pillow.decoder import open_only
            log("preload_decode() Image=%s, open_only=%s", Image, open_only)
        except ImportError as e:
            log("preload_decode()", exc_info=True)
            log.info("window icons require python-pillow: %s", e)

    def cleanup(self) -> None:
        self.overlay_image = None

    def reinit_window_icons(self) -> None:
        # make sure the window icons are the ones we want:
        log("reinit_window_icons()")
        for wid in tuple(self._id_to_window.keys()):
            if window := self.get_window(wid):
                reset_icon = getattr(window, "reset_icon", None)
                if reset_icon:
                    reset_icon()

    ######################################################################
    # combine the window icon with our own icon
    def window_icon_image(self, wid: int, width: int, height: int, coding: str, data):
        # convert the data into a pillow image,
        # adding the icon overlay (if enabled)
        try:
            # pylint: disable=import-outside-toplevel
            from PIL import Image
        except ImportError:
            if first_time("window-icons-require-pillow"):
                log.info("showing window icons requires python-pillow")
            return None
        log("%s.update_icon(%s, %s, %s, %s bytes) ICON_SHRINKAGE=%s, ICON_OVERLAY=%s",
            self, width, height, coding, len(data), ICON_SHRINKAGE, ICON_OVERLAY)
        if coding == "default":
            img = self.overlay_image
        elif coding in ("BGRA", "RGBA"):
            rowstride = width * 4
            img = Image.frombytes("RGBA", (width, height), memoryview_to_bytes(data),
                                  "raw", coding, rowstride, 1)
        else:
            # weak dependency on `Encodings` subsystem:
            enc = self.get_subsystem("encoding")
            if not enc or coding not in enc.get_core_encodings():
                raise ValueError(f"window icon encoding {coding!r} is not supported")
            # pylint: disable=import-outside-toplevel
            from xpra.codecs.pillow.decoder import open_only
            img = open_only(data, ("png",))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        icon = img
        save_time = int(time())
        if SAVE_WINDOW_ICONS:
            filename = "client-window-%#x-icon-%i.png" % (wid, save_time)
            icon.save(filename, "png")
            log("client window icon saved to %s", filename)
        if self.overlay_image and self.overlay_image != img:
            try:
                LANCZOS = Image.Resampling.LANCZOS
            except AttributeError:
                LANCZOS = Image.LANCZOS
            if 0 < ICON_SHRINKAGE < 100:
                # paste the application icon in the top-left corner,
                # shrunk by ICON_SHRINKAGE pct
                shrunk_width = max(1, width * ICON_SHRINKAGE // 100)
                shrunk_height = max(1, height * ICON_SHRINKAGE // 100)
                icon_resized = icon.resize((shrunk_width, shrunk_height), LANCZOS)
                icon = Image.new("RGBA", (width, height))
                icon.paste(icon_resized, (0, 0, shrunk_width, shrunk_height))
                if SAVE_WINDOW_ICONS:
                    filename = "client-window-%i-icon-shrunk-%i.png" % (wid, save_time)
                    icon.save(filename, "png")
                    log("client shrunk window icon saved to %s", filename)
            assert 0 < ICON_OVERLAY <= 100
            overlay_width = max(1, width * ICON_OVERLAY // 100)
            overlay_height = max(1, height * ICON_OVERLAY // 100)
            xpra_resized = self.overlay_image.resize((overlay_width, overlay_height), LANCZOS)
            xpra_corner = Image.new("RGBA", (width, height))
            xpra_corner.paste(xpra_resized, (width - overlay_width, height - overlay_height, width, height))
            if SAVE_WINDOW_ICONS:
                filename = "client-window-%#x-icon-xpracorner-%i.png" % (wid, save_time)
                xpra_corner.save(filename, "png")
                log("client xpracorner window icon saved to %s", filename)
            composite = Image.alpha_composite(icon, xpra_corner)
            icon = composite
            if SAVE_WINDOW_ICONS:
                filename = "client-window-%#x-icon-composited-%i.png" % (wid, save_time)
                icon.save(filename, "png")
                log("client composited window icon saved to %s", filename)
        return icon

    # this handler only queues the work, but it must stay on the UI thread
    # (`main_thread=True`): that hop is what orders it after the `new-window`
    # that creates the window it refers to - do not "optimize" it away.
    def _process_window_icon(self, packet: Packet) -> None:
        wid = packet.get_wid()
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        coding = packet.get_str(4)
        data = packet.get_bytes(5)
        self.add_decode_work(self._decode_window_icon, wid, w, h, coding, data)

    def _decode_window_icon(self, wid: int, w: int, h: int, coding: str, data) -> None:
        """ this runs from the decode thread (see `xpra/client/subsystem/decode.py`) """
        img = self.window_icon_image(wid, w, h, coding, data)
        log("_decode_window_icon(%s, %s, %s, %s, %s bytes) image=%s", wid, w, h, coding, len(data), img)
        if img:
            self.idle_add(self._set_window_icon, wid, img)

    def _set_window_icon(self, wid: int, img) -> None:
        # the window may have been destroyed whilst we were decoding its icon:
        window = self.get_window(wid)
        log("_set_window_icon(%s, %s) window=%s", wid, img, window)
        if window:
            window.update_icon(img)
            set_tray_icon = getattr(self, "set_tray_icon", noop)
            set_tray_icon()

    def init_authenticated_packet_handlers(self) -> None:
        # `main_thread=True` is required for ordering, not for the (trivial) handler:
        # see `_process_window_icon` above
        self.add_packets("window-icon", main_thread=True)
