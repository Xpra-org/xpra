# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#disabled for now as this causes bugs:
PRESERVE_WORSPACE = False

#pygtk3 vs pygtk2 (sigh)
from wimpiggy.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()
if is_gtk3():
    def init_window(win, wintype):
        #TODO: no idea how to do this with gtk3
        #maybe not even possible..
        gtk.Window.__init__(win)
    def is_mapped(win):
        return win.get_mapped()
    def get_window_geometry(gtkwindow):
        x, y = gtkwindow.get_position()
        w, h = gtkwindow.get_size()
        return (x, y, w, h)
    def set_geometry_hints(window, hints):
        """ we convert the hints as a dict into a gdk.Geometry + gdk.WindowHints """
        wh = gdk.WindowHints
        name_to_hint = {"maximum-size"  : wh.MAX_SIZE,
                        "max_width"     : wh.MAX_SIZE,
                        "max_height"    : wh.MAX_SIZE,
                        "minimum-size"  : wh.MIN_SIZE,
                        "min_width"     : wh.MIN_SIZE,
                        "min_height"    : wh.MIN_SIZE,
                        "base-size"     : wh.BASE_SIZE,
                        "base_width"    : wh.BASE_SIZE,
                        "base_height"   : wh.BASE_SIZE,
                        "increment"     : wh.RESIZE_INC,
                        "width_inc"     : wh.RESIZE_INC,
                        "height_inc"    : wh.RESIZE_INC,
                        "min_aspect_ratio"  : wh.ASPECT,
                        "max_aspect_ratio"  : wh.ASPECT,
                        }
        #these fields can be copied directly to the gdk.Geometry as ints:
        INT_FIELDS= ["min_width",    "min_height",
                        "max_width",    "max_height",
                        "base_width",   "base_height",
                        "width_inc",    "height_inc"]
        ASPECT_FIELDS = {
                        "min_aspect_ratio"  : "min_aspect",
                        "max_aspect_ratio"  : "max_aspect",
                         }
        geom = gdk.Geometry()
        mask = 0
        for k,v in hints.items():
            if k in INT_FIELDS:
                setattr(geom, k, int(v))
                mask |= int(name_to_hint.get(k, 0))
            elif k in ASPECT_FIELDS:
                field = ASPECT_FIELDS.get(k)
                setattr(geom, field, float(v))
                mask |= int(name_to_hint.get(k, 0))
        hints = gdk.WindowHints(mask)
        window.set_geometry_hints(None, geom, hints)

    def queue_draw(window, x, y, width, height):
        window.queue_draw_area(x, y, width, height)
    WINDOW_POPUP = gtk.WindowType.POPUP
    WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL
    WINDOW_EVENT_MASK = 0
    OR_TYPE_HINTS = []
    NAME_TO_HINT = { }
    SCROLL_MAP = {}
else:
    def init_window(gtkwindow, wintype):
        gtk.Window.__init__(gtkwindow, wintype)
    def is_mapped(win):
        return win.window is not None and win.window.is_visible()
    def get_window_geometry(gtkwindow):
        gdkwindow = gtkwindow.get_window()
        x, y = gdkwindow.get_origin()
        _, _, w, h, _ = gdkwindow.get_geometry()
        return (x, y, w, h)
    def set_geometry_hints(gtkwindow, hints):
        gtkwindow.set_geometry_hints(None, **hints)

    def queue_draw(gtkwindow, x, y, width, height):
        window = gtkwindow.get_window()
        if window:
            window.invalidate_rect(gdk.Rectangle(x, y, width, height), False)
        else:
            log.warn("ignoring draw received for a window which is not realized yet!")

    WINDOW_POPUP = gtk.WINDOW_POPUP
    WINDOW_TOPLEVEL = gtk.WINDOW_TOPLEVEL
    WINDOW_EVENT_MASK = gdk.STRUCTURE_MASK | gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK | gdk.POINTER_MOTION_MASK | gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK
    OR_TYPE_HINTS = [gdk.WINDOW_TYPE_HINT_DIALOG,
                gdk.WINDOW_TYPE_HINT_MENU, gdk.WINDOW_TYPE_HINT_TOOLBAR,
                #gdk.WINDOW_TYPE_HINT_SPLASHSCREEN, gdk.WINDOW_TYPE_HINT_UTILITY,
                #gdk.WINDOW_TYPE_HINT_DOCK, gdk.WINDOW_TYPE_HINT_DESKTOP,
                gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU, gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                gdk.WINDOW_TYPE_HINT_TOOLTIP,
                #gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                gdk.WINDOW_TYPE_HINT_COMBO,gdk.WINDOW_TYPE_HINT_DND]
    NAME_TO_HINT = {
                "_NET_WM_WINDOW_TYPE_NORMAL"    : gdk.WINDOW_TYPE_HINT_NORMAL,
                "_NET_WM_WINDOW_TYPE_DIALOG"    : gdk.WINDOW_TYPE_HINT_DIALOG,
                "_NET_WM_WINDOW_TYPE_MENU"      : gdk.WINDOW_TYPE_HINT_MENU,
                "_NET_WM_WINDOW_TYPE_TOOLBAR"   : gdk.WINDOW_TYPE_HINT_TOOLBAR,
                "_NET_WM_WINDOW_TYPE_SPLASH"    : gdk.WINDOW_TYPE_HINT_SPLASHSCREEN,
                "_NET_WM_WINDOW_TYPE_UTILITY"   : gdk.WINDOW_TYPE_HINT_UTILITY,
                "_NET_WM_WINDOW_TYPE_DOCK"      : gdk.WINDOW_TYPE_HINT_DOCK,
                "_NET_WM_WINDOW_TYPE_DESKTOP"   : gdk.WINDOW_TYPE_HINT_DESKTOP,
                "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU" : gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU,
                "_NET_WM_WINDOW_TYPE_POPUP_MENU": gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                "_NET_WM_WINDOW_TYPE_TOOLTIP"   : gdk.WINDOW_TYPE_HINT_TOOLTIP,
                "_NET_WM_WINDOW_TYPE_NOTIFICATION" : gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                "_NET_WM_WINDOW_TYPE_COMBO"     : gdk.WINDOW_TYPE_HINT_COMBO,
                "_NET_WM_WINDOW_TYPE_DND"       : gdk.WINDOW_TYPE_HINT_DND
                }
    # Map scroll directions back to mouse buttons.  Mapping is taken from
    # gdk/x11/gdkevents-x11.c.
    SCROLL_MAP = {gdk.SCROLL_UP: 4,
                  gdk.SCROLL_DOWN: 5,
                  gdk.SCROLL_LEFT: 6,
                  gdk.SCROLL_RIGHT: 7,
                  }


import cairo
import re
import sys

from wimpiggy.log import Logger
log = Logger()

from xpra.window_backing import new_backing
try:
    from wimpiggy.prop import prop_set, prop_get
    has_wimpiggy_prop = True
except ImportError, e:
    has_wimpiggy_prop = False

if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x



class ClientWindow(gtk.Window):
    def __init__(self, client, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        if override_redirect:
            init_window(self, WINDOW_POPUP)
        else:
            init_window(self, WINDOW_TOPLEVEL)
        self._client = client
        self._id = wid
        self._pos = (-1, -1)
        self._size = (1, 1)
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

        self.set_app_paintable(True)
        self.add_events(WINDOW_EVENT_MASK)
        self.move(x, y)
        self.set_default_size(w, h)
        if override_redirect:
            transient_for = self.get_transient_for()
            type_hint = self.get_type_hint()
            if transient_for is not None and transient_for.window is not None and type_hint in OR_TYPE_HINTS:
                transient_for._override_redirect_windows.append(self)
        self.connect("notify::has-toplevel-focus", self._focus_change)

    def do_realize(self):
        if not PRESERVE_WORSPACE:
            gtk.Window.do_realize(self)
            return
        ndesktops = 0
        try:
            root = gtk.gdk.screen_get_default().get_root_window()
            prop = root.property_get("_NET_NUMBER_OF_DESKTOPS")
            if prop is not None and len(prop)==3 and len(prop[2])==1:
                ndesktops = prop[2][0]
        except Exception, e:
            log.error("failed to get workspace count: %s", e)
        workspace = self._client_properties.get("workspace", -1)
        log("do_realize() workspace=%s (ndesktops=%s)", workspace, ndesktops)

        #below we duplicate gtk.window.realize() code
        #just so we can insert the property code at the right place:
        #after the gdk.Window is created, but before it gets positionned.
        allocation = self.get_allocation()
        if allocation.x==-1 and allocation.y==-1 and allocation.width==1 and allocation.height==1:
            w, h = self.size_request()
            if w>0 or h>0:
                allocation.width = w
                allocation.height = h
            self.size_allocate(w, h)
            self.queue_resize()
            if self.flags() & gtk.REALIZED:
                log.error("window is already realized!")
                return

        self.set_flags(gtk.REALIZED)
        is_toplevel = self.get_parent() is None
        if hasattr(self, "is_toplevel"):
            is_toplevel = self.is_toplevel()
        if is_toplevel:
            window_type = gtk.gdk.WINDOW_TOPLEVEL
        else:
            window_type = gtk.gdk.WINDOW_TEMP
        if self.get_has_frame():
            #TODO: duplicate gtk code here too..
            pass

        events = self.get_events() | gdk.EXPOSURE_MASK | gdk.STRUCTURE_MASK | \
                    gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK
        self.window = gdk.Window(
            self.get_root_window(),
            x=allocation.x, y=allocation.y, width=allocation.width, height=allocation.height,
            wmclass_name=self.wmclass_name, wmclass_class=self.wmclass_class,
            window_type=window_type,
            wclass=gdk.INPUT_OUTPUT,
            title=self.get_title(),
            event_mask=events,
            )

        if has_wimpiggy_prop and not self._override_redirect and ndesktops>workspace and workspace>=0:
            try:
                prop_set(self.window, "_NET_WM_DESKTOP", "u32", workspace)
            except Exception, e:
                log.error("failed to set workspace: %s", e)

        self.window.set_opacity(1.0)
        #self.window.enable_synchronized_configure().. not used?
        self.window.set_user_data(self)
        self.style.attach(self.window)
        self.style.set_background(self.window, gtk.STATE_NORMAL)
        #self.paint() does not exist in pygtk..
        transient_for = self.get_transient_for()
        if transient_for and transient_for.flags() & gtk.REALIZED:
            self.window.set_transient_for(transient_for.get_window())
        if not self.get_decorated():
            self.window.set_decorations(0)
        if not self.get_deletable():
            self.window.set_functions(gtk.gdk.FUNC_ALL | gtk.gdk.FUNC_CLOSE)
        if self.get_skip_pager_hint():
            self.window.set_skip_pager_hint(True)
        if self.get_skip_taskbar_hint():
            self.window.set_skip_taskbar_hint(True)
        self.window.set_accept_focus(self.get_accept_focus())
        self.window.set_focus_on_map(self.get_focus_on_map())
        self.window.set_modal_hint(self.get_modal())
        #cannot access startup id...

    def get_workspace(self):
        try:
            if sys.platform.startswith("win"):
                return  -1              #windows does not have workspaces
            if not has_wimpiggy_prop:
                prop = self.window.get_screen().get_root_window().property_get("_NET_CURRENT_DESKTOP")
                if not prop or len(prop)!=3 or len(prop[2])!=1:
                    return  -1
                return prop[2][0]
            v = prop_get(self.get_window(), "_NET_WM_DESKTOP", "u32", ignore_errors=True)
            if type(v)==int:
                return  v
        except Exception, e:
            log.error("failed to detect workspace: %s", e)
        return  -1


    def new_backing(self, w, h):
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
                if a in self._metadata["size-constraints"]:
                    hints[h1], hints[h2] = size_metadata[a]
            for (a, h) in [
                ("minimum-aspect", "min_aspect_ratio"),
                ("maximum-aspect", "max_aspect_ratio"),
                ]:
                if a in self._metadata:
                    hints[h] = size_metadata[a][0] * 1.0 / size_metadata[a][1]
            set_geometry_hints(self, hints)

        if hasattr(self, "get_realized"):
            #pygtk 2.22 and above have this method:
            realized = self.get_realized()
        else:
            #older versions:
            realized = self.flags() & gtk.REALIZED
        if not realized:
            self.set_wmclass(*self._metadata.get("class-instance",
                                                 ("xpra", "Xpra")))

        if "icon" in self._metadata:
            (width, height, coding, data) = self._metadata["icon"]
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

        if "transient-for" in self._metadata:
            wid = self._metadata.get("transient-for")
            window = self._client._id_to_window.get(wid)
            log("found transient-for: %s / %s", wid, window)
            if window:
                self.set_transient_for(window)

        #apply window-type hint if window is not mapped yet:
        if "window-type" in self._metadata and not is_mapped(self):
            window_types = self._metadata.get("window-type")
            log("window types=%s", window_types)
            for window_type in window_types:
                hint = NAME_TO_HINT.get(window_type)
                if hint:
                    log("setting window type to %s - %s", window_type, hint)
                    self.set_type_hint(hint)
                    break

    def refresh_window(self, *args):
        log("refresh_window(%s) wid=%s", args, self._id)
        self._client.send_refresh(self._id)

    def refresh_all_windows(self):
        #this method is only here because we may want to fire it
        #from a --key-shortcut action and the event is delivered to
        #the "ClientWindow"
        self._client.send_refresh_all()

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, packet_sequence, options, callbacks):
        def after_draw_refresh(success):
            log("after_draw_refresh(%s) options=%s", success, options)
            if success:
                queue_draw(self, x, y, width, height)
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

    """ gtk3 """
    def do_draw(self, context):
        log("do_draw(%s)", context)
        if self.get_mapped():
            self._backing.cairo_draw(context, 0, 0)

    """ gtk2 """
    def do_expose_event(self, event):
        log("do_expose_event(%s) area=%s", event, event.area)
        if not (self.flags() & gtk.MAPPED):
            return
        x,y,_,_ = event.area
        context = self.window.cairo_create()
        context.rectangle(event.area)
        context.clip()
        self._backing.cairo_draw(context, x, y)

    def do_map_event(self, event):
        log("Got map event: %s", event)
        gtk.Window.do_map_event(self, event)
        if not self._override_redirect:
            x, y, w, h = get_window_geometry(self)
            client_properties = {"workspace" : self.get_workspace()}
            self._client.send("map-window", self._id, x, y, w, h, client_properties)
            self._pos = (x, y)
            self._size = (w, h)
        self._been_mapped = True
        gobject.idle_add(self._focus_change)

    def do_configure_event(self, event):
        log("Got configure event: %s", event)
        gtk.Window.do_configure_event(self, event)
        if self._override_redirect:
            return
        x, y, w, h = get_window_geometry(self)
        w = max(1, w)
        h = max(1, h)
        ox, oy = self._pos
        dx, dy = x-ox, y-oy
        self._pos = (x, y)
        if self._client.window_configure:
            #if we support configure-window, send that first
            client_properties = {"workspace" : self.get_workspace()}
            self._client.send("configure-window", self._id, x, y, w, h, client_properties)
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
        self.new_backing(w, h)

    def destroy(self):
        self._unfocus()
        gtk.Window.destroy(self)
        self._backing.close()

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
        return pointer, modifiers

    def do_motion_notify_event(self, event):
        if self._client.readonly:
            return
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_mouse_position(["pointer-position", self._id,
                                          pointer, modifiers])

    def _button_action(self, button, event, depressed):
        if self._client.readonly:
            return
        (pointer, modifiers) = self._pointer_modifiers(event)
        self._client.send_positional(["button-action", self._id,
                                      button, depressed,
                                      pointer, modifiers])

    def do_button_press_event(self, event):
        if self._client.readonly:
            return
        self._button_action(event.button, event, True)

    def do_button_release_event(self, event):
        if self._client.readonly:
            return
        self._button_action(event.button, event, False)

    def do_scroll_event(self, event):
        if self._client.readonly:
            return
        self._button_action(SCROLL_MAP[event.direction], event, True)
        self._button_action(SCROLL_MAP[event.direction], event, False)

    def _focus_change(self, *args):
        log("_focus_change(%s)", args)
        if self._been_mapped:
            self._client.update_focus(self._id, self.get_property("has-toplevel-focus"))


gobject.type_register(ClientWindow)
