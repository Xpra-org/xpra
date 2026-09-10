# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from io import BytesIO
from time import monotonic
from collections.abc import Iterable, Sequence
from typing import Any

from xpra.util.env import envint, envbool
from xpra.clipboard.common import ClipboardCallback, ClipboardData, ClipboardDataCallback, get_format_size
from xpra.clipboard.targets import choose_eager_targets, IMAGE_TARGETS
from xpra.util.str_fn import bytestostr
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("clipboard")

# how far apart two tokens have to be, in milliseconds:
# an isolated clipboard change is not delayed at all, since the time since the
# last token counts towards this - so it only ever costs anything when the
# clipboard is changing repeatedly, which is exactly when it should:
DELAY_SEND_TOKEN = envint("XPRA_DELAY_SEND_TOKEN", 20)
# the delay doubles for as long as the tokens keep coming, up to this many
# milliseconds - which bounds a selection changing continuously at one token
# per second, well inside the budget `send_clipboard` allows:
BACKOFF_MAX = envint("XPRA_CLIPBOARD_TOKEN_BACKOFF_MAX", 1000)
# a back-off resets once the clipboard has been idle for this many milliseconds:
TOKEN_BACKOFF_RESET = envint("XPRA_CLIPBOARD_TOKEN_BACKOFF_RESET", 1000)
MAX_CLIPBOARD_TOKEN_SIZE = envint("XPRA_CLIPBOARD_TOKEN_MAX_SIZE", 4 * 1024 * 1024)


def filter_data(dtype: str = "", dformat: int = 0, data=b"", trusted: bool = False, output_dtype="") -> bytes:
    log("filter_data(%s, %s, %i %s, %s, %s)", dtype, dformat, len(data), type(data), trusted, output_dtype)
    isimage = dtype in IMAGE_TARGETS
    if not data or not isimage:
        return data
    IMAGE_OVERLAY = os.environ.get("XPRA_CLIPBOARD_IMAGE_OVERLAY", None)
    if IMAGE_OVERLAY and not os.path.exists(IMAGE_OVERLAY):
        IMAGE_OVERLAY = None
    IMAGE_STAMP = envbool("XPRA_CLIPBOARD_IMAGE_STAMP", False)
    SANITIZE_IMAGES = envbool("XPRA_SANITIZE_IMAGES", True)
    modimage = IMAGE_STAMP or IMAGE_OVERLAY or (SANITIZE_IMAGES and not trusted)
    if isimage and ((output_dtype and dtype != output_dtype) or modimage):
        # pylint: disable=import-outside-toplevel
        from xpra.codecs.pillow.decoder import open_only
        img_type = dtype.split("/")[-1]
        img = open_only(data, (img_type,))
        has_alpha = img.mode == "RGBA"
        if not has_alpha and IMAGE_OVERLAY:
            img = img.convert("RGBA")
        w, h = img.size
        if IMAGE_OVERLAY:
            from PIL import Image
            overlay = Image.open(IMAGE_OVERLAY)
            if overlay.mode != "RGBA":
                log.warn("Warning: cannot use overlay image '%s'", IMAGE_OVERLAY)
                log.warn(" invalid mode '%s'", overlay.mode)
            else:
                log("adding clipboard image overlay to %s", dtype)
                try:
                    LANCZOS = Image.Resampling.LANCZOS
                except AttributeError:
                    LANCZOS = Image.LANCZOS
                overlay_resized = overlay.resize((w, h), LANCZOS)
                composite = Image.alpha_composite(img, overlay_resized)
                if not has_alpha and img.mode == "RGBA":
                    composite = composite.convert("RGB")
                img = composite
        if IMAGE_STAMP:
            log("adding clipboard image stamp to %s", dtype)
            from datetime import datetime
            from PIL import ImageDraw
            img_draw = ImageDraw.Draw(img)
            w, h = img.size
            img_draw.text((10, max(0, h // 2 - 16)), 'via Xpra, %s' % datetime.now().isoformat(), fill='black')
        # now save it:
        img_type = (output_dtype or dtype).split("/")[-1]
        buf = BytesIO()
        img.save(buf, img_type.upper())  # ie: "PNG"
        data = buf.getvalue()
        buf.close()
    return data


class ClipboardProxyCore:
    def __init__(self, selection):
        self._selection: str = selection
        self._enabled: bool = False
        self._have_token: bool = False
        # The origin is carried by modern clipboard-data packets.  It is reset
        # when a new local owner takes over the selection.
        self._clipboard_origin: str = ""
        # enabled later during setup
        self._can_send: bool = False
        self._can_receive: bool = False
        # clients that need a new token for every owner-change: (ie: win32 and osx)
        # (forces the client to request new contents - prevents stale clipboard data)
        self._greedy_client: bool = False
        self._want_targets: bool = False
        # semaphore to block the sending of the token when we change the owner ourselves:
        self._block_owner_change: int = 0
        self._last_emit_token: float = 0
        self._emit_token_timer: int = 0
        # the delay in force, once it has grown past `TOKEN_DELAY`
        # (0 whilst the clipboard is idle, and always 0 without a back-off)
        self._emit_token_backoff: int = 0
        # when the token that is scheduled is due, as a monotonic time in milliseconds
        # (only meaningful whilst `_emit_token_timer` is armed)
        self._emit_token_due: int = 0
        # counters for info:
        self._selection_request_events: int = 0
        self._selection_get_events: int = 0
        self._selection_clear_events: int = 0
        self._sent_token_events: int = 0
        self._got_token_events: int = 0
        self._get_contents_events: int = 0
        self._request_contents_events: int = 0
        self._last_targets = ()
        self.preferred_targets = []

    def set_direction(self, can_send: bool, can_receive: bool) -> None:
        self._can_send = can_send
        self._can_receive = can_receive

    def set_want_targets(self, want_targets) -> None:
        self._want_targets = want_targets

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "have_token": self._have_token,
            "enabled": self._enabled,
            "greedy_client": self._greedy_client,
            "preferred-targets": self.preferred_targets,
            "blocked_owner_change": self._block_owner_change,
            "last-targets": self._last_targets,
            "event": {
                "selection_request": self._selection_request_events,
                "selection_get": self._selection_get_events,
                "selection_clear": self._selection_clear_events,
                "got_token": self._got_token_events,
                "sent_token": self._sent_token_events,
                "get_contents": self._get_contents_events,
                "request_contents": self._request_contents_events,
            },
        }
        return info

    def cleanup(self) -> None:
        self._enabled = False
        self.cancel_emit_token()
        self.cancel_unblock()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        log("%s.set_enabled(%s)", self, enabled)
        self._enabled = enabled

    def set_greedy_client(self, greedy: bool) -> None:
        log("%s.set_greedy_client(%s)", self, greedy)
        self._greedy_client = greedy

    def set_preferred_targets(self, preferred_targets) -> None:
        self.preferred_targets = preferred_targets

    def __repr__(self):
        return "ClipboardProxyCore(%s)" % self._selection

    def do_owner_changed(self) -> None:
        # an application on our side owns the clipboard selection
        # (they are ready to provide something via the clipboard)
        self._clipboard_origin = ""
        log("clipboard: %s owner_changed, enabled=%s, "
            "can-send=%s, can-receive=%s, have_token=%s, greedy_client=%s, block_owner_change=%s",
            bytestostr(self._selection), self._enabled, self._can_send, self._can_receive,
            self._have_token, self._greedy_client, self._block_owner_change)
        if not self._enabled or self._block_owner_change:
            return
        if self._have_token or ((self._greedy_client or self._want_targets) and self._can_send):
            self.schedule_emit_token()

    # how far apart the tokens we send are, in milliseconds,
    # before `emit_token_scale()` stretches it:
    TOKEN_DELAY = DELAY_SEND_TOKEN
    # the cap on the exponential back-off, in milliseconds:
    # 0 turns the back-off off, and the delay above is then used as it is
    TOKEN_BACKOFF_MAX = BACKOFF_MAX

    def emit_token_scale(self) -> int:
        """
        How much the delay between tokens is stretched by, for this peer.

        A bare token is just a notification and costs nothing, but collecting
        the targets costs a round trip to the application which owns the
        selection, and a greedy client also makes us fetch the contents - so
        those are spaced out further.
        """
        scale = 1
        if self._want_targets:
            scale *= 2
        if self._greedy_client:
            scale *= 2
        return scale

    def emit_token_delay(self) -> int:
        """
        How far apart the tokens we send have to be, in milliseconds.

        This is the only part of the scheduling that varies,
        so it is the one to override.
        """
        if self.TOKEN_DELAY < 0:
            # told not to wait
            return 0
        return self._emit_token_backoff or self.TOKEN_DELAY * self.emit_token_scale()

    def schedule_emit_token(self, min_delay: int = 0) -> None:
        """
        Schedule the token, keeping whichever deadline comes first.

        `min_delay` is the time the application which owns the selection needs to make
        its data available. A change asking for one must not hold back a token an
        earlier change had already scheduled sooner, and a long one must not make the
        changes which follow it wait either - so the earliest deadline always wins.

        The times are compared in whole milliseconds, and each is converted from the
        clock separately: subtracting two readings that are close together loses the
        last millisecond and makes the comparison unreliable.
        """
        now = round(monotonic() * 1000)
        # the delay only has to space the tokens out, so the time already elapsed
        # counts towards it: an isolated clipboard change is not delayed at all,
        # only the ones following closely behind another are
        elapsed = now - round(self._last_emit_token * 1000)
        if elapsed >= TOKEN_BACKOFF_RESET:
            # the clipboard has been idle long enough: start again from `TOKEN_DELAY`
            self._emit_token_backoff = 0
        delay = max(min_delay, self.emit_token_delay() - elapsed)
        due = now + delay
        log("schedule_emit_token(%i) selection=%s, elapsed=%i, delay=%i, scheduled=%s",
            min_delay, self._selection, elapsed, delay, bool(self._emit_token_timer))
        if self._emit_token_timer:
            if due >= self._emit_token_due:
                # the token already scheduled will not be late for this change
                return
            # this change needs it sooner than it is due:
            self.cancel_emit_token()
        if delay <= 0:
            self.emit_token()
        else:
            self._emit_token_due = due
            self._emit_token_timer = GLib.timeout_add(delay, self.emit_token)

    def emit_token(self) -> None:
        self._emit_token_timer = 0
        self._emit_token_due = 0
        if not self._block_owner_change:
            self._block_owner_change = GLib.idle_add(self.remove_block)
        self._have_token = False
        if not self.do_emit_token():
            # nothing was advertised, so this must neither count
            # nor space out the token which follows it
            return
        self._last_emit_token = monotonic()
        self._sent_token_events += 1
        if self.TOKEN_BACKOFF_MAX > 0 and self.TOKEN_DELAY > 0:
            # space out any token which follows this one closely,
            # and keep doubling that for as long as they keep coming:
            backoff = self._emit_token_backoff * 2 or self.TOKEN_DELAY * self.emit_token_scale()
            self._emit_token_backoff = min(self.TOKEN_BACKOFF_MAX, backoff)

    def do_emit_token(self) -> bool:
        """
        Advertise the local selection to the peer.

        Returns whether a token was sent - a backend which finds it has nothing
        to advertise says so, rather than being counted as if it had.
        Collecting the targets or the contents first is allowed to finish
        asynchronously: what is reported is the decision, not the packet.
        """
        # self.emit("send-clipboard-token")
        return False

    def cancel_emit_token(self) -> None:
        self._emit_token_due = 0
        if ett := self._emit_token_timer:
            self._emit_token_timer = 0
            GLib.source_remove(ett)

    def cancel_unblock(self) -> None:
        if boc := self._block_owner_change:
            self._block_owner_change = 0
            GLib.source_remove(boc)

    def remove_block(self, *_args) -> None:
        log("remove_block: %s", self._selection)
        self._block_owner_change = 0

    def claim(self) -> None:
        """
        Subclasses may want to take ownership of the clipboard selection.
        The X11 clipboard does.
        """

    # This function is called by the xpra core when the peer has requested the
    # contents of this clipboard:
    def get_contents(self, target: str, got_contents: ClipboardCallback) -> None:
        pass

    def collect_contents(self, targets: Iterable[str], got_contents: ClipboardDataCallback,
                         max_size: int = MAX_CLIPBOARD_TOKEN_SIZE) -> None:
        """Collect target contents sequentially, then return the successful results."""
        pending = iter(dict.fromkeys(targets))
        target_data: ClipboardData = {}
        total_size = 0

        def collect_next() -> None:
            try:
                target = next(pending)
            except StopIteration:
                got_contents(target_data)
                return

            completed = False

            def got_target(dtype: str, dformat: int, data: Any) -> None:
                nonlocal completed, total_size
                if completed:
                    return
                completed = True
                if dtype and dformat and data:
                    data_size = self._contents_size(dformat, data)
                    if max_size <= 0 or total_size + data_size <= max_size:
                        target_data[target] = (dtype, dformat, data)
                        total_size += data_size
                collect_next()

            self.get_contents(target, got_target)

        collect_next()

    def get_eager_targets(self, targets: Iterable[str]) -> Sequence[str]:
        return choose_eager_targets(targets, self.preferred_targets)

    @staticmethod
    def _contents_size(dformat: int, data: Any) -> int:
        if isinstance(data, str):
            return len(data.encode("utf8"))
        if isinstance(data, memoryview):
            return data.nbytes
        size = len(data)
        if isinstance(data, (bytes, bytearray)):
            return size
        return size * get_format_size(dformat) // 8

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        raise NotImplementedError()
