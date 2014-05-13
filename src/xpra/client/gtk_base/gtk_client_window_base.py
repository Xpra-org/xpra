# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import math

from xpra.log import Logger
focuslog = Logger("focus")
workspacelog = Logger("workspace")
log = Logger("window")
keylog = Logger("keyboard")

from xpra.util import AdHocStruct, nn, bytestostr
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_cairo, import_pixbufloader
from xpra.gtk_common.gtk_util import pixbuf_new_from_data, COLORSPACE_RGB
from xpra.client.client_window_base import ClientWindowBase
gtk     = import_gtk()
gdk     = import_gdk()
cairo   = import_cairo()
PixbufLoader = import_pixbufloader()

CAN_SET_WORKSPACE = False
HAS_X11_BINDINGS = False
if os.name=="posix":
    try:
        from xpra.x11.gtk_x11.prop import prop_get, prop_set
        from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
        from xpra.gtk_common.error import trap
        X11Window = X11WindowBindings()
        HAS_X11_BINDINGS = True

        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]
        CurrentTime = constants["CurrentTime"]

        try:
            #TODO: in theory this is not a proper check, meh - that will do
            root = gtk.gdk.get_default_root_window()
            supported = prop_get(root, "_NET_SUPPORTED", ["atom"], ignore_errors=True)
            CAN_SET_WORKSPACE = bool(supported) and "_NET_WM_DESKTOP" in supported
        except Exception, e:
            log.info("failed to setup workspace hooks: %s", e)
    except ImportError, e:
        pass

#optional module providing faster handling of premultiplied argb:
try:
    from xpra.codecs.argb.argb import unpremultiply_argb, byte_buffer_to_buffer   #@UnresolvedImport
except:
    unpremultiply_argb, byte_buffer_to_buffer  = None, None



class GTKKeyEvent(AdHocStruct):
    pass


class GTKClientWindowBase(ClientWindowBase, gtk.Window):

    def init_window(self, metadata):
        self._fullscreen = None
        self._iconified = False
        self._resize_counter = 0
        self._window_workspace = self._client_properties.get("workspace")
        workspacelog("init_window(..) workspace=%s", self._window_workspace)
        self._desktop_workspace = -1
        ClientWindowBase.init_window(self, metadata)
        self._can_set_workspace = HAS_X11_BINDINGS and CAN_SET_WORKSPACE


    def setup_window(self):
        self.set_app_paintable(True)
        self.add_events(self.WINDOW_EVENT_MASK)

        #try to enable alpha on this window if needed,
        #and if the backing class can support it:
        bc = self.get_backing_class()
        log("setup_window() has_alpha=%s, %s.HAS_ALPHA=%s", self._has_alpha, bc, bc.HAS_ALPHA)
        if self._has_alpha and bc.HAS_ALPHA:
            screen = self.get_screen()
            rgba = screen.get_rgba_colormap()
            if rgba is None:
                log.error("cannot handle window transparency on screen %s", screen)
            else:
                self.set_colormap(rgba)
                self._window_alpha = True

        if self._override_redirect:
            transient_for = self.get_transient_for()
            type_hint = self.get_type_hint()
            if transient_for is not None and transient_for.window is not None and type_hint in self.OR_TYPE_HINTS:
                transient_for._override_redirect_windows.append(self)

        if not self._override_redirect:
            self.connect("notify::has-toplevel-focus", self._focus_change)
        def focus_in(*args):
            focuslog("focus-in-event for wid=%s", self._id)
        def focus_out(*args):
            focuslog("focus-out-event for wid=%s", self._id)
        self.connect("focus-in-event", focus_in)
        self.connect("focus-out-event", focus_out)
        if self._can_set_workspace:
            self.connect("property-notify-event", self.property_changed)
        self.connect("window-state-event", self.window_state_updated)

        #this will create the backing:
        ClientWindowBase.setup_window(self)

        self.move(*self._pos)
        self.set_default_size(*self._size)

    def show(self):
        if self.group_leader:
            if not self.is_realized():
                self.realize()
            self.window.set_group(self.group_leader)
        gtk.Window.show(self)


    def window_state_updated(self, widget, event):
        self._fullscreen = bool(event.new_window_state & self.WINDOW_STATE_FULLSCREEN)
        maximized = bool(event.new_window_state & self.WINDOW_STATE_MAXIMIZED)
        iconified = bool(event.new_window_state & self.WINDOW_STATE_ICONIFIED)
        self._client_properties["maximized"] = maximized
        log("%s.window_state_updated(%s, %s) new_window_state=%s, fullscreen=%s, maximized=%s, iconified=%s", self, widget, repr(event), event.new_window_state, self._fullscreen, maximized, iconified)
        if iconified!=self._iconified:
            #handle iconification as map events:
            assert not self._override_redirect
            if iconified:
                assert not self._iconified
                #usually means it is unmapped
                self._iconified = True
                self._unfocus()
                if not self._override_redirect:
                    self.send("unmap-window", self._id, True)
            else:
                assert not iconified and self._iconified
                self._iconified = False
                self.process_map_event()

    def set_fullscreen(self, fullscreen):
        if self._fullscreen is None or self._fullscreen!=fullscreen:
            #note: the "_fullscreen" flag is updated by the window-state-event, not here
            log("%s.set_fullscreen(%s)", self, fullscreen)
            if fullscreen:
                self.fullscreen()
            else:
                self.unfullscreen()

    def set_xid(self, xid):
        if HAS_X11_BINDINGS and self.is_realized():
            try:
                if xid.startswith("0x") and xid.endswith("L"):
                    xid = xid[:-1]
                iid = int(xid, 16)
                self.xset_u32_property(self.gdk_window(), "XID", iid)
            except Exception, e:
                log("%s.set_xid(%s) error parsing/setting xid: %s", self, xid, e)
                return

    def xget_u32_property(self, target, name):
        v = prop_get(target, name, "u32", ignore_errors=True)
        log("%s.xget_u32_property(%s, %s)=%s", self, target, name, v)
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
        log("%s.property_changed(%s, %s) : %s", self, widget, event, event.atom)
        if event.atom=="_NET_WM_DESKTOP" and self._been_mapped and not self._override_redirect:
            self.do_workspace_changed(event)

    def workspace_changed(self):
        #on X11 clients, this fires from the root window property watcher 
        ClientWindowBase.workspace_changed(self)
        self.do_workspace_changed("desktop workspace changed")
    
    def do_workspace_changed(self, info):
        #call this method whenever something workspace related may have changed
        window_workspace = self.get_window_workspace()
        desktop_workspace = self.get_desktop_workspace()
        workspacelog("do_worskpace_changed(%s) window/desktop: from %s to %s", info, (self._window_workspace, self._desktop_workspace), (window_workspace, desktop_workspace))
        if self._window_workspace==window_workspace and self._desktop_workspace==desktop_workspace:
            #no change
            return
        if not self._client.window_refresh_config:
            workspacelog("sending configure event to update workspace value")
            self.process_configure_event()
            return
        #we can tell the server using a "buffer-refresh" packet instead
        #and also take care of tweaking the batch config
        client_properties = {"workspace" : window_workspace}
        options = {"refresh-now" : False}               #no need to refresh it
        suspend_resume = None
        if desktop_workspace<0 or window_workspace<0:
            #maybe the property has been cleared? maybe the window is being scrubbed?
            workspacelog("not sure if the window is shown or not: %s vs %s, resuming to be safe", desktop_workspace, window_workspace)
            suspend_resume = False
        elif desktop_workspace!=window_workspace:
            workspacelog("window is on a different workspace, increasing its batch delay")
            suspend_resume = True
        elif self._window_workspace!=self._desktop_workspace:
            workspacelog("window was on a different workspace, resetting its batch delay")
            suspend_resume = False
        self._client.control_refresh(self._id, suspend_resume, refresh=False, options=options, client_properties=client_properties)
        self._window_workspace = window_workspace
        self._desktop_workspace = desktop_workspace


    def get_workspace_count(self):
        if not HAS_X11_BINDINGS:
            return 1
        return self.xget_u32_property(root, "_NET_NUMBER_OF_DESKTOPS")

    def set_workspace(self):
        if not HAS_X11_BINDINGS:
            return -1
        root = self.gdk_window().get_screen().get_root_window()
        ndesktops = self.get_workspace_count()
        workspacelog("%s.set_workspace() workspace=%s ndesktops=%s", self, self._window_workspace, ndesktops)
        if ndesktops is None or ndesktops<=1:
            return  -1
        workspace = max(0, min(ndesktops-1, self._window_workspace))
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask

        def send():
            from xpra.gtk_common.gobject_compat import get_xid
            root_xid = get_xid(root)
            xwin = get_xid(self.gdk_window())
            X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_DESKTOP",
                  workspace, CurrentTime, 0, 0, 0)
        trap.call_synced(send)
        return workspace

    def get_desktop_workspace(self):
        return -1

    def get_window_workspace(self):
        return -1


    def apply_transient_for(self, wid):
        if wid==-1:
            #root is a gdk window, so we need to ensure we have one
            #backing our gtk window to be able to call set_transient_for on it
            log("%s.apply_transient_for(%s) gdkwindow=%s, mapped=%s", self, wid, self.gdk_window(), self.is_mapped())
            if self.gdk_window() is None:
                self.realize()
            self.gdk_window().set_transient_for(gtk.gdk.get_default_root_window())
        else:
            #gtk window is easier:
            window = self._client._id_to_window.get(wid)
            log("%s.apply_transient_for(%s) window=%s", self, wid, window)
            if window:
                self.set_transient_for(window)


    def paint_spinner(self, context, area):
        log("%s.paint_spinner(%s, %s)", self, context, area)
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
        log("%s.do_map_event(%s) OR=%s", self, event, self._override_redirect)
        gtk.Window.do_map_event(self, event)
        xid = self._metadata.strget("xid")
        if xid:
            self.set_xid(xid)
        if not self._override_redirect:
            self.process_map_event()
        self._been_mapped = True

    def process_map_event(self):
        x, y, w, h = self.get_window_geometry()
        props = self._client_properties
        self._client_properties = {}
        if not self._been_mapped:
            #this is the first time around, so set the workspace:
            workspace = self.set_workspace()
        else:
            #window has been mapped, so these attributes can be read (if present):
            props["screen"] = self.get_screen().get_number()
            workspace = self.get_window_workspace()
            if workspace<0:
                workspace = self.get_desktop_workspace()
        if self._window_workspace!=workspace:
            workspacelog("map event: been_mapped=%s, changed workspace from %s to %s", self._been_mapped, self._window_workspace, workspace)
            self._window_workspace = workspace
            props["workspace"] = workspace
        log("map-window for wid=%s with client props=%s", self._id, props)
        self.send("map-window", self._id, x, y, w, h, props)
        self._pos = (x, y)
        self._size = (w, h)
        self.idle_add(self._focus_change, "initial")


    def do_configure_event(self, event):
        log("%s.do_configure_event(%s)", self, event)
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
        props = self._client_properties
        self._client_properties = {}
        if self._been_mapped:
            #if the window has been mapped already, the workspace should be set:
            props["screen"] = self.get_screen().get_number()
            workspace = self.get_window_workspace()
            if self._window_workspace!=workspace:
                workspacelog("configure event: changed workspace from %s to %s", self._window_workspace, workspace)
                self._window_workspace = workspace
                props["workspace"] = workspace
        packet = ["configure-window", self._id, x, y, w, h, props]
        if self._resize_counter>0:
            packet.append(self._resize_counter)
        self.send(*packet)
        if dx!=0 or dy!=0:
            #window has moved, also move any child OR window:
            for window in self._override_redirect_windows:
                x, y = window.get_position()
                window.move(x+dx, y+dy)
        if (w, h) != self._size:
            self._size = (w, h)
            self.new_backing(w, h)

    def resize(self, w, h, resize_counter=0):
        log("resize(%s, %s, %s)", w, h, resize_counter)
        self._resize_counter = resize_counter
        gtk.Window.resize(self, w, h)

    def move_resize(self, x, y, w, h, resize_counter=0):
        log("move_resize%s", (x, y, w, h, resize_counter))
        w = max(1, w)
        h = max(1, h)
        self._resize_counter = resize_counter
        window = self.gdk_window()
        if window.get_position()==(x, y):
            #same location, just resize:
            if self._size!=(w, h):
                self.resize(w, h)
        else:
            mw, mh = self._client.get_root_size()
            if not self.is_realized():
                self.realize()
            #adjust for window frame:
            ox, oy = window.get_origin()[-2:]
            rx, ry = window.get_root_origin()
            ax = x - (ox - rx)
            ay = y - (oy - ry)
            #validate against edge of screen (ensure window is shown):
            if (ax + w)<0:
                ax = -w + 1
            elif ax >= mw:
                ax = mw - 1
            if (ay + h)<0:
                ay = -y + 1
            elif ay >= mh:
                ay = mh -1
            if self._size!=(w, h):
                window.move_resize(ax, ay, w, h)
            else:
                #just move:
                window.move(ax, ay)
        if self._size!=(w, h):
            self._size = (w, h)
            self.new_backing(w, h)

    def destroy(self):
        ClientWindowBase.destroy(self)
        gtk.Window.destroy(self)
        self._unfocus()


    def do_unmap_event(self, event):
        self._unfocus()
        if not self._override_redirect:
            self.send("unmap-window", self._id, False)

    def do_delete_event(self, event):
        self.send("close-window", self._id)
        return True


    def _pointer_modifiers(self, event):
        pointer = (int(event.x_root), int(event.y_root))
        modifiers = self._client.mask_to_names(event.state)
        buttons = []
        for mask, button in self.BUTTON_MASK.items():
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
        keylog("parse_key_event(%s, %s)=%s", event, pressed, key_event)
        return key_event

    def do_key_press_event(self, event):
        key_event = self.parse_key_event(event, True)
        self._client.handle_key_action(self, key_event)

    def do_key_release_event(self, event):
        key_event = self.parse_key_event(event, False)
        self._client.handle_key_action(self, key_event)


    def _focus_change(self, *args):
        assert not self._override_redirect
        htf = self.has_toplevel_focus()
        focuslog("%s focus_change(%s) has-toplevel-focus=%s, _been_mapped=%s", self, args, htf, self._been_mapped)
        if self._been_mapped:
            self._client.update_focus(self._id, htf)


    def update_icon(self, width, height, coding, data):
        log("%s.update_icon(%s, %s, %s, %s bytes)", self, width, height, coding, len(data))
        coding = bytestostr(coding)
        if coding == "premult_argb32":
            if unpremultiply_argb is None:
                #we could use PIL here with mode 'RGBa'
                log.warn("cannot process premult_argb32 icon without the argb module")
                return
            #we usually cannot do in-place and this is not performance critical
            data = byte_buffer_to_buffer(unpremultiply_argb(data))
            pixbuf = pixbuf_new_from_data(data, COLORSPACE_RGB, True, 8, width, height, width*4)
        else:
            loader = PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
        log("%s.set_icon(%s)", self, pixbuf)
        self.set_icon(pixbuf)
