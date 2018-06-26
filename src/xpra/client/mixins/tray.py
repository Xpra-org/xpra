# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("tray")

from xpra.platform.gui import get_native_tray_classes, get_native_tray_menu_helper_class
from xpra.os_util import bytestostr, strtobytes
from xpra.util import nonl, envint, make_instance, CLIENT_EXIT, XPRA_APP_ID
from xpra.client.mixins.stub_client_mixin import StubClientMixin


TRAY_DELAY = envint("XPRA_TRAY_DELAY", 0)


"""
Mixin for supporting our system tray
(not forwarding other application's trays - that's handled in WindowClient)
"""
class TrayClient(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        #settings:
        self.tray_enabled = False
        self.delay_tray = False
        self.tray_icon = None
        #state:
        self.tray = None
        self.menu_helper = None

    def init(self, opts):
        self.tray_enabled = opts.tray
        self.delay_tray = opts.delay_tray
        self.tray_icon = opts.tray_icon

    def init_ui(self):
        """ initialize user interface """
        if self.tray_enabled:
            self.menu_helper = self.make_tray_menu_helper()
            def setup_xpra_tray(*args):
                log("setup_xpra_tray%s", args)
                self.tray = self.setup_xpra_tray(self.tray_icon or "xpra")
                if self.tray:
                    self.tray.show()
                icon_timestamp = self.tray.icon_timestamp
                def reset_icon():
                    #re-set the icon after a short delay,
                    #seems to help with buggy tray geometries,
                    #but don't do it if we have already changed the icon
                    #(ie: the dynamic window icon code may have set a new one)
                    if icon_timestamp==self.tray.icon_timestamp:
                        self.tray.set_icon()
                self.timeout_add(1000, reset_icon)
            if self.delay_tray:
                self.connect("first-ui-received", setup_xpra_tray)
            else:
                #show shortly after the main loop starts running:
                self.timeout_add(TRAY_DELAY, setup_xpra_tray)

    def cleanup(self):
        t = self.tray
        if t:
            self.tray = None
            try:
                t.cleanup()
            except:
                log.error("error on tray cleanup", exc_info=True)


    def get_tray_classes(self):
        #subclasses may add their toolkit specific variants, if any
        #by overriding this method
        #use the native ones first:
        return get_native_tray_classes()

    def make_tray_menu_helper(self):
        """ menu helper class used by our tray (make_tray / setup_xpra_tray) """
        mhc = (get_native_tray_menu_helper_class(), self.get_tray_menu_helper_class())
        log("make_tray_menu_helper() tray menu helper classes: %s", mhc)
        return make_instance(mhc, self)

    def show_menu(self, *_args):
        if self.menu_helper:
            self.menu_helper.activate()

    def setup_xpra_tray(self, tray_icon_filename):
        tray = None
        #this is our own tray
        def xpra_tray_click(button, pressed, time=0):
            log("xpra_tray_click(%s, %s, %s)", button, pressed, time)
            if button==1 and pressed:
                self.idle_add(self.menu_helper.activate, button, time)
            elif button==3 and not pressed:
                self.idle_add(self.menu_helper.popup, button, time)
        def xpra_tray_mouseover(*args):
            log("xpra_tray_mouseover(%s)", args)
        def xpra_tray_exit(*args):
            log("xpra_tray_exit(%s)", args)
            self.disconnect_and_quit(0, CLIENT_EXIT)
        def xpra_tray_geometry(*args):
            if tray:
                log("xpra_tray_geometry%s geometry=%s", args, tray.get_geometry())
        menu = None
        if self.menu_helper:
            menu = self.menu_helper.build()
        tray = self.make_tray(XPRA_APP_ID, menu, self.get_tray_title(), tray_icon_filename, xpra_tray_geometry, xpra_tray_click, xpra_tray_mouseover, xpra_tray_exit)
        log("setup_xpra_tray(%s)=%s", tray_icon_filename, tray)
        if tray:
            def reset_tray_title():
                tray.set_tooltip(self.get_tray_title())
            self.after_handshake(reset_tray_title)
        return tray

    def make_tray(self, *args):
        """ tray used by our own application """
        tc = self.get_tray_classes()
        log("make_tray%s tray classes=%s", args, tc)
        return make_instance(tc, self, *args)

    def get_tray_title(self):
        t = []
        if self.session_name or self.server_session_name:
            t.append(self.session_name or self.server_session_name)
        if self._protocol and self._protocol._conn:
            t.append(bytestostr(self._protocol._conn.target))
        if len(t)==0:
            t.insert(0, u"Xpra")
        v = u"\n".join(t)
        log("get_tray_title()=%s (items=%s)", nonl(v), tuple(strtobytes(x) for x in t))
        return v
