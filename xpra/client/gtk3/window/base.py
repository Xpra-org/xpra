# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from time import monotonic
from typing import Any
from collections.abc import Callable, Sequence

from cairo import RectangleInt, Region
from xpra.os_util import gi_import, WIN32, OSX, POSIX
from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr
from xpra.util.env import envint, envbool, first_time, ignorewarnings, IgnoreWarningsContext
from xpra.util.gobject import no_arg_signal
from xpra.gtk.util import get_default_root_window
from xpra.gtk.window import set_visual
from xpra.gtk.pixbuf import get_pixbuf_from_data
from xpra.common import (
    MoveResize, force_size_constraint, noop,
    MOVERESIZE_DIRECTION_STRING, SOURCE_INDICATION_STRING, BACKWARDS_COMPATIBLE,
)
from xpra.net.common import PacketElement
from xpra.client.gui.window_base import ClientWindowBase
from xpra.client.gtk3.window.common import (
    use_x11_bindings, is_awt, is_popup, mask_buttons,
    WINDOW_NAME_TO_HINT, ALL_WINDOW_TYPES, BUTTON_MASK,
)
from xpra.platform.gui import (
    set_fullscreen_monitors, set_shaded,
    add_window_hooks, remove_window_hooks,
)
from xpra.log import Logger

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
Gio = gi_import("Gio")

focuslog = Logger("focus")
log = Logger("window")
iconlog = Logger("icon")
metalog = Logger("metadata")
statelog = Logger("state")
eventslog = Logger("events")
geomlog = Logger("geometry")
alphalog = Logger("alpha")

HAS_X11_BINDINGS = False

prop_get = None
prop_set = prop_del = noop
X11Window = X11Core = None


if use_x11_bindings():
    try:
        from xpra.x11.error import xlog, verify_sync
        from xpra.x11.prop import prop_get, prop_set, prop_del
        from xpra.x11.bindings.core import X11CoreBindings, set_context_check, constants, get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings

        X11Window = X11WindowBindings()
        X11Core = X11CoreBindings()
    except ImportError as x11e:
        log("x11 bindings", exc_info=True)
        # gtk util should have already logged a detailed warning
        log("cannot import the X11 bindings:")
        log(" %s", x11e)
    except RuntimeError as e:
        log("x11", exc_info=True)
        log.error(f"Error loading X11 bindings: {e}")
    else:
        set_context_check(verify_sync)
        HAS_X11_BINDINGS = True

        SubstructureNotifyMask = constants["SubstructureNotifyMask"]
        SubstructureRedirectMask = constants["SubstructureRedirectMask"]

AWT_DIALOG_WORKAROUND = envbool("XPRA_AWT_DIALOG_WORKAROUND", WIN32)
BREAK_MOVERESIZE = os.environ.get("XPRA_BREAK_MOVERESIZE", "Escape").split(",")
MOVERESIZE_GUESS_BUTTON = envbool("XPRA_MOVERESIZE_GUESS_BUTTON", True)
MOVERESIZE_X11 = envbool("XPRA_MOVERESIZE_X11", POSIX and not OSX)
MOVERESIZE_GDK = envbool("XPRA_MOVERESIZE_GDK", True)
DISPLAY_HAS_SCREEN_INDEX = POSIX and os.environ.get("DISPLAY", "").split(":")[-1].find(".") >= 0
CLAMP_WINDOW_TO_SCREEN = envbool("XPRA_CLAMP_WINDOW_TO_SCREEN", True)
REPAINT_MAXIMIZED = envint("XPRA_REPAINT_MAXIMIZED", 0)
REFRESH_MAXIMIZED = envbool("XPRA_REFRESH_MAXIMIZED", True)
ICONIFY_LATENCY = envint("XPRA_ICONIFY_LATENCY", 150)

WINDOW_OVERFLOW_TOP = envbool("XPRA_WINDOW_OVERFLOW_TOP", False)
AWT_RECENTER = envbool("XPRA_AWT_RECENTER", True)


GDK_MOVERESIZE_MAP = {int(d): we for d, we in {
    MoveResize.SIZE_TOPLEFT: Gdk.WindowEdge.NORTH_WEST,
    MoveResize.SIZE_TOP: Gdk.WindowEdge.NORTH,
    MoveResize.SIZE_TOPRIGHT: Gdk.WindowEdge.NORTH_EAST,
    MoveResize.SIZE_RIGHT: Gdk.WindowEdge.EAST,
    MoveResize.SIZE_BOTTOMRIGHT: Gdk.WindowEdge.SOUTH_EAST,
    MoveResize.SIZE_BOTTOM: Gdk.WindowEdge.SOUTH,
    MoveResize.SIZE_BOTTOMLEFT: Gdk.WindowEdge.SOUTH_WEST,
    MoveResize.SIZE_LEFT: Gdk.WindowEdge.WEST,
    # MOVERESIZE_SIZE_KEYBOARD,
}.items()}


def get_follow_window_types() -> Sequence[Gdk.WindowTypeHint]:
    types_strs: list[str] = os.environ.get(
        "XPRA_FOLLOW_WINDOW_TYPES",
        "DIALOG,MENU,TOOLBAR,DROPDOWN_MENU,POPUP_MENU,TOOLTIP,COMBO,DND"
    ).upper().split(",")
    if "*" in types_strs or "ALL" in types_strs:
        return ALL_WINDOW_TYPES
    types: list[Gdk.WindowTypeHint] = []
    for v in types_strs:
        hint = WINDOW_NAME_TO_HINT.get(v, "")
        if hint:
            types.append(hint)
        else:
            log.warn(f"Warning: invalid follow window type specified {v!r}")
    return tuple(types)


FOLLOW_WINDOW_TYPES = get_follow_window_types()


# noinspection PyTestUnpassedFixture
def noop_destroy() -> None:
    log.warn("Warning: window destroy called twice!")


class GTKClientWindowBase(ClientWindowBase, Gtk.Window):
    __gsignals__ = {
        "state-updated": no_arg_signal,
    }

    # maximum size of the actual window:
    MAX_VIEWPORT_DIMS = 16 * 1024, 16 * 1024
    # maximum size of the backing pixel buffer:
    MAX_BACKING_DIMS = 16 * 1024, 16 * 1024

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.init_max_window_size()
        if self._override_redirect or is_popup(metadata):
            window_type = Gtk.WindowType.POPUP
        else:
            window_type = Gtk.WindowType.TOPLEVEL
        self.on_realize_cb = {}
        Gtk.Window.__init__(self, type=window_type)
        self.set_app_paintable(True)
        self.init_drawing_area()
        self.set_decorated(self._is_decorated(metadata))
        self._window_state = {}
        self._resize_counter = 0
        self._current_frame_extents = None
        self._monitor = None
        self._frozen: bool = False
        self._ondeiconify: list[Callable] = []
        self._follow = None
        self._follow_handler = 0
        self._follow_position = None
        self._follow_configure = None
        self.window_state_timer: int = 0
        self.send_iconify_timer: int = 0
        self.remove_pointer_overlay_timer: int = 0
        self.show_pointer_overlay_timer: int = 0
        self.moveresize_timer: int = 0
        self.moveresize_event = None
        # only set this initially:
        # (so the server can't make us kill just any pid!)
        watcher_pid = metadata.intget("watcher-pid", 0)
        if watcher_pid and HAS_X11_BINDINGS:
            def set_watcher_pid() -> None:
                log("using watcher pid=%i for wid=%#x", watcher_pid, self.wid)
                self.do_set_x11_property("_NET_WM_PID", "u32", watcher_pid)
            self.when_realized("watcher", set_watcher_pid)
        # add platform hooks
        self.connect_after("realize", self.on_realize)
        self.connect("unrealize", self.on_unrealize)
        self.connect("key-press-event", self.key_may_break_moveresize)
        self.add_events(self.get_window_event_mask())
        ClientWindowBase.init_window(self, client, metadata, client_props)

    def init_drawing_area(self) -> None:
        widget = Gtk.DrawingArea()
        widget.set_app_paintable(True)
        widget.set_size_request(*self._size)
        widget.show()
        self.drawing_area = widget
        self.init_widget_events(widget)
        self.add(widget)

    def repaint(self, x: int, y: int, w: int, h: int) -> None:
        if OSX:
            self.queue_draw_area(x, y, w, h)
            return
        widget = self.drawing_area
        # log("repaint%s widget=%s", (x, y, w, h), widget)
        if widget:
            widget.queue_draw_area(x, y, w, h)

    def get_window_event_mask(self) -> Gdk.EventMask:
        return Gdk.EventMask.STRUCTURE_MASK | Gdk.EventMask.PROPERTY_CHANGE_MASK

    def init_widget_events(self, widget) -> None:
        widget.add_events(self.get_window_event_mask())

        def motion(_w, event) -> bool:
            if self.moveresize_event:
                self.motion_moveresize(event)
            # must return False so the other handlers will run
            # ie: the `PointerWindow` also uses this signal
            return False

        widget.connect("motion-notify-event", motion)

        def configure_event(_w, event) -> bool:
            geomlog("widget configure_event: new size=%ix%i", event.width, event.height)
            return True

        widget.connect("configure-event", configure_event)
        widget.connect("draw", self.draw_widget)

    def draw_widget(self, widget, context) -> bool:
        raise NotImplementedError()

    def get_drawing_area_geometry(self) -> tuple[int, int, int, int]:
        raise NotImplementedError()

    def init_max_window_size(self) -> None:
        """ used by GL windows to enforce a hard limit on window sizes """
        saved_mws = self.max_window_size

        def clamp_to(maxw: int, maxh: int):
            # don't bother if the new limit is greater than 16k:
            if maxw >= 16 * 1024 and maxh >= 16 * 1024:
                return
            # only take into account the current max-window-size if non-zero:
            mww, mwh = self.max_window_size
            if mww > 0:
                maxw = min(mww, maxw)
            if mwh > 0:
                maxh = min(mwh, maxh)
            self.max_window_size = maxw, maxh

        # viewport is easy, measured in window pixels:
        clamp_to(*self.MAX_VIEWPORT_DIMS)
        # backing dimensions are harder,
        # we have to take scaling into account (if any):
        clamp_to(*self.sp(*self.MAX_BACKING_DIMS))
        if self.max_window_size != saved_mws:
            log("init_max_window_size(..) max-window-size changed from %s to %s",
                saved_mws, self.max_window_size)
            log(" because of max viewport dims %s and max backing dims %s",
                self.MAX_VIEWPORT_DIMS, self.MAX_BACKING_DIMS)

    def _is_decorated(self, metadata: typedict) -> bool:
        # decide if the window type is POPUP or NORMAL
        # (show window decorations or not)
        if self._override_redirect:
            return False
        return metadata.boolget("decorations", True)

    def set_decorated(self, decorated: bool) -> None:
        was_decorated = self.get_decorated()
        if self._fullscreen and was_decorated and not decorated:
            # fullscreen windows aren't decorated anyway!
            # calling set_decorated(False) would cause it to get unmapped! (why?)
            pass
        else:
            Gtk.Window.set_decorated(self, decorated)
        if WIN32:
            # workaround for new window offsets:
            # keep the window contents where they were and adjust the frame
            # this generates a configure event which ensures the server has the correct window position
            wfs = self._client.get_window_frame_sizes()
            if wfs and decorated and not was_decorated:
                geomlog("set_decorated(%s) re-adjusting window location using %s", decorated, wfs)
                normal = wfs.get("normal")
                fixed = wfs.get("fixed")
                if normal and fixed:
                    nx, ny = normal
                    fx, fy = fixed
                    x, y = self.get_position()
                    Gtk.Window.move(self, max(0, x - nx + fx), max(0, y - ny + fy))

    def setup_window(self, *args) -> None:
        log("setup_window%s OR=%s", args, self._override_redirect)
        self.set_alpha()

        self.connect("property-notify-event", self.property_changed)
        self.connect("window-state-event", self.window_state_updated)

        # this will create the backing:
        ClientWindowBase.setup_window(self, *args)

        # try to honour the initial position
        geomlog("setup_window() position=%s, set_initial_position=%s, OR=%s, decorated=%s",
                self._pos, self._set_initial_position, self.is_OR(), self.get_decorated())
        # honour "set-initial-position"
        if self._set_initial_position or self.is_OR():
            self.set_initial_position(self._requested_position or self._pos)
        self.set_default_size(*self._size)

    def set_initial_position(self, pos) -> None:
        x, y = self.adjusted_position(*pos)
        w, h = self._size
        if self.is_OR():
            # make sure OR windows are mapped on screen
            if self._client._current_screen_sizes:
                self.window_offset = self.calculate_window_offset(x, y, w, h)
                geomlog("OR offsets=%s", self.window_offset)
                if self.window_offset:
                    x += self.window_offset[0]
                    y += self.window_offset[1]
        elif self.get_decorated():
            # try to adjust for window frame size if we can figure it out:
            # Note: we cannot just call self.get_window_frame_size() here because
            # the window is not realized yet, and it may take a while for the window manager
            # to set the frame-extents property anyway
            wfs = self._client.get_window_frame_sizes()
            if wfs:
                geomlog("setup_window() window frame sizes=%s", wfs)
                v = wfs.get("offset")
                if v:
                    dx, dy = v
                    x = max(32 - w, x - dx)
                    y = max(32 - h, y - dy)
                    self._pos = x, y
                    geomlog("setup_window() adjusted initial position=%s", self._pos)
        self.move(x, y)

    def finalize_window(self) -> None:
        if not self.is_tray():
            self.setup_following()

    def setup_following(self) -> None:
        # find a parent window we should follow when it moves:
        def find(attr: str):
            return self._client.find_window(self._metadata, attr)

        follow = find("transient-for") or find("parent")
        log("setup_following() follow=%s", follow)
        if not follow or not isinstance(follow, Gtk.Window):
            return
        type_hint = self.get_type_hint()
        log("setup_following() type_hint=%s, FOLLOW_WINDOW_TYPES=%s", type_hint, FOLLOW_WINDOW_TYPES)
        if not self._override_redirect and type_hint not in FOLLOW_WINDOW_TYPES:
            return

        def follow_configure_event(window, event) -> bool:
            follow = self._follow
            rp = self._follow_position
            log("follow_configure_event(%s, %s) follow=%s, relative position=%s",
                window, event, follow, rp)
            if not follow or not rp:
                return False
            fpos = getattr(follow, "_pos", None)
            log("follow_configure_event: %s moved to %s", follow, fpos)
            if not fpos:
                return False
            fx, fy = fpos
            rx, ry = rp
            x, y = self.get_position()
            newx, newy = fx + follow.sx(rx), fy + follow.sy(ry)
            log("follow_configure_event: new position from %s: %s", self._pos, (newx, newy))
            if newx != x or newy != y:
                # don't update the relative position on the next configure event,
                # since we're generating it
                self._follow_configure = monotonic(), (newx, newy)
                self.move(newx, newy)
            return True

        self.cancel_follow_handler()
        self._follow = follow

        def follow_unmapped(window) -> None:
            log("follow_unmapped(%s)", window)
            self._follow = None
            self.cancel_follow_handler()

        follow.connect("unmap", follow_unmapped)
        self._follow_handler = follow.connect_after("configure-event", follow_configure_event)
        log("setup_following() following %s", follow)

    def cancel_follow_handler(self) -> None:
        f = self._follow
        fh = self._follow_handler
        if f and fh:
            f.disconnect(fh)
            self._follow_handler = 0
            self._follow = None

    def new_backing(self, bw: int, bh: int):
        b = ClientWindowBase.new_backing(self, bw, bh)
        # soft dependency on `PointerWindow`:
        cursor_data = getattr(self, "cursor_data", ())
        if cursor_data:
            # call via idle_add so that the backing has time to be realized too:
            self.when_realized("cursor", GLib.idle_add, self._backing.set_cursor_data, cursor_data)
        return b

    def adjusted_position(self, ox, oy) -> tuple[int, int]:
        if AWT_RECENTER and is_awt(self._metadata):
            ss = self._client._current_screen_sizes
            if ss and len(ss) == 1:
                screen0 = ss[0]
                monitors = screen0[5]
                if monitors and len(monitors) > 1:
                    monitor = monitors[0]
                    mw = monitor[3]
                    mh = monitor[4]
                    w, h = self._size
                    # adjust for window centering on monitor instead of screen java
                    screen = self.get_screen()
                    sw = screen.get_width()
                    sh = screen.get_height()
                    # re-center on first monitor if the window is within
                    # tolerance of the center of the screen:
                    tolerance = 10
                    # center of the window:
                    cx = ox + w // 2
                    cy = oy + h // 2
                    if abs(sw // 2 - cx) <= tolerance:
                        x = mw // 2 - w // 2
                    else:
                        x = ox
                    if abs(sh // 2 - cy) <= tolerance:
                        y = mh // 2 - h // 2
                    else:
                        y = oy
                    geomlog("adjusted_position(%i, %i)=%i, %i", ox, oy, x, y)
                    return x, y
        return ox, oy

    def calculate_window_offset(self, wx: int, wy: int, ww: int, wh: int) -> tuple[int, int] | None:
        ss = self._client._current_screen_sizes
        if not ss:
            return None
        if len(ss) != 1:
            geomlog("cannot handle more than one screen for OR offset")
            return None
        screen0 = ss[0]
        monitors = screen0[5]
        if not monitors:
            geomlog("screen %s lacks monitors information: %s", screen0)
            return None
        try:
            from xpra.util.rectangle import rectangle
        except ImportError as e:
            geomlog("cannot calculate offset: %s", e)
            return None
        wrect = rectangle(wx, wy, ww, wh)
        rects = [wrect]
        pixels_in_monitor = {}
        for i, monitor in enumerate(monitors):
            plug_name, x, y, w, h = monitor[:5]
            new_rects = []
            for rect in rects:
                new_rects += rect.subtract(x, y, w, h)
            geomlog("after removing areas visible on %s from %s: %s", plug_name, rects, new_rects)
            rects = new_rects
            if not rects:
                # the whole window is visible
                return None
            # keep track of how many pixels would be on this monitor:
            inter = wrect.intersection(x, y, w, h)
            if inter:
                pixels_in_monitor[inter.width * inter.height] = i
        # if we're here, then some of the window would land on an area
        # not show on any monitors
        # choose the monitor that had most of the pixels and make it fit:
        geomlog("pixels in monitor=%s", pixels_in_monitor)
        if not pixels_in_monitor:
            i = 0
        else:
            best = max(pixels_in_monitor.keys())
            i = pixels_in_monitor[best]
        monitor = monitors[i]
        plug_name, x, y, w, h = monitor[:5]
        geomlog("calculating OR offset for monitor %i: %s", i, plug_name)
        if ww > w or wh >= h:
            geomlog("window %ix%i is bigger than the monitor %i: %s %ix%i, not adjusting it",
                    ww, wh, i, plug_name, w, h)
            return None
        dx = 0
        dy = 0
        if wx < x:
            dx = x - wx
        elif wx + ww > x + w:
            dx = (x + w) - (wx + ww)
        if wy < y:
            dy = y - wy
        elif wy + wh > y + h:
            dy = (y + h) - (wy + wh)
        assert dx != 0 or dy != 0
        geomlog("calculate_window_offset%s=%s", (wx, wy, ww, wh), (dx, dy))
        return dx, dy

    def when_realized(self, identifier: str, callback: Callable, *args) -> None:
        if self.get_realized():
            callback(*args)
        else:
            self.on_realize_cb[identifier] = callback, args

    def on_realize(self, widget) -> None:
        eventslog("on_realize(%s) gdk window=%s", widget, self.get_window())
        add_window_hooks(self)
        cb = self.on_realize_cb
        self.on_realize_cb = {}
        for callback, args in cb.values():
            with eventslog.trap_error(f"Error on realize callback {callback} for window {self.wid:#x}"):
                callback(*args)
        if HAS_X11_BINDINGS:
            # request frame extents if the window manager supports it
            self._client.request_frame_extents(self)
        if self.group_leader:
            self.get_window().set_group(self.group_leader)

    def on_unrealize(self, widget) -> None:
        eventslog("on_unrealize(%s)", widget)
        self.cancel_follow_handler()
        remove_window_hooks(self)

    def set_alpha(self) -> None:
        # try to enable alpha on this window if needed,
        # and if the backing class can support it:
        bc = self.get_backing_class()
        alphalog("set_alpha() has_alpha=%s, %s.HAS_ALPHA=%s, realized=%s",
                 self._has_alpha, bc, bc.HAS_ALPHA, self.get_realized())
        # by default, only RGB (no transparency):
        # rgb_formats = tuple(BACKING_CLASS.RGB_MODES)
        self._client_properties["encodings.rgb_formats"] = ["RGB", "RGBX"]
        # only set the visual if we need to enable alpha:
        # (breaks the headerbar otherwise!)
        if not self.get_realized() and self._has_alpha:
            if set_visual(self, True):
                if self._has_alpha:
                    self._client_properties["encodings.rgb_formats"] = ["RGBA", "RGB", "RGBX"]
                self._window_alpha = self._has_alpha
            else:
                alphalog("failed to set RGBA visual")
                self._has_alpha = False
                self._client_properties["encoding.transparency"] = False
        if not self._has_alpha or not bc.HAS_ALPHA:
            self._client_properties["encoding.transparency"] = False

    def send_control_refresh(self, suspend_resume: bool, client_properties=None, refresh=False) -> None:
        log("send_control_refresh%s", (suspend_resume, client_properties, refresh))
        # we can tell the server using a "buffer-refresh" packet instead
        # and also take care of tweaking the batch config
        options = {"refresh-now": refresh}  # no need to refresh it
        self._client.control_refresh(self.wid, suspend_resume,
                                     refresh=refresh, options=options, client_properties=client_properties)

    def freeze(self) -> None:
        # the OpenGL subclasses override this method to also free their GL context
        self._frozen = True
        self.iconify()

    def unfreeze(self) -> None:
        if not self._frozen or not self._iconified:
            return
        log("unfreeze() wid=%#x, frozen=%s, iconified=%s", self.wid, self._frozen, self._iconified)
        if not self._frozen or not self._iconified:
            # has been deiconified already
            return
        self._frozen = False
        self.deiconify()

    def deiconify(self) -> None:
        functions = tuple(self._ondeiconify)
        self._ondeiconify = []
        for function in functions:
            try:
                function()
            except Exception as e:
                log("deiconify()", exc_info=True)
                log.error(f"Error calling {function} on {self} during deiconification:")
                log.estr(e)
        Gtk.Window.deiconify(self)

    def window_state_updated(self, widget, event) -> None:
        statelog("%s.window_state_updated(%s, %s) changed_mask=%s, new_window_state=%s",
                 self, widget, repr(event), event.changed_mask, event.new_window_state)
        state_updates: dict[str, bool] = {}
        for flag in ("fullscreen", "above", "below", "sticky", "iconified", "maximized", "focused"):
            wstate = getattr(Gdk.WindowState, flag.upper())  # ie: Gdk.WindowState.FULLSCREEN
            if event.changed_mask & wstate:
                state_updates[flag] = bool(event.new_window_state & wstate)
        self.update_window_state(state_updates)

    def update_window_state(self, state_updates: dict[str, bool]):
        if self._client.readonly:
            log("update_window_state(%s) ignored in readonly mode", state_updates)
            return
        if state_updates.get("maximized") is False or state_updates.get("fullscreen") is False:
            # if we unfullscreen or unmaximize, re-calculate offsets if we have any:
            w, h = self._backing.render_size
            ww, wh = self.get_size()
            log("update_window_state(%s) unmax or unfullscreen", state_updates)
            log("window_offset=%s, backing render_size=%s, window size=%s",
                self.window_offset, (w, h), (ww, wh))
            if self._backing.offsets != (0, 0, 0, 0):
                self.center_backing(w, h)
                self.repaint(0, 0, ww, wh)
        # decide if this is really an update by comparing with our local state vars:
        # (could just be a notification of a state change we already know about)
        actual_updates: dict[str, bool] = {}
        for state, value in state_updates.items():
            var = "_" + state.replace("-", "_")  # ie: "skip-pager" -> "_skip_pager"
            cur = getattr(self, var)  # ie: self._maximized
            if cur != value:
                setattr(self, var, value)  # ie: self._maximized = True
                actual_updates[state] = value
                statelog("%s=%s (was %s)", var, value, cur)
        server_updates: dict[str, bool] = {k: v for k, v in actual_updates.items()
                                           if k in self._client.server_window_states}
        # iconification is handled a bit differently...
        iconified = server_updates.pop("iconified", None)
        if iconified is not None:
            statelog("iconified=%s", iconified)
            # handle iconification as map events:
            if iconified:
                # usually means it is unmapped
                self._unfocus()
                if not self._override_redirect and not self.send_iconify_timer:
                    # tell server, but wait a bit to try to prevent races:
                    self.schedule_send_iconify()
            else:
                self.cancel_send_iconifiy_timer()
                self._frozen = False
                self.process_map_event()
        statelog("window_state_updated(..) state updates: %s, actual updates: %s, server updates: %s",
                 state_updates, actual_updates, server_updates)
        if "maximized" in state_updates:
            if REPAINT_MAXIMIZED > 0:
                def repaint_maximized() -> None:
                    if not self._backing:
                        return
                    ww, wh = self.get_size()
                    self.repaint(0, 0, ww, wh)

                GLib.timeout_add(REPAINT_MAXIMIZED, repaint_maximized)
            if REFRESH_MAXIMIZED:
                self._client.send_refresh(self.wid)

        self._window_state.update(server_updates)
        self.emit("state-updated")
        # if we have state updates, send them back to the server using a configure window packet:
        if self._window_state and not self.window_state_timer:
            self.window_state_timer = GLib.timeout_add(25, self.send_updated_window_state)

    def send_updated_window_state(self) -> None:
        statelog(f"sending configure event with window state={self._window_state}")
        self.window_state_timer = 0
        if self._window_state and self.get_window():
            self.send_configure_event(True)

    def cancel_window_state_timer(self) -> None:
        wst = self.window_state_timer
        if wst:
            self.window_state_timer = 0
            GLib.source_remove(wst)

    def schedule_send_iconify(self) -> None:
        # calculate a good delay to prevent races causing minimize/unminimize loops:
        if self._client.readonly:
            return
        delay = ICONIFY_LATENCY
        if delay > 0:
            spl = tuple(self._client.server_ping_latency)
            if spl:
                worst = max(x[1] for x in self._client.server_ping_latency)
                delay += int(1000 * worst)
                delay = min(1000, delay)
        statelog("telling server about iconification with %sms delay", delay)
        self.send_iconify_timer = GLib.timeout_add(delay, self.send_iconify)

    def send_iconify(self) -> None:
        self.send_iconify_timer = 0
        if self._iconified:
            self.send("unmap-window", self.wid, True, self._window_state)
            # we have sent the window-state already:
            self._window_state = {}
            self.cancel_window_state_timer()

    def cancel_send_iconifiy_timer(self) -> None:
        sit = self.send_iconify_timer
        if sit:
            self.send_iconify_timer = 0
            GLib.source_remove(sit)

    def set_command(self, command) -> None:
        self.set_x11_property("WM_COMMAND", "latin1", command)

    def set_x11_property(self, prop_name: str, dtype: str, value) -> None:
        if not HAS_X11_BINDINGS:
            return
        self.when_realized("x11-prop-%s" % prop_name, self.do_set_x11_property, prop_name, dtype, value)

    def do_set_x11_property(self, prop_name: str, dtype: str, value) -> None:
        xid = self.get_window().get_xid()
        metalog(f"do_set_x11_property({prop_name!r}, {dtype!r}, {value!r}) xid={xid}")
        if dtype == "latin1":
            value = bytestostr(value)
        if isinstance(value, (list, tuple)) and not isinstance(dtype, (list, tuple)):
            dtype = (dtype,)
        if not dtype and not value:
            # remove prop
            prop_del(xid, prop_name)
        else:
            prop_set(xid, prop_name, dtype, value)

    def set_class_instance(self, wmclass_name, wmclass_class) -> None:
        if not self.get_realized():
            # Warning: window managers may ignore the icons we try to set
            # if the wm_class value is set and matches something somewhere undocumented
            # (if the default is used, you cannot override the window icon)
            ignorewarnings(self.set_wmclass, wmclass_name, wmclass_class)
        elif HAS_X11_BINDINGS:
            xid = self.get_window().get_xid()
            with xlog:
                X11Window.setClassHint(xid, wmclass_class, wmclass_name)
                log("XSetClassHint(%s, %s) done", wmclass_class, wmclass_name)

    def set_bypass_compositor(self, v) -> None:
        if v not in (0, 1, 2):
            v = 0
        self.set_x11_property("_NET_WM_BYPASS_COMPOSITOR", "u32", v)

    def set_strut(self, strut: dict) -> None:
        if not HAS_X11_BINDINGS:
            return
        log("strut=%s", strut)
        d = typedict(strut)
        values: list[int] = []
        for x in ("left", "right", "top", "bottom"):
            v = d.intget(x, 0)
            # handle scaling:
            if x in ("left", "right"):
                v = self.sx(v)
            else:
                v = self.sy(v)
            values.append(v)
        has_partial = False
        for x in (
                "left_start_y", "left_end_y",
                "right_start_y", "right_end_y",
                "top_start_x", "top_end_x",
                "bottom_start_x", "bottom_end_x",
        ):
            if x in d:
                has_partial = True
            v = d.intget(x, 0)
            if x.find("_x"):
                v = self.sx(v)
            elif x.find("_y"):
                v = self.sy(v)
            values.append(v)
        log("setting strut=%s, has partial=%s", values, has_partial)
        if has_partial:
            self.set_x11_property("_NET_WM_STRUT_PARTIAL", "u32", values)
        self.set_x11_property("_NET_WM_STRUT", "u32", values[:4])

    def set_window_type(self, window_types) -> None:
        if self.get_mapped():
            # should only be set before mapping the window, as per the Gtk docs:
            # "This function should be called before the window becomes visible."
            return
        hints = 0
        for window_type in window_types:
            # win32 workaround:
            if AWT_DIALOG_WORKAROUND and window_type == "DIALOG" and self._metadata.boolget("skip-taskbar"):
                wm_class = self._metadata.strtupleget("class-instance")
                if wm_class and len(wm_class) == 2 and wm_class[0] and wm_class[0].startswith("sun-awt-X11"):
                    # replace "DIALOG" with "NORMAL":
                    if "NORMAL" in window_types:
                        continue
                    window_type = "NORMAL"
            hint = WINDOW_NAME_TO_HINT.get(window_type, 0)
            if hint:
                hints |= hint
            else:
                log("ignoring unknown window type hint: %s", window_type)
        log("set_window_type(%s) hints=%s", window_types, hints)
        if hints:
            self.set_type_hint(hints)

    def set_modal(self, modal: bool) -> None:
        # setting the window as modal would prevent
        # all other windows we manage from receiving input
        # including other unrelated applications
        # what we want is "window-modal"
        # so we can turn this off using the "modal_windows" feature,
        # from the command line and the system tray:
        mw = self._client.modal_windows
        log("set_modal(%s) modal_windows=%s", modal, mw)
        Gtk.Window.set_modal(self, modal and mw)

    def set_fullscreen_monitors(self, fsm) -> None:
        # platform specific code:
        log("set_fullscreen_monitors(%s)", fsm)

        def do_set_fullscreen_monitors() -> None:
            set_fullscreen_monitors(self.get_window(), fsm)

        self.when_realized("fullscreen-monitors", do_set_fullscreen_monitors)

    def set_shaded(self, shaded: bool) -> None:
        if self._shaded == shaded:
            return
        # platform specific code:
        log("set_shaded(%s)", shaded)

        def do_set_shaded() -> None:
            self._shaded = shaded
            set_shaded(self.get_window(), shaded)

        self.when_realized("shaded", do_set_shaded)

    def restack(self, other_window, above: int = 0) -> None:
        log("restack(%s, %s)", other_window, above)

        def do_restack() -> None:
            self.get_window().restack(other_window, above)

        self.when_realized("restack", do_restack)

    def set_fullscreen(self, fullscreen: bool) -> None:
        statelog("%s.set_fullscreen(%s)", self, fullscreen)

        def do_set_fullscreen() -> None:
            if self._fullscreen is None or self._fullscreen != fullscreen:
                self._fullscreen = fullscreen
            if fullscreen:
                # we may need to temporarily remove the max-window-size restrictions
                # to be able to honour the fullscreen request:
                w, h = self.max_window_size
                if w > 0 and h > 0:
                    self.set_size_constraints(self.size_constraints, (0, 0))
                self.fullscreen()
            else:
                self.unfullscreen()
                # re-apply size restrictions:
                w, h = self.max_window_size
                if w > 0 and h > 0:
                    self.set_size_constraints(self.size_constraints, self.max_window_size)

        self.when_realized("fullscreen", do_set_fullscreen)

    def set_focused(self, focused: bool) -> None:
        if not HAS_X11_BINDINGS:
            return
        from xpra.platform.posix.gui import _send_client_message
        from xpra.x11.common import _NET_WM_STATE_ADD

        def do_focused() -> None:
            with xlog:
                _send_client_message(self.get_window(), "_NET_WM_STATE", _NET_WM_STATE_ADD, "_NET_WM_STATE_FOCUSED")
        self.when_realized("focused", do_focused)

    def set_opaque_region(self, rectangles=()):
        if self._opaque_region == rectangles:
            return
        self._opaque_region = rectangles
        # gtk can only set a single region!
        # noinspection PyArgumentList
        r = Region()
        for rect in rectangles:
            # "opaque-region", aka "_NET_WM_OPAQUE_REGION" is meant to use unsigned values
            # but some applications use 0xffffffff, so we have to validate it:
            rvalues = tuple((int(v) if v < 2**32 else -1) for v in rect)
            rectint = RectangleInt(*self.srect(*rvalues))
            r.union(Region(rectint))

        def do_set_region() -> None:
            log("set_opaque_region(%s)", r)
            try:
                self.get_window().set_opaque_region(r)
            except KeyError as e:
                if first_time("region-KeyError"):
                    log.warn("Warning: cannot set opaque region %r", r)
                    log.warn(" a package may be missing")
                    log.warn(f" {e}")

        self.when_realized("set-opaque-region", do_set_region)

    def set_locale(self, locale: str) -> None:
        self.set_x11_property("WM_LOCALE_NAME", "latin1", locale)

    def set_xid(self, xid: str) -> None:
        if xid.startswith("0x") and xid.endswith("L"):
            xid = xid[:-1]
        try:
            iid = int(xid, 16)
        except Exception as e:
            log("%s.set_xid(%s) error parsing/setting xid: %s", self, xid, e)
            return
        self.set_x11_property("XID", "u32", iid)

    def xget_u32_property(self, target, name: str, default_value=0) -> int:
        if prop_get:
            v = prop_get(target.get_xid(), name, "u32", ignore_errors=True)
            log("%s.xget_u32_property(%s, %s, %s)=%s", self, target, name, default_value, v)
            if isinstance(v, int):
                return v
        return default_value

    def property_changed(self, widget, event) -> None:
        atom = str(event.atom)
        statelog("property_changed(%s, %s) : %s", widget, event, atom)
        # the remaining handlers need `prop_get`:
        if not prop_get:
            return
        xid = self.get_window().get_xid()
        if atom == "_NET_FRAME_EXTENTS":
            v = prop_get(xid, "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
            statelog("_NET_FRAME_EXTENTS: %s", v)
            if v:
                if v == self._current_frame_extents:
                    # unchanged
                    return
                if not self._been_mapped:
                    # map event will take care of sending it
                    return
                if self.is_OR() or self.is_tray():
                    # we can't do it: the server can't handle configure packets for OR windows!
                    return
                if not self._client.server_window_frame_extents:
                    # can't send cheap "skip-geometry" packets or frame-extents feature not supported:
                    return
                # tell server about new value:
                self._current_frame_extents = v
                statelog("sending configure event to update _NET_FRAME_EXTENTS to %s", v)
                self._window_state["frame"] = self.crect(*v)
                self.send_configure_event(True)
            return
        if atom == "XKLAVIER_STATE":
            # unused for now, but log it:
            xklavier_state = prop_get(xid, "XKLAVIER_STATE", ["integer"], ignore_errors=False)
            log("XKLAVIER_STATE=%s", [hex(x) for x in (xklavier_state or [])])
            return
        if atom == "_NET_WM_STATE":
            wm_state_atoms = prop_get(xid, "_NET_WM_STATE", ["atom"], ignore_errors=False)
            # code mostly duplicated from xpra/x11/gtk/window.py:
            WM_STATE_NAME = {
                "fullscreen": ("_NET_WM_STATE_FULLSCREEN",),
                "maximized": ("_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"),
                "shaded": ("_NET_WM_STATE_SHADED",),
                "sticky": ("_NET_WM_STATE_STICKY",),
                "skip-pager": ("_NET_WM_STATE_SKIP_PAGER",),
                "skip-taskbar": ("_NET_WM_STATE_SKIP_TASKBAR",),
                "above": ("_NET_WM_STATE_ABOVE",),
                "below": ("_NET_WM_STATE_BELOW",),
                "focused": ("_NET_WM_STATE_FOCUSED",),
            }
            state_atoms = set(wm_state_atoms or [])
            state_updates = {}
            for state, atoms in WM_STATE_NAME.items():
                var = "_" + state.replace("-", "_")  # ie: "skip-pager" -> "_skip_pager"
                cur_state = getattr(self, var)
                wm_state_is_set = set(atoms).issubset(state_atoms)
                if wm_state_is_set and not cur_state:
                    state_updates[state] = True
                elif cur_state and not wm_state_is_set:
                    state_updates[state] = False
            log("_NET_WM_STATE=%s, state_updates=%s", wm_state_atoms, state_updates)
            if state_updates:
                self.update_window_state(state_updates)

    def toggle_fullscreen(self) -> None:
        geomlog("toggle_fullscreen()")
        if self._fullscreen:
            self.unfullscreen()
        else:
            self.fullscreen()

    def motion_moveresize(self, event) -> None:
        x_root, y_root, direction, button, start_buttons, wx, wy, ww, wh = self.moveresize_event
        dirstr = MOVERESIZE_DIRECTION_STRING.get(direction, direction)
        buttons = mask_buttons(event.state)
        geomlog("motion_moveresize(%s) direction=%s, buttons=%s", event, dirstr, buttons)
        if start_buttons is None:
            # first time around, store the buttons
            start_buttons = buttons
            self.moveresize_event[4] = buttons
        if (button > 0 and button not in buttons) or (button == 0 and start_buttons != buttons):
            geomlog("%s for window button %i is no longer pressed (buttons=%s) cancelling moveresize",
                    dirstr, button, buttons)
            self.moveresize_event = None
            self.cancel_moveresize_timer()
        else:
            x = event.x_root
            y = event.y_root
            dx = x - x_root
            dy = y - y_root
            # clamp resizing using size hints,
            # or sane defaults: minimum of (1x1) and maximum of (2*15x2*25)
            minw = self.geometry_hints.get("min_width", 1)
            minh = self.geometry_hints.get("min_height", 1)
            maxw = self.geometry_hints.get("max_width", 2 ** 15)
            maxh = self.geometry_hints.get("max_height", 2 ** 15)
            geomlog("%s: min=%ix%i, max=%ix%i, window=%ix%i, delta=%ix%i",
                    dirstr, minw, minh, maxw, maxh, ww, wh, dx, dy)
            if direction in (MoveResize.SIZE_BOTTOMRIGHT, MoveResize.SIZE_BOTTOM, MoveResize.SIZE_BOTTOMLEFT):
                # height will be set to: wh+dy
                dy = max(minh - wh, dy)
                dy = min(maxh - wh, dy)
            elif direction in (MoveResize.SIZE_TOPRIGHT, MoveResize.SIZE_TOP, MoveResize.SIZE_TOPLEFT):
                # height will be set to: wh-dy
                dy = min(wh - minh, dy)
                dy = max(wh - maxh, dy)
            if direction in (MoveResize.SIZE_BOTTOMRIGHT, MoveResize.SIZE_RIGHT, MoveResize.SIZE_TOPRIGHT):
                # width will be set to: ww+dx
                dx = max(minw - ww, dx)
                dx = min(maxw - ww, dx)
            elif direction in (MoveResize.SIZE_BOTTOMLEFT, MoveResize.SIZE_LEFT, MoveResize.SIZE_TOPLEFT):
                # width will be set to: ww-dx
                dx = min(ww - minw, dx)
                dx = max(ww - maxw, dx)
            # calculate move + resize:
            if direction == MoveResize.MOVE:
                data = (wx + dx, wy + dy), None
            elif direction == MoveResize.SIZE_BOTTOMRIGHT:
                data = None, (ww + dx, wh + dy)
            elif direction == MoveResize.SIZE_BOTTOM:
                data = None, (ww, wh + dy)
            elif direction == MoveResize.SIZE_BOTTOMLEFT:
                data = (wx + dx, wy), (ww - dx, wh + dy)
            elif direction == MoveResize.SIZE_RIGHT:
                data = None, (ww + dx, wh)
            elif direction == MoveResize.SIZE_LEFT:
                data = (wx + dx, wy), (ww - dx, wh)
            elif direction == MoveResize.SIZE_TOPRIGHT:
                data = (wx, wy + dy), (ww + dx, wh - dy)
            elif direction == MoveResize.SIZE_TOP:
                data = (wx, wy + dy), (ww, wh - dy)
            elif direction == MoveResize.SIZE_TOPLEFT:
                data = (wx + dx, wy + dy), (ww - dx, wh - dy)
            else:
                # not handled yet!
                data = None
            geomlog("%s for window %ix%i: started at %s, now at %s, delta=%s, button=%s, buttons=%s, data=%s",
                    dirstr, ww, wh, (x_root, y_root), (x, y), (dx, dy), button, buttons, data)
            if data:
                # modifying the window is slower than moving the pointer,
                # do it via a timer to batch things together
                self.moveresize_data = data
                if self.moveresize_timer is None:
                    self.moveresize_timer = GLib.timeout_add(20, self.do_moveresize)

    def cancel_moveresize_timer(self) -> None:
        mrt = self.moveresize_timer
        geomlog("cancel_moveresize_timer() timer=%i", mrt)
        if mrt:
            self.moveresize_timer = 0
            GLib.source_remove(mrt)

    def do_moveresize(self) -> None:
        self.moveresize_timer = 0
        mrd = self.moveresize_data
        geomlog("do_moveresize() data=%s", mrd)
        if not mrd:
            return
        move, resize = mrd
        x = y = w = h = 0
        if move:
            x, y = int(move[0]), int(move[1])
        if resize:
            w, h = int(resize[0]), int(resize[1])
            if self._client.readonly:
                # change size-constraints first,
                # so the resize can be honoured:
                sc = typedict(force_size_constraint(w, h))
                self._metadata.update(sc)
                self.set_metadata(sc)
        if move and resize:
            self.get_window().move_resize(x, y, w, h)
        elif move:
            self.get_window().move(x, y)
        elif resize:
            self.get_window().resize(w, h)

    def initiate_moveresize(self, x_root: int, y_root: int, direction: int, button: int,
                            source_indication: int) -> None:
        geomlog("initiate_moveresize%s",
                (
                    x_root, y_root, MOVERESIZE_DIRECTION_STRING.get(direction, direction),
                    button, SOURCE_INDICATION_STRING.get(source_indication, source_indication)
                ))
        # the values we get are bogus!
        # x, y = x_root, y_root
        # use the current position instead:
        with IgnoreWarningsContext():
            p = self.get_root_window().get_pointer()[-3:]
        x, y, mask = p
        if MOVERESIZE_GUESS_BUTTON and button <= 0 and direction not in (
                MoveResize.MOVE_KEYBOARD, MoveResize.SIZE_KEYBOARD, MoveResize.CANCEL,
        ):
            # button seems to be missing!
            for bmask, bval in BUTTON_MASK.items():
                if bmask & mask:
                    button = bval
                    log(f"guessed {button=}")
                    break
        if MOVERESIZE_X11 and HAS_X11_BINDINGS:
            self.initiate_moveresize_x11(x, y, direction, button, source_indication)
        elif direction == MoveResize.CANCEL:
            self.moveresize_event = None
            self.moveresize_data = None
            self.cancel_moveresize_timer()
        elif MOVERESIZE_GDK:
            if direction in (MoveResize.MOVE, MoveResize.MOVE_KEYBOARD):
                self.begin_move_drag(button, x, y, 0)
            else:
                edge = GDK_MOVERESIZE_MAP.get(direction)
                geomlog("edge(%s)=%s", MOVERESIZE_DIRECTION_STRING.get(direction), edge)
                if direction is not None:
                    etime = Gtk.get_current_event_time()
                    self.begin_resize_drag(edge, button, x, y, etime)
        else:
            # handle it ourselves:
            # use window coordinates (which include decorations)
            wx, wy = self.get_window().get_root_origin()
            ww, wh = self.get_size()
            self.moveresize_event = [x_root, y_root, direction, button, None, wx, wy, ww, wh]
        poll = getattr(self, "start_button_polling", noop)
        poll()

    def initiate_moveresize_x11(self, x_root: int, y_root: int, direction: int,
                                button: int, source_indication: int) -> None:
        statelog("initiate_moveresize_x11%s",
                 (x_root, y_root, MOVERESIZE_DIRECTION_STRING.get(direction, direction),
                  button, SOURCE_INDICATION_STRING.get(source_indication, source_indication)))
        event_mask = SubstructureNotifyMask | SubstructureRedirectMask
        assert HAS_X11_BINDINGS
        xwin = self.get_window().get_xid()
        with xlog:
            root_xid = get_root_xid()
            X11Core.UngrabPointer()
            X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_MOVERESIZE",
                                        x_root, y_root, direction, button, source_indication)

    def apply_transient_for(self, wid: int) -> None:
        if wid == 0:
            def set_root_transient() -> None:
                # root is a gdk window, so we need to ensure we have one
                # backing our gtk window to be able to call set_transient_for on it
                log("%s.apply_transient_for(%#x) gdkwindow=%s, mapped=%s",
                    self, wid, self.get_window(), self.get_mapped())
                self.get_window().set_transient_for(get_default_root_window())

            self.when_realized("transient-for-root", set_root_transient)
        else:
            # gtk window is easier:
            window = self._client._id_to_window.get(wid)
            log("%s.apply_transient_for(%#x) window=%s", self, wid, window)
            if window and isinstance(window, Gtk.Window):
                self.set_transient_for(window)

    def do_map_event(self, event) -> None:
        log("%s.do_map_event(%s) OR=%s", self, event, self._override_redirect)
        Gtk.Window.do_map_event(self, event)
        if not self._override_redirect:
            # we can get a map event for an iconified window on win32:
            if self._iconified:
                self.deiconify()
            self.process_map_event()
        # use the drawing area to enforce the minimum size:
        # (as this also honoured correctly with CSD,
        # whereas set_geometry_hints is not..)
        minw, minh = self.size_constraints.intpair("minimum-size", (0, 0))
        w, h = self.sp(minw, minh)
        geomlog("do_map_event %s.set_size_request%s", self.drawing_area, (minw, minh))
        self.drawing_area.set_size_request(w, h)

    def get_map_client_properties(self) -> dict[str, Any]:
        return self._client_properties.copy()

    def process_map_event(self) -> None:
        x, y, w, h = self.get_drawing_area_geometry()
        state = self._window_state
        props = self.get_map_client_properties()
        self._client_properties = {}
        self._window_state = {}
        self.cancel_window_state_timer()
        if self._client.server_window_frame_extents and "frame" not in state:
            wfs = self.get_window_frame_size()
            if wfs and len(wfs) == 4:
                state["frame"] = self.crect(*wfs)
                self._current_frame_extents = wfs
        geomlog("map-window wid=%#x, geometry=%s, client props=%s, state=%s", self.wid, (x, y, w, h), props, state)
        sx, sy, sw, sh = self.cx(x), self.cy(y), self.cx(w), self.cy(h)
        if self._backing is None:
            # we may have cleared the backing, so we must re-create one:
            self._set_backing_size(w, h)
        self._been_mapped = True
        packet = ["map-window", self.wid, sx, sy, sw, sh, props, state]
        self.send(*packet)
        self._pos = (x, y)
        self._size = (w, h)
        self.update_relative_position()
        if not self._override_redirect:
            htf = self.has_toplevel_focus()
            focuslog("mapped: has-toplevel-focus=%s", htf)
            if htf:
                self._client.update_focus(self.wid, htf)

    def get_window_frame_size(self) -> Sequence[int]:
        frame = self._client.get_frame_extents(self).get("frame", ())
        if not frame:
            # default to global value we may have:
            wfs = self._client.get_window_frame_sizes()
            if wfs:
                frame = wfs.get("frame", ())
        return frame

    def monitor_changed(self, monitor) -> None:
        display = monitor.get_display()
        mid = -1
        for i in range(display.get_n_monitors()):
            m = display.get_monitor(i)
            if m == monitor:
                mid = i
                break
        geom = monitor.get_geometry()
        manufacturer = monitor.get_manufacturer()
        model = monitor.get_model()
        if manufacturer == "unknown":
            manufacturer = ""
        if model == "unknown":
            model = ""
        if manufacturer and model:
            plug_name = "%s %s" % (manufacturer, model)
        elif manufacturer:
            plug_name = manufacturer
        elif model:
            plug_name = model
        else:
            plug_name = "%i" % mid
        plug_name += " %ix%i at %i,%i" % (geom.width, geom.height, geom.x, geom.y)
        eventslog.info("window %#x has been moved to monitor %i: %s", self.wid, mid, plug_name)

    def update_relative_position(self) -> None:
        x, y = self.get_position()
        log("update_relative_position() follow_configure=%s", self._follow_configure)
        fc = self._follow_configure
        if fc:
            event_time, event_pos = fc
            # until we see the event we caused by calling move(),
            # or if we timeout (for safety - some platforms may skip events?),
            # don't update the relative position
            if monotonic() - event_time > 0.1 or fc == event_pos:
                # next time we will allow the update:
                self._follow_configure = None
            return
        follow = self._follow
        if not follow:
            return
        # adjust our relative position:
        fpos = getattr(follow, "_pos", None)
        if not fpos:
            return
        fx, fy = fpos
        rel_pos = x - fx, y - fy
        self._follow_position = follow.cp(*rel_pos)
        log("update_relative_position() relative position of %s from %s is %s, follow position=%s",
            self._pos, fpos, rel_pos, self._follow_position)

    def may_send_client_properties(self) -> None:
        # if there are client properties the server should know about,
        # we currently have no other way to send them to the server:
        if self._client_properties:
            self.send_configure_event(True)

    def send_configure(self) -> None:
        self.send_configure_event()

    def do_configure_event(self, event) -> None:
        eventslog("%s.do_configure_event(%s) OR=%s, iconified=%s",
                  self, event, self._override_redirect, self._iconified)
        Gtk.Window.do_configure_event(self, event)
        if self._override_redirect or self._iconified:
            # don't send configure packet for OR windows or iconified windows
            return
        x, y, w, h = self.get_drawing_area_geometry()
        w = max(1, w)
        h = max(1, h)
        ox, oy = self._pos
        dx, dy = x - ox, y - oy
        skip_geometry = dx == 0 and dy == 0 and self._size == (w, h)
        self._pos = (x, y)
        self.update_relative_position()
        gdkwin = self.get_window()
        screen = gdkwin.get_screen()
        display = screen.get_display()
        monitor = display.get_monitor_at_window(gdkwin)
        if monitor != self._monitor:
            if self._monitor is not None:
                self.monitor_changed(monitor)
            self._monitor = monitor
        geomlog("configure event: current size=%s, new size=%s, moved by=%s, backing=%s, iconified=%s",
                self._size, (w, h), (dx, dy), self._backing, self._iconified)
        self._size = (w, h)
        self._set_backing_size(w, h)
        self.send_configure_event(skip_geometry)
        if self._backing and not self._iconified:
            geomlog("configure event: queueing redraw")
            self.repaint(0, 0, w, h)

    def get_configure_client_properties(self) -> dict[str, Any]:
        return self._client_properties.copy()

    def send_configure_event(self, skip_geometry=False) -> None:
        metalog("send_configure_event(%s)", skip_geometry)
        assert skip_geometry or not self.is_OR()
        x, y, w, h = self.get_drawing_area_geometry()
        w = max(1, w)
        h = max(1, h)
        state = self._window_state
        props = self.get_configure_client_properties()
        self._client_properties = {}
        self._window_state = {}
        self.cancel_window_state_timer()
        sx, sy, sw, sh = self.cx(x), self.cy(y), self.cx(w), self.cy(h)
        packet: Sequence[PacketElement] = [self.wid, sx, sy, sw, sh, props, self._resize_counter, state, skip_geometry]
        pwid = self.wid
        if self.is_OR():
            pwid = -1 if BACKWARDS_COMPATIBLE else 0
        packet.append(pwid)
        packet.append(self.get_mouse_position())
        packet.append(self._client.get_current_modifiers())
        geomlog("%s", packet)
        self.send("configure-window", *packet)

    def _set_backing_size(self, ww: int, wh: int) -> None:
        b = self._backing
        bw = self.cx(ww)
        bh = self.cy(wh)
        if max(ww, wh) >= 32000 or min(ww, wh) < 0:
            raise ValueError("invalid window size %ix%i" % (ww, wh))
        if max(bw, bh) >= 32000:
            raise ValueError("invalid window backing size %ix%i" % (bw, bh))
        if b:
            prev_render_size = b.render_size
            b.init(ww, wh, bw, bh)
            if prev_render_size != b.render_size:
                self._client_properties["encoding.render-size"] = b.render_size
        else:
            self.new_backing(bw, bh)

    def resize(self, w: int, h: int, resize_counter: int = 0) -> None:
        ww, wh = self.get_size()
        geomlog("resize(%s, %s, %s) current size=%s, fullscreen=%s, maximized=%s",
                w, h, resize_counter, (ww, wh), self._fullscreen, self._maximized)
        self._resize_counter = resize_counter
        if (w, h) == (ww, wh):
            self._backing.offsets = 0, 0, 0, 0
            self.repaint(0, 0, w, h)
            return
        if not self._fullscreen and not self._maximized:
            Gtk.Window.resize(self, w, h)
            ww, wh = w, h
            self._backing.offsets = 0, 0, 0, 0
        else:
            self.center_backing(w, h)
        geomlog("backing offsets=%s, window offset=%s", self._backing.offsets, self.window_offset)
        self._set_backing_size(w, h)
        self.repaint(0, 0, ww, wh)
        self.may_send_client_properties()

    def center_backing(self, w, h) -> None:
        ww, wh = self.get_size()
        # align in the middle:
        dw = max(0, ww - w)
        dh = max(0, wh - h)
        ox = dw // 2
        oy = dh // 2
        geomlog("using window offset values %i,%i", ox, oy)
        # some backings use top,left values,
        # (opengl uses left and bottom since the viewport starts at the bottom)
        self._backing.offsets = ox, oy, ox + (dw & 0x1), oy + (dh & 0x1)
        geomlog("center_backing(%i, %i) window size=%ix%i, backing offsets=%s", w, h, ww, wh, self._backing.offsets)
        # adjust pointer coordinates:
        self.window_offset = ox, oy

    def move_resize(self, x: int, y: int, w: int, h: int, resize_counter: int = 0) -> None:
        geomlog("window %#x move_resize%s", self.wid, (x, y, w, h, resize_counter))
        x, y = self.adjusted_position(x, y)
        w = max(1, w)
        h = max(1, h)
        if self.window_offset:
            x += self.window_offset[0]
            y += self.window_offset[1]
            # TODO: check this doesn't move it off-screen!
        self._resize_counter = resize_counter
        wx, wy = self.get_drawing_area_geometry()[:2]
        if (wx, wy) == (x, y):
            # same location, just resize:
            if self._size == (w, h):
                geomlog("window unchanged")
            else:
                geomlog("unchanged position %ix%i, using resize(%i, %i)", x, y, w, h)
                self.resize(w, h)
            return
        # we have to move:
        if not self.get_realized():
            geomlog("window was not realized yet")
            self.realize()
        # adjust for window frame:
        window = self.get_window()
        ox, oy = window.get_origin()[-2:]
        rx, ry = window.get_root_origin()
        ax = x - (ox - rx)
        ay = y - (oy - ry)
        geomlog("window origin=%ix%i, root origin=%ix%i, actual position=%ix%i", ox, oy, rx, ry, ax, ay)
        # validate against edge of screen (ensure window is shown):
        if CLAMP_WINDOW_TO_SCREEN:
            mw, mh = self._client.get_root_size()
            if (ax + w) <= 0:
                ax = -w + 1
            elif ax >= mw:
                ax = mw - 1
            if not WINDOW_OVERFLOW_TOP and ay <= 0:
                ay = 0
            elif (ay + h) <= 0:
                ay = -y + 1
            elif ay >= mh:
                ay = mh - 1
            geomlog("validated window position for total screen area %ix%i : %ix%i", mw, mh, ax, ay)
        if self._size == (w, h):
            # just move:
            geomlog("window size unchanged: %ix%i, using move(%i, %i)", w, h, ax, ay)
            window.move(ax, ay)
            return
        # resize:
        self._size = (w, h)
        geomlog("%s.move_resize%s", window, (ax, ay, w, h))
        window.move_resize(ax, ay, w, h)
        # re-init the backing with the new size
        self._set_backing_size(w, h)
        self.repaint(0, 0, w, h)
        self.may_send_client_properties()

    def cleanup(self) -> None:
        self.cancel_window_state_timer()
        self.cancel_send_iconifiy_timer()
        self.cancel_moveresize_timer()
        self.cancel_follow_handler()
        self.on_realize_cb = {}

    def destroy(self) -> None:  # pylint: disable=method-hidden
        ClientWindowBase.destroy(self)
        Gtk.Window.destroy(self)
        self.destroy = noop_destroy

    def do_unmap_event(self, event) -> None:
        self.cancel_follow_handler()
        eventslog("do_unmap_event(%s)", event)
        self._unfocus()
        if not self._override_redirect:
            self.send("unmap-window", self.wid, False)

    def do_delete_event(self, event) -> bool:
        # Gtk.Window.do_delete_event(self, event)
        eventslog("do_delete_event(%s)", event)
        self._client.window_close_event(self.wid)
        return True

    def key_may_break_moveresize(self, _window, event) -> bool:
        keyval = event.keyval
        keyname = Gdk.keyval_name(keyval) or ""
        if self.moveresize_event and keyname in BREAK_MOVERESIZE:
            # cancel move resize if there is one:
            self.moveresize_event = None
            self.cancel_moveresize_timer()
            return True
        # let the event propagate to the next handler
        return False

    def update_icon(self, img) -> None:
        self._current_icon = img
        has_alpha = img.mode == "RGBA"
        width, height = img.size
        rowstride = width * (3 + int(has_alpha))
        pixbuf = get_pixbuf_from_data(img.tobytes(), has_alpha, width, height, rowstride)
        iconlog("%s.set_icon(%s)", self, pixbuf)
        self.set_icon(pixbuf)
