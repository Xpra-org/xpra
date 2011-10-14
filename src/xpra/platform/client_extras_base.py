# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import sys
import os.path
import pygtk
pygtk.require("2.0")
import gtk
import webbrowser

from wimpiggy.util import gtk_main_quit_really
from wimpiggy.log import Logger
log = Logger()


class ClientExtrasBase(object):

    def __init__(self, send_packet_cb, pulseaudio, opts):
        self.send = send_packet_cb
        self.license_text = None

    def quit(self, *args):
        gtk_main_quit_really()

    def exit(self):
        pass

    def handshake_complete(self):
        pass

    def can_notify(self):
        return  False

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        pass
    
    def close_notify(self, id):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        import gtk.gdk
        gtk.gdk.beep()

    def get_keymap_spec(self):
        return None,None,None


    def about(self, *args):
        dialog = gtk.AboutDialog()
        def on_website_hook(dialog, web, *args):
            webbrowser.open("http://xpra.org/")
        def on_email_hook(dialog, mail, *args):
            webbrowser.open("mailto://"+mail)
        gtk.about_dialog_set_url_hook(on_website_hook)
        gtk.about_dialog_set_email_hook(on_email_hook)
        dialog.set_name("Xpra")
        from xpra import __version__
        dialog.set_version(__version__)
        dialog.set_copyright('Copyright (c) 2009-2011')
        dialog.set_authors(('Antoine Martin <antoine@nagafix.co.uk>',
                            'Nathaniel Smith <njs@pobox.com>',
                            'Serviware - Arthur Huillet <ahuillet@serviware.com>'))
        #dialog.set_artists ([""])
        dialog.set_license(self.get_license_text())
        dialog.set_website("http://xpra.org/")
        dialog.set_website_label("xpra.org")
        pixbuf = self.get_pixbuf("xpra.png")
        if pixbuf:
            dialog.set_logo(pixbuf)
        dialog.set_program_name("Xpra")
        def response(*args):
            dialog.destroy()
            self.about_dialog = None
        dialog.connect("response", response)
        self.about_dialog = dialog
        dialog.show()



    def grok_modifier_map(self, display_source):
        modifier_map = {
            "shift": 1 << 0,
            "lock": 1 << 1,
            "control": 1 << 2,
            "mod1": 1 << 3,
            "mod2": 1 << 4,
            "mod3": 1 << 5,
            "mod4": 1 << 6,
            "mod5": 1 << 7,
            "scroll": 0,
            "num": 0,
            "meta": 0,
            "super": 0,
            "hyper": 0,
            "alt": 0,
            }
        modifier_map["nuisance"] = (modifier_map["lock"]
                                    | modifier_map["scroll"]
                                    | modifier_map["num"])
        return modifier_map


    def get_data_dir(self):
        return  os.path.dirname(sys.executable)

    def get_icon_filename(self, icon_name):
        filename = os.path.join(self.get_data_dir(), 'icons', icon_name)
        log.debug("get_icon_filename(%s)=%s, exists=%s" % (icon_name, filename, os.path.exists(filename)))
        if os.path.exists(filename):
            return  filename
        return  None

    def get_license_text(self):
        if self.license_text:
            return  self.license_text
        filename = os.path.join(self.get_data_dir(), 'COPYING')
        if os.path.exists(filename):
            try:
                file = open(filename, mode='rb')
                return file.read()
            finally:
                file.close()
        if not self.license_text:
            self.license_text = "GPL version 2"
        return self.license_text

    def get_pixbuf(self, icon_name):
        try:
            icon_filename = self.get_icon_filename(icon_name)
            return  gtk.gdk.pixbuf_new_from_file(icon_filename)
        except:
            return  None
    
    def get_image(self, icon_name, size=None):
        try:
            pixbuf = self.get_pixbuf(icon_name)
            if not pixbuf:
                return  None
            if size:
                pixbuf = pixbuf.scale_simple(size, size, gtk.gdk.INTERP_BILINEAR)
            return  gtk.image_new_from_pixbuf(pixbuf)
        except:
            return  None
