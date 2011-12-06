# coding=utf8
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
import gobject
import webbrowser
import time
import datetime

from xpra.platform import XPRA_LOCAL_SERVERS_SUPPORTED
from xpra.scripts.main import ENCODINGS
from xpra.keys import XMODMAP_MOD_DEFAULTS, XMODMAP_MOD_ADD, XMODMAP_MOD_CLEAR
from wimpiggy.util import gtk_main_quit_really
from wimpiggy.log import Logger
log = Logger()


#utility method to ensure there is always only one CheckMenuItem
#selected in a submenu:
def ensure_item_selected(submenu, item):
    if not isinstance(item, gtk.CheckMenuItem):
        return
    if item.get_active():
        #deactivate all except this one
        def deactivate(items, skip=None):
            for x in items:
                if x==skip:
                    continue
                if isinstance(x, gtk.MenuItem):
                    submenu = x.get_submenu()
                    if submenu:
                        deactivate(submenu.get_children(), skip)
                if isinstance(x, gtk.CheckMenuItem):
                    if x!=item and x.get_active():
                        x.set_active(False)
        deactivate(submenu.get_children(), item)
        return item
    #ensure there is at least one other active item
    def get_active_item(items):
        for x in items:
            if isinstance(x, gtk.MenuItem):
                submenu = x.get_submenu()
                if submenu:
                    a = get_active_item(submenu.get_children())
                    if a:
                        return a
            if isinstance(x, gtk.CheckMenuItem):
                if x.get_active():
                    return x
        return None
    active = get_active_item(submenu.get_children())
    if active:
        return  active
    #if not then keep this one active:
    item.set_active(True)
    return item

def set_checkeditems(submenu, is_match_func):
    """ recursively descends a submenu and any of its sub menus
        and set any "CheckMenuItem" to active if is_match_func(item) """
    if submenu is None:
        return
    for x in submenu.get_children():
        if isinstance(x, gtk.MenuItem):
            set_checkeditems(x.get_submenu(), is_match_func)
        if isinstance(x, gtk.CheckMenuItem):
            a = x.get_active()
            v = is_match_func(x)
            if a!=v:
                x.set_active(v)

class ClientExtrasBase(object):

    def __init__(self, client, opts):
        self.client = client
        self.license_text = None
        self.session_info_window = None
        self.about_dialog = None
        self.tray_icon = opts.tray_icon
        self.session_name = opts.session_name
        self.set_window_icon(opts.window_icon)

    def set_window_icon(self, window_icon):
        if not window_icon:
            window_icon = self.get_icon_filename("xpra.png")
        if window_icon and os.path.exists(window_icon):
            try:
                gtk.window_set_default_icon_from_file(window_icon)
                log.debug("set default window icon to %s", window_icon)
            except Exception, e:
                log.error("failed to set window icon %s: %s, continuing", window_icon, e)

    def quit(self, *args):
        gtk_main_quit_really()

    def exit(self):
        pass

    def supports_mmap(self):
        return XPRA_LOCAL_SERVERS_SUPPORTED

    def supports_clipboard(self):
        return self.clipboard_helper is not None

    def process_clipboard_packet(self, packet):
        if self.clipboard_helper:
            self.clipboard_helper.process_clipboard_packet(packet)
        else:
            log.warn("received a clipboard packet but clipboard is not supported!")

    def setup_clipboard_helper(self, helperClass):
        def clipboard_send(data):
            if self.client.clipboard_enabled:
                self.client.send(data)
            else:
                log.info("clipboard is disabled, not sending clipboard packet")
        self.clipboard_helper = helperClass(clipboard_send)
        def clipboard_toggled(*args):
            log.debug("clipboard_toggled enabled=%s", self.client.clipboard_enabled)
            if self.client.clipboard_enabled:
                self.clipboard_helper.send_all_tokens()
            else:
                pass    #FIXME: todo!
        self.client.connect("clipboard-toggled", clipboard_toggled)

    def can_notify(self):
        return  False

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        pass

    def close_notify(self, id):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        import gtk.gdk
        gtk.gdk.beep()

    def get_layout_spec(self):
        """ layout, variant, variants"""
        return None,None,None

    def supports_raw_keycodes(self):
        return False

    def get_keymap_modifiers(self):
        return  XMODMAP_MOD_CLEAR, XMODMAP_MOD_ADD

    def get_keymap_spec(self):
        """ xkbmap_print, xkbmap_query, xmodmap """
        # default map for non xposix clients:
        return None,None,XMODMAP_MOD_DEFAULTS

    def get_keyboard_repeat(self):
        """ (delay_ms,interval_ms) or None"""
        return None

    def about(self, *args):
        if self.about_dialog:
            self.about_dialog.present()
            return
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

    def session_info(self, *args):
        if self.session_info_window:
            self.session_info_window.present()
            return
        window = gtk.Window()
        window.set_title(self.session_name or "Session Info")
        window.set_destroy_with_parent(True)
        window.set_resizable(True)
        window.set_decorated(True)
        pixbuf = None
        if self.tray_icon:
            pixbuf = self.get_pixbuf(self.tray_icon)
        if not pixbuf:
            pixbuf = self.get_pixbuf("xpra.png")
        if pixbuf:
            window.set_icon(pixbuf)
        window.set_position(gtk.WIN_POS_CENTER)

        # Contents box
        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(2)
        table = gtk.Table(1, columns=2)
        table.set_col_spacings(3)
        table.set_row_spacings(3)
        vbox.add(table)
        def add_row(row, label, widget):
            l_al = gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
            l_al.add(label)
            table.attach(l_al, 0, 1, row, row + 1, xpadding=10)
            w_al = gtk.Alignment(xalign=0.0, yalign=0.5, xscale=0.0, yscale=0.0)
            w_al.add(widget)
            table.attach(w_al, 1, 2, row, row + 1, xpadding=10)
            return row + 1

        # now add some rows with info:
        row = 0
        self.server_version_label = gtk.Label()
        row = add_row(row, gtk.Label("Server Version"), self.server_version_label)
        if self.client.server_platform:
            row = add_row(row, gtk.Label("Server Platform"), gtk.Label(self.client.server_platform))
        self.server_randr_label = gtk.Label()
        row = add_row(row, gtk.Label("Server RandR Support"), self.server_randr_label)
        if self.client.can_ping:
            self.server_load_label = gtk.Label()
            row = add_row(row, gtk.Label("Server Load"), self.server_load_label)
            self.server_latency_label = gtk.Label()
            row = add_row(row, gtk.Label("Server Latency"), self.server_latency_label)
            self.client_latency_label = gtk.Label()
            row = add_row(row, gtk.Label("Client Latency"), self.client_latency_label)
        if self.client.server_start_time>0:
            self.session_started_label = gtk.Label()
            row = add_row(row, gtk.Label("Session Started"), self.session_started_label)
        self.session_connected_label = gtk.Label()
        row = add_row(row, gtk.Label("Session Connected"), self.session_connected_label)
        self.windows_managed_label = gtk.Label()
        row = add_row(row, gtk.Label("Windows Managed"), self.windows_managed_label)
        self.pixels_per_second_label = gtk.Label()
        row = add_row(row, gtk.Label("Pixels/s"), self.pixels_per_second_label)

        def populate_table(*args):
            if not self.session_info_window:
                return False
            self.client.send_ping()
            def settimedeltastr(label, from_time):
                delta = datetime.timedelta(seconds=(long(time.time())-long(from_time)))
                label.set_text(str(delta))
            v = self.client._remote_version or "unknown"
            if self.client.mmap_enabled:
                self.server_version_label.set_text("%s (mmap in use)" % v)
            else:
                self.server_version_label.set_text(v)
            size_info = ""
            if self.client.server_actual_desktop_size:
                w,h = self.client.server_actual_desktop_size
                size_info = " - %sx%s" % (w,h)
            if self.client.server_randr:
                self.server_randr_label.set_text("Yes%s" % size_info)
            else:
                self.server_randr_label.set_text("No%s" % size_info)
            if self.client.can_ping:
                if self.client.server_load:
                    self.server_load_label.set_text("  ".join([str(x/1000.0) for x in self.client.server_load]))
                if len(self.client.server_latency)>0:
                    avg = sum(self.client.server_latency)/len(self.client.server_latency)
                    self.server_latency_label.set_text("%sms  (%sms)" % (self.client.server_latency[-1], avg))
                if len(self.client.client_latency)>0:
                    avg = sum(self.client.client_latency)/len(self.client.client_latency)
                    self.client_latency_label.set_text("%sms  (%sms)" % (self.client.client_latency[-1], avg))
            if self.client.server_start_time>0:
                settimedeltastr(self.session_started_label, self.client.server_start_time)
            settimedeltastr(self.session_connected_label, self.client.start_time)
            real, redirect = 0, 0
            for w in self.client._window_to_id.keys():
                if w._override_redirect:
                    redirect +=1
                else:
                    real += 1
            self.windows_managed_label.set_text("%s  (%s transient)" % (real, redirect))
            pixels = "n/a"
            if len(self.client.pixel_counter)>0:
                total = 0
                now = time.time()
                mint = now-20       #ignore records older than 20 seconds
                startt = now        #when we actually start counting from
                for (t, count) in self.client.pixel_counter:
                    if t>=mint:
                        total += count
                        startt = min(t, startt)
                if total>0 and startt!=now:
                    def pixelstr(v):
                        if v>1000*1000*1000:
                            return "%sG" % (long(v/1000/1000/100)/10.0)
                        elif v>1000*1000:
                            return "%sM" % (long(v/1000/100)/10.0)
                        elif v>1000:
                            return "%sK" % (long(v/100)/10.0)
                        else:
                            return str(v)
                    t, last = self.client.pixel_counter[-1]
                    if t<now-5:
                        last = 0
                    avg = long(total/(now-startt))
                    pixels = "%s  (%s)" % (pixelstr(last), pixelstr(avg))

            self.pixels_per_second_label.set_text(pixels)
            return True
        gobject.timeout_add(1000, populate_table)

        window.set_border_width(15)
        window.add(vbox)
        window.set_geometry_hints(vbox)
        def window_deleted(*args):
            self.session_info_window = None
        window.connect('delete_event', window_deleted)
        def close_window(*args):
            self.session_info_window = None
            window.destroy()
        self.add_close_accel(window, close_window)
        self.session_info_window = window
        populate_table()
        window.show_all()

    def add_close_accel(self, window, callback):
        # key accelerators
        accel_group = gtk.AccelGroup()
        accel_group.connect_group(ord('w'), gtk.gdk.CONTROL_MASK, gtk.ACCEL_LOCKED, callback)
        window.add_accel_group(accel_group)
        accel_group = gtk.AccelGroup()
        escape_key, modifier = gtk.accelerator_parse('Escape')
        accel_group.connect_group(escape_key, modifier, gtk.ACCEL_LOCKED |  gtk.ACCEL_VISIBLE, callback)
        window.add_accel_group(accel_group)



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
        return  os.path.dirname(sys.executable) or os.getcwd()

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



    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        menu_item = gtk.ImageMenuItem(title)
        image = None
        if icon_name:
            image = self.get_image(icon_name, 24)
        if image:
            menu_item.set_image(image)
            #override gtk defaults: we *want* icons:
            settings = menu_item.get_settings()
            settings.set_property('gtk-menu-images', True)
            if hasattr(settings, "set_always_show_image"):
                settings.set_always_show_image(True)
        if tooltip:
            menu_item.set_tooltip_text(tooltip)
        if cb:
            menu_item.connect('activate', cb)
        menu_item.show()
        return menu_item

    def checkitem(self, title, cb=None):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = gtk.CheckMenuItem(title)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item


    def close_menu(self, *args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *args):
        self.menu_shown = False

    def activate_menu(self, widget, *args):
        self.show_menu(1, 0)

    def popup_menu(self, widget, button, time, *args):
        self.show_menu(button, time)

    def show_menu(self, button, time):
        self.close_menu()
        self.menu.popup(None, None, None, button, time, None)
        self.menu_shown = True

    def make_aboutmenuitem(self):
        return  self.menuitem("About Xpra", "information.png", None, self.about)

    def make_sessioninfomenuitem(self):
        return  self.menuitem(self.session_name or "Session Info", "statistics.png", None, self.session_info)

    def make_bellmenuitem(self):
        def bell_toggled(*args):
            self.client.bell_enabled = self.bell_menuitem.get_active()
            log.debug("bell_toggled(%s) bell_enabled=%s", args, self.client.bell_enabled)
        self.bell_menuitem = self.checkitem("Bell", bell_toggled)
        def set_bellmenuitem(*args):
            self.bell_menuitem.set_active(self.client.bell_enabled)
            self.bell_menuitem.set_sensitive(self.client.server_capabilities.get("bell", False))
        self.client.connect("handshake-complete", set_bellmenuitem)
        return  self.bell_menuitem

    def make_notificationsmenuitem(self):
        def notifications_toggled(*args):
            self.client.notifications_enabled = self.notifications_menuitem.get_active()
            log.debug("notifications_toggled(%s) notifications_enabled=%s", args, self.client.notifications_enabled)
        self.notifications_menuitem = self.checkitem("Notifications", notifications_toggled)
        def set_notifications_menuitem(*args):
            self.notifications_menuitem.set_active(self.client.notifications_enabled)
            self.notifications_menuitem.set_sensitive(self.client.server_capabilities.get("notifications", False))
        self.client.connect("handshake-complete", set_notifications_menuitem)
        return self.notifications_menuitem

    def make_clipboardmenuitem(self):
        def clipboard_toggled(*args):
            self.client.clipboard_enabled = self.clipboard_menuitem.get_active()
            log.debug("clipboard_toggled(%s) clipboard_enabled=%s", args, self.client.clipboard_enabled)
            self.client.emit("clipboard-toggled")
        self.clipboard_menuitem = self.checkitem("Clipboard", clipboard_toggled)
        def set_clipboard_menuitem(*args):
            self.clipboard_menuitem.set_active(self.client.clipboard_enabled)
            self.clipboard_menuitem.set_sensitive(self.client.server_capabilities.get("clipboard", True))
        self.client.connect("handshake-complete", set_clipboard_menuitem)
        return self.clipboard_menuitem

    def make_encodingsmenuitem(self):
        encodings = self.menuitem("Encoding", "encoding.png", "Choose picture data encoding", None)
        self.encodings_submenu = gtk.Menu()
        encodings.set_submenu(self.encodings_submenu)
        self.popup_menu_workaround(self.encodings_submenu)
        def set_encodingsmenuitem(*args):
            for encoding in ENCODINGS:
                encoding_item = gtk.CheckMenuItem(encoding)
                encoding_item.get_label()
                def encoding_changed(item):
                    item = ensure_item_selected(self.encodings_submenu, item)
                    enc = item.get_label()
                    if self.client.encoding!=enc:
                        self.client.set_encoding(enc)
                        log.debug("setting encoding to %s", enc)
                        self.set_jpegmenu()
                        self.updated_menus()
                encoding_item.set_active(encoding==self.client.encoding)
                encoding_item.set_sensitive(encoding in self.client.server_capabilities.get("encodings", ["rgb24"]))
                encoding_item.set_draw_as_radio(True)
                encoding_item.connect("toggled", encoding_changed)
                self.encodings_submenu.append(encoding_item)
            self.encodings_submenu.show_all()
        self.client.connect("handshake-complete", set_encodingsmenuitem)
        return encodings

    def make_layoutsmenuitem(self):
        keyboard = self.menuitem("Keyboard", "keyboard.png", "Select your keyboard layout", None)
        self.layout_submenu = gtk.Menu()
        keyboard.set_submenu(self.layout_submenu)
        self.popup_menu_workaround(self.layout_submenu)
        def kbitem(title, layout, variant):
            def set_layout(item):
                """ this callback updates the client (and server) if needed """
                item = ensure_item_selected(self.layout_submenu, item)
                layout = item.keyboard_layout
                variant = item.keyboard_variant
                if layout!=self.client.xkbmap_layout or variant!=self.client.xkbmap_variant:
                    log.debug("keyboard layout selected: %s / %s", layout, variant)
                    self.client.xkbmap_layout = layout
                    self.client.xkbmap_variant = variant
                    self.client.send_layout()
            l = self.checkitem(title, set_layout)
            l.set_draw_as_radio(True)
            l.keyboard_layout = layout
            l.keyboard_variant = variant
            return l
        def keysort(key):
            c,l = key
            return c.lower()+l.lower()
        layout,variant,variants = self.get_layout_spec()
        if layout and len(variants)>1:
            #just show all the variants to choose from this layout
            self.layout_submenu.append(kbitem("%s - Default" % layout, layout, None))
            for v in variants:
                self.layout_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
        else:
            #show all options to choose from:
            sorted_keys = X11_LAYOUTS.keys()
            sorted_keys.sort(key=keysort)
            for key in sorted_keys:
                country,language = key
                layout,variants = X11_LAYOUTS.get(key)
                name = "%s - %s" % (country, language)
                if len(variants)>1:
                    #sub-menu for each variant:
                    variant = self.menuitem(name, tooltip=layout)
                    variant_submenu = gtk.Menu()
                    variant.set_submenu(variant_submenu)
                    self.popup_menu_workaround(variant_submenu)
                    self.layout_submenu.append(variant)
                    variant_submenu.append(kbitem("%s - Default" % layout, layout, None))
                    for v in variants:
                        variant_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
                else:
                    #no variants:
                    self.layout_submenu.append(kbitem(name, layout, None))
        def set_selected_layout(*args):
            layout = self.client.xkbmap_layout
            variant = self.client.xkbmap_variant
            def is_match(checkitem):
                return checkitem.keyboard_layout==layout and checkitem.keyboard_variant==variant
            set_checkeditems(self.layout_submenu, is_match)
        self.client.connect("handshake-complete", set_selected_layout)
        return keyboard

    def make_jpegsubmenu(self):
        self.jpeg_quality = self.menuitem("JPEG Quality", "slider.png", "Change JPEG quality setting", None)
        self.jpeg_submenu = gtk.Menu()
        self.jpeg_quality.set_submenu(self.jpeg_submenu)
        self.popup_menu_workaround(self.jpeg_submenu)
        jpeg_options = [10, 50, 80, 95]
        if self.client.jpegquality>0 and self.client.jpegquality not in jpeg_options:
            """ add the current value to the list of options """
            i = 0
            for x in jpeg_options:
                if self.client.jpegquality<x:
                    jpeg_options.insert(i, self.client.jpegquality)
                    break
                i += 1
        def set_jpeg_quality(item):
            item = ensure_item_selected(self.jpeg_submenu, item)
            q = int(item.get_label().replace("%", ""))
            if q!=self.client.jpegquality:
                log.debug("setting jpeg quality to %s", q)
                self.client.send_jpeg_quality(q)
        for q in jpeg_options:
            qi = gtk.CheckMenuItem("%s%%" % q)
            qi.set_draw_as_radio(True)
            qi.set_active(q==self.client.jpegquality)
            qi.connect('activate', set_jpeg_quality)
            self.jpeg_submenu.append(qi)
        self.jpeg_submenu.show_all()
        self.client.connect("handshake-complete", self.set_jpegmenu)
        return self.jpeg_quality

    def set_jpegmenu(self, *args):
        if self.jpeg_quality:
            self.jpeg_quality.set_sensitive("jpeg"==self.client.encoding)
            self.updated_menus()

    def updated_menus(self):
        """ subclasses may override this method - see darwin """
        pass

    def make_refreshmenuitem(self):
        def force_refresh(*args):
            log.debug("force refresh")
            self.client.send_refresh_all()
        return self.menuitem("Refresh", "retry.png", None, force_refresh)

    def make_disconnectmenuitem(self):
        return self.menuitem("Disconnect", "quit.png", None, self.quit)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)

    def setup_menu(self, show_close=False):
        self.menu_shown = False
        menu = gtk.Menu()
        menu.set_title(self.client.session_name or "Xpra")
        def set_menu_title(*args):
            #set the real name when available:
            self.menu.set_title(self.client.session_name)
        self.client.connect("handshake-complete", set_menu_title)

        menu.append(self.make_aboutmenuitem())
        menu.append(self.make_sessioninfomenuitem())
        menu.append(gtk.SeparatorMenuItem())
        menu.append(self.make_bellmenuitem())
        menu.append(self.make_notificationsmenuitem())
        menu.append(self.make_clipboardmenuitem())
        if len(ENCODINGS)>1:
            menu.append(self.make_encodingsmenuitem())
        else:
            self.encodings_submenu = None
        if "jpeg" in ENCODINGS:
            menu.append(self.make_jpegsubmenu())
        else:
            self.jpeg_quality = None
            self.jpeg_submenu = None
        menu.append(self.make_layoutsmenuitem())
        menu.append(self.make_refreshmenuitem())
        #menu.append(item("Options", "configure", None, self.options))
        menu.append(gtk.SeparatorMenuItem())
        menu.append(self.make_disconnectmenuitem())
        if show_close:
            menu.append(self.make_closemenuitem())
        self.popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        self.menu = menu

    def popup_menu_workaround(self, menu):
        #win32 overrides this to add the workaround
        pass

    def add_popup_menu_workaround(self, menu):
        """ windows does not automatically close the popup menu when we click outside it
            so we workaround it by using a timer and closing the menu when the mouse
            has stayed outside it for more than 0.5s.
            This code must be added to all the sub-menus of the popup menu too!
        """
        def enter_menu(*args):
            log.debug("mouse_in_tray_menu=%s", self.mouse_in_tray_menu)
            self.mouse_in_tray_menu_counter += 1
            self.mouse_in_tray_menu = True
        def leave_menu(*args):
            log.debug("mouse_in_tray_menu=%s", self.mouse_in_tray_menu)
            self.mouse_in_tray_menu_counter += 1
            self.mouse_in_tray_menu = False
            def check_menu_left(expected_counter):
                if self.mouse_in_tray_menu:
                    return    False
                if expected_counter!=self.mouse_in_tray_menu_counter:
                    return    False            #counter has changed
                self.close_menu()
            gobject.timeout_add(500, check_menu_left, self.mouse_in_tray_menu_counter)
        self.mouse_in_tray_menu_counter = 0
        self.mouse_in_tray_menu = False
        log.debug("popup_menu_workaround: adding events callbacks")
        menu.connect("enter-notify-event", enter_menu)
        menu.connect("leave-notify-event", leave_menu)





# The data for this table can be found mostly here:
# http://msdn.microsoft.com/en-us/library/aa912040.aspx
# and here:
# http://support.microsoft.com/kb/278957
# Format:
# Language identifier: (Language code, Sublanguage - locale, Language, Default code page, X11 keymap, x11 variants)
# The x11 keymap name was found in /usr/share/X11/xkb/rules/*
# This is used for converting the layout we detect using win32api into
# something that can be used by X11 (a layout with optional variant)
UNICODE=-1
LATAM_VARIANTS = ["nodeadkeys", "deadtilde", "sundeadkeys"]
ARA_VARIANTS = ["azerty", "azerty_digits", "digits", "qwerty", "qwerty_digits", "buckwalter"]
ES_VARIANTS = ["nodeadkeys", "deadtilde", "sundeadkeys", "dvorak", "est", "cat", "mac"]
RS_VARIANTS = ["yz", "latin", "latinunicode", "latinyz", "latinunicodeyz", "alternatequotes", "latinalternatequotes", "rue"]
FR_VARIANTS = ["nodeadkeys", "sundeadkeys", "oss", "oss_latin9", "oss_nodeadkeys", "oss_sundeadkeys", "latin9", "latin9_nodeadkeys", "latin9_sundeadkeys", "bepo", "bepo_latin9", "dvorak", "mac", "bre", "oci", "geo"]
WIN32_LAYOUTS = {
           1025: ("ARA", "Saudi Arabia",   "Arabic",                   1356,   "ar", []),
           1026: ("BGR", "Bulgaria",       "Bulgarian",                1251,   "bg", ["phonetic", "bas_phonetic"]),
           1027: ("CAT", "Spain",          "Catalan",                  1252,   "ad", []),
           1028: ("CHT", "Taiwan",         "Chinese",                  950,    "tw", ["indigenous", "saisiyat"]),
           1029: ("CSY", "Czech",          "Czech",                    1250,   "cz", ["bksl", "qwerty", "qwerty_bksl", "ucw", "dvorak-ucw"]),
           1030: ("DAN", "Denmark",        "Danish",                   1252,   "dk", ["nodeadkeys", "mac", "mac_nodeadkeys", "dvorak"]),
           1031: ("DEU", "Germany",        "German",                   1252,   "de", ["nodeadkeys", "sundeadkeys", "mac"]),
           1032: ("ELL", "Greece",         "Greek",                    1253,   "gr", ["simple", "extended", "nodeadkeys", "polytonic"]),
           1033: ("USA", "United States",  "English",                  1252,   "us", []),
           1034: ("ESP", "Spain (Traditional sort)", "Spanish",        1252,   "es", ES_VARIANTS),
           1035: ("FIN", "Finland",        "Finnish",                  1252,   "fi", ["classic", "nodeadkeys", "smi", "mac"]),
           1036: ("FRA", "France",         "French",                   1252,   "fr", FR_VARIANTS),
           1037: ("HEB", "Israel",         "Hebrew",                   1255,   "il", ["lyx", "phonetic", "biblical"]),
           1038: ("HUN", "Hungary",        "Hungarian",                1250,   "hu", ["standard", "nodeadkeys", "qwerty", "101_qwertz_comma_dead", "101_qwertz_comma_nodead", "101_qwertz_dot_dead", "101_qwertz_dot_nodead", "101_qwerty_comma_dead", "101_qwerty_comma_nodead", "101_qwerty_dot_dead", "101_qwerty_dot_nodead", "102_qwertz_comma_dead", "102_qwertz_comma_nodead", "102_qwertz_dot_dead", "102_qwertz_dot_nodead", "102_qwerty_comma_dead", "102_qwerty_comma_nodead", "102_qwerty_dot_dead", "102_qwerty_dot_nodead"]),
           1039: ("ISL", "Iceland",        "Icelandic",                1252,   "is", ["sundeadkeys", "nodeadkeys", "mac", "dvorak"]),
           1040: ("ITA", "Italy",          "Italian",                  1252,   "it", ["nodeadkeys", "mac", "us", "geo"]),
           1041: ("JPN", "Japan",          "Japanese",                 932,    "jp", ["kana", "kana86", "OADG109A", "mac"]),
           1042: ("KOR", "Korea",          "Korean",                   949,    "kr", ["kr104"]),
           1043: ("NLD", "Netherlands",    "Dutch",                    1252,   "nl", ["sundeadkeys", "mac", "std"]),
           1044: ("NOR", "Norway (Bokmål)","Norwegian",                1252,   "no", ["nodeadkeys", "dvorak", "smi", "smi_nodeadkeys", "mac", "mac_nodeadkeys"]),
           1045: ("PLK", "Poland",         "Polish",                   1250,   "pl", ["qwertz", "dvorak", "dvorak_quotes", "dvorak_altquotes", "csb", "ru_phonetic_dvorak", "dvp"]),
           1046: ("PTB", "Brazil",         "Portuguese",               1252,   "br", ["nodeadkeys", "dvorak", "nativo", "nativo-us", "nativo-epo"]),
           1048: ("ROM", "Romania",        "Romanian",                 1250,   "ro", ["cedilla", "std", "std_cedilla", "winkeys"]),
           1049: ("RUS", "Russia",         "Russian",                  1251,   "ru", ["phonetic", "phonetic_winkeys", "typewriter", "legacy", "typewriter-legacy", "tt", "os_legacy", "os_winkeys", "cv", "cv_latin", "udm", "kom", "sah", "xal", "dos", "srp", "bak", "chm"]),
           1050: ("HRV", "Croatia",        "Croatian",                 1250,   "hr", ["alternatequotes", "unicode", "unicodeus", "us"]),
           1051: ("SKY", "Slovakia",       "Slovakian",                1250,   "sk", ["bksl", "qwerty", "qwerty_bksl"]),
           1052: ("SQI", "Albania",        "Albanian",                 1250,   "al", []),
           1053: ("SVE", "Sweden",         "Swedish",                  1252,   "se", ["nodeadkeys", "dvorak", "rus", "rus_nodeadkeys", "smi", "mac", "svdvorak", "swl"]),
           1054: ("THA", "Thailand",       "Thai",                     874,    "th", ["tis", "pat"]),
           1055: ("TRK", "Turkey",         "Turkish",                  1254,   "tr", ["f", "alt", "sundeadkeys", "ku", "ku_f", "ku_alt", "intl", "crh", "crh_f", "crh_alt"]),
           1056: ("URP", "Pakistan",       "Urdu",                     1256,   "pk", ["urd-crulp", "urd-nla", "ara", "snd"]),
           1057: ("IND", "Indonesia (Bahasa)", "Indonesian",           1252,   "", []),
           1058: ("UKR", "Ukraine",        "Ukrainian",                1251,   "ua", ["phonetic", "typewriter", "winkeys", "legacy", "rstu", "rstu_ru", "homophonic"]),
           1059: ("BEL", "Belarus",        "Belarusian",               1251,   "by", ["legacy", "latin"]),
           1060: ("SLV", "Slovenia",       "Slovenian",                1250,   "si", ["alternatequotes", "us"]),
           1061: ("ETI", "Estonia",        "Estonian",                 1257,   "ee", ["nodeadkeys", "dvorak", "us"]),
           1062: ("LVI", "Latvia",         "Latvian",                  1257,   "lv", ["apostrophe", "tilde", "fkey", "modern", "ergonomic", "adapted"]),
           1063: ("LTH", "Lithuania",      "Lithuanian",               1257,   "lt", ["std", "us", "ibm", "lekp", "lekpa"]),
           1065: ("FAR", "Iran",           "Farsi",                    1256,   "", []),
           1066: ("VIT", "Viet Nam",       "Vietnamese",               1258,   "vn", []),
           1067: ("HYE", "Armenia",        "Armenian",                 UNICODE,"am", ["phonetic", "phonetic-alt", "eastern", "western", "eastern-alt"]),
           1068: ("AZE", "Azerbaijan (Latin)", "Azeri",                1254,   "az", ["cyrillic"]),
           1069: ("EUQ", "Spain",          "Basque",                   1252,   "es", []),
           1071: ("MKI", "F.Y.R.O. Macedonia", "F.Y.R.O. Macedonia",   1251,   "mk", ["nodeadkeys"]),
           1078: ("AFK", "South Africa",   "Afrikaans",                1252,   "", []),
           1079: ("KAT", "Georgia",        "Georgian",                 UNICODE,"ge", ["ergonomic", "mess", "ru", "os"]),
           1080: ("FOS", "Faroe Islands",  "Faroese",                  1252,   "fo", ["nodeadkeys"]),
           1081: ("HIN", "India",          "Hindi",                    UNICODE,"in", ["bolnagri", "hin-wx"]),
           1086: ("MSL", "Malaysia",       "Malay",                    1252,   "in", ["mal", "mal_lalitha", "mal_enhanced"]),
           1087: ("KKZ", "Kazakstan",      "Kazakh",                   1251,   "kz", ["ruskaz", "kazrus"]),
           1088: ("KYR", "Kyrgyzstan",     "Kyrgyz",                   1251,   "kg", ["phonetic"]),
           1089: ("SWK", "Kenya",          "Swahili",                  1252,   "ke", ["kik"]),
           1091: ("UZB", "Uzbekistan (Latin)", "Uzbek",                1254,   "uz", ["latin"]),
           1092: ("TTT", "Tatarstan",      "Tatar",                    1251,   "ru", ["tt"]),
           1094: ("PAN", "India (Gurmukhi script)", "Punjabi",         UNICODE,"in", ["guru", "jhelum"]),
           1095: ("GUJ", "India",          "Gujarati",                 UNICODE,"in", ["guj"]),
           1097: ("TAM", "India",          "Tamil",                    UNICODE,"in", ["tam_unicode", "tam_keyboard_with_numerals", "tam_TAB", "tam_TSCII", "tam"]),
           1098: ("TEL", "India (Telugu script)", "Telugu",            UNICODE,"in", ["tel"]),
           1099: ("KAN", "India (Kannada script)", "Kannada",          UNICODE,"in", ["kan"]),
           1102: ("MAR", "India",          "Marathi",                  UNICODE,"in", []),
           1103: ("SAN", "India",          "Sanskrit",                 UNICODE,"in", []),
           1104: ("MON", "Mongolia",       "Mongolian (Cyrillic)",     1251,   "mn", []),
           1110: ("GLC", "Spain",          "Galician",                 1252,   "es", []),
           1111: ("KNK", "India",          "Konkani",                  UNICODE,"in", []),
           1114: ("SYR", "Syria",          "Syriac",                   UNICODE,"sy", ["syc", "syc_phonetic", "ku", "ku_f", "ku_alt"]),
           1125: ("DIV", "Maldives",       "Divehi",                   UNICODE,"", []),
           2049: ("ARI", "Iraq",           "Arabic",                   1256,   "iq", ["ku", "ku_f", "ku_alt", "ku_ara"]),
           2052: ("CHS", "PRC",            "Chinese, Simplified",      0,      "cn", ["tib", "tib_asciinum", "uig"]),
           2055: ("DES", "Switzerland",    "German",                   1252,   "de", ["deadacute", "deadgraveacute", "nodeadkeys", "ro", "ro_nodeadkeys", "dvorak", "sundeadkeys", "neo", "mac", "mac_nodeadkeys", "dsb", "dsb_qwertz", "qwerty", "ru"]),
           2057: ("ENG", "UK",             "English",                  1252,   "gb", ["extd", "intl", "dvorak", "dvorakukp", "mac", "mac_intl", "colemak"]),
           2058: ("ESM", "Mexico",         "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           2060: ("FRB", "Benelux",        "French",                   1252,   "be", ["oss", "oss_latin9", "oss_sundeadkeys", "iso-alternate", "nodeadkeys", "sundeadkeys", "wang"]),
           2064: ("ITS", "Switzerland",    "Italian",                  1252,   "it", ["nodeadkeys", "mac", "us", "geo"]),
           2067: ("NLB", "Belgium",        "Dutch",                    1252,   "nl", ["sundeadkeys", "mac", "std"]),
           2068: ("NON", "Norway (Nynorsk)", "Norwegian",              1252,   "no", ["nodeadkeys", "dvorak", "smi", "smi_nodeadkeys", "mac", "mac_nodeadkeys"]),
           2070: ("PTG", "Portugal",       "Portuguese",               1252,   "pt", ["nodeadkeys", "sundeadkeys", "mac", "mac_nodeadkeys", "mac_sundeadkeys", "nativo", "nativo-us", "nativo-epo"]),
           2074: ("SRL", "Serbia (Latin)", "Serbian",                  1250,   "rs", RS_VARIANTS),
           2077: ("SVF", "Finland",        "Swedish",                  1252,   "se", ["nodeadkeys", "dvorak", "rus", "rus_nodeadkeys", "smi", "mac", "svdvorak", "swl"]),
           2092: ("AZE", "Azerbaijan (Cyrillic)", "Azeri",             1251,   "az", ["cyrillic"]),
           2110: ("MSB", "Brunei Darussalam", "Malay",                 1252,   "in", ["mal", "mal_lalitha", "mal_enhanced"]),
           2115: ("UZB", "Uzbekistan (Cyrillic)", "Uzbek",             1251,   "uz", ["latin"]),
           3073: ("ARE", "Egypt",          "Arabic",                   1256,   "ara", ARA_VARIANTS),
           3076: ("ZHH", "Hong Kong SAR",  "Chinese",                  950,    "cn", []),
           3079: ("DEA", "Austria",        "German",                   1252,   "at", ["nodeadkeys", "sundeadkeys", "mac"]),
           3081: ("ENA", "Australia",      "English",                  1252,   "us", []),
           3082: ("ESN", "Spain (International sort)", "Spanish",      1252,   "es", ES_VARIANTS),
           3084: ("FRC", "Canada",         "French",                   1252,   "ca", ["fr-dvorak", "fr-legacy", "multix", "multi", "multi-2gr", "ike"]),
           3098: ("SRB", "Serbia (Cyrillic)", "Serbian",               1251,   "", RS_VARIANTS),
           4097: ("ARL", "Libya",          "Arabic",                   1256,   "ara", ARA_VARIANTS),
           4100: ("ZHI", "Singapore",      "Chinese",                  936,    "cn", []),
           4103: ("DEL", "Luxembourg",     "German",                   1252,   "de", []),
           4105: ("ENC", "Canada",         "English",                  1252,   "ca", ["eng"]),
           4106: ("ESG", "Guatemala",      "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           4108: ("FRS", "Switzerland",    "French",                   1252,   "ch", ["fr", "fr_nodeadkeys", "fr_sundeadkeys", "fr_mac"]),
           5121: ("ARG", "Algeria",        "Arabic",                   1256,   "ara", ARA_VARIANTS),
           5124: ("ZHM", "Macao SAR",      "Chinese",                  950,    "cn", []),
           5127: ("DEC", "Liechtenstein",  "German",                   1252,   "de", []),
           5129: ("ENZ", "New Zealand",    "English",                  1252,   "us", []),
           5130: ("ESC", "Costa Rica",     "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           5132: ("FRL", "Luxembourg",     "French",                   1252,   "fr", FR_VARIANTS),
           6145: ("ARM", "Morocco",        "Arabic",                   1256,   "ara", ARA_VARIANTS),
           6153: ("ENI", "Ireland",        "English",                  1252,   "en", []),
           6154: ("ESA", "Panama",         "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           6156: ("FRM", "Monaco",         "French",                   1252,   "fr", FR_VARIANTS),
           7169: ("ART", "Tunisia",        "Arabic",                   1256,   "ara", ARA_VARIANTS),
           7177: ("ENS", "South Africa",   "English",                  1252,   "en", []),
           7178: ("ESD", "Dominican Republic", "Spanish",              1252,   "latam", LATAM_VARIANTS),
           8193: ("ARO", "Oman",           "Arabic",                   1256,   "ara", ARA_VARIANTS),
           8201: ("ENJ", "Jamaica",        "English",                  1252,   "en", []),
           8202: ("ESV", "Venezuela",      "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           9217: ("ARY", "Yemen",          "Arabic",                   1256,   "ara", ARA_VARIANTS),
           9225: ("ENB", "Caribbean",      "English",                  1252,   "en", []),
           9226: ("ESO", "Colombia",       "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           10241: ("ARS", "Syria",         "Arabic",                   1256,   "sy", ["syc", "syc_phonetic"]),
           10249: ("ENL", "Belize",        "English",                  1252,   "us", []),
           10250: ("ESR", "Peru",          "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           11265: ("ARJ", "Jordan",        "Arabic",                   1256,   "ara", ARA_VARIANTS),
           11273: ("ENT", "Trinidad",      "English",                  1252,   "us", []),
           11274: ("ESS", "Argentina",     "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           12289: ("ARB", "Lebanon",       "Arabic",                   1256,   "ara", ARA_VARIANTS),
           12297: ("ENW", "Zimbabwe",      "English",                  1252,   "us", []),
           12298: ("ESF", "Ecuador",       "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           13321: ("ENP", "Philippines",   "English",                  1252,   "us", []),
           13313: ("ARK", "Kuwait",        "Arabic",                   1256,   "ara", ARA_VARIANTS),
           13322: ("ESL", "Chile",         "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           14337: ("ARU", "U.A.E.",        "Arabic",                   1256,   "ara", ARA_VARIANTS),
           14345: ("",    "Indonesia",     "English",                  1252,   "us", []),
           14346: ("ESY", "Uruguay",       "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           15361: ("ARH", "Bahrain",       "Arabic",                   1256,   "ara", ARA_VARIANTS),
           15369: ("ZHH", "Hong Kong SAR", "English",                  1252,   "us", []),
           15370: ("ESZ", "Paraguay",      "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           16385: ("ARQ", "Qatar",         "Arabic",                   1256,   "ara", ARA_VARIANTS),
           16393: ("",    "India",         "English",                  1252,   "us", []),
           16394: ("ESB", "Bolivia",       "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           17417: ("",    "Malaysia",      "English",                  1252,   "us", []),
           17418: ("ESE", "El Salvador",   "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           18441: ("",    "Singapore",     "English",                  1252,   "us", []),
           18442: ("ESH", "Honduras",      "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           19466: ("ESI", "Nicaragua",     "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           20490: ("ESU", "Puerto Rico",   "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           58378: ("",    "LatAm",         "Spanish",                  1252,   "latam", LATAM_VARIANTS),
           58380: ("",    "North Africa",  "French",                   1252,   "fr", FR_VARIANTS),
           }

# This is generated from the table above so we can
# let the user choose his own layout.
# (country,language) : (layout,variant)
X11_LAYOUTS = {}
for _, country, language, _, layout, variants in WIN32_LAYOUTS.values():
    key = (country,language)
    value = (layout, variants)
    X11_LAYOUTS[key] = value
LAYOUT_VARIANTS = {}
for _, _, _, _, layout, variants in WIN32_LAYOUTS.values():
    l = LAYOUT_VARIANTS.get(layout)
    if not l:
        l = []
        LAYOUT_VARIANTS[layout] = l
    for v in variants:
        if v not in l:
            l.append(v)
