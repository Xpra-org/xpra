# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.gtk_common.gobject_compat import import_gtk, import_gobject
gtk = import_gtk()
gobject = import_gobject()

from xpra.gtk_common.gtk_util import set_tooltip_text, CheckMenuItem, ensure_item_selected, set_checkeditems, menuitem
from xpra.client.gtk_base.about import about, close_about
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, ENCODINGS_HELP, ENCODINGS_TO_NAME
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_TRAY_DEBUG")


#compression is fine with default value (3), no need to clutter the UI
SHOW_COMPRESSION_MENU = False
STARTSTOP_SOUND_MENU = os.environ.get("XPRA_SHOW_SOUND_MENU", "1")=="1"

LOSSLESS = "Lossless"
QUALITY_OPTIONS_COMMON = {
                50      : "Average",
                30      : "Low",
                }
MIN_QUALITY_OPTIONS = QUALITY_OPTIONS_COMMON.copy()
MIN_QUALITY_OPTIONS[0] = "None"
QUALITY_OPTIONS = QUALITY_OPTIONS_COMMON.copy()
QUALITY_OPTIONS[0]  = "Auto"
QUALITY_OPTIONS[1]  = "Lowest"
QUALITY_OPTIONS[90]  = "Best"
QUALITY_OPTIONS[100]  = LOSSLESS


SPEED_OPTIONS_COMMON = {
                70      : "Low Latency",
                30      : "Low Bandwidth",
                }
MIN_SPEED_OPTIONS = SPEED_OPTIONS_COMMON.copy()
MIN_SPEED_OPTIONS[0] = "None"
SPEED_OPTIONS = SPEED_OPTIONS_COMMON.copy()
SPEED_OPTIONS[0]    = "Auto"
SPEED_OPTIONS[1]    = "Lowest Bandwidth"
SPEED_OPTIONS[100]  = "Lowest Latency"


def make_min_auto_menu(title, min_options, options, get_current_min_value, get_current_value, set_min_value_cb, set_value_cb):
    #note: we must keep references to the parameters on the submenu
    #(closures and gtk callbacks don't mix so well!)
    submenu = gtk.Menu()
    submenu.get_current_min_value = get_current_min_value
    submenu.get_current_value = get_current_value
    submenu.set_min_value_cb = set_min_value_cb
    submenu.set_value_cb = set_value_cb
    fstitle = gtk.MenuItem("Fixed %s:" % title)
    fstitle.set_sensitive(False)
    submenu.append(fstitle)
    submenu.menu_items = {}
    submenu.min_menu_items = {}
    def populate_menu(options, value, set_fn):
        found_match = False
        items = {}
        if value and value>0 and value not in options:
            options[value] = "%s%%" % value
        for s in sorted(options.keys()):
            t = options.get(s)
            qi = CheckMenuItem(t)
            qi.set_draw_as_radio(True)
            candidate_match = s>=max(0, value)
            qi.set_active(not found_match and candidate_match)
            found_match |= candidate_match
            qi.connect('activate', set_fn, submenu)
            if s>0:
                set_tooltip_text(qi, "%s%%" % s)
            submenu.append(qi)
            items[s] = qi
        return items
    def set_value(item, ss):
        if not item.get_active():
            return
        #user select a new value from the menu:
        s = -1
        for ts,tl in options.items():
            if tl==item.get_label():
                s = ts
                break
        if s>=0 and s!=ss.get_current_value():
            debug("setting %s to %s", title, s)
            ss.set_value_cb(s)
            #deselect other items:
            for x in ss.menu_items.values():
                if x!=item:
                    x.set_active(False)
            #min is only relevant in auto-mode:
            if s!=0:
                for v,x in ss.min_menu_items.items():
                    x.set_active(v==0)
    submenu.menu_items.update(populate_menu(options, get_current_value(), set_value))
    submenu.append(gtk.SeparatorMenuItem())
    mstitle = gtk.MenuItem("Minimum %s:" % title)
    mstitle.set_sensitive(False)
    submenu.append(mstitle)
    def set_min_value(item, ss):
        if not item.get_active():
            return
        #user selected a new min-value from the menu:
        s = -1
        for ts,tl in min_options.items():
            if tl==item.get_label():
                s = ts
                break
        if s>=0 and s!=ss.get_current_min_value():
            debug("setting min-%s to %s", title, s)
            ss.set_min_value_cb(s)
            #deselect other min items:
            for x in ss.min_menu_items.values():
                if x!=item:
                    x.set_active(False)
            #min requires auto-mode:
            for x in ss.menu_items.values():
                if x.get_label()=="Auto":
                    if not x.get_active():
                        x.activate()
                else:
                    x.set_active(False)
    mv = -1
    if get_current_value()<=0:
        mv = get_current_min_value()
    submenu.min_menu_items.update(populate_menu(min_options, mv, set_min_value))
    submenu.show_all()
    return submenu

def make_encodingsmenu(get_current_encoding, set_encoding, encodings, server_encodings):
    encodings_submenu = gtk.Menu()
    populate_encodingsmenu(encodings_submenu, get_current_encoding, set_encoding, encodings, server_encodings)
    return encodings_submenu

def populate_encodingsmenu(encodings_submenu, get_current_encoding, set_encoding, encodings, server_encodings):
    encodings_submenu.get_current_encoding = get_current_encoding
    encodings_submenu.set_encoding = set_encoding
    encodings_submenu.encodings = encodings
    encodings_submenu.server_encodings = server_encodings
    encodings_submenu.index_to_encoding = {}
    encodings_submenu.encoding_to_index = {}
    NAME_TO_ENCODING = {}
    i = 0
    for encoding in encodings:
        name = ENCODINGS_TO_NAME.get(encoding, encoding)
        descr = ENCODINGS_HELP.get(encoding)
        NAME_TO_ENCODING[name] = encoding
        encoding_item = CheckMenuItem(name)
        if descr:
            if encoding not in server_encodings:
                descr += "\n(not available on this server)"
            set_tooltip_text(encoding_item, descr)
        def encoding_changed(oitem):
            debug("encoding_changed(%s)", oitem)
            item = ensure_item_selected(encodings_submenu, oitem)
            enc = NAME_TO_ENCODING.get(item.get_label())
            debug("encoding_changed(%s) item=%s, enc=%s, current=%s", oitem, item, enc, encodings_submenu.get_current_encoding())
            if enc is not None and encodings_submenu.get_current_encoding()!=enc:
                encodings_submenu.set_encoding(enc)
        debug("make_encodingsmenu(..) encoding=%s, current=%s, active=%s", encoding, get_current_encoding(), encoding==get_current_encoding())
        encoding_item.set_active(encoding==get_current_encoding())
        encoding_item.set_sensitive(encoding in server_encodings)
        encoding_item.set_draw_as_radio(True)
        encoding_item.connect("toggled", encoding_changed)
        encodings_submenu.append(encoding_item)
        encodings_submenu.index_to_encoding[i] = encoding
        encodings_submenu.encoding_to_index[encoding] = i
        i += 1
    encodings_submenu.show_all()


class GTKTrayMenuBase(object):

    def __init__(self, client):
        self.client = client
        self.session_info = None
        self.menu = None
        self.menu_shown = False

    def build(self):
        if self.menu is None:
            show_close = True #or sys.platform.startswith("win")
            self.menu = self.setup_menu(show_close)
        return self.menu

    def show_session_info(self, *args):
        self.client.show_session_info(*args)

    def get_image(self, *args):
        return self.client.get_image(*args)

    def setup_menu(self, show_close=True):
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
        if self.client.opengl_enabled:
            menu.append(self.make_openglmenuitem())
        if self.client.windows_enabled and len(self.client.get_encodings())>1:
            menu.append(self.make_encodingsmenuitem())
        menu.append(self.make_qualitymenuitem())
        menu.append(self.make_speedmenuitem())
        if self.client.speaker_allowed and STARTSTOP_SOUND_MENU:
            menu.append(self.make_speakermenuitem())
        if self.client.microphone_allowed and STARTSTOP_SOUND_MENU:
            menu.append(self.make_microphonemenuitem())
        if SHOW_COMPRESSION_MENU:
            menu.append(self.make_compressionmenu())
        if not self.client.readonly and self.client.keyboard_helper:
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
        return menu

    def cleanup(self):
        debug("cleanup() session_info=%s", self.session_info)
        if self.session_info:
            self.session_info.destroy()
            self.session_info = None
        self.close_menu()
        close_about()

    def close_menu(self, *args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *args):
        self.menu_shown = False

    def activate(self):
        self.show_menu(1, 0)

    def popup(self, button, time):
        self.show_menu(button, time)

    def show_menu(self, button, time):
        raise Exception("override me!")


    def handshake_menuitem(self, *args, **kwargs):
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        mi.set_sensitive(False)
        def enable_menuitem(*args):
            mi.set_sensitive(True)
        self.client.connect("handshake-complete", enable_menuitem)
        return mi

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        image = None
        if icon_name:
            image = self.get_image(icon_name, 24)
        return menuitem(title, image, tooltip, cb)

    def checkitem(self, title, cb=None):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = CheckMenuItem(title)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item



    def make_aboutmenuitem(self):
        return  self.menuitem("About Xpra", "information.png", None, about)

    def make_sessioninfomenuitem(self):
        title = "Session Info"
        if self.client.session_name and self.client.session_name!="Xpra session":
            title = "Info: %s"  % self.client.session_name
        def show_session_info_cb(*args):
            #we define a generic callback to remove the arguments
            #(which contain the menu widget and are of no interest to the 'show_session_info' function)
            self.show_session_info()
        return  self.handshake_menuitem(title, "statistics.png", None, show_session_info_cb)

    def make_bellmenuitem(self):
        def bell_toggled(*args):
            v = self.bell_menuitem.get_active()
            changed = self.client.bell_enabled != v
            self.client.bell_enabled = v
            if changed and self.client.toggle_cursors_bell_notify:
                self.client.send_bell_enabled()
            debug("bell_toggled(%s) bell_enabled=%s", args, self.client.bell_enabled)
        self.bell_menuitem = self.checkitem("Bell", bell_toggled)
        self.bell_menuitem.set_sensitive(False)
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
            v = self.cursors_menuitem.get_active()
            changed = self.client.cursors_enabled != v
            self.client.cursors_enabled = v
            if changed and self.client.toggle_cursors_bell_notify:
                self.client.send_cursors_enabled()
            if not self.client.cursors_enabled:
                self.client.reset_cursor()
            debug("cursors_toggled(%s) cursors_enabled=%s", args, self.client.cursors_enabled)
        self.cursors_menuitem = self.checkitem("Cursors", cursors_toggled)
        self.cursors_menuitem.set_sensitive(False)
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
            v = self.notifications_menuitem.get_active()
            changed = self.client.notifications_enabled != v
            self.client.notifications_enabled = v
            if changed and self.client.toggle_cursors_bell_notify:
                self.client.send_notify_enabled()
            debug("notifications_toggled(%s) notifications_enabled=%s", args, self.client.notifications_enabled)
        self.notifications_menuitem = self.checkitem("Notifications", notifications_toggled)
        self.notifications_menuitem.set_sensitive(False)
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
        def menu_clipboard_toggled(*args):
            new_state = self.clipboard_menuitem.get_active()
            debug("clipboard_toggled(%s) clipboard_enabled=%s, new_state=%s", args, self.client.clipboard_enabled, new_state)
            if self.client.clipboard_enabled!=new_state:
                self.client.clipboard_enabled = new_state
                self.client.emit("clipboard-toggled")
        self.clipboard_menuitem = self.checkitem("Clipboard", menu_clipboard_toggled)
        self.clipboard_menuitem.set_sensitive(False)
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
        def clipboard_toggled(*args):
            #keep menu in sync with actual "clipboard_enabled" flag:
            if self.client.clipboard_enabled != self.clipboard_menuitem.get_active():
                self.clipboard_menuitem.set_active(self.client.clipboard_enabled)
        self.client.connect("clipboard-toggled", clipboard_toggled)
        return self.clipboard_menuitem

    def make_translatedclipboard_optionsmenuitem(self):
        clipboard_menu = self.menuitem("Clipboard", "clipboard.png", "Choose which remote clipboard to connect to", None)
        clipboard_menu.set_sensitive(False)
        def set_clipboard_menu(*args):
            clipboard_submenu = gtk.Menu()
            clipboard_menu.set_submenu(clipboard_submenu)
            self.popup_menu_workaround(clipboard_submenu)
            c = self.client
            can_clipboard = c.server_supports_clipboard and c.client_supports_clipboard and c.server_supports_clipboard
            debug("set_clipboard_menu(%s) can_clipboard=%s, server=%s, client=%s", args, can_clipboard, c.server_supports_clipboard, c.client_supports_clipboard)
            clipboard_menu.set_sensitive(can_clipboard)
            LABEL_TO_NAME = {"Disabled"  : None,
                            "Clipboard" : "CLIPBOARD",
                            "Primary"   : "PRIMARY",
                            "Secondary" : "SECONDARY"}
            from xpra.clipboard.translated_clipboard import TranslatedClipboardProtocolHelper
            for label, remote_clipboard in LABEL_TO_NAME.items():
                clipboard_item = CheckMenuItem(label)
                def remote_clipboard_changed(item):
                    assert can_clipboard
                    item = ensure_item_selected(clipboard_submenu, item)
                    label = item.get_label()
                    remote_clipboard = LABEL_TO_NAME.get(label)
                    old_state = self.client.clipboard_enabled
                    debug("remote_clipboard_changed(%s) remote_clipboard=%s, old_state=%s", item, remote_clipboard, old_state)
                    send_tokens = False
                    if remote_clipboard is not None:
                        #clipboard is not disabled
                        if self.client.clipboard_helper is None:
                            self.client.setup_clipboard_helper(TranslatedClipboardProtocolHelper)
                        self.client.clipboard_helper.remote_clipboard = remote_clipboard
                        send_tokens = True
                        new_state = True
                    else:
                        self.client.clipboard_helper = None
                        send_tokens = False
                        new_state = False
                    debug("remote_clipboard_changed(%s) label=%s, remote_clipboard=%s, old_state=%s, new_state=%s",
                             item, label, remote_clipboard, old_state, new_state)
                    if new_state!=old_state:
                        self.client.clipboard_enabled = new_state
                        self.client.emit("clipboard-toggled")
                        send_tokens = True
                    if send_tokens and self.client.clipboard_helper:
                        self.client.clipboard_helper.send_all_tokens()
                active = isinstance(self.client.clipboard_helper, TranslatedClipboardProtocolHelper) \
                            and self.client.clipboard_helper.remote_clipboard==remote_clipboard
                clipboard_item.set_active(active)
                clipboard_item.set_sensitive(can_clipboard)
                clipboard_item.set_draw_as_radio(True)
                clipboard_item.connect("toggled", remote_clipboard_changed)
                clipboard_submenu.append(clipboard_item)
            clipboard_submenu.show_all()
        self.client.connect("handshake-complete", set_clipboard_menu)
        return clipboard_menu

    def make_clipboardmenuitem(self):
        try:
            if self.client.clipboard_helper:
                from xpra.clipboard.translated_clipboard import TranslatedClipboardProtocolHelper
                if isinstance(self.client.clipboard_helper, TranslatedClipboardProtocolHelper):
                    return self.make_translatedclipboard_optionsmenuitem()
        except:
            log.error("make_clipboardmenuitem()", exc_info=True)
        return self.make_clipboard_togglemenuitem()


    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip():
            if not self.client.keyboard_helper:
                set_tooltip_text(self.keyboard_sync_menuitem, "Keyboard support is not loaded")
            elif not self.client.toggle_keyboard_sync:
                set_tooltip_text(self.keyboard_sync_menuitem, "This server does not support changes to keyboard synchronization")
            elif self.client.keyboard_helper.keyboard_sync:
                set_tooltip_text(self.keyboard_sync_menuitem, "Disable keyboard synchronization (prevents spurious key repeats on high latency connections)")
            else:
                set_tooltip_text(self.keyboard_sync_menuitem, "Enable keyboard state synchronization")
        def keyboard_sync_toggled(*args):
            self.client.keyboard_sync = self.keyboard_sync_menuitem.get_active()
            debug("keyboard_sync_toggled(%s) keyboard_sync=%s", args, self.client.keyboard_sync)
            set_keyboard_sync_tooltip()
            self.client.emit("keyboard-sync-toggled")
        self.keyboard_sync_menuitem = self.checkitem("Keyboard Synchronization", keyboard_sync_toggled)
        self.keyboard_sync_menuitem.set_sensitive(False)
        def set_keyboard_sync_menuitem(*args):
            self.keyboard_sync_menuitem.set_active(self.client.keyboard_helper.keyboard_sync)
            self.keyboard_sync_menuitem.set_sensitive(self.client.toggle_keyboard_sync)
            set_keyboard_sync_tooltip()
        self.client.connect("handshake-complete", set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_openglmenuitem(self):
        gl = self.checkitem("OpenGL")
        def gl_set(*args):
            debug("gl_set(%s) opengl_enabled=%s, window_unmap=%s", args, self.client.opengl_enabled, self.client.window_unmap)
            gl.set_active(self.client.opengl_enabled)
            gl.set_sensitive(self.client.window_unmap)
            if not self.client.window_unmap:
                set_tooltip_text(gl, "no server support for runtime switching")
                return
            def opengl_toggled(*args):
                self.client.toggle_opengl()
            gl.connect("toggled", opengl_toggled)
        self.client.connect("handshake-complete", gl_set)
        return gl

    def make_encodingsmenuitem(self):
        encodings = self.menuitem("Encoding", "encoding.png", "Choose picture data encoding", None)
        encodings.set_sensitive(False)
        def set_encodingsmenuitem(*args):
            encodings.set_sensitive(not self.client.mmap_enabled)
            if self.client.mmap_enabled:
                #mmap disables encoding and uses raw rgb24
                encodings.set_label("Encoding")
                set_tooltip_text(encodings, "memory mapped transfers are in use so picture encoding is disabled")
            else:
                encodings.set_submenu(self.make_encodingssubmenu())
        self.client.connect("handshake-complete", set_encodingsmenuitem)
        return encodings

    def make_encodingssubmenu(self, handshake_complete=True):
        encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
        encodings_submenu = make_encodingsmenu(self.get_current_encoding, self.set_current_encoding, encodings, self.client.server_encodings)
        self.popup_menu_workaround(encodings_submenu)
        return encodings_submenu

    def get_current_encoding(self):
        return self.client.encoding
    def set_current_encoding(self, enc):
        self.client.set_encoding(enc)
        #these menus may need updating now:
        self.set_qualitymenu()
        self.set_speedmenu()

    def reset_encoding_options(self, encodings_menu):
        for x in encodings_menu.get_children():
            if isinstance(x, gtk.CheckMenuItem):
                encoding = x.get_label()
                active = encoding==self.client.encoding
                if active!=x.get_active():
                    x.set_active(active)
                x.set_sensitive(encoding in self.client.server_encodings)


    def make_qualitymenuitem(self):
        self.quality = self.menuitem("Quality", "slider.png", "Picture quality", None)
        self.quality.set_sensitive(False)
        def may_enable_qualitymenu(*args):
            self.quality.set_submenu(self.make_qualitysubmenu())
            self.set_qualitymenu()
        self.client.connect("handshake-complete", may_enable_qualitymenu)
        return self.quality

    def make_qualitysubmenu(self):
        quality_submenu = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                           self.get_min_quality, self.get_quality, self.set_min_quality, self.set_quality)
        #WARNING: this changes "min-quality", not "quality" (or at least it tries to..)
        self.popup_menu_workaround(quality_submenu)
        quality_submenu.show_all()
        return quality_submenu

    def get_min_quality(self):
        return self.client.min_quality
    def get_quality(self):
        return self.client.quality
    def set_min_quality(self, q):
        self.client.min_quality = q
        self.client.quality = 0
        self.client.send_min_quality()
        self.client.send_quality()
    def set_quality(self, q):
        self.client.min_quality = 0
        self.client.quality = q
        self.client.send_min_quality()
        self.client.send_quality()

    def set_qualitymenu(self, *args):
        if self.quality:
            can_use = not self.client.mmap_enabled and self.client.encoding in self.client.server_encodings_with_quality
            self.quality.set_sensitive(can_use)
            if not can_use:
                set_tooltip_text(self.quality, "Not supported with %s encoding" % self.client.encoding)
                return
            set_tooltip_text(self.quality, "Minimum picture quality")
            #now check if lossless is supported:
            if self.quality.get_submenu():
                can_lossless = self.client.encoding in self.client.server_encodings_with_lossless_mode
                for q,item in self.quality.get_submenu().menu_items.items():
                    item.set_sensitive(q<100 or can_lossless)


    def make_speedmenuitem(self):
        self.speed = self.menuitem("Speed", "speed.png", "Encoding latency vs size", None)
        self.speed.set_sensitive(False)
        def may_enable_speedmenu(*args):
            self.speed.set_submenu(self.make_speedsubmenu())
            self.set_speedmenu()
        self.client.connect("handshake-complete", may_enable_speedmenu)
        return self.speed

    def make_speedsubmenu(self):
        speed_submenu = make_min_auto_menu("Speed", MIN_SPEED_OPTIONS, SPEED_OPTIONS,
                                           self.get_min_speed, self.get_speed, self.set_min_speed, self.set_speed)
        self.popup_menu_workaround(speed_submenu)
        return speed_submenu

    def get_min_speed(self):
        return self.client.min_speed
    def get_speed(self):
        return self.client.speed
    def set_min_speed(self, s):
        self.client.min_speed = s
        self.client.speed = 0
        self.client.send_min_speed()
        self.client.send_speed()
    def set_speed(self, s):
        self.client.min_speed = 0
        self.client.speed = s
        self.client.send_min_speed()
        self.client.send_speed()


    def set_speedmenu(self, *args):
        if self.speed:
            can_use = not self.client.mmap_enabled and self.client.encoding in self.client.server_encodings_with_speed and self.client.change_speed
            self.speed.set_sensitive(can_use)
            if self.client.mmap_enabled:
                set_tooltip_text(self.speed, "Quality is always 100% with mmap")
            elif not self.client.change_speed:
                set_tooltip_text(self.speed, "Server does not support changing speed")
            elif self.client.encoding!="h264":
                set_tooltip_text(self.speed, "Not supported with %s encoding" % self.client.encoding)
            else:
                set_tooltip_text(self.speed, "Encoding latency vs size")


    def spk_on(self, *args):
        debug("spk_on(%s)", args)
        self.client.start_receiving_sound()
    def spk_off(self, *args):
        debug("spk_off(%s)", args)
        self.client.stop_receiving_sound()
    def make_speakermenuitem(self):
        speaker = self.menuitem("Speaker", "speaker.png", "Forward sound output from the server")
        speaker.set_sensitive(False)
        def is_speaker_on(*args):
            return self.client.speaker_enabled
        def speaker_state(*args):
            if not self.client.server_sound_send:
                speaker.set_sensitive(False)
                set_tooltip_text(speaker, "Server does not support speaker forwarding")
                return
            speaker.set_sensitive(True)
            speaker.set_submenu(self.make_soundsubmenu(is_speaker_on, self.spk_on, self.spk_off, "speaker-changed"))
        self.client.connect("handshake-complete", speaker_state)
        return speaker

    def mic_on(self, *args):
        debug("mic_on(%s)", args)
        self.client.start_sending_sound()
    def mic_off(self, *args):
        debug("mic_off(%s)", args)
        self.client.stop_sending_sound()
    def make_microphonemenuitem(self):
        microphone = self.menuitem("Microphone", "microphone.png", "Forward sound input to the server", None)
        microphone.set_sensitive(False)
        def is_microphone_on(*args):
            return self.client.microphone_enabled
        def microphone_state(*args):
            if not self.client.server_sound_receive:
                microphone.set_sensitive(False)
                set_tooltip_text(microphone, "Server does not support microphone forwarding")
                return
            microphone.set_sensitive(True)
            microphone.set_submenu(self.make_soundsubmenu(is_microphone_on, self.mic_on, self.mic_off, "microphone-changed"))
        self.client.connect("handshake-complete", microphone_state)
        return microphone

    def make_soundsubmenu(self, is_on_cb, on_cb, off_cb, client_signal):
        menu = gtk.Menu()
        menu.ignore_events = False
        def onoffitem(label, active, cb):
            c = CheckMenuItem(label)
            c.set_draw_as_radio(True)
            c.set_active(active)
            def submenu_uncheck(item, menu):
                if not menu.ignore_events:
                    ensure_item_selected(menu, item)
            c.connect('activate', submenu_uncheck, menu)
            def check_enabled(item):
                if not menu.ignore_events and item.get_active():
                    cb()
            c.connect('activate', check_enabled)
            return c
        is_on = is_on_cb()
        on = onoffitem("On", is_on, on_cb)
        off = onoffitem("Off", not is_on, off_cb)
        menu.append(on)
        menu.append(off)
        def client_signalled_change(obj):
            menu.ignore_events = True
            is_on = is_on_cb()
            debug("sound: client_signalled_change(%s) is_on=%s", obj, is_on)
            if is_on:
                if not on.get_active():
                    on.set_active(True)
                    ensure_item_selected(menu, on)
            else:
                if not off.get_active():
                    off.set_active(True)
                    ensure_item_selected(menu, off)
            menu.ignore_events = False
        self.client.connect(client_signal, client_signalled_change)
        #menu.append(gtk.SeparatorMenuItem())
        #...
        self.popup_menu_workaround(menu)
        menu.show_all()
        return menu

    def make_layoutsmenuitem(self):
        keyboard = self.menuitem("Keyboard", "keyboard.png", "Select your keyboard layout", None)
        keyboard.set_sensitive(False)
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
                    debug("keyboard layout selected: %s / %s", layout, variant)
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
        layout,variant,variants = self.client.keyboard_helper.keyboard.get_layout_spec()
        if layout and len(variants)>1:
            #just show all the variants to choose from this layout
            self.layout_submenu.append(kbitem("%s - Default" % layout, layout, None))
            for v in variants:
                self.layout_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
        else:
            from xpra.keyboard.layouts import X11_LAYOUTS
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
        keyboard_helper = self.client.keyboard_helper
        def set_selected_layout(*args):
            if keyboard_helper.xkbmap_layout or keyboard_helper.xkbmap_print or keyboard_helper.xkbmap_query:
                #we have detected a layout
                #so no need to let the user override it
                keyboard.hide()
                return
            keyboard.set_sensitive(True)
            layout = keyboard_helper.xkbmap_layout
            variant = keyboard_helper.xkbmap_variant
            def is_match(checkitem):
                return checkitem.keyboard_layout==layout and checkitem.keyboard_variant==variant
            set_checkeditems(self.layout_submenu, is_match)
        self.client.connect("handshake-complete", set_selected_layout)
        return keyboard

    def make_compressionmenu(self):
        self.compression = self.menuitem("Compression", "compressed.png", "Network packet compression", None)
        self.compression.set_sensitive(False)
        self.compression_submenu = gtk.Menu()
        self.compression.set_submenu(self.compression_submenu)
        self.popup_menu_workaround(self.compression_submenu)
        compression_options = {0 : "None"}
        def set_compression(item):
            item = ensure_item_selected(self.compression_submenu, item)
            c = int(item.get_label().replace("None", "0"))
            if c!=self.client.compression_level:
                debug("setting compression level to %s", c)
                self.client.set_deflate_level(c)
        for i in range(0, 10):
            c = CheckMenuItem(str(compression_options.get(i, i)))
            c.set_draw_as_radio(True)
            c.set_active(i==self.client.compression_level)
            c.connect('activate', set_compression)
            self.compression_submenu.append(c)
        def enable_compressionmenu(self):
            self.compression.set_sensitive(True)
            self.compression_submenu.show_all()
        self.client.connect("handshake-complete", enable_compressionmenu)
        return self.compression


    def make_refreshmenuitem(self):
        def force_refresh(*args):
            debug("force refresh")
            self.client.send_refresh_all()
        return self.handshake_menuitem("Refresh", "retry.png", None, force_refresh)

    def make_raisewindowsmenuitem(self):
        def raise_windows(*args):
            for win in self.client._window_to_id.keys():
                if not win.is_OR():
                    win.present()
        return self.handshake_menuitem("Raise Windows", "raise.png", None, raise_windows)

    def make_disconnectmenuitem(self):
        def menu_quit(*args):
            self.client.quit(0)
        return self.handshake_menuitem("Disconnect", "quit.png", None, menu_quit)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)


    def popup_menu_workaround(self, menu):
        #win32 workaround:
        if sys.platform.startswith("win"):
            self.add_popup_menu_workaround(menu)

    def add_popup_menu_workaround(self, menu):
        """ windows does not automatically close the popup menu when we click outside it
            so we workaround it by using a timer and closing the menu when the mouse
            has stayed outside it for more than 0.5s.
            This code must be added to all the sub-menus of the popup menu too!
        """
        def enter_menu(*args):
            debug("mouse_in_tray_menu=%s", self.mouse_in_tray_menu)
            self.mouse_in_tray_menu_counter += 1
            self.mouse_in_tray_menu = True
        def leave_menu(*args):
            debug("mouse_in_tray_menu=%s", self.mouse_in_tray_menu)
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
        debug("popup_menu_workaround: adding events callbacks")
        menu.connect("enter-notify-event", enter_menu)
        menu.connect("leave-notify-event", leave_menu)
