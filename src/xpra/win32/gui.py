# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import os.path

from xpra.platform.client_extras_base import ClientExtrasBase
from xpra.platform.clipboard_base import DefaultClipboardProtocolHelper
from xpra.keys import get_gtk_keymap
from xpra.platform.keyboard_layouts import WIN32_LAYOUTS
from wimpiggy.log import Logger
log = Logger()

from wimpiggy.gobject_compat import import_gdk
gdk = import_gdk()


class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts, conn):
        ClientExtrasBase.__init__(self, client, opts, conn)
        try:
            from xpra.platform.gdk_clipboard import TranslatedClipboardProtocolHelper
            self.setup_clipboard_helper(TranslatedClipboardProtocolHelper)
        except ImportError, e:
            log.error("GDK Translated Clipboard failed to load: %s - using default fallback", e)
            self.setup_clipboard_helper(DefaultClipboardProtocolHelper)
        self.setup_exit_handler(True)
        self.setup_menu(True)
        self.setup_tray(opts.no_tray, opts.notifications, opts.tray_icon)
        self.emulate_altgr = False
        self.last_key_event_sent = None

    def cleanup(self):
        log("cleanup() tray=%s", self.tray)
        ClientExtrasBase.cleanup(self)
        if self.tray:
            self.tray.close()
            self.tray = None

    def setup_exit_handler(self, enable=1):
        try:
            import win32api     #@UnresolvedImport
            result = win32api.SetConsoleCtrlHandler(self.handle_console_event, enable)
            if result == 0:
                log.error("could not SetConsoleCtrlHandler (error %r)", win32api.GetLastError())
        except:
            pass

    def handle_console_event(self, event):
        log("handle_console_event(%s)", event)
        import win32con         #@UnresolvedImport
        events = {win32con.CTRL_C_EVENT         : "CTRL_C",
                  win32con.CTRL_LOGOFF_EVENT    : "LOGOFF",
                  win32con.CTRL_BREAK_EVENT     : "BREAK",
                  win32con.CTRL_SHUTDOWN_EVENT  : "SHUTDOWN",
                  win32con.CTRL_CLOSE_EVENT     : "CLOSE"
                  }
        if event in events:
            log.info("exiting on event %s", events.get(event))
            self.setup_exit_handler(enable=0)       #disable our handler
            self.quit()
            return 1
        return 0

    def can_notify(self):
        return  True

    def show_notify(self, dbus_id, nid, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if self.notify:
            self.notify(self.tray.getHWND(), summary, body, expire_timeout)


    def set_tooltip(self, text=None):
        if self.tray:
            self.tray.set_tooltip(text or self.get_tray_tooltip())

    def set_blinking(self, on):
        if self.tray:
            self.tray.set_blinking(on)

    def set_icon(self, basefilename):
        if not self.tray:
            return
        filename = os.path.join(self.get_data_dir(), "icons", "%s.ico" % basefilename)
        if not os.path.exists(filename):
            log.error("could not find icon %s", filename)
            return
        self.tray.set_icon(filename)

    def setup_tray(self, no_tray, notifications, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not no_tray:
            #we wait for session_name to be set during the handshake
            #the alternative would be to implement a set_name() method
            #on the Win32Tray - but this looks too complicated
            self.client.connect("handshake-complete", self.do_setup_tray, notifications, tray_icon_filename)

    def do_setup_tray(self, client, notifications, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            tray_icon_filename = self.get_icon_filename('xpra.ico')
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            log.error("invalid tray icon filename: '%s'" % tray_icon_filename)

        try:
            from xpra.win32.win32_tray import Win32Tray
            self.tray = Win32Tray(self.get_tray_tooltip(), self.activate_menu, self.quit, tray_icon_filename)
        except Exception, e:
            log.error("failed to load native Windows NotifyIcon: %s", e)

        #cant do balloon without a tray:
        if self.tray and notifications:
            try:
                from xpra.win32.win32_balloon import notify
                self.notify = notify
            except Exception, e:
                log.error("failed to load native win32 balloon: %s", e)

    def mask_to_names(self, mask):
        names = ClientExtrasBase.mask_to_names(self, mask)
        log("mask_to_names(%s)=%s, emulate_altgr=%s", mask, names, self.emulate_altgr)
        if self.emulate_altgr:
            self.AltGr_modifiers(names)
        return names

    def AltGr_modifiers(self, modifiers, pressed=True):
        clear = ["mod1", "mod2", "control"]
        if pressed:
            if "mod5" not in modifiers:
                modifiers.append("mod5")
        else:
            clear.append("mod5")
        for x in clear:
            if x in modifiers:
                modifiers.remove(x)

    def handle_key_event(self, send_key_action_cb, event, wid, pressed):
        """ Caps_Lock and Num_Lock don't work properly: they get reported more than once,
            they are reported as not pressed when the key is down, etc
            So we set the keycode to -1 to tell the server to ignore the actual keypress
            Having the "modifiers" set ought to be enough.
        """
        modifiers = self.mask_to_names(event.state)
        keyname = gdk.keyval_name(event.keyval)
        keyval = event.keyval
        keycode = event.hardware_keycode
        group = event.group
        string = event.string
        #meant to be in PyGTK since 2.10, not used yet so just return False if we don't have it:
        is_modifier = hasattr(event, "is_modifier") and event.is_modifier
        if keyval==2**24-1 and keyname=="VoidSymbol":
            return
        if keyname=="XNum_Lock":
            return
        #self.modifier_mappings = None       #{'control': [(37, 'Control_L'), (105, 'Control_R')], 'mod1':
        #self.modifier_keys = {}             #{"Control_L" : "control", ...}
        #self.modifier_keycodes = {}         #{"Control_R" : [105], ...}
        #self.modifier_keycodes = {"ISO_Level3_Shift": [108]}
        #we can only deal with 'Alt_R' and simulate AltGr (ISO_Level3_Shift)
        #if we have modifier_mappings
        if keyname=="Alt_R" and len(self.modifier_mappings)>0:
            keyname = "ISO_Level3_Shift"
            altgr_keycodes = self.modifier_keycodes.get(keyname, [])
            if len(altgr_keycodes)>0:
                keycode = altgr_keycodes[0]         #FIXME: we just pick the first one..
                self.emulate_altgr = pressed
                if pressed and self.last_key_event_sent:
                    #check for spurious control and undo it
                    last_wid, last_keyname, last_pressed = self.last_key_event_sent[:3]
                    if last_wid==wid and last_keyname=="Control_L" and last_pressed==True:
                        #undo it:
                        undo = self.last_key_event_sent[:]
                        undo[2] = False
                        send_key_action_cb(*undo)
                self.AltGr_modifiers(modifiers, not pressed)
        self.last_key_event_sent = [wid, keyname, pressed, modifiers, keyval, string, keycode, group, is_modifier]
        send_key_action_cb(*self.last_key_event_sent)

    def get_gtk_keymap(self):
        return  get_gtk_keymap()

    def get_keymap_modifiers(self):
        """
            ask the server to manage numlock, and lock can be missing from mouse events
            (or maybe this is virtualbox causing it?)
        """
        return  {}, [], ["lock"]

    def get_layout_spec(self):
        layout = None
        variant = None
        variants = None
        try:
            import win32api         #@UnresolvedImport
            kbid = win32api.GetKeyboardLayout(0) & 0xffff
            if kbid in WIN32_LAYOUTS:
                code, _, _, _, layout, variants = WIN32_LAYOUTS.get(kbid)
                log.debug("found keyboard layout '%s' with variants=%s, code '%s' for kbid=%s", layout, variants, code, kbid)
            if not layout:
                log.debug("unknown keyboard layout for kbid: %s", kbid)
        except Exception, e:
            log.error("failed to detect keyboard layout: %s", e)
        return layout,variant,variants

    def get_keyboard_repeat(self):
        try:
            import win32con         #@UnresolvedImport
            import win32gui         #@UnresolvedImport
            _delay = win32gui.SystemParametersInfo(win32con.SPI_GETKEYBOARDDELAY)
            _speed = win32gui.SystemParametersInfo(win32con.SPI_GETKEYBOARDSPEED)
            #now we need to normalize those weird win32 values:
            #0=250, 3=1000:
            delay = (_delay+1) * 250
            #0=1000/30, 31=1000/2.5
            _speed = min(31, max(0, _speed))
            speed = int(1000/(2.5+27.5*_speed/31))
            log.debug("keyboard repeat speed(%s)=%s, delay(%s)=%s", _speed, speed, _delay, delay)
            return  delay,speed
        except Exception, e:
            log.error("failed to get keyboard rate: %s", e)
        return None

    def popup_menu_workaround(self, menu):
        self.add_popup_menu_workaround(menu)
