#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import copy
import sys
from xpra.x11.gtk2.gdk_display_source import display  # @UnresolvedImport
assert display
from xpra.x11.gtk_x11.prop import prop_set, prop_del
from xpra.dbus.gtk_menuactions import Menus, Actions

# beware: this import has side-effects:
import dbus.glib
assert dbus.glib
import gtk
import gobject


class WindowWithMenu(gtk.Window):

    def __init__(self, *args):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_size_request(320, 500)
        self.connect("delete_event", gtk.mainquit)
        vbox = gtk.VBox()
        self.add(vbox)
        vbox.add(gtk.Label("Delay before actions:"))
        self.delay_entry = gtk.Entry(max=10)
        self.delay_entry.set_text("0")
        vbox.add(self.delay_entry)
        vbox.add(gtk.Label("App ID:"))
        self.app_id_entry = gtk.Entry(max=40)
        self.app_id_entry.set_text("org.xpra.ExampleMenu")
        vbox.add(self.app_id_entry)
        self.app_path_entry = gtk.Entry(max=40)
        self.app_path_entry.set_text("/org/xpra/ExampleMenu")
        vbox.add(self.app_path_entry)
        btn = gtk.Button("Publish Menu")
        btn.connect("clicked", self.delayed_call, self.publish_menu)
        vbox.add(btn)
        btn = gtk.Button("Remove Menu")
        btn.connect("clicked", self.delayed_call, self.remove_menu)
        vbox.add(btn)
        btn = gtk.Button("Toggle Menu")
        btn.connect("clicked", self.delayed_call, self.toggle_menu)
        vbox.add(btn)
        btn = gtk.Button("New Window")
        btn.connect("clicked", self.delayed_call, self.new_window)
        vbox.add(btn)
        #no services to begin with:
        self.window_actions_service, self.app_actions_service, self.menus_service = None, None, None
        from xpra.dbus.common import init_session_bus
        self.session_bus = init_session_bus(private=True)
        self.init_defaults()

    def init_defaults(self):
        self.window_actions = {
                    'reset'         : [True, 'b', [], self.action_cb],
                    'fullscreen'    : [True, '', [0], self.action_cb],
                    'about'         : [True, '', [], self.action_cb],
                    'preferences'   : [True, '', [], self.action_cb],
                    'switch-tab'    : [True, 'i', [], self.action_cb],
                    'detach-tab'    : [True, '', []],
                    'save-contents' : [True, '', []],
                    'edit-profile'  : [True, 's', []],
                    'zoom'          : [True, 'i', []],
                    'move-tab'      : [True, 'i', []],
                    'new-terminal'  : [True, '(ss)', []],
                    'select-all'    : [True, '', []],
                    'new-profile'   : [True, '', []],
                    'show-menubar'  : [True, '', [1]],
                    'close'         : [True, 's', []],
                    'copy'          : [True, '', []],
                    'paste'         : [True, 's', []],
                    'find'          : [True, 's', []],
                    'help'          : [True, '', []]
                }
        self.app_actions = {
                    'quit'          : [True, '', []],
                    'about'         : [True, '', []],
                    'activate-tab'  : [True, 's', []],
                    'preferences'   : [True, '', []],
                    'help'          : [True, '', []],
                    'custom'        : [True, '', []],
                  }
        self.initial_menus = {0:
             {
                0: [{':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}],
                1: [{'action': 'win.new-terminal', 'label': '_New Terminal', 'target': ['default', 'default']}],
                2: [{'action': 'app.preferences', 'label': '_Preferences'}],
                3: [{'action': 'app.help', 'label': '_Help'},
                    {'action': 'app.about', 'label': '_About'},
                    {'action': 'app.quit', 'label': '_Quit'}
                   ]
             },
             # not shown anywhere when defined (group=1):
             # 1:
             # {
             #   0: [{':section': (0, 1)}],
             #   1: [{'action': 'app.custom', 'label': '_Custom'}]
             # },
            }
        self.alt_menus1 = {0:
             {
                0: [{'action': 'app.help', 'label': '_Help'}, {':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}],
                1: [{'action': 'win.new-terminal', 'label': '_New Terminal', 'target': ['default', 'default']}],
                2: [{'action': 'app.preferences', 'label': '_Preferences'}],
                3: [{'action': 'app.help', 'label': '_Help'},
                    {'action': 'app.about', 'label': '_About'},
                    {'action': 'app.quit', 'label': '_Quit'}
                   ]
             },
             # not shown anywhere when defined (group=1):
             # 1:
             # {
             #   0: [{':section': (0, 1)}],
             #   1: [{'action': 'app.custom', 'label': '_Custom'}]
             # },
            }
        self.alt_menus2 = {}
        self.alt_menus2 = copy.deepcopy(self.alt_menus1)
        # remove about:
        help_about_quit = self.alt_menus2[0][3]
        help_about_quit.remove(help_about_quit[1])
        self.current_menus = self.initial_menus


    def delayed_call(self, btn, fn):
        print("delayed_call(%s, %s)" % (btn, fn))
        delay = int(self.delay_entry.get_text())
        gobject.timeout_add(delay*1000, fn)

    def publish_menu(self, *args):
        print("publish_menu%s" % str(args))
        self.stop_dbus_services()
        self.set_props()
        self.setup_dbus_services()
        self.set_X11_props()

    def remove_menu(self, *args):
        print("remove_menu%s" % str(args))
        self.remove_X11_props()
        self.stop_dbus_services()


    def set_props(self):
        self.app_id = self.app_id_entry.get_text().decode()
        self.app_path = self.app_path_entry.get_text().decode()
        self.menu_path = u"%s/menus/appmenu" % self.app_path
        self.window_path = u"%s/window/1" % self.app_path
        self.bus_name = self.session_bus.get_unique_name().decode()

    def stop_dbus_services(self):
        for x in (self.window_actions_service, self.app_actions_service, self.menus_service):
            if x:
                x.remove_from_connection()
        self.window_actions_service, self.app_actions_service, self.menus_service = None, None, None

    def setup_dbus_services(self):
        self.window_actions_service = Actions(self.app_id, self.window_path, self.session_bus, self.window_actions)
        self.app_actions_service = Actions(self.app_id, self.app_path, self.session_bus, self.app_actions)
        self.menus_service = Menus(self.app_id, self.menu_path, self.session_bus, self.current_menus)

    def set_X11_props(self):
        w = self.get_window()
        def pset(key, value):
            return prop_set(w, key, "utf8", value)
        pset("_GTK_APPLICATION_OBJECT_PATH", self.app_path)
        pset("_GTK_WINDOW_OBJECT_PATH", self.window_path)
        pset("_GTK_UNIQUE_BUS_NAME", self.bus_name)
        pset("_GTK_APPLICATION_ID", self.app_id)
        pset("_GTK_APP_MENU_OBJECT_PATH", self.menu_path)

    def remove_X11_props(self):
        w = self.get_window()
        def pdel(key):
            return prop_del(w, key)
        pdel("_GTK_APP_MENU_OBJECT_PATH")
        pdel("_GTK_WINDOW_OBJECT_PATH")
        pdel("_GTK_APPLICATION_OBJECT_PATH")
        pdel("_GTK_UNIQUE_BUS_NAME")
        pdel("_GTK_APPLICATION_ID")


    def toggle_menu(self, *args):
        print("toggle_menu()")
        if self.current_menus == self.alt_menus1:
            m = self.alt_menus2
        else:
            m = self.alt_menus1
        self.current_menus = m
        if self.menus_service:
            self.menus_service.set_menus(self.current_menus)
        self.set_X11_props()

    def new_window(self, *args):
        w = WindowWithMenu()
        w.show_all()

    def action_cb(self, *args):
        print("action_cb%s" % str(args))



def main(args):
    from xpra.dbus.common import loop_init
    loop_init()
    w = WindowWithMenu()
    w.show_all()
    gtk.main()


if __name__ == '__main__':
    if "-v" in sys.argv or "--versbose" in sys.argv:
        from xpra.dbus.gtk_menuactions import log
        log.enable_debug()
    sys.exit(main(sys.argv))
