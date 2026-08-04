# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.clipboard.targets import PLAIN_TEXT_TARGETS
from xpra.os_util import gi_import
from xpra.util.env import envint
from xpra.util.str_fn import csv, Ellipsizer, bytestostr
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("clipboard")

# how long we wait before requesting the remote `PRIMARY` selection contents:
# this selection changes with every mouse selection event,
# so we deliberately use a slow timer to avoid flooding the connection:
PRIMARY_DELAY = envint("XPRA_CLIPBOARD_PRIMARY_DELAY", 200)
log("clipboard: PRIMARY_DELAY=%i", PRIMARY_DELAY)


class PrimaryProxyMixin:
    """
    Mixin for the `PRIMARY` selection on the platforms which do not have one:
    MS Windows and MacOS. (enabled with `--clipboard=all`, the default on these platforms)

    This proxy can only receive: it never claims the selection and never sends a token.
    The peer notifies us when the remote `PRIMARY` selection changes,
    and we then request its contents using a slow timer,
    so that selecting text remotely with the mouse
    does not flood the connection with requests.
    The contents we receive are saved to the local `CLIPBOARD` selection,
    without claiming it.

    Platform proxies must call `init_primary` before the proxy constructor,
    and must be declared with this mixin first:
    `class FooPrimaryProxy(PrimaryProxyMixin, FooClipboardProxy)`
    """

    def init_primary(self, set_clipboard_text: Callable[[str], None]) -> None:
        self.request_timer = 0
        # requests sent and still waiting for a reply:
        self.pending_requests = 0
        # replies to discard: requests which were cancelled after they were sent
        self.stale_requests = 0
        self.set_text = set_clipboard_text

    def set_direction(self, can_send: bool, can_receive: bool) -> None:
        # we can never send this selection: it does not exist here
        super().set_direction(False, can_receive)

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info |= {
            "request-scheduled": bool(self.request_timer),
            "requests-pending": self.pending_requests,
            "requests-stale": self.stale_requests,
        }
        return info

    def cleanup(self) -> None:
        self.cancel_request()
        super().cleanup()

    def do_emit_token(self) -> None:
        log("not emitting a token for the %r selection", self._selection)

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        # the remote end has new `PRIMARY` selection contents for us
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, enabled=%s, can-receive=%s",
            self._selection, targets, Ellipsizer(target_data), claim, self._enabled, self._can_receive)
        if not self._enabled or not self._can_receive:
            return
        if not target_data:
            self.schedule_request()
            return
        # we don't ask for the data with the token, but use it if we get it anyway:
        self.cancel_request()
        for target in PLAIN_TEXT_TARGETS:
            td_def = target_data.get(target)
            if td_def:
                dtype, dformat, data = td_def
                self.save_text(target, bytestostr(dtype), dformat, data)
                return
        log("no plain text in %s", csv(target_data.keys()))

    def schedule_request(self) -> None:
        if self.request_timer:
            # a request is already scheduled, it will collect the latest contents
            return
        self.request_timer = GLib.timeout_add(PRIMARY_DELAY, self.request_contents)

    def cancel_request(self) -> None:
        if rt := self.request_timer:
            self.request_timer = 0
            GLib.source_remove(rt)
        # whatever cancelled the request supersedes the contents we asked for,
        # so the replies to the requests already sent must be discarded:
        self.stale_requests += self.pending_requests
        self.pending_requests = 0

    def request_contents(self) -> None:
        self.request_timer = 0
        self._request_contents_events += 1
        self.pending_requests += 1
        log("requesting the %r selection contents", self._selection)
        self.send_clipboard_request_handler(self, self._selection, "UTF8_STRING")

    def got_contents(self, target: str, dtype="", dformat=0, data=b"") -> None:
        # every request gets exactly one reply (contents, no contents, or a timeout),
        # so we can discard them in the order they were sent:
        if self.stale_requests > 0:
            self.stale_requests -= 1
            log("ignoring the reply to a cancelled %r request", self._selection)
            return
        self.pending_requests = max(0, self.pending_requests - 1)
        self.save_text(target, dtype, dformat, data)

    def save_text(self, target: str, dtype="", dformat=0, data=b"") -> None:
        log("save_text%s", (target, dtype, dformat, Ellipsizer(data)))
        if dformat != 8 or not data or target not in PLAIN_TEXT_TARGETS:
            log("no plain text to save to the 'CLIPBOARD' selection")
            return
        if dtype.lower().find("utf8") >= 0:
            text = data.decode("utf8")
        else:
            text = bytestostr(data)
        self.set_text(text)


class PrimaryHelperMixin:
    """
    Mixin for the clipboard helpers which can create a `PrimaryProxyMixin` proxy.
    The platform helper is responsible for assigning `primary_proxy` in `make_proxy`,
    and must be declared with this mixin first:
    `class FooClipboard(PrimaryHelperMixin, ClipboardTimeoutHelper)`
    """
    primary_proxy: PrimaryProxyMixin | None = None

    def cancel_primary_request(self) -> None:
        if pp := self.primary_proxy:
            pp.cancel_request()

    def _get_clipboard_token_proxy(self, selection: str):
        proxy = super()._get_clipboard_token_proxy(selection)
        if proxy is not None and proxy is not self.primary_proxy:
            # a token for another selection (ie: `CLIPBOARD`) takes precedence
            # over any remote `PRIMARY` contents we were about to fetch:
            self.cancel_primary_request()
        return proxy
