# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from io import BytesIO
from time import monotonic
from typing import Any

from xpra.util.env import envint, envbool
from xpra.clipboard.common import ClipboardCallback
from xpra.util.str_fn import bytestostr
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("clipboard")

DELAY_SEND_TOKEN = envint("XPRA_DELAY_SEND_TOKEN", 100)


class ClipboardProxyCore:
    def __init__(self, selection):
        self._selection: str = selection
        self._enabled: bool = False
        self._have_token: bool = False
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
        log("clipboard: %s owner_changed, enabled=%s, "
            "can-send=%s, can-receive=%s, have_token=%s, greedy_client=%s, block_owner_change=%s",
            bytestostr(self._selection), self._enabled, self._can_send, self._can_receive,
            self._have_token, self._greedy_client, self._block_owner_change)
        if not self._enabled or self._block_owner_change:
            return
        if self._have_token or ((self._greedy_client or self._want_targets) and self._can_send):
            self.schedule_emit_token()

    def schedule_emit_token(self, min_delay: int = 0) -> None:
        if min_delay == 0:
            self.cancel_emit_token()
            GLib.idle_add(self.emit_token)
            return
        if self._have_token or (not self._want_targets and not self._greedy_client) or DELAY_SEND_TOKEN < 0:
            # token ownership will change or told not to wait
            self.cancel_emit_token()
            GLib.idle_add(self.emit_token)
            return
        if not self._emit_token_timer:
            # we already had sent the token,
            # or sending it is expensive, so wait a bit:
            self.do_schedule_emit_token(min_delay)

    def do_schedule_emit_token(self, min_delay: int = 0) -> None:
        now = monotonic()
        elapsed = int((now - self._last_emit_token) * 1000)
        delay = max(min_delay, DELAY_SEND_TOKEN - elapsed)
        log("do_schedule_emit_token(%i) selection=%s, elapsed=%i (max=%i), delay=%i",
            min_delay, self._selection, elapsed, DELAY_SEND_TOKEN, delay)
        if delay <= 0:
            # enough time has passed
            self.emit_token()
        else:
            self._emit_token_timer = GLib.timeout_add(delay, self.emit_token)

    def emit_token(self) -> None:
        self._emit_token_timer = 0
        boc = self._block_owner_change
        if not boc:
            self._block_owner_change = GLib.idle_add(self.remove_block)
        self._have_token = False
        self._last_emit_token = monotonic()
        self.do_emit_token()
        self._sent_token_events += 1

    def do_emit_token(self):
        # self.emit("send-clipboard-token")
        pass

    def cancel_emit_token(self) -> None:
        ett = self._emit_token_timer
        if ett:
            self._emit_token_timer = 0
            GLib.source_remove(ett)

    def cancel_unblock(self) -> None:
        boc = self._block_owner_change
        if boc:
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

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        raise NotImplementedError()

    def filter_data(self, dtype: str = "", dformat: int = 0, data=b"", trusted: bool = False, output_dtype="") -> bytes:
        log("filter_data(%s, %s, %i %s, %s, %s)",
            dtype, dformat, len(data), type(data), trusted, output_dtype)
        if not data:
            return data
        IMAGE_OVERLAY = os.environ.get("XPRA_CLIPBOARD_IMAGE_OVERLAY", None)
        if IMAGE_OVERLAY and not os.path.exists(IMAGE_OVERLAY):
            IMAGE_OVERLAY = None
        IMAGE_STAMP = envbool("XPRA_CLIPBOARD_IMAGE_STAMP", False)
        SANITIZE_IMAGES = envbool("XPRA_SANITIZE_IMAGES", True)
        isimage = dtype in ("image/png", "image/jpeg", "image/tiff")
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
