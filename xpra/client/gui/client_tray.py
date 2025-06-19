# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import time
from typing import Any
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.common import PaintCallbacks
from xpra.client.gui.widget_base import ClientWidgetBase
from xpra.client.gui.window_backing_base import WindowBackingBase, fire_paint_callbacks
from xpra.util.objects import typedict
from xpra.util.str_fn import memoryview_to_bytes
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("tray")

GLib = gi_import("GLib")

SAVE = envbool("XPRA_SAVE_SYSTRAY", False)


class ClientTray(ClientWidgetBase):
    """
        This acts like a widget, we use the `TrayBacking`
        to capture the tray pixels and forward them
        to the real tray widget class.
    """
    DEFAULT_LOCATION = [0, 0]
    DEFAULT_SIZE = [64, 64]
    DEFAULT_GEOMETRY = DEFAULT_LOCATION + DEFAULT_SIZE

    def __init__(self, client, wid, w, h, metadata, tray_widget, mmap_area):
        log("ClientTray%s", (client, wid, w, h, tray_widget, mmap_area))
        super().__init__(client, 0, wid, True)
        self._size = w, h
        self._metadata = metadata
        self.title = metadata.strget("title")
        self.tray_widget = tray_widget
        self._geometry = None
        self._window_alpha = True
        self.group_leader = None

        self.mmap = mmap_area
        self.new_backing(w, h)
        GLib.idle_add(self.reconfigure)
        # things may have settled by now
        GLib.timeout_add(1000, self.send_configure)

    def reset_size_constraints(self) -> None:
        """ we can't implement this method for trays - it should not be called """

    def resize(self, nw, nh) -> None:
        """ we can't implement this method for trays - it should not be called """

    def set_alpha(self) -> None:
        """
        nothing to do,
        trays aren't really windows and transparency is always supported
        """

    def get_backing_class(self) -> type:
        return TrayBacking

    def is_OR(self) -> bool:
        return True

    def is_tray(self) -> bool:
        return True

    def get_window(self):
        return None

    def get_geometry(self):
        return self._geometry or ClientTray.DEFAULT_GEOMETRY

    def get_tray_geometry(self):
        tw = self.tray_widget
        if not tw:
            return None
        return tw.get_geometry()

    def get_tray_size(self):
        tw = self.tray_widget
        if not tw:
            return None
        return tw.get_size()

    def freeze(self) -> None:
        """
        System trays are small, no point in freezing anything
        """

    def send_configure(self) -> None:
        self.reconfigure(True)

    def reconfigure(self, force_send_configure=False) -> None:
        geometry = None
        tw = self.tray_widget
        if tw:
            geometry = tw.get_geometry()
        log("%s.reconfigure(%s) geometry=%s", self, force_send_configure, geometry)
        if geometry is None:
            if self._geometry or not tw:
                geometry = self.get_geometry()
            else:
                # make one up as best we can - maybe we have the size at least?
                size = tw.get_size()
                log("%s.reconfigure() guessing location using size=%s", self, size)
                geometry = ClientTray.DEFAULT_LOCATION + list(size or ClientTray.DEFAULT_SIZE)
        x, y, w, h = geometry
        if w <= 1 or h <= 1:
            w, h = ClientTray.DEFAULT_SIZE
            geometry = x, y, w, h
        if force_send_configure or self._geometry is None or geometry != self._geometry:
            self._geometry = geometry
            client_properties = {
                "encoding.transparency": True,
                "encodings.rgb_formats": ["RGBA", "RGB", "RGBX"],
            }
            if tw:
                orientation = tw.get_orientation()
                if orientation:
                    client_properties["orientation"] = orientation
            # scale to server coordinates
            sx, sy, sw, sh = self._client.crect(x, y, w, h)
            log("%s.reconfigure(%s) sending configure for geometry=%s : %s",
                self, force_send_configure, geometry, (sx, sy, sw, sh, client_properties))
            self._client.send("configure-window", self.wid, sx, sy, sw, sh, client_properties)
        if self._size != (w, h):
            self.new_backing(w, h)

    def move_resize(self, x: int, y: int, w: int, h: int) -> None:
        log("%s.move_resize(%s, %s, %s, %s)", self, x, y, w, h)
        w = max(1, w)
        h = max(1, h)
        self._geometry = x, y, w, h
        self.reconfigure(True)

    def new_backing(self, w: int, h: int) -> None:
        self._size = w, h
        data = None
        if self._backing:
            data = self._backing.data
        self._backing = TrayBacking(self.wid, w, h, self._has_alpha, data)
        if self.mmap:
            self._backing.enable_mmap(self.mmap)

    def update_metadata(self, metadata) -> None:
        log("%s.update_metadata(%s)", self, metadata)

    def update_icon(self, img) -> None:
        """
        this is the window icon... not the tray icon!
        ignore it as it is never shown anywhere
        """

    def draw_region(self, x: int, y: int, width: int, height: int,
                    coding: str, img_data, rowstride: int, options: typedict,
                    callbacks: PaintCallbacks):
        log("%s.draw_region%s", self,
            (x, y, width, height, coding, "%s bytes" % len(img_data), rowstride, options, callbacks))

        # note: a new backing may be assigned between the time we call draw_region
        # and the time we get the callback (as the draw may use idle_add)
        backing = self._backing

        def after_draw_update_tray(success: bool | int, message: str = "") -> None:
            log("%s.after_draw_update_tray(%s, %s)", self, success, message)
            if not success:
                log.warn(f"Warning: tray paint update failed: {message!r}")
                log.warn(f" for {width}x{height} {coding} update with {options=}")
                return
            tray_data = backing.data
            log("tray backing=%s, data: %s", backing, tray_data is not None)
            if tray_data is None:
                log.warn("Warning: no pixel data in tray backing for window %i", backing.wid)
                return
            GLib.idle_add(self.set_tray_icon, *tray_data)
            GLib.idle_add(self.reconfigure)

        callbacks.append(after_draw_update_tray)
        backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def set_tray_icon(self, rgb_format: str, w: int, h: int, rowstride: int, pixels, options: typedict) -> None:
        log("%s.set_tray_icon(%s, %s, %s, %s, %s bytes)", self, rgb_format, w, h, rowstride, len(pixels))
        has_alpha = rgb_format.find("A") >= 0
        tw = self.tray_widget
        if tw:
            # some tray implementations can't deal with memoryviews..
            if isinstance(pixels, (memoryview, bytearray)):
                pixels = memoryview_to_bytes(pixels)
            tw.set_icon_from_data(pixels, has_alpha, w, h, rowstride, options)

    def destroy(self) -> None:
        tw = self.tray_widget
        if tw:
            self.tray_widget = None
            tw.cleanup()

    def __repr__(self):
        return f"ClientTray({self.wid}:{self.title})"


class TrayBacking(WindowBackingBase):
    """
        This backing only stores the rgb pixels,
        so that we can use them with the real widget.
    """

    # keep it simple: only accept 32-bit RGB(X),
    # all tray implementations support alpha
    RGB_MODES: Sequence[str] = ("RGBA", "RGBX")
    HAS_ALPHA = True

    def __init__(self, wid: int, _w: int, _h: int, _has_alpha: bool, data=None):
        self.data = data
        super().__init__(wid, True)
        self._backing = object()  # pretend we have a backing structure

    def get_encoding_properties(self) -> dict[str, Any]:
        # override so we skip all csc caps:
        return {
            "encodings.rgb_formats": self.get_rgb_formats(),
            "encoding.transparency": True,
        }

    def paint_scroll(self, img_data, options, callbacks) -> None:
        raise RuntimeError("scroll should not be used with tray icons")

    def do_paint_rgb(self, context, encoding: str, rgb_format: str, img_data,
                     x: int, y: int, width: int, height: int, render_width: int, render_height: int, rowstride: int,
                     options: typedict, callbacks: PaintCallbacks) -> None:
        if width != render_width or height != render_height:
            fire_paint_callbacks(callbacks, False, "tray paint must not use scaling")
            return
        self.data = (rgb_format, width, height, rowstride, img_data[:], options)
        if SAVE:
            self.save_tray_png()
        fire_paint_callbacks(callbacks, True)

    def save_tray_png(self) -> None:
        log("save_tray_png()")
        rgb_mode, width, height, stride, img_data = self.data[:5]
        mode = "RGB"
        data_mode = "RGB"
        if rgb_mode == "rgb32":
            mode += "A"
            data_mode += "A"
        if not stride:
            stride = width * len(data_mode)
        try:
            from PIL import Image  # pylint: disable=import-outside-toplevel
        except ImportError as e:
            log(f"cannot save tray: {e}")
            return
        img = Image.frombytes(mode, (width, height), img_data, "raw", data_mode, stride, 1)
        filename = f"./tray-{rgb_mode}-{time()}.png"
        img.save(filename, "PNG")
        log.info("tray %s update saved to %s", rgb_mode, filename)
