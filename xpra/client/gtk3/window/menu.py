# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from collections.abc import Callable, Sequence

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.client.gtk3.menu_helper import GTKMenuHelper, gen_non_none_menu_items
from xpra.gtk.widget import checkitem
from xpra.constants import RESOLUTION_ALIASES, MoveResize
from xpra.platform.gui import get_icon_size
from xpra.log import Logger

log = Logger("gtk", "menu")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

NUDGE_TIMEOUT = 0.5
UNFULLSCREEN_TIMEOUT = 1000
RESIZE_TOOLTIP = "Resize the window from the edge closest to the pointer"
MOVE_TOOLTIP = "Move the window with the pointer"

# the window is split in a 3x3 grid, the cell the pointer is in picks the edge(s) to resize from:
RESIZE_GRID: dict[tuple[int, int], MoveResize] = {
    (0, 0): MoveResize.SIZE_TOPLEFT,
    (1, 0): MoveResize.SIZE_TOP,
    (2, 0): MoveResize.SIZE_TOPRIGHT,
    (0, 1): MoveResize.SIZE_LEFT,
    (2, 1): MoveResize.SIZE_RIGHT,
    (0, 2): MoveResize.SIZE_BOTTOMLEFT,
    (1, 2): MoveResize.SIZE_BOTTOM,
    (2, 2): MoveResize.SIZE_BOTTOMRIGHT,
}


def ticked_icon(state: bool) -> str:
    return "ticked.png" if state else "unticked.png"


def get_resize_direction(x: int, y: int, wx: int, wy: int, ww: int, wh: int) -> MoveResize:
    col = min(2, max(0, (x - wx) * 3 // max(1, ww)))
    row = min(2, max(0, (y - wy) * 3 // max(1, wh)))
    if (direction := RESIZE_GRID.get((col, row))) is not None:
        return direction
    # in the middle: use the closest edge
    distances = {
        MoveResize.SIZE_LEFT: x - wx,
        MoveResize.SIZE_RIGHT: wx + ww - x,
        MoveResize.SIZE_TOP: y - wy,
        MoveResize.SIZE_BOTTOM: wy + wh - y,
    }
    return min(distances, key=distances.get)


class WindowMenuHelper(GTKMenuHelper):

    def __init__(self, client, window):
        super().__init__(client)
        self.window = window

    def get_menu_items(self) -> Sequence[Gtk.ImageMenuItem | Gtk.MenuItem]:
        log("get_menu_items()")
        return gen_non_none_menu_items(
            # menu.append(self.make_aboutmenuitem)
            self.make_infomenuitem,
            # if self.client.client_supports_opengl:
            #    menu.append(self.make_openglmenuitem())
            self.make_minimizemenuitem,
            self.make_maximizemenuitem,
            self.make_initiateresizemenuitem,
            self.make_initiatemovemenuitem,
            self.make_fullscreenmenuitem,
            self.make_resizemenuitem,
            self.make_abovenmenuitem,
            self.make_grabmenuitem,
            self.make_bordermenuitem,
            self.make_refreshmenuitem,
            self.make_reinitmenuitem,
            self.make_closemenuitem,
            self.make_actionsmenu,
        )

    def make_infomenuitem(self) -> Gtk.ImageMenuItem:
        def show_info(*_args) -> None:
            from xpra.client.gtk3.window.window_info import WindowInfo
            wi = WindowInfo(self.window)
            wi.show()

        gl = self.menuitem("Window Information", "information.png", "Window state and details", show_info)
        log("make_infomenuitem()=%s", gl)
        return gl

    def make_openglmenuitem(self) -> Gtk.ImageMenuItem:
        gl = checkitem("OpenGL")
        gl.set_tooltip_text("hardware accelerated rendering using OpenGL")
        return gl

    def make_minimizemenuitem(self) -> Gtk.ImageMenuItem:
        def minimize(*args) -> None:
            log("minimize%s", args)
            self.window.iconify()

        return self.menuitem("Minimize", "minimize.png", cb=minimize)

    def make_maximizemenuitem(self) -> Gtk.ImageMenuItem:
        def maximize(*args) -> None:
            log("maximize%s", args)
            if self.window.is_maximized():
                self.window.unmaximize()
            else:
                self.window.maximize()

        def get_label(maximized) -> str:
            return "Unmaximize" if maximized else "Maximize"

        label = get_label(self.window.is_maximized())
        self.maximize_menuitem = self.menuitem(label, "maximize.png", cb=maximize)

        def window_state_updated(widget, event) -> None:
            maximized_changed = event.changed_mask & Gdk.WindowState.MAXIMIZED
            log("state_changed%s maximized_changed=%s", (widget, event), maximized_changed)
            if maximized_changed:
                lbl = get_label(event.new_window_state & Gdk.WindowState.MAXIMIZED)
                self.maximize_menuitem.set_label(lbl)
            self.maximize_menuitem.set_sensitive(self.window.can_maximize())

        self.window.connect("window-state-event", window_state_updated)
        return self.maximize_menuitem

    def make_resizemenuitem(self) -> Gtk.ImageMenuItem | None:
        metadata = typedict(self.window._metadata)
        log("make_resizemenuitem() metadata=%s", metadata)
        if metadata.strtupleget("content-types") != ("desktop",) or metadata.dictget("size-constraints", {}):
            return None

        from threading import Event
        switching = Event()

        def resize(item) -> None:
            if switching.is_set():
                return
            size = item.get_label()
            w, h = self.window.get_size()
            current_size = f"{w}x{h}"
            log("resize(%s) current_size=%s", size, current_size)
            select_size(size)
            if size != current_size:
                self.window.resize(*map(int, size.split("x")))

        items = []

        def update_size(*_args) -> None:
            w, h = self.window.get_size()
            size = f"{w}x{h}"
            log("update_size: %s", size)
            select_size(size)

        def select_size(size: str) -> None:
            log("select_size(%s)", size)
            switching.set()
            for item in items:
                item.set_active(item.get_label() == size)
            switching.clear()

        self.window.connect("configure-event", update_size)

        sizemenu = Gtk.Menu()
        for w, h in sorted(list(set(RESOLUTION_ALIASES.values()))):
            text = "%dx%d" % (w, h)
            item = checkitem(text, resize)
            items.append(item)
            sizemenu.append(item)
        update_size()
        sizemenu.show_all()
        resize = self.menuitem("Resize", "scaling.png")
        resize.set_submenu(sizemenu)
        return resize

    def make_initiateresizemenuitem(self) -> Gtk.ImageMenuItem:
        def initiate_resize() -> None:
            gdkwin = self.window.get_window()
            if not gdkwin:
                return
            # use the geometry before leaving fullscreen to choose the edge,
            # that's the one the user was pointing at:
            frame = gdkwin.get_frame_extents()
            pointer = gdkwin.get_display().get_default_seat().get_pointer()
            x, y = pointer.get_position()[1:]
            direction = get_resize_direction(x, y, frame.x, frame.y, frame.width, frame.height)
            log("initiate_resize() pointer=%s, frame=%s, direction=%s",
                (x, y), (frame.x, frame.y, frame.width, frame.height), direction)
            self.when_not_fullscreen(lambda: do_initiate_resize(direction))

        def do_initiate_resize(direction: MoveResize) -> None:
            gdkwin = self.window.get_window()
            if not gdkwin:
                return
            pointer = gdkwin.get_display().get_default_seat().get_pointer()
            screen, x, y = pointer.get_position()
            from xpra.client.gtk3.window import base
            if base.MOVERESIZE_X11 and base.HAS_X11_BINDINGS:
                # metacity derived window managers (ie: muffin) end edge resizes straight away
                # if the button is not held down, but keyboard resizes also follow the pointer:
                # the window manager warps it to the centre of the window,
                # and the direction of the first motion picks the edges to resize from
                self.window.initiate_moveresize(x, y, MoveResize.SIZE_KEYBOARD, 0, 1)
                col, row = next(k for k, v in RESIZE_GRID.items() if v == direction)
                start = monotonic()

                def nudge_pointer() -> bool:
                    # the frame may still be changing if we just left fullscreen:
                    frame = gdkwin.get_frame_extents()
                    cx, cy = frame.x + frame.width // 2, frame.y + frame.height // 2
                    px, py = pointer.get_position()[1:]
                    if (abs(px - cx) > 1 or abs(py - cy) > 1) and monotonic() - start < NUDGE_TIMEOUT:
                        # not warped yet
                        return True
                    log("nudge_pointer() from %s by %s", (px, py), (col - 1, row - 1))
                    pointer.warp(screen, px + col - 1, py + row - 1)
                    return False

                GLib.timeout_add(20, nudge_pointer)
            else:
                # GDK drags need a button held down (ie: on macOS), so follow the pointer ourselves:
                self.window.initiate_pointer_moveresize(direction)

        self.initiate_resize_menuitem = self.menuitem("Resize", "scaling.png", RESIZE_TOOLTIP,
                                                      cb=self.after_menu(initiate_resize))
        return self.initiate_resize_menuitem

    def make_initiatemovemenuitem(self) -> Gtk.ImageMenuItem:
        def initiate_move() -> None:
            gdkwin = self.window.get_window()
            if not gdkwin:
                return
            x, y = gdkwin.get_display().get_default_seat().get_pointer().get_position()[1:]
            from xpra.client.gtk3.window import base
            log("initiate_move() pointer=%s", (x, y))
            if base.MOVERESIZE_X11 and base.HAS_X11_BINDINGS:
                # same as resizing: a keyboard move follows the pointer without a button held down
                self.window.initiate_moveresize(x, y, MoveResize.MOVE_KEYBOARD, 0, 1)
            else:
                self.window.initiate_pointer_moveresize(MoveResize.MOVE)

        self.initiate_move_menuitem = self.menuitem("Move", "forward.png", MOVE_TOOLTIP,
                                                    cb=self.after_menu(lambda: self.when_not_fullscreen(initiate_move)))
        return self.initiate_move_menuitem

    def when_not_fullscreen(self, fn: Callable[[], None]) -> None:
        # window managers won't move or resize fullscreen windows,
        # so leave fullscreen first and wait for the state change:
        gdkwin = self.window.get_window()
        if not gdkwin or not gdkwin.get_state() & Gdk.WindowState.FULLSCREEN:
            fn()
            return
        handler = timer = 0

        def done() -> None:
            nonlocal handler, timer
            if handler:
                self.window.disconnect(handler)
                handler = 0
            if timer:
                GLib.source_remove(timer)
                timer = 0

        def state_changed(_widget, event) -> None:
            if not event.new_window_state & Gdk.WindowState.FULLSCREEN:
                log("when_not_fullscreen(%s) left fullscreen", fn)
                done()
                GLib.idle_add(fn)

        def timed_out() -> bool:
            nonlocal timer
            timer = 0
            log.warn("Warning: the window did not leave fullscreen, cannot move or resize it")
            done()
            return False

        handler = self.window.connect("window-state-event", state_changed)
        timer = GLib.timeout_add(UNFULLSCREEN_TIMEOUT, timed_out)
        self.window.unfullscreen()

    def update_moveresize_menuitems(self) -> None:
        # window managers will unmaximize a window to move it, but won't resize it,
        # (we could unmaximize it first instead),
        # fullscreen windows are taken out of fullscreen first, see `when_not_fullscreen`
        gdkwin = self.window.get_window()
        state = gdkwin.get_state() if gdkwin else Gdk.WindowState(0)
        sc = self.window.size_constraints
        minw, minh = sc.intpair("minimum-size")
        maxw, maxh = sc.intpair("maximum-size")
        fixed = 0 < maxw <= minw and 0 < maxh <= minh
        log("update_moveresize_menuitems() state=%s, size-constraints=%s, fixed=%s", state, sc, fixed)
        move_reason = resize_reason = ""
        if not gdkwin:
            move_reason = resize_reason = "the window is not mapped"
        elif state & Gdk.WindowState.MAXIMIZED:
            resize_reason = "the window is maximized"
        elif fixed:
            resize_reason = "the window has a fixed size"
        for item, tooltip, unavailable in (
                (self.initiate_move_menuitem, MOVE_TOOLTIP, move_reason),
                (self.initiate_resize_menuitem, RESIZE_TOOLTIP, resize_reason),
        ):
            self.set_sensitive(item, not unavailable)
            item.set_tooltip_text(f"Unavailable: {unavailable}" if unavailable else tooltip)

    def do_show_menu(self, button: int, time) -> None:
        self.update_moveresize_menuitems()
        super().do_show_menu(button, time)

    @staticmethod
    def after_menu(fn: Callable[[], None]) -> Callable[[], None]:
        def cb() -> None:
            # wait for the menu to release its grab:
            GLib.idle_add(fn)
        return cb

    def make_fullscreenmenuitem(self) -> Gtk.ImageMenuItem:
        def is_fullscreen() -> bool:
            gdkwin = self.window.get_window()
            return bool(gdkwin and gdkwin.get_state() & Gdk.WindowState.FULLSCREEN)

        def fullscreen(*args) -> None:
            log("fullscreen%s", args)
            if is_fullscreen():
                self.window.unfullscreen()
            else:
                self.window.fullscreen()

        def get_label(fullscreen) -> str:
            return "Unfullscreen" if fullscreen else "Fullscreen"

        self.fullscreen_menuitem = self.menuitem(get_label(is_fullscreen()), "scaling.png", cb=fullscreen)

        def window_state_updated(widget, event) -> None:
            if event.changed_mask & Gdk.WindowState.FULLSCREEN:
                lbl = get_label(event.new_window_state & Gdk.WindowState.FULLSCREEN)
                log("state_changed%s fullscreen label=%r", (widget, event), lbl)
                self.fullscreen_menuitem.set_label(lbl)

        self.window.connect("window-state-event", window_state_updated)
        return self.fullscreen_menuitem

    def _set_ticked(self, item, state: bool) -> None:
        icon_name = ticked_icon(state)
        icon_size = self.menu_icon_size or get_icon_size()
        image = self.get_image(icon_name, icon_size)
        item.set_image(image)

    def make_abovenmenuitem(self) -> Gtk.ImageMenuItem:
        def toggle_above(*args) -> None:
            above = not self.window._above
            log("toggle_above%s above=%s", args, above)
            self.window._above = above
            self.window.set_keep_above(above)
            self._set_ticked(self.above_menuitem, above)

        self.above_menuitem = self.menuitem("Always on top", ticked_icon(self.window._above), cb=toggle_above)
        return self.above_menuitem

    def make_grabmenuitem(self) -> Gtk.ImageMenuItem:
        if not hasattr(self.client, "_window_with_grab"):
            return None

        def is_grabbed() -> bool:
            return self.client._window_with_grab == self.window.wid

        def toggle_grab(*args) -> None:
            log("toggle_grab%s", args)
            if is_grabbed():
                self.client.window_ungrab()
            else:
                self.client.window_grab(self.window.wid, self.window)
            self._set_ticked(self.grab_menuitem, is_grabbed())

        self.grab_menuitem = self.menuitem("Grabbed", ticked_icon(is_grabbed()), cb=toggle_grab)
        return self.grab_menuitem

    def make_bordermenuitem(self) -> Gtk.ImageMenuItem:
        def toggle_border(*args) -> None:
            log("toggle_border%s", args)
            self.window.border.shown = not self.window.border.shown
            self._set_ticked(self.grab_menuitem, self.window.border.shown)
            self.client.send_refresh(self.window.wid)

        self.border_menuitem = self.menuitem("Show Border", ticked_icon(self.window.border.shown), cb=toggle_border)
        return self.border_menuitem

    def make_refreshmenuitem(self) -> Gtk.ImageMenuItem:
        def force_refresh(*args) -> None:
            log("force refresh%s", args)
            self.client.send_refresh(self.window.wid)
            self.window.reset_icon()

        return self.menuitem("Refresh", "retry.png", cb=force_refresh)

    def make_reinitmenuitem(self) -> Gtk.ImageMenuItem:
        def force_reinit(*args) -> None:
            log("force reinit%s", args)
            if window := self.client.get_subsystem("window"):
                window.reinit_window(self.window.wid, self.window)
            if tray := self.client.get_subsystem("tray"):
                tray.reset_tray_icon()

        return self.menuitem("Re-initialize", "reinitialize.png", cb=force_reinit)

    def make_closemenuitem(self) -> Gtk.ImageMenuItem:
        def close(*args) -> None:
            log("close(%s)", args)
            self.window.close()

        return self.menuitem("Close", "close.png", cb=close)

    def make_actionsmenu(self) -> Gtk.ImageMenuItem | None:
        actions: Sequence[str] = self.window._actions
        log("make_actionsmenu() actions=%s", actions)
        if not actions:
            return None

        def action_menuitem(action: str, icon_name="") -> Gtk.ImageMenuItem:

            def action_cb() -> None:
                wid = self.window.wid
                log("action_cb() for window %#x, action=%s", wid, action)
                self.client.send("window-action", wid, action)
            return self.menuitem(action, icon_name, cb=action_cb)

        if len(actions) == 1:
            return action_menuitem(actions[0], "forward.png")

        # use a submenu:
        actions_menu = self.menuitem("Actions", "forward.png", "")
        actions_submenu = Gtk.Menu()
        actions_menu.set_submenu(actions_submenu)
        for action in actions:
            actions_submenu.append(action_menuitem(action))
        return actions_menu
