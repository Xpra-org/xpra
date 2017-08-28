# This file is part of Xpra.
# Copyright (C) 2015-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("tray", "menu")

from xpra.client.tray_base import TrayBase


class GTKMenuTray(TrayBase):
    """ This fake tray class is only used on desktop environments
        which support gtk menus.
        We add window hooks to our client windows to add our own menu,
        or merge with the existing one if they forward one already.
    """

    def __init__(self, client, *args):
        TrayBase.__init__(self, client, *args)
        self.client = client
        self.shown = False
        self.set_global_menu()

    def hide(self, *_args):
        if self.shown:
            self.shown = False
            self.set_global_menu()

    def show(self, *_args):
        if not self.shown:
            self.shown = True
            self.set_global_menu()

    def set_blinking(self, on):
        pass

    def set_tooltip(self, text=None):
        pass

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride, options={}):
        pass

    def do_set_icon_from_file(self, filename):
        pass

    def get_geometry(self):
        #keep it offscreen so it does not interfere with any windows
        #this should not be used because we only expose this class
        #for use as our own tray, not for system tray forwarding
        return [-100, -100, 32, 32]

    def _info_cb(self, *args):
        log("_info_cb%s", args)
        self.client.show_session_info()

    def _disconnect_cb(self, *args):
        log("_disconnect_cb%s", args)
        self.exit_cb()

    def _about_cb(self, *args):
        log("_about_cb%s", args)
        self.client.show_about()

    def set_global_menu(self):
        menus = {
                 'enabled': self.shown,
                 'application-id':         'org.xpra.DefaultGlobalMenu',
                 'application-actions':    {
                                            'xpra-info'          : (True, '', (), self._info_cb),
                                            'xpra-about'         : (True, '', (), self._about_cb),
                                            'xpra-disconnect'    : (True, '', (), self._disconnect_cb),
                                            },
                 'window-actions':         {},
                 'window-menu':            {0:
                                               {0: ({':section': (0, 1)}, {':section': (0, 2)}),
                                                1: ({'action': 'app.xpra-info',          'label': '_Session Info'},
                                                    {'action': 'app.xpra-about',         'label': '_About'},
                                                   ),
                                                2: ({'action': 'app.xpra-disconnect',    'label': '_Disconnect'},),
                                               }
                                           },
               }
        from xpra.x11.dbus import menu
        menu.fallback_menus = menus
        #menu.our_menu = "Xpra", menus
