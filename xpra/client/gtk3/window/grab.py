# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.env import envbool, IgnoreWarningsContext
from xpra.gtk.util import GRAB_STATUS_STRING
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.platform.gui import pointer_grab, pointer_ungrab
from xpra.log import Logger

Gdk = gi_import("Gdk")

log = Logger("window", "grab")

AUTOGRAB_MODES = os.environ.get("XPRA_AUTOGRAB_MODES", "shadow,desktop,monitors").split(",")
AUTOGRAB_WITH_POINTER = envbool("XPRA_AUTOGRAB_WITH_POINTER", True)

GRAB_EVENT_MASK: Gdk.EventMask = Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
GRAB_EVENT_MASK |= Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.POINTER_MOTION_HINT_MASK
GRAB_EVENT_MASK |= Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
GRAB_EVENT_MASK |= Gdk.EventMask.FOCUS_CHANGE_MASK


class GrabWindow(GtkStubWindow):

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.init_grab()

    def get_window_event_mask(self) -> Gdk.EventMask:
        return Gdk.EventMask.FOCUS_CHANGE_MASK

    def init_grab(self) -> None:
        self.when_realized("init-grab", self.do_init_grab)

    def do_init_grab(self) -> None:
        self.connect("enter-notify-event", self.on_enter_notify_event)
        self.connect("leave-notify-event", self.on_leave_notify_event)
        self.connect("grab-broken-event", self.grab_broken)

    def grab_broken(self, win, event) -> None:
        log("grab_broken%s", (win, event))
        self._client._window_with_grab = None

    def _focus_change(self, *args) -> None:
        assert not self._override_redirect
        htf = self.has_toplevel_focus()
        log("%s focus_change%s has-toplevel-focus=%s, _been_mapped=%s", self, args, htf, self._been_mapped)
        if self._been_mapped:
            self._focus_latest = htf
            self.schedule_recheck_focus()

    def on_enter_notify_event(self, window, event) -> None:
        log("on_enter_notify_event(%s, %s)", window, event)
        if AUTOGRAB_WITH_POINTER:
            self.may_autograb()

    def on_leave_notify_event(self, window, event) -> None:
        info = {}
        for attr in ("detail", "focus", "mode", "subwindow", "type", "window"):
            info[attr] = getattr(event, attr, None)
        log("on_leave_notify_event(%s, %s) crossing event fields: %s", window, event, info)
        if AUTOGRAB_WITH_POINTER and (event.subwindow or event.detail == Gdk.NotifyType.NONLINEAR_VIRTUAL):
            self.keyboard_ungrab()

    def may_autograb(self) -> bool:
        server_mode = self._client._remote_server_mode
        autograb = AUTOGRAB_MODES and any(x == "*" or server_mode.find(x) >= 0 for x in AUTOGRAB_MODES)
        log("may_autograb() server-mode=%s, autograb(%s)=%s", server_mode, AUTOGRAB_MODES, autograb)
        if autograb:
            self.keyboard_grab()
        return autograb

    def keyboard_ungrab(self, *args) -> None:
        log("keyboard_ungrab%s", args)
        gdkwin = self.get_window()
        if gdkwin:
            d = gdkwin.get_display()
            if d:
                seat = d.get_default_seat()
                if seat:
                    seat.ungrab()
                    self._client.keyboard_grabbed = False

    def keyboard_grab(self, *args) -> None:
        log("keyboard_grab%s", args)
        gdkwin = self.get_window()
        r = Gdk.GrabStatus.FAILED
        seat = None
        if gdkwin:
            self.add_events(Gdk.EventMask.ALL_EVENTS_MASK)
            d = gdkwin.get_display()
            if d:
                seat = d.get_default_seat()
                if seat:
                    capabilities = Gdk.SeatCapabilities.KEYBOARD
                    owner_events = True
                    cursor = None
                    event = None
                    r = seat.grab(gdkwin, capabilities, owner_events, cursor, event, None, None)
                    log("%s.grab(..)=%s", seat, r)
        self._client.keyboard_grabbed = r == Gdk.GrabStatus.SUCCESS
        log("keyboard_grab%s %s.grab(..)=%s, keyboard_grabbed=%s",
            args, seat, GRAB_STATUS_STRING.get(r), self._client.keyboard_grabbed)

    def toggle_keyboard_grab(self) -> None:
        grabbed = self._client.keyboard_grabbed
        log("toggle_keyboard_grab() grabbed=%s", grabbed)
        if grabbed:
            self.keyboard_ungrab()
        else:
            self.keyboard_grab()

    def pointer_grab(self, *args) -> None:
        gdkwin = self.get_window()
        # try platform specific variant first:
        if pointer_grab(gdkwin):
            self._client.pointer_grabbed = self.wid
            log(f"{pointer_grab}({gdkwin}) success")
            return
        with IgnoreWarningsContext():
            r = Gdk.pointer_grab(gdkwin, True, GRAB_EVENT_MASK, gdkwin, None, Gdk.CURRENT_TIME)
        if r == Gdk.GrabStatus.SUCCESS:
            self._client.pointer_grabbed = self.wid
        log("pointer_grab%s Gdk.pointer_grab(%s, True)=%s, pointer_grabbed=%s",
            args, self.get_window(), GRAB_STATUS_STRING.get(r), self._client.pointer_grabbed)

    def pointer_ungrab(self, *args) -> None:
        gdkwin = self.get_window()
        if pointer_ungrab(gdkwin):
            self._client.pointer_grabbed = None
            log(f"{pointer_ungrab}({gdkwin}) success")
            return
        log("pointer_ungrab%s pointer_grabbed=%s",
            args, self._client.pointer_grabbed)
        self._client.pointer_grabbed = None
        gdkwin = self.get_window()
        if gdkwin:
            d = gdkwin.get_display()
            if d:
                d.pointer_ungrab(Gdk.CURRENT_TIME)

    def toggle_pointer_grab(self) -> None:
        pg = self._client.pointer_grabbed
        log("toggle_pointer_grab() pointer_grabbed=%s, our id=%s", pg, self.wid)
        if pg == self.wid:
            self.pointer_ungrab()
        else:
            self.pointer_grab()
