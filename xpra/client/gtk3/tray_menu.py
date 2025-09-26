# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from typing import Any
from collections.abc import Sequence, Callable, Iterable

from xpra.util.objects import typedict, reverse_dict
from xpra.util.str_fn import Ellipsizer, repr_ellipsized, csv
from xpra.util.env import envbool, IgnoreWarningsContext
from xpra.os_util import gi_import, OSX, WIN32
from xpra.common import RESOLUTION_ALIASES, ConnectionMessage, uniq
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
from xpra.codecs.constants import PREFERRED_ENCODING_ORDER
from xpra.util.config import unset_config_attributes, update_config_attributes
from xpra.util.stats import std_unit_dec
from xpra.client.base import features
from xpra.log import Logger

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")

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
PREFER_IBUS_LAYOUTS = envbool("XPRA_PREFER_IBUS_LAYOUTS", True)

FULL_LAYOUT_LIST = envbool("XPRA_FULL_LAYOUT_LIST", True)

NEW_MONITOR_RESOLUTIONS = os.environ.get("XPRA_NEW_MONITOR_RESOLUTIONS",
                                         "640x480,1024x768,1600x1200,FHD,4K").split(",")

CLIPBOARD_LABELS = ["Clipboard", "Primary", "Secondary"]
CLIPBOARD_LABEL_TO_NAME = {
    "Clipboard": "CLIPBOARD",
    "Primary": "PRIMARY",
    "Secondary": "SECONDARY"
}
CLIPBOARD_NAME_TO_LABEL = reverse_dict(CLIPBOARD_LABEL_TO_NAME)

CLIPBOARD_DIRECTION_LABELS = ["Client to server only", "Server to client only", "Both directions", "Disabled"]
CLIPBOARD_DIRECTION_LABEL_TO_NAME = {
    "Client to server only": "to-server",
    "Server to client only": "to-client",
    "Both directions": "both",
    "Disabled": "disabled",
}
CLIPBOARD_DIRECTION_NAME_TO_LABEL = reverse_dict(CLIPBOARD_DIRECTION_LABEL_TO_NAME)

SERVER_NOT_SUPPORTED = "Not supported by the server"

# 'auto' is recorded as '' unfortunately:
GENERIC_ENCODINGS = ("", "auto", "stream", "grayscale")

CONFIG = "91_tray.conf"


def update_config(attributes: dict[str, str]) -> None:
    update_config_attributes(attributes, filename=CONFIG)


def unset_config(*names: str) -> None:
    unset_config_attributes(names, filename=CONFIG)


class GTKTrayMenu(MenuHelper):

    def setup_menu(self):
        log("setup_menu()")
        return self.do_setup_menu(self.get_menu_items())

    def do_setup_menu(self, items: Sequence[Gtk.ImageMenuItem | Gtk.MenuItem]):
        menu = Gtk.Menu()
        for menu_item in items:
            menu.append(menu_item)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        return menu

    def get_menu_items(self) -> list[Gtk.ImageMenuItem | Gtk.MenuItem]:
        log("get_menu_items()")
        items: list[Gtk.ImageMenuItem | Gtk.MenuItem] = []

        def add(item) -> None:
            if item:
                items.append(item)

        if SHOW_TITLE_ITEM:
            add(self.make_titlemenuitem())
        add(self.make_infomenuitem())
        add(self.make_featuresmenuitem())
        if features.windows and self.client.keyboard_helper:
            add(self.make_keyboardmenuitem())
        if features.clipboard and SHOW_CLIPBOARD_MENU:
            add(self.make_clipboardmenuitem())
        if features.windows:
            add(self.make_picturemenuitem())
        if features.audio and STARTSTOP_SOUND_MENU:
            add(self.make_audiomenuitem())
        if features.webcam and WEBCAM_MENU:
            add(self.make_webcammenuitem())
        if features.display and MONITORS_MENU:
            add(self.make_monitorsmenuitem())
        if features.windows and WINDOWS_MENU:
            add(self.make_windowsmenuitem())
        if RUNCOMMAND_MENU or SHOW_SERVER_COMMANDS or SHOW_UPLOAD or SHOW_SHUTDOWN:
            add(self.make_servermenuitem())
        if features.windows and START_MENU:
            add(self.make_startmenuitem())
        add(self.make_disconnectmenuitem())
        if SHOW_CLOSE:
            add(self.make_closemenuitem())
        return items

    def is_mmap_enabled(self) -> bool:
        if not getattr(self.client, "", False):
            return False
        mra = self.client.mmap_read_area
        return mra and mra.enabled and mra.size > 0

    def make_titlemenuitem(self) -> Gtk.MenuItem:
        title_item = Gtk.MenuItem()
        title_item.set_label(self.client.session_name or "Xpra")
        set_sensitive(title_item, False)

        def set_menu_title(*_args) -> None:
            # set the real name when available:
            try:
                title = self.client.get_tray_title()
            except Exception:
                title = self.client.session_name or "Xpra"
            title_item.set_label(title)

        self.after_handshake(set_menu_title)
        return title_item

    def make_infomenuitem(self) -> Gtk.ImageMenuItem:
        info_menu_item = self.menuitem("Information", "information.png")
        menu = Gtk.Menu()
        info_menu_item.set_submenu(menu)

        def add(menuitem) -> None:
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

    def make_featuresmenuitem(self) -> Gtk.ImageMenuItem:
        features_menu_item = self.handshake_menuitem("Features", "features.png")
        menu = Gtk.Menu()
        self.append_featuresmenuitems(menu)
        features_menu_item.set_submenu(menu)
        features_menu_item.show_all()
        return features_menu_item

    def append_featuresmenuitems(self, menu) -> None:
        menu.append(self.make_sharingmenuitem())
        menu.append(self.make_lockmenuitem())
        if features.windows:
            menu.append(self.make_readonlymenuitem())
            menu.append(self.make_bellmenuitem())
        if features.notifications:
            menu.append(self.make_notificationsmenuitem())
        if features.windows:
            menu.append(self.make_cursorsmenuitem())
        if self.client.client_supports_opengl:
            menu.append(self.make_openglmenuitem())
        if features.windows:
            menu.append(self.make_modalwindowmenuitem())

    def make_sharingmenuitem(self) -> Gtk.ImageMenuItem:
        def sharing_toggled(*args) -> None:
            v = self.sharing_menuitem.get_active()
            self.client.client_supports_sharing = v
            if self.client.server_sharing_toggle:
                self.client.send_sharing_enabled()
            log("sharing_toggled(%s) readonly=%s", args, self.client.readonly)

        self.sharing_menuitem = self.checkitem("Sharing", sharing_toggled)
        self.sharing_menuitem.set_tooltip_text("Allow other clients to connect to this session")
        set_sensitive(self.sharing_menuitem, False)

        def set_sharing_menuitem(*args) -> None:
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

    def make_lockmenuitem(self) -> Gtk.ImageMenuItem:
        def lock_toggled(*args) -> None:
            v = self.lock_menuitem.get_active()
            self.client.client_lock = v
            if self.client.server_lock_toggle:
                self.client.send_lock_enabled()
            log("lock_toggled(%s) lock=%s", args, self.client.client_lock)

        self.lock_menuitem = self.checkitem("Lock", lock_toggled)
        self.lock_menuitem.set_tooltip_text("Prevent other clients from stealing this session")
        set_sensitive(self.lock_menuitem, False)

        def set_lock_menuitem(*args) -> None:
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

    def make_readonlymenuitem(self) -> Gtk.ImageMenuItem:
        def readonly_toggled(*args) -> None:
            v = self.readonly_menuitem.get_active()
            self.client.readonly = v
            log("readonly_toggled(%s) readonly=%s", args, self.client.readonly)

        self.readonly_menuitem = self.checkitem("Read-only", readonly_toggled)
        set_sensitive(self.readonly_menuitem, False)

        def set_readonly_menuitem(*args) -> None:
            log("set_readonly_menuitem%s enabled=%s", args, self.client.readonly)
            self.readonly_menuitem.set_active(self.client.readonly)
            set_sensitive(self.readonly_menuitem, not self.client.server_readonly)
            if not self.client.server_readonly:
                self.readonly_menuitem.set_tooltip_text("Disable all mouse and keyboard input")
            else:
                self.readonly_menuitem.set_tooltip_text("Cannot disable readonly mode: "
                                                        "the server has locked the session to read only")

        self.after_handshake(set_readonly_menuitem)
        return self.readonly_menuitem

    def make_bellmenuitem(self) -> Gtk.ImageMenuItem:
        c = self.client

        def bell_toggled(*args) -> None:
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

        def set_bell_menuitem(*args) -> None:
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
        return self.bell_menuitem

    def make_cursorsmenuitem(self) -> Gtk.ImageMenuItem:
        def cursors_toggled(*args) -> None:
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
        return self.cursors_menuitem

    def make_notificationsmenuitem(self) -> Gtk.ImageMenuItem:
        def notifications_toggled(*args) -> None:
            v = self.notifications_menuitem.get_active()
            changed = self.client.notifications_enabled != v
            self.client.notifications_enabled = v
            log("notifications_toggled%s active=%s changed=%s", args, v, changed)
            if changed:
                self.client.send_notify_enabled()

        self.notifications_menuitem = self.checkitem("Notifications", notifications_toggled)
        set_sensitive(self.notifications_menuitem, False)

        def set_notifications_menuitem(*args) -> None:
            log("set_notifications_menuitem%s enabled=%s", args, self.client.notifications_enabled)
            can_notify = self.client.client_supports_notifications
            self.notifications_menuitem.set_active(self.client.notifications_enabled and can_notify)
            set_sensitive(self.notifications_menuitem, can_notify)
            if can_notify:
                self.notifications_menuitem.set_tooltip_text("Forward system notifications")
            else:
                self.notifications_menuitem.set_tooltip_text("Cannot forward system notifications: "
                                                             "the feature has been disabled")

        self.after_handshake(set_notifications_menuitem)
        return self.notifications_menuitem

    def remote_clipboard_changed(self, item, clipboard_submenu) -> None:
        c = self.client
        if not c or not c.server_clipboard or not c.client_supports_clipboard:
            return
        # prevent infinite recursion where ensure_item_selected
        # ends up calling here again
        key = "_in_remote_clipboard_changed"
        ich = getattr(clipboard_submenu, key, False)
        clipboardlog("remote_clipboard_changed%s already in change handler: %s, visible=%s",
                     (ll(item), clipboard_submenu),
                     ich, clipboard_submenu.get_visible())
        if ich:  # or not clipboard_submenu.get_visible():
            return
        try:
            setattr(clipboard_submenu, key, True)
            selected_item = ensure_item_selected(clipboard_submenu, item)
            selected = selected_item.get_label()
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME.get(selected)
            self.set_new_remote_clipboard(remote_clipboard)
        finally:
            setattr(clipboard_submenu, key, False)

    def set_new_remote_clipboard(self, remote_clipboard) -> None:
        clipboardlog("set_new_remote_clipboard(%s)", remote_clipboard)
        ch = self.client.clipboard_helper
        local_clipboard = "CLIPBOARD"
        ch._local_to_remote = {local_clipboard: remote_clipboard}
        ch._remote_to_local = {remote_clipboard: local_clipboard}
        selections = [remote_clipboard]
        clipboardlog.info("server clipboard synchronization changed to %s selection", remote_clipboard)
        # tell the server what to look for:
        # (now that "clipboard-toggled" has re-enabled clipboard if necessary)
        self.client.send_clipboard_selections(selections)
        ch.send_tokens([local_clipboard])

    def make_translatedclipboard_optionsmenuitem(self) -> Gtk.ImageMenuItem:
        clipboardlog("make_translatedclipboard_optionsmenuitem()")
        ch = self.client.clipboard_helper
        selection_menu = self.menuitem("Selection", None, "Choose which remote clipboard to connect to")
        selection_submenu = Gtk.Menu()
        selection_menu.set_submenu(selection_submenu)
        rc_setting = None
        if len(ch._local_to_remote) == 1:
            rc_setting = tuple(ch._local_to_remote.values())[0]
        for label in CLIPBOARD_LABELS:
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
            selection_item = Gtk.CheckMenuItem(label=label)
            selection_item.set_active(remote_clipboard == rc_setting)
            selection_item.set_draw_as_radio(True)

            def remote_clipboard_changed(item):
                self.remote_clipboard_changed(item, selection_submenu)

            selection_item.connect("toggled", remote_clipboard_changed)
            selection_submenu.append(selection_item)
        selection_submenu.show_all()
        return selection_menu

    def clipboard_direction_changed(self, item, submenu) -> None:
        log("clipboard_direction_changed(%s, %s)", item, submenu)
        sel = ensure_item_selected(submenu, item, recurse=False)
        if not sel:
            return
        self.do_clipboard_direction_changed(sel.get_label() or "")

    def do_clipboard_direction_changed(self, label) -> None:
        # find the value matching this item label:
        d = CLIPBOARD_DIRECTION_LABEL_TO_NAME.get(label)
        if d and d != self.client.client_clipboard_direction:
            log.info("clipboard synchronization direction changed to: %s", label.lower())
            self.client.client_clipboard_direction = d
            can_send = d in ("to-server", "both")
            can_receive = d in ("to-client", "both")
            self.client.clipboard_helper.set_direction(can_send, can_receive)
            # will send new tokens and may help reset things:
            self.client.emit("clipboard-toggled")

    def make_clipboardmenuitem(self) -> Gtk.ImageMenuItem:
        clipboardlog("make_clipboardmenuitem()")
        self.clipboard_menuitem = self.menuitem("Clipboard", "clipboard.png")
        set_sensitive(self.clipboard_menuitem, False)

        def set_clipboard_menu(*args) -> None:
            c = self.client
            if not c.server_clipboard:
                self.clipboard_menuitem.set_tooltip_text("Server does not support clipboard synchronization")
                return
            ch = c.clipboard_helper
            if not c.client_supports_clipboard or not ch:
                self.clipboard_menuitem.set_tooltip_text("Client does not support clipboard synchronization")
                return
            # add a submenu:
            set_sensitive(self.clipboard_menuitem, True)
            clipboard_submenu = Gtk.Menu()
            self.clipboard_menuitem.set_submenu(clipboard_submenu)
            if WIN32 or OSX:
                # add a submenu to change the selection we synchronize with
                # since this platform only has a single clipboard
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
                direction_item.set_active(d == self.client.client_clipboard_direction)
                clipboard_submenu.append(direction_item)
                items.append(direction_item)
            clipboard_submenu.show_all()
            # connect signals:
            for direction_item in items:
                direction_item.connect("toggled", self.clipboard_direction_changed, clipboard_submenu)

        self.after_handshake(set_clipboard_menu)
        return self.clipboard_menuitem

    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip() -> None:
            kh = self.client.keyboard_helper
            if not kh:
                text = "Keyboard support is not loaded"
            elif kh.sync:
                text = "Disable keyboard synchronization " + \
                       "(prevents spurious key repeats on high latency connections)"
            else:
                text = "Enable keyboard state synchronization"
            self.keyboard_sync_menuitem.set_tooltip_text(text)

        def keyboard_sync_toggled(*args) -> None:
            ks = self.keyboard_sync_menuitem.get_active()
            if self.client.keyboard_sync != ks:
                self.client.keyboard_sync = ks
                log("keyboard_sync_toggled(%s) keyboard_sync=%s", args, ks)
                set_keyboard_sync_tooltip()
                self.client.send_keyboard_sync_enabled_status()

        self.keyboard_sync_menuitem = self.checkitem("State Synchronization")
        set_sensitive(self.keyboard_sync_menuitem, False)

        def set_keyboard_sync_menuitem(*args) -> None:
            kh = self.client.keyboard_helper
            can_set_sync = kh and self.client.server_keyboard
            set_sensitive(self.keyboard_sync_menuitem, can_set_sync)
            if can_set_sync:
                self.keyboard_sync_menuitem.connect("toggled", keyboard_sync_toggled)
            if kh:
                log("set_keyboard_sync_menuitem%s enabled=%s", args, kh.sync)
            self.keyboard_sync_menuitem.set_active(kh and bool(kh.sync))
            set_keyboard_sync_tooltip()

        self.after_handshake(set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_shortcutsmenuitem(self) -> Gtk.ImageMenuItem:
        self.keyboard_shortcuts_menuitem = self.checkitem("Intercept Shortcuts")
        kh = self.client.keyboard_helper
        self.keyboard_shortcuts_menuitem.set_active(kh and bool(kh.shortcuts_enabled))

        def keyboard_shortcuts_toggled(*args) -> None:
            ks = self.keyboard_shortcuts_menuitem.get_active()
            log("keyboard_shortcuts_toggled%s enabled=%s", args, ks)
            kh.shortcuts_enabled = ks

        self.keyboard_shortcuts_menuitem.connect("toggled", keyboard_shortcuts_toggled)
        return self.keyboard_shortcuts_menuitem

    def make_viewshortcutsmenuitem(self):
        return self.menuitem("View Shortcuts", tooltip="Show all active keyboard shortcuts",
                             cb=self.client.show_shortcuts)

    def make_openglmenuitem(self) -> Gtk.ImageMenuItem:
        gl = self.checkitem("OpenGL")
        gl.set_tooltip_text("hardware accelerated rendering using OpenGL")

        def gl_set(*args) -> None:
            log("gl_set(%s) opengl_enabled=%s, ", args, self.client.opengl_enabled)
            gl.set_active(self.client.opengl_enabled)
            set_sensitive(gl, self.client.client_supports_opengl)

            def opengl_toggled(*args) -> None:
                log("opengl_toggled%s", args)
                self.client.toggle_opengl()

            gl.connect("toggled", opengl_toggled)

        self.after_handshake(gl_set)
        return gl

    def make_modalwindowmenuitem(self) -> Gtk.ImageMenuItem:
        modal = self.checkitem("Modal Windows")
        modal.set_tooltip_text("honour modal windows")
        modal.set_active(self.client.modal_windows)
        set_sensitive(modal, False)

        def modal_toggled(*args) -> None:
            self.client.modal_windows = modal.get_active()
            log("modal_toggled%s modal_windows=%s", args, self.client.modal_windows)

        def set_modal_menuitem(*_args) -> None:
            set_sensitive(modal, True)

        self.after_handshake(set_modal_menuitem)
        modal.connect("toggled", modal_toggled)
        return modal

    def make_picturemenuitem(self) -> Gtk.ImageMenuItem:
        picture_menu_item = self.handshake_menuitem("Picture", "picture.png")
        menu = Gtk.Menu()
        picture_menu_item.set_submenu(menu)
        menu.append(self.make_bandwidthlimitmenuitem())
        if self.client.windows_enabled and len(self.client.get_encodings()) > 1:
            menu.append(self.make_encodingsmenuitem())
        if self.client.can_scale:
            menu.append(self.make_scalingmenuitem())
        menu.append(self.make_qualitymenuitem())
        menu.append(self.make_speedmenuitem())
        picture_menu_item.show_all()
        return picture_menu_item

    def make_bandwidthlimitmenuitem(self) -> Gtk.ImageMenuItem:
        bandwidth_limit_menu_item = self.menuitem("Bandwidth Limit", "bandwidth_limit.png")
        menu = Gtk.Menu()
        menuitems = {}

        def bwitem(bwlimit) -> Gtk.CheckMenuItem:
            c = self.bwitem(menu, bwlimit)
            menuitems[bwlimit] = c
            return c

        menu.append(bwitem(0))
        bandwidth_limit_menu_item.set_submenu(menu)
        bandwidth_limit_menu_item.show_all()

        def set_bwlimitmenu(*_args) -> None:
            if self.is_mmap_enabled():
                bandwidth_limit_menu_item.set_tooltip_text("memory mapped transfers are in use, "
                                                           "so bandwidth limits are disabled")
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
                    c.set_active(initial_value == bwlimit)
                    # disable any values higher than what the server allows:
                    if bwlimit == 0:
                        below_server_limit = sbl == 0
                    else:
                        below_server_limit = sbl == 0 or bwlimit <= sbl
                    set_sensitive(c, below_server_limit)
                    if not below_server_limit:
                        c.set_tooltip_text("server set the limit to %sbps" % std_unit_dec(sbl))

        self.after_handshake(set_bwlimitmenu)
        self.client.on_server_setting_changed("bandwidth-limit", set_bwlimitmenu)
        return bandwidth_limit_menu_item

    def bwitem(self, menu, bwlimit=0) -> Gtk.CheckMenuItem:
        bandwidthlog("bwitem(%s, %i)", menu, bwlimit)
        if bwlimit <= 0:
            label = "None"
        elif bwlimit >= 10 * 1000 * 1000:
            label = "%iMbps" % (bwlimit // (1000 * 1000))
        else:
            label = "%sbps" % std_unit_dec(bwlimit)
        c = Gtk.CheckMenuItem(label=label)
        c.set_draw_as_radio(True)
        c.set_active(False)
        set_sensitive(c, False)

        def activate_cb(item, *args) -> None:
            if not c.get_active():
                return
            bandwidthlog("activate_cb(%s, %s) bwlimit=%s", item, args, bwlimit)
            ensure_item_selected(menu, item)
            if (self.client.bandwidth_limit or 0) != bwlimit:
                self.client.bandwidth_limit = bwlimit
                self.client.send_bandwidth_limit()

        c.connect("toggled", activate_cb)
        c.show()
        return c

    def make_encodingsmenuitem(self) -> Gtk.ImageMenuItem:
        encodings = self.menuitem("Encoding", "encoding.png", "Choose picture data encoding")
        set_sensitive(encodings, False)
        self.encodings_submenu = None

        def set_encodingsmenuitem(*args) -> None:
            log("set_encodingsmenuitem%s", args)
            set_sensitive(encodings, not self.is_mmap_enabled())
            if self.is_mmap_enabled():
                # mmap disables encoding and uses raw rgb24
                encodings.set_label("Encoding")
                encodings.set_tooltip_text("memory mapped transfers are in use so picture encoding is disabled")
            else:
                self.encodings_submenu = self.make_encodingssubmenu()
                encodings.set_submenu(self.encodings_submenu)

        self.after_handshake(set_encodingsmenuitem)
        # callback runs from the main thread:
        self.client.on_server_setting_changed("encoding", set_encodingsmenuitem)
        return encodings

    def get_encoding_options(self) -> tuple[Sequence[str], Sequence[str]]:
        server_encodings = list(self.client.server_encodings)
        client_encodings = [x for x in PREFERRED_ENCODING_ORDER if x in self.client.get_encodings()]
        # separator:
        client_encodings.insert(0, "-")
        server_encodings.insert(0, "-")
        client_encodings.insert(1, "label:Don't use these directly:")
        server_encodings.insert(1, "label:Don't use these directly:")
        if "grayscale" in client_encodings and "grayscale" in server_encodings:
            # move grayscale to the top:
            client_encodings.remove("grayscale")
            server_encodings.remove("grayscale")
            client_encodings.insert(0, "grayscale")
            server_encodings.insert(0, "grayscale")
        # auto at the very top:
        client_encodings.insert(0, "auto")
        server_encodings.insert(0, "auto")
        client_encodings.insert(1, "stream")
        server_encodings.insert(1, "stream")
        return client_encodings, server_encodings

    def make_encodingssubmenu(self) -> Gtk.Menu:
        client_encodings, server_encodings = self.get_encoding_options()
        encodings_submenu = make_encodingsmenu(self.get_current_encoding,
                                               self.set_current_encoding,
                                               client_encodings, server_encodings)
        return encodings_submenu

    def get_current_encoding(self) -> str:
        return self.client.encoding

    def set_current_encoding(self, enc: str) -> None:
        self.client.set_encoding(enc)
        # these menus may need updating now:
        self.set_qualitymenu()
        self.set_speedmenu()

    def make_scalingmenuitem(self) -> Gtk.ImageMenuItem:
        self.scaling = self.menuitem("Scaling", "scaling.png", "Desktop Scaling")
        scaling_submenu = self.make_scalingmenu()
        self.scaling.set_submenu(scaling_submenu)
        return self.scaling

    def make_scalingmenu(self) -> Gtk.Menu:
        scaling_submenu = Gtk.Menu()
        scaling_submenu.updating = False
        from xpra.util.parsing import SCALING_OPTIONS
        for x in SCALING_OPTIONS:
            scaling_submenu.append(self.make_scalingvaluemenuitem(scaling_submenu, x))

        def scaling_changed(*args) -> None:
            log("scaling_changed%s updating selected tray menu item", args)
            # find the nearest scaling option to show as current:
            scaling = (self.client.xscale + self.client.yscale) / 2.0
            by_distance = {abs(scaling - x): x for x in SCALING_OPTIONS}
            closest = by_distance.get(sorted(by_distance)[0], 1)
            scaling_submenu.updating = True
            for x in scaling_submenu.get_children():
                scalingvalue = getattr(x, "scalingvalue", -1)
                x.set_active(scalingvalue == closest)
            scaling_submenu.updating = False

        self.client.connect("scaling-changed", scaling_changed)
        return scaling_submenu

    def make_scalingvaluemenuitem(self, scaling_submenu, scalingvalue=1.0) -> Gtk.CheckMenuItem:
        def scalecmp(v) -> bool:
            return abs(self.client.xscale - v) < 0.1

        pct = round(100.0 * scalingvalue)
        label = {100: "None"}.get(pct, f"{pct}%")
        c = Gtk.CheckMenuItem(label=label)
        c.scalingvalue = scalingvalue
        c.set_draw_as_radio(True)
        c.set_active(False)

        def scaling_activated(item) -> None:
            log("scaling_activated(%s) scaling_value=%s, active=%s",
                item, scalingvalue, item.get_active())
            if scaling_submenu.updating or not item.get_active():
                return
            ensure_item_selected(scaling_submenu, item)
            self.client.scaleset(item.scalingvalue, item.scalingvalue)

        c.connect('activate', scaling_activated)

        def set_active_state() -> None:
            scaling_submenu.updating = True
            c.set_active(scalecmp(scalingvalue))
            scaling_submenu.updating = False

        self.after_handshake(set_active_state)
        return c

    def make_qualitymenuitem(self) -> Gtk.ImageMenuItem:
        self.quality = self.menuitem("Quality", "slider.png", "Picture quality")
        set_sensitive(self.quality, False)

        def may_enable_qualitymenu(*_args) -> None:
            self.quality.set_submenu(self.make_qualitysubmenu())
            self.set_qualitymenu()

        self.after_handshake(may_enable_qualitymenu)
        return self.quality

    def make_qualitysubmenu(self) -> Gtk.ImageMenuItem:
        quality_submenu = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                             self.get_min_quality, self.get_quality,
                                             self.set_min_quality, self.set_quality)
        quality_submenu.show_all()
        return quality_submenu

    def get_min_quality(self) -> int:
        return self.client.min_quality

    def get_quality(self) -> int:
        return self.client.quality

    def set_min_quality(self, q) -> None:
        self.client.min_quality = q
        self.client.quality = -1
        self.client.send_min_quality()
        self.client.send_quality()

    def set_quality(self, q) -> None:
        self.client.min_quality = -1
        self.client.quality = q
        self.client.send_min_quality()
        self.client.send_quality()

    def set_qualitymenu(self, *_args) -> None:
        if self.quality:
            enc = self.client.encoding
            with_quality = enc in self.client.server_encodings_with_quality or enc in GENERIC_ENCODINGS
            can_use = with_quality and not self.is_mmap_enabled()
            set_sensitive(self.quality, can_use)
            if self.is_mmap_enabled():
                self.quality.set_tooltip_text("Speed is always 100% with mmap")
                return
            if not can_use:
                self.quality.set_tooltip_text(f"Not supported with {enc!r} encoding")
                return
            self.quality.set_tooltip_text("Minimum picture quality")
            # now check if lossless is supported:
            if self.quality.get_submenu():
                can_lossless = enc in self.client.server_encodings_with_lossless_mode
                for q, item in self.quality.get_submenu().menu_items.items():
                    set_sensitive(item, q < 100 or can_lossless)

    def make_speedmenuitem(self) -> Gtk.ImageMenuItem:
        self.speed = self.menuitem("Speed", "speed.png", "Encoding latency vs size")
        set_sensitive(self.speed, False)

        def may_enable_speedmenu(*_args):
            self.speed.set_submenu(self.make_speedsubmenu())
            self.set_speedmenu()

        self.after_handshake(may_enable_speedmenu)
        return self.speed

    def make_speedsubmenu(self) -> Gtk.ImageMenuItem:
        return make_min_auto_menu("Speed", MIN_SPEED_OPTIONS, SPEED_OPTIONS,
                                  self.get_min_speed, self.get_speed, self.set_min_speed, self.set_speed)

    def get_min_speed(self) -> int:
        return self.client.min_speed

    def get_speed(self) -> int:
        return self.client.speed

    def set_min_speed(self, s) -> None:
        self.client.min_speed = s
        self.client.speed = -1
        self.client.send_min_speed()
        self.client.send_speed()

    def set_speed(self, s) -> None:
        self.client.min_speed = -1
        self.client.speed = s
        self.client.send_min_speed()
        self.client.send_speed()

    def set_speedmenu(self, *_args) -> None:
        if self.speed:
            enc = self.client.encoding
            with_speed = enc in self.client.server_encodings_with_speed or enc in GENERIC_ENCODINGS
            set_sensitive(self.speed, with_speed and not self.is_mmap_enabled())
            if self.is_mmap_enabled():
                self.speed.set_tooltip_text("Quality is always 100% with mmap")
            elif not with_speed:
                self.speed.set_tooltip_text(f"Not supported with {enc!r} encoding")
            else:
                self.speed.set_tooltip_text("Encoding latency vs size")

    def make_audiomenuitem(self) -> Gtk.ImageMenuItem:
        audio_menu_item = self.handshake_menuitem("Audio", "audio.png")
        menu = Gtk.Menu()
        audio_menu_item.set_submenu(menu)
        menu.append(self.make_speakermenuitem())
        menu.append(self.make_microphonemenuitem())
        menu.append(self.make_avsyncmenuitem())
        audio_menu_item.show_all()
        return audio_menu_item

    def spk_on(self, *args) -> None:
        log("spk_on(%s)", args)
        self.client.start_receiving_audio()

    def spk_off(self, *args) -> None:
        log("spk_off(%s)", args)
        self.client.stop_receiving_audio()

    def make_speakermenuitem(self) -> Gtk.ImageMenuItem:
        speaker = self.menuitem("Speaker", "speaker.png", "Forward audio output from the server")
        set_sensitive(speaker, False)

        def is_speaker_on(*_args) -> bool:
            return self.client.speaker_enabled

        def speaker_state(*_args) -> None:
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

    def mic_on(self, *args) -> None:
        log("mic_on(%s)", args)
        self.client.start_sending_audio()

    def mic_off(self, *args) -> None:
        log("mic_off(%s)", args)
        self.client.stop_sending_audio()

    def make_microphonemenuitem(self) -> Gtk.ImageMenuItem:
        microphone = self.menuitem("Microphone", "microphone.png", "Forward audio input to the server")
        set_sensitive(microphone, False)

        def is_microphone_on(*_args) -> bool:
            return self.client.microphone_enabled

        def microphone_state(*_args) -> None:
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

    def audio_submenu_activate(self, item, menu, cb: Callable) -> None:
        log("audio_submenu_activate(%s, %s, %s) ignore_events=%s, active=%s",
            item, menu, cb, menu.ignore_events, item.get_active())
        if menu.ignore_events:
            return
        ensure_item_selected(menu, item)
        if item.get_active():
            cb()

    def make_audiosubmenu(self, is_on_cb: Callable, on_cb: Callable, off_cb, client_signal: str) -> Gtk.Menu:
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

        def update_audiosubmenu_state(*args) -> None:
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

    def make_avsyncmenuitem(self) -> Gtk.ImageMenuItem:
        sync = self.menuitem("Video Sync", "video.png", "Synchronize audio and video")
        menu = Gtk.Menu()
        current_value = 0
        if not self.client.av_sync:
            current_value = None

        def syncitem(label, delta: int | None = 0) -> Gtk.CheckMenuItem:
            c = Gtk.CheckMenuItem(label=label)
            c.set_draw_as_radio(True)
            c.set_active(current_value == delta)

            def activate_cb(item, *_args) -> None:
                avsynclog("activate_cb(%s, %s) delta=%s", item, menu, delta)
                if delta is None:
                    self.client.av_sync = False
                    self.client.send_audio_sync(0)
                else:
                    self.client.av_sync = True
                    self.client.av_sync_delta = delta
                    # the actual sync value will be calculated and sent
                    # in client._process_sound_data

            c.connect("toggled", activate_cb, menu)
            return c

        def add_sync_options() -> None:
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

        def set_avsyncmenu(*_args) -> None:
            if not self.client.server_av_sync:
                set_sensitive(sync, False)
                sync.set_tooltip_text("video-sync is not supported by the server")
                return
            if not (self.client.speaker_allowed and self.client.server_audio_send):
                set_sensitive(sync, False)
                sync.set_tooltip_text("video-sync requires speaker forwarding")
                return
            add_sync_options()
            set_sensitive(sync, True)

        self.after_handshake(set_avsyncmenu)
        sync.show_all()
        return sync

    def make_webcammenuitem(self) -> Gtk.ImageMenuItem:
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
        # TODO: register remove_video_device_change_callback for cleanup
        menu = Gtk.Menu()
        # so we can toggle the menu items without causing yet more events and infinite loops:
        menu.ignore_events = False

        def deviceitem(label, cb, device_no=0) -> Gtk.CheckMenuItem:
            c = Gtk.CheckMenuItem(label=label)
            c.set_draw_as_radio(True)
            c.set_active(get_active_device_no() == device_no)
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

        def start_webcam(device_no=0) -> None:
            webcamlog("start_webcam(%s)", device_no)
            self.client.do_start_sending_webcam(device_no)

        def stop_webcam(device_no=0) -> None:
            webcamlog("stop_webcam(%s)", device_no)
            self.client.stop_sending_webcam()

        def get_active_device_no() -> int:
            if self.client.webcam_device is None:
                return -1
            return self.client.webcam_device_no

        def populate_webcam_menu() -> None:
            menu.ignore_events = True
            webcamlog("populate_webcam_menu()")
            for x in menu.get_children():
                menu.remove(x)
            all_video_devices = get_all_video_devices()  # pylint: disable=assignment-from-none
            off_label = "Off"
            if all_video_devices is None:
                # None means that this platform cannot give us the device names,
                # so we just use a single "On" menu item and hope for the best
                on = deviceitem("On", start_webcam)
                menu.append(on)
            else:
                virt_devices = get_virtual_video_devices()
                non_virtual = {k: v for k, v in all_video_devices.items() if k not in virt_devices}
                for device_no, info in non_virtual.items():
                    label = str(info.get("card", info.get("device", str(device_no))))
                    item = deviceitem(label, start_webcam, device_no)
                    menu.append(item)
                if not non_virtual:
                    off_label = "No devices found"
            off = deviceitem(off_label, stop_webcam, -1)
            set_sensitive(off, off_label == "Off")
            menu.append(off)
            menu.show_all()
            menu.ignore_events = False

        populate_webcam_menu()

        def video_devices_changed(added=None, device=None) -> None:
            if added is not None and device:
                log.info("video device %s: %s", ["removed", "added"][added], device)
            else:
                log("video_devices_changed")
            # this callback runs in another thread,
            # and we want to wait for the devices to settle
            # so that the file permissions are correct when we try to access it:
            GLib.timeout_add(1000, populate_webcam_menu)

        add_video_device_change_callback(video_devices_changed)

        webcam.set_submenu(menu)

        def webcam_changed(*args) -> None:
            webcamlog("webcam_changed%s webcam_device=%s", args, self.client.webcam_device)
            if not self.client.webcam_forwarding:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Webcam forwarding is disabled")
                return
            if self.client.server_virtual_video_devices <= 0 or not self.client.server_webcam:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Server does not support webcam forwarding")
                return
            webcam.set_tooltip_text("")
            set_sensitive(webcam, True)
            webcamlog("webcam_changed%s active device no=%s", args, get_active_device_no())
            menu.ignore_events = True
            for x in menu.get_children():
                x.set_active(x.device_no == get_active_device_no())
            menu.ignore_events = False

        self.client.connect("webcam-changed", webcam_changed)
        set_sensitive(webcam, False)
        self.after_handshake(webcam_changed)
        self.client.on_server_setting_changed("webcam", webcam_changed)
        return webcam

    def make_keyboardmenuitem(self) -> Gtk.Menu:
        keyboard_menu_item = self.handshake_menuitem("Keyboard", "keyboard.png")
        menu = Gtk.Menu()
        keyboard_menu_item.set_submenu(menu)
        menu.append(self.make_keyboardsyncmenuitem())
        menu.append(self.make_shortcutsmenuitem())
        menu.append(self.make_viewshortcutsmenuitem())
        menu.append(self.make_layoutsmenuitem())
        keyboard_menu_item.show_all()
        return keyboard_menu_item

    def make_layoutsmenuitem(self) -> Gtk.ImageMenuItem:
        keyboard = self.menuitem("Layout", "keyboard.png", "Select your keyboard layout")
        set_sensitive(keyboard, False)
        self.keyboard_layout_item = keyboard
        self.after_handshake(self.populate_keyboard_layouts)
        return keyboard

    def populate_keyboard_layouts(self) -> None:
        log(f"populate_keyboard_layouts() {PREFER_IBUS_LAYOUTS=}")
        # by default, use keyboard helper values:
        self.populate_keyboard_helper_layouts()
        set_sensitive(self.keyboard_layout_item, True)

        if PREFER_IBUS_LAYOUTS:
            def got_ibus_layouts(setting: str, ibus_layouts) -> None:
                kh = self.client.keyboard_helper
                Logger("ibus").debug(f"current layout=%r, got {setting!r}=%s", kh.layout, Ellipsizer(ibus_layouts))
                if ibus_layouts and kh.layout:
                    self.populate_ibus_keyboard_layouts(ibus_layouts)
            self.client.on_server_setting_changed("ibus-layouts", got_ibus_layouts)

    def kbitem(self, title: str, layout: str, variant: str, backend="", name="", active=False) -> Gtk.CheckMenuItem:
        l = self.checkitem(title, self.set_kbitem_layout, active)
        l.set_draw_as_radio(True)
        l.keyboard_name = name
        l.keyboard_backend = backend
        l.keyboard_layout = layout
        l.keyboard_variant = variant
        return l

    def set_kbitem_layout(self, item, save=True) -> None:
        """ this callback updates the client (and server) if needed """
        ensure_item_selected(self.layout_submenu, item)
        descr = item.get_label()
        name = item.keyboard_name
        backend = item.keyboard_backend
        layout = item.keyboard_layout
        variant = item.keyboard_variant
        kh = self.client.keyboard_helper
        kh.locked = layout != "Auto"
        if layout != kh.layout_option or variant != kh.variant_option or kh.backend != backend or kh.name != name:
            kh.backend = backend
            if layout == "Auto":
                # re-detect everything:
                msg = "keyboard automatic mode"
                kh.layout_option = ""
                kh.variant_option = ""
                kh.backend = ""
                kh.name = ""
                if save:
                    unset_config("keyboard-backend", "keyboard-layout", "keyboard-variant")
            else:
                # use layout specified and send it:
                kh.layout_option = layout
                kh.variant_option = variant
                kh.backend = backend
                kh.name = name
                msg = "new keyboard layout selected"
                if save:
                    update_config({
                        "# description": descr,         # ie: "English (UK, extended, Windows)"
                        "# keyboard name": name,        # ie: "xkb:gb:extd:eng"
                        "keyboard-backend": backend,
                        "keyboard-layout": layout,
                        "keyboard-variant": variant,
                    })
            kh.update()
            kh.send_layout()
            log.info(f"{msg}: {descr!r}")
            if not backend:
                kh.send_keymap()

    def populate_ibus_keyboard_layouts(self, ibus_layouts: dict) -> None:
        self.layout_submenu = Gtk.Menu()
        self.keyboard_layout_item.set_submenu(self.layout_submenu)
        kh = self.client.keyboard_helper
        matches = []

        def engine_item(engine) -> tuple[str, Gtk.CheckMenuItem]:
            layout = engine.get("layout", "")
            name = engine.get("name", layout)
            descr = engine.get("description", layout).split("\n")[0]
            variant = engine.get("variant", "")
            backend = "ibus"
            active = kh.backend == backend and kh.layout == layout and kh.variant == variant and not matches
            log(f"{engine=} : {active=}")
            item = self.kbitem(descr, layout, variant, backend, name, active)
            return descr, item

        def items_matching(*layouts: str) -> Sequence[Gtk.CheckMenuItem]:
            # find all the ibus "engines" matching one of these layouts:
            engines = {}
            for i, engine in enumerate(ibus_layouts.get("engines", ())):
                layout = engine.get("layout", "")
                if not layout or layout not in layouts:
                    continue
                rank = engine.get("rank", 0)
                engines[rank * 65536 + i] = engine
            items = {}
            for rank in reversed(sorted(engines)):
                engine = engines[rank]
                descr, item = engine_item(engine)
                if descr not in items:
                    items[descr] = item
                    if item.get_active():
                        matches.append(item)
            items = dict(sorted(items.items()))
            return tuple(items.values())

        log(f"current settings: backend={kh.backend!r}, layout={kh.layout!r}, variant={kh.variant!r}")

        # at the top level menu, show layouts matching the layout-option or current layout:
        layouts = uniq((kh.layout_option or kh.layout).split(","))
        log(f"unique layouts: {layouts}")
        for item in items_matching(*layouts):
            self.layout_submenu.append(item)

        # now add a submenu for each of the other layouts:
        other_layouts = tuple(layout.strip() for layout in uniq((csv(kh.layouts_option or kh.layouts)).split(","))
                              if layout.strip() not in layouts)
        log(f"other layouts: {other_layouts}")
        from xpra.keyboard.layouts import LAYOUT_NAMES
        for layout in other_layouts:
            items = items_matching(layout)
            log(f"items_matching({layout})={items}")
            if items:
                layout_name = LAYOUT_NAMES.get(layout, layout)
                layout_menu = self.menuitem(layout_name)
                submenu = Gtk.Menu()
                for item in items:
                    submenu.append(item)
                layout_menu.set_submenu(submenu)
                self.layout_submenu.append(layout_menu)

        log(f"ibus {matches=}")
        if matches:
            self.set_kbitem_layout(matches[0], save=False)

    def populate_keyboard_helper_layouts(self) -> None:
        self.layout_submenu = Gtk.Menu()
        self.keyboard_layout_item.set_submenu(self.layout_submenu)

        def disable(message: str) -> None:
            self.keyboard_layout_item.set_tooltip_text(message)
            set_sensitive(self.keyboard_layout_item, False)

        def keysort(key) -> str:
            c, l = key
            return c.lower() + l.lower()

        def variants_submenu(layout: str, variants: Iterable[str]) -> None:
            # just show all the variants to choose from this layout
            default_layout = self.kbitem(f"{layout} - Default", layout, "", active=True)
            self.layout_submenu.append(default_layout)
            for variant in variants:
                self.layout_submenu.append(self.kbitem(f"{layout} - {variant}", layout, variant))

        kh = self.client.keyboard_helper
        if not kh:
            # this can happen when connection fails?
            return
        model, layout, layouts, variant, variants, _ = kh.get_layout_spec()
        log(f"make_layoutsmenuitem() {model=}, {layout=}, {layouts=}, {variant=}, {variants=}")
        if len(layouts) > 1:
            log("keyboard layouts: %s", ",".join(layouts))
            # log after removing dupes:
            log("keyboard layouts: %s", ",".join(uniq(layouts)))
            auto = self.kbitem("Auto", "Auto", "", active=True)
            self.layout_submenu.append(auto)
            if layout:
                self.layout_submenu.append(self.kbitem(layout, layout, ""))
            if variants:
                for v in variants:
                    self.layout_submenu.append(self.kbitem(f"{layout} - {v}", layout, v))
            for uq_l in uniq(layouts):
                if uq_l != layout:
                    self.layout_submenu.append(self.kbitem(uq_l, uq_l, ""))
            return
        if layout and len(variants) > 1:
            variants_submenu(layout, variants)
            return
        if layout or kh.query_struct:
            khl = layout or kh.query_struct.get("layout", "")
            from xpra.keyboard.layouts import LAYOUT_VARIANTS
            variants = LAYOUT_VARIANTS.get(khl) if khl else ()
            if variants:
                variants_submenu(khl, variants)
            else:
                disable(f"Detected {khl!r}" if khl else "")
            return
        if not FULL_LAYOUT_LIST:
            disable("No keyboard layouts detected")
            return
        from xpra.keyboard.layouts import X11_LAYOUTS
        # show all options to choose from:
        sorted_keys = list(X11_LAYOUTS.keys())
        sorted_keys.sort(key=keysort)
        for key in sorted_keys:
            country, language = key
            layout, variants = X11_LAYOUTS.get(key)
            name = f"{country} - {language}"
            if len(variants) > 1:
                # sub-menu for each variant:
                variant = self.menuitem(name, tooltip=layout)
                variant_submenu = Gtk.Menu()
                variant.set_submenu(variant_submenu)
                self.layout_submenu.append(variant)
                variant_submenu.append(self.kbitem(f"{layout} - Default", layout, ""))
                for v in variants:
                    variant_submenu.append(self.kbitem(f"{layout} - {v}", layout, v))
            else:
                # no variants:
                self.layout_submenu.append(self.kbitem(name, layout, ""))

    def make_monitorsmenuitem(self) -> Gtk.ImageMenuItem:
        monitors_menu_item = self.handshake_menuitem("Monitors", "display.png")
        menu = Gtk.Menu()
        monitors_menu_item.set_submenu(menu)

        def populate_monitors(*args) -> None:
            log("populate_monitors%s client server_multi_monitors=%s, server_monitors=%s",
                args, self.client.server_multi_monitors, self.client.server_monitors)
            if not self.client.server_multi_monitors or not self.client.server_monitors:
                monitors_menu_item.hide()
                return
            for x in menu.get_children():
                menu.remove(x)

            def monitor_changed(mitem, index) -> None:
                log("monitor_changed(%s, %s)", mitem, index)
                self.client.send_remove_monitor(index)

            for i, monitor in self.client.server_monitors.items():
                mitem = Gtk.CheckMenuItem(label=monitor.get("name", "VFB-%i" % i))
                mitem.set_active(True)
                mitem.set_draw_as_radio(True)
                mitem.connect("toggled", monitor_changed, i)
                menu.append(mitem)
            # and finally, an entry for adding a new monitor:
            add_monitor_item = self.menuitem("Add a monitor")
            resolutions_menu = Gtk.Menu()
            add_monitor_item.set_submenu(resolutions_menu)

            def add_monitor(mitem, resolution) -> None:
                log("add_monitor(%s, %s)", mitem, resolution)
                # older servers may not have all the aliases:
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

    def make_windowsmenuitem(self) -> Gtk.ImageMenuItem:
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

    def make_refreshmenuitem(self) -> Gtk.ImageMenuItem:
        def force_refresh(*_args) -> None:
            log("force refresh")
            self.client.send_refresh_all()
            self.client.reinit_window_icons()

        return self.handshake_menuitem("Refresh", "retry.png", None, force_refresh)

    def make_reinitmenuitem(self) -> Gtk.ImageMenuItem:
        def force_reinit(*_args) -> None:
            log("force reinit")
            self.client.reinit_windows()
            self.client.reinit_window_icons()

        return self.handshake_menuitem("Re-initialize", "reinitialize.png", None, force_reinit)

    def _non_OR_windows(self) -> tuple:
        return tuple(win for win in self.client._window_to_id.keys() if not win.is_OR())

    def _call_non_OR_windows(self, functions: dict[str, Any]):
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
        self._call_non_OR_windows({"deiconify": (), "present": ()})

    def make_raisewindowsmenuitem(self) -> Gtk.ImageMenuItem:
        return self.handshake_menuitem("Raise Windows", "raise.png", None, self._raise_all_windows())

    def _minimize_all_windows(self, *_args) -> Gtk.ImageMenuItem:
        self._call_non_OR_windows({"iconify": ()})

    def make_minimizewindowsmenuitem(self) -> Gtk.ImageMenuItem:
        return self.handshake_menuitem("Minimize Windows", "minimize.png", None, self._minimize_all_windows)

    def _hide_window(self, win) -> None:
        skip_pager = win.get_skip_pager_hint()
        skip_taskbar = win.get_skip_taskbar_hint()

        def ondeiconify() -> None:
            win.set_skip_pager_hint(skip_pager)
            win.set_skip_taskbar_hint(skip_taskbar)

        win._ondeiconify.append(ondeiconify)
        if not skip_pager:
            win.set_skip_pager_hint(True)
        if not skip_taskbar:
            win.set_skip_taskbar_hint(True)
        win.freeze()

    def make_showhidewindowsmenuitem(self) -> Gtk.ImageMenuItem:
        def set_icon(icon_name) -> None:
            image = self.get_image(icon_name, self.menu_icon_size)
            if image:
                self.showhidewindows.set_image(image)

        def showhide_windows(*args) -> None:
            self.showhidewindows_state = not self.showhidewindows_state
            log("showhide_windows%s showhidewindows_state=%s", args, self.showhidewindows_state)
            if self.showhidewindows_state:
                # deiconify() will take care of restoring the attributes via "_ondeiconify"
                self._call_non_OR_windows({"unfreeze": (), "present": ()})
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

    def make_servermenuitem(self) -> Gtk.ImageMenuItem:
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

    def make_servercommandsmenuitem(self) -> Gtk.ImageMenuItem:
        self.servercommands = self.menuitem("Server Commands", "list.png",
                                            "Commands running on the server",
                                            self.client.show_server_commands)

        def enable_servercommands(*args) -> None:
            log("enable_servercommands%s server-commands-info=%s", args, self.client.server_commands_info)
            set_sensitive(self.servercommands, self.client.server_commands_info)
            if not self.client.server_commands_info:
                self.servercommands.set_tooltip_text(SERVER_NOT_SUPPORTED)
            else:
                self.servercommands.set_tooltip_text("")

        self.after_handshake(enable_servercommands)
        return self.servercommands

    def make_runcommandmenuitem(self) -> Gtk.ImageMenuItem:
        self.startnewcommand = self.menuitem("Run Command", "forward.png",
                                             "Run a new command on the server",
                                             self.client.show_start_new_command)

        def enable_start_new_command(*args) -> None:
            log("enable_start_new_command%s start_new_command=%s", args, self.client.server_start_new_commands)
            set_sensitive(self.startnewcommand, self.client.server_start_new_commands)
            if not self.client.server_start_new_commands:
                self.startnewcommand.set_tooltip_text("Not supported or enabled on the server")
            else:
                self.startnewcommand.set_tooltip_text("")

        self.after_handshake(enable_start_new_command)
        self.client.on_server_setting_changed("start-new-commands", enable_start_new_command)
        return self.startnewcommand

    def make_servertransfersmenuitem(self) -> Gtk.ImageMenuItem:
        self.transfers = self.menuitem("Transfers", "transfer.png",
                                       "Files and URLs forwarding",
                                       self.client.show_ask_data_dialog)
        return self.transfers

    def make_uploadmenuitem(self) -> Gtk.ImageMenuItem:
        self.upload = self.menuitem("Upload File", "upload.png", cb=self.client.show_file_upload)

        def enable_upload(*args) -> None:
            log("enable_upload%s server_file_transfer=%s", args, self.client.remote_file_transfer)
            set_sensitive(self.upload, self.client.remote_file_transfer)
            if not self.client.remote_file_transfer:
                self.upload.set_tooltip_text(SERVER_NOT_SUPPORTED)
            else:
                self.upload.set_tooltip_text("Send a file to the server")

        self.after_handshake(enable_upload)
        return self.upload

    def make_downloadmenuitem(self) -> Gtk.ImageMenuItem:
        self.download = self.menuitem("Download File", "download.png", cb=self.client.send_download_request)

        def enable_download(*args) -> None:
            log("enable_download%s server_file_transfer=%s, server_start_new_commands=%s, subcommands=%s",
                args, self.client.remote_file_transfer, self.client.server_start_new_commands,
                self.client._remote_subcommands)
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

    def make_serverlogmenuitem(self) -> Gtk.ImageMenuItem:
        def download_server_log(*_args) -> None:
            self.client.download_server_log()

        self.download_log = self.menuitem("Download Server Log", "list.png", cb=download_server_log)

        def enable_download(*args) -> None:
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

    def make_shutdownmenuitem(self) -> Gtk.ImageMenuItem:
        def ask_shutdown_confirm(*_args) -> None:
            messages = []
            # uri = self.client.display_desc.get("display_name")
            # if uri:
            #    messages.append("URI: %s" % uri)
            session_name = self.client.session_name or self.client.server_session_name
            if session_name:
                messages.append("Shutting down the session '%s' may result in data loss," % session_name)
            else:
                messages.append("Shutting down this session may result in data loss,")
            messages.append("are you sure you want to proceed?")
            dialog = Gtk.MessageDialog(transient_for=None, flags=0,
                                       message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                                       text="\n".join(messages))
            dialog.add_button(Gtk.STOCK_CANCEL, 0)
            SHUTDOWN = 1
            dialog.add_button("Shutdown", SHUTDOWN)
            response = dialog.run()  # pylint: disable=no-member
            dialog.destroy()
            if response == SHUTDOWN:
                self.client.send_shutdown_server()

        self.shutdown = self.menuitem("Shutdown Session", "shutdown.png", cb=ask_shutdown_confirm)

        def enable_shutdown(*args) -> None:
            log("enable_shutdown%s can_shutdown_server=%s", args, self.client.server_client_shutdown)
            set_sensitive(self.shutdown, self.client.server_client_shutdown)
            if not self.client.server_client_shutdown:
                self.shutdown.set_tooltip_text("Disabled by the server")
            else:
                self.shutdown.set_tooltip_text("Shutdown this server session")

        self.after_handshake(enable_shutdown)
        self.client.on_server_setting_changed("client-shutdown", enable_shutdown)
        return self.shutdown

    def make_startmenuitem(self) -> Gtk.ImageMenuItem:
        start_menu_item = self.handshake_menuitem("Start", "start.png")
        start_menu_item.show()

        def update_menu_data() -> None:
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

        def on_xdg_menu_changed(setting, value):
            log("on_xdg_menu_changed(%s, %s)", setting, repr_ellipsized(str(value)))
            update_menu_data()
        self.client.on_server_setting_changed("xdg-menu", on_xdg_menu_changed)

        def start_menu_init() -> None:
            update_menu_data()
        self.after_handshake(start_menu_init)
        return start_menu_item

    def build_start_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        execlog("build_start_menu() %i menu items", len(self.client.server_xdg_menu))
        execlog("self.client.server_xdg_menu=%s", Ellipsizer(self.client.server_xdg_menu))
        for category, category_props in sorted(self.client.server_xdg_menu.items()):
            execlog(" * category: %s", category)
            # log("category_props(%s)=%s", category, category_props)
            if not isinstance(category_props, dict):
                execlog("category properties is not a dict: %s", type(category_props))
                continue
            cp = typedict(category_props)
            execlog("  category_props(%s)=%s", category, Ellipsizer(category_props))
            entries = cp.dictget("Entries")
            if not entries:
                execlog("  no entries for category '%s'", category)
                continue
            icondata = cp.bytesget("IconData")
            category_menu_item = self.start_menuitem(category, icondata)
            cat_menu = Gtk.Menu()
            category_menu_item.set_submenu(cat_menu)
            menu.append(category_menu_item)
            for app_name, cp in sorted(entries.items()):
                command_props = typedict(cp)
                execlog("  - app_name=%s", app_name)
                app_menu_item = self.make_applaunch_menu_item(app_name, command_props)
                cat_menu.append(app_menu_item)
        menu.show_all()
        return menu

    def start_menuitem(self, title: str, icondata=b"") -> Gtk.ImageMenuItem:
        smi = self.handshake_menuitem(title)
        if icondata:
            image = get_appimage(title, icondata, self.menu_icon_size)
            if image:
                with IgnoreWarningsContext():
                    smi.set_image(image)
        return smi

    def make_applaunch_menu_item(self, app_name: str, command_props: typedict) -> Gtk.ImageMenuItem:
        icondata = command_props.bytesget("IconData")
        app_menu_item = self.start_menuitem(app_name, icondata)

        def app_launch(*args) -> None:
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

    def make_disconnectmenuitem(self) -> Gtk.ImageMenuItem:
        def menu_quit(*_args) -> None:
            self.client.disconnect_and_quit(ExitCode.OK, ConnectionMessage.CLIENT_EXIT)

        return self.handshake_menuitem("Disconnect", "quit.png", None, menu_quit)

    def make_closemenuitem(self) -> Gtk.ImageMenuItem:
        return self.menuitem("Close Menu", "close.png", cb=self.close_menu)
