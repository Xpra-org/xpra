# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.client_window_base import ClientWindowBase

from xpra.util import AdHocStruct, nn
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk
gtk = import_gtk()
gdk = import_gdk()

import os
import cairo
import sys
import time
import math


CAN_SET_WORKSPACE = False
HAS_X11_BINDINGS = False
if os.name=="posix":
    try:
        from xpra.x11.gtk_x11.prop import prop_get, prop_set
        from xpra.x11.gtk_x11.gdk_bindings import get_xwindow
        from xpra.x11.bindings.window_bindings import const, X11WindowBindings  #@UnresolvedImport
        from xpra.x11.gtk_x11.error import trap
        HAS_X11_BINDINGS = True
        try:
            #TODO: in theory this is not a proper check, meh - that will do
            root = gtk.gdk.get_default_root_window()
            supported = prop_get(root, "_NET_SUPPORTED", ["atom"], ignore_errors=True)
            CAN_SET_WORKSPACE = bool(supported) and "_NET_WM_DESKTOP" in supported
        except:
            pass
    except ImportError, e:
        pass


class GTKKeyEvent(AdHocStruct):
    pass

class GTKClientWindowBase(ClientWindowBase, gtk.Window):

    def init_window(self, metadata):
        self._fullscreen = None
        self._can_set_workspace = HAS_X11_BINDINGS and CAN_SET_WORKSPACE
        ClientWindowBase.init_window(self, metadata)
        # tell KDE/oxygen not to intercept clicks
        # see: https://bugs.kde.org/show_bug.cgi?id=274485
        self.set_data("_kde_no_window_grab", 1)

    def setup_window(self):
        ClientWindowBase.setup_window(self)
        #preserve screen:
        if not self._override_redirect:
            display = gtk.gdk.display_get_default()
            screen_num = self._client_properties.get("screen")
            if screen_num is not None and screen_num>=0 and screen_num<display.get_n_screens():
                screen = display.get_screen(screen_num)
                if screen:
                    self.set_screen(screen)
        self.set_app_paintable(True)
        self.add_events(self.WINDOW_EVENT_MASK)
        if self._override_redirect:
            transient_for = self.get_transient_for()
            type_hint = self.get_type_hint()
            if transient_for is not None and transient_for.window is not None and type_hint in self.OR_TYPE_HINTS:
                transient_for._override_redirect_windows.append(self)
        self.connect("notify::has-toplevel-focus", self._focus_change)
        if self._can_set_workspace:
            self.connect("property-notify-event", self.property_changed)
        self.connect("window-state-event", self.window_state_updated)

        self.move(*self._pos)
        self.set_default_size(*self._size)

    def window_state_updated(self, widget, event):
        self._fullscreen = bool(event.new_window_state & gtk.gdk.WINDOW_STATE_FULLSCREEN)
        self.debug("window_state_updated(%s, %s) new_window_state=%s, fullscreen=%s", widget, repr(event), event.new_window_state, self._fullscreen)

    def set_fullscreen(self, fullscreen):
        self.debug("set_fullscreen(%s)", fullscreen)
        if self._fullscreen is None or self._fullscreen!=fullscreen:
            #note: the "_fullscreen" flag is updated by the window-state-event, not here
            if fullscreen:
                self.fullscreen()
            else:
                self.unfullscreen()

    def set_xid(self, xid):
        if HAS_X11_BINDINGS and self.is_realized():
            self.debug("set_xid(%s)", xid)
            try:
                if xid.startswith("0x") and xid.endswith("L"):
                    xid = xid[:-1]
                iid = int(xid, 16)
                self.debug("set_xid(%s) using xset_u32_property", iid)
                self.xset_u32_property(self.gdk_window(), "XID", iid)
            except Exception, e:
                self.debug("set_xid(%s) error parsing/setting xid: %s", xid, e)
                return

    def xget_u32_property(self, target, name):
        v = prop_get(target, name, "u32", ignore_errors=True)
        self.debug("xget_u32_property(%s, %s)=%s", target, name, v)
        if type(v)==int:
            return  v
        return None

    def xset_u32_property(self, target, name, value):
        prop_set(target, name, "u32", value)

    def is_realized(self):
        if hasattr(self, "get_realized"):
            #pygtk 2.22 and above have this method:
            return self.get_realized()
        #older versions:
        return self.flags() & gtk.REALIZED


    def property_changed(self, widget, event):
        self.debug("property_changed: %s", event.atom)
        if event.atom=="_NET_WM_DESKTOP" and self._been_mapped and not self._override_redirect:
            #fake a configure event to send the new client_properties with
            #the updated workspace number:
            self.process_configure_event()

    def do_set_workspace(self, workspace):
        assert HAS_X11_BINDINGS
        root = self.gdk_window().get_screen().get_root_window()
        ndesktops = self.xget_u32_property(root, "_NET_NUMBER_OF_DESKTOPS")
        self.debug("set_workspace() ndesktops=%s", ndesktops)
        if ndesktops is None or ndesktops<=1:
            return  -1
        workspace = max(0, min(ndesktops-1, workspace))
        event_mask = const["SubstructureNotifyMask"] | const["SubstructureRedirectMask"]
        def send():
            root_window = get_xwindow(root)
            window = get_xwindow(self.gdk_window())
            X11WindowBindings.sendClientMessage(root_window, window, False, event_mask, "_NET_WM_DESKTOP",
                  workspace, const["CurrentTime"],
                  0, 0, 0)
        trap.call_synced(send)
        return workspace

    def get_current_workspace(self):
        window = self.gdk_window()
        root = window.get_screen().get_root_window()
        return self.do_get_workspace(root, "_NET_CURRENT_DESKTOP")

    def get_window_workspace(self):
        return self.do_get_workspace(self.gdk_window(), "_NET_WM_DESKTOP")

    def do_get_workspace(self, target, prop):
        if sys.platform.startswith("win"):
            return  -1              #windows does not have workspaces
        value = self.xget_u32_property(target, prop)
        if value is not None:
            self.debug("do_get_workspace() found value=%s from %s / %s", value, target, prop)
            return value
        self.debug("do_get_workspace() value not found!")
        return  -1


    def apply_transient_for(self, wid):
        if wid==-1:
            window = gtk.gdk.get_default_root_window()
        else:
            window = self._client._id_to_window.get(wid)
        self.debug("found transient-for: %s / %s", wid, window)
        if window:
            self.set_transient_for(window)

    def update_icon(self, width, height, coding, data):
        if coding == "premult_argb32":
            cairo_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            cairo_surf.get_data()[:] = data
            # FIXME: We round-trip through PNG. This is ridiculous, but faster
            # than doing a bunch of alpha un-premultiplying and byte-swapping
            # by hand in Python (better still would be to write some Pyrex,
            # but I don't have time right now):
            loader = gdk.PixbufLoader()
            cairo_surf.write_to_png(loader)
            loader.close()
            pixbuf = loader.get_pixbuf()
        else:
            loader = gdk.PixbufLoader(coding)
            loader.write(data, len(data))
            loader.close()
            pixbuf = loader.get_pixbuf()
        self.set_icon(pixbuf)


    def paint_spinner(self, context, area):
        self.debug("paint_spinner(%s, %s)", context, area)
        #add grey semi-opaque layer on top:
        context.set_operator(cairo.OPERATOR_OVER)
        context.set_source_rgba(0.2, 0.2, 0.2, 0.8)
        context.rectangle(area)
        #w, h = self._size
        #context.rectangle(gdk.Rectangle(0, 0, w, h))
        context.fill()
        #add spinner:
        w, h = self.get_size()
        dim = min(w/3.0, h/3.0, 100.0)
        context.set_line_width(dim/10.0)
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.translate(w/2, h/2)
        from xpra.gtk_common.gtk_spinner import cv
        count = int(time.time()*5.0)
        for i in range(8):      #8 lines
            context.set_source_rgba(0, 0, 0, cv.trs[count%8][i])
            context.move_to(0.0, -dim/4.0)
            context.line_to(0.0, -dim)
            context.rotate(math.pi/4)
            context.stroke()

    def spinner(self, ok):
        if not self.can_have_spinner():
            return
        #with normal windows, we just queue a draw request
        #and let the expose event paint the spinner
        w, h = self.get_size()
        self.queue_draw(0, 0, w, h)


    def do_map_event(self, event):
        self.debug("Got map event: %s", event)
        gtk.Window.do_map_event(self, event)
        if self.group_leader:
            self.window.set_group(self.group_leader)
        xid = self._metadata.get("xid")
        if xid:
            self.set_xid(xid)
        if not self._override_redirect:
            x, y, w, h = self.get_window_geometry()
            if not self._been_mapped:
                workspace = self.set_workspace()
            else:
                #window has been mapped, so these attributes can be read (if present):
                self._client_properties["screen"] = self.get_screen().get_number()
                workspace = self.get_window_workspace()
                if workspace<0:
                    workspace = self.get_current_workspace()
            if workspace>=0:
                self._client_properties["workspace"] = workspace
            self.debug("map-window for wid=%s with client props=%s", self._id, self._client_properties)
            self._client.send("map-window", self._id, x, y, w, h, self._client_properties)
            self._pos = (x, y)
            self._size = (w, h)
        self._been_mapped = True
        self.idle_add(self._focus_change)

    def do_configure_event(self, event):
        self.debug("Got configure event: %s", event)
        gtk.Window.do_configure_event(self, event)
        if not self._override_redirect:
            self.process_configure_event()

    def process_configure_event(self):
        x, y, w, h = self.get_window_geometry()
        w = max(1, w)
        h = max(1, h)
        ox, oy = self._pos
        dx, dy = x-ox, y-oy
        self._pos = (x, y)
        if self._client.window_configure:
            #if we support configure-window, send that first
            if self._been_mapped:
                #if the window has been mapped already, the workspace should be set:
                self._client_properties["screen"] = self.get_screen().get_number()
                workspace = self.get_window_workspace()
                if workspace<0:
                    workspace = self.get_current_workspace()
                if workspace>=0:
                    self._client_properties["workspace"] = workspace
            self.debug("configure-window for wid=%s with client props=%s", self._id, self._client_properties)
            self._client.send("configure-window", self._id, x, y, w, h, self._client_properties)
        if dx!=0 or dy!=0:
            #window has moved
            if not self._client.window_configure:
                #if we don't handle the move via configure:
                self._client.send("move-window", self._id, x, y)
            #move any OR window with their parent:
            for window in self._override_redirect_windows:
                x, y = window.get_position()
                window.move(x+dx, y+dy)
        if (w, h) != self._size:
            self._size = (w, h)
            self.new_backing(w, h)
            if not self._client.window_configure:
                self._client.send("resize-window", self._id, w, h)

    def move_resize(self, x, y, w, h):
        assert self._override_redirect
        assert self._offset == (0, 0, 0, 0)
        w = max(1, w)
        h = max(1, h)
        self.window.move_resize(x, y, w, h)
        if (w, h) != self._size:
            self._size = (w, h)
            self.new_backing(w, h)

    def destroy(self):
        if self._refresh_timer:
            self.source_remove(self._refresh_timer)
        self._unfocus()
        if self._backing:
            self._backing.close()
            self._backing = None
        gtk.Window.destroy(self)


    def do_unmap_event(self, event):
        self._unfocus()
        if not self._override_redirect:
            self._client.send("unmap-window", self._id)

    def do_delete_event(self, event):
        self._client.send("close-window", self._id)
        return True


    def _pointer_modifiers(self, event):
        pointer = (int(event.x_root), int(event.y_root))
        modifiers = self._client.mask_to_names(event.state)
        buttons = []
        for mask, button in {gtk.gdk.BUTTON1_MASK : 1,
                             gtk.gdk.BUTTON2_MASK : 2,
                             gtk.gdk.BUTTON3_MASK : 3,
                             gtk.gdk.BUTTON4_MASK : 4,
                             gtk.gdk.BUTTON5_MASK : 5}.items():
            if event.state & mask:
                buttons.append(button)
        return pointer, modifiers, buttons

    def parse_key_event(self, event, pressed):
        key_event = GTKKeyEvent()
        key_event.modifiers = self._client.mask_to_names(event.state)
        key_event.keyname = nn(gdk.keyval_name(event.keyval))
        key_event.keyval = nn(event.keyval)
        key_event.keycode = event.hardware_keycode
        key_event.group = event.group
        key_event.string = nn(event.string)
        key_event.pressed = pressed
        return key_event

    def do_key_press_event(self, event):
        key_event = self.parse_key_event(event, True)
        self._client.handle_key_action(self, key_event)

    def do_key_release_event(self, event):
        key_event = self.parse_key_event(event, False)
        self._client.handle_key_action(self, key_event)


    def _focus_change(self, *args):
        self.debug("_focus_change(%s)", args)
        if self._been_mapped:
            self._client.update_focus(self._id, self.get_property("has-toplevel-focus"))

