# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.common import noop
from xpra.clipboard.core import ClipboardProtocolHelperCore, ClipboardProxyCore
from xpra.util.str_fn import Ellipsizer, repr_ellipsized
from xpra.util.env import envint
from xpra.log import Logger
from xpra.platform.features import CLIPBOARD_GREEDY

GLib = gi_import("GLib")

log = Logger("clipboard")


def env_timeout(name, default: int, min_time=0, max_time=5000) -> int:
    env_name = f"XPRA_CLIPBOARD_{name}_TIMEOUT"
    value = envint(env_name, default)
    if not min_time < value <= max_time:
        log.warn(f"Warning: invalid value for {env_name!r}")
        log.warn(f" valid range is from {min_time} to {max_time}")
        value = max(min_time, min(max_time, value))
    return value


CONVERT_TIMEOUT = env_timeout("CONVERT", 100)
REMOTE_TIMEOUT = env_timeout("REMOTE", 2500)


class ClipboardTimeoutHelper(ClipboardProtocolHelperCore):
    # a clipboard superclass that handles timeouts

    def __init__(self, send_packet_cb, progress_cb=noop, **kwargs):
        super().__init__(send_packet_cb, progress_cb, **kwargs)
        self._clipboard_outstanding_requests: dict[int, tuple[int, str, str]] = {}

    def cleanup(self) -> None:
        # reply to outstanding requests with "no data":
        for request_id in tuple(self._clipboard_outstanding_requests.keys()):
            self._clipboard_got_contents(request_id)
        self._clipboard_outstanding_requests = {}
        super().cleanup()

    def make_proxy(self, selection: str):
        raise NotImplementedError()

    def _get_proxy(self, selection: str) -> ClipboardProxyCore | None:
        proxy = self._clipboard_proxies.get(selection)
        if not proxy:
            log.warn("Warning: no clipboard proxy for '%s'", selection)
            return None
        return proxy

    def set_want_targets_client(self, want_targets: bool) -> None:
        super().set_want_targets_client(want_targets)
        # pass it on to the ClipboardProxy instances:
        for proxy in self._clipboard_proxies.values():
            proxy.set_want_targets(want_targets)

    ############################################################################
    # network methods for communicating with the remote clipboard:
    ############################################################################
    def _send_clipboard_token_handler(self, proxy: ClipboardProxyCore, packet_data=()):
        if log.is_debug_enabled():
            log("_send_clipboard_token_handler(%s, %s)", proxy, repr_ellipsized(packet_data))
        remote = self.local_to_remote(proxy._selection)
        packet: list[Any] = ["clipboard-token", remote]
        if packet_data:
            # append 'TARGETS' unchanged:
            packet.append(packet_data[0])
            # if present, the next element is the target data,
            # which we have to convert to wire format:
            if len(packet_data) >= 2:
                target, dtype, dformat, data = packet_data[1]
                wire_encoding, wire_data = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
                if wire_encoding:
                    wire_data = self._may_compress(dtype, dformat, wire_data)
                    if wire_data:
                        packet += [target, dtype, dformat, wire_encoding, wire_data]
                        claim = proxy._can_send
                        packet += [claim, CLIPBOARD_GREEDY]
        log("send_clipboard_token_handler %s to %s", proxy._selection, remote)
        self.send(*packet)

    def _send_clipboard_request_handler(self, proxy: ClipboardProxyCore, selection: str, target: str):
        log("send_clipboard_request_handler%s", (proxy, selection, target))
        request_id = self._clipboard_request_counter
        self._clipboard_request_counter += 1
        remote = self.local_to_remote(selection)
        log("send_clipboard_request %s to %s, id=%s", selection, remote, request_id)
        timer = GLib.timeout_add(REMOTE_TIMEOUT, self.timeout_request, request_id)
        self._clipboard_outstanding_requests[request_id] = (timer, selection, target)
        self.progress()
        self.send("clipboard-request", request_id, remote, target)

    def timeout_request(self, request_id: int) -> None:
        try:
            selection, target = self._clipboard_outstanding_requests.pop(request_id)[1:]
        except KeyError:
            log.warn("Warning: clipboard request id %i not found", request_id)
            return
        finally:
            self.progress()
        log.warn("Warning: remote clipboard request timed out")
        log.warn(" request id %i, selection=%s, target=%s", request_id, selection, target)
        proxy = self._get_proxy(selection)
        if proxy:
            proxy.got_contents(target)

    def _clipboard_got_contents(self, request_id: int, dtype: str = "", dformat: int = 0, data=None) -> None:
        try:
            timer, selection, target = self._clipboard_outstanding_requests.pop(request_id)
        except KeyError:
            log.warn("Warning: request id %i not found", request_id)
            log.warn(" already timed out or duplicate reply")
            return
        finally:
            self.progress()
        GLib.source_remove(timer)
        proxy = self._get_proxy(selection)
        log("clipboard got contents%s: proxy=%s for selection=%s",
            (request_id, dtype, dformat, Ellipsizer(data)), proxy, selection)
        if data and isinstance(data, memoryview):
            data = bytes(data)
        if proxy:
            proxy.got_contents(target, dtype, dformat, data)

    def client_reset(self) -> None:
        super().client_reset()
        # timeout all pending requests
        cor = self._clipboard_outstanding_requests
        if cor:
            log.info("cancelling %i clipboard requests", len(cor))
            self._clipboard_outstanding_requests = {}
            for request_id in cor:
                self._clipboard_got_contents(request_id)
