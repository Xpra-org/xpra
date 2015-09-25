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

    app_id = u"org.xpra.Terminal"
    app_path = u"/org/xpra/Terminal"
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
                    'help'          : [True, '', []]
                  }
    appactions_service = Actions(app_id, app_path, session_bus, app_actions)
    menus = {0:
             {0: [{':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}],
              1: [{'action': 'win.new-terminal', 'label': '_New Terminal', 'target': ['default', 'default']}],
              2: [{'action': 'app.preferences', 'label': '_Preferences'}],
              3: [{'action': 'app.help', 'label': '_Help'},
                  {'action': 'app.about', 'label': '_About'},
                  {'action': 'app.quit', 'label': '_Quit'}
                  ]
              }
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

    window.show()
    gtk.main()
    del menuactions_service, appactions_service, menus_service


if __name__ == '__main__':
    sys.exit(main(sys.argv))
