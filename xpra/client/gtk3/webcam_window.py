# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam client window: receives and displays compressed webcam frames forwarded
by an xpra server when v4l2 is unavailable.  Connects back to the server as a
regular client with only the `webcam-client` capability set so that the server
creates a minimal `ClientConnection` for it.
"""

import uuid
from typing import Any

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import
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
        self.client_type = "webcam"
        # use a unique uuid so the sharing subsystem doesn't treat us
        # as a reconnection of the regular client (which would kick it off):
        self.uuid = uuid.uuid4().hex
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
        caps["webcam-client"] = {"device": self._device_no}
        if BACKWARDS_COMPATIBLE:
            # for older versions, we need to turn this subsystem off explicitly
            caps["bandwidth"] = False
        return caps

    def init_authenticated_packet_handlers(self) -> None:
        super().init_authenticated_packet_handlers()
        self.add_packets("webcam-frame", "webcam-stop", "startup-complete")

    def _process_startup_complete(self, _packet: Packet) -> None:
        log("startup-complete")

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
        if pixbuf := self._pixbuf:
            Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
            ctx.paint()
