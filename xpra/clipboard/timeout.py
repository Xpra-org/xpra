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
from xpra.util.env import envint, first_time
from xpra.net.packet_type import CLIPBOARD_REQUEST
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("clipboard")

REMOTE_TIMEOUT = env_timeout("REMOTE", 2500)
# local applications can make as many requests as they like,
# but we only forward this many to the peer at any given time:
MAX_CLIPBOARD_OUTSTANDING_REQUESTS = envint("XPRA_MAX_CLIPBOARD_OUTSTANDING_REQUESTS", 32)


class ClipboardTimeoutHelper(ClipboardProtocolHelperCore):
    # a clipboard superclass that handles timeouts

    def __init__(self, send_packet_cb: Callable, progress_cb=noop, **kwargs):
        super().__init__(send_packet_cb, progress_cb, **kwargs)
        # request_id: (timer, local selection, target, remote selection)
        self._clipboard_outstanding_requests: dict[int, tuple[int, str, str, str]] = {}

    def cleanup(self) -> None:
        self.cancel_outstanding_requests()
        super().cleanup()

    def cancel_outstanding_requests(self) -> None:
        # reply to all the outstanding requests with "no data":
        # `_clipboard_got_contents` cancels the timer and removes each request as it answers it,
        # so the dictionary must not be cleared before they have all been served
        if cor := self._clipboard_outstanding_requests:
            log.info("cancelling %i clipboard requests", len(cor))
        for request_id in tuple(cor):
            self._clipboard_got_contents(request_id)

    ############################################################################
    # network methods for communicating with the remote clipboard:
    ############################################################################

    def _send_clipboard_request_handler(self, proxy: ClipboardProxyCore, selection: str, target: str):
        log("send_clipboard_request_handler%s", (proxy, selection, target))
        if len(self._clipboard_outstanding_requests) >= MAX_CLIPBOARD_OUTSTANDING_REQUESTS:
            if first_time("clipboard-outstanding-requests"):
                log.warn("Warning: too many pending clipboard requests, the limit is %i",
                         MAX_CLIPBOARD_OUTSTANDING_REQUESTS)
            # answer from the main loop: the proxy only records the request once this handler returns
            GLib.idle_add(proxy.got_contents, target)
            return
        request_id = self._clipboard_request_counter
        self._clipboard_request_counter += 1
        remote = self.local_to_remote(selection)
        log("send_clipboard_request %s to %s, id=%s", selection, remote, request_id)
        timer = GLib.timeout_add(REMOTE_TIMEOUT, self.timeout_request, request_id)
        self._clipboard_outstanding_requests[request_id] = (timer, selection, target, remote)
        self.progress()
        self.send(CLIPBOARD_REQUEST, request_id, remote, target)

    def timeout_request(self, request_id: int) -> None:
        try:
            selection, target = self._clipboard_outstanding_requests.pop(request_id)[1:3]
        except KeyError:
            log.warn("Warning: clipboard request id %i not found", request_id)
            return
        finally:
            self.progress()
        log.warn("Warning: remote clipboard request timed out")
        log.warn(" request id %i, selection=%s, target=%s", request_id, selection, target)
        if proxy := self._get_proxy(selection):
            proxy.got_contents(target)

    def _clipboard_got_contents(self, request_id: int, dtype: str = "", dformat: int = 0, data=None,
                                selection: str = "", encoding: str = "") -> None:
        request = self._clipboard_outstanding_requests.get(request_id)
        if not request:
            log.warn("Warning: request id %i not found", request_id)
            log.warn(" already timed out or duplicate reply")
            self.progress()
            return
        timer, local, target, remote = request
        if selection and selection != remote:
            # leave the request for its timer to answer:
            log.warn("Warning: clipboard reply for request id %i does not match the request", request_id)
            log.warn(" expected selection %r but got %r", remote, selection)
            return
        del self._clipboard_outstanding_requests[request_id]
        self.progress()
        GLib.source_remove(timer)
        if target == "TARGETS" and data is not None and ((dtype, dformat) != ("ATOM", 32) or encoding not in ("", "atoms")):
            # ie: the html5 client answers every request with text
            log.warn("Warning: invalid clipboard reply for %r TARGETS: %r, format %s, encoding %r",
                     remote, dtype, dformat, encoding)
            dtype, dformat, data = "", 0, None
        proxy = self._get_proxy(local)
        log("clipboard got contents%s: proxy=%s for selection=%s",
            (request_id, dtype, dformat, Ellipsizer(data)), proxy, local)
        if data and isinstance(data, memoryview):
            data = bytes(data)
        if proxy:
            proxy.got_contents(target, dtype, dformat, data)

    def client_reset(self) -> None:
        super().client_reset()
        self.cancel_outstanding_requests()
