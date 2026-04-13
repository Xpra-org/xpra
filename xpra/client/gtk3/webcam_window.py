# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Minimal GTK3 window for receiving and displaying webcam frames forwarded by xpra.
Used by the `xpra webcam-client` subcommand.
"""

import sys
from typing import Any

from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("webcam")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")
GdkPixbuf = gi_import("GdkPixbuf")


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
        # fallback via Pillow
        return get_pillow_pixbuf(data)


def get_pillow_pixbuf(encoding, data: bytes):
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


class WebcamClientWindow:
    """
    Connects to a running xpra server as a webcam-client, receives compressed
    webcam frames (webp/jpeg/png) and displays them in a GTK window.
    """

    def __init__(self, socket_path: str, device_no: int, token: str) -> None:
        self._socket_path = socket_path
        self._device_no = device_no
        self._token = token
        self._protocol = None
        self._pixbuf: Any = None

        self._window = Gtk.Window(title=f"Webcam (device {device_no})")
        self._window.set_default_size(640, 480)
        self._window.connect("delete-event", self._on_close)

        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)
        self._window.add(self._area)
        self._window.show_all()

    # ------------------------------------------------------------------
    # Connection

    def connect(self) -> None:
        import socket as _socket
        from xpra.net.bytestreams import SocketConnection
        from xpra.net.packet_encoding import init_all as init_encoders
        from xpra.net.compression import init_all as init_compressors
        from xpra.net.protocol.factory import get_client_protocol_class

        init_encoders()
        init_compressors()

        sock = _socket.socket(_socket.AF_UNIX)
        sock.settimeout(10)
        try:
            sock.connect(self._socket_path)
        except OSError as e:
            log.error("Error: cannot connect to %s: %s", self._socket_path, e)
            self.quit()
            return
        sock.settimeout(None)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(),
                                self._socket_path, "socket")
        proto_class = get_client_protocol_class("socket")
        self._protocol = proto_class(conn, self._process_packet)
        self._protocol.enable_default_encoder()
        self._protocol.enable_default_compressor()
        self._protocol.start()
        self._protocol.large_packets.append("webcam-frame")
        self._send_hello()

    def _send_hello(self) -> None:
        from xpra.net.common import Packet
        from xpra.util.version import XPRA_VERSION, vparts
        hello: dict[str, Any] = {
            "version": vparts(XPRA_VERSION, 3),
            "request": "webcam-client",
            "webcam-client": {
                "device": self._device_no,
                "token": self._token,
            },
            "wants": [],
            "rencodeplus": True,
        }
        log("sending hello: %s", hello)
        self._protocol.send_now(Packet("hello", hello))

    def quit(self) -> None:
        log("quit")
        if self._protocol:
            self._protocol.close()
            self._protocol = None
        Gtk.main_quit()

    def _on_close(self, _window, _event) -> bool:
        self.quit()
        return False

    # ------------------------------------------------------------------
    # Packet handling

    def _process_packet(self, _proto, packet) -> None:
        packet_type = packet[0]
        handler = getattr(self, f"_process_{packet_type.replace('-', '_')}", None)
        log("packet-handler(%s)=%s", packet_type, handler)
        if handler:
            GLib.idle_add(handler, packet)
        else:
            log("unhandled packet type: %r", packet_type)

    def _process_hello(self, packet) -> None:
        log("webcam-client connected: %s", packet)

    def _process_webcam_frame(self, packet) -> None:
        try:
            encoding = packet[3]
            data = packet[6]
            if hasattr(data, "data"):
                data = data.data
            log("webcam frame: %s", encoding)
            self._update_frame(encoding, bytes(data))
        except Exception as e:
            log.error("Error processing webcam frame: %s", e)

    def _process_webcam_stop(self, _packet) -> None:
        log.info("webcam forwarding stopped by server")
        self.quit()

    def _process_disconnect(self, packet) -> None:
        reason = packet[1] if len(packet) > 1 else "unknown"
        log.info("disconnected: %s", reason)
        self.quit()

    def _process_connection_lost(self, packet) -> None:
        log("connection-lost: %s", packet[1:])
        self.quit()

    # ------------------------------------------------------------------
    # Display

    def _update_frame(self, encoding: str, data: bytes) -> None:
        self._pixbuf = get_pixbuf(encoding, data)
        log("update_frame(%s, %i bytes) pixbuf=%s", encoding, len(data), self._pixbuf)
        if self._pixbuf:
            w, h = self._pixbuf.get_width(), self._pixbuf.get_height()
            self._window.resize(w, h)
            self._area.queue_draw()

    def _on_draw(self, _widget, ctx) -> None:
        pixbuf = self._pixbuf
        log("drawing %s", pixbuf)
        if pixbuf:
            Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
            ctx.paint()


def main(params: dict[str, Any]) -> int:
    socket_path = params.get("socket_path", "")
    if not socket_path:
        sys.stderr.write(f"Error: no socket path in connection params: {params}\n")
        return 1
    device_no = int(params.get("device", 0))
    token = params.get("token", "")
    if not token:
        sys.stderr.write(f"Error: no token in connection params: {params}\n")
        return 1

    win = WebcamClientWindow(socket_path, device_no, token)
    GLib.idle_add(win.connect)
    Gtk.main()
    return 0
