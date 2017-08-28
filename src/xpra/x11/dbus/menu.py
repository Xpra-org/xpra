# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import weakref
from xpra.log import Logger
log = Logger("menu")

from xpra.util import typedict
from xpra.os_util import bytestostr, strtobytes


def has_gtk_menu_support(root_window):
    #figure out if we can handle the "global menu" stuff:
    try:
        from xpra.dbus.helper import DBusHelper
        assert DBusHelper
    except Exception as e:
        log("has_menu_support() no dbus: %s", e)
        return False
    try:
        from xpra.x11.gtk_x11.prop import prop_get
    except Exception as e:
        log("has_menu_support() no X11 bindings: %s", e)
        return False
    v = prop_get(root_window, "_NET_SUPPORTED", ["atom"], ignore_errors=True, raise_xerrors=False)
    if not v:
        log("has_menu_support() _NET_SUPPORTED is empty!?")
        return False
    show_window_menu = "_GTK_SHOW_WINDOW_MENU" in v
    log("has_menu_support() _GTK_SHOW_WINDOW_MENU in _NET_SUPPORTED: %s", show_window_menu)
    return show_window_menu


window_menus = {}
window_menu_services = weakref.WeakValueDictionary()

fallback_menus = {}

def setup_dbus_window_menu(add, wid, menus, application_action_callback=None, window_action_callback=None):
    def nomenu():
        #tell caller to clear all properties if they exist:
        return {
                "_GTK_APP_MENU_OBJECT_PATH"     : None,
                "_GTK_WINDOW_OBJECT_PATH"       : None,
                "_GTK_APPLICATION_OBJECT_PATH"  : None,
                "_GTK_UNIQUE_BUS_NAME"          : None,
                "_GTK_APPLICATION_ID"           : None
                }
    if add is False:
        return nomenu()
    global window_menu_services, window_menus, fallback_menus
    if len(menus)==0 and fallback_menus:
        menus = fallback_menus
    #ie: menu = {
    #         'enabled': True,
    #         'application-id':         'org.xpra.ExampleMenu',
    #         'application-actions':    {'quit': (True, '', ()), 'about': (True, '', ()), 'help': (True, '', ()), 'custom': (True, '', ()), 'activate-tab': (True, 's', ()), 'preferences': (True, '', ())},
    #         'window-actions':         {'edit-profile': (True, 's', ()), 'reset': (True, 'b', ()), 'about': (True, '', ()), 'help': (True, '', ()), 'fullscreen': (True, '', (0,)), 'detach-tab': (True, '', ()), 'save-contents': (True, '', ()), 'zoom': (True, 'i', ()), 'move-tab': (True, 'i', ()), 'new-terminal': (True, '(ss)', ()), 'switch-tab': (True, 'i', ()), 'new-profile': (True, '', ()), 'close': (True, 's', ()), 'show-menubar': (True, '', (1,)), 'select-all': (True, '', ()), 'copy': (True, '', ()), 'paste': (True, 's', ()), 'find': (True, 's', ()), 'preferences': (True, '', ())},
    #         'window-menu':            {0:
    #               {0: ({':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}),
    #                1: ({'action': 'win.new-terminal', 'target': ('default', 'default'), 'label': '_New Terminal'},),
    #                2: ({'action': 'app.preferences', 'label': '_Preferences'},),
    #                3: ({'action': 'app.help', 'label': '_Help'}, {'action': 'app.about', 'label': '_About'}, {'action': 'app.quit', 'label': '_Quit'}),
    #                }
    #             }
    #           }
    enabled = menus.get("enabled", False)
    app_actions_service, window_actions_service, window_menu_service = None, None, None
    def remove_services(*_args):
        """ removes all the services if they are not longer used by any windows """
        for x in (app_actions_service, window_actions_service, window_menu_service):
            if x:
                if x not in window_menu_services.values():
                    try:
                        x.remove_from_connection()
                    except Exception as e:
                        log.warn("Error removing %s: %s", x, e)
        try:
            del window_menus[wid]
        except:
            pass
    if enabled:
        m = typedict(menus)
        app_id          = bytestostr(m.strget("application-id", b"org.xpra.Window%i" % wid)).decode()
        app_actions     = m.dictget("application-actions")
        window_actions  = m.dictget("window-actions")
        window_menu     = m.dictget("window-menu")
    if wid in window_menus:
        #update, destroy or re-create the services:
        app_actions_service, window_actions_service, window_menu_service, cur_app_id = window_menus[wid]
        if not enabled or cur_app_id!=app_id:
            remove_services()   #falls through to re-create them if enabled is True
            app_actions_service, window_actions_service, window_menu_service = None, None, None
        else:
            #update them:
            app_actions_service.set_actions(app_actions)
            window_actions_service.set_actions(window_actions)
            window_menu_service.set_menus(window_menu)
            return
    if not enabled:
        #tell caller to clear all properties if they exist:
        return nomenu()
    #make or re-use services:
    try:
        NAME_PREFIX = "org.xpra."
        from xpra.dbus.common import init_session_bus
        from xpra.dbus.gtk_menuactions import Menus, Actions
        session_bus = init_session_bus()
        bus_name = session_bus.get_unique_name().decode()
        name = app_id
        for strip in ("org.", "gtk.", "xpra.", "gnome."):
            if name.startswith(strip):
                name = name[len(strip):]
        name = NAME_PREFIX + name
        log("normalized named(%s)=%s", app_id, name)

        def get_service(service_class, name, path, *args):
            """ find the service by name and path, or create one """
            service = window_menu_services.get((service_class, name, path))
            if service is None:
                service = service_class(name, path, session_bus, *args)
                window_menu_services[(service_class, name, path)] = service
            return service

        app_path = strtobytes("/"+name.replace(".", "/")).decode()
        app_actions_service = get_service(Actions, name, app_path, app_actions, application_action_callback)

        #this one should be unique and therefore not re-used? (only one "window_action_callback"..)
        window_path = u"%s/window/%s" % (app_path, wid)
        window_actions_service = get_service(Actions, name, window_path, window_actions, window_action_callback)

        menu_path = u"%s/menus/appmenu" % app_path
        window_menu_service = get_service(Menus, app_id, menu_path, window_menu)
        window_menus[wid] = app_actions_service, window_actions_service, window_menu_service, app_id

        return {
                "_GTK_APP_MENU_OBJECT_PATH"     : ("utf8", menu_path),
                "_GTK_WINDOW_OBJECT_PATH"       : ("utf8", window_path),
                "_GTK_APPLICATION_OBJECT_PATH"  : ("utf8", app_path),
                "_GTK_UNIQUE_BUS_NAME"          : ("utf8", bus_name),
                "_GTK_APPLICATION_ID"           : ("utf8", app_id),
               }
    except Exception:
        log.error("Error: cannot parse or apply menu:", exc_info=True)
        remove_services()
        return nomenu()
