# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
import xpra.x11.gtk_x11.window
from xpra.x11.gtk_x11.error import trap
from xpra.x11.bindings.core_bindings import const           #@UnresolvedImport
from xpra.x11.gtk_x11.send_wm import send_wm_take_focus     #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_set
from xpra.log import Logger
log = Logger()

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
    prop_set(gtk.gdk.get_default_root_window(), *args)


class WorldWindow(gtk.Window):
    def __init__(self):
        super(WorldWindow, self).__init__()
        self.set_title("Xpra-WorldWindow")

        # FIXME: This would better be a default handler, but there is a bug in
        # the superclass's default handler that means we can't call it
        # properly[0], so as a workaround we let the real default handler run,
        # and then come in afterward to do what we need to.  (See also
        # Viewport._after_set_focus_child.)
        #   [0] http://bugzilla.gnome.org/show_bug.cgi?id=462368
        self.connect_after("set-focus", self._after_set_focus)

        # Make sure that we are always the same size as the screen
        self.set_resizable(False)
        gtk.gdk.screen_get_default().connect("size-changed", self._resize)
        self.move(0, 0)
        self._resize()

    def _resize(self, *args):
        x = gtk.gdk.screen_width()
        y = gtk.gdk.screen_height()
        log("sizing world to %sx%s", x, y)
        self.set_size_request(x, y)
        self.resize(x, y)
        root_set("_NET_DESKTOP_GEOMETRY", ["u32"], [x, y])

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
            current_time = const["CurrentTime"]
            send_wm_take_focus(self.window, current_time)

    def do_focus_in_event(self, *args):
        log("world window got focus")
        if not self.get_property("has-toplevel-focus"):
            #super(WorldWindow, self).do_focus_in_event(*args)
            gtk.Window.do_focus_in_event(self, *args)
            self.reset_x_focus()

    def do_focus_out_event(self, *args):
        # Do nothing -- harder:
        self.stop_emission("focus-out-event")
        return False

    def _take_focus(self):
        log("Focus -> world window")
        assert self.flags() & gtk.REALIZED
        # Weird hack: we are a GDK window, and the only way to properly get
        # input focus to a GDK window is to send it WM_TAKE_FOCUS.  So this is
        # sending a WM_TAKE_FOCUS to our own window, which will go to the X
        # server and then come back to our own process, which will then issue
        # an XSetInputFocus on itself.  Note not swallowing errors here, this
        # should always succeed.
        now = gtk.gdk.x11_get_server_time(self.window)
        send_wm_take_focus(self.window, now)

    def reset_x_focus(self):
        focus = self.get_focus()
        log("widget with focus: %s", focus)
        if isinstance(focus, xpra.x11.gtk_x11.window.WindowView):
            # FIXME: ugly:
            focus.model.give_client_focus()
            trap.swallow_synced(root_set, "_NET_ACTIVE_WINDOW", "window", focus.model.get_property("client-window"))
        else:
            self._take_focus()
            trap.swallow_synced(root_set, "_NET_ACTIVE_WINDOW", "u32", const["XNone"])

    def _after_set_focus(self, *args):
        # GTK focus has changed.  See comment in __init__ for why this isn't a
        # default handler.
        if self.get_focus() is not None:
            self.reset_x_focus()

gobject.type_register(WorldWindow)
