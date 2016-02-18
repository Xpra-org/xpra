# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.gtk_common.gobject_compat import import_gtk, import_glib
gtk = import_gtk()
glib = import_glib()

from xpra.util import CLIENT_EXIT, iround
from xpra.os_util import bytestostr
from xpra.gtk_common.gtk_util import ensure_item_selected, menuitem, popup_menu_workaround, CheckMenuItem
from xpra.client.client_base import EXIT_OK
from xpra.gtk_common.about import about, close_about
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, ENCODINGS_HELP, ENCODINGS_TO_NAME
from xpra.platform.gui import get_icon_size

from xpra.log import Logger
log = Logger("menu")
clipboardlog = Logger("menu", "clipboard")
webcamlog = Logger("menu", "webcam")


HIDE_DISABLED_MENU_ENTRIES = sys.platform.startswith("darwin")

#compression is fine with default value (3), no need to clutter the UI
SHOW_COMPRESSION_MENU = False
STARTSTOP_SOUND_MENU = os.environ.get("XPRA_SHOW_SOUND_MENU", "1")=="1"
WEBCAM_MENU = os.environ.get("XPRA_SHOW_WEBCAM_MENU", "1")=="1"

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


def set_sensitive(widget, sensitive):
    if sys.platform.startswith("darwin"):
        if sensitive:
            widget.show()
        else:
            widget.hide()
    widget.set_sensitive(sensitive)


def make_min_auto_menu(title, min_options, options, get_current_min_value, get_current_value, set_min_value_cb, set_value_cb):
    #note: we must keep references to the parameters on the submenu
    #(closures and gtk callbacks don't mix so well!)
    submenu = gtk.Menu()
    submenu.get_current_min_value = get_current_min_value
    submenu.get_current_value = get_current_value
    submenu.set_min_value_cb = set_min_value_cb
    submenu.set_value_cb = set_value_cb
    fstitle = gtk.MenuItem("Fixed %s:" % title)
    set_sensitive(fstitle, False)
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
                qi.set_tooltip_text("%s%%" % s)
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
            log("setting %s to %s", title, s)
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
    set_sensitive(mstitle, False)
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
            log("setting min-%s to %s", title, s)
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
    for i, encoding in enumerate(encodings):
        name = ENCODINGS_TO_NAME.get(encoding, encoding)
        descr = ENCODINGS_HELP.get(encoding)
        NAME_TO_ENCODING[name] = encoding
        encoding_item = CheckMenuItem(name)
        if descr:
            if encoding not in server_encodings:
                descr += "\n(not available on this server)"
            encoding_item.set_tooltip_text(descr)
        def encoding_changed(item):
            ensure_item_selected(encodings_submenu, item)
            enc = NAME_TO_ENCODING.get(item.get_label())
            log("encoding_changed(%s) enc=%s, current=%s", item, enc, encodings_submenu.get_current_encoding())
            if enc is not None and encodings_submenu.get_current_encoding()!=enc:
                encodings_submenu.set_encoding(enc)
        log("make_encodingsmenu(..) encoding=%s, current=%s, active=%s", encoding, get_current_encoding(), encoding==get_current_encoding())
        encoding_item.set_active(encoding==get_current_encoding())
        sensitive = encoding in server_encodings
        if not sensitive and HIDE_DISABLED_MENU_ENTRIES:
            continue
        set_sensitive(encoding_item, encoding in server_encodings)
        encoding_item.set_draw_as_radio(True)
        encoding_item.connect("toggled", encoding_changed)
        encodings_submenu.append(encoding_item)
        encodings_submenu.index_to_encoding[i] = encoding
        encodings_submenu.encoding_to_index[encoding] = i
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

    def show_bug_report(self, *args):
        self.client.show_bug_report(*args)


    def get_image(self, *args):
        return self.client.get_image(*args)

    def setup_menu(self, show_close=True):
        self.menu_shown = False
        menu = gtk.Menu()
        menu.set_title(self.client.session_name or "Xpra")
        def set_menu_title(*args):
            #set the real name when available:
            self.menu.set_title(self.client.session_name)
        self.client.after_handshake(set_menu_title)

        menu.append(self.make_aboutmenuitem())
        menu.append(self.make_sessioninfomenuitem())
        menu.append(self.make_bugreportmenuitem())
        menu.append(gtk.SeparatorMenuItem())
        menu.append(self.make_bellmenuitem())
        menu.append(self.make_notificationsmenuitem())
        if self.client.windows_enabled:
            menu.append(self.make_cursorsmenuitem())
        if self.client.client_supports_opengl:
            menu.append(self.make_openglmenuitem())
        if self.client.windows_enabled and not self.client.readonly:
            menu.append(self.make_keyboardsyncmenuitem())
        if not self.client.readonly and self.client.keyboard_helper:
            menu.append(self.make_layoutsmenuitem())
        if not self.client.readonly:
            menu.append(self.make_clipboardmenuitem())
        if self.client.windows_enabled and len(self.client.get_encodings())>1:
            menu.append(self.make_encodingsmenuitem())
        if self.client.can_scale:
            menu.append(self.make_scalingmenuitem())
        menu.append(self.make_qualitymenuitem())
        menu.append(self.make_speedmenuitem())
        if STARTSTOP_SOUND_MENU:
            menu.append(self.make_speakermenuitem())
        if STARTSTOP_SOUND_MENU:
            menu.append(self.make_microphonemenuitem())
        if WEBCAM_MENU:
            menu.append(self.make_webcammenuitem())
        if SHOW_COMPRESSION_MENU:
            menu.append(self.make_compressionmenu())
        if self.client.windows_enabled:
            menu.append(self.make_refreshmenuitem())
            menu.append(self.make_raisewindowsmenuitem())
        #menu.append(item("Options", "configure", None, self.options))
        menu.append(gtk.SeparatorMenuItem())
        menu.append(self.make_startnewcommandmenuitem())
        menu.append(self.make_uploadmenuitem())
        menu.append(self.make_disconnectmenuitem())
        if show_close:
            menu.append(self.make_closemenuitem())
        self.popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        return menu

    def cleanup(self):
        log("cleanup() session_info=%s", self.session_info)
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
        log("activate()")
        self.show_menu(1, 0)

    def popup(self, button, time):
        log("popup(%s, %s)", button, time)
        self.show_menu(button, time)

    def show_menu(self, button, time):
        raise Exception("override me!")


    def handshake_menuitem(self, *args, **kwargs):
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        set_sensitive(mi, False)
        def enable_menuitem(*args):
            set_sensitive(mi, True)
        self.client.after_handshake(enable_menuitem)
        return mi


    def make_menu(self):
        return gtk.Menu()

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        image = None
        if icon_name:
            icon_size = get_icon_size()
            image = self.get_image(icon_name, icon_size)
        return menuitem(title, image, tooltip, cb)

    def checkitem(self, title, cb=None, active=False):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = CheckMenuItem(title)
        check_item.set_active(active)
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

    def make_bugreportmenuitem(self):
        def show_bug_report_cb(*args):
            self.show_bug_report()
        return  self.handshake_menuitem("Bug Report", "bugs.png", None, show_bug_report_cb)


    def make_bellmenuitem(self):
        def bell_toggled(*args):
            v = self.bell_menuitem.get_active()
            changed = self.client.bell_enabled != v
            self.client.bell_enabled = v
            if changed:
                self.client.send_bell_enabled()
            log("bell_toggled(%s) bell_enabled=%s", args, self.client.bell_enabled)
        self.bell_menuitem = self.checkitem("Bell", bell_toggled)
        set_sensitive(self.bell_menuitem, False)
        def set_bell_menuitem(*args):
            log("set_bell_menuitem%s enabled=%s", args, self.client.bell_enabled)
            self.bell_menuitem.set_active(self.client.bell_enabled)
            c = self.client
            can_toggle_bell = c.server_supports_bell and c.client_supports_bell
            set_sensitive(self.bell_menuitem, can_toggle_bell)
            if can_toggle_bell:
                self.bell_menuitem.set_tooltip_text("Forward system bell")
            else:
                self.bell_menuitem.set_tooltip_text("Cannot forward the system bell: the feature has been disabled")
        self.client.after_handshake(set_bell_menuitem)
        return  self.bell_menuitem

    def make_cursorsmenuitem(self):
        def cursors_toggled(*args):
            v = self.cursors_menuitem.get_active()
            changed = self.client.cursors_enabled != v
            self.client.cursors_enabled = v
            if changed:
                self.client.send_cursors_enabled()
            if not self.client.cursors_enabled:
                self.client.reset_cursor()
            log("cursors_toggled(%s) cursors_enabled=%s", args, self.client.cursors_enabled)
        self.cursors_menuitem = self.checkitem("Cursors", cursors_toggled)
        set_sensitive(self.cursors_menuitem, False)
        def set_cursors_menuitem(*args):
            log("set_cursors_menuitem%s enabled=%s", args, self.client.cursors_enabled)
            self.cursors_menuitem.set_active(self.client.cursors_enabled)
            c = self.client
            can_toggle_cursors = c.server_supports_cursors and c.client_supports_cursors
            set_sensitive(self.cursors_menuitem, can_toggle_cursors)
            if can_toggle_cursors:
                self.cursors_menuitem.set_tooltip_text("Forward custom mouse cursors")
            else:
                self.cursors_menuitem.set_tooltip_text("Cannot forward mouse cursors: the feature has been disabled")
        self.client.after_handshake(set_cursors_menuitem)
        return  self.cursors_menuitem

    def make_notificationsmenuitem(self):
        def notifications_toggled(*args):
            v = self.notifications_menuitem.get_active()
            changed = self.client.notifications_enabled != v
            self.client.notifications_enabled = v
            log("notifications_toggled%s active=%s changed=%s", args, v, changed)
            if changed:
                self.client.send_notify_enabled()
        self.notifications_menuitem = self.checkitem("Notifications", notifications_toggled)
        set_sensitive(self.notifications_menuitem, False)
        def set_notifications_menuitem(*args):
            log("set_notifications_menuitem%s enabled=%s", args, self.client.notifications_enabled)
            self.notifications_menuitem.set_active(self.client.notifications_enabled)
            c = self.client
            can_notify = c.server_supports_notifications and c.client_supports_notifications
            set_sensitive(self.notifications_menuitem, can_notify)
            if can_notify:
                self.notifications_menuitem.set_tooltip_text("Forward system notifications")
            else:
                self.notifications_menuitem.set_tooltip_text("Cannot forward system notifications: the feature has been disabled")
        self.client.after_handshake(set_notifications_menuitem)
        return self.notifications_menuitem

    def make_clipboard_togglemenuitem(self):
        clipboardlog("make_clipboard_togglemenuitem()")
        def menu_clipboard_toggled(*args):
            new_state = self.clipboard_menuitem.get_active()
            clipboardlog("clipboard_toggled(%s) clipboard_enabled=%s, new_state=%s", args, self.client.clipboard_enabled, new_state)
            if self.client.clipboard_enabled!=new_state:
                self.client.clipboard_enabled = new_state
                self.client.emit("clipboard-toggled")
        self.clipboard_menuitem = self.checkitem("Clipboard", menu_clipboard_toggled)
        set_sensitive(self.clipboard_menuitem, False)
        def set_clipboard_menuitem(*args):
            clipboardlog("set_clipboard_menuitem%s enabled=%s", args, self.client.clipboard_enabled)
            self.clipboard_menuitem.set_active(self.client.clipboard_enabled)
            c = self.client
            can_clipboard = c.server_supports_clipboard and c.client_supports_clipboard
            set_sensitive(self.clipboard_menuitem, can_clipboard)
            if can_clipboard:
                self.clipboard_menuitem.set_tooltip_text("Enable clipboard synchronization")
            else:
                self.clipboard_menuitem.set_tooltip_text("Clipboard synchronization cannot be enabled: disabled by server")
        self.client.after_handshake(set_clipboard_menuitem)
        def clipboard_toggled(*args):
            #keep menu in sync with actual "clipboard_enabled" flag:
            if self.client.clipboard_enabled != self.clipboard_menuitem.get_active():
                self.clipboard_menuitem.set_active(self.client.clipboard_enabled)
        self.client.connect("clipboard-toggled", clipboard_toggled)
        return self.clipboard_menuitem

    def make_translatedclipboard_optionsmenuitem(self):
        clipboardlog("make_translatedclipboard_optionsmenuitem()")
        clipboard_menu = self.menuitem("Clipboard", "clipboard.png", "Choose which remote clipboard to connect to", None)
        set_sensitive(clipboard_menu, False)
        def set_clipboard_menu(*args):
            clipboard_submenu = gtk.Menu()
            clipboard_menu.set_submenu(clipboard_submenu)
            self.popup_menu_workaround(clipboard_submenu)
            c = self.client
            can_clipboard = c.server_supports_clipboard and c.client_supports_clipboard and c.server_supports_clipboard
            clipboardlog("set_clipboard_menu(%s) can_clipboard=%s, server=%s, client=%s", args, can_clipboard, c.server_supports_clipboard, c.client_supports_clipboard)
            set_sensitive(clipboard_menu, can_clipboard)
            LABEL_TO_NAME = {"Disabled"  : None,
                            "Clipboard" : "CLIPBOARD",
                            "Primary"   : "PRIMARY",
                            "Secondary" : "SECONDARY"}
            from xpra.clipboard.translated_clipboard import TranslatedClipboardProtocolHelper
            for label, remote_clipboard in LABEL_TO_NAME.items():
                clipboard_item = CheckMenuItem(label)
                def remote_clipboard_changed(item):
                    assert can_clipboard
                    ensure_item_selected(clipboard_submenu, item)
                    label = item.get_label()
                    remote_clipboard = LABEL_TO_NAME.get(label)
                    old_state = self.client.clipboard_enabled
                    clipboardlog("remote_clipboard_changed(%s) remote_clipboard=%s, old_state=%s", item, remote_clipboard, old_state)
                    send_tokens = False
                    if remote_clipboard is not None:
                        #clipboard is not disabled
                        if self.client.clipboard_helper is None:
                            self.client.setup_clipboard_helper(TranslatedClipboardProtocolHelper)
                        self.client.clipboard_helper.remote_clipboard = remote_clipboard
                        self.client.clipboard_helper.remote_clipboards = [remote_clipboard]
                        send_tokens = True
                        new_state = True
                        selections = [remote_clipboard]
                    else:
                        self.client.clipboard_helper = None
                        send_tokens = False
                        new_state = False
                        selections = []
                    #tell the server what to look for:
                    self.client.send_clipboard_selections(selections)
                    clipboardlog("remote_clipboard_changed(%s) label=%s, remote_clipboard=%s, old_state=%s, new_state=%s",
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
                set_sensitive(clipboard_item, can_clipboard)
                clipboard_item.set_draw_as_radio(True)
                clipboard_item.connect("toggled", remote_clipboard_changed)
                clipboard_submenu.append(clipboard_item)
            clipboard_submenu.show_all()
        self.client.after_handshake(set_clipboard_menu)
        return clipboard_menu

    def make_clipboardmenuitem(self):
        try:
            copts = self.client.get_clipboard_helper_classes()
            #ugly alert: the helper does not exist yet.. we just check the helper classnames:
            for c in copts:
                if c.find("translated_clipboard")>0:
                    return self.make_translatedclipboard_optionsmenuitem()
        except:
            clipboardlog.error("make_clipboardmenuitem()", exc_info=True)
        return self.make_clipboard_togglemenuitem()


    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip():
            if not self.client.keyboard_helper:
                self.keyboard_sync_menuitem.set_tooltip_text("Keyboard support is not loaded")
            elif self.client.keyboard_helper.keyboard_sync:
                self.keyboard_sync_menuitem.set_tooltip_text("Disable keyboard synchronization (prevents spurious key repeats on high latency connections)")
            else:
                self.keyboard_sync_menuitem.set_tooltip_text("Enable keyboard state synchronization")
        def keyboard_sync_toggled(*args):
            self.client.keyboard_sync = self.keyboard_sync_menuitem.get_active()
            log("keyboard_sync_toggled(%s) keyboard_sync=%s", args, self.client.keyboard_sync)
            set_keyboard_sync_tooltip()
            self.client.emit("keyboard-sync-toggled")
        self.keyboard_sync_menuitem = self.checkitem("Keyboard Synchronization", keyboard_sync_toggled)
        set_sensitive(self.keyboard_sync_menuitem, False)
        def set_keyboard_sync_menuitem(*args):
            log("set_keyboard_sync_menuitem%s enabled=%s", args, self.client.keyboard_helper.keyboard_sync)
            self.keyboard_sync_menuitem.set_active(self.client.keyboard_helper.keyboard_sync)
            set_sensitive(self.keyboard_sync_menuitem, True)
            set_keyboard_sync_tooltip()
        self.client.after_handshake(set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_openglmenuitem(self):
        gl = self.checkitem("OpenGL")
        def gl_set(*args):
            log("gl_set(%s) opengl_enabled=%s, ", args, self.client.opengl_enabled)
            gl.set_active(self.client.opengl_enabled)
            set_sensitive(gl, self.client.client_supports_opengl)
            def opengl_toggled(*args):
                log("opengl_toggled%s", args)
                self.client.toggle_opengl()
            gl.connect("toggled", opengl_toggled)
        self.client.after_handshake(gl_set)
        return gl

    def make_encodingsmenuitem(self):
        encodings = self.menuitem("Encoding", "encoding.png", "Choose picture data encoding", None)
        set_sensitive(encodings, False)
        def set_encodingsmenuitem(*args):
            log("set_encodingsmenuitem%s", args)
            set_sensitive(encodings, not self.client.mmap_enabled)
            if self.client.mmap_enabled:
                #mmap disables encoding and uses raw rgb24
                encodings.set_label("Encoding")
                encodings.set_tooltip_text("memory mapped transfers are in use so picture encoding is disabled")
            else:
                encodings.set_submenu(self.make_encodingssubmenu())
        self.client.after_handshake(set_encodingsmenuitem)
        return encodings

    def make_encodingssubmenu(self, handshake_complete=True):
        all_encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
        encodings = [x for x in all_encodings if x not in self.client.server_encodings_problematic]
        if not encodings:
            #all we have, show the "bad" hidden ones then!
            encodings = all_encodings
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
                set_sensitive(x, encoding in self.client.server_encodings)


    def make_scalingmenuitem(self):
        self.scaling = self.menuitem("Scaling", "scaling.png", "Desktop Scaling")
        def set_scalingmenuitem(*args):
            log("set_scalingmenuitem%s", args)
            set_sensitive(self.scaling, not self.client.mmap_enabled)
        self.client.after_handshake(set_scalingmenuitem)
        scaling_submenu = self.make_scalingmenu()
        self.scaling.set_submenu(scaling_submenu)
        return self.scaling

    def make_scalingmenu(self):
        scaling_submenu = gtk.Menu()
        scaling_submenu.updating = False
        self.popup_menu_workaround(scaling_submenu)
        def scalecmp(v):
            return abs(self.client.xscale-v)<0.1
        from xpra.client.ui_client_base import SCALING_OPTIONS
        def scalingitem(scalingvalue=1.0):
            pct = iround(100.0*scalingvalue)
            label = {100 : "None"}.get(pct, "%i%%" % pct)
            c = CheckMenuItem(label)
            c.scalingvalue = scalingvalue
            c.set_draw_as_radio(True)
            c.set_active(scalecmp(scalingvalue))
            def scaling_activated(item):
                if scaling_submenu.updating:
                    return
                ensure_item_selected(scaling_submenu, item)
                self.client.scaleset(item.scalingvalue, item.scalingvalue)
            c.connect('activate', scaling_activated)
            return c
        for x in SCALING_OPTIONS:
            scaling_submenu.append(scalingitem(x))
        def scaling_changed(*args):
            log("scaling_changed%s updating selected tray menu item", args)
            #find the nearest scaling option to show as current:
            scaling = (self.client.xscale + self.client.yscale)/2.0
            by_distance = dict((abs(scaling-x),x) for x in SCALING_OPTIONS)
            closest = by_distance.get(sorted(by_distance)[0], 1)
            scaling_submenu.updating = True
            for x in scaling_submenu.get_children():
                scalingvalue = getattr(x, "scalingvalue", -1)
                x.set_active(scalingvalue==closest)
            scaling_submenu.updating = False
        self.client.connect("scaling-changed", scaling_changed)
        return scaling_submenu


    def make_qualitymenuitem(self):
        self.quality = self.menuitem("Quality", "slider.png", "Picture quality", None)
        set_sensitive(self.quality, False)
        def may_enable_qualitymenu(*args):
            self.quality.set_submenu(self.make_qualitysubmenu())
            self.set_qualitymenu()
        self.client.after_handshake(may_enable_qualitymenu)
        return self.quality

    def make_qualitysubmenu(self):
        quality_submenu = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                           self.get_min_quality, self.get_quality, self.set_min_quality, self.set_quality)
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
            set_sensitive(self.quality, can_use)
            if not can_use:
                self.quality.set_tooltip_text("Not supported with %s encoding" % self.client.encoding)
                return
            self.quality.set_tooltip_text("Minimum picture quality")
            #now check if lossless is supported:
            if self.quality.get_submenu():
                can_lossless = self.client.encoding in self.client.server_encodings_with_lossless_mode
                for q,item in self.quality.get_submenu().menu_items.items():
                    set_sensitive(item, q<100 or can_lossless)


    def make_speedmenuitem(self):
        self.speed = self.menuitem("Speed", "speed.png", "Encoding latency vs size", None)
        set_sensitive(self.speed, False)
        def may_enable_speedmenu(*args):
            self.speed.set_submenu(self.make_speedsubmenu())
            self.set_speedmenu()
        self.client.after_handshake(may_enable_speedmenu)
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
            can_use = not self.client.mmap_enabled and self.client.encoding in self.client.server_encodings_with_speed
            set_sensitive(self.speed, can_use)
            if self.client.mmap_enabled:
                self.speed.set_tooltip_text("Quality is always 100% with mmap")
            elif self.client.encoding!="h264":
                self.speed.set_tooltip_text("Not supported with %s encoding" % self.client.encoding)
            else:
                self.speed.set_tooltip_text("Encoding latency vs size")


    def spk_on(self, *args):
        log("spk_on(%s)", args)
        self.client.start_receiving_sound()
    def spk_off(self, *args):
        log("spk_off(%s)", args)
        self.client.stop_receiving_sound()
    def make_speakermenuitem(self):
        speaker = self.menuitem("Speaker", "speaker.png", "Forward sound output from the server")
        set_sensitive(speaker, False)
        def is_speaker_on(*args):
            return self.client.speaker_enabled
        def speaker_state(*args):
            if not self.client.speaker_allowed:
                set_sensitive(speaker, False)
                speaker.set_tooltip_text("Speaker forwarding has been disabled")
                return
            if not self.client.server_sound_send:
                set_sensitive(speaker, False)
                speaker.set_tooltip_text("Server does not support speaker forwarding")
                return
            set_sensitive(speaker, True)
            speaker.set_submenu(self.make_soundsubmenu(is_speaker_on, self.spk_on, self.spk_off, "speaker-changed"))
        self.client.after_handshake(speaker_state)
        return speaker

    def mic_on(self, *args):
        log("mic_on(%s)", args)
        self.client.start_sending_sound()
    def mic_off(self, *args):
        log("mic_off(%s)", args)
        self.client.stop_sending_sound()
    def make_microphonemenuitem(self):
        microphone = self.menuitem("Microphone", "microphone.png", "Forward sound input to the server", None)
        set_sensitive(microphone, False)
        def is_microphone_on(*args):
            return self.client.microphone_enabled
        def microphone_state(*args):
            if not self.client.microphone_allowed:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Microphone forwarding has been disabled")
                return
            if not self.client.server_sound_receive:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Server does not support microphone forwarding")
                return
            set_sensitive(microphone, True)
            microphone.set_submenu(self.make_soundsubmenu(is_microphone_on, self.mic_on, self.mic_off, "microphone-changed"))
        self.client.after_handshake(microphone_state)
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
            log("sound: client_signalled_change(%s) is_on=%s", obj, is_on)
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

    def make_webcammenuitem(self):
        def webcam_toggled(*args):
            active = self.client.webcam_device is not None
            v = webcam.get_active()
            webcamlog("webcam_toggled%s active=%s, menu=%s", args, active, v)
            changed = active != v
            if not changed:
                return
            if v:
                self.client.start_sending_webcam()
            else:
                self.client.stop_sending_webcam()
            active = self.client.webcam_device is not None
            if webcam.get_active()!=active:
                webcam.set_active(active)
        webcam = self.checkitem("Webcam", webcam_toggled)
        def webcam_changed(*args):
            active = self.client.webcam_device is not None
            v = webcam.get_active()
            webcamlog("webcam_changed%s active=%s, menu=%s", args, active, v)
            if webcam.get_active()!=active:
                webcam.set_active(active)
        self.client.connect("webcam-changed", webcam_changed)
        #webcam = self.menuitem("Webcam", "webcam.png", "Forward webcam", None)
        set_sensitive(webcam, False)
        def set_webcam(*args):
            webcamlog("set_webcam%s webcam forwarding=%s, server virtual video devices=%i", args, self.client.webcam_forwarding, self.client.server_virtual_video_devices)
            if not self.client.webcam_forwarding:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Webcam forwarding is disabled")
                return
            if self.client.server_virtual_video_devices<=0:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Server does not support webcam forwarding")
                return
            set_sensitive(webcam, True)
            webcam.set_active(self.client.webcam_device is not None)
        self.client.after_handshake(set_webcam)
        return webcam

    def make_layoutsmenuitem(self):
        keyboard = self.menuitem("Keyboard", "keyboard.png", "Select your keyboard layout", None)
        set_sensitive(keyboard, False)
        self.layout_submenu = gtk.Menu()
        keyboard.set_submenu(self.layout_submenu)
        self.popup_menu_workaround(self.layout_submenu)
        def kbitem(title, layout, variant, active=False):
            def set_layout(item):
                """ this callback updates the client (and server) if needed """
                ensure_item_selected(self.layout_submenu, item)
                layout = item.keyboard_layout
                variant = item.keyboard_variant
                kh = self.client.keyboard_helper
                kh.locked = layout!="Auto"
                if layout!=kh.xkbmap_layout or variant!=kh.xkbmap_variant:
                    if layout=="Auto":
                        #re-detect everything:
                        kh.update()
                        log.info("keyboard automatic mode: %s", kh.layout_str())
                        kh.send_layout()
                        kh.send_keymap()
                    else:
                        #use layout specified and send it:
                        kh.xkbmap_layout = layout
                        kh.xkbmap_variant = variant
                        log.info("new keyboard layout selected: %s", kh.layout_str())
                        kh.send_layout()
            l = self.checkitem(title, set_layout, active)
            l.set_draw_as_radio(True)
            l.keyboard_layout = layout
            l.keyboard_variant = variant
            return l
        def keysort(key):
            c,l = key
            return c.lower()+l.lower()
        layout,layouts,variant,variants = self.client.keyboard_helper.keyboard.get_layout_spec()
        full_layout_list = False
        if len(layouts)>1:
            log("keyboard layouts: %s", u",".join(bytestostr(x) for x in layouts))
            #log after removing dupes:
            def uniq(seq):
                seen = set()
                return [x for x in seq if not (x in seen or seen.add(x))]
            log.info("keyboard layouts: %s", u",".join(bytestostr(x) for x in uniq(layouts)))
            auto = kbitem("Auto", "Auto", "", True)
            self.layout_submenu.append(auto)
            if layout:
                self.layout_submenu.append(kbitem("%s" % layout, layout, ""))
            if variants:
                for v in variants:
                    self.layout_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
            for l in uniq(layouts):
                if l!=layout:
                    self.layout_submenu.append(kbitem("%s" % l, l, ""))
        elif layout and variants and len(variants)>1:
            #just show all the variants to choose from this layout
            default = kbitem("%s - Default" % layout, layout, "", True)
            self.layout_submenu.append(default)
            for v in variants:
                self.layout_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
        else:
            full_layout_list = True
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
        def set_layout_enabled(*args):
            if full_layout_list and (keyboard_helper.xkbmap_layout or keyboard_helper.xkbmap_print or keyboard_helper.xkbmap_query):
                #we have detected a layout
                #so no need to show the user the huge layout list
                keyboard.hide()
                return
            set_sensitive(keyboard, True)
        self.client.after_handshake(set_layout_enabled)
        return keyboard

    def make_compressionmenu(self):
        self.compression = self.menuitem("Compression", "compressed.png", "Network packet compression", None)
        set_sensitive(self.compression, False)
        self.compression_submenu = gtk.Menu()
        self.compression.set_submenu(self.compression_submenu)
        self.popup_menu_workaround(self.compression_submenu)
        compression_options = {0 : "None"}
        def set_compression(item):
            ensure_item_selected(self.compression_submenu, item)
            c = int(item.get_label().replace("None", "0"))
            if c!=self.client.compression_level:
                log("setting compression level to %s", c)
                self.client.set_deflate_level(c)
        for i in range(0, 10):
            c = CheckMenuItem(str(compression_options.get(i, i)))
            c.set_draw_as_radio(True)
            c.set_active(i==self.client.compression_level)
            c.connect('activate', set_compression)
            self.compression_submenu.append(c)
        def enable_compressionmenu(self):
            set_sensitive(self.compression, True)
            self.compression_submenu.show_all()
        self.client.after_handshake(enable_compressionmenu)
        return self.compression


    def make_refreshmenuitem(self):
        def force_refresh(*args):
            log("force refresh")
            self.client.send_refresh_all()
        return self.handshake_menuitem("Refresh", "retry.png", None, force_refresh)

    def make_raisewindowsmenuitem(self):
        def raise_windows(*args):
            for win in self.client._window_to_id.keys():
                if not win.is_OR():
                    win.present()
        return self.handshake_menuitem("Raise Windows", "raise.png", None, raise_windows)

    def make_startnewcommandmenuitem(self):
        self.startnewcommand = self.menuitem("Run Command", "forward.png", "Run a new command on the server", self.client.show_start_new_command)
        def enable_start_new_command(*args):
            log("enable_start_new_command%s start_new_command=%s", args, self.client.start_new_commands)
            set_sensitive(self.startnewcommand, self.client.start_new_commands)
            if not self.client.start_new_commands:
                self.startnewcommand.set_tooltip_text("Not supported by the server")
        self.client.after_handshake(enable_start_new_command)
        return self.startnewcommand

    def make_uploadmenuitem(self):
        self.upload = self.menuitem("Upload File", "upload.png", "Send a file to the server", self.client.show_file_upload)
        def enable_upload(*args):
            log("enable_upload%s server_file_transfer=%s", args, self.client.server_file_transfer)
            set_sensitive(self.upload, self.client.server_file_transfer)
            if not self.client.server_file_transfer:
                self.upload.set_tooltip_text("Not supported by the server")
        self.client.after_handshake(enable_upload)
        return self.upload


    def make_disconnectmenuitem(self):
        def menu_quit(*args):
            self.client.disconnect_and_quit(EXIT_OK, CLIENT_EXIT)
        return self.handshake_menuitem("Disconnect", "quit.png", None, menu_quit)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)


    def popup_menu_workaround(self, menu):
        popup_menu_workaround(menu, self.close_menu)
