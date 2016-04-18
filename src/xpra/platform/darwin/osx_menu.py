# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.gtk_common.gobject_compat import import_gtk, import_glib
gtk = import_gtk()
glib = import_glib()

from xpra.gtk_common.gtk_util import scaled_image
from xpra.gtk_common.about import about
from xpra.client.gtk_base.gtk_tray_menu_base import GTKTrayMenuBase, populate_encodingsmenu, CLIPBOARD_LABEL_TO_NAME, CLIPBOARD_LABELS
from xpra.platform.darwin.osx_clipboard import OSXClipboardProtocolHelper
from xpra.platform.paths import get_icon
from xpra.platform.darwin.gui import get_OSXApplication

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

SHOW_ABOUT_XPRA = True

SINGLE_MENU = os.environ.get("XPRA_OSX_SINGLE_MENU", "1")=="1"


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
            self.client.after_handshake(self.add_about)

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
        if self.full:
            return
        self.full = True
        assert self.client
        menus = self.get_extra_menus()
        for label, submenu in reversed(menus):
            self.add_top_level_menu(label, submenu)
        self.menu_bar.show_all()

    def get_extra_menus(self):
        menus = []
        if SHOW_INFO_MENU:
            info_menu = self.make_menu()
            info_menu.append(self.make_sessioninfomenuitem())
            info_menu.append(self.make_bugreportmenuitem())
            menus.append(("Info", info_menu))
        if SHOW_FEATURES_MENU:
            features_menu = self.make_menu()
            menus.append(("Features", features_menu))
            features_menu.add(self.make_bellmenuitem())
            features_menu.add(self.make_cursorsmenuitem())
            features_menu.add(self.make_notificationsmenuitem())
            features_menu.add(self.make_swapkeysmenuitem())
            features_menu.add(self.make_numlockmenuitem())
            features_menu.add(self.make_openglmenuitem())
            features_menu.add(self.make_scalingmenuitem())
        if SHOW_CLIPBOARD_MENU:
            clipboard_menu = self.make_menu()
            menus.append(("Clipboard", clipboard_menu))
            for label in CLIPBOARD_LABELS:
                remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
                clipboard_menu.add(self.make_clipboard_submenuitem(label, remote_clipboard))
            self.client.after_handshake(self.set_clipboard_menu, clipboard_menu)
        if SHOW_SOUND_MENU:
            sound_menu = self.make_menu()
            if self.client.speaker_allowed and len(self.client.speaker_codecs)>0:
                sound_menu.add(self.make_speakermenuitem())
            if self.client.microphone_allowed and len(self.client.microphone_codecs)>0:
                sound_menu.add(self.make_microphonemenuitem())
            menus.append(("Sound", sound_menu))
        if SHOW_ENCODINGS_MENU:
            encodings_menu = self.make_menu()
            def set_encodings_menu(*args):
                from xpra.codecs.loader import PREFERED_ENCODING_ORDER
                encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
                populate_encodingsmenu(encodings_menu, self.get_current_encoding, self.set_current_encoding, encodings, self.client.server_encodings)
            self.client.after_handshake(set_encodings_menu)
            menus.append(("Encoding", encodings_menu))
        if SHOW_ACTIONS_MENU:
            actions_menu = self.make_menu()
            actions_menu.add(self.make_refreshmenuitem())
            actions_menu.add(self.make_raisewindowsmenuitem())
            #set_sensitive(bool) does not work on OSX,
            #so we only add the menu item if it does something
            def add_ah(*args):
                if self.client.start_new_commands:
                    actions_menu.add(self.make_startnewcommandmenuitem())
                if self.client.server_file_transfer:
                    actions_menu.add(self.make_uploadmenuitem())
            self.client.after_handshake(add_ah)
            menus.append(("Actions", actions_menu))
        menus.append((SEPARATOR+"-EXTRAS", None))
        return menus

    def get_clipboard_helper_class(self):
        return OSXClipboardProtocolHelper

    def make_clipboard_submenuitem(self, label, selection):
        clipboard_item = self.checkitem(label)
        clipboard_item.set_draw_as_radio(True)
        def remote_clipboard_changed(item):
            clipboardlog("remote_clipboard_changed(%s) label=%s - clipboard_change_pending=%s", item, label, self._clipboard_change_pending)
            self.select_clipboard_menu_option(item, label)
        clipboard_item.connect("toggled", remote_clipboard_changed)
        return clipboard_item

    def select_clipboard_menu_option(self, item=None, label="Disabled"):
        clipboardlog("select_clipboard_menu_option(%s, %s) clipboard_change_pending=%s", item, label, self._clipboard_change_pending)
        if self._clipboard_change_pending:
            return
        clipboard = self.get_menu("Clipboard")
        if not clipboard:
            log.error("Error: cannot locate Clipboad menu object!")
            return
        all_items = clipboard.get_submenu().get_children()
        selected_items = [x for x in all_items if x==item] + [x for x in all_items if x.get_label()==label]
        default_items = [x for x in all_items if x.get_label()=="Disabled"]
        options = selected_items+default_items
        if not options:
            log.error("Error: cannot find any clipboard menu options to match!")
            return
        self._clipboard_change_pending = True
        sel = options[0]
        remote_clipboard = CLIPBOARD_LABEL_TO_NAME.get(sel.get_label())
        clipboardlog("will select clipboard menu item with label=%s, for remote_clipboard=%s", sel.get_label(), remote_clipboard)
        for x in all_items:
            x.set_active(x.get_label()==sel.get_label())
        glib.timeout_add(0, self.do_clipboard_change, remote_clipboard)

    def do_clipboard_change(self, remote_clipboard):
        #why do we look it up again when we could just pass it in
        #to make_clipboard_submenuitem as an extra argument?
        #because gtk-osx would fall over itself, making a complete mess of the menus in the process
        #and why do we use a timer here? again, more trouble with gtk-osx..
        self._clipboard_change_pending = False
        self.set_new_remote_clipboard(remote_clipboard)

    def set_clipboard_menu(self, clipboard_menu):
        #find the menu item matching the current settings,
        #and select it
        try:
            assert self._can_handle_clipboard()
            remote_clipboard = self.client.clipboard_helper.remote_clipboard
            label = None
        except:
            remote_clipboard = None
            label = "Disabled"
        selected_menu_item = None
        for item in clipboard_menu.get_children():
            if remote_clipboard and remote_clipboard==CLIPBOARD_LABEL_TO_NAME.get(item.get_label()):
                selected_menu_item = item
                break
        self.select_clipboard_menu_option(selected_menu_item, label)

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
        return  self.swapkeys_menuitem

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
