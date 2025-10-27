# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envbool
from xpra.util.gobject import one_arg_signal
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.error import xsync, xswallow, xlog, XError
from xpra.x11.common import Unmanageable, X11Event

from xpra.x11.bindings.ximage import XImageBindings
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.bindings.damage import init_damage_events, XDamageBindings
from xpra.log import Logger

log = Logger("x11", "window", "damage")

XImage = XImageBindings()
X11Window = X11WindowBindings()
XDamage = XDamageBindings()
XDamage.ensure_XDamage_support()
assert init_damage_events()

USE_XSHM = envbool("XPRA_XSHM", True)
if USE_XSHM:
    try:
        from xpra.x11.bindings.shm import XShmBindings
        XShm = XShmBindings()
    except ImportError as e:
        log.warn("Warning: unable to load the X11 Shm bindings")
        log.warn(" this can severely affect performance")
        log.warn(" %s", e)
        USE_XSHM = False

XPresent = None
USE_XPRESENT = envbool("XPRA_XPRESENT", False)
if USE_XPRESENT:
    try:
        from xpra.x11.bindings.present import XPresentBindings, init_present_events
        init_present_events()
        XPresent = XPresentBindings()
    except ImportError:
        log.warn("Warning: unable to load the X11 Present bindings", exc_info=True)


class WindowDamageHandler:
    XShmEnabled = USE_XSHM
    MAX_RECEIVERS = 3

    __common_gsignals__ = {
        "x11-damage-event": one_arg_signal,
        "x11-unmap-event": one_arg_signal,
        "x11-configure-event": one_arg_signal,
        "x11-reparent-event": one_arg_signal,
    }

    # This may raise XError.
    def __init__(self, xid: int, use_xshm: bool = USE_XSHM):
        if not isinstance(xid, int):
            raise ValueError(f"xid must be an int, not a {type(xid)}")
        self.xid: int = xid
        log("WindowDamageHandler.__init__(%#x, %s)", self.xid, use_xshm)
        self._use_xshm: bool = use_xshm
        self._damage_handle: int = 0
        self._xshm_handle = None  # XShmWrapper instance
        self._present_handle: int = 0
        self._contents_handle = None  # DrawableWrapper instance
        self._border_width: int = 0

    def __repr__(self):
        return f"WindowDamageHandler({self.xid:x})"

    def setup(self) -> None:
        self.invalidate_pixmap()
        geom = X11Window.geometry_with_border(self.xid)
        if geom is None:
            raise Unmanageable(f"window {self.xid:x} disappeared already")
        self._border_width = geom[-1]
        self._damage_handle = XDamage.XDamageCreate(self.xid)
        log("damage handle(%#x)=%#x", self.xid, self._damage_handle)
        if XPresent:
            self._present_handle = XPresent.SelectInput(self.xid)
        add_event_receiver(self.xid, self, self.MAX_RECEIVERS)

    def destroy(self) -> None:
        if not self.xid:
            log.error(f"Error: damage window handler for {self.xid:x} already cleaned up!")
        self.do_destroy()

    def do_destroy(self) -> None:
        remove_event_receiver(self.xid, self)
        self.xid = 0
        self.destroy_damage_handle()
        self.destroy_present_handle()

    def destroy_damage_handle(self) -> None:
        log("destroy_damage_handle()")
        self.invalidate_pixmap()
        dh = self._damage_handle
        if dh:
            self._damage_handle = 0
            with xlog:
                XDamage.XDamageDestroy(dh)
        sh = self._xshm_handle
        if sh:
            self._xshm_handle = None
            with xlog:
                sh.cleanup()
        # note: this should be redundant, but it's cheap and safer
        self.invalidate_pixmap()

    def destroy_present_handle(self) -> None:
        log("destroy_present_handle()")
        ph = self._present_handle
        if ph:
            self._present_handle = 0
            with xlog:
                XPresent.FreeInput(self.xid, ph)

    def acknowledge_changes(self) -> None:
        sh = self._xshm_handle
        dh = self._damage_handle
        log("acknowledge_changes() xid=%#x, xshm handle=%s, damage handle=%#x", self.xid, sh, dh)
        if sh:
            sh.discard()
        if dh and self.xid:
            # "Synchronously modifies the regions..." so unsynced?
            with xlog:
                XDamage.XDamageSubtract(dh)
            self.invalidate_pixmap()

    def invalidate_pixmap(self) -> None:
        ch = self._contents_handle
        log("invalidating named pixmap, contents handle=%s", ch)
        if ch:
            self._contents_handle = None
            with xlog:
                ch.cleanup()

    def has_xshm(self) -> bool:
        return self._use_xshm and WindowDamageHandler.XShmEnabled and XShm and XShm.has_XShm()

    def get_xshm_handle(self):
        if not self.has_xshm():
            return None
        if self._xshm_handle:
            sw, sh = self._xshm_handle.get_size()
            with xswallow:
                geom = X11Window.getGeometry(self.xid)
            if not geom:
                return None
            ww, wh = geom[2:4]
            if sw != ww or sh != wh:
                # size has changed!
                # make sure the current wrapper gets garbage collected:
                self._xshm_handle.cleanup()
                self._xshm_handle = None
        if self._xshm_handle is None:
            # make a new one:
            self._xshm_handle = XShm.get_XShmWrapper(self.xid)
            if self._xshm_handle is None:
                # failed (may retry)
                return None
            init_ok, retry_window, xshm_failed = self._xshm_handle.setup()
            if not init_ok:
                # this handle is not valid, clear it:
                self._xshm_handle = None
            if not retry_window:
                # and it looks like it is not worth re-trying this window:
                self._use_xshm = False
            if xshm_failed:
                log.warn("Warning: disabling XShm support following irrecoverable error")
                WindowDamageHandler.XShmEnabled = False
        return self._xshm_handle

    def _set_pixmap(self) -> None:
        self._contents_handle = XImage.get_xwindow_pixmap_wrapper(self.xid)

    def get_contents_handle(self):
        if not self.xid:
            # shortcut out
            return None
        if self._contents_handle is None:
            log("refreshing named pixmap")
            with xlog:
                self._set_pixmap()
        return self._contents_handle

    def get_image(self, x: int, y: int, width: int, height: int):
        handle = self.get_contents_handle()
        if handle is None:
            log("get_image(..) pixmap is None for window %#x", self.xid)
            return None

        # try XShm:
        shm = None  # XShmWrapper instance
        try:
            with xsync:
                shm = self.get_xshm_handle()
                if shm:
                    shm_image = shm.get_image(handle.get_drawable(), x, y, width, height)
                    if shm_image:
                        return shm_image
        except XError as e:
            log("get_image%s", (x, y, width, height), exc_info=True)
            if e.msg.startswith("BadMatch") or e.msg.startswith("BadWindow"):
                log("BadMatch / BadWindow ignored - window %#x already gone?", self.xid)
            elif e.msg.startswith("BadShmSeg"):
                log.error("Error accessing XShm image of window %#x", self.xid)
                log.estr(e)
            else:
                log.warn("Warning: failed to get image for window %#x", self.xid)
                log.warn(" %s", e)
            # better try using another shm handle next time:
            if shm:
                shm.discard()
        try:
            w = min(handle.get_width(), width)
            h = min(handle.get_height(), height)
            if w != width or h != height:
                log("get_image(%s, %s, %s, %s) clamped to pixmap dimensions: %sx%s", x, y, width, height, w, h)
            with xsync:
                return handle.get_image(x, y, w, h)
        except XError as e:
            if e.msg.startswith("BadMatch"):
                log("get_image(%s, %s, %s, %s) get_image BadMatch ignored (window already gone?)", x, y, width, height)
            else:
                log.warn("Warning: cannot capture image of geometry %", (x, y, width, height), exc_info=True)
            return None

    def do_x11_damage_event(self, _event: X11Event) -> None:
        raise NotImplementedError()

    def do_x11_reparent_event(self, _event: X11Event) -> None:
        self.invalidate_pixmap()

    def xpra_unmap_event(self, _event) -> None:
        self.invalidate_pixmap()

    def do_x11_configure_event(self, event: X11Event) -> None:
        self._border_width = event.border_width
        self.invalidate_pixmap()
