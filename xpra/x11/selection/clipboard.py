# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any, Final
from collections.abc import Callable

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.gobject import one_arg_signal
from xpra.x11.common import X11Event
from xpra.x11.error import xsync, xlog
from xpra.x11.prop import prop_set
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.selection.common import xatoms_to_strings, strings_to_xatoms, xfixes_selection_input
from xpra.clipboard.timeout import ClipboardTimeoutHelper
from xpra.log import Logger

GObject = gi_import("GObject")

log = Logger("x11", "clipboard")


IGNORED_PROPERTIES = (
    "_NET_WM_NAME", "WM_NAME", "_NET_WM_ICON_NAME", "WM_ICON_NAME",
    "WM_PROTOCOLS", "WM_NORMAL_HINTS", "WM_CLIENT_MACHINE", "WM_LOCALE_NAME",
    "_NET_WM_PID", "WM_CLIENT_LEADER", "_NET_WM_USER_TIME_WINDOW",
)
IGNORED_MESSAGES = (
    "_GTK_LOAD_ICONTHEMES",
)


def init_event_window() -> int:
    from xpra.x11.bindings.core import constants
    from xpra.x11.bindings.window import X11WindowBindings
    X11Window = X11WindowBindings()
    InputOnly: Final[int] = constants["InputOnly"]
    PropertyChangeMask: Final[int] = constants["PropertyChangeMask"]
    rxid = X11Window.get_root_xid()
    xid = X11Window.CreateWindow(rxid, -1, -1, event_mask=PropertyChangeMask, inputoutput=InputOnly)
    prop_set(xid, "WM_TITLE", "latin1", "Xpra-Clipboard")
    X11Window.selectSelectionInput(xid)
    log(f"init_event_window()={xid=}")
    return xid


def remove_event_window(xid: int) -> None:
    with xlog:
        from xpra.x11.bindings.window import X11WindowBindings
        X11Window = X11WindowBindings()
        # X11Window.Unmap(xid)
        X11Window.DestroyWindow(xid)


class X11Clipboard(ClipboardTimeoutHelper, GObject.GObject):
    # handle signals from the X11 bindings,
    # and dispatch them to the proxy handling the selection specified:
    __gsignals__ = {
        "x11-client-message-event": one_arg_signal,
        "x11-selection-request": one_arg_signal,
        "x11-selection-clear": one_arg_signal,
        "x11-property-notify-event": one_arg_signal,
        "x11-xfixes-selection-notify-event": one_arg_signal,
    }

    def __init__(self, send_packet_cb: Callable, progress_cb=noop, **kwargs):
        GObject.GObject.__init__(self)
        with xsync:
            self.event_window_xid = init_event_window()
            add_event_receiver(self.event_window_xid, self)
            # gtk must know about this window before we use it:
            from xpra.x11.common import get_pywindow
            self.window = get_pywindow(self.event_window_xid)
        super().__init__(send_packet_cb, progress_cb, **kwargs)

    def __repr__(self):
        return "X11Clipboard"

    def cleanup_window(self) -> None:
        xid = self.event_window_xid
        if xid:
            self.event_window_xid = 0
            remove_event_receiver(xid, self)
            remove_event_window(xid)

    def cleanup(self) -> None:
        ClipboardTimeoutHelper.cleanup(self)
        self.cleanup_window()

    def make_proxy(self, selection):
        from xpra.x11.selection.proxy import ClipboardProxy
        xid = self.event_window_xid
        proxy = ClipboardProxy(xid, selection)
        proxy.set_want_targets(self._want_targets)
        proxy.set_direction(self.can_send, self.can_receive)
        proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
        proxy.connect("send-clipboard-request", self._send_clipboard_request_handler)
        from xpra.x11.bindings.core import get_root_xid
        rxid = get_root_xid()
        xfixes_selection_input(xid, selection)
        xfixes_selection_input(rxid, selection)
        return proxy

    ############################################################################
    # X11 event handlers:
    # we dispatch them to the proxy handling the selection specified
    ############################################################################
    def do_x11_selection_request(self, event: X11Event) -> None:
        log("do_x11_selection_request(%s)", event)
        proxy = self._get_proxy(event.selection)
        if proxy:
            proxy.do_selection_request_event(event)

    def do_x11_selection_clear(self, event: X11Event) -> None:
        log("do_x11_selection_clear(%s)", event)
        proxy = self._get_proxy(event.selection)
        if proxy:
            proxy.do_selection_clear_event(event)

    def do_x11_xfixes_selection_notify_event(self, event: X11Event) -> None:
        log("do_x11_xfixes_selection_notify_event(%s)", event)
        proxy = self._get_proxy(event.selection)
        if proxy:
            proxy.do_selection_notify_event(event)

    def do_x11_client_message_event(self, event: X11Event) -> None:
        message_type = event.message_type
        if message_type in IGNORED_MESSAGES:
            log("ignored clipboard client message: %s", message_type)
            return
        log.info(f"Unexpected X11 message received by clipboard window {event.window:x}")
        log.info(f" {event}")

    def do_x11_property_notify_event(self, event: X11Event) -> None:
        if event.atom in IGNORED_PROPERTIES:
            # these properties are populated by GTK when we create the window,
            # no need to log them
            return
        log("do_x11_property_notify_event(%s)", event)
        # ie: atom=PRIMARY-TARGETS
        # ie: atom=PRIMARY-VALUE
        parts = event.atom.split("-", 1)
        if len(parts) != 2:
            return
        selection = parts[0]  # ie: PRIMARY
        # target = parts[1]           # ie: VALUE
        proxy = self._get_proxy(selection)
        if proxy:
            proxy.do_property_notify(event)

    ############################################################################
    # x11 specific munging support:
    ############################################################################

    def _munge_raw_selection_to_wire(self, target, dtype, dformat, data) -> tuple[Any, Any]:
        if dformat == 32 and dtype in ("ATOM", "ATOM_PAIR"):
            return "atoms", self.remote_targets(xatoms_to_strings(data))
        return super()._munge_raw_selection_to_wire(target, dtype, dformat, data)

    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data) -> bytes | str:
        if encoding == "atoms":
            return strings_to_xatoms(self.local_targets(data))
        return super()._munge_wire_selection_to_raw(encoding, dtype, dformat, data)


GObject.type_register(X11Clipboard)
