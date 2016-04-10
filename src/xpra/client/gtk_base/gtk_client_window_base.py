# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
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
iconlog = Logger("icon")
metalog = Logger("metadata")
statelog = Logger("state")
eventslog = Logger("events")
shapelog = Logger("shape")
mouselog = Logger("mouse")
geomlog = Logger("geometry")
menulog = Logger("menu")


from xpra.os_util import memoryview_to_bytes
from xpra.util import AdHocStruct, bytestostr, typedict, WORKSPACE_UNSET, WORKSPACE_ALL, WORKSPACE_NAMES
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_cairo, import_pixbufloader, get_xid
from xpra.gtk_common.gobject_util import no_arg_signal
from xpra.gtk_common.gtk_util import get_pixbuf_from_data, get_default_root_window, is_realized, WINDOW_POPUP, WINDOW_TOPLEVEL
from xpra.gtk_common.keymap import KEY_TRANSLATIONS
from xpra.client.client_window_base import ClientWindowBase
from xpra.platform.gui import set_fullscreen_monitors, set_shaded
from xpra.codecs.argb.argb import unpremultiply_argb, bgra_to_rgba    #@UnresolvedImport
from xpra.platform.gui import add_window_hooks, remove_window_hooks
gtk     = import_gtk()
gdk     = import_gdk()
cairo   = import_cairo()
PixbufLoader = import_pixbufloader()

CAN_SET_WORKSPACE = False
HAS_X11_BINDINGS = False
if os.name=="posix" and os.environ.get("XPRA_SET_WORKSPACE", "1")!="0":
    try:
        from xpra.x11.gtk_x11.prop import prop_get, prop_set
        from xpra.x11.bindings.window_bindings import constants, X11WindowBindings, SHAPE_KIND  #@UnresolvedImport
        from xpra.x11.bindings.core_bindings import X11CoreBindings
        from xpra.gtk_common.error import xsync
        from xpra.x11.gtk_x11.send_wm import send_wm_workspace
        X11Window = X11WindowBindings()
        X11Core = X11CoreBindings()
        HAS_X11_BINDINGS = True

        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]
        CurrentTime = constants["CurrentTime"]

        try:
            #TODO: in theory this is not a proper check, meh - that will do
            root = get_default_root_window()
            supported = prop_get(root, "_NET_SUPPORTED", ["atom"], ignore_errors=True)
            CAN_SET_WORKSPACE = bool(supported) and "_NET_WM_DESKTOP" in supported
        except Exception as e:
            log.info("failed to setup workspace hooks: %s", e, exc_info=True)
    except ImportError:
        pass


UNDECORATED_TRANSIENT_IS_OR = int(os.environ.get("XPRA_UNDECORATED_TRANSIENT_IS_OR", "1"))

#window types we map to POPUP rather than TOPLEVEL
POPUP_TYPE_HINTS = set((
                    #"DIALOG",
                    #"MENU",
                    #"TOOLBAR",
                    #"SPLASHSCREEN",
                    #"UTILITY",
                    #"DOCK",
                    #"DESKTOP",
                    "DROPDOWN_MENU",
                    "POPUP_MENU",
                    #"TOOLTIP",
                    #"NOTIFICATION",
                    #"COMBO",
                    #"DND"
                    ))
#window types for which we skip window decorations (title bar)
UNDECORATED_TYPE_HINTS = set((
                    #"DIALOG",
                    "MENU",
                    #"TOOLBAR",
                    "SPLASHSCREEN",
                    "UTILITY",
                    "DOCK",
                    "DESKTOP",
                    "DROPDOWN_MENU",
                    "POPUP_MENU",
                    "TOOLTIP",
                    "NOTIFICATION",
                    "COMBO",
                    "DND"))

import sys
WIN32 = sys.platform.startswith("win")
PYTHON3 = sys.version_info[0] == 3
if PYTHON3:
    unicode = str           #@ReservedAssignment


def wn(w):
    return WORKSPACE_NAMES.get(w, w)


class GTKKeyEvent(AdHocStruct):
    pass


class GTKClientWindowBase(ClientWindowBase, gtk.Window):

    __gsignals__ = {
        "state-updated" : no_arg_signal,
        }

    #maximum size of the actual window:
    MAX_VIEWPORT_DIMS = 16*1024, 16*1024
    #maximum size of the backing pixel buffer:
    MAX_BACKING_DIMS = 16*1024, 16*1024

    def init_window(self, metadata):
        self.init_max_window_size(metadata)
        if self._is_popup(metadata):
            window_type = WINDOW_POPUP
        else:
            window_type = WINDOW_TOPLEVEL
        self.do_init_window(window_type)
        self.set_decorated(self._is_decorated(metadata))
        self.set_app_paintable(True)
        self._window_state = {}
        self._resize_counter = 0
        self._can_set_workspace = HAS_X11_BINDINGS and CAN_SET_WORKSPACE
        self._current_frame_extents = None
        self._screen = -1
        self._frozen = False
        #add platform hooks
        self.on_realize_cb = {}
        self.connect_after("realize", self.on_realize)
        self.connect('unrealize', self.on_unrealize)
        self.add_events(self.WINDOW_EVENT_MASK)
        ClientWindowBase.init_window(self, metadata)


    def init_max_window_size(self, metadata):
        """ used by GL windows to enforce a hard limit on window sizes """
        saved_mws = self.max_window_size
        def clamp_to(maxw, maxh):
            #don't bother if the new limit is greater than 16k:
            if maxw>=16*1024 and maxh>=16*1024:
                return
            #only take into account the current max-window-size if non zero:
            mww, mwh = self.max_window_size
            if mww>0:
                maxw = min(mww, maxw)
            if mwh>0:
                maxh = min(mwh, maxh)
            self.max_window_size = maxw, maxh
        #viewport is easy, measured in window pixels:
        clamp_to(*self.MAX_VIEWPORT_DIMS)
        #backing dimensions are harder,
        #we have to take scaling into account (if any):
        clamp_to(*self._client.sp(*self.MAX_BACKING_DIMS))
        if self.max_window_size!=saved_mws:
            log("init_max_window_size(..) max-window-size changed from %s to %s, because of max viewport dims %s and max backing dims %s",
                saved_mws, self.max_window_size, self.MAX_VIEWPORT_DIMS, self.MAX_BACKING_DIMS)


    def _is_popup(self, metadata):
        #decide if the window type is POPUP or NORMAL
        if self._override_redirect:
            return True
        if UNDECORATED_TRANSIENT_IS_OR>0:
            transient_for = metadata.get("transient-for", -1)
            decorations = metadata.get("decorations", 0)
            if transient_for>0 and decorations<=0:
                if UNDECORATED_TRANSIENT_IS_OR>1:
                    metalog("forcing POPUP type for window transient-for=%s", transient_for)
                    return True
                if metadata.get("skip-taskbar"):
                    #look for java AWT
                    wm_class = metadata.get("class-instance")
                    if wm_class and len(wm_class)==2 and wm_class[0].startswith("sun-awt-X11"):
                        metalog("forcing POPUP type for Java AWT skip-taskbar window, transient-for=%s", transient_for)
                        return True
        window_types = metadata.strlistget("window-type", [])
        popup_types = list(POPUP_TYPE_HINTS.intersection(window_types))
        metalog("popup_types(%s)=%s", window_types, popup_types)
        if popup_types:
            metalog("forcing POPUP window type for %s", popup_types)
            return True
        return False

    def _is_decorated(self, metadata):
        #decide if the window type is POPUP or NORMAL
        #(show window decorations or not)
        if self._override_redirect:
            return False
        decorations = metadata.get("decorations")
        if decorations is not None:
            #honour the flag given by the server:
            return bool(decorations)
        if self._client.server_window_decorations:
            #rely on the server to tell us when to turn decorations off
            return True
        #older servers don't tell us if we need decorations, so take a guess:
        #skip decorations for any non-normal non-dialog window that is transient for another window:
        window_types = metadata.strlistget("window-type", [])
        if ("NORMAL" not in window_types) and ("DIALOG" not in window_types) and metadata.intget("transient-for", -1)>0:
            return False
        undecorated_types = list(UNDECORATED_TYPE_HINTS.intersection(window_types))
        metalog("undecorated_types(%s)=%s", window_types, undecorated_types)
        if undecorated_types:
            metalog("not decorating window type %s", undecorated_types)
            return False
        return True

    def set_decorated(self, decorated):
        was_decorated = self.get_decorated()
        if self._fullscreen and was_decorated and not decorated:
            #fullscreen windows aren't decorated anyway!
            #calling set_decorated(False) would cause it to get unmapped! (why?)
            pass
        else:
            gtk.Window.set_decorated(self, decorated)
        if WIN32:
            #workaround for new window offsets:
            #keep the window contents where they were and adjust the frame
            #this generates a configure event which ensures the server has the correct window position
            wfs = self._client.get_window_frame_sizes()
            if wfs and decorated and not was_decorated:
                geomlog("set_decorated(%s) re-adjusting window location using %s", wfs)
                normal = wfs.get("normal")
                fixed = wfs.get("fixed")
                if normal and fixed:
                    nx, ny = normal
                    fx, fy = fixed
                    x, y = self.get_position()
                    gtk.Window.move(self, max(0, x-nx+fx), max(0, y-ny+fy))


    def setup_window(self, *args):
        self.set_alpha()

        if self._override_redirect:
            transient_for = self.get_transient_for()
            type_hint = self.get_type_hint()
            if transient_for is not None and type_hint in self.OR_TYPE_HINTS:
                transient_for._override_redirect_windows.append(self)

        if not self._override_redirect:
            self.connect("notify::has-toplevel-focus", self._focus_change)
        def focus_in(*args):
            focuslog("focus-in-event for wid=%s", self._id)
        def focus_out(*args):
            focuslog("focus-out-event for wid=%s", self._id)
        self.connect("focus-in-event", focus_in)
        self.connect("focus-out-event", focus_out)
        self.connect("property-notify-event", self.property_changed)
        self.connect("window-state-event", self.window_state_updated)

        #this will create the backing:
        ClientWindowBase.setup_window(self, *args)

        #try to honour the initial position
        geomlog("setup_window() position=%s, set_initial_position=%s, OR=%s, decorated=%s", self._pos, self._set_initial_position, self.is_OR(), self.get_decorated())
        if self._pos!=(0, 0) or self._set_initial_position:
            x,y = self._pos
            if not self.is_OR() and self.get_decorated():
                #try to adjust for window frame size if we can figure it out:
                #Note: we cannot just call self.get_window_frame_size() here because
                #the window is not realized yet, and it may take a while for the window manager
                #to set the frame-extents property anyway
                wfs = self._client.get_window_frame_sizes()
                dx, dy = 0, 0
                if wfs:
                    geomlog("setup_window() window frame sizes=%s", wfs)
                    v = wfs.get("offset")
                    if v:
                        dx, dy = v
                        x = max(0, x-dx)
                        y = max(0, y-dy)
                        self._pos = x, y
                        geomlog("setup_window() adjusted initial position=%s", self._pos)
            self.move(x, y)
        self.set_default_size(*self._size)


    def when_realized(self, identifier, callback, *args):
        if self.is_realized():
            callback(*args)
        else:
            self.on_realize_cb[identifier] = callback, args

    def on_realize(self, widget):
        eventslog("on_realize(%s) gdk window=%s", widget, self.get_window())
        add_window_hooks(self)
        cb = self.on_realize_cb
        self.on_realize_cb = {}
        for x, args in cb.values():
            try:
                x(*args)
            except Exception as e:
                log.error("Error on realize callback %s for window %i", x, self._id, exc_info=True)
        if HAS_X11_BINDINGS:
            #request frame extents if the window manager supports it
            self._client.request_frame_extents(self)
        if self.group_leader:
            self.get_window().set_group(self.group_leader)

    def on_unrealize(self, widget):
        eventslog("on_unrealize(%s)", widget)
        remove_window_hooks(self)


    def set_alpha(self):
        #try to enable alpha on this window if needed,
        #and if the backing class can support it:
        bc = self.get_backing_class()
        metalog("set_alpha() has_alpha=%s, %s.HAS_ALPHA=%s, realized=%s", self._has_alpha, bc, bc.HAS_ALPHA, self.is_realized())
        #by default, only RGB (no transparency):
        #rgb_formats = list(BACKING_CLASS.RGB_MODES)
        self._client_properties["encodings.rgb_formats"] = ["RGB", "RGBX"]
        if not self._has_alpha or not bc.HAS_ALPHA:
            self._client_properties["encoding.transparency"] = False
            return
        if self._has_alpha and not self.is_realized():
            if self.enable_alpha():
                self._client_properties["encodings.rgb_formats"] = ["RGBA", "RGB", "RGBX"]
                self._window_alpha = True
            else:
                self._has_alpha = False
                self._client_properties["encoding.transparency"] = False


    def freeze(self):
        #the OpenGL subclasses override this method to also free their GL context
        self._frozen = True
        self.iconify()

    def unfreeze(self):
        if not self._frozen or not self._iconified:
            return
        log("unfreeze() wid=%i, frozen=%s, iconified=%s", self._id, self._frozen, self._iconified)
        if not self._frozen or not self._iconified:
            #has been deiconified already
            return
        self._frozen = False
        self.deiconify()


    def show(self):
        gtk.Window.show(self)


    def window_state_updated(self, widget, event):
        statelog("%s.window_state_updated(%s, %s) changed_mask=%s, new_window_state=%s", self, widget, repr(event), event.changed_mask, event.new_window_state)
        state_updates = {}
        if event.changed_mask & self.WINDOW_STATE_FULLSCREEN:
            state_updates["fullscreen"] = bool(event.new_window_state & self.WINDOW_STATE_FULLSCREEN)
        if event.changed_mask & self.WINDOW_STATE_ABOVE:
            state_updates["above"] = bool(event.new_window_state & self.WINDOW_STATE_ABOVE)
        if event.changed_mask & self.WINDOW_STATE_BELOW:
            state_updates["below"] = bool(event.new_window_state & self.WINDOW_STATE_BELOW)
        if event.changed_mask & self.WINDOW_STATE_STICKY:
            state_updates["sticky"] = bool(event.new_window_state & self.WINDOW_STATE_STICKY)
        if event.changed_mask & self.WINDOW_STATE_ICONIFIED:
            state_updates["iconified"] = bool(event.new_window_state & self.WINDOW_STATE_ICONIFIED)
        if event.changed_mask & self.WINDOW_STATE_MAXIMIZED:
            #this may get sent now as part of map_event code below (and it is irrelevant for the unmap case),
            #or when we get the configure event - which should come straight after
            #if we're changing the maximized state
            state_updates["maximized"] = bool(event.new_window_state & self.WINDOW_STATE_MAXIMIZED)
        self.update_window_state(state_updates)

    def update_window_state(self, state_updates):
        #decide if this is really an update by comparing with our local state vars:
        #(could just be a notification of a state change we already know about)
        actual_updates = {}
        for state,value in state_updates.items():
            var = "_" + state.replace("-", "_")     #ie: "skip-pager" -> "_skip_pager"
            cur = getattr(self, var)                #ie: self._maximized
            if cur!=value:
                setattr(self, var, value)           #ie: self._maximized = True
                actual_updates[state] = value
                statelog("%s=%s (was %s)", var, value, cur)
        statelog("window_state_updated(..) state updates: %s, actual updates: %s", state_updates, actual_updates)
        self._window_state.update(actual_updates)
        #iconification is handled a bit differently...
        iconified = actual_updates.get("iconified")
        if iconified is not None:
            statelog("iconified=%s", iconified)
            #handle iconification as map events:
            if iconified:
                #usually means it is unmapped
                self._unfocus()
                if not self._override_redirect:
                    #tell server, but wait a bit to try to prevent races:
                    def tell_server():
                        if self._iconified:
                            self.send("unmap-window", self._id, True, self._window_state)
                            self._window_state = {}
                    #calculate a good delay to prevent races causing minimize/unminimize loops:
                    delay = 150
                    spl = list(self._client.server_ping_latency)
                    if len(spl)>0:
                        worst = max([x for _,x in spl])
                        delay += int(1000*worst)
                        delay = min(1000, delay)
                    statelog("telling server about iconification with %sms delay", delay)
                    self.timeout_add(delay, tell_server)
            else:
                self._frozen = False
                self.process_map_event()
        self.emit("state-updated")
        #if we have state updates, send them back to the server using a configure window packet:
        if not self._client.window_configure_skip_geometry:
            #we can't do it: the server can't handle configure packets for OR windows!
            statelog("not sending updated window state %s to a server which is missing the configure skip-geometry feature", self._window_state)
            return
        def send_updated_window_state():
            if self._window_state and self.get_window():
                self.send_configure_event(True)
        if self._window_state:
            self.timeout_add(25, send_updated_window_state)


    def set_command(self, command):
        if not HAS_X11_BINDINGS:
            return
        v = command
        if type(command)!=unicode:
            v = bytestostr(command)
            try:
                v = v.decode("utf8")
            except:
                pass
        def do_set_command():
            metalog("do_set_command() str(%s)=%s (type=%s)", command, v, type(command))
            prop_set(self.get_window(), "WM_COMMAND", "latin1", v)
        self.when_realized("command", do_set_command)


    def set_class_instance(self, wmclass_name, wmclass_class):
        if not self.is_realized():
            #Warning: window managers may ignore the icons we try to set
            #if the wm_class value is set and matches something somewhere undocumented
            #(if the default is used, you cannot override the window icon)
            self.set_wmclass(wmclass_name, wmclass_class)
        elif HAS_X11_BINDINGS:
            xid = get_xid(self.get_window())
            with xsync:
                X11Window.setClassHint(xid, wmclass_class, wmclass_name)
                log("XSetClassHint(%s, %s) done", wmclass_class, wmclass_name)

    def set_shape(self, shape):
        shapelog("set_shape(%s)", shape)
        if not HAS_X11_BINDINGS:
            return
        def do_set_shape():
            xid = get_xid(self.get_window())
            x_off, y_off = shape.get("x", 0), shape.get("y", 0)
            for kind, name in SHAPE_KIND.items():
                rectangles = shape.get("%s.rectangles" % name)      #ie: Bounding.rectangles = [(0, 0, 150, 100)]
                if rectangles:
                    #adjust for scaling:
                    if self._client.xscale!=1 or self._client.yscale!=1:
                        x_off, y_off = self._client.sp(x_off, y_off)
                        rectangles = self.scale_shape_rectangles(name, rectangles)
                    #too expensive to log with actual rectangles:
                    shapelog("XShapeCombineRectangles(%#x, %s, %i, %i, %i rects)", xid, name, x_off, y_off, len(rectangles))
                    with xsync:
                        X11Window.XShapeCombineRectangles(xid, kind, x_off, y_off, rectangles)
        self.when_realized("shape", do_set_shape)

    def scale_shape_rectangles(self, kind_name, rectangles):
        try:
            from PIL import Image, ImageDraw        #@UnresolvedImport
        except:
            Image, ImageDraw = None, None
        if not Image or not ImageDraw:
            #scale the rectangles without a bitmap...
            #results aren't so good! (but better than nothing?)
            srect = self._client.srect
            return [srect(*x) for x in rectangles]
        ww, wh = self._size
        sw, sh = self._client.cp(ww, wh)
        img = Image.new('1', (sw, sh), color=0)
        shapelog("drawing %s on bitmap(%s,%s)=%s", kind_name, sw, sh, img)
        d = ImageDraw.Draw(img)
        for x,y,w,h in rectangles:
            d.rectangle([x, y, x+w, y+h], fill=1)
        img = img.resize((ww, wh))
        shapelog("resized %s bitmap to window size %sx%s: %s", kind_name, ww, wh, img)
        #now convert back to rectangles...
        rectangles = []
        for y in range(wh):
            #for debugging, this is very useful, but costly!
            #shapelog("pixels[%3i]=%s", y, "".join([str(img.getpixel((x, y))) for x in range(ww)]))
            x = 0
            start = None
            while x<ww:
                #find first white pixel:
                while x<ww and img.getpixel((x, y))==0:
                    x += 1
                start = x
                #find next black pixel:
                while x<ww and img.getpixel((x, y))!=0:
                    x += 1
                end = x
                if start<end:
                    rectangles.append((start, y, end-start, 1))
        return rectangles

    def set_bypass_compositor(self, v):
        if not HAS_X11_BINDINGS:
            return
        if v not in (0, 1, 2):
            v = 0
        def do_set_bypass_compositor():
            prop_set(self.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", v)
        self.when_realized("bypass-compositor", do_set_bypass_compositor)


    def set_strut(self, strut):
        if not HAS_X11_BINDINGS:
            return
        log("strut=%s", strut)
        d = typedict(strut)
        values = []
        for x in ("left", "right", "top", "bottom"):
            v = d.intget(x, 0)
            #handle scaling:
            if x in ("left", "right"):
                v = self._client.sx(v)
            else:
                v = self._client.sy(v)
            values.append(v)
        has_partial = False
        for x in ("left_start_y", "left_end_y",
                  "right_start_y", "right_end_y",
                  "top_start_x", "top_end_x",
                  "bottom_start_x", "bottom_end_x"):
            if x in d:
                has_partial = True
            v = d.intget(x, 0)
            if x.find("_x"):
                v = self._client.sx(v)
            elif x.find("_y"):
                v = self._client.sy(v)
            values.append(v)
        log("setting strut=%s, has partial=%s", values, has_partial)
        def do_set_strut():
            if has_partial:
                prop_set(self.get_window(), "_NET_WM_STRUT_PARTIAL", ["u32"], values)
            prop_set(self.get_window(), "_NET_WM_STRUT", ["u32"], values[:4])
        self.when_realized("strut", do_set_strut)


    def set_fullscreen_monitors(self, fsm):
        #platform specific code:
        log("set_fullscreen_monitors(%s)", fsm)
        def do_set_fullscreen_monitors():
            set_fullscreen_monitors(self.get_window(), fsm)
        self.when_realized("fullscreen-monitors", do_set_fullscreen_monitors)


    def set_shaded(self, shaded):
        #platform specific code:
        log("set_shaded(%s)", shaded)
        def do_set_shaded():
            set_shaded(self.get_window(), shaded)
        self.when_realized("shaded", do_set_shaded)


    def set_fullscreen(self, fullscreen):
        statelog("%s.set_fullscreen(%s)", self, fullscreen)
        def do_set_fullscreen():
            if fullscreen:
                #we may need to temporarily remove the max-window-size restrictions
                #to be able to honour the fullscreen request:
                w, h = self.max_window_size
                if w>0 and h>0:
                    self.set_size_constraints(self.size_constraints, (0, 0))
                self.fullscreen()
            else:
                self.unfullscreen()
                #re-apply size restrictions:
                w, h = self.max_window_size
                if w>0 and h>0:
                    self.set_size_constraints(self.size_constraints, self.max_window_size)
        self.when_realized("fullscreen", do_set_fullscreen)

    def set_xid(self, xid):
        if not HAS_X11_BINDINGS:
            return
        if xid.startswith("0x") and xid.endswith("L"):
            xid = xid[:-1]
        try:
            iid = int(xid, 16)
        except Exception as e:
            log("%s.set_xid(%s) error parsing/setting xid: %s", self, xid, e)
            return
        def do_set_xid():
            self.xset_u32_property(self.get_window(), "XID", iid)
        self.when_realized("xid", do_set_xid)

    def xget_u32_property(self, target, name):
        v = prop_get(target, name, "u32", ignore_errors=True)
        log("%s.xget_u32_property(%s, %s)=%s", self, target, name, v)
        if type(v)==int:
            return  v
        return None

    def xset_u32_property(self, target, name, value):
        prop_set(target, name, "u32", value)

    def is_realized(self):
        return is_realized(self)


    def property_changed(self, widget, event):
        statelog("property_changed(%s, %s) : %s", widget, event, event.atom)
        if event.atom=="_NET_WM_DESKTOP" and self._been_mapped and not self._override_redirect:
            self.do_workspace_changed(event)
        elif event.atom=="_NET_FRAME_EXTENTS":
            v = prop_get(self.get_window(), "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
            statelog("_NET_FRAME_EXTENTS: %s", v)
            if v:
                if v==self._current_frame_extents:
                    #unchanged
                    return
                if not self._been_mapped:
                    #map event will take care of sending it
                    return
                if self.is_OR() or self.is_tray():
                    #we can't do it: the server can't handle configure packets for OR windows!
                    return
                if not self._client.window_configure_skip_geometry or not self._client.server_window_frame_extents:
                    #can't send cheap "skip-geometry" packets or frame-extents feature not supported:
                    return
                #tell server about new value:
                #TODO: don't bother if unchanged
                self._current_frame_extents = v
                statelog("sending configure event to update _NET_FRAME_EXTENTS to %s", v)
                self._window_state["frame"] = self._client.crect(*v)
                self.send_configure_event(True)
        elif event.atom=="XKLAVIER_STATE":
            #unused for now, but log it:
            xklavier_state = prop_get(self.get_window(), "XKLAVIER_STATE", ["integer"], ignore_errors=False)
            keylog("XKLAVIER_STATE=%s", [hex(x) for x in (xklavier_state or [])])
        elif event.atom=="_NET_WM_STATE":
            wm_state_atoms = prop_get(self.get_window(), "_NET_WM_STATE", ["atom"], ignore_errors=False)
            #code mostly duplicated from gtk_x11/window.py:
            WM_STATE_NAME = {
                             "fullscreen"            : ("_NET_WM_STATE_FULLSCREEN", ),
                             "maximized"             : ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"),
                             "shaded"                : ("_NET_WM_STATE_SHADED", ),
                             "sticky"                : ("_NET_WM_STATE_STICKY", ),
                             "skip-pager"            : ("_NET_WM_STATE_SKIP_PAGER", ),
                             "skip-taskbar"          : ("_NET_WM_STATE_SKIP_TASKBAR", ),
                             "above"                 : ("_NET_WM_STATE_ABOVE", ),
                             "below"                 : ("_NET_WM_STATE_BELOW", ),
                             "focused"               : ("_NET_WM_STATE_FOCUSED", ),
                             }
            state_atoms = set(wm_state_atoms or [])
            state_updates = {}
            for state, atoms in WM_STATE_NAME.items():
                var = "_" + state.replace("-", "_")           #ie: "skip-pager" -> "_skip_pager"
                cur_state = getattr(self, var)
                wm_state_is_set = set(atoms).issubset(state_atoms)
                if wm_state_is_set and not cur_state:
                    state_updates[state] = True
                elif cur_state and not wm_state_is_set:
                    state_updates[state] = False
            log("_NET_WM_STATE=%s, state_updates=%s", wm_state_atoms, state_updates)
            if state_updates:
                self.update_window_state(state_updates)

    def workspace_changed(self):
        #on X11 clients, this fires from the root window property watcher
        ClientWindowBase.workspace_changed(self)
        self.do_workspace_changed("desktop workspace changed")

    def do_workspace_changed(self, info):
        #call this method whenever something workspace related may have changed
        window_workspace = self.get_window_workspace()
        desktop_workspace = self.get_desktop_workspace()
        workspacelog("do_workspace_changed(%s) (window, desktop): from %s to %s", info, (wn(self._window_workspace), wn(self._desktop_workspace)), (wn(window_workspace), wn(desktop_workspace)))
        if self._window_workspace==window_workspace and self._desktop_workspace==desktop_workspace:
            #no change
            return
        #we can tell the server using a "buffer-refresh" packet instead
        #and also take care of tweaking the batch config
        client_properties = {}
        if window_workspace is not None:
            client_properties = {"workspace" : window_workspace}
        options = {"refresh-now" : False}               #no need to refresh it
        suspend_resume = None
        if desktop_workspace<0 or window_workspace is None:
            #maybe the property has been cleared? maybe the window is being scrubbed?
            workspacelog("not sure if the window is shown or not: %s vs %s, resuming to be safe", wn(desktop_workspace), wn(window_workspace))
            suspend_resume = False
        elif window_workspace==WORKSPACE_UNSET:
            workspacelog("workspace unset: assume current")
            suspend_resume = False
        elif window_workspace==WORKSPACE_ALL:
            workspacelog("window is on all workspaces")
            suspend_resume = False
        elif desktop_workspace!=window_workspace:
            workspacelog("window is on a different workspace, increasing its batch delay (desktop: %s, window: %s)", wn(desktop_workspace), wn(window_workspace))
            suspend_resume = True
        elif self._window_workspace!=self._desktop_workspace:
            assert desktop_workspace==window_workspace
            workspacelog("window was on a different workspace, resetting its batch delay (was desktop: %s, window: %s, now both on %s)", wn(self._window_workspace), wn(self._desktop_workspace), wn(desktop_workspace))
            suspend_resume = False
        self._client.control_refresh(self._id, suspend_resume, refresh=False, options=options, client_properties=client_properties)
        self._window_workspace = window_workspace
        self._desktop_workspace = desktop_workspace


    def get_workspace_count(self):
        if not HAS_X11_BINDINGS:
            return None
        return self.xget_u32_property(root, "_NET_NUMBER_OF_DESKTOPS")


    def set_workspace(self, workspace):
        workspacelog("set_workspace(%s)", workspace)
        if not self._been_mapped:
            #will be dealt with in the map event handler
            #which will look at the window metadata again
            workspacelog("workspace=%s will be set when the window is mapped", wn(workspace))
            return
        desktop = self.get_desktop_workspace()
        ndesktops = self.get_workspace_count()
        current = self.get_window_workspace()
        workspacelog("set_workspace(%s) realized=%s, current workspace=%s, detected=%s, desktop workspace=%s, ndesktops=%s",
                     wn(workspace), self.is_realized(), wn(self._window_workspace), wn(current), wn(desktop), ndesktops)
        if not self._can_set_workspace or ndesktops is None:
            return None
        if workspace==desktop or workspace==WORKSPACE_ALL or desktop is None:
            #window is back in view
            self._client.control_refresh(self._id, False, False)
        if (workspace<0 or workspace>=ndesktops) and workspace not in(WORKSPACE_UNSET, WORKSPACE_ALL):
            #this should not happen, workspace is unsigned (CARDINAL)
            #and the server should have the same list of desktops that we have here
            workspacelog.warn("Warning: invalid workspace number: %s", wn(workspace))
            workspace = WORKSPACE_UNSET
        if workspace==WORKSPACE_UNSET:
            #we cannot unset via send_wm_workspace, so we have to choose one:
            workspace = self.get_desktop_workspace()
        if workspace in (None, WORKSPACE_UNSET):
            workspacelog.warn("workspace=%s (doing nothing)", wn(workspace))
            return
        #we will need the gdk window:
        if current==workspace:
            workspacelog("window workspace unchanged: %s", wn(workspace))
            return
        gdkwin = self.get_window()
        workspacelog("do_set_workspace: gdkwindow: %#x, mapped=%s, visible=%s", get_xid(gdkwin), self.is_mapped(), gdkwin.is_visible())
        with xsync:
            send_wm_workspace(root, gdkwin, workspace)


    def set_menu(self, menu):
        menulog("set_menu(%s)", menu)
        def do_set_menu():
            self._client.set_window_menu(True, self._id, menu, self.application_action_callback, self.window_action_callback)
        self.when_realized("menu", do_set_menu)

    def application_action_callback(self, action_service, action, state, pdata):
        self.call_action("application", action, state, pdata)

    def window_action_callback(self, action_service, action, state, pdata):
        self.call_action("window", action, state, pdata)

    def call_action(self, action_type, action, state, pdata):
        menulog("call_action%s", (action_type, action, state, pdata))
        rpc_args = [action_type, self._id, action, state, pdata]
        try:
            self._client.rpc_call("menu", rpc_args)
        except Exception as e:
            log.error("Error: failed to send %s menu rpc request for %s", action_type, action, exc_info=True)


    def initiate_moveresize(self, x_root, y_root, direction, button, source_indication):
        statelog("initiate_moveresize%s", (x_root, y_root, direction, button, source_indication))
        assert HAS_X11_BINDINGS, "cannot handle initiate-moveresize without X11 bindings"
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask
        root = self.get_window().get_screen().get_root_window()
        root_xid = get_xid(root)
        xwin = get_xid(self.get_window())
        with xsync:
            X11Core.UngrabPointer()
            X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_MOVERESIZE",
                  x_root, y_root, direction, button, source_indication)


    def apply_transient_for(self, wid):
        if wid==-1:
            def set_root_transient():
                #root is a gdk window, so we need to ensure we have one
                #backing our gtk window to be able to call set_transient_for on it
                log("%s.apply_transient_for(%s) gdkwindow=%s, mapped=%s", self, wid, self.get_window(), self.is_mapped())
                self.get_window().set_transient_for(gtk.gdk.get_default_root_window())
            self.when_realized("transient-for-root", set_root_transient)
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
        context.set_source_rgba(0.2, 0.2, 0.2, 0.4)
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
        count = int(time.time()*4.0)
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
        if not self._override_redirect:
            self.process_map_event()

    def process_map_event(self):
        x, y, w, h = self.get_window_geometry()
        state = self._window_state
        props = self._client_properties
        self._client_properties = {}
        self._window_state = {}
        workspace = self.get_window_workspace()
        workspacelog("process_map_event() workspace=%s, been_mapped=%s", workspace, self._been_mapped)
        if self._been_mapped:
            screen = self.get_screen().get_number()
            if screen!=self._screen:
                props["screen"] = screen
                self._screen = screen
            if workspace is None:
                #not set, so assume it is on the current workspace:
                workspace = self.get_desktop_workspace()
        else:
            self._been_mapped = True
            workspace = self._metadata.intget("workspace", WORKSPACE_UNSET)
            if workspace!=WORKSPACE_UNSET:
                self.set_workspace(workspace)
        if self._window_workspace!=workspace and workspace is not None:
            workspacelog("map event: been_mapped=%s, changed workspace from %s to %s", self._been_mapped, wn(self._window_workspace), wn(workspace))
            self._window_workspace = workspace
        if workspace is not None:
            props["workspace"] = workspace
        if self._client.server_window_frame_extents and "frame" not in state:
            wfs = self.get_window_frame_size()
            if wfs:
                state["frame"] = self._client.crect(*wfs)
                self._current_frame_extents = wfs
        geomlog("map-window for wid=%s with client props=%s, state=%s", self._id, props, state)
        cx = self._client.cx
        cy = self._client.cy
        self.send("map-window", self._id, cx(x), cy(y), cx(w), cy(h), props, state)
        self._pos = (x, y)
        self._size = (w, h)
        if self._backing is None:
            #we may have cleared the backing, so we must re-create one:
            self._set_backing_size(w, h)
        self.idle_add(self._focus_change, "initial")

    def get_window_frame_size(self):
        frame = self._client.get_frame_extents(self)
        if not frame:
            #default to global value we may have:
            wfs = self._client.get_window_frame_sizes()
            if wfs:
                frame = wfs.get("frame")
        return frame


    def send_configure(self):
        self.send_configure_event()

    def do_configure_event(self, event):
        eventslog("%s.do_configure_event(%s) OR=%s, iconified=%s", self, event, self._override_redirect, self._iconified)
        gtk.Window.do_configure_event(self, event)
        if not self._override_redirect and not self._iconified:
            self.process_configure_event()

    def process_configure_event(self, skip_geometry=False):
        assert skip_geometry or not self.is_OR()
        x, y, w, h = self.get_window_geometry()
        w = max(1, w)
        h = max(1, h)
        ox, oy = self._pos
        dx, dy = x-ox, y-oy
        self._pos = (x, y)
        self.send_configure_event(skip_geometry)
        if dx!=0 or dy!=0:
            #window has moved, also move any child OR window:
            for window in self._override_redirect_windows:
                x, y = window.get_position()
                window.move(x+dx, y+dy)
        log("configure event: current size=%s, new size=%s, backing=%s, iconified=%s", self._size, (w, h), self._backing, self._iconified)
        if (w, h) != self._size or (self._backing is None and not self._iconified):
            self._size = (w, h)
            self._set_backing_size(w, h)

    def send_configure_event(self, skip_geometry=False):
        assert skip_geometry or not self.is_OR()
        x, y, w, h = self.get_window_geometry()
        w = max(1, w)
        h = max(1, h)
        state = self._window_state
        props = self._client_properties
        self._client_properties = {}
        self._window_state = {}
        if self._been_mapped:
            #if the window has been mapped already, the workspace should be set:
            screen = self.get_screen().get_number()
            if screen!=self._screen:
                props["screen"] = screen
                self._screen = screen
            workspace = self.get_window_workspace()
            if self._window_workspace!=workspace and workspace is not None:
                workspacelog("configure event: changed workspace from %s to %s", wn(self._window_workspace), wn(workspace))
                self._window_workspace = workspace
                props["workspace"] = workspace
        cx = self._client.cx
        cy = self._client.cy
        packet = ["configure-window", self._id, cx(x), cy(y), cx(w), cy(h), props, self._resize_counter, state, skip_geometry]
        if self._client.window_configure_pointer:
            packet.append(self.get_mouse_event_wid())
            packet.append(self._client.get_mouse_position())
            packet.append(self._client.get_current_modifiers())
        geomlog("%s", packet)
        self.send(*packet)

    def _set_backing_size(self, ww, wh):
        b = self._backing
        if b:
            b.init(ww, wh, self._client.cx(ww), self._client.cy(wh))
        else:
            self.new_backing(self._client.cx(ww), self._client.cy(wh))

    def resize(self, w, h, resize_counter=0):
        log("resize(%s, %s, %s)", w, h, resize_counter)
        self._resize_counter = resize_counter
        gtk.Window.resize(self, w, h)
        self._set_backing_size(w, h)

    def move_resize(self, x, y, w, h, resize_counter=0):
        geomlog("window %i move_resize%s", self._id, (x, y, w, h, resize_counter))
        w = max(1, w)
        h = max(1, h)
        self._resize_counter = resize_counter
        window = self.get_window()
        if window.get_position()==(x, y):
            #same location, just resize:
            if self._size==(w, h):
                geomlog("window unchanged")
            else:
                geomlog("unchanged position %ix%i, using resize(%i, %i)", x, y, w, h)
                self.resize(w, h)
            return
        #we have to move:
        mw, mh = self._client.get_root_size()
        if not self.is_realized():
            geomlog("window was not realized yet")
            self.realize()
        #adjust for window frame:
        ox, oy = window.get_origin()[-2:]
        rx, ry = window.get_root_origin()
        ax = x - (ox - rx)
        ay = y - (oy - ry)
        geomlog("window origin=%ix%i, root origin=%ix%i, actual position=%ix%i", ox, oy, rx, ry, ax, ay)
        #validate against edge of screen (ensure window is shown):
        if (ax + w)<0:
            ax = -w + 1
        elif ax >= mw:
            ax = mw - 1
        if (ay + h)<0:
            ay = -y + 1
        elif ay >= mh:
            ay = mh -1
        geomlog("validated window position for total screen area %ix%i : %ix%i", mw, mh, ax, ay)
        if self._size==(w, h):
            #just move:
            geomlog("window size unchanged: %ix%i, using move(%i, %i)", w, h, ax, ay)
            window.move(ax, ay)
            return
        #resize:
        self._size = (w, h)
        geomlog("%s.move_resize%s", window, (ax, ay, w, h))
        window.move_resize(ax, ay, w, h)
        #re-init the backing with the new size
        self._set_backing_size(w, h)


    def noop_destroy(self):
        log.warn("Warning: window destroy called twice!")

    def destroy(self):
        if self._client._set_window_menu:
            self._client.set_window_menu(False, self._id, {})
        self.on_realize_cb = {}
        ClientWindowBase.destroy(self)
        gtk.Window.destroy(self)
        self._unfocus()
        self.destroy = self.noop_destroy


    def do_unmap_event(self, event):
        eventslog("do_unmap_event(%s)", event)
        self._unfocus()
        if not self._override_redirect:
            self.send("unmap-window", self._id, False)

    def do_delete_event(self, event):
        eventslog("do_delete_event(%s)", event)
        self._client.window_close_event(self._id)
        return True


    def _pointer_modifiers(self, event):
        pointer = self._client.cp(event.x_root, event.y_root)
        modifiers = self._client.mask_to_names(event.state)
        buttons = []
        for mask, button in self.BUTTON_MASK.items():
            if event.state & mask:
                buttons.append(button)
        v = pointer, modifiers, buttons
        mouselog("pointer_modifiers(%s)=%s", event, v)
        return v

    def parse_key_event(self, event, pressed):
        keyval = event.keyval
        keycode = event.hardware_keycode
        keyname = gdk.keyval_name(keyval)
        keyname = KEY_TRANSLATIONS.get((keyname, keyval, keycode), keyname)
        key_event = GTKKeyEvent()
        key_event.modifiers = self._client.mask_to_names(event.state)
        key_event.keyname = keyname or ""
        key_event.keyval = keyval or 0
        key_event.keycode = keycode
        key_event.group = event.group
        key_event.string = event.string or ""
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
        coding = bytestostr(coding)
        iconlog("%s.update_icon(%s, %s, %s, %s bytes)", self, width, height, coding, len(data))
        if PYTHON3 and WIN32:
            iconlog("not setting icon to prevent crashes..")
            return
        if coding == "premult_argb32":            #we usually cannot do in-place and this is not performance critical
            data = unpremultiply_argb(data)
            rgba = memoryview_to_bytes(bgra_to_rgba(data))
            pixbuf = get_pixbuf_from_data(rgba, True, width, height, width*4)
        else:
            loader = PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
        #for debugging, save to a file so we can see it:
        #pixbuf.save("C-%s-%s.png" % (self._id, int(time.time())), "png")
        iconlog("%s.set_icon(%s)", self, pixbuf)
        self.set_icon(pixbuf)
