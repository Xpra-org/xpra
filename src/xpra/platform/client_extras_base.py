# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from wimpiggy.gobject_compat import import_gtk, import_gdk, import_gobject, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
import webbrowser

from xpra.platform import XPRA_LOCAL_SERVERS_SUPPORTED
from xpra.scripts.main import ENCODINGS
from xpra.keys import get_gtk_keymap, mask_to_names
from wimpiggy.log import Logger
log = Logger()

#compression is fine with default value (3), no need to clutter the UI
SHOW_COMPRESSION_MENU = False

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

def add_close_accel(window, callback):
    if is_gtk3():
        return      #TODO: implement accel for gtk3
    # key accelerators
    accel_group = gtk.AccelGroup()
    accel_group.connect_group(ord('w'), gdk.CONTROL_MASK, gtk.ACCEL_LOCKED, callback)
    window.add_accel_group(accel_group)
    accel_group = gtk.AccelGroup()
    escape_key, modifier = gtk.accelerator_parse('Escape')
    accel_group.connect_group(escape_key, modifier, gtk.ACCEL_LOCKED |  gtk.ACCEL_VISIBLE, callback)
    window.add_accel_group(accel_group)

def get_build_info():
    info = []
    try:
        from xpra.build_info import BUILT_BY, BUILT_ON, BUILD_DATE, REVISION, LOCAL_MODIFICATIONS
        info.append("Built on %s by %s" % (BUILT_ON, BUILT_BY))
        if BUILD_DATE:
            info.append(BUILD_DATE)
        if int(LOCAL_MODIFICATIONS)==0:
            info.append("revision %s" % REVISION)
        else:
            info.append("revision %s with %s local changes" % (REVISION, LOCAL_MODIFICATIONS))
    except Exception, e:
        log.error("could not find the build information: %s", e)
    return info


if hasattr(gtk, "pygtk_version") and gtk.pygtk_version<(2,12):
    def set_tooltip_text(widget, text):
        pass
else:
    def set_tooltip_text(widget, text):
        widget.set_tooltip_text(text)

def CheckMenuItem(label):
    """ adds a get_label() method for older versions of gtk which do not have it
        beware that this label is not mutable!
    """
    cmi = gtk.CheckMenuItem(label)
    if not hasattr(cmi, "get_label"):
        def get_label():
            return  label
        cmi.get_label = get_label
    return cmi

class ClientExtrasBase(object):

    def __init__(self, client, opts, conn):
        self.client = client
        self.connection = conn
        self.license_text = None
        self.session_info_window = None
        self.about_dialog = None
        self.tray_icon = opts.tray_icon
        self.session_name = opts.session_name
        self.clipboard_helper = None
        #modifier bits:
        self.modifier_mappings = None       #{'control': [(37, 'Control_L'), (105, 'Control_R')], 'mod1':
        self.modifier_keys = {}             #{"Control_L" : "control", ...}
        self.modifier_keycodes = {}         #{"Control_R" : [105], ...}
        self.set_window_icon(opts.window_icon)
        self.update_modmap()

    def set_modifier_mappings(self, mappings):
        log("set_modifier_mappings(%s)", mappings)
        self.modifier_mappings = mappings
        self.modifier_keys = {}
        self.modifier_keycodes = {}
        for modifier, keys in mappings.items():
            for keycode,keyname in keys:
                self.modifier_keys[keyname] = modifier
                keycodes = self.modifier_keycodes.setdefault(keyname, [])
                if keycode not in keycodes:
                    keycodes.append(keycode)
        log("modifier_keys=%s", self.modifier_keys)
        log("modifier_keycodes=%s", self.modifier_keycodes)

    def set_window_icon(self, window_icon):
        if not window_icon:
            window_icon = self.get_icon_filename("xpra.png")
        if window_icon and os.path.exists(window_icon):
            try:
                if is_gtk3():
                    gtk.Window.set_default_icon_from_file(window_icon)
                else:
                    gtk.window_set_default_icon_from_file(window_icon)
                log.debug("set default window icon to %s", window_icon)
            except Exception, e:
                log.error("failed to set window icon %s: %s, continuing", window_icon, e)

    def quit(self, *args):
        self.client.quit(0)

    def cleanup(self):
        self.close_about()
        self.close_session_info()

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
        def clipboard_send(*parts):
            if self.client.clipboard_enabled:
                self.client.send(*parts)
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

    def show_notify(self, dbus_id, nid, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        pass

    def close_notify(self, nid):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        gdk.beep()

    def get_layout_spec(self):
        """ layout, variant, variants"""
        return None,None,None

    def mask_to_names(self, mask):
        return mask_to_names(mask, self._modifier_map)

    def handle_key_event(self, send_key_action_cb, event, wid, pressed):
        modifiers = self.mask_to_names(event.state)
        keyname = gdk.keyval_name(event.keyval)
        keyval = event.keyval
        keycode = event.hardware_keycode
        group = event.group
        string = event.string
        #meant to be in PyGTK since 2.10, not used yet so just return False if we don't have it:
        is_modifier = hasattr(event, "is_modifier") and event.is_modifier
        send_key_action_cb(wid, keyname, pressed, modifiers, keyval, string, keycode, group, is_modifier)

    def update_modmap(self, xkbmap_mod_meanings={}):
        try:
            self._modifier_map = self.grok_modifier_map(gdk.display_get_default(), xkbmap_mod_meanings)
        except Exception, e:
            log.error("update_modmap(%s): %s" % (xkbmap_mod_meanings, e))
            self._modifier_map = {}
        log("update_modmap(%s)=%s" % (xkbmap_mod_meanings, self._modifier_map))

    def get_gtk_keymap(self):
        return  get_gtk_keymap()

    def get_x11_keymap(self):
        return  {}

    def get_keymap_modifiers(self):
        return  {}, [], []

    def get_keymap_spec(self):
        """ xkbmap_print, xkbmap_query """
        return None,None

    def get_keyboard_repeat(self):
        """ (delay_ms,interval_ms) or None"""
        return None

    def get_tray_tooltip(self):
        if self.client.session_name:
            return "%s\non %s" % (self.client.session_name, self.connection.target)
        return self.connection.target


    def about(self, *args):
        if self.about_dialog:
            self.about_dialog.present()
            return
        dialog = gtk.AboutDialog()
        if not is_gtk3():
            def on_website_hook(dialog, web, *args):
                webbrowser.open("http://xpra.org/")
            def on_email_hook(dialog, mail, *args):
                webbrowser.open("mailto://"+mail)
            gtk.about_dialog_set_url_hook(on_website_hook)
            gtk.about_dialog_set_email_hook(on_email_hook)
            xpra_icon = self.get_pixbuf("xpra.png")
            if xpra_icon:
                dialog.set_icon(xpra_icon)
        dialog.set_name("Xpra")
        from xpra import __version__
        dialog.set_version(__version__)
        dialog.set_copyright('Copyright (c) 2009-2012')
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
        dialog.set_comments("\n".join(get_build_info()))
        dialog.connect("response", self.close_about)
        self.about_dialog = dialog
        dialog.show()
        dialog.present()

    def close_about(self, *args):
        try:
            if self.about_dialog:
                self.about_dialog.destroy()
                self.about_dialog = None
        except:
            log.error("closing about dialog", exc_info=True)


    def session_info(self, *args):
        if self.session_info_window is None:
            #we import here to avoid an import loop
            from xpra.platform.session_info import SessionInfo
            pixbuf = self.get_pixbuf("statistics.png")
            if not pixbuf and self.tray_icon:
                pixbuf = self.get_pixbuf(self.tray_icon)
            self.session_info_window = SessionInfo(self.client, self.session_name, pixbuf, self.connection)
            self.session_info_window.populate_info()
            add_close_accel(self.session_info_window, self.close_session_info)
            gobject.timeout_add(1000, self.session_info_window.populate_info)
            self.session_info_window.show_all()
        self.session_info_window.present()

    def close_session_info(self, *args):
        try:
            if self.session_info_window:
                self.session_info_window.destroy()
                self.session_info_window = None
        except:
            log.error("closing session info", exc_info=True)


    def grok_modifier_map(self, display_source, xkbmap_mod_meanings):
        modifier_map = {
            "shift": 1 << 0,
            "lock": 1 << 1,
            "control": 1 << 2,
            "mod1": 1 << 3,
            "mod2": 1 << 4,
            "mod3": 1 << 5,
            "mod4": 1 << 6,
            "mod5": 1 << 7,
            }
        return modifier_map


    def get_data_dir(self):
        return  os.path.dirname(sys.executable) or os.getcwd()

    def get_icon_filename(self, icon_name):
        dd = self.get_data_dir()
        if dd is None:
            return None
        for icons_path in ("icons", "xpra/icons"):
            filename = os.path.join(dd, icons_path, icon_name)
            if os.path.exists(filename):
                return  filename
        log.error("get_icon_filename(%s) could not be found!", icon_name)
        return  None

    def get_license_text(self):
        if self.license_text:
            return  self.license_text
        filename = os.path.join(self.get_data_dir(), 'COPYING')
        if os.path.exists(filename):
            try:
                if sys.version < '3':
                    license_file = open(filename, mode='rb')
                else:
                    license_file = open(filename, mode='r', encoding='ascii')
                return license_file.read()
            finally:
                license_file.close()
        if not self.license_text:
            self.license_text = "GPL version 2"
        return self.license_text

    def get_pixbuf(self, icon_name):
        try:
            if not icon_name:
                return None
            icon_filename = self.get_icon_filename(icon_name)
            if icon_filename:
                if is_gtk3():
                    from gi.repository.GdkPixbuf import Pixbuf    #@UnresolvedImport
                    return Pixbuf.new_from_file(icon_filename)
                else:
                    return  gdk.pixbuf_new_from_file(icon_filename)
        except:
            log.error("get_image(%s)", icon_name, exc_info=True)
        return  None

    def get_image(self, icon_name, size=None):
        try:
            pixbuf = self.get_pixbuf(icon_name)
            if not pixbuf:
                return  None
            if size:
                if is_gtk3():
                    from gi.repository.GdkPixbuf import InterpType  #@UnresolvedImport
                    interp = InterpType.BILINEAR
                else:
                    interp = gdk.INTERP_BILINEAR
                pixbuf = pixbuf.scale_simple(size, size, interp)
            if is_gtk3():
                return  gtk.Image.new_from_pixbuf(pixbuf)
            return  gtk.image_new_from_pixbuf(pixbuf)
        except:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
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
            if hasattr(menu_item, "set_always_show_image"):
                menu_item.set_always_show_image(True)
        if tooltip:
            set_tooltip_text(menu_item, tooltip)
        if cb:
            menu_item.connect('activate', cb)
        menu_item.show()
        return menu_item

    def checkitem(self, title, cb=None):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = CheckMenuItem(title)
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
        if is_gtk3():
            self.menu.popup(None, None, None, None, button, time)
        else:
            self.menu.popup(None, None, None, button, time, None)
        self.menu_shown = True

    def make_aboutmenuitem(self):
        return  self.menuitem("About Xpra", "information.png", None, self.about)

    def make_sessioninfomenuitem(self):
        title = "Session Info"
        if self.session_name and self.session_name!="Xpra session":
            title = self.session_name
        return  self.menuitem(title, "statistics.png", None, self.session_info)

    def make_bellmenuitem(self):
        def bell_toggled(*args):
            self.client.bell_enabled = self.bell_menuitem.get_active()
            self.client.send_bell_enabled()
            log.debug("bell_toggled(%s) bell_enabled=%s", args, self.client.bell_enabled)
        self.bell_menuitem = self.checkitem("Bell", bell_toggled)
        def set_bell_menuitem(*args):
            self.bell_menuitem.set_active(self.client.bell_enabled)
            c = self.client
            can_toggle_bell = c.toggle_cursors_bell_notify and c.server_supports_bell and c.client_supports_bell
            self.bell_menuitem.set_sensitive(can_toggle_bell)
            if can_toggle_bell:
                set_tooltip_text(self.bell_menuitem, "Forward system bell")
            else:
                set_tooltip_text(self.bell_menuitem, "Cannot forward the system bell: the feature has been disabled")
        self.client.connect("handshake-complete", set_bell_menuitem)
        return  self.bell_menuitem

    def make_cursorsmenuitem(self):
        def cursors_toggled(*args):
            self.client.cursors_enabled = self.cursors_menuitem.get_active()
            self.client.send_cursors_enabled()
            log.debug("cursors_toggled(%s) cursors_enabled=%s", args, self.client.cursors_enabled)
        self.cursors_menuitem = self.checkitem("Cursors", cursors_toggled)
        def set_cursors_menuitem(*args):
            self.cursors_menuitem.set_active(self.client.cursors_enabled)
            c = self.client
            can_toggle_cursors = c.toggle_cursors_bell_notify and c.server_supports_cursors and c.client_supports_cursors
            self.cursors_menuitem.set_sensitive(can_toggle_cursors)
            if can_toggle_cursors:
                set_tooltip_text(self.cursors_menuitem, "Forward custom mouse cursors")
            else:
                set_tooltip_text(self.cursors_menuitem, "Cannot forward mouse cursors: the feature has been disabled")
        self.client.connect("handshake-complete", set_cursors_menuitem)
        return  self.cursors_menuitem

    def make_notificationsmenuitem(self):
        def notifications_toggled(*args):
            self.client.notifications_enabled = self.notifications_menuitem.get_active()
            self.client.send_notify_enabled()
            log.debug("notifications_toggled(%s) notifications_enabled=%s", args, self.client.notifications_enabled)
        self.notifications_menuitem = self.checkitem("Notifications", notifications_toggled)
        def set_notifications_menuitem(*args):
            self.notifications_menuitem.set_active(self.client.notifications_enabled)
            c = self.client
            can_notify = c.toggle_cursors_bell_notify and c.server_supports_notifications and c.client_supports_notifications
            self.notifications_menuitem.set_sensitive(can_notify)
            if can_notify:
                set_tooltip_text(self.notifications_menuitem, "Forward system notifications")
            else:
                set_tooltip_text(self.notifications_menuitem, "Cannot forward system notifications: the feature has been disabled")
        self.client.connect("handshake-complete", set_notifications_menuitem)
        return self.notifications_menuitem

    def make_clipboard_togglemenuitem(self):
        def clipboard_toggled(*args):
            new_state = self.clipboard_menuitem.get_active()
            log.debug("clipboard_toggled(%s) clipboard_enabled=%s, new_state=%s", args, self.client.clipboard_enabled, new_state)
            if self.client.clipboard_enabled!=new_state:
                self.client.clipboard_enabled = new_state
                self.client.emit("clipboard-toggled")
        self.clipboard_menuitem = self.checkitem("Clipboard", clipboard_toggled)
        def set_clipboard_menuitem(*args):
            self.clipboard_menuitem.set_active(self.client.clipboard_enabled)
            c = self.client
            can_clipboard = c.server_supports_clipboard and c.client_supports_clipboard
            self.clipboard_menuitem.set_sensitive(can_clipboard)
            if can_clipboard:
                set_tooltip_text(self.clipboard_menuitem, "Enable clipboard synchronization")
            else:
                set_tooltip_text(self.clipboard_menuitem, "Clipboard synchronization cannot be enabled: disabled by server")
        self.client.connect("handshake-complete", set_clipboard_menuitem)
        return self.clipboard_menuitem

    def make_translatedclipboard_optionsmenuitem(self):
        clipboard_menu = self.menuitem("Clipboard", "clipboard.png", "Choose which remote clipboard to connect to", None)
        clipboard_submenu = gtk.Menu()
        clipboard_menu.set_submenu(clipboard_submenu)
        self.popup_menu_workaround(clipboard_submenu)
        def set_clipboard_menu(*args):
            c = self.client
            can_clipboard = c.server_supports_clipboard and c.client_supports_clipboard
            log("set_clipboard_menu(%s) can_clipboard=%s, server=%s, client=%s", args, can_clipboard, c.server_supports_clipboard, c.client_supports_clipboard)
            clipboard_menu.set_sensitive(can_clipboard)
            LABEL_TO_NAME = {"Disabled"  : None,
                            "Clipboard" : "CLIPBOARD",
                            "Primary"   : "PRIMARY",
                            "Secondary" : "SECONDARY"}
            for label, remote_clipboard in LABEL_TO_NAME.items():
                clipboard_item = CheckMenuItem(label)
                def remote_clipboard_changed(item):
                    item = ensure_item_selected(clipboard_submenu, item)
                    label = item.get_label()
                    remote_clipboard = LABEL_TO_NAME.get(label)
                    old_state = self.client.clipboard_enabled
                    if remote_clipboard:
                        self.clipboard_helper.remote_clipboard = remote_clipboard
                        new_state = True
                    else:
                        new_state = False
                    log("remote_clipboard_changed(%s) label=%s, remote_clipboard=%s, old_state=%s, new_state=%s",
                             item, label, remote_clipboard, old_state, new_state)
                    if new_state!=old_state:
                        self.client.clipboard_enabled = new_state
                        self.client.emit("clipboard-toggled")
                    if new_state:
                        self.clipboard_helper.send_all_tokens()
                clipboard_item.set_active(self.clipboard_helper.remote_clipboard==remote_clipboard)
                clipboard_item.set_sensitive(can_clipboard)
                clipboard_item.set_draw_as_radio(True)
                clipboard_item.connect("toggled", remote_clipboard_changed)
                clipboard_submenu.append(clipboard_item)
            clipboard_submenu.show_all()
        self.client.connect("handshake-complete", set_clipboard_menu)
        return clipboard_menu

    def make_clipboardmenuitem(self):
        try:
            from xpra.platform.gdk_clipboard import TranslatedClipboardProtocolHelper
            if self.clipboard_helper and isinstance(self.clipboard_helper, TranslatedClipboardProtocolHelper):
                return self.make_translatedclipboard_optionsmenuitem()
        except:
            log.error("make_clipboardmenuitem()", exc_info=True)
        return self.make_clipboard_togglemenuitem()


    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip():
            if not self.client.toggle_keyboard_sync:
                set_tooltip_text(self.keyboard_sync_menuitem, "This server does not support changes to keyboard synchronization")
            elif self.client.keyboard_sync:
                set_tooltip_text(self.keyboard_sync_menuitem, "Disable keyboard synchronization (prevents spurious key repeats on high latency connections)")
            else:
                set_tooltip_text(self.keyboard_sync_menuitem, "Enable keyboard state synchronization")
        def keyboard_sync_toggled(*args):
            self.client.keyboard_sync = self.keyboard_sync_menuitem.get_active()
            log.debug("keyboard_sync_toggled(%s) keyboard_sync=%s", args, self.client.keyboard_sync)
            set_keyboard_sync_tooltip()
            self.client.emit("keyboard-sync-toggled")
        self.keyboard_sync_menuitem = self.checkitem("Keyboard Synchronization", keyboard_sync_toggled)
        def set_keyboard_sync_menuitem(*args):
            self.keyboard_sync_menuitem.set_active(self.client.keyboard_sync)
            self.keyboard_sync_menuitem.set_sensitive(self.client.toggle_keyboard_sync)
            set_keyboard_sync_tooltip()
        self.client.connect("handshake-complete", set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_encodingsmenuitem(self):
        encodings = self.menuitem("Encoding", "encoding.png", "Choose picture data encoding", None)
        encodings.set_submenu(self.make_encodingssubmenu())
        def set_encodingsmenuitem(*args):
            if self.client.mmap_enabled:
                #mmap disables encoding and uses raw rgb24
                encodings.set_label("Encoding")
                set_tooltip_text(encodings, "memory mapped transfers are in use so picture encoding is disabled")
                encodings.set_sensitive(False)
        self.client.connect("handshake-complete", set_encodingsmenuitem)
        return encodings

    def make_encodingssubmenu(self):
        self.encodings_submenu = gtk.Menu()
        self.popup_menu_workaround(self.encodings_submenu)
        def set_encodingsmenuitem(*args):
            for encoding in ENCODINGS:
                encoding_item = CheckMenuItem(encoding)
                def encoding_changed(item):
                    item = ensure_item_selected(self.encodings_submenu, item)
                    enc = item.get_label()
                    if self.client.encoding!=enc:
                        self.client.set_encoding(enc)
                        log.debug("setting encoding to %s", enc)
                        self.set_qualitymenu()
                encoding_item.set_active(encoding==self.client.encoding)
                encoding_item.set_sensitive(encoding in self.client.server_capabilities.get("encodings", ["rgb24"]))
                encoding_item.set_draw_as_radio(True)
                encoding_item.set_sensitive(not self.client.mmap_enabled)
                encoding_item.connect("toggled", encoding_changed)
                self.encodings_submenu.append(encoding_item)
            self.encodings_submenu.show_all()
        self.client.connect("handshake-complete", set_encodingsmenuitem)
        return self.encodings_submenu

    def make_qualitymenuitem(self):
        self.quality = self.menuitem("Quality", "slider.png", "Change quality setting", None)
        self.quality.set_submenu(self.make_qualitysubmenu())
        return self.quality

    def make_qualitysubmenu(self):
        self.quality_submenu = gtk.Menu()
        self.popup_menu_workaround(self.quality_submenu)
        quality_options = [-1, 10, 50, 80, 95]
        if self.client.quality>0 and self.client.quality not in quality_options:
            """ add the current value to the list of options """
            i = 0
            for x in quality_options:
                if self.client.quality<x:
                    quality_options.insert(i, self.client.quality)
                    break
                i += 1
        def set_quality(item):
            item = ensure_item_selected(self.quality_submenu, item)
            q = -1
            try:
                q = int(item.get_label().replace("%", ""))
            except:
                pass
            if q!=self.client.quality:
                log.debug("setting quality to %s", q)
                self.client.send_quality(q)
        self.auto_quality = None
        for q in quality_options:
            if q>=0:
                qi = CheckMenuItem("%s%%" % q)
            else:
                self.auto_quality = CheckMenuItem("Auto")
                qi = self.auto_quality
            qi.set_draw_as_radio(True)
            qi.set_active(q==self.client.quality)
            qi.connect('activate', set_quality)
            self.quality_submenu.append(qi)
        self.quality_submenu.show_all()
        self.client.connect("handshake-complete", self.set_qualitymenu)
        return self.quality_submenu

    def set_qualitymenu(self, *args):
        if self.quality:
            self.quality.set_sensitive(not self.client.mmap_enabled and self.client.encoding in ("jpeg", "webp", "x264"))
            is_x264 = self.client.encoding in ("x264")
            self.auto_quality.set_sensitive(is_x264)
            if is_x264:
                self.auto_quality.set_label("Auto")
            else:
                self.auto_quality.set_label("Default")

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
            from xpra.platform.keyboard_layouts import X11_LAYOUTS
            #show all options to choose from:
            sorted_keys = list(X11_LAYOUTS.keys())
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
            if self.client.xkbmap_layout or self.client.xkbmap_print or self.client.xkbmap_query:
                #we have detected a layout
                #so no need to let the user override it
                keyboard.hide()
                return
            layout = self.client.xkbmap_layout
            variant = self.client.xkbmap_variant
            def is_match(checkitem):
                return checkitem.keyboard_layout==layout and checkitem.keyboard_variant==variant
            set_checkeditems(self.layout_submenu, is_match)
        self.client.connect("handshake-complete", set_selected_layout)
        return keyboard

    def make_compressionmenu(self):
        self.compression = self.menuitem("Compression", "compressed.png", "Network packet compression", None)
        self.compression_submenu = gtk.Menu()
        self.compression.set_submenu(self.compression_submenu)
        self.popup_menu_workaround(self.compression_submenu)
        compression_options = {0 : "None"}
        def set_compression(item):
            item = ensure_item_selected(self.compression_submenu, item)
            c = int(item.get_label().replace("None", "0"))
            if c!=self.client.compression_level:
                log.debug("setting compression level to %s", c)
                self.client.set_deflate_level(c)
        for i in range(0, 10):
            c = CheckMenuItem(str(compression_options.get(i, i)))
            c.set_draw_as_radio(True)
            c.set_active(i==self.client.compression_level)
            c.connect('activate', set_compression)
            self.compression_submenu.append(c)
        self.compression_submenu.show_all()
        return self.compression


    def make_refreshmenuitem(self):
        def force_refresh(*args):
            log.debug("force refresh")
            self.client.send_refresh_all()
        return self.menuitem("Refresh", "retry.png", None, force_refresh)

    def make_raisewindowsmenuitem(self):
        def raise_windows(*args):
            for win in self.client._window_to_id.keys():
                if not win._override_redirect:
                    win.present()
        return self.menuitem("Raise Windows", "raise.png", None, raise_windows)

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
        if self.client.windows_enabled:
            menu.append(self.make_cursorsmenuitem())
        menu.append(self.make_notificationsmenuitem())
        if not self.client.readonly:
            menu.append(self.make_clipboardmenuitem())
        if self.client.windows_enabled and len(ENCODINGS)>1:
            menu.append(self.make_encodingsmenuitem())
        else:
            self.encodings_submenu = None
        lossy_encodings = set(ENCODINGS) & set(["jpeg", "webp", "x264", "vpx"])
        if self.client.windows_enabled and len(lossy_encodings)>0:
            menu.append(self.make_qualitymenuitem())
        else:
            self.quality = None
            self.quality_submenu = None
        if SHOW_COMPRESSION_MENU:
            menu.append(self.make_compressionmenu())
        if not self.client.readonly:
            menu.append(self.make_layoutsmenuitem())
        if self.client.windows_enabled and not self.client.readonly:
            menu.append(self.make_keyboardsyncmenuitem())
        if self.client.windows_enabled:
            menu.append(self.make_refreshmenuitem())
            menu.append(self.make_raisewindowsmenuitem())
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

