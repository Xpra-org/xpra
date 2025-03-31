# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.net.qrcode import qrencode
from xpra.gtk.window import add_close_accel
from xpra.log import Logger, consume_verbose_argv

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")
GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("menu")


def show_qr(uri: str, width: int = 640, height: int = 640):
    assert uri.find(":") > 0, "invalid uri"
    # support old-style URIs, ie: tcp:host:port
    if uri.find(":") != uri.find("://"):
        uri = uri.replace(":", "://", 1)
    parts = uri.split(":", 1)
    if parts[0] in ("tcp", "ws"):
        uri = "http:" + parts[1]
    else:
        uri = "https:" + parts[1]
    pixbuf = qr_pixbuf(uri, width, height)
    if not pixbuf:
        return
    image = Gtk.Image().new_from_pixbuf(pixbuf)
    window = Gtk.Window(modal=True, title="QR Code")
    window.set_position(Gtk.WindowPosition.CENTER)
    window.add(image)
    window.set_size_request(width, height)
    window.set_resizable(False)

    def close(*_args):
        window.close()

    add_close_accel(window, close)
    window.show_all()
    if Gtk.main_level() <= 0:
        def gtk_quit(*_args):
            close()
            Gtk.main_quit()

        window.connect("delete-event", gtk_quit)
        Gtk.main()


def qr_pixbuf(uri: str, width: int = 640, height: int = 640):
    img = qrencode.encode_image(uri)
    if not img:
        return None
    from PIL import Image
    try:
        NEAREST = Image.Resampling.NEAREST
    except AttributeError:
        NEAREST = Image.NEAREST
    img = img.convert("RGB")
    img = img.resize((width, height), NEAREST)
    data = img.tobytes()
    w, h = img.size
    data = GLib.Bytes.new(data)
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                                             False, 8, w, h, w * 3)
    return pixbuf


def main(args: list[str]) -> int:
    consume_verbose_argv(args, "menu")
    uri = sys.argv[1]
    show_qr(uri)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
