# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import threading
from io import BytesIO
from time import monotonic
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

from xpra.os_util import gi_import
from xpra.util.io import load_binary_file
from xpra.net import compression
from xpra.util.str_fn import csv, memoryview_to_bytes
from xpra.util.env import envint, envbool
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("icon")

ARGB_ICONS = envbool("XPRA_ARGB_ICONS", True)
PNG_ICONS = envbool("XPRA_PNG_ICONS", True)
DEFAULT_ICONS = envbool("XPRA_DEFAULT_ICONS", True)

LOG_THEME_DEFAULT_ICONS = envbool("XPRA_LOG_THEME_DEFAULT_ICONS", False)
SAVE_WINDOW_ICONS = envbool("XPRA_SAVE_WINDOW_ICONS", False)
MAX_ARGB_PIXELS = envint("XPRA_MAX_ARGB_PIXELS", 1024)


class WindowIconSource:
    """
    Mixin for handling the sending of window icon pixels.
    """

    fallback_window_icon: bool | tuple[int, int, str, bytes] = False

    def __init__(self, window_icon_encodings, icons_encoding_options):
        self.window_icon_encodings = window_icon_encodings
        self.icons_encoding_options = icons_encoding_options  # icon caps

        self.has_png = PNG_ICONS and ("png" in self.window_icon_encodings)
        self.has_default = DEFAULT_ICONS and ("default" in self.window_icon_encodings)
        log("WindowIconSource(%s, %s) has_png=%s",
            window_icon_encodings, icons_encoding_options, self.has_png)

        self.window_icon_data = None
        self.send_window_icon_timer = 0
        self.theme_default_icons = icons_encoding_options.strtupleget("default.icons")
        self.window_icon_greedy = icons_encoding_options.boolget("greedy", False)
        self.window_icon_size = icons_encoding_options.intpair("size", (64, 64))
        self.window_icon_max_size = icons_encoding_options.intpair("max_size", self.window_icon_size)
        self.window_icon_max_size = (
            max(self.window_icon_max_size[0], 16),
            max(self.window_icon_max_size[1], 16),
        )
        self.window_icon_size = (
            min(self.window_icon_size[0], self.window_icon_max_size[0]),
            min(self.window_icon_size[1], self.window_icon_max_size[1]),
        )
        self.window_icon_size = (
            max(self.window_icon_size[0], 16),
            max(self.window_icon_size[1], 16),
        )
        log("client icon settings: size=%s, max_size=%s", self.window_icon_size, self.window_icon_max_size)
        if LOG_THEME_DEFAULT_ICONS:
            log("theme_default_icons=%s", self.theme_default_icons)

    def cleanup(self):
        self.cancel_window_icon_timer()

    def cancel_window_icon_timer(self):
        swit = self.send_window_icon_timer
        if swit:
            self.send_window_icon_timer = 0
            GLib.source_remove(swit)

    def get_info(self) -> dict[str, Any]:
        idata = self.window_icon_data
        if not idata:
            return {}
        w, h, fmt, data = idata
        return {
            "icon": {
                "width": w,
                "height": h,
                "format": fmt,
                "bytes": len(data),
            }
        }

    @staticmethod
    def get_fallback_window_icon():
        if WindowIconSource.fallback_window_icon is False and Image:
            try:
                from xpra.platform.paths import get_icon_filename  # pylint: disable=import-outside-toplevel
                icon_filename = get_icon_filename("xpra.png")
                log(f"get_fallback_window_icon() icon filename={icon_filename}")
                img = Image.open(icon_filename)
                icon_data = load_binary_file(icon_filename)
                icon = (img.size[0], img.size[1], "png", icon_data)
                WindowIconSource.fallback_window_icon = icon
                return icon
            except Exception as e:
                log.warn(f"Warning: failed to get fallback icon: {e}")
                WindowIconSource.fallback_window_icon = False
        return WindowIconSource.fallback_window_icon

    def get_default_window_icon(self, size=48):
        # return the icon which would be used from the wmclass
        wmclass_name = self.get_window_wm_class_name()
        if not wmclass_name:
            return None
        Gtk = gi_import("Gtk")
        it = Gtk.IconTheme.get_default()  # pylint: disable=no-member
        log("get_default_window_icon(%i) icon theme=%s, wmclass_name=%s", size, it, wmclass_name)
        for icon_name in (
                f"{wmclass_name}-color",
                wmclass_name,
                f"{wmclass_name}_{size}x{size}",
                f"application-x-{wmclass_name}",
                f"{wmclass_name}-symbolic",
                f"{wmclass_name}.symbolic",
        ):
            i = it.lookup_icon(icon_name, size, 0)
            log("lookup_icon(%s)=%s", icon_name, i)
            if not i:
                continue
            try:
                pixbuf = i.load_icon()
                log("load_icon()=%s", pixbuf)
                if pixbuf:
                    w, h = pixbuf.props.width, pixbuf.props.height
                    log("using '%s' pixbuf %ix%i", icon_name, w, h)
                    return w, h, "RGBA", pixbuf.get_pixels()
            except Exception:
                log("%s.load_icon()", i, exc_info=True)
        return None

    def get_window_wm_class_name(self):
        try:
            c_i = self.window.get_property("class-instance")
        except Exception:
            return None
        if not c_i or len(c_i) != 2:
            return None
        return c_i[0]

    def client_has_theme_icon(self):
        wm_class = self.get_window_wm_class_name()
        return wm_class and wm_class in self.theme_default_icons

    def send_window_icon(self):
        # some of this code could be moved to the work queue half, meh
        assert self.ui_thread == threading.current_thread()
        if self.suspended:
            return
        # this runs in the UI thread
        icons = self.window.get_property("icons")
        log("send_window_icon window %s found %i icons", self.window, len(icons or ()))
        if not icons:
            if self.client_has_theme_icon():
                log("%s in client theme icons already (not sending default icon)", self.theme_default_icons)
                return
            # try to load the icon for this class-instance from the theme:
            icons = []
            sizes = []
            for size in (self.window_icon_size, self.window_icon_max_size, (48, 64)):
                if size:
                    for dim in size:  # ie: 48
                        if dim not in sizes:
                            sizes.append(dim)
            for size in sizes:
                icon = self.window.get_default_window_icon(size)
                if icon:
                    icons.append(icon)
            if not icons:
                # try to find one using the wmclass:
                icon = self.get_default_window_icon()
                if icon:
                    log("send_window_icon window %s using default window icon", self.window)
                    icons.append(icon)
        max_w, max_h = self.window_icon_max_size
        icon = self.choose_icon(icons, max_w, max_h)
        if not icon:
            # try again, without size restrictions:
            # (we'll downscale it)
            icon = self.choose_icon(icons)
        if not icon:
            if not self.window_icon_greedy:
                return
            # "greedy": client does not set a default icon, so we must provide one every time
            # to make sure that the window icon does get set to something
            # (our icon is at least better than the window manager's default)
            if self.has_default:
                # client will set the default itself,
                # send a mostly empty packet:
                packet = ("window-icon", self.wid, 0, 0, "default", "")
                log("queuing window icon update: %s", packet)
                # this is cheap, so don't use the encode thread,
                # and make sure we don't send another one via the timer:
                self.cancel_window_icon_timer()
                self.queue_packet(packet, wait_for_more=True)
                return
            icon = WindowIconSource.get_fallback_window_icon()
            log("using fallback window icon")
        if not icon:
            log("no suitable icon")
            return
        self.window_icon_data = icon
        if not self.send_window_icon_timer:
            # call compress via the work queue
            # and delay sending it by a bit to allow basic icon batching:
            w, h = self.window_icon_data[:2]
            delay = min(1000, max(50, w * h * self.batch_config.delay_per_megapixel // 1000000))
            log("send_window_icon() window=%s, wid=%s, compression scheduled in %sms for batch delay=%i",
                self.window, self.wid, delay, self.batch_config.delay_per_megapixel)
            self.send_window_icon_timer = GLib.timeout_add(delay, self.call_in_encode_thread,
                                                           True, self.compress_and_send_window_icon)

    def compress_and_send_window_icon(self):
        # this runs in the work queue
        self.send_window_icon_timer = 0
        idata = self.window_icon_data
        if not idata or not self.has_png:
            return
        w, h, pixel_format, pixel_data = idata
        log("compress_and_send_window_icon() %ix%i in %s format, %i bytes for wid=%i",
            w, h, pixel_format, len(pixel_data), self.wid)
        if pixel_format not in ("BGRA", "RGBA", "png"):
            raise RuntimeError(f"invalid window icon format {pixel_format}")
        if pixel_format == "BGRA":
            # BGRA data is always unpremultiplied
            # (that's what we get from NetWMIcons)
            from xpra.codecs.argb.argb import premultiply_argb  # pylint: disable=import-outside-toplevel
            pixel_data = premultiply_argb(pixel_data)

        max_w, max_h = self.window_icon_max_size
        # use png if supported and if "premult_argb32" is not supported by the client (ie: html5)
        # or if we must downscale it (bigger than what the client is willing to deal with),
        # or if we want to save window icons
        must_scale = w > max_w or h > max_h
        log("compress_and_send_window_icon: %sx%s (max-size=%s, standard-size=%s), pixel_format=%s",
            w, h, self.window_icon_max_size, self.window_icon_size, pixel_format)
        must_convert = pixel_format != "png"
        log(" must convert=%s, must scale=%s", must_convert, must_scale)

        image = None
        if must_scale or must_convert or SAVE_WINDOW_ICONS:
            if Image is None:
                log("cannot scale or convert window icon without python-pillow")
                return
            # we're going to need a PIL Image:
            if pixel_format == "png":
                image = Image.open(BytesIO(pixel_data))
            else:
                image = Image.frombuffer("RGBA", (w, h), memoryview_to_bytes(pixel_data), "raw", pixel_format, 0, 1)
            if must_scale:
                # scale the icon down to the size the client wants
                # (we should scale + paste to preserve the aspect ratio, meh)
                icon_w, icon_h = self.window_icon_size
                if float(w) / icon_w >= float(h) / icon_h:
                    rh = min(max_h, h * icon_w // w)
                    rw = icon_w
                else:
                    rw = min(max_w, w * icon_h // h)
                    rh = icon_h
                log("scaling window icon down to %sx%s", rw, rh)
                try:
                    LANCZOS = Image.Resampling.LANCZOS
                except AttributeError:
                    LANCZOS = Image.LANCZOS
                image = image.resize((rw, rh), LANCZOS)
            if SAVE_WINDOW_ICONS:
                filename = f"server-window-{self.wid}-icon-{int(monotonic())}.png"
                image.save(filename, 'PNG')
                log("server window icon saved to %s", filename)

        if image:
            # image got converted or scaled, get the new pixel data:
            output = BytesIO()
            image.save(output, "png")
            pixel_data = output.getvalue()
            output.close()
            w, h = image.size
        wrapper = compression.Compressed("png", pixel_data)
        packet = ("window-icon", self.wid, w, h, wrapper.datatype, wrapper)
        log("queuing window icon update: %s", packet)
        self.queue_packet(packet, wait_for_more=True)

    @staticmethod
    def choose_icon(icons, max_w=1024, max_h=1024):
        if not icons:
            return None
        log("choose_icon from: %s", csv("%ix%i %s" % icon[:3] for icon in icons))
        size_image = {icon[0] * icon[1]: icon for icon in icons if icon[0] < max_w and icon[1] < max_h}
        if not size_image:
            return None
        # we should choose one whose size is close to what the client wants,
        # take the biggest one for now:
        largest_size = sorted(size_image)[-1]
        icon = size_image[largest_size]
        log("choose_icon(..)=%ix%i %s", *icon[:3])
        return icon
