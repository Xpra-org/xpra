# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.common import noop
from xpra.clipboard.common import env_timeout
from xpra.clipboard.core import ClipboardProtocolHelperCore
from xpra.clipboard.proxy import ClipboardProxyCore
from xpra.util.str_fn import Ellipsizer
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("clipboard")

REMOTE_TIMEOUT = env_timeout("REMOTE", 2500)


class ClipboardTimeoutHelper(ClipboardProtocolHelperCore):
    # a clipboard superclass that handles timeouts

    def __init__(self, send_packet_cb: Callable, progress_cb=noop, **kwargs):
        super().__init__(send_packet_cb, progress_cb, **kwargs)
        self._clipboard_outstanding_requests: dict[int, tuple[int, str, str]] = {}

    def cleanup(self) -> None:
        # reply to outstanding requests with "no data":
        for request_id in tuple(self._clipboard_outstanding_requests.keys()):
            self._clipboard_got_contents(request_id)
        self._clipboard_outstanding_requests = {}
        super().cleanup()

    ############################################################################
    # network methods for communicating with the remote clipboard:
    ############################################################################

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
