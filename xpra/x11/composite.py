# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final

from xpra.os_util import gi_import
from xpra.util.gobject import one_arg_signal
from xpra.x11.common import X11Event
from xpra.x11.error import xlog, xsync, xswallow, XError
from xpra.x11.damage import WindowDamageHandler
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.bindings.core import constants, get_root_xid
from xpra.x11.bindings.ximage import XImageBindings
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.bindings.composite import XCompositeBindings
from xpra.log import Logger

log = Logger("x11", "window", "damage")

GObject = gi_import("GObject")

XImage = XImageBindings()
X11Window = X11WindowBindings()
X11Composite = XCompositeBindings()
X11Composite.ensure_XComposite_support()

StructureNotifyMask: Final[int] = constants["StructureNotifyMask"]

rxid = get_root_xid()

# windows we have redirected before they were mapped,
# waiting for a `CompositeHelper` to take ownership of the redirection:
pre_redirected: set[int] = set()


def pre_redirect(xid: int) -> bool:
    """
    Redirect a window before it is mapped, so that its backing pixmap
    is allocated as soon as it becomes viewable and no contents are lost.
    `CompositeHelper.setup()` will take over this redirection,
    otherwise it must be cancelled with `cancel_pre_redirect`.
    """
    if xid in pre_redirected:
        return True
    try:
        with xsync:
            X11Composite.XCompositeRedirectWindow(xid)
    except XError as e:
        # the window may already be gone, or it may be an InputOnly window
        log("failed to pre-redirect %#x: %s", xid, e)
        return False
    log("pre-redirected %#x", xid)
    pre_redirected.add(xid)
    return True


def cancel_pre_redirect(xid: int, unredirect=True) -> None:
    """
    Forget about a pre-redirected window,
    and un-redirect it unless the window is already gone.
    """
    if xid not in pre_redirected:
        return
    pre_redirected.discard(xid)
    log("cancel_pre_redirect(%#x, %s)", xid, unredirect)
    if unredirect:
        with xswallow:
            X11Composite.XCompositeUnredirectWindow(xid)


def cancel_all_pre_redirects() -> None:
    for xid in tuple(pre_redirected):
        cancel_pre_redirect(xid)


class CompositeHelper(WindowDamageHandler, GObject.GObject):
    __gsignals__ = WindowDamageHandler.__common_gsignals__.copy()
    __gsignals__ |= {
        # emit:
        "contents-changed": one_arg_signal,
    }

    # This may raise XError.
    def __init__(self, xid: int):
        WindowDamageHandler.__init__(self, xid)
        GObject.GObject.__init__(self)
        self._listening_to: list[int] = []

    def __repr__(self):
        return f"CompositeHelper({self.xid:x})"

    def setup(self) -> None:
        if self.xid in pre_redirected:
            # already redirected at `CreateNotify` time, take ownership:
            # (a second manual redirection would fail with `BadAccess`)
            pre_redirected.discard(self.xid)
            log("claimed pre-redirected window %#x", self.xid)
        else:
            X11Composite.XCompositeRedirectWindow(self.xid)
        WindowDamageHandler.setup(self)

    def do_destroy(self) -> None:
        with xlog:
            X11Composite.XCompositeUnredirectWindow(self.xid)
            WindowDamageHandler.do_destroy(self)

    def invalidate_pixmap(self) -> None:
        if lt := self._listening_to:
            self._listening_to = []
            self._cleanup_listening(lt)
        WindowDamageHandler.invalidate_pixmap(self)

    def _cleanup_listening(self, listening: list[int]) -> None:
        if listening:
            for w in listening:
                # Don't want to stop listening to our xid!:
                if w != self.xid:
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
        listening: list[int] = []
        try:
            xid = X11Window.getParent(self.xid)
            while xid not in (0, rxid):
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
            pixmap = X11Composite.XCompositeNameWindowPixmap(self.xid)
            # `wrap_pixmap` takes ownership of the pixmap unconditionally:
            # it is freed with the wrapper, or immediately if the wrapping
            # fails or raises - so there is nothing to free here
            handle = XImage.wrap_pixmap(pixmap)
        except Exception:
            try:
                self._cleanup_listening(listening)
            except Exception:
                log(f"failed to cleanup listening for {listening}", exc_info=True)
            raise
        if handle is None:
            log("failed to name a window pixmap for %#x", self.xid)
            self._cleanup_listening(listening)
        else:
            self._contents_handle = handle
            # Don't save the listening set until after
            # NameWindowPixmap has succeeded, to maintain our
            # invariant:
            self._listening_to = listening

    def do_x11_damage_event(self, event: X11Event) -> None:
        event.x += self._border_width
        event.y += self._border_width
        self.emit("contents-changed", event)


GObject.type_register(CompositeHelper)
