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


from xpra.util import AdHocStruct, bytestostr, typedict, WORKSPACE_UNSET, WORKSPACE_ALL
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_cairo, import_pixbufloader
from xpra.gtk_common.gtk_util import get_pixbuf_from_data
from xpra.gtk_common.keymap import KEY_TRANSLATIONS
from xpra.client.client_window_base import ClientWindowBase
from xpra.platform.gui import get_window_frame_sizes, set_fullscreen_monitors, set_shaded
from xpra.codecs.argb.argb import unpremultiply_argb, bgra_to_rgba    #@UnresolvedImport
gtk     = import_gtk()
gdk     = import_gdk()
cairo   = import_cairo()
PixbufLoader = import_pixbufloader()

CAN_SET_WORKSPACE = False
HAS_X11_BINDINGS = False
if os.name=="posix" and os.environ.get("XPRA_SET_WORKSPACE", "1")!="0":
    try:
        from xpra.x11.gtk_x11.prop import prop_get, prop_set
        from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
        from xpra.x11.bindings.core_bindings import X11CoreBindings
        from xpra.gtk_common.error import xsync, xswallow
        from xpra.x11.gtk_x11.send_wm import send_wm_workspace
        X11Window = X11WindowBindings()
        X11Core = X11CoreBindings()
        HAS_X11_BINDINGS = True

        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]
        CurrentTime = constants["CurrentTime"]

        try:
            #TODO: in theory this is not a proper check, meh - that will do
            root = gtk.gdk.get_default_root_window()
            supported = prop_get(root, "_NET_SUPPORTED", ["atom"], ignore_errors=True)
            CAN_SET_WORKSPACE = bool(supported) and "_NET_WM_DESKTOP" in supported
        except Exception as e:
            log.info("failed to setup workspace hooks: %s", e)
    except ImportError:
        pass


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
                    #"DESKTOP",
                    "DROPDOWN_MENU",
                    "POPUP_MENU",
                    "TOOLTIP",
                    "NOTIFICATION",
                    "COMBO",
                    "DND"))


class GTKKeyEvent(AdHocStruct):
    pass


class GTKClientWindowBase(ClientWindowBase, gtk.Window):

    def init_window(self, metadata):
        self._window_state = {}
        self._resize_counter = 0
        self._can_set_workspace = HAS_X11_BINDINGS and CAN_SET_WORKSPACE
        ClientWindowBase.init_window(self, metadata)

    def _is_popup(self, metadata):
        #decide if the window type is POPUP or NORMAL
        if self._override_redirect:
            return True
        window_types = metadata.get("window-type", [])
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
        #older servers don't tell us if we need decorations, so take a guess:
        #skip decorations for any non-normal non-dialog window that is transient for another window:
        window_types = metadata.get("window-type", [])
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
        #win32 workaround for new window offsets:
        #keep the window contents where they were and adjust the frame
        #this generates a configure event which ensures the server has the correct window position
        #if we end up implementing "get_window_frame_sizes" on other platforms,
        #we may end up calling this code unnecessarily - meh
        wfs = get_window_frame_sizes()
        if wfs and decorated and not was_decorated:
            normal = wfs.get("normal")
            fixed = wfs.get("fixed")
            if normal and fixed:
                nx, ny = normal
                fx, fy = fixed
                x, y = self.get_position()
                gtk.Window.move(self, max(0, x-nx+fx), max(0, y-ny+fy))


    def setup_window(self):
        self.set_app_paintable(True)
        self.add_events(self.WINDOW_EVENT_MASK)
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
        if self._can_set_workspace:
            self.connect("property-notify-event", self.property_changed)
        self.connect("window-state-event", self.window_state_updated)

        #this will create the backing:
        ClientWindowBase.setup_window(self)

        #honour the initial position if the flag is set
        #(or just if non zero, for older servers)
        if self._pos!=(0, 0) or self._set_initial_position:
            self.move(*self._pos)
        self.set_default_size(*self._size)

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


    def show(self):
        if self.group_leader:
            if not self.is_realized():
                self.realize()
            self.window.set_group(self.group_leader)
        gtk.Window.show(self)
        #now it is realized, we can set WM_COMMAND (for X11 clients only)
        command = self._metadata.strget("command")
        if command and HAS_X11_BINDINGS:
            prop_set(self.get_window(), "WM_COMMAND", "latin1", command.decode("latin1"))


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
        if "iconified" in actual_updates:
            iconified = actual_updates.get("iconified")
            statelog("iconified=%s (was %s)", iconified, self._iconified)
            if iconified!=self._iconified:
                self._iconified = iconified
                #handle iconification as map events:
                assert not self._override_redirect
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
                    self.process_map_event()
        self.after_window_state_updated()
        #if we have state updates, send them back to the server using a configure window packet:
        if self.is_OR() and not self._client.window_configure_skip_geometry:
            #we can't do it: the server can't handle configure packets for OR windows!
            log("not sending updated window state %s to a server which is missing the configure skip-geometry feature", self._window_state)
            return
        def send_updated_window_state():
            if self._window_state and self.get_window():
                self.process_configure_event(True)
        if self._window_state:
            self.timeout_add(25, send_updated_window_state)

    def after_window_state_updated(self):
        #this is here to make it easier to hook some code
        #after window_state_updated() has been called
        #(used by the win32 platform workarounds)
        pass


    def set_bypass_compositor(self, v):
        if not HAS_X11_BINDINGS:
            return
        if v not in (0, 1, 2):
            v = 0
        if not self.is_realized():
            self.realize()
        prop_set(self.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", v)


    def set_strut(self, strut):
        if not HAS_X11_BINDINGS:
            return
        log("strut=%s", strut)
        d = typedict(strut)
        values = []
        for x in ("left", "right", "top", "bottom"):
            values.append(d.intget(x, 0))
        has_partial = False
        for x in ("left_start_y", "left_end_y",
                  "right_start_y", "right_end_y",
                  "top_start_x", "top_end_x",
                  "bottom_start_x", "bottom_end_x"):
            if x in d:
                has_partial = True
            values.append(d.intget(x, 0))
        log("setting strut=%s, has partial=%s", values, has_partial)
        if not self.is_realized():
            self.realize()
        if has_partial:
            prop_set(self.get_window(), "_NET_WM_STRUT_PARTIAL", ["u32"], values)
        prop_set(self.get_window(), "_NET_WM_STRUT", ["u32"], values[:4])


    def set_fullscreen_monitors(self, fsm):
        #platform specific code:
        log("set_fullscreen_monitors(%s)", fsm)
        if not self.is_realized():
            self.realize()
        set_fullscreen_monitors(self.get_window(), fsm)


    def set_shaded(self, shaded):
        #platform specific code:
        log("set_shaded(%s)", shaded)
        if not self.is_realized():
            self.realize()
        set_shaded(self.get_window(), shaded)


    def set_fullscreen(self, fullscreen):
        statelog("%s.set_fullscreen(%s)", self, fullscreen)
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

    def set_xid(self, xid):
        if HAS_X11_BINDINGS and self.is_realized():
            try:
                if xid.startswith("0x") and xid.endswith("L"):
                    xid = xid[:-1]
                iid = int(xid, 16)
                self.xset_u32_property(self.get_window(), "XID", iid)
            except Exception as e:
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
        statelog("%s.property_changed(%s, %s) : %s", self, widget, event, event.atom)
        if event.atom=="_NET_WM_DESKTOP" and self._been_mapped and not self._override_redirect:
            self.do_workspace_changed(event)
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
                             }
            state_atoms = set(wm_state_atoms)
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
        workspacelog("do_workspace_changed(%s) (window, desktop): from %s to %s", info, (self._window_workspace, self._desktop_workspace), (window_workspace, desktop_workspace))
        if self._window_workspace==window_workspace and self._desktop_workspace==desktop_workspace:
            #no change
            return
        if not self._client.window_refresh_config:
            workspacelog("sending configure event to update workspace value")
            self.process_configure_event(True)
            return
        #we can tell the server using a "buffer-refresh" packet instead
        #and also take care of tweaking the batch config
        client_properties = {"workspace" : window_workspace}
        options = {"refresh-now" : False}               #no need to refresh it
        suspend_resume = None
        if desktop_workspace<0 or window_workspace is None:
            #maybe the property has been cleared? maybe the window is being scrubbed?
            workspacelog("not sure if the window is shown or not: %s vs %s, resuming to be safe", desktop_workspace, window_workspace)
            suspend_resume = False
        elif window_workspace==WORKSPACE_UNSET:
            workspacelog("workspace unset: assume current")
            suspend_resume = False
        elif window_workspace==WORKSPACE_ALL:
            workspacelog("window is on all workspaces")
            suspend_resume = False
        elif desktop_workspace!=window_workspace:
            workspacelog("window is on a different workspace, increasing its batch delay (desktop: %s, window: %s)", desktop_workspace, window_workspace)
            suspend_resume = True
        elif self._window_workspace!=self._desktop_workspace:
            assert desktop_workspace==window_workspace
            workspacelog("window was on a different workspace, resetting its batch delay (was desktop: %s, window: %s, now both on %s)", self._window_workspace, self._desktop_workspace, desktop_workspace)
            suspend_resume = False
        self._client.control_refresh(self._id, suspend_resume, refresh=False, options=options, client_properties=client_properties)
        self._window_workspace = window_workspace
        self._desktop_workspace = desktop_workspace


    def get_workspace_count(self):
        if not HAS_X11_BINDINGS:
            return 1
        return self.xget_u32_property(root, "_NET_NUMBER_OF_DESKTOPS")

    def set_workspace(self, workspace):
        if not self._can_set_workspace:
            return None
        desktop = self.get_desktop_workspace()
        if self._been_mapped and (workspace==desktop or desktop is None):
            #window is back in view
            self._client.control_refresh(self._id, False, False)
        ndesktops = self.get_workspace_count()
        if ndesktops is None or ndesktops<=1:
            workspacelog("number of desktops not defined, cannot set workspace")
            return None
        if workspace<0:
            #this should not happen, workspace is unsigned! (CARDINAL)
            workspace = WORKSPACE_UNSET
            workspacelog.warn("invalid workspace number: %s", self._window_workspace)
        workspacelog("%s.set_workspace() workspace=%s ndesktops=%s", self, workspace, ndesktops)
        #we will need the gdk window:
        if not self.is_realized():
            self.realize()
        gdkwin = self.get_window()
        if workspace==WORKSPACE_UNSET:
            #we want to remove the setting, so access the window property directly:
            self._window_workspace = workspace
            with xswallow:
                X11Window.XDeleteProperty(gdkwin.xid, "_NET_WM_DESKTOP")
            return self._window_workspace
        #clamp to number of workspaces just in case we have a mismatch:
        if workspace==WORKSPACE_ALL:
            self._window_workspace = WORKSPACE_ALL
        else:
            self._window_workspace = max(0, min(ndesktops-1, workspace))
        workspacelog("%s.set_workspace() clamped workspace=%s", self, self._window_workspace)
        if not gdkwin.is_visible():
            #window is unmapped so we can set the window property directly:
            prop_set(self.get_window(), "_NET_WM_DESKTOP", "u32", self._window_workspace)
            return self._window_workspace
        #the window is visible, so we have to ask the window manager politely
        with xsync:
            send_wm_workspace(root, self.get_window(), self._window_workspace)
        return self._window_workspace


    def initiate_moveresize(self, x_root, y_root, direction, button, source_indication):
        statelog("initiate_moveresize%s", (x_root, y_root, direction, button, source_indication))
        assert HAS_X11_BINDINGS, "cannot handle initiate-moveresize without X11 bindings"
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask
        with xsync:
            from xpra.gtk_common.gobject_compat import get_xid
            root = self.get_window().get_screen().get_root_window()
            root_xid = get_xid(root)
            xwin = get_xid(self.get_window())
            X11Core.UngrabPointer()
            X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_MOVERESIZE",
                  x_root, y_root, direction, button, source_indication)


    def apply_transient_for(self, wid):
        if wid==-1:
            #root is a gdk window, so we need to ensure we have one
            #backing our gtk window to be able to call set_transient_for on it
            log("%s.apply_transient_for(%s) gdkwindow=%s, mapped=%s", self, wid, self.get_window(), self.is_mapped())
            if self.get_window() is None:
                self.realize()
            self.get_window().set_transient_for(gtk.gdk.get_default_root_window())
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
        xid = self._metadata.strget("xid")
        if xid:
            self.set_xid(xid)
        if not self._override_redirect:
            self.process_map_event()
        self._been_mapped = True

    def process_map_event(self):
        x, y, w, h = self.get_window_geometry()
        state = self._window_state
        props = self._client_properties
        self._client_properties = {}
        self._window_state = {}
        if not self._been_mapped:
            #this is the first time around, so save the workspace value:
            workspace = self.set_workspace(self._window_workspace)
        else:
            #window has been mapped, so these attributes can be read (if present):
            props["screen"] = self.get_screen().get_number()
            workspace = self.get_window_workspace()
            if workspace is None:
                #not set, so assume it is on the current workspace:
                workspace = self.get_desktop_workspace()
        if self._window_workspace!=workspace and workspace is not None:
            workspacelog("map event: been_mapped=%s, changed workspace from %s to %s", self._been_mapped, self._window_workspace, workspace)
            self._window_workspace = workspace
            props["workspace"] = workspace
        eventslog("map-window for wid=%s with client props=%s, state=%s", self._id, props, state)
        self.send("map-window", self._id, x, y, w, h, props, state)
        self._pos = (x, y)
        self._size = (w, h)
        self.idle_add(self._focus_change, "initial")


    def do_configure_event(self, event):
        eventslog("%s.do_configure_event(%s)", self, event)
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
        state = self._window_state
        props = self._client_properties
        self._client_properties = {}
        self._window_state = {}
        if self._been_mapped:
            #if the window has been mapped already, the workspace should be set:
            props["screen"] = self.get_screen().get_number()
            workspace = self.get_window_workspace()
            if self._window_workspace!=workspace and workspace is not None:
                workspacelog("configure event: changed workspace from %s to %s", self._window_workspace, workspace)
                self._window_workspace = workspace
                props["workspace"] = workspace
        packet = ["configure-window", self._id, x, y, w, h, props, self._resize_counter, state, skip_geometry]
        eventslog("%s", packet)
        self.send(*packet)
        if dx!=0 or dy!=0:
            #window has moved, also move any child OR window:
            for window in self._override_redirect_windows:
                x, y = window.get_position()
                window.move(x+dx, y+dy)
        if (w, h) != self._size:
            self._size = (w, h)
            self._backing.init(w, h)

    def resize(self, w, h, resize_counter=0):
        log("resize(%s, %s, %s)", w, h, resize_counter)
        self._resize_counter = resize_counter
        gtk.Window.resize(self, w, h)
        self._backing.init(w, h)

    def move_resize(self, x, y, w, h, resize_counter=0):
        statelog("move_resize%s", (x, y, w, h, resize_counter))
        w = max(1, w)
        h = max(1, h)
        self._resize_counter = resize_counter
        window = self.get_window()
        if window.get_position()==(x, y):
            #same location, just resize:
            if self._size!=(w, h):
                self.resize(w, h)
            return
        #we have to move:
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
        if self._size==(w, h):
            #just move:
            window.move(ax, ay)
            return
        #resize:
        self._size = (w, h)
        window.move_resize(ax, ay, w, h)
        #re-init the backing with the new size
        self._backing.init(w, h)

    def destroy(self):
        ClientWindowBase.destroy(self)
        gtk.Window.destroy(self)
        self._unfocus()


    def do_unmap_event(self, event):
        eventslog("do_unmap_event(%s)", event)
        self._unfocus()
        if not self._override_redirect:
            self.send("unmap-window", self._id, False)

    def do_delete_event(self, event):
        eventslog("do_delete_event(%s)", event)
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
        iconlog("%s.update_icon(%s, %s, %s, %s bytes)", self, width, height, coding, len(data))
        coding = bytestostr(coding)
        if coding == "premult_argb32":            #we usually cannot do in-place and this is not performance critical
            data = unpremultiply_argb(data)
            rgba = str(bgra_to_rgba(data))
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
