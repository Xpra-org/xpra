# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from typing import Sequence, Any, Final

from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.clipboard.common import ClipboardCallback, env_timeout
from xpra.clipboard.targets import must_discard_extra, must_discard, TEXT_TARGETS
from xpra.clipboard.proxy import ClipboardProxyCore
from xpra.util.env import first_time
from xpra.util.gobject import one_arg_signal, n_arg_signal
from xpra.util.str_fn import Ellipsizer, bytestostr, csv, memoryview_to_bytes
from xpra.x11.selection.common import xatoms_to_strings, strings_to_xatoms
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import PropertyError, X11WindowBindings
from xpra.x11.common import X11Event
from xpra.x11.error import xsync, XError
from xpra.x11.info import get_wininfo
from xpra.log import Logger

GObject = gi_import("GObject")
GLib = gi_import("GLib")

log = Logger("x11", "clipboard")

CONVERT_TIMEOUT = env_timeout("CONVERT", 100)

X11Window = X11WindowBindings()
CurrentTime: Final[int] = constants["CurrentTime"]
StructureNotifyMask: Final[int] = constants["StructureNotifyMask"]

MAX_DATA_SIZE: int = 4 * 1024 * 1024
RECLAIM = envbool("XPRA_CLIPBOARD_RECLAIM", True)
BLOCKLISTED_CLIPBOARD_CLIENTS: list[str] = os.environ.get(
    "XPRA_BLOCKLISTED_CLIPBOARD_CLIENTS",
    "clipit,Software,gnome-shell"
).split(",")
log("BLOCKLISTED_CLIPBOARD_CLIENTS=%s", BLOCKLISTED_CLIPBOARD_CLIENTS)
DEFAULT_TRANSLATED_TARGETS: str = "#".join(
    (
        "text/plain;charset=utf-8:UTF8_STRING,text/plain,public.utf8-plain-text",
        "TEXT:text/plain,text/plain;charset=utf-8,UTF8_STRING,public.utf8-plain-text",
        "STRING:text/plain,text/plain;charset=utf-8,UTF8_STRING,public.utf8-plain-text",
        "UTF8_STRING:text/plain;charset=utf-8,text/plain,public.utf8-plain-text",
        "GTK_TEXT_BUFFER_CONTENTS:UTF8_STRING,text/plain,public.utf8-plain-text",
    )
)


def parse_translated_targets(v: str) -> dict[str, list[str]]:
    trans: dict[str, list[str]] = {}
    # we can't use ";" or "/" as separators
    # because those are used in mime-types,
    # and we use "," and ":" ourselves..
    for entry in v.split("#"):
        parts = entry.split(":", 1)
        if len(parts) != 2:
            log.warn("Warning: invalid clipboard translated target:")
            log.warn(f" {entry!r}")
            continue
        src_target = parts[0]
        dst_targets = parts[1].split(",")
        trans[src_target] = dst_targets
    return trans


TRANSLATED_TARGETS = parse_translated_targets(os.environ.get(
    "XPRA_CLIPBOARD_TRANSLATED_TARGETS",
    DEFAULT_TRANSLATED_TARGETS)
)
log("TRANSLATED_TARGETS=%s", TRANSLATED_TARGETS)


class ClipboardProxy(ClipboardProxyCore, GObject.GObject):
    __gsignals__ = {
        "x11-client-message-event": one_arg_signal,
        "x11-selection-request": one_arg_signal,
        "x11-selection-clear": one_arg_signal,
        "x11-property-notify-event": one_arg_signal,
        "x11-xfixes-selection-notify-event": one_arg_signal,
        #
        "send-clipboard-token": one_arg_signal,
        "send-clipboard-request": n_arg_signal(2),
    }

    def __init__(self, xid: int, selection="CLIPBOARD"):
        ClipboardProxyCore.__init__(self, selection)
        GObject.GObject.__init__(self)
        self.xid: int = xid
        self.owned: bool = False
        self._want_targets: bool = False
        self.remote_requests: dict[str, list[tuple[int, str, str, float]]] = {}
        self.local_requests: dict[str, dict[int, tuple[int, ClipboardCallback]]] = {}
        self.local_request_counter: int = 0
        self.targets: Sequence[str] = ()
        self.target_data: dict[str, tuple[str, int, Any]] = {}
        self.incr_data_size: int = 0
        self.incr_data_type: str = ""
        self.incr_data_chunks: list[bytes] = []
        self.incr_data_timer: int = 0

    def reset_incr_data(self) -> None:
        self.incr_data_size: int = 0
        self.incr_data_type: str = ""
        self.incr_data_chunks: list[bytes] = []
        self.incr_data_timer: int = 0

    def __repr__(self):
        return f"X11ClipboardProxy({self._selection})"

    def cleanup(self) -> None:
        log("%s.cleanup()", self)
        # give up selection:
        # (disabled because this crashes GTK3 on exit)
        # if self.owned:
        #    self.owned = False
        #    with xswallow:
        #        X11Window.XSetSelectionOwner(0, self._selection)
        # empty replies for all pending requests,
        # this will also cancel any pending timers:
        rr = self.remote_requests
        self.remote_requests = {}
        for target in rr:
            self.got_contents(target)
        lr = self.local_requests
        self.local_requests = {}
        for target in lr:
            self.got_local_contents(target)

    def got_token(self, targets, target_data=None, claim=True, synchronous_client=False) -> None:
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, can-receive=%s",
            self._selection, targets, Ellipsizer(target_data), claim, self._can_receive)
        if claim:
            self._have_token = True
        if self._can_receive:
            if target_data:
                # ensure we also expose the targets in the target_data:
                # ie: {'UTF8_STRING': ('UTF8_STRING', 8, b'foobar')}
                targets = list(targets) + list(target_data.keys())
            self.targets = tuple(bytestostr(x) for x in (targets or ()))
            self.target_data = target_data or {}
            if targets and claim:
                xatoms = strings_to_xatoms(targets)
                self.got_contents("TARGETS", "ATOM", 32, xatoms)
            if target_data and synchronous_client and claim:
                targets = target_data.keys()
                text_targets = tuple(x for x in targets if x in TEXT_TARGETS)
                if text_targets:
                    target = text_targets[0]
                    dtype, dformat, data = target_data.get(target)
                    dtype = bytestostr(dtype)
                    self.got_contents(target, dtype, dformat, data)
        if self._can_receive and claim:
            self.claim()

    def claim(self) -> None:
        time = 0
        try:
            with xsync:
                owner = X11Window.XGetSelectionOwner(self._selection)
                self.owned = owner == self.xid
                if RECLAIM or not self.owned:
                    setsel = X11Window.XSetSelectionOwner(self.xid, self._selection, time)
                    owner = X11Window.XGetSelectionOwner(self._selection)
                    self.owned = owner == self.xid
                    log("claim_selection: set selection owner returned %s, owner=%#x, owned=%s",
                        setsel, owner, self.owned)
                else:
                    log("we already owned the %r selection", self._selection)
                if not self.owned:
                    log.warn("Warning: we failed to get ownership of the '%s' clipboard selection", self._selection)
                    return
                # send announcement:
                log("claim_selection: sending message to root window")
                from xpra.x11.bindings.core import get_root_xid
                root_xid = get_root_xid()
                event_mask = StructureNotifyMask
                X11Window.sendClientMessage(root_xid, root_xid, False, event_mask, "MANAGER",
                                            time or CurrentTime, self._selection, self.xid)
                log(f"claim_selection {self._selection} done")
        except Exception:
            log("failed to claim selection '%s'", self._selection, exc_info=True)
            raise

    def do_x11_client_message_event(self, event: X11Event) -> None:
        if event.message_type == "_GTK_LOAD_ICONTHEMES":
            # ignore this crap
            return
        log.info(f"Unexpected X11 message received by clipboard window {event.window:x}")
        log.info(f" {event}")

    ############################################################################
    # forward local requests to the remote clipboard:
    ############################################################################
    def do_selection_request_event(self, event) -> None:
        # an app is requesting clipboard data from us
        log("do_selection_request_event(%s)", event)
        requestor = event.requestor
        if not requestor:
            log.warn("Warning: clipboard selection request without a window, dropped")
            return
        wininfo = get_wininfo(requestor)
        prop = event.property
        target = str(event.target)
        log("clipboard request for %s from window %s, target=%s, prop=%s",
            self._selection, wininfo, target, prop)
        if not target:
            log.warn("Warning: ignoring clipboard request without a TARGET")
            log.warn(" coming from %s", wininfo)
            return
        if not prop:
            log.warn("Warning: ignoring clipboard request without a property")
            log.warn(" coming from %s", wininfo)
            return

        def nodata() -> None:
            self.set_selection_response(requestor, target, prop, "STRING", 8, b"", time=event.time)

        if not self._enabled:
            nodata()
            return
        blocklisted = tuple(client for client in BLOCKLISTED_CLIPBOARD_CLIENTS if client in wininfo)
        if blocklisted:
            if first_time(f"clipboard-blocklisted:{blocklisted}"):
                log.warn(f"receiving clipboard requests from blocklisted client: {wininfo}")
                log.warn(" all requests will be silently ignored")
            log("responding with nodata for blocklisted client '%s'", wininfo)
            return
        if not self.owned:
            log.warn("Warning: clipboard selection request received,")
            log.warn(" coming from %s", wininfo)
            log.warn(" but we don't own the selection,")
            log.warn(" sending an empty reply")
            nodata()
            return
        if not self._can_receive:
            log.warn("Warning: clipboard selection request received,")
            log.warn(" coming from %s", wininfo)
            log.warn(" but receiving remote data is disabled,")
            log.warn(" sending an empty reply")
            nodata()
            return
        if must_discard(target):
            log.info("clipboard %s rejecting request for invalid target '%s'", self._selection, target)
            log.info(" coming from %s", wininfo)
            nodata()
            return

        if target == "TARGETS":
            if self.targets:
                log("using existing TARGETS value as response: %s", self.targets)
                xatoms = strings_to_xatoms(self.targets)
                self.set_selection_response(requestor, target, prop, "ATOM", 32, xatoms, event.time)
                return
            if "TARGETS" not in self.remote_requests:
                self.emit("send-clipboard-request", self._selection, "TARGETS")
            # when appending, the time may not be honoured
            # and we may reply with data from an older request
            self.remote_requests.setdefault("TARGETS", []).append((requestor, target, prop, event.time))
            return

        req_target = target
        if self.targets and target not in self.targets:
            translated_targets = TRANSLATED_TARGETS.get(target, ())
            can_translate = tuple(x for x in translated_targets if x in self.targets)
            log_fn = log.debug
            if not can_translate and first_time(f"client-{wininfo}-invalidtarget-{target}"):
                log_fn = log.info
            log_fn(f"client {wininfo} is requesting an unknown target: {target!r}")
            if can_translate:
                req_target = can_translate[0]
                log_fn(f" using {req_target!r} instead")
            else:
                log_fn(" valid targets: %s", csv(self.targets))
                if must_discard_extra(target):
                    log_fn(" dropping the request")
                    nodata()
                    return

        target_data = self.target_data.get(req_target)
        if target_data and self._have_token:
            # we have it already
            dtype, dformat, data = target_data
            dtype = bytestostr(dtype)
            log("setting target data for '%s': %s, %s, %s (%s)",
                target, dtype, dformat, Ellipsizer(data), type(data))
            self.set_selection_response(requestor, target, prop, dtype, dformat, data, event.time)
            return

        waiting = self.remote_requests.setdefault(req_target, [])
        if waiting:
            log("already waiting for '%s' remote request: %s", req_target, waiting)
        else:
            self.emit("send-clipboard-request", self._selection, req_target)
        waiting.append((requestor, target, prop, event.time))

    def set_selection_response(self, requestor: int, target: str, prop: str, dtype: str, dformat: int,
                               data, time: float = 0.0) -> None:
        log("set_selection_response(%s, %s, %s, %s, %s, %r, %i)",
            requestor, target, prop, dtype, dformat, Ellipsizer(data), time)
        # answer the selection request:
        if not prop:
            log.warn("Warning: cannot set clipboard response")
            log.warn(" property is unset for requestor %s", get_wininfo(requestor))
            return
        try:
            with xsync:
                if data is not None:
                    X11Window.XChangeProperty(requestor, prop, dtype, dformat, memoryview_to_bytes(data))
                else:
                    # maybe even delete the property?
                    # X11Window.XDeleteProperty(xid, prop)
                    prop = ""
                X11Window.sendSelectionNotify(requestor, self._selection, target, prop, time)
        except XError as e:
            log("failed to set selection", exc_info=True)
            log.warn(f"Warning: failed to set selection for target {target!r}")
            log.warn(" on requestor %s", get_wininfo(requestor))
            log.warn(f" property {prop!r}")
            log.warn(f" {e}")

    def got_contents(self, target: str, dtype: str = "", dformat: int = 0, data=None) -> None:
        # if this is the special target 'TARGETS', cache the result:
        if target == "TARGETS" and dtype == "ATOM" and dformat == 32:
            self.targets = xatoms_to_strings(data)
        # the remote peer sent us a response,
        # find all the pending requests for this target
        # and give them the response they are waiting for:
        pending = self.remote_requests.pop(target, [])
        log("got_contents%s pending=%s",
            (target, dtype, dformat, Ellipsizer(data)), csv(pending))
        for requestor, actual_target, prop, time in pending:
            if log.is_debug_enabled():
                log("setting response %s: %s as '%s' on property '%s' of window %s as %s",
                    type(data), Ellipsizer(data), actual_target, prop, get_wininfo(requestor), dtype)
            if actual_target != target and dtype == target:
                dtype = actual_target
            self.set_selection_response(requestor, actual_target, prop, dtype, dformat, data, time)

    ############################################################################
    # local clipboard events, which may or may not be sent to the remote end
    ############################################################################
    def do_selection_notify_event(self, event) -> None:
        owned = self.owned
        xid = 0
        if event.owner:
            xid = event.owner
        self.owned = bool(xid) and xid == self.xid
        log("do_selection_notify_event(%s) owned=%s, was %s (owner=%#x, xid=%#x), enabled=%s, can-send=%s",
            event, self.owned, owned, xid, self.xid, self._enabled, self._can_send)
        if not self._enabled:
            return
        if self.owned or not self._can_send or xid == 0:
            return
        self.do_owner_changed()
        self.schedule_emit_token()

    def schedule_emit_token(self, min_delay: int = 0) -> None:
        if not (self._want_targets or self._greedy_client):
            self._have_token = False
            self.emit("send-clipboard-token", ())
            return

        # we need the targets, and the target data for greedy clients:

        def send_token_with_targets() -> None:
            token_data = (self.targets, )
            self._have_token = False
            self.emit("send-clipboard-token", token_data)

        def with_targets(otargets: Sequence[str]) -> None:
            if not self._greedy_client:
                send_token_with_targets()
                return
            # find the preferred targets:
            targets = self.choose_targets(otargets)
            log(f"choose_targets({otargets})={targets}")
            if not targets:
                send_token_with_targets()
                return
            target = targets[0]

            def got_chosen_target(dtype: str, dformat: int, data: Any) -> None:
                log("got_chosen_target(%s, %s, %s)", dtype, dformat, Ellipsizer(data))
                if not (dtype and dformat and data):
                    send_token_with_targets()
                    return
                token_data = (targets, (target, dtype, dformat, data))
                self._have_token = False
                self.emit("send-clipboard-token", token_data)

            self.get_contents(target, got_chosen_target)

        if self.targets:
            with_targets(self.targets)
            return

        def got_targets(dtype: str, dformat: int, data: Any) -> None:
            assert dtype == "ATOM" and dformat == 32
            self.targets = xatoms_to_strings(data)
            log("got_targets: %s", self.targets)
            with_targets(self.targets)

        self.get_contents("TARGETS", got_targets)

    def choose_targets(self, targets) -> Sequence[str]:
        if self.preferred_targets:
            # prefer PNG, but only if supported by the client:
            fmts = []
            for img_fmt in ("image/png", "image/jpeg"):
                if img_fmt in targets and img_fmt in self.preferred_targets:
                    fmts.append(img_fmt)
            if fmts:
                return tuple(fmts)
            common_targets = tuple(x for x in self.preferred_targets if x in targets)
            # prefer text targets:
            preferred_text_targets = tuple(x for x in common_targets if x in TEXT_TARGETS)
            log(f"choose_targets(..) {common_targets=}, {preferred_text_targets=}")
            if preferred_text_targets:
                return preferred_text_targets
            return common_targets
        # prefer a text target:
        text_targets = tuple(x for x in targets if x in TEXT_TARGETS)
        if text_targets:
            return text_targets
        return targets

    def do_selection_clear_event(self, event) -> None:
        log("do_x11_selection_clear(%s) was owned=%s", event, self.owned)
        if not self._enabled:
            return
        self.owned = False
        self.do_owner_changed()

    def do_owner_changed(self) -> None:
        log("do_owner_changed()")
        self.target_data = {}
        self.targets = ()
        super().do_owner_changed()

    def get_contents(self, target: str, got_contents: ClipboardCallback) -> None:
        log("get_contents(%s, %s) owned=%s, have-token=%s",
            target, got_contents, self.owned, self._have_token)
        if target == "TARGETS":
            if self.targets:
                xatoms = strings_to_xatoms(self.targets)
                got_contents("ATOM", 32, xatoms)
                return
        else:
            target_data = self.target_data.get(target)
            if target_data:
                dtype, dformat, value = target_data
                got_contents(dtype, dformat, value)
                return
        prop = f"{self._selection}-{target}"
        with xsync:
            owner = X11Window.XGetSelectionOwner(self._selection)
            self.owned = owner == self.xid
            if self.owned:
                # we are the clipboard owner!
                log("we are the %s selection owner, using empty reply", self._selection)
                got_contents("", 0, b"")
                return
            request_id = self.local_request_counter
            self.local_request_counter += 1
            timer = GLib.timeout_add(CONVERT_TIMEOUT, self.timeout_get_contents, target, request_id)
            self.local_requests.setdefault(target, {})[request_id] = (timer, got_contents)
            log("requesting local XConvertSelection from %s as '%s' into '%s'", get_wininfo(owner), target, prop)
            X11Window.ConvertSelection(self._selection, target, prop, self.xid, time=CurrentTime)

    def timeout_get_contents(self, target: str, request_id: int) -> None:
        try:
            target_requests = self.local_requests.get(target)
            if target_requests is None:
                return
            timer, got_contents = target_requests.pop(request_id)
            if not target_requests:
                del self.local_requests[target]
        except KeyError:
            return
        GLib.source_remove(timer)
        log.warn("Warning: %s selection request for '%s' timed out", self._selection, target)
        log.warn(" request %i", request_id)
        if target == "TARGETS":
            got_contents("ATOM", 32, b"")
        else:
            got_contents("", 0, b"")

    def do_property_notify(self, event) -> None:
        log("do_property_notify(%s)", event)
        if not self._enabled:
            return
        # ie: atom="PRIMARY-TARGETS", atom="PRIMARY-STRING"
        parts = event.atom.split("-", 1)
        assert len(parts) == 2
        # selection = parts[0]        # ie: PRIMARY
        target = parts[1]  # ie: VALUE
        try:
            with xsync:
                dtype, dformat = X11Window.GetWindowPropertyType(self.xid, event.atom, True)
                data = X11Window.XGetWindowProperty(self.xid, event.atom, dtype, buffer_size=MAX_DATA_SIZE, incr=True)
                # all the code below deals with INCRemental transfers:
                if dtype == "INCR" and not self.incr_data_size:
                    # start of an incremental transfer, extract the size
                    assert dformat == 32
                    self.incr_data_size = struct.unpack("@L", data)[0]
                    self.incr_data_chunks = []
                    self.incr_data_type = ""
                    log("incremental clipboard data of size %s", self.incr_data_size)
                    self.reschedule_incr_data_timer()
                    X11Window.XDeleteProperty(self.xid, event.atom)
                    return
                if self.incr_data_size > 0:
                    # incremental is now in progress:
                    if not self.incr_data_type:
                        self.incr_data_type = dtype
                    elif self.incr_data_type != dtype:
                        log.error("Error: invalid change of data type")
                        log.error(" from %s to %s", self.incr_data_type, dtype)
                        self.reset_incr_data()
                        self.cancel_incr_data_timer()
                        return
                    if data:
                        log("got incremental data: %i bytes", len(data))
                        self.incr_data_chunks.append(data)
                        self.reschedule_incr_data_timer()
                        X11Window.XDeleteProperty(self.xid, event.atom)
                        return
                    self.cancel_incr_data_timer()
                    data = b"".join(self.incr_data_chunks)
                    log("got incremental data termination, total size=%i bytes", len(data))
                    self.reset_incr_data()
                    self.got_local_contents(target, dtype, dformat, data)
                    return
        except PropertyError:
            log("do_property_notify() property '%s' is gone?", event.atom, exc_info=True)
            return
        log("%s=%s (%s : %s)", event.atom, Ellipsizer(data), dtype, dformat)
        if target == "TARGETS":
            self.targets = xatoms_to_strings(data or b"")
        self.got_local_contents(target, dtype, dformat, data)

    def got_local_contents(self, target: str, dtype="", dformat: int = 8, data=b"") -> None:
        data = self.filter_data(dtype, dformat, data)
        target_requests = self.local_requests.pop(target, {})
        for timer, got_contents in target_requests.values():
            if log.is_debug_enabled():
                log("got_local_contents: calling %s%s",
                    got_contents, (dtype, dformat, Ellipsizer(data)))
            GLib.source_remove(timer)
            got_contents(dtype, dformat, data)

    def reschedule_incr_data_timer(self) -> None:
        self.cancel_incr_data_timer()
        self.incr_data_timer = GLib.timeout_add(1 * 1000, self.incr_data_timeout)

    def cancel_incr_data_timer(self) -> None:
        idt = self.incr_data_timer
        if idt:
            self.incr_data_timer = 0
            GLib.source_remove(idt)

    def incr_data_timeout(self) -> None:
        log.warn("Warning: incremental data timeout")
        self.reset_incr_data()


GObject.type_register(ClipboardProxy)
