#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.x11.gtk2.gdk_display_source import display    #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_set
from xpra.dbus.helper import DBusHelper
from xpra.dbus.gtk_menuactions import Menus, Actions

#beware: this import has side-effects:
import dbus.glib
assert dbus.glib
import gtk

from xpra.dbus.common import loop_init


def main(args):
    window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    window.set_size_request(200, 200)
    window.connect("delete_event", gtk.mainquit)
    window.realize()
    w = window.get_window()

    dbus_helper = DBusHelper()
    loop_init()
    session_bus = dbus_helper.get_session_bus()

    app_id = u"org.xpra.ExampleMenu"
    app_path = u"/org/xpra/ExampleMenu"
    menu_path = u"%s/menus/appmenu" % app_path
    window_path = u"%s/window/1" % app_path
    bus_name = session_bus.get_unique_name().decode()

    def action_cb(*args):
        print("action_cb%s" % str(args))
    window_actions={'reset'         : [True, 'b', [], action_cb],
                    'fullscreen'    : [True, '', [0], action_cb],
                    'about'         : [True, '', [], action_cb],
                    'preferences'   : [True, '', [], action_cb],
                    'switch-tab'    : [True, 'i', [], action_cb],
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
                    'help'          : [True, '', []]}
    menuactions_service = Actions(app_id, window_path, session_bus, window_actions)
    app_actions = {
                    'quit'          : [True, '', []],
                    'about'         : [True, '', []],
                    'activate-tab'  : [True, 's', []],
                    'preferences'   : [True, '', []],
                    'help'          : [True, '', []],
                    'custom'        : [True, '', []],
                  }
    appactions_service = Actions(app_id, app_path, session_bus, app_actions)
    menus = {0:
             {
                0: [{':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}],
                1: [{'action': 'win.new-terminal', 'label': '_New Terminal', 'target': ['default', 'default']}],
                2: [{'action': 'app.preferences', 'label': '_Preferences'}],
                3: [{'action': 'app.help', 'label': '_Help'},
                    {'action': 'app.about', 'label': '_About'},
                    {'action': 'app.quit', 'label': '_Quit'}
                   ]
             },
             #not shown anywhere:
             #1:
             #{
             #   0: [{':section': (0, 1)}],
             #   1: [{'action': 'app.custom', 'label': '_Custom'}]
             #},
            }
    menus_service = Menus(app_id, menu_path, session_bus, menus)

    def pset(key, etype, value, ignore_errors=True):
        return prop_set(w, key, etype, value)
    pset("_GTK_APP_MENU_OBJECT_PATH", "utf8", menu_path)
    pset("_GTK_WINDOW_OBJECT_PATH", "utf8", window_path)
    pset("_GTK_APPLICATION_OBJECT_PATH", "utf8", app_path)
    pset("_GTK_UNIQUE_BUS_NAME", "utf8", bus_name)
    pset("_GTK_APPLICATION_ID", "utf8", app_id)
    print("gtk menu properties for window %#x on display %s" % (w.xid, display.get_name()))

    import copy
    new_menus = copy.deepcopy(menus)
    #remove about:
    help_about_quit = new_menus[0][3]
    help_about_quit.remove(help_about_quit[1])

    both_menus = [menus, new_menus]
    def toggle_menu(*args):
        menus_service.set_menus(both_menus[0])
        saved = list(both_menus)
        both_menus[0] = saved[1]
        both_menus[1] = saved[0]
        return True
    import gobject
    gobject.timeout_add(1000*5, toggle_menu)
    window.show()
    gtk.main()


if __name__ == '__main__':
    if "-v" in sys.argv or "--versbose" in sys.argv:
        from xpra.dbus.gtk_menuactions import log
        log.enable_debug()
    sys.exit(main(sys.argv))
