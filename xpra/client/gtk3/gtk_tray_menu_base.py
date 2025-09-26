# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from gi.repository import GLib, Gtk  # @UnresolvedImport
from typing import Optional

from xpra.util import (
    ConnectionMessage,
    envbool, u,
    ellipsizer, repr_ellipsized, reverse_dict, typedict,
    )
from xpra.os_util import bytestostr, OSX, WIN32
from xpra.common import RESOLUTION_ALIASES
from xpra.client.gtk3.menu_helper import (
    MenuHelper,
    BANDWIDTH_MENU_OPTIONS,
    QUALITY_OPTIONS, MIN_QUALITY_OPTIONS,
    SPEED_OPTIONS, MIN_SPEED_OPTIONS,
    get_appimage,
    ll, set_sensitive, ensure_item_selected,
    make_encodingsmenu, make_min_auto_menu,
    )
from xpra.exit_codes import ExitCode
from xpra.codecs.codec_constants import PREFERRED_ENCODING_ORDER
from xpra.simple_stats import std_unit_dec
from xpra.client.gui import mixin_features
from xpra.log import Logger

log = Logger("menu")
execlog = Logger("exec")
clipboardlog = Logger("menu", "clipboard")
webcamlog = Logger("menu", "webcam")
avsynclog = Logger("menu", "av-sync")
bandwidthlog = Logger("bandwidth", "network")

SHOW_TITLE_ITEM = envbool("XPRA_SHOW_TITLE_ITEM", True)
SHOW_VERSION_CHECK = envbool("XPRA_SHOW_VERSION_CHECK", True)
SHOW_QR = envbool("XPRA_SHOW_QR", True)
SHOW_UPLOAD = envbool("XPRA_SHOW_UPLOAD_MENU", True)
SHOW_SERVER_LOG = envbool("XPRA_SHOW_SERVER_LOG", True)
SHOW_DOWNLOAD = envbool("XPRA_SHOW_DOWNLOAD", True)
STARTSTOP_SOUND_MENU = envbool("XPRA_SHOW_SOUND_MENU", True)
WEBCAM_MENU = envbool("XPRA_SHOW_WEBCAM_MENU", True)
RUNCOMMAND_MENU = envbool("XPRA_SHOW_RUNCOMMAND_MENU", True)
SHOW_SERVER_COMMANDS = envbool("XPRA_SHOW_SERVER_COMMANDS", True)
SHOW_TRANSFERS = envbool("XPRA_SHOW_TRANSFERS", True)
SHOW_CLIPBOARD_MENU = envbool("XPRA_SHOW_CLIPBOARD_MENU", True)
SHOW_CLOSE = envbool("XPRA_SHOW_CLOSE", True)
SHOW_SHUTDOWN = envbool("XPRA_SHOW_SHUTDOWN", True)
MONITORS_MENU = envbool("XPRA_SHOW_MONITORS_MENU", True)
WINDOWS_MENU = envbool("XPRA_SHOW_WINDOWS_MENU", True)
START_MENU = envbool("XPRA_SHOW_START_MENU", True)
MENU_ICONS = envbool("XPRA_MENU_ICONS", True)

FULL_LAYOUT_LIST = envbool("XPRA_FULL_LAYOUT_LIST", True)

NEW_MONITOR_RESOLUTIONS = os.environ.get("XPRA_NEW_MONITOR_RESOLUTIONS",
                                         "640x480,1024x768,1600x1200,FHD,4K").split(",")

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

SERVER_NOT_SUPPORTED = "Not supported by the server"

GENERIC_ENCODINGS = ("", "auto", "stream", "grayscale")



class GTKTrayMenuBase(MenuHelper):

    def setup_menu(self):
        return self.do_setup_menu(SHOW_CLOSE)

    def do_setup_menu(self, show_close):
        log("setup_menu(%s)", show_close)
        menu = Gtk.Menu()
        def add(menuitem):
            if menuitem:
                menu.append(menuitem)
        title_item = None
        if SHOW_TITLE_ITEM:
            title_item = Gtk.MenuItem()
            title_item.set_label(self.client.session_name or "Xpra")
            set_sensitive(title_item, False)
            add(title_item)
            def set_menu_title(*_args):
                #set the real name when available:
                try:
                    title = self.client.get_tray_title()
                except Exception:
                    title = self.client.session_name or "Xpra"
                title_item.set_label(title)
            self.after_handshake(set_menu_title)
        add(self.make_infomenuitem())
        add(self.make_featuresmenuitem())
        if mixin_features.windows and self.client.keyboard_helper:
            add(self.make_keyboardmenuitem())
        if mixin_features.clipboard and SHOW_CLIPBOARD_MENU:
            add(self.make_clipboardmenuitem())
        if mixin_features.windows:
            add(self.make_picturemenuitem())
        if mixin_features.audio and STARTSTOP_SOUND_MENU:
            add(self.make_audiomenuitem())
        if mixin_features.webcam and WEBCAM_MENU:
            add(self.make_webcammenuitem())
        if mixin_features.display and MONITORS_MENU:
            add(self.make_monitorsmenuitem())
        if mixin_features.windows and WINDOWS_MENU:
            add(self.make_windowsmenuitem())
        if RUNCOMMAND_MENU or SHOW_SERVER_COMMANDS or SHOW_UPLOAD or SHOW_SHUTDOWN:
            add(self.make_servermenuitem())
        if mixin_features.windows and START_MENU:
            add(self.make_startmenuitem())
        add(self.make_disconnectmenuitem())
        if show_close:
            add(self.make_closemenuitem())
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        log("setup_menu(%s) done", show_close)
        return menu

    def make_infomenuitem(self):
        info_menu_item = self.menuitem("Information", "information.png")
        menu = Gtk.Menu()
        info_menu_item.set_submenu(menu)
        def add(menuitem):
            if menuitem:
                menu.append(menuitem)
        add(self.make_aboutmenuitem())
        add(self.make_sessioninfomenuitem())
        if SHOW_QR:
            add(self.make_qrmenuitem())
        if SHOW_VERSION_CHECK:
            add(self.make_updatecheckmenuitem())
        add(self.make_bugreportmenuitem())
        add(self.make_docsmenuitem())
        add(self.make_html5menuitem())
        info_menu_item.show_all()
        return info_menu_item

    def make_featuresmenuitem(self):
        features_menu_item = self.handshake_menuitem("Features", "features.png")
        menu = Gtk.Menu()
        self.append_featuresmenuitems(menu)
        features_menu_item.set_submenu(menu)
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
        self.after_handshake(set_sharing_menuitem)
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
        self.after_handshake(set_lock_menuitem)
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
        self.after_handshake(set_readonly_menuitem)
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
        self.after_handshake(set_bell_menuitem)
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
        self.after_handshake(set_cursors_menuitem)
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
        self.after_handshake(set_notifications_menuitem)
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
        selection_submenu = Gtk.Menu()
        selection_menu.set_submenu(selection_submenu)
        rc_setting = None
        if len(ch._local_to_remote)==1:
            rc_setting = tuple(ch._local_to_remote.values())[0]
        for label in CLIPBOARD_LABELS:
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
            selection_item = Gtk.CheckMenuItem(label=label)
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
            clipboard_submenu = Gtk.Menu()
            self.clipboard_menuitem.set_submenu(clipboard_submenu)
            if WIN32 or OSX:
                #add a submenu to change the selection we synchronize with
                #since this platform only has a single clipboard
                try:
                    clipboardlog("set_clipboard_menu(%s) helper=%s, server=%s, client=%s",
                                 args, ch, c.server_clipboard, c.client_supports_clipboard)
                    clipboard_submenu.append(self.make_translatedclipboard_optionsmenuitem())
                    clipboard_submenu.append(Gtk.SeparatorMenuItem())
                except ImportError:
                    clipboardlog.error("make_clipboardmenuitem()", exc_info=True)
            items = []
            for label in CLIPBOARD_DIRECTION_LABELS:
                direction_item = Gtk.CheckMenuItem(label=label)
                d = CLIPBOARD_DIRECTION_LABEL_TO_NAME.get(label)
                direction_item.set_active(d==self.client.client_clipboard_direction)
                clipboard_submenu.append(direction_item)
                items.append(direction_item)
            clipboard_submenu.show_all()
            #connect signals:
            for direction_item in items:
                direction_item.connect("toggled", self.clipboard_direction_changed, clipboard_submenu)
        self.after_handshake(set_clipboard_menu)
        return self.clipboard_menuitem


    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip():
            kh = self.client.keyboard_helper
            if not kh:
                text = "Keyboard support is not loaded"
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
        self.keyboard_sync_menuitem = self.checkitem("State Synchronization")
        set_sensitive(self.keyboard_sync_menuitem, False)
        def set_keyboard_sync_menuitem(*args):
            kh = self.client.keyboard_helper
            can_set_sync = kh and self.client.server_keyboard
            set_sensitive(self.keyboard_sync_menuitem, can_set_sync)
            if can_set_sync:
                self.keyboard_sync_menuitem.connect("toggled", keyboard_sync_toggled)
            if kh:
                log("set_keyboard_sync_menuitem%s enabled=%s", args, kh.keyboard_sync)
            self.keyboard_sync_menuitem.set_active(kh and bool(kh.keyboard_sync))
            set_keyboard_sync_tooltip()
        self.after_handshake(set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_shortcutsmenuitem(self):
        self.keyboard_shortcuts_menuitem = self.checkitem("Intercept Shortcuts")
        kh = self.client.keyboard_helper
        self.keyboard_shortcuts_menuitem.set_active(kh and bool(kh.shortcuts_enabled))
        def keyboard_shortcuts_toggled(*args):
            ks = self.keyboard_shortcuts_menuitem.get_active()
            log("keyboard_shortcuts_toggled%s enabled=%s", args, ks)
            kh.shortcuts_enabled = ks
        self.keyboard_shortcuts_menuitem.connect("toggled", keyboard_shortcuts_toggled)
        return self.keyboard_shortcuts_menuitem

    def make_viewshortcutsmenuitem(self):
        def show_shortcuts(*_args):
            self.client.show_shortcuts()
        return self.menuitem("View Shortcuts", tooltip="Show all active keyboard shortcuts", cb=show_shortcuts)


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
        self.after_handshake(gl_set)
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
        self.after_handshake(set_modal_menuitem)
        modal.connect("toggled", modal_toggled)
        return modal

    def make_picturemenuitem(self):
        picture_menu_item = self.handshake_menuitem("Picture", "picture.png")
        menu = Gtk.Menu()
        picture_menu_item.set_submenu(menu)
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
        menu = Gtk.Menu()
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
                menu.append(Gtk.SeparatorMenuItem())
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
        self.after_handshake(set_bwlimitmenu)
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
        c = Gtk.CheckMenuItem(label=label)
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
        self.encodings_submenu = None
        def set_encodingsmenuitem(*args):
            log("set_encodingsmenuitem%s", args)
            set_sensitive(encodings, not self.client.mmap_enabled)
            if self.client.mmap_enabled:
                #mmap disables encoding and uses raw rgb24
                encodings.set_label("Encoding")
                encodings.set_tooltip_text("memory mapped transfers are in use so picture encoding is disabled")
            else:
                self.encodings_submenu = self.make_encodingssubmenu()
                encodings.set_submenu(self.encodings_submenu)
        self.after_handshake(set_encodingsmenuitem)
        #FUGLY warning: we want to update the menu if we get an 'encodings' packet,
        #so we inject our handler:
        saved_process_encodings = getattr(self.client, "_process_encodings")
        if saved_process_encodings:
            def process_encodings(*args):
                #pass it on:
                saved_process_encodings(*args)
                #re-generate the menu with the correct server properties:
                GLib.idle_add(set_encodingsmenuitem)
            self.client._process_encodings = process_encodings
        return encodings

    def get_encoding_options(self):
        server_encodings = list(self.client.server_encodings)
        client_encodings = [x for x in PREFERRED_ENCODING_ORDER if x in self.client.get_encodings()]
        #separator:
        client_encodings.insert(0, "-")
        server_encodings.insert(0, "-")
        client_encodings.insert(1, "label:Don't use these directly:")
        server_encodings.insert(1, "label:Don't use these directly:")
        if "grayscale" in client_encodings and "grayscale" in server_encodings:
            #move grayscale to the top:
            client_encodings.remove("grayscale")
            server_encodings.remove("grayscale")
            client_encodings.insert(0, "grayscale")
            server_encodings.insert(0, "grayscale")
        #auto at the very top:
        client_encodings.insert(0, "auto")
        server_encodings.insert(0, "auto")
        client_encodings.insert(1, "stream")
        server_encodings.insert(1, "stream")
        return client_encodings, server_encodings

    def make_encodingssubmenu(self):
        client_encodings, server_encodings = self.get_encoding_options()
        encodings_submenu = make_encodingsmenu(self.get_current_encoding,
                                               self.set_current_encoding,
                                               client_encodings, server_encodings)
        return encodings_submenu

    def get_current_encoding(self):
        return self.client.encoding
    def set_current_encoding(self, enc):
        self.client.set_encoding(enc)
        #these menus may need updating now:
        self.set_qualitymenu()
        self.set_speedmenu()


    def make_scalingmenuitem(self):
        self.scaling = self.menuitem("Scaling", "scaling.png", "Desktop Scaling")
        scaling_submenu = self.make_scalingmenu()
        self.scaling.set_submenu(scaling_submenu)
        return self.scaling

    def make_scalingmenu(self):
        scaling_submenu = Gtk.Menu()
        scaling_submenu.updating = False
        from xpra.scaling_parser import SCALING_OPTIONS
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
        pct = round(100.0*scalingvalue)
        label = {100 : "None"}.get(pct, "%i%%" % pct)
        c = Gtk.CheckMenuItem(label=label)
        c.scalingvalue = scalingvalue
        c.set_draw_as_radio(True)
        c.set_active(False)
        def scaling_activated(item):
            log("scaling_activated(%s) scaling_value=%s, active=%s",
                item, scalingvalue, item.get_active())
            if scaling_submenu.updating or not item.get_active():
                return
            ensure_item_selected(scaling_submenu, item)
            self.client.scaleset(item.scalingvalue, item.scalingvalue)
        c.connect('activate', scaling_activated)
        def set_active_state():
            scaling_submenu.updating = True
            c.set_active(scalecmp(scalingvalue))
            scaling_submenu.updating = False
        self.after_handshake(set_active_state)
        return c


    def make_qualitymenuitem(self):
        self.quality = self.menuitem("Quality", "slider.png", "Picture quality", None)
        set_sensitive(self.quality, False)
        def may_enable_qualitymenu(*_args):
            self.quality.set_submenu(self.make_qualitysubmenu())
            self.set_qualitymenu()
        self.after_handshake(may_enable_qualitymenu)
        return self.quality

    def make_qualitysubmenu(self):
        quality_submenu = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                           self.get_min_quality, self.get_quality,
                                           self.set_min_quality, self.set_quality)
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
            can_use = not self.client.mmap_enabled and \
            (self.client.encoding in self.client.server_encodings_with_quality or self.client.encoding in GENERIC_ENCODINGS)
            set_sensitive(self.quality, can_use)
            if self.client.mmap_enabled:
                self.quality.set_tooltip_text("Speed is always 100% with mmap")
                return
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
        def may_enable_speedmenu(*_args):
            self.speed.set_submenu(self.make_speedsubmenu())
            self.set_speedmenu()
        self.after_handshake(may_enable_speedmenu)
        return self.speed

    def make_speedsubmenu(self):
        speed_submenu = make_min_auto_menu("Speed", MIN_SPEED_OPTIONS, SPEED_OPTIONS,
                                           self.get_min_speed, self.get_speed, self.set_min_speed, self.set_speed)
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
            enc = self.client.encoding
            with_speed = enc in self.client.server_encodings_with_speed or enc in GENERIC_ENCODINGS
            set_sensitive(self.speed, with_speed and not self.client.mmap_enabled)
            if self.client.mmap_enabled:
                self.speed.set_tooltip_text("Quality is always 100% with mmap")
            elif not with_speed:
                self.speed.set_tooltip_text("Not supported with %s encoding" % enc)
            else:
                self.speed.set_tooltip_text("Encoding latency vs size")


    def make_audiomenuitem(self):
        audio_menu_item = self.handshake_menuitem("Audio", "audio.png")
        menu = Gtk.Menu()
        audio_menu_item.set_submenu(menu)
        menu.append(self.make_speakermenuitem())
        menu.append(self.make_microphonemenuitem())
        menu.append(self.make_avsyncmenuitem())
        audio_menu_item.show_all()
        return audio_menu_item


    def spk_on(self, *args):
        log("spk_on(%s)", args)
        self.client.start_receiving_audio()
    def spk_off(self, *args):
        log("spk_off(%s)", args)
        self.client.stop_receiving_audio()
    def make_speakermenuitem(self):
        speaker = self.menuitem("Speaker", "speaker.png", "Forward audio output from the server")
        set_sensitive(speaker, False)
        def is_speaker_on(*_args):
            return self.client.speaker_enabled
        def speaker_state(*_args):
            if not self.client.speaker_allowed:
                set_sensitive(speaker, False)
                speaker.set_tooltip_text("Speaker forwarding has been disabled")
                return
            if not self.client.server_audio_send:
                set_sensitive(speaker, False)
                speaker.set_tooltip_text("Server does not support speaker forwarding")
                return
            set_sensitive(speaker, True)
            speaker.set_submenu(self.make_audiosubmenu(is_speaker_on, self.spk_on, self.spk_off, "speaker-changed"))
        self.after_handshake(speaker_state)
        return speaker

    def mic_on(self, *args):
        log("mic_on(%s)", args)
        self.client.start_sending_audio()
    def mic_off(self, *args):
        log("mic_off(%s)", args)
        self.client.stop_sending_audio()
    def make_microphonemenuitem(self):
        microphone = self.menuitem("Microphone", "microphone.png", "Forward audio input to the server", None)
        set_sensitive(microphone, False)
        def is_microphone_on(*_args):
            return self.client.microphone_enabled
        def microphone_state(*_args):
            if not self.client.microphone_allowed:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Microphone forwarding has been disabled")
                return
            if not self.client.server_audio_receive:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Server does not support microphone forwarding")
                return
            set_sensitive(microphone, True)
            microphone.set_submenu(self.make_audiosubmenu(is_microphone_on,
                                                          self.mic_on, self.mic_off, "microphone-changed"))
        self.after_handshake(microphone_state)
        return microphone

    def audio_submenu_activate(self, item, menu, cb):
        log("audio_submenu_activate(%s, %s, %s) ignore_events=%s, active=%s",
            item, menu, cb, menu.ignore_events, item.get_active())
        if menu.ignore_events:
            return
        ensure_item_selected(menu, item)
        if item.get_active():
            cb()

    def make_audiosubmenu(self, is_on_cb, on_cb, off_cb, client_signal):
        menu = Gtk.Menu()
        menu.ignore_events = False
        def onoffitem(label, active, cb):
            c = Gtk.CheckMenuItem(label=label)
            c.set_draw_as_radio(True)
            c.set_active(active)
            set_sensitive(c, True)
            c.connect('activate', self.audio_submenu_activate, menu, cb)
            return c
        is_on = is_on_cb()
        on = onoffitem("On", is_on, on_cb)
        off = onoffitem("Off", not is_on, off_cb)
        menu.append(on)
        menu.append(off)
        def update_audiosubmenu_state(*args):
            menu.ignore_events = True
            is_on = is_on_cb()
            log("update_audiosubmenu_state%s is_on=%s", args, is_on)
            if is_on:
                if not on.get_active():
                    on.set_active(True)
                    ensure_item_selected(menu, on)
            else:
                if not off.get_active():
                    off.set_active(True)
                    ensure_item_selected(menu, off)
            menu.ignore_events = False
        self.client.connect(client_signal, update_audiosubmenu_state)
        self.after_handshake(update_audiosubmenu_state)
        menu.show_all()
        return menu

    def make_avsyncmenuitem(self):
        sync = self.menuitem("Video Sync", "video.png", "Synchronize audio and video", None)
        menu = Gtk.Menu()
        current_value = 0
        if not self.client.av_sync:
            current_value = None
        def syncitem(label, delta:Optional[int]=0):
            c = Gtk.CheckMenuItem(label=label)
            c.set_draw_as_radio(True)
            c.set_active(current_value==delta)
            def activate_cb(item, *_args):
                avsynclog("activate_cb(%s, %s) delta=%s", item, menu, delta)
                if delta is None:
                    self.client.av_sync = False
                    self.client.send_audio_sync(0)
                else:
                    self.client.av_sync = True
                    self.client.av_sync_delta = delta
                    #the actual sync value will be calculated and sent
                    #in client._process_sound_data
            c.connect("toggled", activate_cb, menu)
            return c
        menu.append(syncitem("Off", None))
        menu.append(Gtk.SeparatorMenuItem())
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
            if not (self.client.speaker_allowed and self.client.server_audio_send):
                set_sensitive(sync, False)
                sync.set_tooltip_text("video-sync requires speaker forwarding")
                return
            set_sensitive(sync, True)
        self.after_handshake(set_avsyncmenu)
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
        menu = Gtk.Menu()
        #so we can toggle the menu items without causing yet more events and infinite loops:
        menu.ignore_events = False
        def deviceitem(label, cb, device_no=0):
            c = Gtk.CheckMenuItem(label=label)
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
            GLib.timeout_add(1000, populate_webcam_menu)
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
        self.after_handshake(webcam_changed)
        self.client.on_server_setting_changed("webcam", webcam_changed)
        return webcam


    def make_keyboardmenuitem(self):
        keyboard_menu_item = self.handshake_menuitem("Keyboard", "keyboard.png")
        menu = Gtk.Menu()
        keyboard_menu_item.set_submenu(menu)
        menu.append(self.make_keyboardsyncmenuitem())
        menu.append(self.make_shortcutsmenuitem())
        menu.append(self.make_viewshortcutsmenuitem())
        menu.append(self.make_layoutsmenuitem())
        keyboard_menu_item.show_all()
        return keyboard_menu_item

    def make_layoutsmenuitem(self):
        keyboard = self.menuitem("Layout", "keyboard.png", "Select your keyboard layout", None)
        set_sensitive(keyboard, False)
        self.layout_submenu = Gtk.Menu()
        keyboard.set_submenu(self.layout_submenu)
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
                    log.info(f"{msg}: {kh.layout_str()}")
            l = self.checkitem(str(title), set_layout, active)
            l.set_draw_as_radio(True)
            l.keyboard_layout = layout
            l.keyboard_variant = variant
            return l
        def keysort(key):
            c,l = key
            return c.lower()+l.lower()
        def variants_submenu(layout, variants):
            #just show all the variants to choose from this layout
            default_layout = kbitem(f"{layout} - Default", layout, "", True)
            self.layout_submenu.append(default_layout)
            for v in variants:
                self.layout_submenu.append(kbitem(f"{layout} - {v}", layout, v))
        kh = self.client.keyboard_helper
        layout, layouts, variant, variants, _ = kh.get_layout_spec()
        layout = bytestostr(layout)
        layouts = tuple(bytestostr(x) for x in layouts)
        variant = bytestostr(variant or b"")
        variants = tuple(bytestostr(x) for x in variants)
        log(f"make_layoutsmenuitem() layout={layout}, layouts={layouts}, variant={variant}, variants={variants}")
        if len(layouts)>1:
            log("keyboard layouts: %s", ",".join(bytestostr(x) for x in layouts))
            #log after removing dupes:
            def uniq(seq):
                seen = set()
                return [x for x in seq if not (x in seen or seen.add(x))]
            log("keyboard layouts: %s", ",".join(bytestostr(x) for x in uniq(layouts)))
            auto = kbitem("Auto", "Auto", "", True)
            self.layout_submenu.append(auto)
            if layout:
                self.layout_submenu.append(kbitem(layout, layout, ""))
            if variants:
                for v in variants:
                    self.layout_submenu.append(kbitem(f"{layout} - {v}", layout, v))
            for l in uniq(layouts):
                if l!=layout:
                    self.layout_submenu.append(kbitem(l, l, ""))
        elif layout and len(variants)>1:
            variants_submenu(layout, variants)
        elif layout or kh.query_struct:
            l = layout or kh.query_struct.get("layout", "")
            from xpra.keyboard.layouts import LAYOUT_VARIANTS
            variants = LAYOUT_VARIANTS.get(l) if l else ()
            if variants:
                variants_submenu(l, variants)
            else:
                if l:
                    keyboard.set_tooltip_text(f"Detected {l!r}")
                set_sensitive(keyboard, False)
                return keyboard
        elif not FULL_LAYOUT_LIST:
            keyboard.set_tooltip_text("No keyboard layouts detected")
            set_sensitive(keyboard, False)
            return keyboard
        else:
            from xpra.keyboard.layouts import X11_LAYOUTS
            #show all options to choose from:
            sorted_keys = list(X11_LAYOUTS.keys())
            sorted_keys.sort(key=keysort)
            for key in sorted_keys:
                country,language = key
                layout,variants = X11_LAYOUTS.get(key)
                name = f"{country} - {language}"
                if len(variants)>1:
                    #sub-menu for each variant:
                    variant = self.menuitem(name, tooltip=layout)
                    variant_submenu = Gtk.Menu()
                    variant.set_submenu(variant_submenu)
                    self.layout_submenu.append(variant)
                    variant_submenu.append(kbitem(f"{layout} - Default", layout, None))
                    for v in variants:
                        variant_submenu.append(kbitem(f"{layout} - {v}", layout, v))
                else:
                    #no variants:
                    self.layout_submenu.append(kbitem(name, layout, None))
        self.after_handshake(set_sensitive, keyboard, True)
        return keyboard


    def make_monitorsmenuitem(self):
        monitors_menu_item = self.handshake_menuitem("Monitors", "display.png")
        menu = Gtk.Menu()
        monitors_menu_item.set_submenu(menu)
        def populate_monitors(*args):
            log("populate_monitors%s client server_multi_monitors=%s, server_monitors=%s",
                     args, self.client.server_multi_monitors, self.client.server_monitors)
            if not self.client.server_multi_monitors or not self.client.server_monitors:
                monitors_menu_item.hide()
                return
            for x in menu.get_children():
                menu.remove(x)
            def monitor_changed(mitem, index):
                log("monitor_changed(%s, %s)", mitem, index)
                self.client.send_remove_monitor(index)
            for i, monitor in self.client.server_monitors.items():
                mitem = Gtk.CheckMenuItem(label=monitor.get("name", "VFB-%i" % i))
                mitem.set_active(True)
                mitem.set_draw_as_radio(True)
                mitem.connect("toggled", monitor_changed, i)
                menu.append(mitem)
            #and finally, an entry for adding a new monitor:
            add_monitor_item = self.menuitem("Add a monitor")
            resolutions_menu = Gtk.Menu()
            add_monitor_item.set_submenu(resolutions_menu)
            def add_monitor(mitem, resolution):
                log("add_monitor(%s, %s)", mitem, resolution)
                #older servers may not have all the aliases:
                resolution = RESOLUTION_ALIASES.get(resolution, resolution)
                self.client.send_add_monitor(resolution)
            for resolution in NEW_MONITOR_RESOLUTIONS:
                mitem = self.menuitem(resolution)
                mitem.connect("activate", add_monitor, resolution)
                resolutions_menu.append(mitem)
            resolutions_menu.show_all()
            menu.append(add_monitor_item)
            menu.show_all()
        self.client.on_server_setting_changed("monitors", populate_monitors)
        self.after_handshake(populate_monitors)
        monitors_menu_item.show_all()
        return monitors_menu_item


    def make_windowsmenuitem(self):
        windows_menu_item = self.handshake_menuitem("Windows", "windows.png")
        menu = Gtk.Menu()
        windows_menu_item.set_submenu(menu)
        menu.append(self.make_raisewindowsmenuitem())
        menu.append(self.make_showhidewindowsmenuitem())
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

    def _non_OR_windows(self):
        return tuple(win for win in self.client._window_to_id.keys() if not win.is_OR())

    def _call_non_OR_windows(self, functions):
        for win in self._non_OR_windows():
            for function, args in functions.items():
                fn = getattr(win, function, None)
                if not fn:
                    log.warn("Warning: no '%s' function on %s", function, win)
                else:
                    try:
                        fn(*args)
                    except Exception as e:
                        log.error("Error calling %s%s on %s:", function, args, win)
                        log.estr(e)

    def _raise_all_windows(self, *_args):
        self._call_non_OR_windows({"deiconify" : (), "present" : ()})

    def make_raisewindowsmenuitem(self):
        return self.handshake_menuitem("Raise Windows", "raise.png", None, self._raise_all_windows())

    def _minimize_all_windows(self, *_args):
        self._call_non_OR_windows({"iconify" : ()})

    def make_minimizewindowsmenuitem(self):
        return self.handshake_menuitem("Minimize Windows", "minimize.png", None, self._minimize_all_windows)

    def _hide_window(self, win):
        skip_pager = win.get_skip_pager_hint()
        skip_taskbar = win.get_skip_taskbar_hint()
        def ondeiconify():
            win.set_skip_pager_hint(skip_pager)
            win.set_skip_taskbar_hint(skip_taskbar)
        win._ondeiconify.append(ondeiconify)
        if not skip_pager:
            win.set_skip_pager_hint(True)
        if not skip_taskbar:
            win.set_skip_taskbar_hint(True)
        win.freeze()

    def make_showhidewindowsmenuitem(self):
        def set_icon(icon_name):
            image = self.get_image(icon_name, self.menu_icon_size)
            if image:
                self.showhidewindows.set_image(image)
        def showhide_windows(*args):
            self.showhidewindows_state = not self.showhidewindows_state
            log("showhide_windows%s showhidewindows_state=%s", args, self.showhidewindows_state)
            if self.showhidewindows_state:
                #deiconify() will take care of restoring the attributes via "_ondeiconify"
                self._call_non_OR_windows({"unfreeze" : (), "present" : ()})
                set_icon("eye-off.png")
                self.showhidewindows.set_label("Hide Windows")
            else:
                for win in self._non_OR_windows():
                    self._hide_window(win)
                set_icon("eye-on.png")
                self.showhidewindows.set_label("Show Windows")
        self.showhidewindows_state = True
        self.showhidewindows = self.handshake_menuitem("Hide Windows", "eye-off.png", None, showhide_windows)
        return self.showhidewindows

    def make_servermenuitem(self):
        server_menu_item = self.handshake_menuitem("Server", "server.png")
        menu = Gtk.Menu()
        server_menu_item.set_submenu(menu)
        if RUNCOMMAND_MENU:
            menu.append(self.make_runcommandmenuitem())
        if SHOW_SERVER_COMMANDS:
            menu.append(self.make_servercommandsmenuitem())
        if SHOW_TRANSFERS:
            menu.append(self.make_servertransfersmenuitem())
        if SHOW_UPLOAD:
            menu.append(self.make_uploadmenuitem())
        if SHOW_DOWNLOAD:
            menu.append(self.make_downloadmenuitem())
        if SHOW_SERVER_LOG:
            menu.append(self.make_serverlogmenuitem())
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
                self.servercommands.set_tooltip_text(SERVER_NOT_SUPPORTED)
            else:
                self.servercommands.set_tooltip_text("")
        self.after_handshake(enable_servercommands)
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
        self.after_handshake(enable_start_new_command)
        self.client.on_server_setting_changed("start-new-commands", enable_start_new_command)
        return self.startnewcommand

    def make_servertransfersmenuitem(self):
        self.transfers = self.menuitem("Transfers", "transfer.png",
                                       "Files and URLs forwarding",
                                       self.client.show_ask_data_dialog)
        return self.transfers

    def make_uploadmenuitem(self):
        self.upload = self.menuitem("Upload File", "upload.png", cb=self.client.show_file_upload)
        def enable_upload(*args):
            log("enable_upload%s server_file_transfer=%s", args, self.client.remote_file_transfer)
            set_sensitive(self.upload, self.client.remote_file_transfer)
            if not self.client.remote_file_transfer:
                self.upload.set_tooltip_text(SERVER_NOT_SUPPORTED)
            else:
                self.upload.set_tooltip_text("Send a file to the server")
        self.after_handshake(enable_upload)
        return self.upload

    def make_downloadmenuitem(self):
        self.download = self.menuitem("Download File", "download.png", cb=self.client.send_download_request)
        def enable_download(*args):
            log("enable_download%s server_file_transfer=%s, server_start_new_commands=%s, subcommands=%s",
                args, self.client.remote_file_transfer, self.client.server_start_new_commands, self.client._remote_subcommands)
            remote_send_file = "send-file" in self.client._remote_subcommands
            supported = self.client.remote_file_transfer and self.client.server_start_new_commands
            set_sensitive(self.download, supported and remote_send_file)
            if not supported:
                self.download.set_tooltip_text(SERVER_NOT_SUPPORTED)
            elif not remote_send_file:
                self.download.set_tooltip_text("'send-file' subcommand is not supported by the server")
            else:
                self.download.set_tooltip_text("Download a file from the server")

        self.after_handshake(enable_download)
        return self.download


    def make_serverlogmenuitem(self):
        def download_server_log(*_args):
            self.client.download_server_log()
        self.download_log = self.menuitem("Download Server Log", "list.png", cb=download_server_log)
        def enable_download(*args):
            log("enable_download%s server_file_transfer=%s", args, self.client.remote_file_transfer)
            set_sensitive(self.download_log, self.client.remote_file_transfer and bool(self.client._remote_server_log))
            if not self.client.remote_file_transfer:
                self.download_log.set_tooltip_text(SERVER_NOT_SUPPORTED)
            elif not self.client._remote_server_log:
                self.download_log.set_tooltip_text("Server does not expose its log-file")
            else:
                self.download_log.set_tooltip_text("Download the server log")
        self.after_handshake(enable_download)
        return self.download_log


    def make_shutdownmenuitem(self):
        def ask_shutdown_confirm(*_args):
            messages = []
            #uri = self.client.display_desc.get("display_name")
            #if uri:
            #    messages.append("URI: %s" % uri)
            session_name = self.client.session_name or self.client.server_session_name
            if session_name:
                messages.append("Shutting down the session '%s' may result in data loss," % session_name)
            else:
                messages.append("Shutting down this session may result in data loss,")
            messages.append("are you sure you want to proceed?")
            dialog = Gtk.MessageDialog (None, 0, Gtk.MessageType.QUESTION,
                                    Gtk.ButtonsType.NONE,
                                    "\n".join(messages))
            dialog.add_button(Gtk.STOCK_CANCEL, 0)
            SHUTDOWN = 1
            dialog.add_button("Shutdown", SHUTDOWN)
            response = dialog.run()     # pylint: disable=no-member
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
        self.after_handshake(enable_shutdown)
        self.client.on_server_setting_changed("client-shutdown", enable_shutdown)
        return self.shutdown

    def make_startmenuitem(self):
        start_menu_item = self.handshake_menuitem("Start", "start.png")
        start_menu_item.show()
        def update_menu_data():
            if not self.client.start_new_commands:
                set_sensitive(start_menu_item, False)
                start_menu_item.set_tooltip_text("Starting new commands is disabled")
                return
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
            start_menu_item.set_tooltip_text(None)
        def start_menu_init():
            update_menu_data()
            def on_xdg_menu_changed(setting, value):
                log("on_xdg_menu_changed(%s, %s)", setting, repr_ellipsized(str(value)))
                update_menu_data()
            self.client.on_server_setting_changed("xdg-menu", on_xdg_menu_changed)
        self.after_handshake(start_menu_init)
        return start_menu_item

    def build_start_menu(self):
        menu = Gtk.Menu()
        execlog("build_start_menu() %i menu items", len(self.client.server_xdg_menu))
        execlog("self.client.server_xdg_menu=%s", ellipsizer(self.client.server_xdg_menu))
        for cat, category_props in sorted(self.client.server_xdg_menu.items()):
            category = u(cat)
            execlog(" * category: %s", category)
            #log("category_props(%s)=%s", category, category_props)
            if not isinstance(category_props, dict):
                execlog("category properties is not a dict: %s", type(category_props))
                continue
            cp = typedict(category_props)
            execlog("  category_props(%s)=%s", category, ellipsizer(category_props))
            entries = cp.dictget("Entries")
            if not entries:
                execlog("  no entries for category '%s'", category)
                continue
            icondata = cp.bytesget("IconData")
            category_menu_item = self.start_menuitem(category, icondata)
            cat_menu = Gtk.Menu()
            category_menu_item.set_submenu(cat_menu)
            menu.append(category_menu_item)
            for an, cp in sorted(entries.items()):
                app_name = u(an)
                command_props = typedict(cp)
                execlog("  - app_name=%s", app_name)
                app_menu_item = self.make_applaunch_menu_item(app_name, command_props)
                cat_menu.append(app_menu_item)
        menu.show_all()
        return menu

    def start_menuitem(self, title, icondata=None):
        smi = self.handshake_menuitem(title)
        if icondata:
            image = get_appimage(title, icondata, self.menu_icon_size)
            if image:
                smi.set_image(image)
        return smi

    def make_applaunch_menu_item(self, app_name : str, command_props : typedict):
        icondata = command_props.bytesget("IconData")
        app_menu_item = self.start_menuitem(app_name, icondata)
        def app_launch(*args):
            log("app_launch(%s) command_props=%s", args, command_props)
            command = command_props.strget("command")
            try:
                command = re.sub('\\%[fFuU]', '', command)
            except Exception:
                log("re substitution failed", exc_info=True)
                command = command.split("%", 1)[0]
            log("command=%s", command)
            if command:
                self.client.send_start_command(app_name, command, False, self.client.server_sharing)
        app_menu_item.connect("activate", app_launch)
        return app_menu_item


    def make_disconnectmenuitem(self):
        def menu_quit(*_args):
            self.client.disconnect_and_quit(ExitCode.OK, ConnectionMessage.CLIENT_EXIT)
        return self.handshake_menuitem("Disconnect", "quit.png", None, menu_quit)


    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)
