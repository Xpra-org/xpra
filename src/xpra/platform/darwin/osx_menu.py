# This file is part of Xpra.
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gtk, import_glib
gtk = import_gtk()
glib = import_glib()

from xpra.util import envbool, csv
from xpra.gtk_common.gtk_util import scaled_image
from xpra.gtk_common.about import about
from xpra.client.gtk_base.gtk_tray_menu_base import GTKTrayMenuBase, populate_encodingsmenu, \
            CLIPBOARD_LABEL_TO_NAME, CLIPBOARD_NAME_TO_LABEL, CLIPBOARD_LABELS, CLIPBOARD_DIRECTION_LABELS, CLIPBOARD_DIRECTION_NAME_TO_LABEL, \
            SHOW_UPLOAD, SHOW_VERSION_CHECK, RUNCOMMAND_MENU, SHOW_SERVER_COMMANDS, SHOW_SHUTDOWN
from xpra.platform.paths import get_icon
from xpra.platform.darwin.gui import get_OSXApplication
from xpra.client import mixin_features

from xpra.log import Logger
log = Logger("osx", "tray", "menu")
clipboardlog = Logger("osx", "menu", "clipboard")


#control which menus are shown in the OSX global menu:
SHOW_FEATURES_MENU = True
SHOW_SOUND_MENU = True
SHOW_ENCODINGS_MENU = True
SHOW_ACTIONS_MENU = True
SHOW_INFO_MENU = True
SHOW_CLIPBOARD_MENU = True
SHOW_SERVER_MENU = True

SHOW_ABOUT_XPRA = True

SINGLE_MENU = envbool("XPRA_OSX_SINGLE_MENU", True)


SEPARATOR = "SEPARATOR"


_OSXMenuHelper = None
def getOSXMenuHelper(client=None):
    global _OSXMenuHelper
    if _OSXMenuHelper is None:
        _OSXMenuHelper = OSXMenuHelper(client)
    elif client is not None:
        _OSXMenuHelper.set_client(client)
    return _OSXMenuHelper


class OSXMenuHelper(GTKTrayMenuBase):
    """
    we have to do this stuff here so we can
    re-use the same instance,
    and change the callbacks if needed.
    (that way, the launcher and the client can both change the menus)
    """

    def __init__(self, client=None):
        GTKTrayMenuBase.__init__(self, client)
        log("OSXMenuHelper(%s)", client)
        self.menu_bar = None
        self.hidden_window = None
        self.keyboard = None
        self.menus = {}             #all the "top-level" menu items we manage
        self.app_menus = {}         #the ones added to the app_menu via insert_app_menu_item (which cannot be removed!)
        self.full = False
        self.set_client(client)
        self._clipboard_change_pending = False

    def set_client(self, client):
        self.client = client
        if client and client.keyboard_helper:
            self.keyboard = client.keyboard_helper.keyboard
        #if we call add_about before the main loop is ready,
        #things don't work...
        if client and SHOW_ABOUT_XPRA:
            client.after_handshake(self.add_about)

    def show_menu(self, button, time):
        #does not mean anything on OSX since the menu is controlled by the OS
        pass

    def build(self):
        log("OSXMenuHelper.build()")
        if self.menu_bar is None:
            self.menu_bar = gtk.MenuBar()
            self.menu_bar.show_all()
        return self.menu_bar

    def rebuild(self):
        log("OSXMenuHelper.rebuild()")
        if not self.menu_bar:
            return self.build()
        self.remove_all_menus()
        return self.menu_bar

    def remove_all_menus(self):
        log("OSXMenuHelper.remove_all_menus()")
        if self.menu_bar:
            for x in self.menus.values():
                if x in self.menu_bar.get_children():
                    self.menu_bar.remove(x)
                    x.hide()
        self.menus = {}
        self.full = False


    def add_top_level_menu(self, label, submenu):
        """ Adds the item to the app-menu or to the top bar,
            but only if it has not been added yet.
            (depending on the SINGLE_MENU flag)
        """
        if SINGLE_MENU:
            #add or re-use menu item in the app-menu:
            self.add_to_app_menu(label, submenu)
        else:
            self.add_to_menu_bar(label, submenu)

    def add_to_app_menu(self, label, submenu):
        item = self.app_menus.get(label)
        if item:
            log("application menu already has a '%s' entry", label)
            if submenu is not None:
                item.set_submenu(submenu)
            item.show_all()
        else:
            if label.startswith(SEPARATOR):
                item = gtk.SeparatorMenuItem()
            else:
                item = self.menuitem(label)
                item.set_submenu(submenu)
            item.show_all()
            macapp = get_OSXApplication()
            macapp.insert_app_menu_item(item, 1)
            self.app_menus[label] = item

    def add_to_menu_bar(self, label, submenu):
        if label.startswith(SEPARATOR):
            return      #not relevant
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

    def get_menu(self, label):
        if SINGLE_MENU:
            return self.app_menus.get(label)
        else:
            return self.menus.get(label)


    def add_about(self):
        if "About" in self.app_menus:
            return
        item = self.menuitem("About", cb=about)
        item.show_all()
        macapp = get_OSXApplication()
        macapp.insert_app_menu_item(item, 0)
        self.app_menus["About"] = item


    def add_full_menu(self):
        log("OSXMenuHelper.add_full_menu()")
        if self.full or not self.client:
            return
        self.full = True
        menus = self.get_extra_menus()
        for label, submenu in reversed(menus):
            self.add_top_level_menu(label, submenu)
        self.menu_bar.show_all()

    def get_extra_menus(self):
        menus = []
        if SHOW_INFO_MENU:
            info_menu = self.make_menu()
            info_menu.append(self.make_sessioninfomenuitem())
            if SHOW_VERSION_CHECK:
                info_menu.append(self.make_updatecheckmenuitem())
            info_menu.append(self.make_bugreportmenuitem())
            menus.append(("Info", info_menu))
        if SHOW_FEATURES_MENU:
            features_menu = self.make_menu()
            menus.append(("Features", features_menu))
            self.append_featuresmenuitems(features_menu)
            if mixin_features.windows:
                features_menu.add(self.make_swapkeysmenuitem())
                features_menu.add(self.make_invertmousewheelmenuitem())
                features_menu.add(self.make_numlockmenuitem())
                features_menu.add(self.make_scalingmenuitem())
        if mixin_features.clipboard and SHOW_CLIPBOARD_MENU:
            clipboard_menu = self.make_menu()
            menus.append(("Clipboard", clipboard_menu))
            for label in CLIPBOARD_LABELS:
                clipboard_menu.add(self.make_clipboard_submenuitem(label, self._remote_clipboard_changed))
            clipboard_menu.add(gtk.SeparatorMenuItem())
            for label in CLIPBOARD_DIRECTION_LABELS:
                clipboard_menu.add(self.make_clipboard_submenuitem(label, self._clipboard_direction_changed))
            clipboard_menu.show_all()
            self.client.after_handshake(self.set_clipboard_menu, clipboard_menu)
        if mixin_features.audio and SHOW_SOUND_MENU:
            sound_menu = self.make_menu()
            if self.client.speaker_allowed and len(self.client.speaker_codecs)>0:
                sound_menu.add(self.make_speakermenuitem())
            if self.client.microphone_allowed and len(self.client.microphone_codecs)>0:
                sound_menu.add(self.make_microphonemenuitem())
            menus.append(("Sound", sound_menu))
        if mixin_features.windows and SHOW_ENCODINGS_MENU:
            encodings_menu = self.make_menu()
            def set_encodings_menu(*_args):
                from xpra.codecs.loader import PREFERED_ENCODING_ORDER
                server_encodings = list(self.client.server_encodings)
                encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
                if self.client.server_auto_video_encoding:
                    encodings.insert(0, "auto")
                    server_encodings.insert(0, "auto")
                populate_encodingsmenu(encodings_menu, self.get_current_encoding, self.set_current_encoding, encodings, server_encodings)
            self.client.after_handshake(set_encodings_menu)
            menus.append(("Encoding", encodings_menu))
        if mixin_features.windows and SHOW_ACTIONS_MENU:
            actions_menu = self.make_menu()
            actions_menu.add(self.make_refreshmenuitem())
            actions_menu.add(self.make_raisewindowsmenuitem())
            menus.append(("Actions", actions_menu))
        if RUNCOMMAND_MENU or SHOW_SERVER_COMMANDS or SHOW_UPLOAD or SHOW_SHUTDOWN:
            server_menu = self.make_menu()
            if SHOW_SHUTDOWN:
                server_menu.append(self.make_shutdownmenuitem())
            #set_sensitive(bool) does not work on OSX,
            #so we only add the menu item if it does something
            def add_ah(*_args):
                if self.client.server_start_new_commands:
                    server_menu.add(self.make_runcommandmenuitem())
                if SHOW_SERVER_COMMANDS and self.client.server_commands_info:
                    server_menu.append(self.make_servercommandsmenuitem())
                if SHOW_UPLOAD and self.client.remote_file_transfer:
                    server_menu.add(self.make_uploadmenuitem())
            self.client.after_handshake(add_ah)
            menus.append(("Server", server_menu))
        menus.append((SEPARATOR+"-EXTRAS", None))
        return menus


    def _clipboard_direction_changed(self, item, label):
        clipboardlog("_clipboard_direction_changed(%s, %s) clipboard_change_pending=%s", item, label, self._clipboard_change_pending)
        label = self.select_clipboard_menu_option(item, label, CLIPBOARD_DIRECTION_LABELS)
        self.do_clipboard_direction_changed(label or "")

    def _remote_clipboard_changed(self, item, label):
        clipboardlog("_remote_clipboard_changed(%s, %s) clipboard_change_pending=%s", item, label, self._clipboard_change_pending)
        #ensure this is the only clipboard label selected:
        label = self.select_clipboard_menu_option(item, label, CLIPBOARD_LABELS)
        if not label:
            return
        remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
        clipboardlog("will select clipboard menu item with label=%s, for remote_clipboard=%s", label, remote_clipboard)
        glib.timeout_add(0, self._do_clipboard_change, remote_clipboard)

    def _do_clipboard_change(self, remote_clipboard):
        #why do we look it up again when we could just pass it in
        #to make_clipboard_submenuitem as an extra argument?
        #because gtk-osx would fall over itself, making a complete mess of the menus in the process
        #and why do we use a timer here? again, more trouble with gtk-osx..
        self._clipboard_change_pending = False
        self.set_new_remote_clipboard(remote_clipboard)

    def make_clipboard_submenuitem(self, label, cb=None):
        clipboard_item = self.checkitem(label)
        clipboard_item.set_draw_as_radio(True)
        def clipboard_option_changed(item):
            clipboardlog("clipboard_option_changed(%s) label=%s, callback=%s clipboard_change_pending=%s", item, label, cb, self._clipboard_change_pending)
            if cb:
                cb(item, label)
        clipboard_item.connect("toggled", clipboard_option_changed)
        return clipboard_item

    def select_clipboard_menu_option(self, item=None, label=None, labels=[]):
        #ensure that only the matching menu item is selected,
        #(can be specified as a menuitem object, or using its label)
        #all the other menu items whose labels are specified will be made inactive
        #(we use a flag to prevent reentry)
        clipboardlog("select_clipboard_menu_option(%s, %s, %s) clipboard_change_pending=%s", item, label, labels, self._clipboard_change_pending)
        if self._clipboard_change_pending:
            return None
        clipboard = self.get_menu("Clipboard")
        if not clipboard:
            log.error("Error: cannot locate Clipboard menu object!")
            return None
        all_items = [x for x in clipboard.get_submenu().get_children() if x.get_label() in labels]
        selected_items = [x for x in all_items if x==item] + [x for x in all_items if x.get_label()==label]
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
            active = x.get_label()==label
            if x.get_active()!=active:
                x.set_active(active)
        self._clipboard_change_pending = False
        return label

    def set_clipboard_menu(self, _clipboard_menu):
        #find the menu item matching the current settings,
        #and select it
        try:
            label = CLIPBOARD_NAME_TO_LABEL.get(self.client.clipboard_helper.remote_clipboard)
            self.select_clipboard_menu_option(None, label, CLIPBOARD_LABELS)
        except:
            pass
        direction_label = CLIPBOARD_DIRECTION_NAME_TO_LABEL.get(self.client.client_clipboard_direction, "Disabled")
        clipboardlog("direction(%s)=%s", self.client.client_clipboard_direction, direction_label)
        self.select_clipboard_menu_option(None, direction_label, CLIPBOARD_DIRECTION_LABELS)


    #these methods are called by the superclass
    #but we don't have a quality or speed menu, so override and ignore
    def set_qualitymenu(self, *args):
        pass
    def set_speedmenu(self, *args):
        pass

    def make_swapkeysmenuitem(self):
        def swapkeys_toggled(*args):
            v = self.swapkeys_menuitem.get_active()
            log("swapkeys_toggled(%s) swap keys enabled=%s", args, v)
            if self.keyboard:
                self.keyboard.swap_keys = v
        self.swapkeys_menuitem = self.checkitem("Control/Command Key Swap", swapkeys_toggled)
        def set_swapkeys_menuitem(*args):
            if self.keyboard:
                log("set_swapkeys_menuitem(%s) swap_keys=%s", args, self.keyboard.swap_keys)
                self.swapkeys_menuitem.set_active(self.keyboard.swap_keys)
            else:
                log("set_swapkeys_menuitem(%s) no keyboard!", args)
                self.swapkeys_menuitem.set_sensitive(False)
        self.client.after_handshake(set_swapkeys_menuitem)
        return self.swapkeys_menuitem

    def make_invertmousewheelmenuitem(self):
        def invert_toggled(*args):
            v = self.mousewheel_menuitem.get_active()
            log.info("invert_toggled(%s) invert enabled=%s", args, v)
            if v:
                self.client.wheel_map[4] = 5
                self.client.wheel_map[5] = 4
            else:
                self.client.wheel_map[4] = 4
                self.client.wheel_map[5] = 5
        self.mousewheel_menuitem = self.checkitem("Invert Mouse Wheel", invert_toggled)
        self.mousewheel_menuitem.set_active(self.client.wheel_map.get(4)!=4)
        return self.mousewheel_menuitem

    def make_numlockmenuitem(self):
        def numlock_toggled(*args):
            v = self.numlock_menuitem.get_active()
            log("numlock_toggled(%s) menu active=%s", args, v)
            if self.keyboard:
                self.keyboard.num_lock_state = v
        self.numlock_menuitem = self.checkitem("Num Lock", cb=numlock_toggled)
        self.numlock_menuitem.set_active(True)
        def set_numlock_menuitem(*args):
            if self.keyboard:
                log("set_numlock_menuitem(%s) num_lock_state=%s", args, self.keyboard.num_lock_state)
                self.numlock_menuitem.set_active(self.keyboard.num_lock_state)
            else:
                log("set_numlock_menuitem(%s) no keyboard!", args)
                self.swapkeys_menuitem.set_sensitive(False)
        self.client.after_handshake(set_numlock_menuitem)
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

    #the code below is mostly duplicated from xpra/client/gtk2...

    def get_image(self, icon_name, size=None):
        try:
            pixbuf = get_icon(icon_name)
            log("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            if size:
                return scaled_image(pixbuf, size)
            return  gtk.image_new_from_pixbuf(pixbuf)
        except:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None
