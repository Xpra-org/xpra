# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf

from xpra.gtk_common.gtk_util import add_close_accel
from xpra.util import first_time
from xpra.log import Logger

log = Logger("menu")


_qrencode_fn = None
def get_qrencode_fn():
    global _qrencode_fn
    if _qrencode_fn is None:
        _qrencode_fn = _get_qrencode_fn() or False
        log("get_qrencode_fn()=%s", _qrencode_fn)
    return _qrencode_fn

def _get_qrencode_fn():
    try:
        from PIL import Image
        from qrencode import encode
        def qrencode_fn(s):
            return encode(s)[2]
        return qrencode_fn
    except ImportError:
        try:
            from PIL import Image
            from ctypes import (
                Structure, POINTER,
                cdll, create_string_buffer, c_int, c_char_p,
                )
            from ctypes.util import find_library
            class QRCode(Structure):
                _fields_ = (
                    ("version", c_int),
                    ("width", c_int),
                    ("data", c_char_p),
                    )
            PQRCode = POINTER(QRCode)
            lib_file = None
            for lib_name in ("libqrencode", "qrencode"):
                lib_file = find_library(lib_name)
                if lib_file:
                    break
            if not lib_file:
                if first_time("libqrencode"):
                    log.warn("Warning: libqrencode not found")
                return None
            libqrencode = cdll.LoadLibrary(lib_file)
            encodeString8bit = libqrencode.QRcode_encodeString8bit
            encodeString8bit.argtypes = (c_char_p, c_int, c_int)
            encodeString8bit.restype = PQRCode
            QRcode_free = libqrencode.QRcode_free
            QRcode_free.argtypes = (PQRCode,)
            def qrencode_ctypes_fn(s):
                data = create_string_buffer(s.encode("latin1"))
                qrcode = encodeString8bit(data, 0, 0).contents
                try:
                    size = qrcode.width
                    pixels = bytearray(size*size)
                    pdata = qrcode.data
                    for i in range(size*size):
                        pixels[i] = 0 if (pdata[i] & 0x1) else 255
                    return Image.frombytes('L', (size, size), bytes(pixels))
                finally:
                    QRcode_free(qrcode)
            return qrencode_ctypes_fn
        except Exception:
            log.error("failed to load qrencode via ctypes", exc_info=True)
    return None


def qrencode(s):
    fn = get_qrencode_fn()
    if fn:
        return fn(s)
    return None

def show_qr(uri, width=640, height=640):
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
        window.destroy()
    add_close_accel(window, close)
    window.show_all()

def qr_pixbuf(uri, width=640, height=640):
    img = qrencode(uri)
    if not img:
        return  None
    from PIL import Image
    img = img.convert("RGB")
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
    fn = get_qrencode_fn()
    log.info("qrencode_fn=%s" % (fn,))


if __name__ == "__main__":
    import sys
    main()
    sys.exit(0)
