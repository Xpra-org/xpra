# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display -- the parts that
# may import gtk.

import sys
import os
from wimpiggy.gobject_compat import import_gtk, import_gdk
gtk = import_gtk()
gdk = import_gdk()
_display = gdk.get_display()
assert _display, "cannot open the display with GTK, is DISPLAY set?"

from xpra.platform.client_extras_base import ClientExtrasBase
from xpra.platform.clipboard_base import DefaultClipboardProtocolHelper

from wimpiggy.log import Logger
log = Logger()


class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts, conn):
        ClientExtrasBase.__init__(self, client, opts, conn)
        try:
            from xpra.platform.gdk_clipboard import GDKClipboardProtocolHelper
            self.setup_clipboard_helper(GDKClipboardProtocolHelper)
        except ImportError, e:
            log.error("GDK Clipboard failed to load: %s - using 'Default Clipboard' fallback", e)
            self.setup_clipboard_helper(DefaultClipboardProtocolHelper)
        self.setup_menu(True)
        self.setup_tray(opts.no_tray, opts.delay_tray, opts.tray_icon)
        self.setup_xprops(opts.pulseaudio)
        self.setup_x11_bell()
        self.has_dbusnotify = False
        self.has_pynotify = False
        if opts.notifications:
            if not self.setup_dbusnotify() and not self.setup_pynotify():
                log.error("turning notifications off")

    def cleanup(self):
        ClientExtrasBase.cleanup(self)
        if self.tray_widget:
            self.hide_tray()
            self.tray_widget = None

    def get_data_dir(self):
        #is there a better/cleaner way?
        options = ["/usr/share/xpra", "/usr/local/share/xpra"]
        if sys.executable.startswith("/usr/local"):
            options.reverse()
        try:
            # test for a local installation path (run from source tree):
            local_share_path = os.path.join(os.path.dirname(sys.argv[0]), "..", "share", "xpra")
            if os.path.exists(local_share_path):
                options.insert(0, local_share_path)
        except:
            pass
        for x in options:
            if os.path.exists(x):
                return x
        return  os.getcwd()

    def get_icons_dir(self):
        return os.path.join(self.get_data_dir(), "icons")

    def get_tray_icon_filename(self, cmdlineoverride):
        if cmdlineoverride and os.path.exists(cmdlineoverride):
            log.debug("get_tray_icon_filename using %s from command line", cmdlineoverride)
            return  cmdlineoverride
        f = os.path.join(self.get_icons_dir(), "xpra.png")
        if os.path.exists(f):
            log.debug("get_tray_icon_filename using default: %s", f)
            return  f
        return  None

    def setup_statusicon(self, delay_tray, tray_icon_filename):
        self.tray_widget = None
        try:
            self.tray_widget = gtk.StatusIcon()
            def hide_tray(*args):
                self.tray_widget.set_visible(False)
            self.hide_tray = hide_tray
            if delay_tray:
                self.hide_tray()
            def show_tray(*args):
                log.info("showing tray")
                #session_name will get set during handshake
                self.tray_widget.set_visible(True)
            if hasattr(self.tray_widget, "set_tooltip_text"):
                self.tray_widget.set_tooltip_text(self.get_tray_tooltip())
            else:
                self.tray_widget.set_tooltip(self.get_tray_tooltip())
            self.tray_widget.connect('popup-menu', self.popup_menu)
            self.tray_widget.connect('activate', self.activate_menu)
            filename = self.get_tray_icon_filename(tray_icon_filename)
            if filename:
                if hasattr(self.tray_widget, "set_from_file"):
                    self.tray_widget.set_from_file(filename)
                else:
                    pixbuf = gdk.pixbuf_new_from_file(filename)
                    self.tray_widget.set_from_pixbuf(pixbuf)
            if delay_tray:
                self.client.connect("first-ui-received", show_tray)
            return True
        except Exception, e:
            log.info("could not setup gtk.StatusIcon: %s", e)
            return False

    def setup_appindicator(self, delay_tray, tray_icon_filename):
        try:
            import appindicator            #@UnresolvedImport
            filename = self.get_tray_icon_filename(tray_icon_filename)
            self.tray_widget = appindicator.Indicator("Xpra", filename, appindicator.CATEGORY_APPLICATION_STATUS)
            def hide_appindicator(*args):
                self.tray_widget.set_status(appindicator.STATUS_PASSIVE)
            self.hide_tray = hide_appindicator
            if delay_tray:
                self.hide_tray()
            def show_appindicator(*args):
                self.tray_widget.set_status(appindicator.STATUS_ACTIVE)
            if hasattr(self.tray_widget, "set_icon_theme_path"):
                self.tray_widget.set_icon_theme_path(self.get_icons_dir())
            self.tray_widget.set_attention_icon("xpra.png")
            if filename:
                self.tray_widget.set_icon(filename)
            else:
                self.tray_widget.set_label("Xpra")
            self.tray_widget.set_menu(self.menu)
            if delay_tray:
                self.client.connect("first-ui-received", show_appindicator)
            return  True
        except Exception, e:
            log.debug("could not setup appindicator: %s", e)
            return False

    def hide_tray(self):
        """ this method will be re-defined by one  of the setup_* methods
            (if one succeeds) """
        pass

    def _is_ubuntu_11_10_or_later(self):
        lsb = "/etc/lsb-release"
        if not os.path.exists(lsb):
            return  False
        try:
            try:
                f = open(lsb, mode='rb')
                data = f.read()
            finally:
                f.close()
            props = {}
            for l in data.splitlines():
                parts = l.split("=", 1)
                if len(parts)!=2:
                    continue
                props[parts[0].strip()] = parts[1].strip()
            log("found lsb properties: %s", props)
            if props.get("DISTRIB_ID")=="Ubuntu":
                version = [int(x) for x in props.get("DISTRIB_RELEASE", "0").split(".")]
                log("detected Ubuntu release %s", version)
                return version>=[11,10]
        except:
            return False

    def setup_tray(self, no_tray, delay_tray, tray_icon_filename):
        """ choose the most appropriate tray implementation
            Ubuntu is a disaster in this area, see:
            http://xpra.org/trac/ticket/43#comment:8
        """
        self.tray_widget = None
        self.hide_tray = None
        if no_tray:
            return
        if self._is_ubuntu_11_10_or_later() and self.setup_appindicator(delay_tray, tray_icon_filename):
            return
        if not self.setup_statusicon(delay_tray, tray_icon_filename):
            log.error("failed to setup tray icon")

    def setup_dbusnotify(self):
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        try:
            import dbus.glib
            assert dbus.glib
            self.dbus_session = dbus.SessionBus()
            FD_NOTIFICATIONS = 'org.freedesktop.Notifications'
            self.org_fd_notifications = self.dbus_session.get_object(FD_NOTIFICATIONS, '/org/freedesktop/Notifications')
            self.dbusnotify = dbus.Interface(self.org_fd_notifications, FD_NOTIFICATIONS)
            self.has_dbusnotify = True
            log("using dbusnotify: %s(%s)", type(self.dbusnotify), FD_NOTIFICATIONS)
        except Exception, e:
            log("cannot import dbus.glib notification wrapper: %s", e)
            log.error("failed to locate the dbus notification service")
        return self.has_dbusnotify

    def setup_pynotify(self):
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        try:
            import pynotify
            pynotify.init("Xpra")
            self.has_pynotify = True
            log("using pynotify: %s", pynotify)
        except ImportError, e:
            log.error("cannot import pynotify wrapper: %s", e)
        return self.has_pynotify

    def setup_x11_bell(self):
        self.has_x11_bell = False
        try:
            from wimpiggy.lowlevel.bindings import device_bell
            self.has_x11_bell = device_bell is not None
        except ImportError, e:
            log.error("cannot import x11 bell bindings (will use gtk fallback) : %s", e)

    def setup_xprops(self, pulseaudio):
        self.ROOT_PROPS = {
            "RESOURCE_MANAGER": "resource-manager"
            }
        if pulseaudio:
            self.ROOT_PROPS["PULSE_COOKIE"] = "pulse-cookie"
            self.ROOT_PROPS["PULSE_ID"] = "pulse-id"
            self.ROOT_PROPS["PULSE_SERVER"] = "pulse-server"
        def setup_xprop_xsettings(client):
            log.debug("setup_xprop_xsettings(%s)", client)
            try:
                from xpra.xposix.xsettings import XSettingsWatcher
                from xpra.xposix.xroot_props import XRootPropWatcher
                self._xsettings_watcher = XSettingsWatcher()
                self._xsettings_watcher.connect("xsettings-changed", self._handle_xsettings_changed)
                self._handle_xsettings_changed()
                self._root_props_watcher = XRootPropWatcher(self.ROOT_PROPS.keys())
                self._root_props_watcher.connect("root-prop-changed", self._handle_root_prop_changed)
                self._root_props_watcher.notify_all()
            except ImportError, e:
                log.error("failed to load X11 properties/settings bindings: %s - root window properties will not be propagated", e)
        self.client.connect("handshake-complete", setup_xprop_xsettings)

    def _handle_xsettings_changed(self, *args):
        blob = self._xsettings_watcher.get_settings_blob()
        log("xsettings_changed new value=%s", blob)
        if blob is not None:
            self.client.send("server-settings", {"xsettings-blob": blob})

    def _handle_root_prop_changed(self, obj, prop, value):
        log("root_prop_changed: %s=%s", prop, value)
        assert prop in self.ROOT_PROPS
        if value is not None:
            self.client.send("server-settings", {self.ROOT_PROPS[prop]: value.encode("utf-8")})

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if not self.has_x11_bell:
            gdk.beep()
            return
        from wimpiggy.error import trap, XError
        try:
            from wimpiggy.lowlevel.bindings import device_bell      #@UnresolvedImport
            trap.call_unsynced(device_bell, window, device, bell_class, bell_id, percent, bell_name)
        except XError, e:
            log.error("error using device_bell: %s, will fallback to gdk beep from now on", e)
            self.has_x11_bell = False

    def can_notify(self):
        return  self.has_dbusnotify or self.has_pynotify

    def show_notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, may_retry=True):
        if self.dbus_id==dbus_id:
            log.error("remote dbus instance is the same as our local one, "
                      "cannot forward notification to ourself as this would create a loop")
            return
        if self.has_dbusnotify:
            def cbReply(*args):
                log("notification reply: %s", args)
                return False
            def cbError(dbus_error, *args):
                try:
                    import dbus.exceptions
                    if type(dbus_error)==dbus.exceptions.DBusException:
                        message = dbus_error.get_dbus_message()
                        dbus_error_name = dbus_error.get_dbus_name()
                        if dbus_error_name!="org.freedesktop.DBus.Error.ServiceUnknown":
                            log.error("unhandled dbus exception: %s, %s", message, dbus_error_name)
                            return False

                        if not may_retry:
                            log.error("cannot send notification via dbus, please check that you notification service is operating properly")
                            return False

                        log.info("trying to re-connect to the notification service")
                        #try to connect to the notification again (just once):
                        if self.setup_dbusnotify():
                            self.show_notify(dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, may_retry=False)
                        return False
                except:
                    pass
                log.error("notification error: %s", dbus_error)
                return False
            try:
                self.dbusnotify.Notify("Xpra", 0, app_icon, summary, body, [], [], expire_timeout,
                     reply_handler = cbReply,
                     error_handler = cbError)
            except:
                log.error("dbus notify failed", exc_info=True)
        elif self.has_pynotify:
            try:
                import pynotify
                n = pynotify.Notification(summary, body)
                n.set_urgency(pynotify.URGENCY_LOW)
                n.set_timeout(expire_timeout)
                n.show()
            except:
                log.error("pynotify failed", exc_info=True)
        else:
            log.error("notification cannot be displayed, no backend support!")

    def close_notify(self, nid):
        pass

    def exec_get_keyboard_data(self, cmd):
        # Find the client's current keymap so we can send it to the server:
        try:
            import subprocess
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
            (out,_) = process.communicate(None)
            if process.returncode==0:
                return out.decode('utf-8')
            log.error("'%s' failed with exit code %s", cmd, process.returncode)
        except Exception, e:
            log.error("error running '%s': %s", cmd, e)
        return None

    def get_keymap_modifiers(self):
        try:
            from wimpiggy.lowlevel import get_modifier_mappings         #@UnresolvedImport
            mod_mappings = get_modifier_mappings()
            if mod_mappings:
                #ie: {"shift" : ["Shift_L", "Shift_R"], "mod1" : "Meta_L", ...]}
                log.debug("modifier mappings=%s", mod_mappings)
                meanings = {}
                for modifier,keys in mod_mappings.items():
                    for _,keyname in keys:
                        meanings[keyname] = modifier
                return  meanings, [], []
        except ImportError, e:
            log.error("failed to use native get_modifier_mappings: %s", e)
        except Exception, e:
            log.error("failed to use native get_modifier_mappings: %s", e, exc_info=True)
        return self.modifiers_fallback()

    def modifiers_fallback(self):
        xmodmap_pm = self.exec_get_keyboard_data(["xmodmap", "-pm"])
        if not xmodmap_pm:
            log.warn("bindings are not available and 'xmodmap -pm' also failed, expect keyboard mapping problems")
            return ClientExtrasBase.get_keymap_modifiers(self)
        #parse it so we can feed it back to xmodmap (ala "xmodmap -pke")
        meanings = {}
        for line in xmodmap_pm.splitlines()[1:]:
            if not line:
                continue
            parts = line.split()
            #ie: ['shift', 'Shift_L', '(0x32),', 'Shift_R', '(0x3e)']
            if len(parts)>1:
                nohex = [x for x in parts[1:] if not x.startswith("(")]
                for x in nohex:
                    #ie: meanings['Shift_L']=shift
                    meanings[x] = parts[0]
        log.debug("get_keymap_modifiers parsed: meanings=%s", meanings)
        return  meanings, [], []

    def get_x11_keymap(self):
        try:
            from wimpiggy.lowlevel import get_keycode_mappings      #@UnresolvedImport
            return get_keycode_mappings(gtk.gdk.get_default_root_window())
        except Exception, e:
            log.error("failed to use raw x11 keymap: %s", e)
        return  ""

    def get_keymap_spec(self):
        xkbmap_print = self.exec_get_keyboard_data(["setxkbmap", "-print"])
        if xkbmap_print is None:
            log.error("your keyboard mapping will probably be incorrect unless you are using a 'us' layout");
        xkbmap_query = self.exec_get_keyboard_data(["setxkbmap", "-query"])
        if xkbmap_query is None and xkbmap_print is not None:
            log.error("the server will try to guess your keyboard mapping, which works reasonably well in most cases");
            log.error("however, upgrading 'setxkbmap' to a version that supports the '-query' parameter is preferred");
        return xkbmap_print, xkbmap_query

    def get_keyboard_repeat(self):
        try:
            from wimpiggy.lowlevel import get_key_repeat_rate   #@UnresolvedImport
            delay, interval = get_key_repeat_rate()
            return delay,interval
        except Exception, e:
            log.error("failed to get keyboard repeat rate: %s", e)
        return None

    def grok_modifier_map(self, display_source, xkbmap_mod_meanings):
        try:
            from wimpiggy.keys import grok_modifier_map
            return grok_modifier_map(display_source, xkbmap_mod_meanings)
        except ImportError:
            return ClientExtrasBase.grok_modifier_map(self, display_source, xkbmap_mod_meanings)
