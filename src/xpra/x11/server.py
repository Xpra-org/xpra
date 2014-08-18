# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Todo:
#   xsync resize stuff
#   shape?
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk.gdk
import gobject

from xpra.util import AdHocStruct
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.x11.xsettings import XSettingsManager, XSettingsHelper
from xpra.x11.gtk_x11.wm import Wm
from xpra.x11.gtk_x11.tray import get_tray_window, SystemTray
from xpra.x11.gtk_x11.prop import prop_set
from xpra.x11.gtk_x11.gdk_bindings import (
                               add_event_receiver,          #@UnresolvedImport
                               get_children,                #@UnresolvedImport
                               init_x11_filter,             #@UnresolvedImport
                               cleanup_x11_filter,          #@UnresolvedImport
                               cleanup_all_event_receivers  #@UnresolvedImport
                               )
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings #@UnresolvedImport
X11Keyboard = X11KeyboardBindings()
from xpra.x11.gtk_x11.window import OverrideRedirectWindowModel, SystemTrayWindowModel, Unmanageable
from xpra.gtk_common.error import trap

from xpra.log import Logger
log = Logger("server")
focuslog = Logger("server", "focus")
grablog = Logger("server", "grab")
windowlog = Logger("server", "window")
cursorlog = Logger("server", "cursor")
traylog = Logger("server", "tray")
settingslog = Logger("x11", "xsettings")

import xpra
from xpra.util import nonl
from xpra.os_util import StringIOClass
from xpra.x11.x11_server_base import X11ServerBase, mouselog
from xpra.net.compression import Compressed


class DesktopManager(gtk.Widget):
    def __init__(self):
        self._models = {}
        gtk.Widget.__init__(self)
        self.set_property("can-focus", True)
        self.set_flags(gtk.NO_WINDOW)

    def __repr__(self):
        return "DesktopManager(%s)" % len(self._models)

    ## For communicating with the main WM:

    def add_window(self, model, x, y, w, h):
        assert self.flags() & gtk.REALIZED
        s = AdHocStruct()
        s.shown = False
        s.geom = [x, y, w, h]
        s.resize_counter = 0
        self._models[model] = s
        model.connect("unmanaged", self._unmanaged)
        model.connect("ownership-election", self._elect_me)
        def new_geom(window_model, *args):
            log("new_geom(%s,%s)", window_model, args)
        model.connect("notify::geometry", new_geom)
        model.ownership_election()

    def window_geometry(self, model):
        return self._models[model].geom

    def get_resize_counter(self, window, inc=0):
        model = self._models[window]
        v = model.resize_counter+inc
        model.resize_counter = v
        return v

    def show_window(self, model):
        self._models[model].shown = True
        model.ownership_election()
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def is_shown(self, model):
        return self._models[model].shown

    def configure_window(self, win, x, y, w, h, resize_counter=0):
        log("DesktopManager.configure_window(%s, %s, %s, %s, %s, %s)", win, x, y, w, h, resize_counter)
        model = self._models[win]
        if not self.visible(win):
            model.shown = True
            win.set_property("iconic", False)
            win.ownership_election()
        if resize_counter>0 and resize_counter<model.resize_counter:
            log("resize ignored: counter %s vs %s", resize_counter, model.resize_counter)
            return
        new_geom = [x, y, w, h]
        if model.geom!=new_geom:
            model.geom = [x, y, w, h]
            win.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

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

    def window_size(self, model):
        w, h = self._models[model].geom[2:4]
        return w, h

    def window_position(self, model, w, h):
        [x, y, w0, h0] = self._models[model].geom
        if abs(w0-w)>1 or abs(h0-h)>1:
            log.warn("Uh-oh, our size doesn't fit window sizing constraints: "
                     "%sx%s vs %sx%s", w0, h0, w, h)
        return x, y

    def get_transient_for(self, window, window_to_id):
        transient_for = window.get_property("transient-for")
        if transient_for is None:
            return None
        log("found transient_for=%s, xid=%#x", transient_for, transient_for.xid)
        #try to find the model for this window:
        for model in self._models.keys():
            log("testing model %s: %#x", model, model.client_window.xid)
            if model.client_window.xid==transient_for.xid:
                wid = window_to_id.get(model)
                log("found match, window id=%s", wid)
                return wid
        root = gtk.gdk.get_default_root_window()
        if root.xid==transient_for.xid:
            return -1       #-1 is the backwards compatible marker for root...
        log("not found transient_for=%s, xid=%#x", transient_for, transient_for.xid)
        return  None


gobject.type_register(DesktopManager)


class XpraServer(gobject.GObject, X11ServerBase):
    __gsignals__ = {
        "xpra-child-map-event": one_arg_signal,
        "xpra-cursor-event": one_arg_signal,
        }

    def __init__(self):
        gobject.GObject.__init__(self)
        X11ServerBase.__init__(self)

    def init(self, clobber, opts):
        X11ServerBase.init(self, clobber, opts)
        self.xsettings_enabled = opts.xsettings

    def x11_init(self):
        X11ServerBase.x11_init(self)
        assert init_x11_filter() is True

        self._has_grab = 0
        self._has_focus = 0
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

        ### Create the WM object
        self._wm = Wm(self.clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("bell", self._bell_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        #save default xsettings:
        self.default_xsettings = XSettingsHelper().get_settings()
        settingslog("default_xsettings=%s", self.default_xsettings)
        self._settings = {}
        self._xsettings_manager = None

        #cursor:
        self.default_cursor_data = None
        self.last_cursor_serial = None
        self.last_cursor_data = None
        self.send_cursor_pending = False
        def get_default_cursor():
            self.default_cursor_data = X11Keyboard.get_cursor_image()
            cursorlog("get_default_cursor=%s", self.default_cursor_data)
        trap.swallow_synced(get_default_cursor)
        self._wm.enableCursors(True)


    def make_hello(self, source):
        capabilities = X11ServerBase.make_hello(self, source)
        if source.wants_features:
            capabilities["window.raise"] = True
            capabilities["window.resize-counter"] = True
            capabilities["pointer.grabs"] = True
        return capabilities


    def do_get_info(self, proto, server_sources, window_ids):
        info = X11ServerBase.do_get_info(self, proto, server_sources, window_ids)
        log("do_get_info: adding cursor=%s", self.last_cursor_data)
        #copy to prevent race:
        cd = self.last_cursor_data
        if cd is None:
            info["cursor"] = "None"
        else:
            info["cursor.is_default"] = bool(self.default_cursor_data and len(self.default_cursor_data)>=8 and len(cd)>=8 and cd[7]==cd[7])
            #all but pixels:
            i = 0
            for x in ("x", "y", "width", "height", "xhot", "yhot", "serial", None, "name"):
                if x:
                    v = cd[i] or ""
                    info["cursor." + x] = v
                i += 1
        return info

    def get_ui_info(self, proto, wids, *args):
        info = X11ServerBase.get_ui_info(self, proto, wids, *args)
        #now cursor size info:
        display = gtk.gdk.display_get_default()
        for prop, size in {"default" : display.get_default_cursor_size(),
                           "max"     : display.get_maximal_cursor_size()}.items():
            if size is None:
                continue
            info["cursor.%s_size" % prop] = size
        return info


    def get_window_info(self, window):
        info = X11ServerBase.get_window_info(self, window)
        info["focused"] = self._has_focus and self._window_to_id.get(window, -1)==self._has_focus
        info["grabbed"] = self._has_grab and self._window_to_id.get(window, -1)==self._has_grab
        return info


    def set_workarea(self, workarea):
        self._wm.set_workarea(workarea.x, workarea.y, workarea.width, workarea.height)

    def set_desktop_geometry(self, width, height):
        self._wm.set_desktop_geometry(width, height)

    def set_dpi(self, xdpi, ydpi):
        self._wm.set_dpi(xdpi, ydpi)


    def get_transient_for(self, window):
        return self._desktop_manager.get_transient_for(window, self._window_to_id)

    def is_shown(self, window):
        return self._desktop_manager.is_shown(window)

    def cleanup(self, *args):
        if self._tray:
            self._tray.cleanup()
            self._tray = None
        X11ServerBase.cleanup(self)
        cleanup_x11_filter()
        cleanup_all_event_receivers()
        if self._wm:
            self._wm.cleanup()
            self._wm = None
        if self._has_grab:
            #normally we set this value when we receive the NotifyUngrab
            #but at this point in the cleanup, we probably won't, so force set it:
            self._has_grab = 0
            self.X11_ungrab()


    def cleanup_source(self, protocol):
        had_client = len(self._server_sources)>0
        X11ServerBase.cleanup_source(self, protocol)
        has_client = len(self._server_sources)>0
        if had_client and not has_client:
            #last client is gone:
            self.reset_settings()
            if self._has_grab:
                self.X11_ungrab()


    def load_existing_windows(self, system_tray):
        # Tray handler:
        self._tray = None
        if system_tray:
            try:
                self._tray = SystemTray()
            except Exception, e:
                log.error("cannot setup tray forwarding: %s", e, exc_info=True)

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        root = gtk.gdk.get_default_root_window()
        for window in get_children(root):
            if X11Window.is_override_redirect(window.xid) and X11Window.is_mapped(window.xid):
                self._add_new_or_window(window)

    def send_windows_and_cursors(self, ss, sharing=False):
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        windowlog("send_windows_and_cursors(%s, %s) will send: %s", ss, sharing, self._id_to_window)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            if not window.is_managed():
                #we keep references to windows that aren't meant to be displayed..
                continue
            #most of the code here is duplicated from the send functions
            #so we can send just to the new client and request damage
            #just for the new client too:
            if window.is_tray():
                #code more or less duplicated from _send_new_tray_window_packet:
                w, h = window.get_property("geometry")[2:4]
                if ss.system_tray:
                    ss.new_tray(wid, window, w, h)
                    ss.damage(wid, window, 0, 0, w, h)
                elif not sharing:
                    #park it outside the visible area
                    window.move_resize(-200, -200, w, h)
            elif window.is_OR():
                #code more or less duplicated from _send_new_or_window_packet:
                x, y, w, h = window.get_property("geometry")
                wprops = self.client_properties.get("%s|%s" % (wid, ss.uuid))
                ss.new_window("new-override-redirect", wid, window, x, y, w, h, wprops)
                ss.damage(wid, window, 0, 0, w, h)
            else:
                #code more or less duplicated from send_new_window_packet:
                if not sharing:
                    self._desktop_manager.hide_window(window)
                x, y, w, h = self._desktop_manager.window_geometry(window)
                wprops = self.client_properties.get("%s|%s" % (wid, ss.uuid))
                ss.new_window("new-window", wid, window, x, y, w, h, wprops)
        #cursors: get sizes and send:
        display = gtk.gdk.display_get_default()
        self.cursor_sizes = display.get_default_cursor_size(), display.get_maximal_cursor_size()
        cursorlog("cursor_sizes=%s", self.cursor_sizes)
        ss.send_cursor(self.get_cursor_data)


    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_xpra_child_map_event(self, event):
        windowlog("do_xpra_child_map_event(%s)", event)
        if event.override_redirect:
            self._add_new_or_window(event.window)

    def _add_new_window_common(self, window):
        windowlog("adding window %s", window)
        wid = X11ServerBase._add_new_window_common(self, window)
        window.managed_connect("client-contents-changed", self._contents_changed)
        window.managed_connect("unmanaged", self._lost_window)
        window.managed_connect("raised", self._raised_window)
        window.managed_connect("grab", self._window_grab)
        window.managed_connect("ungrab", self._window_ungrab)
        return wid

    def _add_new_window(self, window):
        self._add_new_window_common(window)
        for prop in self.get_dynamic_property_names():
            window.connect("notify::%s" % prop, self._update_metadata)
        _, _, w, h, _ = window.get_property("client-window").get_geometry()
        x, y, _, _, _ = window.corral_window.get_geometry()
        windowlog("Discovered new ordinary window: %s (geometry=%s)", window, (x, y, w, h))
        self._desktop_manager.add_window(window, x, y, w, h)
        window.connect("notify::geometry", self._window_resized_signaled)
        self._send_new_window_packet(window)

    def _window_resized_signaled(self, window, *args):
        nw, nh = window.get_property("actual-size")
        x, y = window.get_position()
        geom = self._desktop_manager.window_geometry(window)
        windowlog("XpraServer._window_resized_signaled(%s,%s) position=%sx%s, actual-size=%sx%s, current geometry=%s", window, args, x, y, nw, nh, geom)
        if geom[:4]==[x, y, nw, nh]:
            #unchanged
            return
        geom[:4] = [x, y, nw, nh]
        resize_counter = self._desktop_manager.get_resize_counter(window, 1)
        for ss in self._server_sources.values():
            ss.move_resize_window(self._window_to_id[window], window, x, y, nw, nh, resize_counter)

    def _add_new_or_window(self, raw_window):
        xid = raw_window.xid
        if raw_window.get_window_type()==gtk.gdk.WINDOW_TEMP:
            #ignoring one of gtk's temporary windows
            #all the windows we manage should be gtk.gdk.WINDOW_FOREIGN
            windowlog("ignoring TEMP window %#x", xid)
            return
        WINDOW_MODEL_KEY = "_xpra_window_model_"
        wid = raw_window.get_data(WINDOW_MODEL_KEY)
        window = self._id_to_window.get(wid)
        if window:
            if window.is_managed():
                windowlog("found existing window model %s for %#x, will refresh it", type(window), xid)
                geometry = window.get_property("geometry")
                _, _, w, h = geometry
                self._damage(window, 0, 0, w, h, options={"min_delay" : 50})
                return
            windowlog("found existing model %s (but no longer managed!) for %#x", type(window), xid)
            #we could try to re-use the existing model and window ID,
            #but for now it is just easier to create a new one:
            self._lost_window(window)
        tray_window = get_tray_window(raw_window)
        windowlog("Discovered new override-redirect window: %#x (tray=%s)", xid, tray_window)
        try:
            if tray_window is not None:
                assert self._tray
                window = SystemTrayWindowModel(raw_window)
                wid = self._add_new_window_common(window)
                raw_window.set_data(WINDOW_MODEL_KEY, wid)
                window.call_setup()
                self._send_new_tray_window_packet(wid, window)
            else:
                window = OverrideRedirectWindowModel(raw_window)
                wid = self._add_new_window_common(window)
                raw_window.set_data(WINDOW_MODEL_KEY, wid)
                window.call_setup()
                window.connect("notify::geometry", self._or_window_geometry_changed)
                self._send_new_or_window_packet(window)
        except Unmanageable, e:
            if window:
                windowlog("window %s is not manageable: %s", window, e)
                #if window is set, we failed after instantiating it,
                #so we need to fail it manually:
                window.setup_failed(e)
                if window in self._window_to_id:
                    self._lost_window(window, False)
            else:
                windowlog.warn("cannot add window %#x: %s", xid, e)
            #from now on, we return to the gtk main loop,
            #so we *should* get a signal when the window goes away

    def _or_window_geometry_changed(self, window, pspec=None):
        (x, y, w, h) = window.get_property("geometry")
        if w>=32768 or h>=32768:
            self.error("not sending new invalid window dimensions: %ix%i !", w, h)
            return
        windowlog("or_window_geometry_changed: %s (window=%s)", window.get_property("geometry"), window)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.or_window_geometry(wid, window, x, y, w, h)


    def do_xpra_cursor_event(self, event):
        if not self.cursors:
            return
        if self.last_cursor_serial==event.cursor_serial:
            cursorlog("ignoring cursor event %s with the same serial number %s", event, self.last_cursor_serial)
            return
        cursorlog("cursor_event: %s", event)
        self.last_cursor_serial = event.cursor_serial
        for ss in self._server_sources.values():
            ss.send_cursor(self.get_cursor_data)
        return False

    def get_cursor_data(self):
        #must be called from the UI thread!
        cursor_data = X11Keyboard.get_cursor_image()
        if cursor_data is None:
            cursorlog("get_cursor_data() failed to get cursor image")
            return None, []
        self.last_cursor_data = cursor_data
        pixels = self.last_cursor_data[7]
        cursorlog("get_cursor_data() cursor=%s", cursor_data[:7]+["%s bytes" % len(pixels)]+cursor_data[8:])
        if self.default_cursor_data is not None and str(pixels)==str(self.default_cursor_data[7]):
            cursorlog("get_cursor_data(): default cursor - clearing it")
            cursor_data = None
        display = gtk.gdk.display_get_default()
        cursor_sizes = display.get_default_cursor_size(), display.get_maximal_cursor_size()
        return (cursor_data, cursor_sizes)


    def _bell_signaled(self, wm, event):
        log("bell signaled on window %s", event.window.xid)
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



    def _focus(self, server_source, wid, modifiers):
        focuslog("focus wid=%s has_focus=%s", wid, self._has_focus)
        if self._has_focus==wid:
            #nothing to do!
            return
        had_focus = self._id_to_window.get(self._has_focus)
        def reset_focus():
            toplevel = None
            if self._wm:
                toplevel = self._wm.get_property("toplevel")
            focuslog("reset_focus() %s / %s had focus (toplevel=%s)", self._has_focus, had_focus, toplevel)
            self._clear_keys_pressed()
            # FIXME: kind of a hack:
            self._has_focus = 0
            #toplevel may be None during cleanup!
            if toplevel:
                toplevel.reset_x_focus()

        if wid == 0:
            #wid==0 means root window
            return reset_focus()
        window = self._id_to_window.get(wid)
        if not window:
            #not found! (go back to root)
            return reset_focus()
        if window.is_OR():
            focuslog.warn("focus(..) cannot focus OR window: %s", window)
            return
        focuslog("focus: giving focus to %s", window)
        #using idle_add seems to prevent some focus races:
        def give_focus():
            if not window.is_managed():
                return
            window.raise_window()
            window.give_client_focus()
        gobject.idle_add(give_focus)
        if server_source and modifiers is not None:
            focuslog("focus: will set modified mask to %s", modifiers)
            server_source.make_keymask_match(modifiers)
        self._has_focus = wid

    def get_focus(self):
        return self._has_focus


    def _send_new_window_packet(self, window):
        geometry = self._desktop_manager.window_geometry(window)
        self._do_send_new_window_packet("new-window", window, geometry)

    def _send_new_or_window_packet(self, window, options=None):
        geometry = window.get_property("geometry")
        self._do_send_new_window_packet("new-override-redirect", window, geometry)
        (_, _, w, h) = geometry
        self._damage(window, 0, 0, w, h, options=options)

    def _send_new_tray_window_packet(self, wid, window, options=None):
        (_, _, w, h) = window.get_property("geometry")
        for ss in self._server_sources.values():
            ss.new_tray(wid, window, w, h)
        self._damage(window, 0, 0, w, h, options=options)


    def _update_metadata(self, window, pspec):
        windowlog("updating metadata on %s: %s", window, pspec)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.window_metadata(wid, window, pspec.name)

    def _lost_window(self, window, wm_exiting=False):
        wid = self._window_to_id[window]
        windowlog("lost_window: %s - %s", wid, window)
        for ss in self._server_sources.values():
            ss.lost_window(wid, window)
        del self._window_to_id[window]
        del self._id_to_window[wid]
        for ss in self._server_sources.values():
            ss.remove_window(wid, window)

    def _contents_changed(self, window, event):
        if window.is_OR() or self._desktop_manager.visible(window):
            self._damage(window, event.x, event.y, event.width, event.height)


    def _window_grab(self, window, event):
        grab_id = self._window_to_id.get(window, -1)
        grablog("window_grab(%s, %s) has_grab=%s, has focus=%s, grab window=%s", window, event, self._has_grab, self._has_focus, grab_id)
        if grab_id<0 or self._has_grab==grab_id:
            return
        self._has_grab = grab_id
        for ss in self._server_sources.values():
            ss.pointer_grab(self._has_grab)

    def _window_ungrab(self, window, event):
        grab_id = self._window_to_id.get(window, -1)
        grablog("window_ungrab(%s, %s) has_grab=%s, has focus=%s, grab window=%s", window, event, self._has_grab, self._has_focus, grab_id)
        if not self._has_grab:
            return
        self._has_grab = 0
        for ss in self._server_sources.values():
            ss.pointer_ungrab(grab_id)


    def _raised_window(self, window, event):
        windowlog("raised window: %s (%s)", window, event)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.raise_window(wid, window)

    def _process_map_window(self, proto, packet):
        wid, x, y, width, height = packet[1:6]
        window = self._id_to_window.get(wid)
        if not window:
            windowlog("cannot map window %s: already removed!", wid)
            return
        assert not window.is_OR()
        windowlog("client mapped window %s - %s, at: %s", wid, window, (x, y, width, height))
        self._desktop_manager.configure_window(window, x, y, width, height)
        self._desktop_manager.show_window(window)
        if len(packet)>=7:
            self._set_client_properties(proto, wid, window, packet[6])
        self._damage(window, 0, 0, width, height)


    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        assert not window.is_OR()
        windowlog("client unmapped window %s - %s", wid, window)
        for ss in self._server_sources.values():
            ss.unmap_window(wid, window)
        self._desktop_manager.hide_window(window)

    def _process_configure_window(self, proto, packet):
        wid, x, y, w, h = packet[1:6]
        if len(packet)>=7:
            client_properties = packet[6]
        else:
            client_properties = {}
        resize_counter = 0
        if len(packet)>=8:
            resize_counter = packet[7]
        window = self._id_to_window.get(wid)
        windowlog("client configured window %s - %s, at: %s", wid, window, (x, y, w, h))
        if not window:
            windowlog("cannot map window %s: already removed!", wid)
            return
        if window.is_tray():
            assert self._tray
            traylog("tray %s configured to: %s", window, (x, y, w, h))
            self._tray.move_resize(window, x, y, w, h)
        else:
            assert not window.is_OR()
            owx, owy, oww, owh = self._desktop_manager.window_geometry(window)
            windowlog("_process_configure_window(%s) old window geometry: %s", packet[1:], (owx, owy, oww, owh))
            self._desktop_manager.configure_window(window, x, y, w, h, resize_counter)
        if client_properties:
            self._set_client_properties(proto, wid, window, client_properties)
        if window.is_tray() or (self._desktop_manager.visible(window) and (oww!=w or owh!=h)):
            self._damage(window, 0, 0, w, h)


    """ override so we can raise the window under the cursor
        (gtk raise does not change window stacking, just focus) """
    def _move_pointer(self, wid, pos):
        window = self._id_to_window.get(wid)
        if not window:
            mouselog("_move_pointer(%s, %s) invalid window id", wid, pos)
        else:
            mouselog("raising %s", window)
            window.raise_window()
        X11ServerBase._move_pointer(self, wid, pos)


    def _process_close_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid, None)
        windowlog("client closed window %s - %s", wid, window)
        if window:
            window.request_close()
        else:
            windowlog("cannot close window %s: it is already gone!", wid)


    def make_screenshot_packet(self):
        try:
            return self.do_make_screenshot_packet()
        except:
            log.error("make_screenshot_packet()", exc_info=True)
            return None

    def do_make_screenshot_packet(self):
        debug = log.debug
        debug("grabbing screenshot")
        regions = []
        OR_regions = []
        for wid in reversed(sorted(self._id_to_window.keys())):
            window = self._id_to_window.get(wid)
            debug("screenshot: window(%s)=%s", wid, window)
            if window is None:
                continue
            if window.is_tray():
                debug("screenshot: skipping tray window %s", wid)
                continue
            if not window.is_managed():
                debug("screenshot: window %s is not/no longer managed", wid)
                continue
            if window.is_OR():
                x, y = window.get_property("geometry")[:2]
            else:
                x, y = self._desktop_manager.window_geometry(window)[:2]
            debug("screenshot: position(%s)=%s,%s", window, x, y)
            w, h = window.get_dimensions()
            debug("screenshot: size(%s)=%sx%s", window, w, h)
            try:
                img = trap.call_synced(window.get_image, 0, 0, w, h)
            except:
                log.warn("screenshot: window %s could not be captured", wid)
                continue
            if img is None:
                log.warn("screenshot: no pixels for window %s", wid)
                continue
            debug("screenshot: image=%s, size=%s", (img, img.get_size()))
            if img.get_pixel_format() not in ("RGB", "RGBA", "XRGB", "BGRX", "ARGB", "BGRA"):
                log.warn("window pixels for window %s using an unexpected rgb format: %s", wid, img.get_pixel_format())
                continue
            item = (wid, x, y, img)
            if window.is_OR():
                OR_regions.append(item)
            elif self._has_focus==wid:
                #window with focus first (drawn last)
                regions.insert(0, item)
            else:
                regions.append(item)
        all_regions = OR_regions+regions
        if len(all_regions)==0:
            debug("screenshot: no regions found, returning empty 0x0 image!")
            return ["screenshot", 0, 0, "png", -1, ""]
        debug("screenshot: found regions=%s, OR_regions=%s", len(regions), len(OR_regions))
        #in theory, we could run the rest in a non-UI thread since we're done with GTK..
        minx = min([x for (_,x,_,_) in all_regions])
        miny = min([y for (_,_,y,_) in all_regions])
        maxx = max([(x+img.get_width()) for (_,x,_,img) in all_regions])
        maxy = max([(y+img.get_height()) for (_,_,y,img) in all_regions])
        width = maxx-minx
        height = maxy-miny
        debug("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
        from PIL import Image                           #@UnresolvedImport
        screenshot = Image.new("RGBA", (width, height))
        for wid, x, y, img in reversed(all_regions):
            pixel_format = img.get_pixel_format()
            target_format = {
                     "XRGB"   : "RGB",
                     "BGRX"   : "RGB",
                     "BGRA"   : "RGBA"}.get(pixel_format, pixel_format)
            try:
                window_image = Image.frombuffer(target_format, (w, h), img.get_pixels(), "raw", pixel_format, img.get_rowstride())
            except:
                log.warn("failed to parse window pixels in %s format", pixel_format)
                continue
            tx = x-minx
            ty = y-miny
            screenshot.paste(window_image, (tx, ty))
        buf = StringIOClass()
        screenshot.save(buf, "png")
        data = buf.getvalue()
        buf.close()
        packet = ["screenshot", width, height, "png", width*4, Compressed("png", data)]
        debug("screenshot: %sx%s %s", packet[1], packet[2], packet[-1])
        return packet


    def reset_settings(self):
        if not self.xsettings_enabled:
            return
        settingslog("resetting xsettings to: %s", self.default_xsettings)
        self.set_xsettings(self.default_xsettings or (0, ()))

    def set_xsettings(self, v):
        if self._xsettings_manager is None:
            self._xsettings_manager = XSettingsManager()
        self._xsettings_manager.set_settings(v)

    def update_server_settings(self, settings, reset=False):
        if not self.xsettings_enabled:
            settingslog("ignoring xsettings update: %s", settings)
            return
        if reset:
            self.reset_settings()
            self._settings = self.default_xsettings or {}
        old_settings = dict(self._settings)
        settingslog("server_settings: old=%s, updating with=%s", nonl(old_settings), nonl(settings))
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
                values["gnome.Xft/DPI"] = self.dpi*1024
                settingslog("server_settings: resource-manager values=%s", nonl(values))
                #convert the dict back into a resource string:
                value = ''
                for vk, vv in values.items():
                    value += "%s:\t%s\n" % (vk, vv)
                #record the actual value used
                self._settings["resource-manager"] = value
                v = value.encode("utf-8")

            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    settingslog("server_settings: setting %s to %s", nonl(p), nonl(v))
                    prop_set(root, p, "latin1", v.decode("utf-8"))
                if k == "xsettings-blob":
                    self.set_xsettings(v)
                elif k == "resource-manager":
                    root_set("RESOURCE_MANAGER")
                elif self.pulseaudio:
                    if k == "pulse-cookie":
                        root_set("PULSE_COOKIE")
                    elif k == "pulse-id":
                        root_set("PULSE_ID")
                    elif k == "pulse-server":
                        root_set("PULSE_SERVER")


gobject.type_register(XpraServer)
