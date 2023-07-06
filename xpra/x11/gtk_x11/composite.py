# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject, Gdk
from typing import List

from xpra.x11.gtk_x11.window_damage import WindowDamageHandler
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.x11.gtk3.gdk_bindings import add_event_receiver, remove_event_receiver
from xpra.gtk_common.error import xlog
from xpra.x11.gtk_x11.world_window import get_world_window
from xpra.x11.bindings.ximage import XImageBindings #@UnresolvedImport
from xpra.x11.bindings.window import constants, X11WindowBindings #@UnresolvedImport
from xpra.log import Logger

log = Logger("x11", "window", "damage")

XImage = XImageBindings()
X11Window = X11WindowBindings()
X11Window.ensure_XComposite_support()

StructureNotifyMask = constants["StructureNotifyMask"]


class CompositeHelper(WindowDamageHandler, GObject.GObject):

    __gsignals__ = WindowDamageHandler.__common_gsignals__.copy()
    __gsignals__.update({
        #emit:
        "contents-changed"      : one_arg_signal,
        })

    # This may raise XError.
    def __init__(self, xid:int):
        WindowDamageHandler.__init__(self, xid)
        GObject.GObject.__init__(self)
        self._listening_to : List[int] = []

    def __repr__(self):
        return f"CompositeHelper({self.xid:x})"

    def setup(self) -> None:
        X11Window.XCompositeRedirectWindow(self.xid)
        WindowDamageHandler.setup(self)

    def do_destroy(self) -> None:
        with xlog:
            X11Window.XCompositeUnredirectWindow(self.xid)
            WindowDamageHandler.do_destroy(self)

    def invalidate_pixmap(self) -> None:
        lt = self._listening_to
        if lt:
            self._listening_to = []
            self._cleanup_listening(lt)
        WindowDamageHandler.invalidate_pixmap(self)

    def _cleanup_listening(self, listening:List[int]) -> None:
        if listening:
            for w in listening:
                # Don't want to stop listening to our xid!:
                if w!=self.xid:
                    remove_event_receiver(w, self)

    def _set_pixmap(self) -> None:
        # The tricky part here is that the pixmap returned by
        # NameWindowPixmap gets invalidated every time the window's
        # viewable state changes.  ("viewable" here is the X term that
        # means "mapped, and all ancestors are also mapped".)  But
        # there is no X event that will tell you when a window's
        # viewability changes!
        # Instead, we have to find all ancestors,
        # and watch all of them for unmap and reparent events.  But
        # what about races?  I hear you cry.  By doing things in the
        # exact order:
        #   1) select for StructureNotify
        #   2) QueryTree to get parent
        #   3) repeat 1 & 2 up to the root
        #   4) call NameWindowPixmap
        # we are safe.  (I think.)
        listening : List[int] = []
        e = None
        try:
            world = get_world_window()
            wxid = None
            if world:
                wxid = world.get_window().get_xid()
            root = Gdk.Screen.get_default().get_root_window()
            rxid = root.get_xid()
            xid = X11Window.getParent(self.xid)
            while xid not in (0, rxid, wxid):
                # We have to use a lowlevel function to manipulate the
                # event selection here, because SubstructureRedirectMask
                # does not roundtrip through the GDK event mask
                # functions.  So if we used them, here, we would clobber
                # corral window selection masks, and those don't deserve
                # clobbering.  They are our friends!  X is driving me
                # slowly mad.
                parent = X11Window.getParent(xid)
                if not parent:
                    break
                X11Window.addXSelectInput(xid, StructureNotifyMask)
                add_event_receiver(xid, self, max_receivers=-1)
                listening.append(xid)
                xid = parent
            handle = XImage.get_xcomposite_pixmap(self.xid)
        except Exception:
            try:
                self._cleanup_listening(listening)
            except Exception:
                log(f"failed to cleanup listening for {listening}", exc_info=True)
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


    def do_xpra_damage_event(self, event) -> None:
        event.x += self._border_width
        event.y += self._border_width
        self.emit("contents-changed", event)

GObject.type_register(CompositeHelper)
