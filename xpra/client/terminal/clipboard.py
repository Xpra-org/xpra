# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from base64 import b64encode
from collections.abc import Callable, Sequence

from xpra.common import noop
from xpra.util.env import envint
from xpra.util.str_fn import csv, bytestostr, Ellipsizer
from xpra.clipboard.common import ClipboardCallback
from xpra.clipboard.proxy import ClipboardProxyCore
from xpra.clipboard.timeout import ClipboardTimeoutHelper
from xpra.clipboard.targets import TEXT_TARGETS, is_utf8_target
from xpra.log import Logger

log = Logger("clipboard", "terminal")

# `ESC ] 52 ; c ; <base64> BEL` sets the terminal's clipboard selection:
OSC52_START: Final[bytes] = b"\x1b]52;c;"
OSC52_END: Final[bytes] = b"\x07"
# terminals apply their own limit to OSC 52 payloads and drop the ones that are too big,
# there is no point in writing megabytes of escape codes to find out:
MAX_OSC52_SIZE: Final[int] = envint("XPRA_TERMINAL_OSC52_MAX_SIZE", 1024 * 1024)
# OSC 52 can only address the terminal's own clipboard:
LOCAL_SELECTIONS: Final[Sequence[str]] = ("CLIPBOARD", )


def osc52(text: str) -> bytes:
    """ the escape sequence which sets the terminal's clipboard to `text` """
    return OSC52_START + b64encode(text.encode("utf8")) + OSC52_END


class OSC52ClipboardProxy(ClipboardProxyCore):
    """
    Receive-only clipboard proxy: the contents the peer sends us are written to the
    terminal with OSC 52.
    Terminals almost always refuse to answer the OSC 52 read form (`ESC ] 52 ; c ; ? BEL`),
    so this proxy has nothing to offer: like `PrimaryProxyMixin`, it never claims the
    selection and never emits a token.
    """

    def __init__(self, selection: str = "CLIPBOARD", osc52_write: Callable = noop):
        super().__init__(selection)
        # writes to the terminal, on the UI thread
        # (clipboard packets are handled there, see `ClipboardClient`):
        self.osc52_write = osc52_write

    def __repr__(self):
        return "OSC52ClipboardProxy(%s)" % self._selection

    def do_emit_token(self) -> None:
        log("not emitting a token for the %r selection: OSC 52 cannot read the clipboard", self._selection)

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        # the peer has new clipboard contents for us
        self.cancel_emit_token()
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, enabled=%s, can-receive=%s",
            self._selection, targets, Ellipsizer(target_data), claim, self._enabled, self._can_receive)
        if not self._enabled or not self._can_receive or not target_data:
            return
        for target, td_def in target_data.items():
            target = bytestostr(target)
            if target not in TEXT_TARGETS or len(td_def) < 3:
                continue
            dtype, dformat, data = td_def[:3]
            if dformat != 8 or not data:
                continue
            self.set_terminal_clipboard(target, bytestostr(dtype), data)
            return
        log("no text data found in %s", csv(tuple(target_data.keys())))

    def set_terminal_clipboard(self, target: str, dtype: str, data) -> None:
        if isinstance(data, (bytes, bytearray, memoryview)):
            data = bytes(data)
            encoding = "utf8" if (is_utf8_target(target) or is_utf8_target(dtype)) else "latin1"
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                log("failed to decode %i bytes as %r", len(data), encoding, exc_info=True)
                text = data.decode("utf8", "replace")
        else:
            text = str(data)
        sequence = osc52(text)
        log("set_terminal_clipboard%s writing %i bytes", (target, dtype, Ellipsizer(data)), len(sequence))
        if len(sequence) > MAX_OSC52_SIZE:
            log.warn("Warning: %i bytes of clipboard data is too much for the terminal", len(text))
            log.warn(" the clipboard has not been updated")
            return
        self.osc52_write(sequence)

    def get_contents(self, target: str, got_contents: ClipboardCallback) -> None:
        self._get_contents_events += 1
        log("get_contents(%s, %s)", target, got_contents)
        if target == "TARGETS":
            # we cannot read the terminal's clipboard, so we have no targets to offer:
            got_contents("ATOM", 32, ())
            return
        got_contents(target, 0, b"")


class OSC52Clipboard(ClipboardTimeoutHelper):
    """
    Clipboard helper for terminals: a single `CLIPBOARD` proxy which writes
    the contents received from the peer using OSC 52.
    """

    def __init__(self, send_packet_cb: Callable, progress_cb: Callable = noop, **kwargs):
        # how we write to the terminal: the clipboard subsystem binds this to the client
        self.osc52_write: Callable = kwargs.pop("osc52-write", noop)
        super().__init__(send_packet_cb, progress_cb, **kwargs)
        # `get_local_selections` returns whatever the platform has (ie: `PRIMARY`),
        # but OSC 52 only ever addresses the terminal's clipboard:
        self.local_selections = LOCAL_SELECTIONS
        # a greedy client is one that needs the contents to come with the token:
        # our proxies are receive-only and never send a clipboard request,
        # so a token without any data is a token we can do nothing with.
        # (peers only collect the contents ahead of time for greedy clients)
        self.local_greedy = LOCAL_SELECTIONS

    def __repr__(self):
        return "OSC52Clipboard"

    def init_proxies(self, selections) -> None:
        log("init_proxies(%s) OSC 52 only supports %s", selections, LOCAL_SELECTIONS)
        super().init_proxies(LOCAL_SELECTIONS)

    def make_proxy(self, selection: str) -> OSC52ClipboardProxy:
        proxy = OSC52ClipboardProxy(selection, self.osc52_write)
        proxy.set_want_targets(self.proxy_want_targets(selection))
        proxy.set_direction(self.can_send, self.can_receive)
        return proxy
