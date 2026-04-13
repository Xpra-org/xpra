# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam client window: receives and displays compressed webcam frames forwarded
by an xpra server when v4l2 is unavailable.  Connects back to the server over
the unix socket and authenticates with a one-time token embedded in the URI.
"""

from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.exit_codes import ExitCode
from xpra.client.base.gobject import GObjectClientAdapter
from xpra.client.base.client import XpraClientBase
from xpra.log import Logger

log = Logger("webcam")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")
GLib = gi_import("GLib")


def get_pixbuf(encoding: str, data: bytes):
    try:
        assert encoding in ("jpeg", "png", "webp")
        mime = f"image/{encoding}"
        loader = GdkPixbuf.PixbufLoader.new_with_mime_type(mime)
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except Exception as e:
        log("get_pixbuf(%s, %i bytes) error: %s", encoding, len(data), e)
        return get_pillow_pixbuf(encoding, data)


def get_pillow_pixbuf(encoding: str, data: bytes):
    try:
        from xpra.codecs.pillow.decoder import open_only
        img = open_only(data, encoding)
        img = img.convert("RGBA")
        w, h = img.size
        raw = GLib.Bytes.new(img.tobytes())
        return GdkPixbuf.Pixbuf.new_from_bytes(raw, GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
    except Exception as e:
        log.error("Error loading %r webcam frame: %s", encoding, e)
        return None


class WebcamClient(GObjectClientAdapter, XpraClientBase):
    """
    Minimal xpra client that connects back to the server, authenticates with
    a one-time token, and displays incoming webcam frames in a GTK window.
    """

    def __init__(self, display_desc: dict[str, Any]) -> None:
        GObjectClientAdapter.__init__(self)
        XpraClientBase.__init__(self)
        self._device_no: int = int(display_desc.get("device", 0))
        self._pixbuf = None

        self._window = Gtk.Window(title=f"Webcam (device {self._device_no})")
        self._window.set_default_size(640, 480)
        self._window.connect("delete-event", self._on_close)
        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)
        self._window.add(self._area)
        self._window.show_all()

    def init(self, opts) -> None:
        XpraClientBase.init(self, opts)

    def make_protocol(self, conn):
        proto = super().make_protocol(conn)
        proto.large_packets.append("webcam-frame")
        return proto

    def make_hello(self) -> dict[str, Any]:
        caps = super().make_hello()
        caps["request"] = "webcam-client"
        caps["webcam-client"] = {"device": self._device_no}
        return caps

    def server_connection_established(self, caps: typedict) -> bool:
        # The server hello only contains {"webcam": True}; skip the full
        # capability parse chain used by regular clients.
        self.init_authenticated_packet_handlers()
        self.connection_established = True
        return True

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packet_handler("webcam-frame", self._process_webcam_frame)
        self.add_packet_handler("webcam-stop", self._process_webcam_stop)

    # ------------------------------------------------------------------
    # Packet handlers — dispatched on the GLib main loop by XpraClientBase

    def _process_webcam_frame(self, packet) -> None:
        try:
            encoding = str(packet[3])
            data = packet[6]
            if hasattr(data, "data"):
                data = data.data
            log("webcam frame: %s", encoding)
            self._update_frame(encoding, bytes(data))
        except Exception as e:
            log.error("Error processing webcam frame: %s", e)

    def _process_webcam_stop(self, _packet) -> None:
        log.info("webcam forwarding stopped by server")
        self.quit(ExitCode.OK)

    # ------------------------------------------------------------------
    # GTK window

    def _on_close(self, _window, _event) -> bool:
        self.quit(ExitCode.OK)
        return False

    def _update_frame(self, encoding: str, data: bytes) -> None:
        self._pixbuf = get_pixbuf(encoding, data)
        if self._pixbuf:
            w, h = self._pixbuf.get_width(), self._pixbuf.get_height()
            self._window.resize(w, h)
            self._area.queue_draw()

    def _on_draw(self, _widget, ctx) -> None:
        pixbuf = self._pixbuf
        if pixbuf:
            Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
            ctx.paint()
