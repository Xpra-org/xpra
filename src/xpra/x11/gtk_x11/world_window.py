# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.error import trap
from xpra.x11.bindings.window_bindings import constants     #@UnresolvedImport
from xpra.x11.gtk_x11.send_wm import send_wm_take_focus     #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_set
from xpra.x11.gtk_x11.gdk_bindings import x11_get_server_time
from xpra.gtk_common.gtk_util import get_default_root_window, screen_get_default, get_xwindow, is_realized
from xpra.gtk_common.gobject_compat import import_gtk, import_gobject, is_gtk3
from xpra.log import Logger

log = Logger("x11", "window")
focuslog = Logger("x11", "window", "focus")


gtk = import_gtk()
gobject = import_gobject()


XNone = constants["XNone"]
CurrentTime = constants["CurrentTime"]


# This file defines Xpra's top-level widget.  It is a magic window that
# always and exactly covers the entire screen (possibly crossing multiple
# screens, in the Xinerama case); it also mediates between the GTK+ and X
# focus models.
#
# This requires a very long comment, because focus management is teh awesome.
# The basic problems are:
#    1) X focus management sucks
#    2) GDK/GTK know this, and sensibly avoids it
# (1) is a problem by itself, but (2) makes it worse, because we have to wedge
# them together somehow anyway.
#
# In more detail: X tracks which X-level window has (keyboard) focus at each
# point in time.  This is the window which receives KeyPress and KeyRelease
# events.  GTK also has a notion of focus; at any given time (within a
# particular toplevel) exactly one widget is focused.  This is the widget
# which receives key-press-event and key-release-event signals.  However,
# at the level of implementation, these two ideas of focus are actually kept
# entirely separate.  In fact, when a GTK toplevel gets focus, it sets the X
# input focus to a special hidden window, reads X events off of that window,
# and then internally routes these events to whatever the appropriate widget
# would be at any given time.
#
# The other thing which GTK does with focus is simply tweak the drawing style
# of widgets.  A widget that is focused within its toplevel can/will look
# different from a widget that does not have focus within its toplevel.
# Similarly, a widget may look different depending on whether the toplevel
# that contains it has toplevel focus or not.
#
# Unfortunately, we cannot read keyboard events out of the special hidden
# window and route them to client windows; to be a proper window manager, we
# must actually assign X focus to client windows, while pretending to GTK+
# that nothing funny is going on, and our client windows are just ordinary
# widgets.
#
# So there are a few pieces to this.  Firstly, GTK tracks focus on toplevels
# by watching for focus events from X, which ultimately come from the window
# manager.  Since we *are* the window manager, this is not particularly
# useful.  Instead, we create a special subclass of gtk.Window that fills the
# whole screen, and trick GTK into thinking that this toplevel *always* has
# (GTK) focus.
#
# Then, to manage the actual X focus, we do a little dance, watching the GTK
# focus within our special toplevel.  Whenever it moves to a widget that
# actually represents a client window, we send the X focus to that client
# window.  Whenever it moves to a widget that is actually an ordinary widget,
# we take the X focus back to our special toplevel.
#
# Note that this means that we do violate our overall goal of making client
# window widgets indistinguishable from ordinary GTK widgets, because client
# window widgets can only be placed inside this special toplevel, and this
# toplevel has special-cased handling for our particular client-wrapping
# widget.  In practice this should not be a problem.
#
# Finally, we have to notice when the root window gets focused (as it can when
# a client misbehaves, or perhaps exits in a weird way), and regain the
# focus.  The Wm object is actually responsible for doing this (since it is
# responsible for all root-window event handling); we just expose an API
# ('reset_x_focus') that people should call whenever they think that focus may
# have gone wonky.

def root_set(*args):
    prop_set(get_default_root_window(), *args)

world_window = None
def get_world_window():
    global world_window
    return world_window

def destroy_world_window():
    global world_window
    ww = world_window
    if ww:
        world_window = None
        ww.destroy()


class WorldWindow(gtk.Window):
    def __init__(self, screen=screen_get_default()):
        global world_window
        assert world_window is None, "a world window already exists! (%s)" % world_window
        world_window = self
        super(WorldWindow, self).__init__()
        self.set_screen(screen)
        self.set_title("Xpra-WorldWindow")
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_opacity(0)

        # FIXME: This would better be a default handler, but there is a bug in
        # the superclass's default handler that means we can't call it
        # properly[0], so as a workaround we let the real default handler run,
        # and then come in afterward to do what we need to.  (See also
        # Viewport._after_set_focus_child.)
        #   [0] http://bugzilla.gnome.org/show_bug.cgi?id=462368
        self.connect_after("set-focus", self._after_set_focus)

        # Make sure that we are always the same size as the screen
        self.set_resizable(False)
        screen.connect("size-changed", self._resize)
        self.move(0, 0)
        self._resize()

        if is_gtk3():
            self.add = self._patched_add

    def __repr__(self):
        xid = 0
        w = self.get_window()
        if w:
            xid = get_xwindow(w)
        return "WorldWindow(%#x)" % xid

    def _resize(self, *_args):
        s = self.get_screen()
        x = s.get_width()
        y = s.get_height()
        log("sizing world to %sx%s", x, y)
        self.set_size_request(x, y)
        self.resize(x, y)

    # We want to fake GTK out into thinking that this window always has
    # toplevel focus, no matter what happens.  There are two parts to this:
    # (1) getting has-toplevel-focus set to start with, (2) making sure it is
    # never unset.  (2) is easy -- we just override do_focus_out_event to
    # silently swallow all FocusOut events, so we never notice losing the
    # focus.  (1) is harder, because we can't just go ahead and set
    # has-toplevel-focus to true; there is a bunch of other stuff that GTK
    # does from the focus-in-event handler, and we want to do all of that.  To
    # make it worse, we cannot call the focus-in-event handler unless we
    # actually have a GdkEvent to pass it, and PyGtk does not expose any
    # constructor for GdkEvents!  So instead, we:
    #   -- force focus to ourselves for real, once, when becoming visible
    #   -- let the normal GTK machinery handle this first FocusIn
    #      -- it is possible that we should not in fact have the X focus at
    #         this time, though, so then give it to whoever should
    #   -- and finally ignore all subsequent focus-in-events
    def do_map(self, *args):
        gtk.Window.do_map(self, *args)

        # We are being mapped, so we can focus ourselves.
        # Check for the property, just in case this is the second time we are
        # being mapped -- otherwise we might miss the special call to
        # reset_x_focus in do_focus_in_event:
        if not self.get_property("has-toplevel-focus"):
            # Take initial focus upon being mapped.  Technically it is illegal
            # (ICCCM violating) to use CurrentTime in a WM_TAKE_FOCUS message,
            # but GTK doesn't happen to care, and this guarantees that we
            # *will* get the focus, and thus a real FocusIn event.
            send_wm_take_focus(self.get_window(), CurrentTime)

    def _patched_add(self, widget):
        w = widget.get_window()
        log("add(%s) realized=%s, widget window=%s", widget, self.get_realized(), w)
        #the DesktopManager does not have a window..
        if w:
            super().add(widget)

    def do_focus_in_event(self, event):
        htf = self.get_property("has-toplevel-focus")
        focuslog("world window got focus: %s, has-toplevel-focus=%s", event, htf)
        if not htf:
            gtk.Window.do_focus_in_event(self, event)
            self.reset_x_focus()

    def do_focus_out_event(self, event):
        focuslog("world window lost focus: %s", event)
        # Do nothing -- harder:
        self.stop_emission("focus-out-event")
        return False

    def _take_focus(self):
        focuslog("Take Focus -> world window")
        assert is_realized(self)
        # Weird hack: we are a GDK window, and the only way to properly get
        # input focus to a GDK window is to send it WM_TAKE_FOCUS.  So this is
        # sending a WM_TAKE_FOCUS to our own window, which will go to the X
        # server and then come back to our own process, which will then issue
        # an XSetInputFocus on itself.
        w = self.get_window()
        now = x11_get_server_time(w)
        send_wm_take_focus(w, now)

    def reset_x_focus(self):
        focuslog("reset_x_focus: widget with focus: %s", self.get_focus())
        def do_reset_x_focus():
            self._take_focus()
            root_set("_NET_ACTIVE_WINDOW", "u32", XNone)
        trap.swallow_synced(do_reset_x_focus)

    def _after_set_focus(self, *_args):
        focuslog("after_set_focus")
        # GTK focus has changed.  See comment in __init__ for why this isn't a
        # default handler.
        if self.get_focus() is not None:
            self.reset_x_focus()

gobject.type_register(WorldWindow)
