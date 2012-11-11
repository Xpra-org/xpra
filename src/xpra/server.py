# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Todo:
#   xsync resize stuff
#   shape?
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk.gdk
gtk.gdk.threads_init()

import os.path
import threading
import gobject
import sys
import hmac
import uuid
try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport
import time

from wimpiggy.wm import Wm
from wimpiggy.tray import SystemTray, get_tray_window
from wimpiggy.util import (AdHocStruct,
                           one_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from wimpiggy.lowlevel import (xtest_fake_key,              #@UnresolvedImport
                               xtest_fake_button,           #@UnresolvedImport
                               set_key_repeat_rate,         #@UnresolvedImport
                               unpress_all_keys,            #@UnresolvedImport
                               is_override_redirect,        #@UnresolvedImport
                               is_mapped,                   #@UnresolvedImport
                               add_event_receiver,          #@UnresolvedImport
                               get_cursor_image,            #@UnresolvedImport
                               get_children,                #@UnresolvedImport
                               has_randr, get_screen_sizes, #@UnresolvedImport
                               set_screen_size,             #@UnresolvedImport
                               get_screen_size,             #@UnresolvedImport
                               init_x11_filter,             #@UnresolvedImport
                               get_xatom,                   #@UnresolvedImport
                               )
from wimpiggy.prop import prop_set, set_xsettings_format
from wimpiggy.window import OverrideRedirectWindowModel, SystemTrayWindowModel, Unmanageable
from wimpiggy.error import XError, trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.server_source import ServerSource
from xpra.pixbuf_to_rgb import get_rgb_rawdata
from xpra.bytestreams import SocketConnection
from xpra.protocol import Protocol, zlib_compress, has_rencode
from xpra.platform.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.xkbhelper import clean_keyboard_state
from xpra.xposix.xsettings import XSettingsManager
from xpra.scripts.main import ENCODINGS, ENCRYPTION_CIPHERS
from xpra.version_util import is_compatible_with, add_version_info, add_gtk_version_info

MAX_CONCURRENT_CONNECTIONS = 20


class DesktopManager(gtk.Widget):
    def __init__(self):
        gtk.Widget.__init__(self)
        self.set_property("can-focus", True)
        self.set_flags(gtk.NO_WINDOW)
        self._models = {}

    ## For communicating with the main WM:

    def add_window(self, model, x, y, w, h):
        assert self.flags() & gtk.REALIZED
        s = AdHocStruct()
        s.shown = False
        s.geom = [x, y, w, h]
        s.window = None
        self._models[model] = s
        model.connect("unmanaged", self._unmanaged)
        model.connect("ownership-election", self._elect_me)
        def new_geom(window_model, *args):
            log("new_geom(%s,%s)", window_model, args)
        model.connect("geometry", new_geom)
        model.ownership_election()

    def window_geometry(self, model):
        return self._models[model].geom

    def show_window(self, model):
        self._models[model].shown = True
        model.ownership_election()
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def configure_window(self, model, x, y, w, h):
        log("DesktopManager.configure_window(%s, %s, %s, %s, %s)", model, x, y, w, h)
        if not self.visible(model):
            self._models[model].shown = True
            model.set_property("iconic", False)
            model.ownership_election()
        self._models[model].geom = [x, y, w, h]
        model.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

    def raise_window(self, model):
        if model.is_OR():
            model.get_property("client-window").raise_()
        else:
            window = self._models[model].window
            if window is not None:
                window.raise_()

    ## For communicating with WindowModels:

    def _unmanaged(self, model, wm_exiting):
        del self._models[model]

    def _elect_me(self, model):
        if self.visible(model):
            return (1, self)
        else:
            return (-1, self)

    def take_window(self, model, window):
        window.reparent(self.window, 0, 0)
        self._models[model].window = window

    def window_size(self, model):
        w, h = self._models[model].geom[2:4]
        return w, h

    def window_position(self, model, w, h):
        [x, y, w0, h0] = self._models[model].geom
        if abs(w0-w)>1 or abs(h0-h)>1:
            log.warn("Uh-oh, our size doesn't fit window sizing constraints: "
                     "%sx%s vs %sx%s", w0, h0, w, h)
        return x, y

gobject.type_register(DesktopManager)

def window_name(window):
    from wimpiggy.prop import prop_get
    return prop_get(window, "_NET_WM_NAME", "utf8", True) or "unknown"

def window_info(window):
    from wimpiggy.prop import prop_get
    net_wm_name = prop_get(window, "_NET_WM_NAME", "utf8", True)
    return "%s %s (%s / %s)" % (net_wm_name, window, window.get_geometry(), window.is_visible())

def dump_windows():
    root = gtk.gdk.get_default_root_window()
    log("root window: %s" % root)
    children = get_children(root)
    log("%s windows" % len(children))
    for window in get_children(root):
        log("found window: %s", window_info(window))


class XpraServer(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-child-map-event": one_arg_signal,
        "wimpiggy-cursor-event": one_arg_signal,
        }

    def __init__(self, clobber, sockets, opts):
        gobject.GObject.__init__(self)
        dump_windows()

        init_x11_filter()
        self.init_x11_atoms()

        self.start_time = time.time()

        # Do this before creating the Wm object, to avoid clobbering its
        # selecting SubstructureRedirect.
        root = gtk.gdk.get_default_root_window()
        root.set_events(root.get_events() | gtk.gdk.SUBSTRUCTURE_MASK)
        root.property_change(gtk.gdk.atom_intern("XPRA_SERVER", False),
                            gtk.gdk.atom_intern("STRING", False),
                            8,
                            gtk.gdk.PROP_MODE_REPLACE,
                            xpra.__version__)
        add_event_receiver(root, self)

        self.default_dpi = int(opts.dpi)
        self.dpi = self.default_dpi

        # This must happen early, before loading in windows at least:
        self._potential_protocols = []
        self._server_sources = {}

        #so clients can store persistent attributes on windows:
        self.client_properties = {}

        self.supports_mmap = opts.mmap
        self.default_encoding = opts.encoding
        assert self.default_encoding in ENCODINGS
        self.session_name = opts.session_name
        try:
            import glib
            glib.set_application_name(self.session_name or "Xpra")
        except ImportError, e:
            log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)

        ### Create the WM object
        self._wm = Wm("Xpra", clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("window-resized", self._window_resized_signaled)
        self._wm.connect("bell", self._bell_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        # Tray handler:
        if opts.system_tray:
            try:
                self._tray = SystemTray()
            except Exception, e:
                log.error("cannot setup tray forwarding: %s", e, exc_info=True)
        else:
            self._tray = None

        self.default_cursor_data = None
        self.last_cursor_serial = None
        self.cursor_data = None
        def get_default_cursor():
            self.default_cursor_data = get_cursor_image()
            log("get_default_cursor=%s", self.default_cursor_data)
        trap.swallow(get_default_cursor)
        self._wm.enableCursors(True)

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        for window in get_children(root):
            if (is_override_redirect(window) and is_mapped(window)):
                self._add_new_or_window(window)

        ## These may get set by the client:
        self.xkbmap_mod_meanings = {}

        self.keyboard_config = None
        self.keymap_changing = False            #to ignore events when we know we are changing the configuration
        self.keyboard_sync = True
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1

        #store list of currently pressed keys
        #(using a dict only so we can display their names in debug messages)
        self.keys_pressed = {}
        self.keys_timedout = {}
        #timers for cancelling key repeat when we get jitter
        self.keys_repeat_timers = {}
        ### Set up keymap change notification:
        gtk.gdk.keymap_get_default().connect("keys-changed", self._keys_changed)
        #clear all modifiers
        clean_keyboard_state()

        ### Clipboard handling:
        self._clipboard_helper = None
        self._clipboard_client = None
        if opts.clipboard:
            self._clipboard_helper = GDKClipboardProtocolHelper(self.send_clipboard_packet)

        ### Misc. state:
        self._settings = {}
        self._xsettings_manager = None
        self._has_focus = 0
        self._upgrading = False

        self.compression_level = opts.compression_level
        self.password_file = opts.password_file

        self.randr = has_randr()
        if self.randr and len(get_screen_sizes())<=1:
            #disable randr when we are dealing with a Xvfb
            #with only one resolution available
            #since we don't support adding them on the fly yet
            self.randr = False
        if self.randr:
            display = gtk.gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1
        log("randr enabled: %s", self.randr)

        self.default_quality = opts.quality
        self.pulseaudio = opts.pulseaudio
        self.sharing = opts.sharing
        self.bell = opts.bell
        self.cursors = opts.cursors
        self.notifications_forwarder = None
        if opts.notifications:
            try:
                from xpra.dbus_notifications_forwarder import register
                self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback)
                if self.notifications_forwarder:
                    log.info("using notification forwarder: %s", self.notifications_forwarder)
            except Exception, e:
                log.error("error loading or registering our dbus notifications forwarder:")
                log.error("  %s", e)
                log.info("if you do not have a dedicated dbus session for this xpra instance,")
                log.info("  you should use the '--no-notifications' flag")
                log.info("")

        ### All right, we're ready to accept customers:
        for sock in sockets:
            self.add_listen_socket(sock)
        dump_windows()

    def init_x11_atoms(self):
        #some applications (like openoffice), do not work properly
        #if some x11 atoms aren't defined, so we define them in advance:
        for atom_name in ["_NET_WM_WINDOW_TYPE",
                          "_NET_WM_WINDOW_TYPE_NORMAL",
                          "_NET_WM_WINDOW_TYPE_DESKTOP",
                          "_NET_WM_WINDOW_TYPE_DOCK",
                          "_NET_WM_WINDOW_TYPE_TOOLBAR",
                          "_NET_WM_WINDOW_TYPE_MENU",
                          "_NET_WM_WINDOW_TYPE_UTILITY",
                          "_NET_WM_WINDOW_TYPE_SPLASH",
                          "_NET_WM_WINDOW_TYPE_DIALOG",
                          "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
                          "_NET_WM_WINDOW_TYPE_POPUP_MENU",
                          "_NET_WM_WINDOW_TYPE_TOOLTIP",
                          "_NET_WM_WINDOW_TYPE_NOTIFICATION",
                          "_NET_WM_WINDOW_TYPE_COMBO",
                          "_NET_WM_WINDOW_TYPE_DND",
                          "_NET_WM_WINDOW_TYPE_NORMAL"
                          ]:
            get_xatom(atom_name)

    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def quit(self, upgrading):
        self._upgrading = upgrading
        log.info("xpra is terminating.")
        sys.stdout.flush()
        gtk_main_quit_really()

    def run(self):
        log.info("xpra server version %s" % xpra.__version__)
        gtk_main_quit_on_fatal_exceptions_enable()
        def print_ready():
            log.info("xpra is ready.")
            sys.stdout.flush()
        gobject.idle_add(print_ready)
        gtk.main()
        log.info("xpra end of gtk.main().")
        return self._upgrading

    def cleanup(self, *args):
        if self._tray:
            self._tray.cleanup()
        if self.notifications_forwarder:
            try:
                self.notifications_forwarder.release()
            except Exception, e:
                log.error("failed to release dbus notification forwarder: %s", e)
        for proto in self._server_sources.keys():
            self.disconnect(proto, "shutting down")

    def _new_connection(self, listener, *args):
        sock, address = listener.accept()
        if len(self._potential_protocols)>=MAX_CONCURRENT_CONNECTIONS:
            log.error("too many connections (%s), ignoring new one", len(self._potential_protocols))
            sock.close()
            return  True
        sc = SocketConnection(sock, sock.getsockname(), address, sock.getpeername())
        log.info("New connection received: %s", sc)
        protocol = Protocol(sc, self.process_packet)
        protocol.salt = None
        protocol.set_compression_level(self.compression_level)
        self._potential_protocols.append(protocol)
        protocol.start()
        def verify_connection_accepted(protocol):
            if not protocol._closed and protocol in self._potential_protocols and protocol not in self._server_sources:
                log.error("connection timedout: %s", protocol)
                self.send_disconnect(protocol, "login timeout")
        gobject.timeout_add(10*1000, verify_connection_accepted, protocol)
        return True

    def _window_resized_signaled(self, wm, window):
        nw,nh = window.get_property("actual-size")
        geom = self._desktop_manager.window_geometry(window)
        log("XpraServer._window_resized_signaled(%s,%s) actual-size=%sx%s, current geometry=%s", wm, window, nw, nh, geom)
        geom[2:4] = nw,nh
        for ss in self._server_sources.values():
            ss.resize_window(self._window_to_id[window], nw, nh)

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_wimpiggy_cursor_event(self, event):
        if not self.cursors:
            return
        if self.last_cursor_serial==event.cursor_serial:
            log("ignoring cursor event with the same serial number")
            return
        self.last_cursor_serial = event.cursor_serial
        self.cursor_data = get_cursor_image()
        if self.cursor_data:
            pixels = self.cursor_data[7]
            if self.default_cursor_data and pixels==self.default_cursor_data[7]:
                log("cursor event: default cursor - clearing it")
                self.cursor_data = None
            elif pixels is not None:
                if len(pixels)<64:
                    self.cursor_data[7] = str(pixels)
                else:
                    self.cursor_data[7] = zlib_compress("cursor", pixels)
        else:
            log("do_wimpiggy_cursor_event(%s) failed to get cursor image", event)
        for ss in self._server_sources.values():
            ss.send_cursor(self.cursor_data)

    def _bell_signaled(self, wm, event):
        log("_bell_signaled(%s,%r)", wm, event)
        if not self.bell:
            return
        wid = 0
        if event.window!=gtk.gdk.get_default_root_window() and event.window_model is not None:
            try:
                wid = self._window_to_id[event.window_model]
            except:
                pass
        log("_bell_signaled(%s,%r) wid=%s", wm, event, wid)
        for ss in self._server_sources.values():
            ss.bell(wid, event.device, event.percent, event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name or "")

    def send_clipboard_packet(self, *parts):
        if self._clipboard_client:
            self._clipboard_client.send(*parts)

    def notify_callback(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        assert self.notifications_forwarder
        log("notify_callback(%s,%s,%s,%s,%s,%s,%s,%s) send_notifications=%s", dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, self.send_notifications)
        for ss in self._server_sources.values():
            ss.notify(dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout))

    def notify_close_callback(self, nid):
        assert self.notifications_forwarder
        log("notify_close_callback(%s)", nid)
        for ss in self._server_sources.values():
            ss.notify_close(int(nid))

    def do_wimpiggy_child_map_event(self, event):
        log("do_wimpiggy_child_map_event(%s)", event)
        raw_window = event.window
        if event.override_redirect:
            self._add_new_or_window(raw_window)

    def _add_new_window_common(self, window):
        wid = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        window.connect("client-contents-changed", self._contents_changed)
        window.connect("unmanaged", self._lost_window)
        return wid

    _window_export_properties = ("title", "size-hints")
    def _add_new_window(self, window):
        self._add_new_window_common(window)
        for prop in self._window_export_properties:
            window.connect("notify::%s" % prop, self._update_metadata)
        (x, y, w, h, _) = window.get_property("client-window").get_geometry()
        log("Discovered new ordinary window: %s (geometry=%s)", window, (x, y, w, h))
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)

    def _add_new_or_window(self, raw_window):
        log("Discovered new override-redirect window: %s (geometry=%s)", raw_window, raw_window.get_geometry())
        is_tray = get_tray_window(raw_window) is not None
        try:
            if is_tray:
                assert self._tray
                window = SystemTrayWindowModel(raw_window)
                wid = self._add_new_window_common(window)
                self._send_new_tray_window_packet(wid, window)
                return
            else:
                window = OverrideRedirectWindowModel(raw_window)
                self._add_new_window_common(window)
                window.connect("notify::geometry", self._or_window_geometry_changed)
                self._send_new_or_window_packet(window)
        except Unmanageable, e:
            log("cannot add %s: %s" % (window_info(raw_window), e))

    def _or_window_geometry_changed(self, window, pspec):
        (x, y, w, h) = window.get_property("geometry")
        log("or_window_geometry_changed: %s (window=%s)", window.get_property("geometry"), window)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.or_window_geometry(wid, window, x, y, w, h)

    # These are the names of WindowModel properties that, when they change,
    # trigger updates in the xpra window metadata:
    _all_metadata = ("title", "size-hints", "class-instance", "icon", "client-machine", "transient-for", "window-type", "modal")

    def _get_transient_for(self, window):
        transient_for = window.get_property("transient-for")
        if transient_for is None:
            return None
        log("found transient_for=%s, xid=%s", transient_for, transient_for.xid)
        #try to find the model for this window:
        for model in self._desktop_manager._models.keys():
            log("testing model %s: %s", model, model.client_window.xid)
            if model.client_window.xid==transient_for.xid:
                wid = self._window_to_id.get(model)
                log("found match, window id=%s", wid)
                return wid
        root = gtk.gdk.get_default_root_window()
        if root.xid==transient_for.xid:
            return -1       #-1 is the backwards compatible marker for root...
        log.info("not found transient_for=%s, xid=%s", transient_for, transient_for.xid)
        return  None

    def set_keymap(self, server_source):
        try:
            #prevent _keys_changed() from firing:
            #(using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
            self.keymap_changing = True

            self.keyboard_config = server_source.set_keymap(self.keyboard_config, self.keys_pressed)
        finally:
            # re-enable via idle_add to give all the pending
            # events a chance to run first (and get ignored)
            def reenable_keymap_changes(*args):
                self.keymap_changing = False
                self._keys_changed()
            gobject.idle_add(reenable_keymap_changes)

    def _keys_changed(self, *args):
        if not self.keymap_changing:
            for ss in self._server_sources.values():
                ss.keys_changed()

    def _clear_keys_pressed(self):
        #make sure the timers don't fire and interfere:
        if len(self.keys_repeat_timers)>0:
            for timer in self.keys_repeat_timers.values():
                gobject.source_remove(timer)
            self.keys_repeat_timers = {}
        #clear all the keys we know about:
        if len(self.keys_pressed)>0:
            log("clearing keys pressed: %s", self.keys_pressed)
            for keycode in self.keys_pressed.keys():
                xtest_fake_key(gtk.gdk.display_get_default(), keycode, False)
            self.keys_pressed = {}
        #this will take care of any remaining ones we are not aware of:
        #(there should not be any - but we want to be certain)
        unpress_all_keys(gtk.gdk.display_get_default())

    def _focus(self, server_source, wid, modifiers):
        log("_focus(%s,%s) has_focus=%s", wid, modifiers, self._has_focus)
        if self._has_focus != wid:
            def reset_focus():
                self._clear_keys_pressed()
                # FIXME: kind of a hack:
                self._has_focus = 0
                self._wm.get_property("toplevel").reset_x_focus()

            if wid == 0:
                return reset_focus()
            window = self._id_to_window.get(wid)
            if not window:
                return reset_focus()
            #no idea why we can't call this straight away!
            #but with win32 clients, it would often fail!???
            def give_focus():
                #problem with that is that the window may be gone by then!
                #so ignore those errors:
                trap.swallow(window.give_client_focus)
                return False
            gobject.idle_add(give_focus)
            if server_source and modifiers is not None:
                server_source.make_keymask_match(modifiers)
            self._has_focus = wid

    def _move_pointer(self, pos):
        (x, y) = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _damage(self, window, x, y, width, height, options=None):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.damage(wid, window, x, y, width, height, options)

    def _cancel_damage(self, wid, window):
        for ss in self._server_sources.values():
            ss.cancel_damage(wid, window)

    def _send_new_window_packet(self, window):
        geometry = self._desktop_manager.window_geometry(window)
        self._do_send_new_window_packet("new-window", window, geometry, self._all_metadata)

    def _send_new_or_window_packet(self, window):
        geometry = window.get_property("geometry")
        properties = ["transient-for", "window-type"]
        self._do_send_new_window_packet("new-override-redirect", window, geometry, properties)
        (_, _, w, h) = geometry
        self._damage(window, 0, 0, w, h)

    def _send_new_tray_window_packet(self, wid, window):
        (_, _, w, h) = window.get_property("geometry")
        for ss in self._server_sources.values():
            ss.new_tray(wid, window, w, h)
        self._damage(window, 0, 0, w, h)

    def _do_send_new_window_packet(self, ptype, window, geometry, properties):
        wid = self._window_to_id[window]
        x, y, w, h = geometry
        for ss in self._server_sources.values():
            ss.new_window(ptype, wid, window, x, y, w, h, properties, self.client_properties.get(ss.uuid))

    def _update_metadata(self, window, pspec):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.window_metadata(wid, window, pspec.name)

    def _lost_window(self, window, wm_exiting):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.lost_window(wid, window)
        del self._window_to_id[window]
        del self._id_to_window[wid]
        for ss in self._server_sources.values():
            ss.remove_window(wid, window)

    def _contents_changed(self, window, event):
        if window.is_OR() or self._desktop_manager.visible(window):
            self._damage(window, event.x, event.y, event.width, event.height)

    def _screen_size_changed(self, *args):
        log("_screen_size_changed(%s)", args)
        #randr has resized the screen, tell the client (if it supports it)
        gobject.idle_add(self.send_updated_screen_size)

    def send_updated_screen_size(self):
        max_w, max_h = self.get_max_screen_size()
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        log.info("sending updated screen size to clients: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        for ss in self._server_sources.values():
            ss.updated_desktop_size(root_w, root_h, max_w, max_h)

    def get_max_screen_size(self):
        max_w, max_h = gtk.gdk.get_default_root_window().get_size()
        sizes = get_screen_sizes()
        if self.randr and len(sizes)>=1:
            for w,h in sizes:
                max_w = max(max_w, w)
                max_h = max(max_h, h)
        return max_w, max_h

    def _get_desktop_size_capability(self, server_source, root_w, root_h):
        client_size = server_source.desktop_size
        log("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
        if not client_size:
            """ client did not specify size, just return what we have """
            return    root_w, root_h
        client_w, client_h = client_size
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return    w, h

    def set_best_screen_size(self):
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        max_w, max_h = 0, 0
        sizes = []
        for ss in self._server_sources.values():
            client_size = ss.desktop_size
            if not client_size:
                continue
            sizes.append(client_size)
            w, h = client_size
            max_w = max(max_w, w)
            max_h = max(max_h, h)
        log.info("max client resolution is %sx%s (from %s), current server resolution is %sx%s", max_w, max_h, sizes, root_w, root_h)
        if max_w>0 and max_h>0:
            return self.set_screen_size(max_w, max_h)
        return  root_w, root_h

    def set_screen_size(self, desired_w, desired_h):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        if desired_w==root_w and desired_h==root_h:
            return    root_w,root_h    #unlikely: perfect match already!
        #try to find the best screen size to resize to:
        new_size = None
        for w,h in get_screen_sizes():
            if w<desired_w or h<desired_h:
                continue            #size is too small for client
            if new_size:
                ew,eh = new_size
                if ew*eh<w*h:
                    continue        #we found a better (smaller) candidate already
            new_size = w,h
        log("best resolution for client(%sx%s) is: %s", desired_w, desired_h, new_size)
        if not new_size:
            return  root_w, root_h
        w, h = new_size
        if w==root_w and h==root_h:
            log.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
            return  root_w, root_h
        try:
            set_screen_size(w, h)
            root_w, root_h = get_screen_size()
            if root_w!=w or root_h!=h:
                log.error("odd, failed to set the new resolution, "
                          "tried to set it to %sx%s and ended up with %sx%s", w, h, root_w, root_h)
            else:
                log.info("new resolution matching %sx%s : screen now set to %sx%s", desired_w, desired_h, root_w, root_h)
        except Exception, e:
            log.error("ouch, failed to set new resolution: %s", e, exc_info=True)
        return  root_w, root_h

    def _process_desktop_size(self, proto, packet):
        width, height = packet[1:3]
        log("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)
        if len(packet)>=4:
            screen_sizes = packet[3]
            log("client screen sizes: %s", screen_sizes)

    def _process_encoding(self, proto, packet):
        encoding = packet[1]
        if len(packet)>=3:
            #client specified which windows this is for:
            in_wids = packet[2]
            wids = []
            wid_windows = {}
            for wid in in_wids:
                if wid not in self._id_to_window:
                    continue
                wids.append(wid)
                wid_windows[wid] = self._id_to_window.get(wid)
        else:
            #apply to all windows:
            wids = None
            wid_windows = self._id_to_window
        self._server_sources.get(proto).set_encoding(encoding, wids)
        self.refresh_windows(proto, wid_windows)

    def send_disconnect(self, proto, reason):
        if proto._closed:
            return
        def force_disconnect(*args):
            proto.close()
        proto._add_packet_to_queue(["disconnect", reason])
        gobject.timeout_add(1000, force_disconnect)

    def _send_password_challenge(self, proto, server_cipher):
        proto.salt = uuid.uuid4().hex
        log.info("Password required, sending challenge")
        packet = ("challenge", proto.salt, server_cipher)
        proto._add_packet_to_queue(packet)

    def _verify_password(self, proto, client_hash, password):
        salt = proto.salt
        proto.salt = None
        if not salt:
            self.send_disconnect(proto, "illegal challenge response received - salt cleared or unset")
            return
        password_hash = hmac.HMAC(password, salt)
        if client_hash != password_hash.hexdigest():
            def login_failed(*args):
                log.error("Password supplied does not match! dropping the connection.")
                self.send_disconnect(proto, "invalid password")
            gobject.timeout_add(1000, login_failed)
            return False
        log.info("Password matches!")
        sys.stdout.flush()
        return True

    def get_password(self):
        if not self.password_file or not os.path.exists(self.password_file):
            return  None
        try:
            passwordFile = open(self.password_file, "rU")
            password  = passwordFile.read()
            passwordFile.close()
            while password.endswith("\n") or password.endswith("\r"):
                password = password[:-1]
            return password
        except IOError, e:
            log.error("cannot open password file %s: %s", self.password_file, e)
            return  None

    def get_info(self, proto):
        info = {}
        add_version_info(info)
        add_gtk_version_info(info, gtk)
        info["root_window_size"] = gtk.gdk.get_default_root_window().get_size()
        info["max_desktop_size"] = self.get_max_screen_size()
        info["session_name"] = self.session_name or ""
        info["password_file"] = self.password_file or ""
        info["randr"] = self.randr
        info["clipboard"] = self._clipboard_helper is not None
        info["cursors"] = self.cursors
        info["bell"] = self.bell
        info["notifications"] = self.notifications_forwarder is not None
        info["pulseaudio"] = self.pulseaudio
        info["start_time"] = int(self.start_time)
        info["encodings"] = ",".join(ENCODINGS)
        info["platform"] = sys.platform
        info["windows"] = len(self._id_to_window)
        info["clients"] = len([p for p in self._server_sources.keys() if p!=proto])
        info["potential_clients"] = len([p for p in self._potential_protocols if ((p is not proto) and (p not in self._server_sources.keys()))])
        info["keyboard_sync"] = self.keyboard_sync
        info["key_repeat_delay"] = self.key_repeat_delay
        info["key_repeat_interval"] = self.key_repeat_interval
        #find the source to report on:
        n = len(self._server_sources)
        if n==1:
            self._server_sources.values()[0].add_stats(info, self._id_to_window.keys())
        elif n>1:
            i = 0
            for ss in self._server_sources.values():
                ss.add_stats(info, self._id_to_window.keys(), suffix="{%s}" % i)
                i += 1
        #threads:
        info_threads = proto.get_threads()
        info["threads"] = threading.active_count() - len(info_threads)
        info["info_threads"] = len(info_threads)
        i = 0
        #threads used by the "info" client:
        for t in info_threads:
            info["info_thread[%s]" % i] = t.name
            i += 1
        i = 0
        #all non-info threads:
        for t in threading.enumerate():
            if t not in info_threads:
                info["thread[%s]" % i] = t.name
                i += 1
        return info

    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        log("process_hello: capabilities=%s", capabilities)
        if capabilities.get("version_request", False):
            response = {"version" : xpra.__version__}
            packet = ["hello", response]
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "version sent")
            return

        screenshot_req = capabilities.get("screenshot_request", False)
        info_req = capabilities.get("info_request", False)
        if not screenshot_req and not info_req:
            log.info("Handshake complete; enabling connection")

        remote_version = capabilities.get("version")
        if not is_compatible_with(remote_version):
            proto.close()
            return

        #client may have requested encryption:
        cipher = capabilities.get("cipher")
        cipher_iv = capabilities.get("cipher.iv")
        key_salt = capabilities.get("cipher.key_salt")
        iterations = capabilities.get("cipher.key_stretch_iterations")
        password = None
        if self.password_file or (cipher and cipher_iv):
            #we will need the password:
            password = self.get_password()
            if not password:
                self.send_disconnect(proto, "password not found")
                return
        server_cipher = None
        if cipher and cipher_iv:
            if cipher not in ENCRYPTION_CIPHERS:
                log.warn("unsupported cipher: %s", cipher)
                self.send_disconnect(proto, "unsupported cipher")
                return
            proto.set_cipher_out(cipher, cipher_iv, password, key_salt, iterations)
            #use the same cipher as used by the client:
            iv = uuid.uuid4().hex[:16]
            key_salt = uuid.uuid4().hex
            iterations = 1000
            proto.set_cipher_in(cipher, iv, password, key_salt, iterations)
            server_cipher = {
                             "cipher"           : cipher,
                             "cipher.iv"        : iv,
                             "cipher.key_salt"  : key_salt,
                             "cipher.key_stretch_iterations" : iterations
                             }
            log("server cipher=%s", server_cipher)

        if self.password_file:
            log("password auth required")
            #send challenge if this is not a response:
            client_hash = capabilities.get("challenge_response")
            if not client_hash or not proto.salt:
                self._send_password_challenge(proto, server_cipher or "")
                return
            if not self._verify_password(proto, client_hash, password):
                return

        if screenshot_req:
            #this is a screenshot request, handle it and disconnect
            packet = self.make_screenshot_packet()
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "screenshot sent")
            return
        if info_req:
            packet = ["hello", self.get_info(proto)]
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "info sent")
            return

        # Things are okay, we accept this connection, and may disconnect previous one(s)
        share_count = 0
        for p,ss in self._server_sources.items():
            #check existing sessions are willing to share:
            if not self.sharing:
                self.disconnect(p, "new valid connection received, this session does not allow sharing")
            elif not capabilities.get("share", False):
                self.disconnect(p, "new valid connection received, the new client does not wish to share")
            elif not ss.share:
                self.disconnect(p, "new valid connection received, this client had not enabled sharing ")
            else:
                share_count += 1
        if share_count>0:
            log.info("sharing with %s other session(s)", share_count)
        self.dpi = capabilities.get("dpi", self.default_dpi)
        if self.dpi>0:
            #some non-posix clients never send us 'resource-manager' settings
            #so just use a fake one to ensure the dpi gets applied:
            self.update_server_settings({'resource-manager' : ""})
        if capabilities.get("rencode") and has_rencode:
            proto.enable_rencode()
        #max packet size from client (the biggest we can get are clipboard packets)
        proto.max_packet_size = 1024*1024  #1MB
        proto.chunked_compression = capabilities.get("chunked_compression", False)
        ss = ServerSource(proto, self._get_transient_for, self.supports_mmap, self.default_quality)
        ss.parse_hello(capabilities)
        self._server_sources[proto] = ss
        if self.randr:
            root_w, root_h = self.set_best_screen_size()
        else:
            root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        #take the clipboard if no-one else has yet:
        if ss.clipboard_enabled and (self._clipboard_client is None or self._clipboard_client.closed):
            self._clipboard_client = ss
        #so only activate this feature afterwards:
        self.keyboard_sync = bool(capabilities.get("keyboard_sync", True))
        key_repeat = capabilities.get("key_repeat", None)
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat
            if self.key_repeat_delay>0 and self.key_repeat_interval>0:
                set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                log.info("setting key repeat rate from client: %sms delay / %sms interval", self.key_repeat_delay, self.key_repeat_interval)
        else:
            #dont do any jitter compensation:
            self.key_repeat_delay = -1
            self.key_repeat_interval = -1
            #but do set a default repeat rate:
            set_key_repeat_rate(500, 30)
        #parse keyboard related options:
        self.xkbmap_layout = capabilities.get("xkbmap_layout")
        self.xkbmap_variant = capabilities.get("xkbmap_variant")
        #always clear modifiers before setting a new keymap
        self.set_keymap(ss)
        ss.make_keymask_match(capabilities.get("modifiers", []))

        #send_hello will take care of sending the current and max screen resolutions
        self.send_hello(ss, root_w, root_h, key_repeat, server_cipher)

        #old clients used a network unsafe binary format..
        set_xsettings_format(use_tuple=capabilities.get("xsettings-tuple", False))
        # now we can set the modifiers to match the client
        self.send_windows_and_cursors(ss)

    def send_windows_and_cursors(self, ss):
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            if window.is_OR():
                self._send_new_or_window_packet(window)
            else:
                self._desktop_manager.hide_window(window)
                #code more or less duplicated from send_new_window_packet:
                #so we can send it just to the new client:
                x, y, w, h = self._desktop_manager.window_geometry(window)
                ss.new_window("new-window", wid, window, x, y, w, h, self._all_metadata, self.client_properties.get(ss.uuid))
        ss.send_cursor(self.cursor_data)

    def send_hello(self, server_source, root_w, root_h, key_repeat, server_cipher):
        capabilities = {}
        if server_cipher:
            capabilities.update(server_cipher)
        capabilities["version"] = xpra.__version__
        capabilities["actual_desktop_size"] = root_w, root_h
        capabilities["root_window_size"] = root_w, root_h
        capabilities["desktop_size"] = self._get_desktop_size_capability(server_source, root_w, root_h)
        capabilities["max_desktop_size"] = self.get_max_screen_size()
        capabilities["display"] = gtk.gdk.display_get_default().get_name()
        capabilities["platform"] = sys.platform
        capabilities["encodings"] = ENCODINGS
        capabilities["resize_screen"] = self.randr
        if key_repeat:
            capabilities["key_repeat"] = key_repeat
            capabilities["key_repeat_modifiers"] = True
        if self.session_name:
            capabilities["session_name"] = self.session_name
        capabilities["start_time"] = int(self.start_time)
        capabilities["toggle_cursors_bell_notify"] = True
        capabilities["toggle_keyboard_sync"] = True
        capabilities["notifications"] = self.notifications_forwarder is not None
        capabilities["clipboard"] = self._clipboard_client == server_source
        capabilities["bell"] = self.bell
        capabilities["cursors"] = self.cursors
        capabilities["raw_packets"] = True
        capabilities["chunked_compression"] = True
        capabilities["rencode"] = has_rencode
        capabilities["window_configure"] = True
        capabilities["xsettings-tuple"] = True
        capabilities["change-quality"] = True
        capabilities["client_window_properties"] = True
        add_version_info(capabilities)
        add_gtk_version_info(capabilities, gtk)
        server_source.hello(capabilities)

    def send_ping(self):
        for ss in self._server_sources.values():
            ss.ping()

    def _process_ping_echo(self, proto, packet):
        self._server_sources.get(proto).process_ping_echo(packet)

    def _process_ping(self, proto, packet):
        time_to_echo = packet[1]
        self._server_sources.get(proto).process_ping(time_to_echo)

    def _process_screenshot(self, proto, packet):
        packet = self.make_screenshot_packet()
        self._server_sources.get(proto).send(*packet)

    def make_screenshot_packet(self):
        log("grabbing screenshot")
        regions = []
        for wid in reversed(sorted(self._id_to_window.keys())):
            window = self._id_to_window[wid]
            pixmap = window.get_property("client-contents")
            if pixmap is None:
                continue
            (x, y, _, _) = self._desktop_manager.window_geometry(window)
            w, h = pixmap.get_size()
            item = (wid, x, y, w, h, pixmap)
            if self._has_focus==wid:
                #window with focus first (drawn last)
                regions.insert(0, item)
            else:
                regions.append(item)
        log("screenshot: found regions=%s", regions)
        if len(regions)==0:
            packet = ["screenshot", 0, 0, "png", -1, ""]
        else:
            minx = min([x for (_,x,_,_,_,_) in regions])
            miny = min([y for (_,_,y,_,_,_) in regions])
            maxx = max([(x+w) for (_,x,_,w,_,_) in regions])
            maxy = max([(y+h) for (_,_,y,_,h,_) in regions])
            width = maxx-minx
            height = maxy-miny
            log("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
            import Image
            image = Image.new("RGBA", (width, height))
            for wid, x, y, w, h, pixmap in reversed(regions):
                _, _, wid, _, _, w, h, _, raw_data, rowstride, _, _ = get_rgb_rawdata(0, 0, wid, pixmap, 0, 0, w, h, "rgb24", -1, None)
                window_image = Image.fromstring("RGB", (w, h), raw_data, "raw", "RGB", rowstride)
                tx = x-minx
                ty = y-miny
                image.paste(window_image, (tx, ty))
            buf = StringIO()
            image.save(buf, "png")
            data = buf.getvalue()
            buf.close()
            packet = ["screenshot", width, height, "png", rowstride, data]
        return packet

    def _process_set_notify(self, proto, packet):
        assert self.notifications_forwarder is not None, "cannot toggle notifications: the feature is disabled"
        self._server_sources.get(proto).send_notifications = bool(packet[1])

    def _process_set_cursors(self, proto, packet):
        assert self.cursors, "cannot toggle send_cursors: the feature is disabled"
        self._server_sources.get(proto).send_cursors = bool(packet[1])

    def _process_set_bell(self, proto, packet):
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        self._server_sources.get(proto).send_bell = bool(packet[1])

    def _process_set_deflate(self, proto, packet):
        level = packet[1]
        log("client has requested compression level=%s", level)
        proto.set_compression_level(level)
        #echo it back to the client:
        self._server_sources.get(proto).set_deflate(level)

    def disconnect(self, protocol, reason):
        ss = None
        if protocol:
            log.info("Disconnecting existing client %s, reason is: %s", protocol, reason)
            # send message asking client to disconnect (politely):
            protocol.flush_then_close(["disconnect", reason])
            #this ensures that from now on we ignore any incoming packets coming
            #from this connection as these could potentially set some keys pressed, etc
            ss = self._server_sources.get(protocol)
            if ss:
                ss.close()
                del self._server_sources[protocol]
        #so it is now safe to clear them:
        #(this may fail during shutdown - which is ok)
        try:
            self._clear_keys_pressed()
        except:
            pass
        self._focus(ss, 0, [])
        log.info("Connection lost")


    def _process_disconnect(self, proto, packet):
        self.disconnect(proto, "on client request")

    def _process_clipboard_enabled_status(self, proto, packet):
        clipboard_enabled = packet[1]
        if self._clipboard_helper:
            assert self._clipboard_client==self._server_sources.get(proto), \
                    "the request to change the clipboard enabled status does not come from the clipboard owner!"
            self._clipboard_client.clipboard_enabled = clipboard_enabled
            log("toggled clipboard to %s", self.clipboard_enabled)
        else:
            log.warn("client toggled clipboard-enabled but we do not support clipboard at all! ignoring it")

    def _process_keyboard_sync_enabled_status(self, proto, packet):
        self.keyboard_sync = bool(packet[1])
        log("toggled keyboard-sync to %s", self.keyboard_sync)

    def _process_server_settings(self, proto, packet):
        self.update_server_settings(packet[1])

    def update_server_settings(self, settings):
        old_settings = dict(self._settings)
        log("server_settings: old=%s, updating with=%s", old_settings, settings)
        self._settings.update(settings)
        root = gtk.gdk.get_default_root_window()
        for k, v in settings.items():
            #cook the "resource-manager" value to add the DPI:
            if k == "resource-manager" and self.dpi>0:
                value = v.decode("utf-8")
                #parse the resources into a dict:
                values={}
                options = value.split("\n")
                for option in options:
                    if not option:
                        continue
                    parts = option.split(":\t")
                    if len(parts)!=2:
                        continue
                    values[parts[0]] = parts[1]
                values["Xft.dpi"] = self.dpi
                log("server_settings: resource-manager values=%s", values)
                #convert the dict back into a resource string:
                value = ''
                for vk, vv in values.items():
                    value += "%s:\t%s\n" % (vk, vv)
                value += '\n'
                #record the actual value used
                self._settings["resource-manager"] = value
                v = value.encode("utf-8")

            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    log("server_settings: setting %s to %s", p, v)
                    prop_set(root, p, "latin1", v.decode("utf-8"))
                if k == "xsettings-blob":
                    self._xsettings_manager = XSettingsManager(v)
                elif k == "resource-manager":
                    root_set("RESOURCE_MANAGER")
                elif self.pulseaudio:
                    if k == "pulse-cookie":
                        root_set("PULSE_COOKIE")
                    elif k == "pulse-id":
                        root_set("PULSE_ID")
                    elif k == "pulse-server":
                        root_set("PULSE_SERVER")

    def _process_map_window(self, proto, packet):
        wid, x, y, width, height = packet[1:6]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        assert not window.is_OR()
        self._desktop_manager.configure_window(window, x, y, width, height)
        self._desktop_manager.show_window(window)
        self._damage(window, 0, 0, width, height)
        if len(packet)>=7:
            self._set_client_properties(proto, packet[6])

    def _set_client_properties(self, proto, new_client_properties):
        ss = self._server_sources.get(proto)
        client_properties = self.client_properties.setdefault(ss.uuid, {})
        log("set_client_properties updating %s with %s", client_properties, new_client_properties)
        client_properties.update(new_client_properties)

    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        assert not window.is_OR()
        self._cancel_damage(wid, window)
        self._desktop_manager.hide_window(window)

    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        if window.is_tray():
            assert self._tray
            self._tray.move_resize(window, x, y, w, h)
            return
        assert not window.is_OR()
        owx, owy, oww, owh = self._desktop_manager.window_geometry(window)
        log("_process_configure_window(%s) old window geometry: %s", packet[1:], (owx, owy, oww, owh))
        self._desktop_manager.configure_window(window, x, y, w, h)
        if self._desktop_manager.visible(window) and (oww!=w or owh!=h):
            self._damage(window, 0, 0, w, h)
        if len(packet)>=7:
            self._set_client_properties(proto, packet[6])

    def _process_move_window(self, proto, packet):
        wid, x, y = packet[1:4]
        window = self._id_to_window.get(wid)
        log("_process_move_window(%s)", packet[1:])
        if not window:
            log("cannot move window %s: already removed!", wid)
            return
        assert not window.is_OR()
        _, _, w, h = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_resize_window(self, proto, packet):
        wid, w, h = packet[1:4]
        window = self._id_to_window.get(wid)
        log("_process_resize_window(%s)", packet[1:])
        if not window:
            log("cannot resize window %s: already removed!", wid)
            return
        assert not window.is_OR()
        self._cancel_damage(wid, window)
        x, y, _, _ = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)
        _, _, ww, wh = self._desktop_manager.window_geometry(window)
        visible = self._desktop_manager.visible(window)
        log("resize_window to %sx%s, desktop manager set it to %sx%s, visible=%s", w, h, ww, wh, visible)
        if visible:
            self._damage(window, 0, 0, w, h)

    def _process_focus(self, proto, packet):
        wid = packet[1]
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        ss = self._server_sources.get(proto)
        self._focus(ss, wid, modifiers)

    def _process_layout(self, proto, packet):
        layout, variant = packet[1:3]
        ss = self._server_sources.get(proto)
        ss.set_layout(layout, variant)
        self.set_keymap(ss)

    def _process_keymap(self, proto, packet):
        props = packet[1]
        ss = self._server_sources.get(proto)
        ss.assign_keymap_options(props)
        modifiers = props.get("modifiers")
        self.set_keymap(ss)
        ss.make_keymask_match(modifiers)

    def _process_key_action(self, proto, packet):
        wid, keyname, pressed, modifiers, keyval, _, client_keycode = packet[1:8]
        ss = self._server_sources.get(proto)
        keycode = ss.get_keycode(client_keycode, keyname, modifiers)
        log("process_key_action(%s) server keycode=%s", packet, keycode)
        #currently unused: (group, is_modifier) = packet[8:10]
        self._focus(ss, wid, None)
        ss.make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        #negative keycodes are used for key events without a real keypress/unpress
        #for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode>0:
            self._handle_key(wid, pressed, keyname, keyval, keycode, modifiers)

    def fake_key(self, keycode, press):
        trap.call(xtest_fake_key, gtk.gdk.display_get_default(), keycode, press)

    def _handle_key(self, wid, pressed, name, keyval, keycode, modifiers):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        log("handle_key(%s,%s,%s,%s,%s,%s)", wid, pressed, name, keyval, keycode, modifiers)
        if pressed and (wid is not None) and (wid not in self._id_to_window):
            log("window %s is gone, ignoring key press", wid)
            return
        if keycode<0:
            log.warn("ignoring invalid keycode=%s", keycode)
            return
        if keycode in self.keys_timedout:
            del self.keys_timedout[keycode]
        def press():
            log("handle keycode pressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                self.keys_pressed[keycode] = name
            self.fake_key(keycode, True)
        def unpress():
            log("handle keycode unpressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                del self.keys_pressed[keycode]
            self.fake_key(keycode, False)
        if pressed:
            if keycode not in self.keys_pressed:
                press()
                if not self.keyboard_sync:
                    #keyboard is not synced: client manages repeat so unpress
                    #it immediately
                    unpress()
            else:
                log("handle keycode %s: key %s was already pressed, ignoring", keycode, name)
        else:
            if keycode in self.keys_pressed:
                unpress()
            else:
                log("handle keycode %s: key %s was already unpressed, ignoring", keycode, name)
        if self.keyboard_sync and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(wid, pressed, name, keyval, keycode, modifiers, self.key_repeat_delay)

    def _key_repeat(self, wid, pressed, keyname, keyval, keycode, modifiers, delay_ms=0):
        """ Schedules/cancels the key repeat timeouts """
        timer = self.keys_repeat_timers.get(keycode, None)
        if timer:
            log("cancelling key repeat timer: %s for %s / %s", timer, keyname, keycode)
            gobject.source_remove(timer)
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            log("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            def _key_repeat_timeout(when):
                now = time.time()
                log("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
                self._handle_key(wid, False, keyname, keyval, keycode, modifiers)
                self.keys_timedout[keycode] = now
            now = time.time()
            self.keys_repeat_timers[keycode] = gobject.timeout_add(delay_ms, _key_repeat_timeout, now)

    def _process_key_repeat(self, proto, packet):
        wid, keyname, keyval, client_keycode, modifiers = packet[1:6]
        ss = self._server_sources.get(proto)
        keycode = ss.get_keycode(client_keycode, keyname, modifiers)
        #key repeat uses modifiers from a pointer event, so ignore mod_pointermissing:
        ss.make_keymask_match(modifiers)
        if not self.keyboard_sync:
            #this check should be redundant: clients should not send key-repeat without
            #having keyboard_sync enabled
            return
        if keycode not in self.keys_pressed:
            #the key is no longer pressed, has it timed out?
            when_timedout = self.keys_timedout.get(keycode, None)
            if when_timedout:
                del self.keys_timedout[keycode]
            now = time.time()
            if when_timedout and (now-when_timedout)<30:
                #not so long ago, just re-press it now:
                log("key %s/%s, had timed out, re-pressing it", keycode, keyname)
                self.keys_pressed[keycode] = keyname
                self.fake_key(keycode, True)
        self._key_repeat(wid, True, keyname, keyval, keycode, modifiers, self.key_repeat_interval)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        ss = self._server_sources.get(proto)
        ss.make_keymask_match(modifiers)
        window = self._id_to_window.get(wid)
        if not window:
            log("_process_mouse_common() invalid window id: %s", wid)
            return
        def raise_and_move():
            self._desktop_manager.raise_window(window)
            self._move_pointer(pointer)
        trap.swallow(raise_and_move)

    def _process_button_action(self, proto, packet):
        wid, button, pressed, pointer, modifiers = packet[1:6]
        self._process_mouse_common(proto, wid, pointer, modifiers)
        display = gtk.gdk.display_get_default()
        try:
            trap.call(xtest_fake_button, display, button, pressed)
        except XError:
            log.warn("Failed to pass on (un)press of mouse button %s"
                     + " (perhaps your Xvfb does not support mousewheels?)",
                     button)

    def _process_pointer_position(self, proto, packet):
        wid, pointer, modifiers = packet[1:4]
        self._process_mouse_common(proto, wid, pointer, modifiers)

    def _process_close_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid, None)
        if window:
            window.request_close()
        else:
            log("cannot close window %s: it is already gone!", wid)

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        for p in self._potential_protocols:
            try:
                self.send_disconnect(p, "server shutdown")
            except:
                pass
        gobject.timeout_add(1000, self.quit, False)

    def _process_damage_sequence(self, proto, packet):
        packet_sequence = packet[1]
        log("received sequence: %s", packet_sequence)
        if len(packet)>=6:
            wid, width, height, decode_time = packet[2:6]
            self._server_sources.get(proto).client_ack_damage(packet_sequence, wid, width, height, decode_time)

    def _process_buffer_refresh(self, proto, packet):
        [wid, _, qual] = packet[1:4]
        if wid==-1:
            wid_windows = self._id_to_window
        elif wid in self._id_to_window:
            wid_windows = {wid : self._id_to_window.get(wid)}
        else:
            return
        opts = {"quality" : qual,
                "override_options" : True}
        log("process_buffer_refresh for windows: %s, with options=%s", wid_windows, opts)
        self.refresh_windows(proto, wid_windows, opts)

    def refresh_windows(self, proto, wid_windows, opts=None):
        for wid, window in wid_windows.items():
            if window is None:
                continue
            if not window.is_OR():
                if not self._desktop_manager._models[window].shown:
                    log("window is no longer shown, ignoring buffer refresh which would fail")
                    continue
            self._server_sources.get(proto).refresh(wid, window, opts)

    def _process_quality(self, proto, packet):
        quality = packet[1]
        log("Setting quality to ", quality)
        self._server_sources.get(proto).set_quality(quality)
        self.refresh_windows(proto, self._id_to_window)

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        if self._clipboard_client and self._clipboard_client.protocol==proto:
            self._clipboard_client = None
        source = self._server_sources.get(proto)
        if source:
            del self._server_sources[proto]
            source.close()
            log.info("xpra client disconnected.")
        if len(self._server_sources)==0:
            self._clear_keys_pressed()
            self._focus(source, 0, [])
        sys.stdout.flush()

    def _process_gibberish(self, proto, packet):
        data = packet[1]
        log.info("Received uninterpretable nonsense: %s", repr(data))

    _default_packet_handlers = {
        "hello": _process_hello,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        Protocol.GIBBERISH: _process_gibberish,
        }
    _authenticated_packet_handlers = {
        "set-clipboard-enabled": _process_clipboard_enabled_status,
        "set-keyboard-sync-enabled": _process_keyboard_sync_enabled_status,
        "damage-sequence": _process_damage_sequence,
        "ping": _process_ping,
        "ping_echo": _process_ping_echo,
        "set_deflate": _process_set_deflate,
        "set-cursors": _process_set_cursors,
        "set-notify": _process_set_notify,
        "set-bell": _process_set_bell,
                                      }
    _authenticated_ui_packet_handlers = {
        "hello": _process_hello,
        "server-settings": _process_server_settings,
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "configure-window": _process_configure_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "focus": _process_focus,
        "key-action": _process_key_action,
        "key-repeat": _process_key_repeat,
        "layout-changed": _process_layout,
        "keymap-changed": _process_keymap,
        "button-action": _process_button_action,
        "pointer-position": _process_pointer_position,
        "close-window": _process_close_window,
        "shutdown-server": _process_shutdown_server,
        "jpeg-quality": _process_quality,
        "quality": _process_quality,
        "buffer-refresh": _process_buffer_refresh,
        "screenshot": _process_screenshot,
        "desktop_size": _process_desktop_size,
        "encoding": _process_encoding,
        "disconnect": _process_disconnect,
        # "clipboard-*" packets are handled below:
        Protocol.CONNECTION_LOST: _process_connection_lost,
        Protocol.GIBBERISH: _process_gibberish,
        }

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        assert isinstance(packet_type, str) or isinstance(packet_type, unicode), "packet_type %s is not a string: %s..." % (type(packet_type), str(packet_type)[:100])
        if packet_type.startswith("clipboard-"):
            ss = self._server_sources.get(proto)
            assert self._clipboard_client==ss, \
                    "the clipboard packet '%s' does not come from the clipboard owner!" % packet_type
            assert ss.clipboard_enabled, "received a clipboard packet from a source which does not have clipboard enabled!"
            gobject.idle_add(self._clipboard_helper.process_clipboard_packet, packet)
            return
        if proto in self._server_sources:
            handlers = self._authenticated_packet_handlers
            ui_handlers = self._authenticated_ui_packet_handlers
        else:
            handlers = {}
            ui_handlers = self._default_packet_handlers
        handler = handlers.get(packet_type)
        if handler:
            log("process non-ui packet %s", packet_type)
            handler(self, proto, packet)
            return
        handler = ui_handlers.get(packet_type)
        if handler:
            log("will process ui packet %s", packet_type)
            gobject.idle_add(handler, self, proto, packet)
            return
        log.error("unknown or invalid packet type: %s", packet_type)
        if proto not in self._server_sources:
            proto.close()

gobject.type_register(XpraServer)
