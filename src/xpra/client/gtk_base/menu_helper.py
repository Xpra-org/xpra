# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gtk, GLib, GdkPixbuf

from xpra.util import envbool
from xpra.os_util import OSX, WIN32
from xpra.gtk_common.gtk_util import menuitem
from xpra.gtk_common.about import about, close_about
from xpra.platform.gui import get_icon_size
from xpra.log import Logger

log = Logger("menu")

MENU_ICONS = envbool("XPRA_MENU_ICONS", True)


def ll(m):
    try:
        return "%s:%s" % (type(m), m.get_label())
    except AttributeError:
        return str(m)

def set_sensitive(widget, sensitive):
    if OSX:
        if sensitive:
            widget.show()
        else:
            widget.hide()
    widget.set_sensitive(sensitive)


#utility method to ensure there is always only one CheckMenuItem
#selected in a submenu:
def ensure_item_selected(submenu, item, recurse=True):
    if not isinstance(item, Gtk.CheckMenuItem):
        return None
    if item.get_active():
        #deactivate all except this one
        def deactivate(items, skip=None):
            for x in items:
                if x==skip:
                    continue
                if isinstance(x, Gtk.MenuItem):
                    submenu = x.get_submenu()
                    if submenu and recurse:
                        deactivate(submenu.get_children(), skip)
                if isinstance(x, Gtk.CheckMenuItem):
                    if x!=item and x.get_active():
                        x.set_active(False)
        deactivate(submenu.get_children(), item)
        return item
    #ensure there is at least one other active item
    def get_active_item(items):
        for x in items:
            if isinstance(x, Gtk.MenuItem):
                submenu = x.get_submenu()
                if submenu:
                    a = get_active_item(submenu.get_children())
                    if a:
                        return a
            if isinstance(x, Gtk.CheckMenuItem):
                if x.get_active():
                    return x
        return None
    active = get_active_item(submenu.get_children())
    if active:
        return active
    #if not then keep this one active:
    item.set_active(True)
    return item


class MenuHelper:

    def __init__(self, client):
        self.client = client
        self.menu = None
        self.menu_shown = False
        self.menu_icon_size = get_icon_size()

    def build(self):
        if self.menu is None:
            try:
                self.menu = self.setup_menu()
            except Exception as e:
                log("build()", exc_info=True)
                log.error("Error: failed to setup menu")
                log.error(" %s", e)
        return self.menu

    def show_session_info(self, *args):
        self.client.show_session_info(*args)

    def show_bug_report(self, *args):
        self.client.show_bug_report(*args)


    def get_image(self, icon_name, size=None):
        return self.client.get_image(icon_name, size)

    def setup_menu(self):
        raise NotImplementedError()

    def cleanup(self):
        self.close_menu()
        close_about()

    def close_menu(self, *_args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *_args):
        self.menu_shown = False

    def activate(self, button=1, time=0):
        log("activate(%s, %s)", button, time)
        self.show_menu(button, time)

    def popup(self, button, time):
        log("popup(%s, %s)", button, time)
        self.show_menu(button, time)

    def show_menu(self, button, time):
        self.close_menu()
        self.menu.popup(None, None, None, None, button, time)
        self.menu_shown = True


    def handshake_menuitem(self, *args, **kwargs):
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        set_sensitive(mi, False)
        def enable_menuitem(*_args):
            set_sensitive(mi, True)
        self.client.after_handshake(enable_menuitem)
        return mi


    def make_menu(self):
        return Gtk.Menu()

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None, **kwargs):
        """ Utility method for easily creating an ImageMenuItem """
        image = None
        if MENU_ICONS:
            image = kwargs.get("image")
            if icon_name and not image:
                icon_size = self.menu_icon_size or get_icon_size()
                image = self.get_image(icon_name, icon_size)
        return menuitem(title, image, tooltip, cb)

    def checkitem(self, title, cb=None, active=False):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = Gtk.CheckMenuItem(label=title)
        check_item.set_active(active)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item


    def make_aboutmenuitem(self):
        return self.menuitem("About Xpra", "xpra.png", None, about)

    def make_updatecheckmenuitem(self):
        def show_update_window(*_args):
            from xpra.client.gtk_base.update_status import getUpdateStatusWindow
            w = getUpdateStatusWindow()
            w.show()
            w.check()
        return self.menuitem("Check for updates", "update.png", None, show_update_window)


    def make_qrmenuitem(self):
        qrencode_fn = None
        try:
            from PIL import Image
            from qrencode import encode
            def _qrencode_fn(s):
                return encode(s)[2]
            qrencode_fn = _qrencode_fn
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
                lib_file = find_library("libqrencode")
                if lib_file:
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
                    qrencode_fn = qrencode_ctypes_fn
            except Exception:
                log.error("failed to load qrencode via ctypes", exc_info=True)

        def show_qr(*_args):
            uri = self.client.display_desc.get("display_name")
            #support old-style URIs, ie: tcp:host:port
            if uri.find(":")!=uri.find("://"):
                uri = uri.replace(":", "://", 1)
            parts = uri.split(":", 1)
            if parts[0] in ("tcp", "ws"):
                uri = "http:"+parts[1]
            else:
                uri = "https:"+parts[1]
            img = qrencode_fn(uri)
            W = H = 640
            img = img.convert("RGB")
            img = img.resize((W, H), Image.NEAREST)
            data = img.tobytes()
            w, h = img.size
            data = GLib.Bytes.new(data)
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                                                     False, 8, w, h, w * 3)
            image = Gtk.Image().new_from_pixbuf(pixbuf)
            window = Gtk.Window(modal=True, title="QR Code")
            window.set_position(Gtk.WindowPosition.CENTER)
            window.add(image)
            window.set_size_request(W, H)
            window.set_resizable(False)
            window.show_all()
        self.qr_menuitem = self.menuitem("Show QR connection string", "qr.png", None, show_qr)
        log("make_qrmenuitem() qrencode_fn=%s", qrencode_fn)
        if qrencode_fn:
            def with_connection(*_args):
                uri = self.client.display_desc.get("display_name")
                if not uri or not any(uri.startswith(proto) for proto in ("tcp:", "ws:", "wss:")):
                    set_sensitive(self.qr_menuitem, False)
                    self.qr_menuitem.set_tooltip_text("server uri is not shareable")
            self.client.after_handshake(with_connection)
        else:
            set_sensitive(self.qr_menuitem, False)
            self.qr_menuitem.set_tooltip_text("qrencode library is missing")
        return self.qr_menuitem

    def make_sessioninfomenuitem(self):
        def show_session_info_cb(*_args):
            #we define a generic callback to remove the arguments
            #(which contain the menu widget and are of no interest to the 'show_session_info' function)
            self.show_session_info()
        sessioninfomenuitem = self.handshake_menuitem("Session Info", "statistics.png", None, show_session_info_cb)
        return sessioninfomenuitem

    def make_bugreportmenuitem(self):
        def show_bug_report_cb(*_args):
            self.show_bug_report()
        return  self.menuitem("Bug Report", "bugs.png", None, show_bug_report_cb)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)
