# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()

import os
import cairo
import re
import sys
import time
import math

from wimpiggy.log import Logger
log = Logger()

DRAW_DEBUG = os.environ.get("XPRA_DRAW_DEBUG", "0")=="1"

try:
    from wimpiggy.prop import prop_get
    has_wimpiggy_prop = True
except ImportError, e:
    has_wimpiggy_prop = False

def xget_u32_property(target, name):
    try:
        if not has_wimpiggy_prop:
            if is_gtk3():
                name_atom = gdk.Atom.intern(name, False)
                type_atom = gdk.Atom.intern("CARDINAL", False)
                gdk.property_get(target, name_atom, type_atom, 0, 9999, False)
            else:
                prop = target.property_get(name)
            if not prop or len(prop)!=3 or len(prop[2])!=1:
                return  None
            log("xget_u32_property(%s, %s)=%s", target, name, prop[2][0])
            return prop[2][0]
        v = prop_get(target, name, "u32", ignore_errors=True)
        log("xget_u32_property(%s, %s)=%s", target, name, v)
        if type(v)==int:
            return  v
    except Exception, e:
        log.error("xget_u32_property error on %s / %s: %s", target, name, e)
    return None

CAN_SET_WORKSPACE = False
if not sys.platform.startswith("win") and has_wimpiggy_prop:
    try:
        #TODO: in theory this is not a proper check, meh - that will do
        root = gtk.gdk.get_default_root_window()
        supported = prop_get(root, "_NET_SUPPORTED", ["atom"], ignore_errors=True)
        CAN_SET_WORKSPACE = bool(supported) and "_NET_WM_DESKTOP" in supported
    except:
        pass

if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x



class ClientWindowBase(gtk.Window):
    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        self.init_window(override_redirect)
        self._client = client
        self.group_leader = group_leader
        self._id = wid
        self._pos = (-1, -1)
        self._size = (w, h)
        self._backing = None
        self.new_backing(w, h)
        self._metadata = {}
        self._override_redirect = override_redirect
        self._client_properties = client_properties
        self._auto_refresh_delay = auto_refresh_delay
        self._refresh_timer = None
        self._refresh_min_pixels = -1
        self._refresh_ignore_sequence = -1
        # used for only sending focus events *after* the window is mapped:
        self._been_mapped = False
        self._override_redirect_windows = []
        # tell KDE/oxygen not to intercept clicks
        # see: https://bugs.kde.org/show_bug.cgi?id=274485
        self.set_data("_kde_no_window_grab", 1)

        self.update_metadata(metadata)

        if not self._override_redirect:
            display = gtk.gdk.display_get_default()
            screen_num = client_properties.get("screen")
            if screen_num is not None and screen_num>=0 and screen_num<display.get_n_screens():
                screen = display.get_screen(screen_num)
                if screen:
                    self.set_screen(screen)

        self.set_app_paintable(True)
        self.add_events(self.WINDOW_EVENT_MASK)
        self.move(x, y)
        self.set_default_size(w, h)
        if override_redirect:
            transient_for = self.get_transient_for()
            type_hint = self.get_type_hint()
            if transient_for is not None and transient_for.window is not None and type_hint in self.OR_TYPE_HINTS:
                transient_for._override_redirect_windows.append(self)
        self.connect("notify::has-toplevel-focus", self._focus_change)
        if CAN_SET_WORKSPACE:
            self.connect("property-notify-event", self.property_changed)

    def property_changed(self, widget, event):
        log("property_changed: %s", event.atom)
        if event.atom=="_NET_WM_DESKTOP" and self._been_mapped and not self._override_redirect:
            #fake a configure event to send the new client_properties with
            #the updated workspace number:
            self.process_configure_event()

    def set_workspace(self):
        if not CAN_SET_WORKSPACE or self._been_mapped:
            return -1
        workspace = self._client_properties.get("workspace", -1)
        log("set_workspace() workspace=%s", workspace)
        if workspace<0 or workspace==self.get_current_workspace():
            return -1
        try:
            from wimpiggy.lowlevel import sendClientMessage, const  #@UnresolvedImport
            from wimpiggy.error import trap
            root = self.gdk_window().get_screen().get_root_window()
            ndesktops = xget_u32_property(root, "_NET_NUMBER_OF_DESKTOPS")
            log("set_workspace() ndesktops=%s", ndesktops)
            if ndesktops is None or ndesktops<=1:
                return  -1
            workspace = max(0, min(ndesktops-1, workspace))
            event_mask = const["SubstructureNotifyMask"] | const["SubstructureRedirectMask"]
            trap.call_synced(sendClientMessage, root, self.gdk_window(), False, event_mask, "_NET_WM_DESKTOP",
                      workspace, const["CurrentTime"],
                      0, 0, 0)
            return workspace
        except Exception, e:
            log.error("failed to set workspace: %s", e)
            return -1

    def is_OR(self):
        return self._override_redirect

    def is_tray(self):
        return False

    def is_GL(self):
        return False

    def get_current_workspace(self):
        window = self.gdk_window()
        root = window.get_screen().get_root_window()
        return self.do_get_workspace(root, "_NET_CURRENT_DESKTOP")

    def get_window_workspace(self):
        return self.do_get_workspace(self.gdk_window(), "_NET_WM_DESKTOP")

    def do_get_workspace(self, target, prop):
        if sys.platform.startswith("win"):
            return  -1              #windows does not have workspaces
        value = xget_u32_property(target, prop)
        if value is not None:
            log("do_get_workspace() found value=%s from %s / %s", value, target, prop)
            return value
        log("do_get_workspace() value not found!")
        return  -1

    def new_backing(self, w, h):
        from xpra.client.window_backing import new_backing
        self._backing = new_backing(self._id, w, h, self._backing, self._client.supports_mmap, self._client.mmap)

    def update_metadata(self, metadata):
        self._metadata.update(metadata)

        title = u(self._client.title)
        if title.find("@")>=0:
            #perform metadata variable substitutions:
            default_values = {"title" : u("<untitled window>"),
                              "client-machine" : u("<unknown machine>")}
            def metadata_replace(match):
                atvar = match.group(0)          #ie: '@title@'
                var = atvar[1:len(atvar)-1]     #ie: 'title'
                default_value = default_values.get(var, u("<unknown %s>") % var)
                value = self._metadata.get(var, default_value)
                if sys.version<'3':
                    value = value.decode("utf-8")
                return value
            title = re.sub("@[\w\-]*@", metadata_replace, title)
        self.set_title(title)

        if "size-constraints" in self._metadata:
            size_metadata = self._metadata["size-constraints"]
            hints = {}
            for (a, h1, h2) in [
                ("maximum-size", "max_width", "max_height"),
                ("minimum-size", "min_width", "min_height"),
                ("base-size", "base_width", "base_height"),
                ("increment", "width_inc", "height_inc"),
                ]:
                v = size_metadata.get(a)
                if v:
                    v1, v2 = v
                    hints[h1], hints[h2] = int(v1), int(v2)
            for (a, h) in [
                ("minimum-aspect-ratio", "min_aspect"),
                ("maximum-aspect-ratio", "max_aspect"),
                ]:
                v = size_metadata.get(a)
                if v:
                    v1, v2 = v
                    hints[h] = float(v1)/float(v2)
            try:
                self.set_geometry_hints(hints)
            except:
                log.error("with hints=%s", hints, exc_info=True)
            #TODO:
            #gravity = size_metadata.get("gravity")

        if hasattr(self, "get_realized"):
            #pygtk 2.22 and above have this method:
            realized = self.get_realized()
        else:
            #older versions:
            realized = self.flags() & gtk.REALIZED
        if not realized:
            self.set_wmclass(*self._metadata.get("class-instance",
                                                 ("xpra", "Xpra")))

        modal = self._metadata.get("modal", False)
        self.set_modal(modal or False)

        if "icon" in self._metadata:
            width, height, coding, data = self._metadata["icon"]
            self.update_icon(width, height, coding, data)

        if "transient-for" in self._metadata:
            wid = self._metadata.get("transient-for")
            if wid==-1:
                window = gtk.gdk.get_default_root_window()
            else:
                window = self._client._id_to_window.get(wid)
            log("found transient-for: %s / %s", wid, window)
            if window:
                self.set_transient_for(window)

        #apply window-type hint if window is not mapped yet:
        if "window-type" in self._metadata and not self.is_mapped(self):
            window_types = self._metadata.get("window-type")
            log("window types=%s", window_types)
            for window_type in window_types:
                hint = self.NAME_TO_HINT.get(window_type)
                if hint:
                    log("setting window type to %s - %s", window_type, hint)
                    self.set_type_hint(hint)
                    break

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

    def refresh_window(self, *args):
        log("refresh_window(%s) wid=%s", args, self._id)
        self._client.send_refresh(self._id)

    def refresh_all_windows(self):
        #this method is only here because we may want to fire it
        #from a --key-shortcut action and the event is delivered to
        #the "ClientWindow"
        self._client.send_refresh_all()

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, packet_sequence, options, callbacks):
        """ Note: this runs from the draw thread (not UI thread) """
        assert self._backing, "window %s has no backing!" % self._id
        def after_draw_refresh(success):
            if DRAW_DEBUG:
                log.info("after_draw_refresh(%s) options=%s", success, options)
            if success and self._backing and self._backing.draw_needs_refresh:
                self.queue_draw(self, x, y, width, height)
            #clear the auto refresh if enough pixels were sent (arbitrary limit..)
            if success and self._refresh_timer and width*height>=self._refresh_min_pixels:
                gobject.source_remove(self._refresh_timer)
                self._refresh_timer = None
            #if we need to set a refresh timer, do it:
            is_hq = options.get("quality", 0)>=95
            is_lossy = coding in ("jpeg", "vpx", "x264")
            if self._refresh_timer is None and self._auto_refresh_delay>0 and is_lossy and not is_hq:
                #make sure our own refresh does not make us fire again
                #FIXME: this should be per-window!
                if self._refresh_ignore_sequence<packet_sequence:
                    #NOTE: for x264 and vpx, we always get full frames (whole window refresh)
                    #this is not the case with jpeg but since jpeg does not switch the encoding on the fly, we're ok
                    self._refresh_min_pixels = width*height
                    self._refresh_ignore_sequence = packet_sequence+1
                    self._refresh_timer = gobject.timeout_add(int(1000 * self._auto_refresh_delay), self.refresh_window)
        callbacks.append(after_draw_refresh)
        self._backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def paint_spinner(self, context, area):
        log("paint_spinner(%s, %s)", context, area)
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
        self.queue_draw(self, 0, 0, w, h)

    def can_have_spinner(self):
        window_types = self._metadata.get("window-type")
        return ("_NET_WM_WINDOW_TYPE_NORMAL" in window_types) or \
               ("_NET_WM_WINDOW_TYPE_DIALOG" in window_types) or \
               ("_NET_WM_WINDOW_TYPE_SPLASH" in window_types)


    def do_map_event(self, event):
        log("Got map event: %s", event)
        gtk.Window.do_map_event(self, event)
        if self.group_leader:
            self.window.set_group(self.group_leader)
        if not self._override_redirect:
            x, y, w, h = self.get_window_geometry(self)
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
            log("map-window for wid=%s with client props=%s", self._id, self._client_properties)
            self._client.send("map-window", self._id, x, y, w, h, self._client_properties)
            self._pos = (x, y)
            self._size = (w, h)
        self._been_mapped = True
        gobject.idle_add(self._focus_change)

    def do_configure_event(self, event):
        log("Got configure event: %s", event)
        gtk.Window.do_configure_event(self, event)
        if not self._override_redirect:
            self.process_configure_event()

    def process_configure_event(self):
        x, y, w, h = self.get_window_geometry(self)
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
            log("configure-window for wid=%s with client props=%s", self._id, self._client_properties)
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
        w = max(1, w)
        h = max(1, h)
        self.window.move_resize(x, y, w, h)
        if (w, h) != self._size:
            self._size = (w, h)
            self.new_backing(w, h)

    def destroy(self):
        if self._refresh_timer:
            gobject.source_remove(self._refresh_timer)
        self._unfocus()
        if self._backing:
            self._backing.close()
            self._backing = None
        gtk.Window.destroy(self)

    def _unfocus(self):
        if self._client._focused==self._id:
            self._client.update_focus(self._id, False)

    def do_unmap_event(self, event):
        self._unfocus()
        if not self._override_redirect:
            self._client.send("unmap-window", self._id)

    def do_delete_event(self, event):
        self._client.send("close-window", self._id)
        return True

    def quit(self):
        self._client.quit(0)

    def void(self):
        pass

    def do_key_press_event(self, event):
        self._client.handle_key_action(event, self, True)

    def do_key_release_event(self, event):
        self._client.handle_key_action(event, self, False)

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

    def do_motion_notify_event(self, event):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        self._client.send_mouse_position(["pointer-position", self._id,
                                          pointer, modifiers, buttons])

    def _button_action(self, button, event, depressed):
        if self._client.readonly:
            return
        pointer, modifiers, buttons = self._pointer_modifiers(event)
        self._client.send_positional(["button-action", self._id,
                                      button, depressed,
                                      pointer, modifiers, buttons])

    def do_button_press_event(self, event):
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        self._button_action(event.button, event, False)

    def do_scroll_event(self, event):
        if self._client.readonly:
            return
        self._button_action(self.SCROLL_MAP[event.direction], event, True)
        self._button_action(self.SCROLL_MAP[event.direction], event, False)

    def _focus_change(self, *args):
        log("_focus_change(%s)", args)
        if self._been_mapped:
            self._client.update_focus(self._id, self.get_property("has-toplevel-focus"))


gobject.type_register(ClientWindowBase)
