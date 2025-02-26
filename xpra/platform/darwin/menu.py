# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.common import noop
from xpra.gtk.widget import scaled_image
from xpra.gtk.dialogs.about import about
from xpra.client.gtk3.tray_menu import (
    GTKTrayMenu,
    CLIPBOARD_LABEL_TO_NAME, CLIPBOARD_NAME_TO_LABEL, CLIPBOARD_LABELS,
    CLIPBOARD_DIRECTION_LABELS, CLIPBOARD_DIRECTION_NAME_TO_LABEL,
    SHOW_UPLOAD, SHOW_VERSION_CHECK, RUNCOMMAND_MENU, SHOW_SERVER_COMMANDS, SHOW_SHUTDOWN,
    SHOW_QR,
)
from xpra.platform.paths import get_icon
from xpra.platform.darwin import get_OSXApplication
from xpra.client.base import features
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("osx", "tray", "menu")
clipboardlog = Logger("osx", "menu", "clipboard")

# control which menus are shown in the OSX global menu:
DEFAULT = envbool("XPRA_OSX_SHOW_MENU_DEFAULT", True)
SHOW_FEATURES_MENU = DEFAULT
SHOW_SOUND_MENU = DEFAULT
SHOW_ENCODINGS_MENU = DEFAULT
SHOW_ACTIONS_MENU = DEFAULT
SHOW_INFO_MENU = DEFAULT
SHOW_CLIPBOARD_MENU = DEFAULT
SHOW_SERVER_MENU = DEFAULT

SHOW_ABOUT_XPRA = DEFAULT

SINGLE_MENU = envbool("XPRA_OSX_SINGLE_MENU", False)
USE_WINDOW_MENU = envbool("XPRA_OSX_USE_WINDOW_MENU", True)

SEPARATOR = "SEPARATOR"

_OSXMenuHelper = None


def getOSXMenuHelper(client=None):
    global _OSXMenuHelper
    if _OSXMenuHelper is None:
        _OSXMenuHelper = OSXMenuHelper(client)
    elif client is not None:
        _OSXMenuHelper.set_client(client)
    return _OSXMenuHelper


class OSXMenuHelper(GTKTrayMenu):
    """
    we have to do this stuff here,
    so we can re-use the same instance,
    and change the callbacks if needed.
    (that way, the launcher and the client can both change the menus)
    """

    def __init__(self, client=None):
        super().__init__(client)
        log("OSXMenuHelper(%s)", client)
        self.menu_bar = None
        self.hidden_window = None
        self.menus = {}  # all the "top-level" menu items we manage
        self.app_menus = {}  # the ones added to the app_menu via insert_app_menu_item (which cannot be removed!)
        self.dock_menu = None
        self.window_menu = None
        self.window_menu_item = None
        self.numlock_menuitem = None
        self.full = False
        self.set_client(client)
        self._clipboard_change_pending = False

    def set_client(self, client) -> None:
        super().set_client(client)
        # if we call add_about before the main loop is ready,
        # things don't work...
        if client and SHOW_ABOUT_XPRA:
            self.after_handshake(self.add_about)

    def show_menu(self, button: int, time) -> None:
        # does not mean anything on OSX since the menu is controlled by the OS
        pass

    def build(self):
        log("OSXMenuHelper.build()")
        if self.menu_bar is None:
            self.menu_bar = Gtk.MenuBar()
            self.menu_bar.show_all()
        return self.menu_bar

    def rebuild(self):
        log("OSXMenuHelper.rebuild()")
        if not self.menu_bar:
            return self.build()
        self.remove_all_menus()
        return self.menu_bar

    def remove_all_menus(self) -> None:
        log("OSXMenuHelper.remove_all_menus()")
        if self.menu_bar:
            for x in self.menus.values():
                if x in self.menu_bar.get_children():
                    self.menu_bar.remove(x)
                    x.hide()
        self.menus = {}
        self.full = False

    def add_top_level_menu(self, label: str, submenu) -> None:
        """ Adds the item to the app-menu or to the top bar,
            but only if it has not been added yet.
            (depending on the SINGLE_MENU flag)
        """
        if SINGLE_MENU:
            # add or re-use menu item in the app-menu:
            self.add_to_app_menu(label, submenu)
        else:
            self.add_to_menu_bar(label, submenu)

    def add_to_app_menu(self, label: str, submenu) -> None:
        item = self.app_menus.get(label)
        if item:
            log("application menu already has a '%s' entry", label)
            if submenu is not None:
                item.set_submenu(submenu)
            item.show_all()
        else:
            if label.startswith(SEPARATOR):
                item = Gtk.SeparatorMenuItem()
            else:
                item = self.menuitem(label)
                item.set_submenu(submenu)
            item.show_all()
            macapp = get_OSXApplication()
            macapp.insert_app_menu_item(item, 1)
            self.app_menus[label] = item

    def add_to_menu_bar(self, label, submenu):
        if label.startswith(SEPARATOR):
            return  # not relevant
        item = self.menus.get(label)
        if item is None:
            item = self.menuitem(label)
            item.set_submenu(submenu)
            item.show_all()
            self.menu_bar.add(item)
            self.menus[label] = item
        else:
            item.set_submenu(submenu)
            item.show_all()

    def get_menu(self, label: str):
        if SINGLE_MENU:
            return self.app_menus.get(label)
        return self.menus.get(label)

    def add_about(self) -> None:
        if "About" in self.app_menus:
            return
        item = self.menuitem("About", cb=about)
        item.show_all()
        macapp = get_OSXApplication()
        macapp.insert_app_menu_item(item, 0)
        self.app_menus["About"] = item

    def add_full_menu(self) -> None:
        log("OSXMenuHelper.add_full_menu()")
        if self.full or not self.client:
            return
        self.full = True
        menus = self.get_extra_menus()
        for label, submenu in reversed(menus):
            self.add_top_level_menu(label, submenu)
        self.menu_bar.show_all()
        if USE_WINDOW_MENU:
            self.window_menu_item = self.get_menu("Windows")
            if self.window_menu_item:
                macapp = get_OSXApplication()
                macapp.set_window_menu(self.window_menu_item)

    def get_extra_menus(self) -> list:
        menus = []

        def add(menu, item):
            if item:
                menu.add(item)

        if SHOW_INFO_MENU:
            info_menu = self.make_menu()
            menus.append(("Info", info_menu))
            add(info_menu, self.make_sessioninfomenuitem())
            if SHOW_QR:
                add(info_menu, self.make_qrmenuitem())
            if SHOW_VERSION_CHECK:
                add(info_menu, self.make_updatecheckmenuitem())
            add(info_menu, self.make_bugreportmenuitem())
        if SHOW_FEATURES_MENU:
            features_menu = self.make_menu()
            menus.append(("Features", features_menu))
            self.append_featuresmenuitems(features_menu)
            if features.windows:
                add(features_menu, self.make_swapkeysmenuitem())
                add(features_menu, self.make_invertmousewheelmenuitem())
                add(features_menu, self.make_numlockmenuitem())
                add(features_menu, self.make_scalingmenuitem())
        if features.clipboard and SHOW_CLIPBOARD_MENU:
            clipboard_menu = self.make_menu()
            menus.append(("Clipboard", clipboard_menu))
            for label in CLIPBOARD_LABELS:
                add(clipboard_menu, self.make_clipboard_submenuitem(label, self._remote_clipboard_changed))
            add(clipboard_menu, Gtk.SeparatorMenuItem())
            for label in CLIPBOARD_DIRECTION_LABELS:
                add(clipboard_menu, self.make_clipboard_submenuitem(label, self._clipboard_direction_changed))
            clipboard_menu.show_all()
            self.after_handshake(self.set_clipboard_menu, clipboard_menu)
        if features.audio and SHOW_SOUND_MENU:
            audio_menu = self.make_menu()
            if self.client.speaker_allowed and self.client.speaker_codecs:
                add(audio_menu, self.make_speakermenuitem())
            if self.client.microphone_allowed and self.client.microphone_codecs:
                add(audio_menu, self.make_microphonemenuitem())
            menus.append(("Audio", audio_menu))
        if features.windows and SHOW_ENCODINGS_MENU:
            encodings_menu = self.make_menu()

            def set_encodings_menu(*_args):
                client_encodings, server_encodings = self.get_encoding_options()
                from xpra.client.gtk3.menu_helper import populate_encodingsmenu
                populate_encodingsmenu(encodings_menu, self.get_current_encoding, self.set_current_encoding,
                                       client_encodings, server_encodings)

            self.after_handshake(set_encodings_menu)
            menus.append(("Encoding", encodings_menu))
        if features.windows and SHOW_ACTIONS_MENU:
            actions_menu = self.make_menu()
            add(actions_menu, self.make_raisewindowsmenuitem())
            add(actions_menu, self.make_minimizewindowsmenuitem())
            add(actions_menu, self.make_refreshmenuitem())
            add(actions_menu, self.make_reinitmenuitem())
            self.window_menu = actions_menu
            menus.append(("Windows", actions_menu))
        if RUNCOMMAND_MENU or SHOW_SERVER_COMMANDS or SHOW_UPLOAD or SHOW_SHUTDOWN:
            server_menu = self.make_menu()
            if SHOW_SHUTDOWN:
                add(server_menu, self.make_shutdownmenuitem())

            # set_sensitive(bool) does not work on OSX,
            # so we only add the menu item if it does something
            def add_ah(*_args):
                if self.client.server_start_new_commands:
                    add(server_menu, self.make_runcommandmenuitem())
                if SHOW_SERVER_COMMANDS and self.client.server_commands_info:
                    add(server_menu, self.make_servercommandsmenuitem())
                if SHOW_UPLOAD and self.client.remote_file_transfer:
                    add(server_menu, self.make_uploadmenuitem())

            self.after_handshake(add_ah)
            menus.append(("Server", server_menu))
        menus.append((SEPARATOR + "-EXTRAS", None))
        return menus

    def _clipboard_direction_changed(self, item, label: str):
        clipboardlog("_clipboard_direction_changed(%s, %s) clipboard_change_pending=%s",
                     item, label, self._clipboard_change_pending)
        label = self.select_clipboard_menu_option(item, label, CLIPBOARD_DIRECTION_LABELS)
        self.do_clipboard_direction_changed(label or "")

    def _remote_clipboard_changed(self, item, label: str):
        clipboardlog("_remote_clipboard_changed(%s, %s) clipboard_change_pending=%s",
                     item, label, self._clipboard_change_pending)
        # ensure this is the only clipboard label selected:
        label = self.select_clipboard_menu_option(item, label, CLIPBOARD_LABELS)
        if not label:
            return
        remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
        clipboardlog("will select clipboard menu item with label=%s, for remote_clipboard=%s", label, remote_clipboard)
        GLib.timeout_add(0, self._do_clipboard_change, remote_clipboard)

    def _do_clipboard_change(self, remote_clipboard: str):
        # why do we look it up again when we could just pass it in
        # to make_clipboard_submenuitem as an extra argument?
        # because gtk-osx would fall over itself, making a complete mess of the menus in the process
        # and why do we use a timer here? again, more trouble with gtk-osx..
        self._clipboard_change_pending = False
        self.set_new_remote_clipboard(remote_clipboard)

    def make_clipboard_submenuitem(self, label: str, cb: Callable = noop):
        clipboard_item = self.checkitem(label)
        clipboard_item.set_draw_as_radio(True)

        def clipboard_option_changed(item):
            clipboardlog("clipboard_option_changed(%s) label=%s, callback=%s clipboard_change_pending=%s",
                         item, label, cb, self._clipboard_change_pending)
            cb(item, label)

        clipboard_item.connect("toggled", clipboard_option_changed)
        return clipboard_item

    def select_clipboard_menu_option(self, item=None, label: str = "", labels=()):
        # ensure that only the matching menu item is selected,
        # (can be specified as a menuitem object, or using its label)
        # all the other menu items whose labels are specified will be made inactive
        # (we use a flag to prevent reentry)
        clipboardlog("select_clipboard_menu_option(%s, %s, %s) clipboard_change_pending=%s",
                     item, label, labels, self._clipboard_change_pending)
        if self._clipboard_change_pending:
            return None
        clipboard = self.get_menu("Clipboard")
        if not clipboard:
            log.error("Error: cannot locate Clipboard menu object!")
            return None
        all_items = [x for x in clipboard.get_submenu().get_children() if x.get_label() in labels]
        selected_items = [x for x in all_items if x == item] + [x for x in all_items if x.get_label() == label]
        if not selected_items:
            log.error("Error: cannot find any clipboard menu options to match '%s'", label)
            log.error(" all menu items: %s", csv(x.get_label() for x in all_items))
            log.error(" selected: %s", csv(x.get_label() for x in selected_items))
            return None
        self._clipboard_change_pending = True
        sel = selected_items[0]
        if not label:
            label = sel.get_label()
        for x in all_items:
            active = x.get_label() == label
            if x.get_active() != active:
                x.set_active(active)
        self._clipboard_change_pending = False
        return label

    def set_clipboard_menu(self, clipboard_menu) -> None:
        # find the menu item matching the current settings,
        # and select it
        try:
            ch = self.client.clipboard_helper
            rc_setting = "Clipboard"
            if len(ch._local_to_remote) == 1:
                rc_setting = tuple(ch._local_to_remote.values())[0]
            label = CLIPBOARD_NAME_TO_LABEL.get(rc_setting)
            clipboardlog(f"set_clipboard_menu(%s) setting={rc_setting!r}, {label=}", clipboard_menu)
            self.select_clipboard_menu_option(None, label, CLIPBOARD_LABELS)
        except RuntimeError:
            clipboardlog("failed to select remote clipboard option in menu", exc_info=True)
        direction = self.client.client_clipboard_direction
        direction_label = CLIPBOARD_DIRECTION_NAME_TO_LABEL.get(direction, "Disabled")
        clipboardlog("direction(%s)=%s", direction, direction_label)
        self.select_clipboard_menu_option(None, direction_label, CLIPBOARD_DIRECTION_LABELS)

    # these methods are called by the superclass,
    # but we don't have a quality or speed menu,
    # so override and ignore
    def set_qualitymenu(self, *args):
        pass  # no quality menu on MacOS

    def set_speedmenu(self, *args):
        pass  # no speed menu on MacOS

    def _get_keyboard(self):
        if not self.client or not self.client.keyboard_helper:
            return None
        return self.client.keyboard_helper.keyboard

    def make_swapkeysmenuitem(self):
        def swapkeys_toggled(*args):
            v = swapkeys_menuitem.get_active()
            keyboard = self._get_keyboard()
            log("swapkeys_toggled(%s) keyboard=%s, swap keys enabled=%s", args, keyboard, v)
            if keyboard:
                keyboard.swap_keys = v

        swapkeys_menuitem = self.checkitem("Control/Command Key Swap", swapkeys_toggled)

        def set_swapkeys_menuitem(*args):
            keyboard = self._get_keyboard()
            if keyboard:
                log("set_swapkeys_menuitem(%s) keyboard=%s, swap_keys=%s", args, keyboard, keyboard.swap_keys)
                swapkeys_menuitem.set_active(keyboard.swap_keys)
            else:
                log("set_swapkeys_menuitem(%s) no keyboard!", args)
                swapkeys_menuitem.set_sensitive(False)

        self.after_handshake(set_swapkeys_menuitem)
        return swapkeys_menuitem

    def make_invertmousewheelmenuitem(self):
        def invert_toggled(*args):
            v = mousewheel_menuitem.get_active()
            log("invert_toggled(%s) invert enabled=%s", args, v)
            if v:
                self.client.wheel_map[4] = 5
                self.client.wheel_map[5] = 4
            else:
                self.client.wheel_map[4] = 4
                self.client.wheel_map[5] = 5

        mousewheel_menuitem = self.checkitem("Invert Mouse Wheel", invert_toggled)
        mousewheel_menuitem.set_active(self.client.wheel_map.get(4) != 4)
        return mousewheel_menuitem

    def make_numlockmenuitem(self):
        def numlock_toggled(*args):
            v = self.numlock_menuitem.get_active()
            keyboard = self._get_keyboard()
            log("numlock_toggled(%s) menu active=%s", args, v)
            if keyboard:
                keyboard.num_lock_state = v

        self.numlock_menuitem = self.checkitem("Num Lock", cb=numlock_toggled)
        self.numlock_menuitem.set_active(True)

        def set_numlock_menuitem(*args):
            keyboard = self._get_keyboard()
            if keyboard:
                log("set_numlock_menuitem(%s) keyboard=%s, num_lock_state=%s", args, keyboard, keyboard.num_lock_state)
                self.numlock_menuitem.set_active(keyboard.num_lock_state)
            else:
                log("set_numlock_menuitem(%s) no keyboard!", args)
                self.numlock_menuitem.set_sensitive(False)

        self.after_handshake(set_numlock_menuitem)
        return self.numlock_menuitem

    def update_numlock(self, on):
        if self.numlock_menuitem:
            self.numlock_menuitem.set_active(on)

    def build_dock_menu(self):
        log("OSXMenuHelper.build_dock_menu()")
        self.dock_menu = self.make_menu()
        if SHOW_ABOUT_XPRA:
            self.dock_menu.add(self.menuitem("About Xpra", "information.png", None, about))
        self.dock_menu.show_all()
        return self.dock_menu

    # the code below is mostly duplicated from xpra/client/gtk2...

    def get_image(self, icon_name, size=None):
        try:
            pixbuf = get_icon(icon_name)
            log("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return None
            if size:
                return scaled_image(pixbuf, size)
            return Gtk.Image.new_from_pixbuf(pixbuf)
        except Exception:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return None
