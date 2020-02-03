# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.x11.gtk_x11.window_damage import WindowDamageHandler
from xpra.gtk_common.gobject_util import one_arg_signal, AutoPropGObjectMixin
from xpra.gtk_common.gtk_util import get_xwindow
from xpra.x11.gtk_x11.gdk_bindings import (
    add_event_receiver,             #@UnresolvedImport
    remove_event_receiver,          #@UnresolvedImport
    get_parent,                     #@UnresolvedImport
    )
from xpra.gtk_common.error import trap
from xpra.x11.gtk_x11.world_window import get_world_window
from xpra.x11.bindings.ximage import XImageBindings #@UnresolvedImport
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
from xpra.gtk_common.gobject_compat import import_gobject
from xpra.log import Logger

log = Logger("x11", "window")

gobject = import_gobject()

XImage = XImageBindings()
X11Window = X11WindowBindings()
X11Window.ensure_XComposite_support()

StructureNotifyMask = constants["StructureNotifyMask"]


class CompositeHelper(WindowDamageHandler, AutoPropGObjectMixin, gobject.GObject):

    __gsignals__ = WindowDamageHandler.__common_gsignals__.copy()
    __gsignals__.update({
        #emit:
        "contents-changed"      : one_arg_signal,
        })

    # This may raise XError.
    def __init__(self, window):
        WindowDamageHandler.__init__(self, window)
        AutoPropGObjectMixin.__init__(self)
        gobject.GObject.__init__(self)
        self._listening_to = None

    def __repr__(self):
        return "CompositeHelper(%#x)" % self.xid

    def setup(self):
        X11Window.XCompositeRedirectWindow(self.xid)
        WindowDamageHandler.setup(self)

    def do_destroy(self, win):
        trap.swallow_synced(X11Window.XCompositeUnredirectWindow, self.xid)
        WindowDamageHandler.do_destroy(self, win)

    def invalidate_pixmap(self):
        lt = self._listening_to
        if lt:
            self._listening_to = None
            self._cleanup_listening(lt)
        WindowDamageHandler.invalidate_pixmap(self)

    def _cleanup_listening(self, listening):
        if listening:
            # Don't want to stop listening to self.client_window!:
            assert self.client_window is None or self.client_window not in listening
            for w in listening:
                remove_event_receiver(w, self)

    def _set_pixmap(self):
        # The tricky part here is that the pixmap returned by
        # NameWindowPixmap gets invalidated every time the window's
        # viewable state changes.  ("viewable" here is the X term that
        # means "mapped, and all ancestors are also mapped".)  But
        # there is no X event that will tell you when a window's
        # viewability changes!  Instead we have to find all ancestors,
        # and watch all of them for unmap and reparent events.  But
        # what about races?  I hear you cry.  By doing things in the
        # exact order:
        #   1) select for StructureNotify
        #   2) QueryTree to get parent
        #   3) repeat 1 & 2 up to the root
        #   4) call NameWindowPixmap
        # we are safe.  (I think.)
        listening = []
        e = None
        try:
            screen = self.client_window.get_screen()
            if not screen:
                log("cannot set pixmap on client window - maybe deleted?")
                return
            root = screen.get_root_window()
            gdkworld = None
            world = get_world_window()
            if world:
                gdkworld = world.get_window()
            win = get_parent(self.client_window)
            while win not in (None, root, gdkworld) and win.get_parent() is not None:
                # We have to use a lowlevel function to manipulate the
                # event selection here, because SubstructureRedirectMask
                # does not roundtrip through the GDK event mask
                # functions.  So if we used them, here, we would clobber
                # corral window selection masks, and those don't deserve
                # clobbering.  They are our friends!  X is driving me
                # slowly mad.
                xid = get_xwindow(win)
                X11Window.addXSelectInput(xid, StructureNotifyMask)
                add_event_receiver(win, self, max_receivers=-1)
                listening.append(win)
                win = get_parent(win)
            handle = XImage.get_xcomposite_pixmap(self.xid)
        except Exception as e:
            try:
                self._cleanup_listening(listening)
            except Exception:
                pass
            raise
        if handle is None:
            log("failed to name a window pixmap for %#x: %s", self.xid, e)
            self._cleanup_listening(listening)
        else:
            self._contents_handle = handle
            # Don't save the listening set until after
            # NameWindowPixmap has succeeded, to maintain our
            # invariant:
            self._listening_to = listening


    def do_xpra_damage_event(self, event):
        event.x += self._border_width
        event.y += self._border_width
        self.emit("contents-changed", event)

gobject.type_register(CompositeHelper)
