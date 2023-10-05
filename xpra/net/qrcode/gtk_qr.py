# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("GdkPixbuf", "2.0")  # @UndefinedVariable
from gi.repository import Gtk, GLib, GdkPixbuf  # @UnresolvedImport

from xpra.net.qrcode import qrencode
from xpra.gtk_common.gtk_util import add_close_accel
from xpra.log import Logger

log = Logger("menu")


def show_qr(uri:str, width:int=640, height:int=640):
    assert uri.find(":")>0, "invalid uri"
    #support old-style URIs, ie: tcp:host:port
    if uri.find(":")!=uri.find("://"):
        uri = uri.replace(":", "://", 1)
    parts = uri.split(":", 1)
    if parts[0] in ("tcp", "ws"):
        uri = "http:"+parts[1]
    else:
        uri = "https:"+parts[1]
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
    if Gtk.main_level()<=0:
        def gtk_quit(*_args):
            close()
            Gtk.main_quit()
        window.connect("delete-event", gtk_quit)
        Gtk.main()

def qr_pixbuf(uri:str, width:int=640, height:int=640):
    img = qrencode(uri)
    if not img:
        return  None
    from PIL import Image
    img = img.convert("RGB")
    try:
        from PIL.Image.Resampling import NEAREST
    except ImportError:
        from PIL.Image import NEAREST
    img = img.resize((width, height), Image.NEAREST)
    data = img.tobytes()
    w, h = img.size
    data = GLib.Bytes.new(data)
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                                             False, 8, w, h, w * 3)
    return pixbuf


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    uri = sys.argv[1]
    show_qr(uri)


if __name__ == "__main__":
    import sys
    main()
    sys.exit(0)
