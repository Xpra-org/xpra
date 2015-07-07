# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
from xpra.gtk_common.gobject_util import one_arg_signal, AutoPropGObjectMixin
from xpra.x11.gtk2.gdk_bindings import (
            add_event_receiver,             #@UnresolvedImport
            remove_event_receiver,          #@UnresolvedImport
            get_parent)                     #@UnresolvedImport
from xpra.gtk_common.error import trap

from xpra.x11.gtk2.world_window import get_world_window
from xpra.x11.bindings.ximage import XImageBindings #@UnresolvedImport
XImage = XImageBindings()
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()
X11Window.ensure_XComposite_support()
X11Window.ensure_XDamage_support()

from xpra.log import Logger
log = Logger("x11", "window")


StructureNotifyMask = constants["StructureNotifyMask"]


class CompositeHelper(AutoPropGObjectMixin, gobject.GObject):

    XShmEnabled = True

    __gsignals__ = {
        "contents-changed": one_arg_signal,

        "xpra-damage-event": one_arg_signal,
        "xpra-unmap-event": one_arg_signal,
        "xpra-configure-event": one_arg_signal,
        "xpra-reparent-event": one_arg_signal,
        }

    # This may raise XError.
    def __init__(self, window, already_composited, use_shm=False):
        super(CompositeHelper, self).__init__()
        log("CompositeHelper.__init__(%#x, %s, %s)", window.xid, already_composited, use_shm)
        self._window = window
        self._already_composited = already_composited
        self._listening_to = None
        self._damage_handle = None
        self._use_shm = use_shm
        self._shm_handle = None
        self._contents_handle = None

    def __repr__(self):
        xid = None
        if self._window:
            xid = self._window.xid
        return "CompositeHelper(%#x)" % xid

    def setup(self):
        xwin = self._window.xid
        if not self._already_composited:
            X11Window.XCompositeRedirectWindow(xwin)
        self._border_width = X11Window.geometry_with_border(xwin)[-1]
        self.invalidate_pixmap()
        self._damage_handle = X11Window.XDamageCreate(xwin)
        log("CompositeHelper.setup() damage handle(%#x)=%#x", xwin, self._damage_handle)
        add_event_receiver(self._window, self)

    def destroy(self):
        if self._window is None:
            log.warn("composite window %s already destroyed!", self)
            return
        #clear the reference to the window early:
        win = self._window
        xwin = self._window.xid
        #Note: invalidate_pixmap()/_cleanup_listening() use self._window, but won't care if it's None
        self._window = None
        remove_event_receiver(win, self)
        self.invalidate_pixmap()
        if not self._already_composited:
            trap.swallow_synced(X11Window.XCompositeUnredirectWindow, xwin)
        if self._damage_handle:
            trap.swallow_synced(X11Window.XDamageDestroy, self._damage_handle)
            self._damage_handle = None
        if self._shm_handle:
            self._shm_handle.cleanup()
            self._shm_handle = None
        #note: this should be redundant since we cleared the
        #reference to self._window and shortcut out in do_get_property_contents_handle
        #but it's cheap anyway
        self.invalidate_pixmap()

    def acknowledge_changes(self):
        if self._shm_handle:
            self._shm_handle.discard()
        if self._damage_handle is not None and self._window is not None:
            #"Synchronously modifies the regions..." so unsynced?
            if not trap.swallow_synced(X11Window.XDamageSubtract, self._damage_handle):
                self.invalidate_pixmap()

    def invalidate_pixmap(self):
        log("invalidating named pixmap")
        if self._listening_to is not None:
            self._cleanup_listening(self._listening_to)
            self._listening_to = None
        if self._contents_handle:
            self._contents_handle.cleanup()
            self._contents_handle = None

    def _cleanup_listening(self, listening):
        if listening:
            # Don't want to stop listening to self._window!:
            assert self._window is None or self._window not in listening
            for w in listening:
                remove_event_receiver(w, self)

    def get_shm_handle(self):
        if not self._use_shm or not CompositeHelper.XShmEnabled:
            return None
        if self._shm_handle and self._shm_handle.get_size()!=self._window.get_size():
            #size has changed!
            #make sure the current wrapper gets garbage collected:
            self._shm_handle.cleanup()
            self._shm_handle = None
        if self._shm_handle is None:
            #make a new one:
            self._shm_handle = XImage.get_XShmWrapper(self._window.xid)
            if self._shm_handle is None:
                #failed (may retry)
                return None
            init_ok, retry_window, xshm_failed = self._shm_handle.setup()
            if not init_ok:
                #this handle is not valid, clear it:
                self._shm_handle = None
            if not retry_window:
                #and it looks like it is not worth re-trying this window:
                self._use_shm = False
            if xshm_failed:
                log.warn("disabling XShm support following irrecoverable error")
                CompositeHelper.XShmEnabled = False
        return self._shm_handle

    def get_contents_handle(self):
        if self._window is None:
            #shortcut out
            return  None
        if self._contents_handle is None:
            log("refreshing named pixmap")
            assert self._listening_to is None
            def set_pixmap():
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
                    root = self._window.get_screen().get_root_window()
                    world = get_world_window().window
                    win = get_parent(self._window)
                    while win not in (None, root, world) and win.get_parent() is not None:
                        # We have to use a lowlevel function to manipulate the
                        # event selection here, because SubstructureRedirectMask
                        # does not roundtrip through the GDK event mask
                        # functions.  So if we used them, here, we would clobber
                        # corral window selection masks, and those don't deserve
                        # clobbering.  They are our friends!  X is driving me
                        # slowly mad.
                        X11Window.addXSelectInput(win.xid, StructureNotifyMask)
                        add_event_receiver(win, self, max_receivers=-1)
                        listening.append(win)
                        win = get_parent(win)
                    handle = XImage.get_xcomposite_pixmap(self._window.xid)
                except Exception as e:
                    try:
                        self._cleanup_listening(listening)
                    except:
                        pass
                    raise
                if handle is None:
                    #avoid race during signal exit, which will clear self._window:
                    win = self._window
                    xid = 0
                    if win:
                        xid = win.xid
                    log("failed to name a window pixmap for %#x: %s", xid, e)
                    self._cleanup_listening(listening)
                else:
                    self._contents_handle = handle
                    # Don't save the listening set until after
                    # NameWindowPixmap has succeeded, to maintain our
                    # invariant:
                    self._listening_to = listening
            trap.swallow_synced(set_pixmap)
        return self._contents_handle


    def do_xpra_unmap_event(self, event):
        self.invalidate_pixmap()

    def do_xpra_configure_event(self, event):
        self._border_width = event.border_width
        self.invalidate_pixmap()

    def do_xpra_reparent_event(self, event):
        self.invalidate_pixmap()

    def do_xpra_damage_event(self, event):
        event.x += self._border_width
        event.y += self._border_width
        self.emit("contents-changed", event)

gobject.type_register(CompositeHelper)
