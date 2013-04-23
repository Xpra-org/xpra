# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Todo:
#   xsync resize stuff
#   shape?
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk.gdk
import gobject

try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport

from wimpiggy.wm import Wm
from wimpiggy.tray import get_tray_window, SystemTray
from wimpiggy.util import (AdHocStruct,
                           one_arg_signal)
from wimpiggy.lowlevel import (is_override_redirect,        #@UnresolvedImport
                               is_mapped,                   #@UnresolvedImport
                               get_xwindow,                 #@UnresolvedImport
                               add_event_receiver,          #@UnresolvedImport
                               get_cursor_image,            #@UnresolvedImport
                               get_children,                #@UnresolvedImport
                               init_x11_filter,             #@UnresolvedImport
                               )
from wimpiggy.window import OverrideRedirectWindowModel, SystemTrayWindowModel, Unmanageable
from wimpiggy.error import trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.x11_server_base import X11ServerBase
from xpra.pixbuf_to_rgb import get_rgb_rawdata
from xpra.protocol import zlib_compress, Compressed


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

    def is_shown(self, model):
        return self._models[model].shown

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

    def get_transient_for(self, window, window_to_id):
        transient_for = window.get_property("transient-for")
        if transient_for is None:
            return None
        log("found transient_for=%s, xid=%s", transient_for, hex(transient_for.xid))
        #try to find the model for this window:
        for model in self._models.keys():
            log("testing model %s: %s", model, hex(model.client_window.xid))
            if model.client_window.xid==transient_for.xid:
                wid = window_to_id.get(model)
                log("found match, window id=%s", wid)
                return wid
        root = gtk.gdk.get_default_root_window()
        if root.xid==transient_for.xid:
            return -1       #-1 is the backwards compatible marker for root...
        log.info("not found transient_for=%s, xid=%s", transient_for, hex(transient_for.xid))
        return  None


gobject.type_register(DesktopManager)


class XpraServer(gobject.GObject, X11ServerBase):
    __gsignals__ = {
        "wimpiggy-child-map-event": one_arg_signal,
        "wimpiggy-cursor-event": one_arg_signal,
        }

    def __init__(self, clobber, sockets, opts):
        gobject.GObject.__init__(self)
        X11ServerBase.__init__(self, clobber, sockets, opts)

    def x11_init(self, clobber):
        X11ServerBase.x11_init(self, clobber)
        init_x11_filter()

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
        self._wm = Wm("Xpra", clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("window-resized", self._window_resized_signaled)
        self._wm.connect("bell", self._bell_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        self.default_cursor_data = None
        self.last_cursor_serial = None
        self.send_cursor_pending = False
        self.cursor_data = None
        def get_default_cursor():
            self.default_cursor_data = get_cursor_image()
            log("get_default_cursor=%s", self.default_cursor_data)
        trap.swallow_synced(get_default_cursor)
        self._wm.enableCursors(True)

    def set_workarea(self, workarea):
        self._wm.set_workarea(workarea.x, workarea.y, workarea.width, workarea.height)

    def get_transient_for(self, window):
        return self._desktop_manager.get_transient_for(window, self._window_to_id)

    def is_shown(self, window):
        return self._desktop_manager.is_shown(window)

    def cleanup(self, *args):
        if self._tray:
            self._tray.cleanup()
            self._tray = None
        X11ServerBase.cleanup(self)

    def load_existing_windows(self, system_tray):
        # Tray handler:
        if system_tray:
            try:
                self._tray = SystemTray()
            except Exception, e:
                log.error("cannot setup tray forwarding: %s", e, exc_info=True)
        else:
            self._tray = None

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        root = gtk.gdk.get_default_root_window()
        for window in get_children(root):
            if is_override_redirect(window) and is_mapped(window):
                self._add_new_or_window(window)

    def send_windows_and_cursors(self, ss):
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        log("send_windows_and_cursors(%s) will send: %s", ss, self._id_to_window)
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
                else:
                    #park it outside the visible area
                    window.move_resize(-200, -200, w, h)
            elif window.is_OR():
                #code more or less duplicated from _send_new_or_window_packet:
                x, y, w, h = window.get_property("geometry")
                wprops = self.client_properties.get("%s|%s" % (wid, ss.uuid))
                ss.new_window("new-override-redirect", wid, window, x, y, w, h, self._OR_metadata, wprops)
                ss.damage(wid, window, 0, 0, w, h)
            else:
                #code more or less duplicated from send_new_window_packet:
                self._desktop_manager.hide_window(window)
                x, y, w, h = self._desktop_manager.window_geometry(window)
                wprops = self.client_properties.get("%s|%s" % (wid, ss.uuid))
                ss.new_window("new-window", wid, window, x, y, w, h, self._all_metadata, wprops)
        ss.send_cursor(self.cursor_data)



    def _window_resized_signaled(self, wm, window):
        nw,nh = window.get_property("actual-size")
        geom = self._desktop_manager.window_geometry(window)
        log("XpraServer._window_resized_signaled(%s,%s) actual-size=%sx%s, current geometry=%s", wm, window, nw, nh, geom)
        geom[2:4] = nw,nh
        for ss in self._server_sources.values():
            ss.resize_window(self._window_to_id[window], window, nw, nh)

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_wimpiggy_child_map_event(self, event):
        log("do_wimpiggy_child_map_event(%s)", event)
        if event.override_redirect:
            self._add_new_or_window(event.window)

    def _add_new_window_common(self, window):
        wid = X11ServerBase._add_new_window_common(self, window)
        window.managed_connect("client-contents-changed", self._contents_changed)
        window.managed_connect("unmanaged", self._lost_window)
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
        xid = get_xwindow(raw_window)
        if raw_window.get_window_type()==gtk.gdk.WINDOW_TEMP:
            #ignoring one of gtk's temporary windows
            #all the windows we manage should be gtk.gdk.WINDOW_FOREIGN
            log("ignoring TEMP window %s", hex(xid))
            return
        WINDOW_MODEL_KEY = "_xpra_window_model_"
        wid = raw_window.get_data(WINDOW_MODEL_KEY)
        window = self._id_to_window.get(wid)
        if window:
            if window.is_managed():
                log("found existing window model %s for %s, will refresh it", type(window), hex(xid))
                geometry = window.get_property("geometry")
                _, _, w, h = geometry
                self._damage(window, 0, 0, w, h, options={"min_delay" : 50})
                return
            log("found existing model %s (but no longer managed!) for %s", type(window), hex(xid))
            #TODO: we could try to re-use the existing model and window ID,
            #but for now it is just easier to create a new one:
            self._lost_window(window)
        tray_window = get_tray_window(raw_window)
        log("Discovered new override-redirect window: %s (tray=%s)", hex(xid), tray_window)
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
                #if window is set, we failed after instantiating it,
                #so we need to fail it manually:
                window.setup_failed(e)
            else:
                log.warn("cannot add %s: %s", hex(xid), e)
            #from now on, we return to the gtk main loop,
            #so we *should* get a signal when the window goes away

    def _or_window_geometry_changed(self, window, pspec):
        (x, y, w, h) = window.get_property("geometry")
        log("or_window_geometry_changed: %s (window=%s)", window.get_property("geometry"), window)
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.or_window_geometry(wid, window, x, y, w, h)

    # These are the names of WindowModel properties that, when they change,
    # trigger updates in the xpra window metadata:
    _all_metadata = ("title", "pid", "size-hints", "class-instance", "icon", "client-machine", "transient-for", "window-type", "modal")
    _OR_metadata = ("transient-for", "window-type")



    def do_wimpiggy_cursor_event(self, event):
        if not self.cursors:
            return
        if self.last_cursor_serial==event.cursor_serial:
            log("ignoring cursor event with the same serial number")
            return
        self.last_cursor_serial = event.cursor_serial
        if not self.send_cursor_pending:
            self.send_cursor_pending = True
            gobject.timeout_add(10, self.send_cursor)

    def send_cursor(self):
        self.send_cursor_pending = False
        self.cursor_data = get_cursor_image()
        if self.cursor_data:
            pixels = self.cursor_data[7]
            if self.default_cursor_data and pixels==self.default_cursor_data[7]:
                log("send_cursor(): default cursor - clearing it")
                self.cursor_data = None
            elif pixels is not None:
                if len(pixels)<64:
                    self.cursor_data[7] = str(pixels)
                else:
                    self.cursor_data[7] = zlib_compress("cursor", pixels)
        else:
            log("send_cursor() failed to get cursor image")
        for ss in self._server_sources.values():
            ss.send_cursor(self.cursor_data)
        return False

    def _bell_signaled(self, wm, event):
        log("bell signaled on window %s", get_xwindow(event.window))
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
            gobject.idle_add(window.give_client_focus)
            if server_source and modifiers is not None:
                server_source.make_keymask_match(modifiers)
            self._has_focus = wid


    def _send_new_window_packet(self, window):
        geometry = self._desktop_manager.window_geometry(window)
        self._do_send_new_window_packet("new-window", window, geometry, self._all_metadata)

    def _send_new_or_window_packet(self, window, options=None):
        geometry = window.get_property("geometry")
        self._do_send_new_window_packet("new-override-redirect", window, geometry, self._OR_metadata)
        (_, _, w, h) = geometry
        self._damage(window, 0, 0, w, h, options=options)

    def _send_new_tray_window_packet(self, wid, window, options=None):
        (_, _, w, h) = window.get_property("geometry")
        for ss in self._server_sources.values():
            ss.new_tray(wid, window, w, h)
        self._damage(window, 0, 0, w, h, options=options)


    def _update_metadata(self, window, pspec):
        wid = self._window_to_id[window]
        for ss in self._server_sources.values():
            ss.window_metadata(wid, window, pspec.name)

    def _lost_window(self, window, wm_exiting=False):
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
            self._set_client_properties(proto, wid, packet[6])


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
            self._set_client_properties(proto, wid, packet[6])

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

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        ss = self._server_sources.get(proto)
        if ss is None:
            return      #gone already!
        ss.make_keymask_match(modifiers)
        window = self._id_to_window.get(wid)
        if not window:
            log("_process_mouse_common() invalid window id: %s", wid)
            return
        def raise_and_move():
            self._desktop_manager.raise_window(window)
            self._move_pointer(pointer)
        trap.swallow_synced(raise_and_move)


    def _process_close_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid, None)
        if window:
            window.request_close()
        else:
            log("cannot close window %s: it is already gone!", wid)


    def make_screenshot_packet(self):
        return trap.call_synced(self.do_make_screenshot_packet)

    def do_make_screenshot_packet(self):
        log("grabbing screenshot")
        regions = []
        OR_regions = []
        for wid in reversed(sorted(self._id_to_window.keys())):
            window = self._id_to_window.get(wid)
            log("screenshot: window(%s)=%s", wid, window)
            if window is None or window.is_tray() or not window.is_managed():
                continue
            pixmap = window.get_property("client-contents")
            log("screenshot: pixmap(%s)=%s", window, pixmap)
            if pixmap is None:
                continue
            if window.is_OR():
                x, y = window.get_property("geometry")[:2]
            else:
                x, y = self._desktop_manager.window_geometry(window)[:2]
            log("screenshot: position(%s)=%s,%s", window, x, y)
            w, h = pixmap.get_size()
            log("screenshot: size(%s)=%sx%s", pixmap, w, h)
            item = (wid, x, y, w, h, pixmap)
            if window.is_OR():
                OR_regions.append(item)
            elif self._has_focus==wid:
                #window with focus first (drawn last)
                regions.insert(0, item)
            else:
                regions.append(item)
        all_regions = OR_regions+regions
        if len(all_regions)==0:
            log("screenshot: no regions found, returning empty 0x0 image!")
            return ["screenshot", 0, 0, "png", -1, ""]
        log("screenshot: found regions=%s, OR_regions=%s", regions, OR_regions)
        minx = min([x for (_,x,_,_,_,_) in all_regions])
        miny = min([y for (_,_,y,_,_,_) in all_regions])
        maxx = max([(x+w) for (_,x,_,w,_,_) in all_regions])
        maxy = max([(y+h) for (_,_,y,_,h,_) in all_regions])
        width = maxx-minx
        height = maxy-miny
        log("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
        import Image
        image = Image.new("RGBA", (width, height))
        for wid, x, y, w, h, pixmap in reversed(all_regions):
            _, _, wid, _, _, w, h, _, raw_data, rowstride, _, _ = get_rgb_rawdata(0, 0, wid, pixmap, 0, 0, w, h, "rgb24", -1, None, logger=log.debug)
            window_image = Image.fromstring("RGB", (w, h), raw_data, "raw", "RGB", rowstride)
            tx = x-minx
            ty = y-miny
            image.paste(window_image, (tx, ty))
        buf = StringIO()
        image.save(buf, "png")
        data = buf.getvalue()
        buf.close()
        packet = ["screenshot", width, height, "png", rowstride, Compressed("png", data)]
        log("screenshot: %sx%s %s", packet[1], packet[2], packet[-1])
        return packet


gobject.type_register(XpraServer)
