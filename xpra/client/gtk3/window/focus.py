# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import noop
from xpra.os_util import gi_import, WIN32, OSX
from xpra.util.system import is_X11
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.util.gobject import one_arg_signal
from xpra.gtk.util import ds_inited
from xpra.log import Logger

GLib = gi_import("GLib")
Gdk = gi_import("Gdk")

log = Logger("focus", "grab")

NotifyInferior = 2

FOCUS_RECHECK_DELAY = envint("XPRA_FOCUS_RECHECK_DELAY", 0)
AUTOGRAB_WITH_FOCUS = envbool("XPRA_AUTOGRAB_WITH_FOCUS", False)


class FocusWindow(GtkStubWindow):
    __gsignals__ = {
        "x11-focus-out-event": one_arg_signal,
        "x11-focus-in-event": one_arg_signal,
    }

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self._focus_latest = None
        self.recheck_focus_timer: int = 0
        self.remove_event_receiver = noop
        self.init_focus()

    def cleanup(self):
        self.remove_event_receiver()
        self.cancel_focus_timer()
        if self._client.has_focus(self.wid):
            self._unfocus()

    def get_info(self) -> dict[str, Any]:
        return {
            "focused": bool(self._focus_latest),
        }

    def get_window_event_mask(self) -> Gdk.EventMask:
        return Gdk.EventMask.FOCUS_CHANGE_MASK

    def init_focus(self) -> None:
        self.when_realized("init-focus", self.do_init_focus)

    def do_init_focus(self) -> None:
        # hook up the X11 gdk event notifications,
        # so we can get focus-out when grabs are active:
        if not (WIN32 or OSX) and is_X11():
            try:
                from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
            except ImportError as e:
                log("do_init_focus()", exc_info=True)
                if not ds_inited():
                    log.warn("Warning: missing Gdk X11 bindings:")
                    log.warn(" %s", e)
                    log.warn(" you may experience window focus issues")
            else:
                log("adding event receiver so we can get FocusIn and FocusOut events whilst grabbing the keyboard")
                xid = self.get_window().get_xid()
                add_event_receiver(xid, self)

                def remove_hook() -> None:
                    remove_event_receiver(xid, self)
                self.remove_event_receiver = remove_hook

        # other platforms should be getting regular focus events instead:

        def focus_in(_window, event) -> None:
            log("focus-in-event for wid=%#x", self.wid)
            self.do_x11_focus_in_event(event)

        def focus_out(_window, event) -> None:
            log("focus-out-event for wid=%#x", self.wid)
            self.do_x11_focus_out_event(event)

        self.connect("focus-in-event", focus_in)
        self.connect("focus-out-event", focus_out)
        if not self._override_redirect:
            self.connect("notify::has-toplevel-focus", self._focus_change)

    def _focus_change(self, *args) -> None:
        assert not self._override_redirect
        htf = self.has_toplevel_focus()
        log("%s focus_change%s has-toplevel-focus=%s, _been_mapped=%s", self, args, htf, self._been_mapped)
        if self._been_mapped:
            self._focus_latest = htf
            self.schedule_recheck_focus()

    def recheck_focus(self) -> None:
        self.recheck_focus_timer = 0
        self.send_latest_focus()

    def send_latest_focus(self) -> None:
        focused = self._client._focused
        log("send_latest_focus() wid=%#x, focused=%s, latest=%s", self.wid, focused, self._focus_latest)
        if self._focus_latest:
            self._focus()
        else:
            self._unfocus()

    def _focus(self) -> bool:
        change = self._client.update_focus(self.wid, True)
        if change and AUTOGRAB_WITH_FOCUS:
            # soft dependency on GrabWindow:
            autograb = getattr(self, "may_autograb", noop)
            autograb()
        return change

    def _unfocus(self) -> bool:
        client = self._client
        client.window_ungrab()
        if client.pointer_grabbed and client.pointer_grabbed == self.wid:
            # we lost focus, assume we also lost the grab:
            client.pointer_grabbed = None
        changed = super()._unfocus()
        if changed and AUTOGRAB_WITH_FOCUS:
            # soft dependency on GrabWindow:
            ungrab = getattr(self, "keyboard_ungrab", noop)
            ungrab()
        return changed

    def cancel_focus_timer(self) -> None:
        rft = self.recheck_focus_timer
        if rft:
            self.recheck_focus_timer = 0
            GLib.source_remove(rft)

    def schedule_recheck_focus(self) -> None:
        if self._override_redirect:
            # never send focus events for OR windows
            return
        # we receive pairs of FocusOut + FocusIn following a keyboard grab,
        # so we recheck the focus status via this timer to skip unnecessary churn
        if FOCUS_RECHECK_DELAY < 0:
            self.recheck_focus()
        elif not self.recheck_focus_timer:
            log(f"will recheck focus in {FOCUS_RECHECK_DELAY}ms")
            self.recheck_focus_timer = GLib.timeout_add(FOCUS_RECHECK_DELAY, self.recheck_focus)

    def do_x11_focus_out_event(self, event) -> None:
        log("do_x11_focus_out_event(%s)", event)
        # `detail` is only available with X11 clients,
        # but this method can be called by other clients (see `focus_out`):
        detail = getattr(event, "detail", 0)
        if detail == NotifyInferior:
            log("dropped NotifyInferior focus event")
            return
        self._focus_latest = False
        self.schedule_recheck_focus()

    def do_x11_focus_in_event(self, event) -> None:
        log("do_x11_focus_in_event(%s) been_mapped=%s", event, self._been_mapped)
        if self._been_mapped:
            self._focus_latest = True
            self.schedule_recheck_focus()
