# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re

from xpra.gtk_common.gobject_compat import import_gtk, import_glib, import_pixbufloader
from xpra.util import CLIENT_EXIT, iround, envbool, repr_ellipsized, reverse_dict, typedict
from xpra.os_util import bytestostr, OSX, WIN32, PYTHON2
from xpra.gtk_common.gtk_util import (
    ensure_item_selected, menuitem, popup_menu_workaround, CheckMenuItem,
    get_pixbuf_from_data, scaled_image,
    MESSAGE_QUESTION, BUTTONS_NONE,
    )
from xpra.client.client_base import EXIT_OK
from xpra.gtk_common.about import about, close_about
from xpra.codecs.codec_constants import PREFERED_ENCODING_ORDER
from xpra.codecs.loader import get_encoding_help, get_encoding_name
from xpra.simple_stats import std_unit_dec
from xpra.platform.gui import get_icon_size
from xpra.platform.paths import get_icon_dir
from xpra.client import mixin_features
from xpra.log import Logger

log = Logger("menu")
clipboardlog = Logger("menu", "clipboard")
webcamlog = Logger("menu", "webcam")
avsynclog = Logger("menu", "av-sync")
bandwidthlog = Logger("bandwidth", "network")

gtk = import_gtk()
glib = import_glib()

HIDE_DISABLED_MENU_ENTRIES = envbool("XPRA_HIDE_DISABLED_MENU_ENTRIES", PYTHON2 and OSX)

SHOW_TITLE_ITEM = envbool("XPRA_SHOW_TITLE_ITEM", True)
SHOW_VERSION_CHECK = envbool("XPRA_SHOW_VERSION_CHECK", True)
SHOW_UPLOAD = envbool("XPRA_SHOW_UPLOAD_MENU", True)
STARTSTOP_SOUND_MENU = envbool("XPRA_SHOW_SOUND_MENU", True)
WEBCAM_MENU = envbool("XPRA_SHOW_WEBCAM_MENU", True)
RUNCOMMAND_MENU = envbool("XPRA_SHOW_RUNCOMMAND_MENU", True)
SHOW_SERVER_COMMANDS = envbool("XPRA_SHOW_SERVER_COMMANDS", True)
SHOW_TRANSFERS = envbool("XPRA_SHOW_TRANSFERS", True)
SHOW_CLIPBOARD_MENU = envbool("XPRA_SHOW_CLIPBOARD_MENU", True)
SHOW_CLOSE = envbool("XPRA_SHOW_CLOSE", True)
SHOW_SHUTDOWN = envbool("XPRA_SHOW_SHUTDOWN", True)
WINDOWS_MENU = envbool("XPRA_SHOW_WINDOWS_MENU", True)
START_MENU = envbool("XPRA_SHOW_START_MENU", True)
MENU_ICONS = envbool("XPRA_MENU_ICONS", True)


def s(v):
    try:
        return v.decode("utf-8")
    except AttributeError:
        return str(v)


def get_bandwidth_menu_options():
    options = []
    for x in os.environ.get("XPRA_BANDWIDTH_MENU_OPTIONS", "1,2,5,10,20,50,100").split(","):
        try:
            options.append(int(float(x)*1000*1000))
        except ValueError:
            log.warn("Warning: invalid bandwidth menu option '%s'", x)
    return options
BANDWIDTH_MENU_OPTIONS = get_bandwidth_menu_options()

LOSSLESS = "Lossless"
QUALITY_OPTIONS_COMMON = {
                50      : "Average",
                30      : "Low",
                }
MIN_QUALITY_OPTIONS = QUALITY_OPTIONS_COMMON.copy()
MIN_QUALITY_OPTIONS[0] = "None"
MIN_QUALITY_OPTIONS[75] = "High"
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

# 'auto' is recorded as '' unfortunately:
GENERIC_ENCODINGS = ("", "auto", "grayscale")

CLIPBOARD_LABELS = ["Clipboard", "Primary", "Secondary"]
CLIPBOARD_LABEL_TO_NAME = {
                           "Clipboard"  : "CLIPBOARD",
                           "Primary"    : "PRIMARY",
                           "Secondary"  : "SECONDARY"
                           }
CLIPBOARD_NAME_TO_LABEL  = reverse_dict(CLIPBOARD_LABEL_TO_NAME)

CLIPBOARD_DIRECTION_LABELS = ["Client to server only", "Server to client only", "Both directions", "Disabled"]
CLIPBOARD_DIRECTION_LABEL_TO_NAME = {
                                     "Client to server only"    : "to-server",
                                     "Server to client only"    : "to-client",
                                     "Both directions"          : "both",
                                     "Disabled"                 : "disabled",
                                     }
CLIPBOARD_DIRECTION_NAME_TO_LABEL = reverse_dict(CLIPBOARD_DIRECTION_LABEL_TO_NAME)


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


def make_min_auto_menu(title, min_options, options,
                       get_current_min_value,
                       get_current_value,
                       set_min_value_cb,
                       set_value_cb):
    #note: we must keep references to the parameters on the submenu
    #(closures and gtk callbacks don't mix so well!)
    submenu = gtk.Menu()
    submenu.get_current_min_value = get_current_min_value
    submenu.get_current_value = get_current_value
    submenu.set_min_value_cb = set_min_value_cb
    submenu.set_value_cb = set_value_cb
    fstitle = gtk.MenuItem()
    fstitle.set_label("Fixed %s:" % title)
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
    mstitle = gtk.MenuItem()
    mstitle.set_label("Minimum %s:" % title)
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
        name = get_encoding_name(encoding)
        descr = get_encoding_help(encoding)
        NAME_TO_ENCODING[name] = encoding
        encoding_item = CheckMenuItem(label=name)
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
        log("populate_encodingsmenu(..) encoding=%s, current=%s, active=%s",
            encoding, get_current_encoding(), encoding==get_current_encoding())
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
        self.menu = None
        self.menu_shown = False
        self.menu_icon_size = 0

    def build(self):
        if self.menu is None:
            try:
                self.menu = self.setup_menu(SHOW_CLOSE)
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

    def setup_menu(self, show_close=True):
        log("setup_menu(%s)", show_close)
        self.menu_shown = False
        self.menu_icon_size = get_icon_size()
        self.handshake_menuitem = self.do_handshake_menuitem
        def shortcut():
            self.handshake_menuitem = self.menuitem
        if self.client:
            self.client.after_handshake(shortcut)
        menu = gtk.Menu()
        title_item = None
        if SHOW_TITLE_ITEM:
            title_item = gtk.MenuItem()
            title_item.set_label(self.client.session_name or u"Xpra")
            set_sensitive(title_item, False)
            menu.append(title_item)
            def set_menu_title(*_args):
                #set the real name when available:
                try:
                    title = self.client.get_tray_title()
                except Exception:
                    title = self.client.session_name or u"Xpra"
                title_item.set_label(title)
            if self.client:
                self.client.after_handshake(set_menu_title)

        menu.append(self.make_infomenuitem())
        menu.append(self.make_featuresmenuitem())
        if mixin_features.windows and self.client.keyboard_helper:
            menu.append(self.make_layoutsmenuitem())
        if mixin_features.clipboard and SHOW_CLIPBOARD_MENU:
            menu.append(self.make_clipboardmenuitem())
        if mixin_features.windows:
            menu.append(self.make_picturemenuitem())
        if mixin_features.audio and STARTSTOP_SOUND_MENU:
            menu.append(self.make_audiomenuitem())
        if mixin_features.webcam and WEBCAM_MENU:
            menu.append(self.make_webcammenuitem())
        if mixin_features.windows and WINDOWS_MENU:
            menu.append(self.make_windowsmenuitem())
        if RUNCOMMAND_MENU or SHOW_SERVER_COMMANDS or SHOW_UPLOAD or SHOW_SHUTDOWN:
            menu.append(self.make_servermenuitem())
        if mixin_features.windows and START_MENU:
            menu.append(self.make_startmenuitem())
        menu.append(self.make_disconnectmenuitem())
        if show_close:
            menu.append(self.make_closemenuitem())
        self.popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        log("setup_menu(%s) done", show_close)
        return menu

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

    def show_menu(self, _button, _time):
        raise NotImplementedError("override me!")


    def do_handshake_menuitem(self, *args, **kwargs):
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        set_sensitive(mi, False)
        def enable_menuitem(*_args):
            set_sensitive(mi, True)
        self.client.after_handshake(enable_menuitem)
        return mi


    def make_menu(self):
        return gtk.Menu()

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
        check_item = CheckMenuItem(title)
        check_item.set_active(active)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item


    def make_infomenuitem(self):
        info_menu_item = self.menuitem("Information", "information.png")
        menu = gtk.Menu()
        info_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_aboutmenuitem())
        menu.append(self.make_sessioninfomenuitem())
        if SHOW_VERSION_CHECK:
            menu.append(self.make_updatecheckmenuitem())
        menu.append(self.make_bugreportmenuitem())
        info_menu_item.show_all()
        return info_menu_item

    def make_aboutmenuitem(self):
        return self.menuitem("About Xpra", "xpra.png", None, about)

    def make_updatecheckmenuitem(self):
        def show_update_window(*_args):
            from xpra.client.gtk_base.update_status import getUpdateStatusWindow
            w = getUpdateStatusWindow()
            w.show()
            w.check()
        return self.menuitem("Check for updates", "update.png", None, show_update_window)

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


    def make_featuresmenuitem(self):
        features_menu_item = self.handshake_menuitem("Features", "features.png")
        menu = gtk.Menu()
        self.append_featuresmenuitems(menu)
        features_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        features_menu_item.show_all()
        return features_menu_item

    def append_featuresmenuitems(self, menu):
        menu.append(self.make_sharingmenuitem())
        menu.append(self.make_lockmenuitem())
        if mixin_features.windows:
            menu.append(self.make_readonlymenuitem())
            menu.append(self.make_bellmenuitem())
        if mixin_features.notifications:
            menu.append(self.make_notificationsmenuitem())
        if mixin_features.windows:
            menu.append(self.make_cursorsmenuitem())
        if self.client.client_supports_opengl:
            menu.append(self.make_openglmenuitem())
        if mixin_features.windows:
            menu.append(self.make_modalwindowmenuitem())
        if mixin_features.windows and self.client.keyboard_helper:
            menu.append(self.make_keyboardsyncmenuitem())
            menu.append(self.make_shortcutsmenuitem())

    def make_sharingmenuitem(self):
        def sharing_toggled(*args):
            v = self.sharing_menuitem.get_active()
            self.client.client_supports_sharing = v
            if self.client.server_sharing_toggle:
                self.client.send_sharing_enabled()
            log("sharing_toggled(%s) readonly=%s", args, self.client.readonly)
        self.sharing_menuitem = self.checkitem("Sharing", sharing_toggled)
        self.sharing_menuitem.set_tooltip_text("Allow other clients to connect to this session")
        set_sensitive(self.sharing_menuitem, False)
        def set_sharing_menuitem(*args):
            log("set_sharing_menuitem%s client_supports_sharing=%s, server_sharing_toggle=%s, server_sharing=%s",
                args, self.client.client_supports_sharing,
                self.client.server_sharing_toggle, self.client.server_sharing)
            self.sharing_menuitem.set_active(self.client.server_sharing and self.client.client_supports_sharing)
            set_sensitive(self.sharing_menuitem, self.client.server_sharing_toggle)
            if not self.client.server_sharing:
                self.sharing_menuitem.set_tooltip_text("Sharing is disabled on the server")
            elif not self.client.server_sharing_toggle:
                self.sharing_menuitem.set_tooltip_text("Sharing cannot be changed on this server")
            else:
                self.sharing_menuitem.set_tooltip_text("")
        self.client.after_handshake(set_sharing_menuitem)
        self.client.on_server_setting_changed("sharing", set_sharing_menuitem)
        self.client.on_server_setting_changed("sharing-toggle", set_sharing_menuitem)
        return self.sharing_menuitem

    def make_lockmenuitem(self):
        def lock_toggled(*args):
            v = self.lock_menuitem.get_active()
            self.client.client_lock = v
            if self.client.server_lock_toggle:
                self.client.send_lock_enabled()
            log("lock_toggled(%s) lock=%s", args, self.client.client_lock)
        self.lock_menuitem = self.checkitem("Lock", lock_toggled)
        self.lock_menuitem.set_tooltip_text("Prevent other clients from stealing this session")
        set_sensitive(self.lock_menuitem, False)
        def set_lock_menuitem(*args):
            log("set_lock_menuitem%s client_lock=%s, server_lock_toggle=%s, server lock=%s",
                args, self.client.client_lock, self.client.server_lock_toggle, self.client.server_lock)
            self.lock_menuitem.set_active(self.client.server_lock and self.client.client_lock)
            set_sensitive(self.lock_menuitem, self.client.server_lock_toggle)
            if not self.client.server_lock:
                self.lock_menuitem.set_tooltip_text("Session locking is disabled on this server")
            elif not self.client.server_lock_toggle:
                self.lock_menuitem.set_tooltip_text("Session locking cannot be toggled on this server")
            else:
                self.lock_menuitem.set_tooltip_text("")
        self.client.after_handshake(set_lock_menuitem)
        self.client.on_server_setting_changed("lock", set_lock_menuitem)
        self.client.on_server_setting_changed("lock-toggle", set_lock_menuitem)
        return self.lock_menuitem

    def make_readonlymenuitem(self):
        def readonly_toggled(*args):
            v = self.readonly_menuitem.get_active()
            self.client.readonly = v
            log("readonly_toggled(%s) readonly=%s", args, self.client.readonly)
        self.readonly_menuitem = self.checkitem("Read-only", readonly_toggled)
        set_sensitive(self.readonly_menuitem, False)
        def set_readonly_menuitem(*args):
            log("set_readonly_menuitem%s enabled=%s", args, self.client.readonly)
            self.readonly_menuitem.set_active(self.client.readonly)
            set_sensitive(self.readonly_menuitem, not self.client.server_readonly)
            if not self.client.server_readonly:
                self.readonly_menuitem.set_tooltip_text("Disable all mouse and keyboard input")
            else:
                self.readonly_menuitem.set_tooltip_text("Cannot disable readonly mode: "+
                                                        "the server has locked the session to read only")
        self.client.after_handshake(set_readonly_menuitem)
        return self.readonly_menuitem

    def make_bellmenuitem(self):
        c = self.client
        def bell_toggled(*args):
            can_toggle_bell = c.server_bell and c.client_supports_bell
            if not can_toggle_bell:
                return
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
            can_toggle_bell = c.server_bell and c.client_supports_bell
            self.bell_menuitem.set_active(self.client.bell_enabled and can_toggle_bell)
            set_sensitive(self.bell_menuitem, can_toggle_bell)
            if can_toggle_bell:
                self.bell_menuitem.set_tooltip_text("Forward system bell")
            else:
                self.bell_menuitem.set_tooltip_text("Cannot forward the system bell: the feature has been disabled")
        self.client.after_handshake(set_bell_menuitem)
        self.client.on_server_setting_changed("bell", set_bell_menuitem)
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
            c = self.client
            can_toggle_cursors = c.server_cursors and c.client_supports_cursors
            self.cursors_menuitem.set_active(self.client.cursors_enabled and can_toggle_cursors)
            set_sensitive(self.cursors_menuitem, can_toggle_cursors)
            if can_toggle_cursors:
                self.cursors_menuitem.set_tooltip_text("Forward custom mouse cursors")
            else:
                self.cursors_menuitem.set_tooltip_text("Cannot forward mouse cursors: the feature has been disabled")
        self.client.after_handshake(set_cursors_menuitem)
        self.client.on_server_setting_changed("cursors", set_cursors_menuitem)
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
            can_notify = self.client.client_supports_notifications
            self.notifications_menuitem.set_active(self.client.notifications_enabled and can_notify)
            set_sensitive(self.notifications_menuitem, can_notify)
            if can_notify:
                self.notifications_menuitem.set_tooltip_text("Forward system notifications")
            else:
                self.notifications_menuitem.set_tooltip_text("Cannot forward system notifications: "+
                                                             "the feature has been disabled")
        self.client.after_handshake(set_notifications_menuitem)
        return self.notifications_menuitem


    def remote_clipboard_changed(self, item, clipboard_submenu):
        c = self.client
        if not c or not c.server_clipboard or not c.client_supports_clipboard:
            return
        #prevent infinite recursion where ensure_item_selected
        #ends up calling here again
        key = "_in_remote_clipboard_changed"
        ich = getattr(clipboard_submenu, key, False)
        clipboardlog("remote_clipboard_changed%s already in change handler: %s, visible=%s",
                     (ll(item), clipboard_submenu), ich, clipboard_submenu.get_visible())
        if ich: # or not clipboard_submenu.get_visible():
            return
        try:
            setattr(clipboard_submenu, key, True)
            selected_item = ensure_item_selected(clipboard_submenu, item)
            selected = selected_item.get_label()
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME.get(selected)
            self.set_new_remote_clipboard(remote_clipboard)
        finally:
            setattr(clipboard_submenu, key, False)

    def set_new_remote_clipboard(self, remote_clipboard):
        clipboardlog("set_new_remote_clipboard(%s)", remote_clipboard)
        ch = self.client.clipboard_helper
        local_clipboard = "CLIPBOARD"
        ch._local_to_remote = {local_clipboard : remote_clipboard}
        ch._remote_to_local = {remote_clipboard : local_clipboard}
        selections = [remote_clipboard]
        clipboardlog.info("server clipboard synchronization changed to %s selection", remote_clipboard)
        #tell the server what to look for:
        #(now that "clipboard-toggled" has re-enabled clipboard if necessary)
        self.client.send_clipboard_selections(selections)
        ch.send_tokens([local_clipboard])

    def make_translatedclipboard_optionsmenuitem(self):
        clipboardlog("make_translatedclipboard_optionsmenuitem()")
        ch = self.client.clipboard_helper
        selection_menu = self.menuitem("Selection", None, "Choose which remote clipboard to connect to")
        selection_submenu = gtk.Menu()
        selection_menu.set_submenu(selection_submenu)
        rc_setting = None
        if len(ch._local_to_remote)==1:
            rc_setting = tuple(ch._local_to_remote.values())[0]
        self.popup_menu_workaround(selection_submenu)
        for label in CLIPBOARD_LABELS:
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
            selection_item = CheckMenuItem(label)
            selection_item.set_active(remote_clipboard==rc_setting)
            selection_item.set_draw_as_radio(True)
            def remote_clipboard_changed(item):
                self.remote_clipboard_changed(item, selection_submenu)
            selection_item.connect("toggled", remote_clipboard_changed)
            selection_submenu.append(selection_item)
        selection_submenu.show_all()
        return selection_menu

    def clipboard_direction_changed(self, item, submenu):
        log("clipboard_direction_changed(%s, %s)", item, submenu)
        sel = ensure_item_selected(submenu, item, recurse=False)
        if not sel:
            return
        self.do_clipboard_direction_changed(sel.get_label() or "")

    def do_clipboard_direction_changed(self, label):
        #find the value matching this item label:
        d = CLIPBOARD_DIRECTION_LABEL_TO_NAME.get(label)
        if d and d!=self.client.client_clipboard_direction:
            log.info("clipboard synchronization direction changed to: %s", label.lower())
            self.client.client_clipboard_direction = d
            can_send = d in ("to-server", "both")
            can_receive = d in ("to-client", "both")
            self.client.clipboard_helper.set_direction(can_send, can_receive)
            #will send new tokens and may help reset things:
            self.client.emit("clipboard-toggled")

    def make_clipboardmenuitem(self):
        clipboardlog("make_clipboardmenuitem()")
        self.clipboard_menuitem = self.menuitem("Clipboard", "clipboard.png")
        set_sensitive(self.clipboard_menuitem, False)
        def set_clipboard_menu(*args):
            c = self.client
            if not c.server_clipboard:
                self.clipboard_menuitem.set_tooltip_text("Server does not support clipboard synchronization")
                return
            ch = c.clipboard_helper
            if not c.client_supports_clipboard or not ch:
                self.clipboard_menuitem.set_tooltip_text("Client does not support clipboard synchronization")
                return
            #add a submenu:
            set_sensitive(self.clipboard_menuitem, True)
            clipboard_submenu = gtk.Menu()
            self.clipboard_menuitem.set_submenu(clipboard_submenu)
            self.popup_menu_workaround(clipboard_submenu)
            if WIN32 or OSX:
                #add a submenu to change the selection we synchronize with
                #since this platform only has a single clipboard
                try:
                    clipboardlog("set_clipboard_menu(%s) helper=%s, server=%s, client=%s",
                                 args, ch, c.server_clipboard, c.client_supports_clipboard)
                    clipboard_submenu.append(self.make_translatedclipboard_optionsmenuitem())
                    clipboard_submenu.append(gtk.SeparatorMenuItem())
                except ImportError:
                    clipboardlog.error("make_clipboardmenuitem()", exc_info=True)
            items = []
            for label in CLIPBOARD_DIRECTION_LABELS:
                direction_item = CheckMenuItem(label)
                d = CLIPBOARD_DIRECTION_LABEL_TO_NAME.get(label)
                direction_item.set_active(d==self.client.client_clipboard_direction)
                clipboard_submenu.append(direction_item)
                items.append(direction_item)
            clipboard_submenu.show_all()
            #connect signals:
            for direction_item in items:
                direction_item.connect("toggled", self.clipboard_direction_changed, clipboard_submenu)
        self.client.after_handshake(set_clipboard_menu)
        return self.clipboard_menuitem


    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip():
            kh = self.client.keyboard_helper
            if not kh:
                text = "Keyboard support is not loaded"
            elif not self.client.server_toggle_keyboard_sync:
                text = "Server does not support toggling the synchronization"
            elif kh.keyboard_sync:
                text = "Disable keyboard synchronization "+\
                       "(prevents spurious key repeats on high latency connections)"
            else:
                text = "Enable keyboard state synchronization"
            self.keyboard_sync_menuitem.set_tooltip_text(text)
        def keyboard_sync_toggled(*args):
            ks = self.keyboard_sync_menuitem.get_active()
            if self.client.keyboard_sync!=ks:
                self.client.keyboard_sync = ks
                log("keyboard_sync_toggled(%s) keyboard_sync=%s", args, ks)
                set_keyboard_sync_tooltip()
                self.client.send_keyboard_sync_enabled_status()
        self.keyboard_sync_menuitem = self.checkitem("Keyboard Synchronization")
        set_sensitive(self.keyboard_sync_menuitem, False)
        def set_keyboard_sync_menuitem(*args):
            kh = self.client.keyboard_helper
            can_set_sync = kh and self.client.server_keyboard and self.client.server_toggle_keyboard_sync
            set_sensitive(self.keyboard_sync_menuitem, can_set_sync)
            if can_set_sync:
                self.keyboard_sync_menuitem.connect("toggled", keyboard_sync_toggled)
            if kh:
                log("set_keyboard_sync_menuitem%s enabled=%s", args, kh.keyboard_sync)
            self.keyboard_sync_menuitem.set_active(kh and bool(kh.keyboard_sync))
            set_keyboard_sync_tooltip()
        self.client.after_handshake(set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_shortcutsmenuitem(self):
        self.keyboard_shortcuts_menuitem = self.checkitem("Keyboard Shortcuts")
        kh = self.client.keyboard_helper
        self.keyboard_shortcuts_menuitem.set_active(kh and bool(kh.shortcuts_enabled))
        def keyboard_shortcuts_toggled(*args):
            ks = self.keyboard_shortcuts_menuitem.get_active()
            log("keyboard_shortcuts_toggled%s enabled=%s", args, ks)
            kh.shortcuts_enabled = ks
        self.keyboard_shortcuts_menuitem.connect("toggled", keyboard_shortcuts_toggled)
        return self.keyboard_shortcuts_menuitem


    def make_openglmenuitem(self):
        gl = self.checkitem("OpenGL")
        gl.set_tooltip_text("hardware accelerated rendering using OpenGL")
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

    def make_modalwindowmenuitem(self):
        modal = self.checkitem("Modal Windows")
        modal.set_tooltip_text("honour modal windows")
        modal.set_active(self.client.modal_windows)
        set_sensitive(modal, False)
        def modal_toggled(*args):
            self.client.modal_windows = modal.get_active()
            log("modal_toggled%s modal_windows=%s", args, self.client.modal_windows)
        def set_modal_menuitem(*_args):
            set_sensitive(modal, True)
        self.client.after_handshake(set_modal_menuitem)
        modal.connect("toggled", modal_toggled)
        return modal

    def make_picturemenuitem(self):
        picture_menu_item = self.handshake_menuitem("Picture", "picture.png")
        menu = gtk.Menu()
        picture_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_bandwidthlimitmenuitem())
        if self.client.windows_enabled and len(self.client.get_encodings())>1:
            menu.append(self.make_encodingsmenuitem())
        if self.client.can_scale:
            menu.append(self.make_scalingmenuitem())
        menu.append(self.make_qualitymenuitem())
        menu.append(self.make_speedmenuitem())
        picture_menu_item.show_all()
        return picture_menu_item

    def make_bandwidthlimitmenuitem(self):
        bandwidth_limit_menu_item = self.menuitem("Bandwidth Limit", "bandwidth_limit.png")
        menu = gtk.Menu()
        self.popup_menu_workaround(menu)
        menuitems = {}

        def bwitem(bwlimit):
            c = self.bwitem(menu, bwlimit)
            menuitems[bwlimit] = c
            return c

        menu.append(bwitem(0))
        bandwidth_limit_menu_item.set_submenu(menu)
        bandwidth_limit_menu_item.show_all()

        def set_bwlimitmenu(*_args):
            if self.client.mmap_enabled:
                bandwidth_limit_menu_item.set_tooltip_text("memory mapped transfers are in use, "+
                                                           "so bandwidth limits are disabled")
                set_sensitive(bandwidth_limit_menu_item, False)
            elif not self.client.server_bandwidth_limit_change:
                bandwidth_limit_menu_item.set_tooltip_text("the server does not support bandwidth-limit")
                set_sensitive(bandwidth_limit_menu_item, False)
            else:
                initial_value = self.client.server_bandwidth_limit or self.client.bandwidth_limit or 0
                bandwidthlog("set_bwlimitmenu() server_bandwidth_limit=%s, bandwidth_limit=%s, initial value=%s",
                             self.client.server_bandwidth_limit, self.client.bandwidth_limit, initial_value)

                options = BANDWIDTH_MENU_OPTIONS
                if initial_value and initial_value not in options:
                    options.append(initial_value)
                bandwidthlog("bandwidth options=%s", options)
                menu.append(gtk.SeparatorMenuItem())
                for v in sorted(options):
                    menu.append(bwitem(v))

                sbl = self.client.server_bandwidth_limit
                for bwlimit, c in menuitems.items():
                    c.set_active(initial_value==bwlimit)
                    #disable any values higher than what the server allows:
                    if bwlimit==0:
                        below_server_limit = sbl==0
                    else:
                        below_server_limit = sbl==0 or bwlimit<=sbl
                    set_sensitive(c, below_server_limit)
                    if not below_server_limit:
                        c.set_tooltip_text("server set the limit to %sbps" % std_unit_dec(sbl))
        self.client.after_handshake(set_bwlimitmenu)
        self.client.on_server_setting_changed("bandwidth-limit", set_bwlimitmenu)
        return bandwidth_limit_menu_item
    def bwitem(self, menu, bwlimit=0):
        bandwidthlog("bwitem(%s, %i)", menu, bwlimit)
        if bwlimit<=0:
            label = "None"
        elif bwlimit>=10*1000*1000:
            label = "%iMbps" % (bwlimit//(1000*1000))
        else:
            label = "%sbps" % std_unit_dec(bwlimit)
        c = CheckMenuItem(label)
        c.set_draw_as_radio(True)
        c.set_active(False)
        set_sensitive(c, False)
        def activate_cb(item, *args):
            if not c.get_active():
                return
            bandwidthlog("activate_cb(%s, %s) bwlimit=%s", item, args, bwlimit)
            ensure_item_selected(menu, item)
            if (self.client.bandwidth_limit or 0)!=bwlimit:
                self.client.bandwidth_limit = bwlimit
                self.client.send_bandwidth_limit()
        c.connect("toggled", activate_cb)
        c.show()
        return c


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

    def make_encodingssubmenu(self):
        server_encodings = list(self.client.server_encodings)
        all_encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
        encodings = [x for x in all_encodings if x not in self.client.server_encodings_problematic]
        if not encodings:
            #all we have, show the "bad" hidden ones then!
            encodings = all_encodings
        if self.client.server_auto_video_encoding:
            encodings.insert(0, "auto")
            server_encodings.insert(0, "auto")
        encodings_submenu = make_encodingsmenu(self.get_current_encoding,
                                               self.set_current_encoding,
                                               encodings, server_encodings)
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
        scaling_submenu = self.make_scalingmenu()
        self.scaling.set_submenu(scaling_submenu)
        return self.scaling

    def make_scalingmenu(self):
        scaling_submenu = gtk.Menu()
        scaling_submenu.updating = False
        self.popup_menu_workaround(scaling_submenu)
        from xpra.client.mixins.display import SCALING_OPTIONS
        for x in SCALING_OPTIONS:
            scaling_submenu.append(self.make_scalingvaluemenuitem(scaling_submenu, x))
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

    def make_scalingvaluemenuitem(self, scaling_submenu, scalingvalue=1.0):
        def scalecmp(v):
            return abs(self.client.xscale-v)<0.1
        pct = iround(100.0*scalingvalue)
        label = {100 : "None"}.get(pct, "%i%%" % pct)
        c = CheckMenuItem(label)
        c.scalingvalue = scalingvalue
        c.set_draw_as_radio(True)
        c.set_active(False)
        def scaling_activated(item):
            if scaling_submenu.updating or not item.get_active():
                return
            ensure_item_selected(scaling_submenu, item)
            self.client.scaleset(item.scalingvalue, item.scalingvalue)
        c.connect('activate', scaling_activated)
        def set_active_state():
            scaling_submenu.updating = True
            c.set_active(scalecmp(scalingvalue))
            scaling_submenu.updating = False
        self.client.after_handshake(set_active_state)
        return c


    def make_qualitymenuitem(self):
        self.quality = self.menuitem("Quality", "slider.png", "Picture quality", None)
        set_sensitive(self.quality, False)
        def may_enable_qualitymenu(*_args):
            self.quality.set_submenu(self.make_qualitysubmenu())
            self.set_qualitymenu()
        self.client.after_handshake(may_enable_qualitymenu)
        return self.quality

    def make_qualitysubmenu(self):
        quality_submenu = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                           self.get_min_quality, self.get_quality,
                                           self.set_min_quality, self.set_quality)
        self.popup_menu_workaround(quality_submenu)
        quality_submenu.show_all()
        return quality_submenu

    def get_min_quality(self):
        return self.client.min_quality
    def get_quality(self):
        return self.client.quality
    def set_min_quality(self, q):
        self.client.min_quality = q
        self.client.quality = -1
        self.client.send_min_quality()
        self.client.send_quality()
    def set_quality(self, q):
        self.client.min_quality = -1
        self.client.quality = q
        self.client.send_min_quality()
        self.client.send_quality()

    def set_qualitymenu(self, *_args):
        if self.quality:
            enc = self.client.encoding
            with_speed = enc in self.client.server_encodings_with_speed or enc in GENERIC_ENCODINGS
            set_sensitive(self.speed, with_speed and not self.client.mmap_enabled)
            if self.client.mmap_enabled:
                self.speed.set_tooltip_text("Quality is always 100% with mmap")
            elif not with_speed:
                self.speed.set_tooltip_text("Not supported with %s encoding" % enc)
            else:
                self.speed.set_tooltip_text("Encoding latency vs size")
            #now check if lossless is supported:
            if self.quality.get_submenu():
                can_lossless = enc in self.client.server_encodings_with_lossless_mode
                for q,item in self.quality.get_submenu().menu_items.items():
                    set_sensitive(item, q<100 or can_lossless)


    def make_speedmenuitem(self):
        self.speed = self.menuitem("Speed", "speed.png", "Encoding latency vs size", None)
        set_sensitive(self.speed, False)
        def may_enable_speedmenu(*_args):
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
        self.client.speed = -1
        self.client.send_min_speed()
        self.client.send_speed()
    def set_speed(self, s):
        self.client.min_speed = -1
        self.client.speed = s
        self.client.send_min_speed()
        self.client.send_speed()


    def set_speedmenu(self, *_args):
        if self.speed:
            can_use = not self.client.mmap_enabled and \
            (self.client.encoding in self.client.server_encodings_with_speed or self.client.encoding in GENERIC_ENCODINGS)
            set_sensitive(self.speed, can_use)
            if self.client.mmap_enabled:
                self.speed.set_tooltip_text("Quality is always 100% with mmap")
            elif self.client.encoding!="h264":
                self.speed.set_tooltip_text("Not supported with %s encoding" % self.client.encoding)
            else:
                self.speed.set_tooltip_text("Encoding latency vs size")


    def make_audiomenuitem(self):
        audio_menu_item = self.handshake_menuitem("Audio", "audio.png")
        menu = gtk.Menu()
        audio_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_speakermenuitem())
        menu.append(self.make_microphonemenuitem())
        menu.append(self.make_avsyncmenuitem())
        audio_menu_item.show_all()
        return audio_menu_item


    def spk_on(self, *args):
        log("spk_on(%s)", args)
        self.client.start_receiving_sound()
    def spk_off(self, *args):
        log("spk_off(%s)", args)
        self.client.stop_receiving_sound()
    def make_speakermenuitem(self):
        speaker = self.menuitem("Speaker", "speaker.png", "Forward sound output from the server")
        set_sensitive(speaker, False)
        def is_speaker_on(*_args):
            return self.client.speaker_enabled
        def speaker_state(*_args):
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
        def is_microphone_on(*_args):
            return self.client.microphone_enabled
        def microphone_state(*_args):
            if not self.client.microphone_allowed:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Microphone forwarding has been disabled")
                return
            if not self.client.server_sound_receive:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Server does not support microphone forwarding")
                return
            set_sensitive(microphone, True)
            microphone.set_submenu(self.make_soundsubmenu(is_microphone_on,
                                                          self.mic_on, self.mic_off, "microphone-changed"))
        self.client.after_handshake(microphone_state)
        return microphone

    def sound_submenu_activate(self, item, menu, cb):
        log("submenu_uncheck(%s, %s, %s) ignore_events=%s, active=%s",
            item, menu, cb, menu.ignore_events, item.get_active())
        if menu.ignore_events:
            return
        ensure_item_selected(menu, item)
        if item.get_active():
            cb()

    def make_soundsubmenu(self, is_on_cb, on_cb, off_cb, client_signal):
        menu = gtk.Menu()
        menu.ignore_events = False
        def onoffitem(label, active, cb):
            c = CheckMenuItem(label)
            c.set_draw_as_radio(True)
            c.set_active(active)
            set_sensitive(c, True)
            c.connect('activate', self.sound_submenu_activate, menu, cb)
            return c
        is_on = is_on_cb()
        on = onoffitem("On", is_on, on_cb)
        off = onoffitem("Off", not is_on, off_cb)
        menu.append(on)
        menu.append(off)
        def update_soundsubmenu_state(*args):
            menu.ignore_events = True
            is_on = is_on_cb()
            log("update_soundsubmenu_state%s is_on=%s", args, is_on)
            if is_on:
                if not on.get_active():
                    on.set_active(True)
                    ensure_item_selected(menu, on)
            else:
                if not off.get_active():
                    off.set_active(True)
                    ensure_item_selected(menu, off)
            menu.ignore_events = False
        self.client.connect(client_signal, update_soundsubmenu_state)
        self.client.after_handshake(update_soundsubmenu_state)
        self.popup_menu_workaround(menu)
        menu.show_all()
        return menu

    def make_avsyncmenuitem(self):
        sync = self.menuitem("Video Sync", "video.png", "Synchronize audio and video", None)
        menu = gtk.Menu()
        self.popup_menu_workaround(menu)
        current_value = 0
        if not self.client.av_sync:
            current_value = None
        def syncitem(label, delta=0):
            c = CheckMenuItem(label)
            c.set_draw_as_radio(True)
            c.set_active(current_value==delta)
            def activate_cb(item, *_args):
                avsynclog("activate_cb(%s, %s) delta=%s", item, menu, delta)
                if delta==0:
                    self.client.av_sync = False
                    self.client.send_sound_sync(0)
                else:
                    self.client.av_sync = True
                    self.client.av_sync_delta = delta
                    #the actual sync value will be calculated and sent
                    #in client._process_sound_data
            c.connect("toggled", activate_cb, menu)
            return c
        menu.append(syncitem("Off", None))
        menu.append(gtk.SeparatorMenuItem())
        menu.append(syncitem("-200", -200))
        menu.append(syncitem("-100", -100))
        menu.append(syncitem(" -50", -50))
        menu.append(syncitem("Auto", 0))
        menu.append(syncitem(" +50", 50))
        menu.append(syncitem(" +100", 100))
        menu.append(syncitem(" +200", 200))
        sync.set_submenu(menu)
        sync.show_all()
        def set_avsyncmenu(*_args):
            if not self.client.server_av_sync:
                set_sensitive(sync, False)
                sync.set_tooltip_text("video-sync is not supported by the server")
                return
            if not (self.client.speaker_allowed and self.client.server_sound_send):
                set_sensitive(sync, False)
                sync.set_tooltip_text("video-sync requires speaker forwarding")
                return
            set_sensitive(sync, True)
        self.client.after_handshake(set_avsyncmenu)
        return sync


    def make_webcammenuitem(self):
        webcam = self.menuitem("Webcam", "webcam.png")
        if not self.client.webcam_forwarding:
            webcam.set_tooltip_text("Webcam forwarding is disabled")
            set_sensitive(webcam, False)
            return webcam
        from xpra.platform.webcam import (
            get_all_video_devices,
            get_virtual_video_devices,
            add_video_device_change_callback,
            )
        #TODO: register remove_video_device_change_callback for cleanup
        menu = gtk.Menu()
        self.popup_menu_workaround(menu)
        #so we can toggle the menu items without causing yet more events and infinite loops:
        menu.ignore_events = False
        def deviceitem(label, cb, device_no=0):
            c = CheckMenuItem(label)
            c.set_draw_as_radio(True)
            c.set_active(get_active_device_no()==device_no)
            c.device_no = device_no
            def activate_cb(item, *_args):
                webcamlog("activate_cb(%s, %s) ignore_events=%s", item, menu, menu.ignore_events)
                if not menu.ignore_events:
                    try:
                        menu.ignore_events = True
                        ensure_item_selected(menu, item)
                        cb(device_no)
                    finally:
                        menu.ignore_events = False
            c.connect("toggled", activate_cb, menu)
            return c
        def start_webcam(device_no=0):
            webcamlog("start_webcam(%s)", device_no)
            self.client.do_start_sending_webcam(device_no)
        def stop_webcam(device_no=0):
            webcamlog("stop_webcam(%s)", device_no)
            self.client.stop_sending_webcam()

        def get_active_device_no():
            if self.client.webcam_device is None:
                return -1
            return self.client.webcam_device_no

        def populate_webcam_menu():
            menu.ignore_events = True
            webcamlog("populate_webcam_menu()")
            for x in menu.get_children():
                menu.remove(x)
            all_video_devices = get_all_video_devices()     #pylint: disable=assignment-from-none
            off_label = "Off"
            if all_video_devices is None:
                #None means that this platform cannot give us the device names,
                #so we just use a single "On" menu item and hope for the best
                on = deviceitem("On", start_webcam)
                menu.append(on)
            else:
                on = None
                virt_devices = get_virtual_video_devices()
                non_virtual = dict((k,v) for k,v in all_video_devices.items() if k not in virt_devices)
                for device_no,info in non_virtual.items():
                    label = bytestostr(info.get("card", info.get("device", str(device_no))))
                    item = deviceitem(label, start_webcam, device_no)
                    menu.append(item)
                if not non_virtual:
                    off_label = "No devices found"
            off = deviceitem(off_label, stop_webcam, -1)
            set_sensitive(off, off_label=="Off")
            menu.append(off)
            menu.show_all()
            menu.ignore_events = False
        populate_webcam_menu()

        def video_devices_changed(added=None, device=None):
            if added is not None and device:
                log.info("video device %s: %s", ["removed", "added"][added], device)
            else:
                log("video_devices_changed")
            #this callback runs in another thread,
            #and we want to wait for the devices to settle
            #so that the file permissions are correct when we try to access it:
            glib.timeout_add(1000, populate_webcam_menu)
        add_video_device_change_callback(video_devices_changed)

        webcam.set_submenu(menu)
        def webcam_changed(*args):
            webcamlog("webcam_changed%s webcam_device=%s", args, self.client.webcam_device)
            if not self.client.webcam_forwarding:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Webcam forwarding is disabled")
                return
            if self.client.server_virtual_video_devices<=0 or not self.client.server_webcam:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Server does not support webcam forwarding")
                return
            webcam.set_tooltip_text("")
            set_sensitive(webcam, True)
            webcamlog("webcam_changed%s active device no=%s", args, get_active_device_no())
            menu.ignore_events = True
            for x in menu.get_children():
                x.set_active(x.device_no==get_active_device_no())
            menu.ignore_events = False
        self.client.connect("webcam-changed", webcam_changed)
        set_sensitive(webcam, False)
        self.client.after_handshake(webcam_changed)
        self.client.on_server_setting_changed("webcam", webcam_changed)
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
                if layout!=kh.layout_option or variant!=kh.variant_option:
                    if layout=="Auto":
                        #re-detect everything:
                        msg = "keyboard automatic mode"
                    else:
                        #use layout specified and send it:
                        kh.layout_option = layout
                        kh.variant_option = variant
                        msg = "new keyboard layout selected"
                    kh.update()
                    kh.send_layout()
                    kh.send_keymap()
                    log.info("%s: %s", msg, kh.layout_str())
            l = self.checkitem(title, set_layout, active)
            l.set_draw_as_radio(True)
            l.keyboard_layout = layout
            l.keyboard_variant = variant
            return l
        def keysort(key):
            c,l = key
            return c.lower()+l.lower()
        layout, layouts, variant, variants, _ = self.client.keyboard_helper.get_layout_spec()
        layout = bytestostr(layout)
        layouts = tuple(bytestostr(x) for x in layouts)
        variant = bytestostr(variant or b"")
        variants = tuple(bytestostr(x) for x in variants)
        full_layout_list = False
        if len(layouts)>1:
            log("keyboard layouts: %s", u",".join(bytestostr(x) for x in layouts))
            #log after removing dupes:
            def uniq(seq):
                seen = set()
                return [x for x in seq if not (x in seen or seen.add(x))]
            log("keyboard layouts: %s", u",".join(bytestostr(x) for x in uniq(layouts)))
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
        def set_layout_enabled(*_args):
            if full_layout_list and \
            (keyboard_helper.xkbmap_layout or keyboard_helper.xkbmap_print or keyboard_helper.xkbmap_query):
                #we have detected a layout
                #so no need to show the user the huge layout list
                keyboard.hide()
                return
            set_sensitive(keyboard, True)
        self.client.after_handshake(set_layout_enabled)
        return keyboard


    def make_windowsmenuitem(self):
        windows_menu_item = self.handshake_menuitem("Windows", "windows.png")
        menu = gtk.Menu()
        windows_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_raisewindowsmenuitem())
        menu.append(self.make_minimizewindowsmenuitem())
        menu.append(self.make_refreshmenuitem())
        menu.append(self.make_reinitmenuitem())
        windows_menu_item.show_all()
        return windows_menu_item

    def make_refreshmenuitem(self):
        def force_refresh(*_args):
            log("force refresh")
            self.client.send_refresh_all()
            self.client.reinit_window_icons()
        return self.handshake_menuitem("Refresh", "retry.png", None, force_refresh)

    def make_reinitmenuitem(self):
        def force_reinit(*_args):
            log("force reinit")
            self.client.reinit_windows()
            self.client.reinit_window_icons()
        return self.handshake_menuitem("Re-initialize", "reinitialize.png", None, force_reinit)

    def make_raisewindowsmenuitem(self):
        def raise_windows(*_args):
            for win in self.client._window_to_id:
                if not win.is_OR():
                    win.deiconify()
                    win.present()
        return self.handshake_menuitem("Raise Windows", "raise.png", None, raise_windows)

    def make_minimizewindowsmenuitem(self):
        def minimize_windows(*_args):
            for win in self.client._window_to_id:
                if not win.is_OR():
                    win.iconify()
        return self.handshake_menuitem("Minimize Windows", "minimize.png", None, minimize_windows)


    def make_servermenuitem(self):
        server_menu_item = self.handshake_menuitem("Server", "server.png")
        menu = gtk.Menu()
        server_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        if RUNCOMMAND_MENU:
            menu.append(self.make_runcommandmenuitem())
        if SHOW_SERVER_COMMANDS:
            menu.append(self.make_servercommandsmenuitem())
        if SHOW_TRANSFERS:
            menu.append(self.make_servertransfersmenuitem())
        if SHOW_UPLOAD:
            menu.append(self.make_uploadmenuitem())
        if SHOW_SHUTDOWN:
            menu.append(self.make_shutdownmenuitem())
        server_menu_item.show_all()
        return server_menu_item

    def make_servercommandsmenuitem(self):
        self.servercommands = self.menuitem("Server Commands", "list.png",
                                            "Commands running on the server",
                                            self.client.show_server_commands)
        def enable_servercommands(*args):
            log("enable_servercommands%s server-commands-info=%s", args, self.client.server_commands_info)
            set_sensitive(self.servercommands, self.client.server_commands_info)
            if not self.client.server_commands_info:
                self.servercommands.set_tooltip_text("Not supported by the server")
            else:
                self.servercommands.set_tooltip_text("")
        self.client.after_handshake(enable_servercommands)
        return self.servercommands

    def make_runcommandmenuitem(self):
        self.startnewcommand = self.menuitem("Run Command", "forward.png",
                                             "Run a new command on the server",
                                             self.client.show_start_new_command)
        def enable_start_new_command(*args):
            log("enable_start_new_command%s start_new_command=%s", args, self.client.server_start_new_commands)
            set_sensitive(self.startnewcommand, self.client.server_start_new_commands)
            if not self.client.server_start_new_commands:
                self.startnewcommand.set_tooltip_text("Not supported or enabled on the server")
            else:
                self.startnewcommand.set_tooltip_text("")
        self.client.after_handshake(enable_start_new_command)
        self.client.on_server_setting_changed("start-new-commands", enable_start_new_command)
        return self.startnewcommand

    def make_servertransfersmenuitem(self):
        self.transfers = self.menuitem("Transfers", "transfer.png",
                                       "Files and URLs forwarding",
                                       self.client.show_ask_data_dialog)
        def enable_transfers(*args):
            log("enable_transfers%s ask=%s", args, ())
            has_ask = (self.client.remote_file_transfer_ask or
                       self.client.remote_printing_ask or
                       self.client.remote_open_files_ask or
                       self.client.remote_open_url_ask)
            set_sensitive(self.transfers, has_ask)
        self.client.after_handshake(enable_transfers)
        return self.transfers

    def make_uploadmenuitem(self):
        self.upload = self.menuitem("Upload File", "upload.png", cb=self.client.show_file_upload)
        def enable_upload(*args):
            log("enable_upload%s server_file_transfer=%s", args, self.client.remote_file_transfer)
            set_sensitive(self.upload, self.client.remote_file_transfer)
            if not self.client.remote_file_transfer:
                self.upload.set_tooltip_text("Not supported by the server")
            else:
                self.upload.set_tooltip_text("Send a file to the server")
        self.client.after_handshake(enable_upload)
        return self.upload


    def make_shutdownmenuitem(self):
        def ask_shutdown_confirm(*_args):
            dialog = gtk.MessageDialog (None, 0, MESSAGE_QUESTION,
                                    BUTTONS_NONE,
                                    "Shutting down this session may cause data loss,\n"+
                                    "are you sure you want to proceed?")
            dialog.add_button(gtk.STOCK_CANCEL, 0)
            SHUTDOWN = 1
            dialog.add_button("Shutdown", SHUTDOWN)
            response = dialog.run()
            dialog.close()
            if response == SHUTDOWN:
                self.client.send_shutdown_server()
        self.shutdown = self.menuitem("Shutdown Session", "shutdown.png", cb=ask_shutdown_confirm)
        def enable_shutdown(*args):
            log("enable_shutdown%s can_shutdown_server=%s", args, self.client.server_client_shutdown)
            set_sensitive(self.shutdown, self.client.server_client_shutdown)
            if not self.client.server_client_shutdown:
                self.shutdown.set_tooltip_text("Disabled by the server")
            else:
                self.shutdown.set_tooltip_text("Shutdown this server session")
        self.client.after_handshake(enable_shutdown)
        self.client.on_server_setting_changed("client-shutdown", enable_shutdown)
        return self.shutdown

    def make_startmenuitem(self):
        start_menu_item = self.handshake_menuitem("Start", "start.png")
        start_menu_item.show()
        def update_menu_data():
            if not self.client.server_start_new_commands:
                set_sensitive(start_menu_item, False)
                start_menu_item.set_tooltip_text("This server does not support starting new commands")
                return
            if not self.client.server_xdg_menu:
                set_sensitive(start_menu_item, False)
                start_menu_item.set_tooltip_text("This server does not provide start menu data")
                return
            set_sensitive(start_menu_item, True)
            menu = self.build_start_menu()
            start_menu_item.set_submenu(menu)
        def start_menu_init():
            update_menu_data()
            def on_xdg_menu_changed(setting, value):
                log("on_xdg_menu_changed(%s, %s)", setting, repr_ellipsized(str(value)))
                update_menu_data()
            self.client.on_server_setting_changed("xdg-menu", on_xdg_menu_changed)
        self.client.after_handshake(start_menu_init)
        return start_menu_item

    def build_start_menu(self):
        menu = gtk.Menu()
        self.popup_menu_workaround(menu)
        log("build_start_menu() %i menu items", len(self.client.server_xdg_menu))
        for category, category_props in sorted(self.client.server_xdg_menu.items()):
            log("build_start_menu() category: %s", category)
            #log("category_props(%s)=%s", category, category_props)
            if not isinstance(category_props, dict):
                continue
            category_props = typedict(category_props)
            entries = category_props.rawget(b"Entries", {})
            if not entries:
                continue
            icondata = category_props.rawget(b"IconData")
            category_menu_item = self.start_menuitem(s(category), icondata)
            cat_menu = gtk.Menu()
            category_menu_item.set_submenu(cat_menu)
            self.popup_menu_workaround(cat_menu)
            menu.append(category_menu_item)
            for app_name, command_props in sorted(entries.items()):
                log("build_start_menu() app_name=%s", app_name)
                app_menu_item = self.make_applaunch_menu_item(s(app_name), command_props)
                cat_menu.append(app_menu_item)
        menu.show_all()
        return menu

    def get_appimage(self, app_name, icondata=None):
        pixbuf = None
        if app_name and not icondata:
            #try to load from our icons:
            try:
                nstr = app_name.decode("utf-8").lower()
            except UnicodeDecodeError:
                nstr = bytestostr(app_name).lower()
            icon_filename = os.path.join(get_icon_dir(), "%s.png" % nstr)
            if os.path.exists(icon_filename):
                from xpra.gtk_common.gtk_util import pixbuf_new_from_file
                pixbuf = pixbuf_new_from_file(icon_filename)
        if not pixbuf and icondata:
            #gtk pixbuf loader:
            try:
                loader = import_pixbufloader()()
                loader.write(icondata)
                loader.close()
                pixbuf = loader.get_pixbuf()
            except Exception:
                log.error("Error: failed to load icon data for %s", bytestostr(app_name), exc_info=True)
                log.error(" data=%s", repr_ellipsized(icondata))
        if not pixbuf and icondata:
            #let's try pillow:
            try:
                from xpra.codecs.pillow.decoder import open_only
                img = open_only(icondata)
                has_alpha = img.mode=="RGBA"
                width, height = img.size
                rowstride = width * (3+int(has_alpha))
                pixbuf = get_pixbuf_from_data(img.tobytes(), has_alpha, width, height, rowstride)
                return scaled_image(pixbuf, icon_size=self.menu_icon_size)
            except Exception:
                log.error("Error: failed to load icon data for %s", bytestostr(app_name), exc_info=True)
                log.error(" data=%s", repr_ellipsized(icondata))
        if pixbuf:
            return scaled_image(pixbuf, icon_size=self.menu_icon_size)
        return None

    def start_menuitem(self, title, icondata=None):
        smi = self.handshake_menuitem(title)
        if icondata:
            image = self.get_appimage(title, icondata)
            if image:
                smi.set_image(image)
        return smi

    def make_applaunch_menu_item(self, app_name, command_props):
        command_props = typedict(command_props)
        icondata = command_props.get(b"IconData")
        app_menu_item = self.start_menuitem(app_name, icondata)
        def app_launch(*args):
            log("app_launch(%s) command_props=%s", args, command_props)
            command = command_props.get(b"command")
            try:
                command = re.sub(b'\\%[fFuU]', b'', command)
            except Exception:
                log("re substitution failed", exc_info=True)
                command = command.split(b"%", 1)[0]
            log("command=%s", command)
            if command:
                self.client.send_start_command(app_name, command, False, self.client.server_sharing)
        app_menu_item.connect("activate", app_launch)
        return app_menu_item


    def make_disconnectmenuitem(self):
        def menu_quit(*_args):
            self.client.disconnect_and_quit(EXIT_OK, CLIENT_EXIT)
        return self.handshake_menuitem("Disconnect", "quit.png", None, menu_quit)


    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)


    def popup_menu_workaround(self, menu):
        popup_menu_workaround(menu, self.close_menu)
