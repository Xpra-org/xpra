# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from io import BytesIO
from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.net.compression import Compressed
from xpra.util.str_fn import memoryview_to_bytes
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "cursor")

SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)


class CursorsMixin(StubSourceMixin):
    PREFIX = "cursor"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("cursors")

    def __init__(self):
        self.get_cursor_data_cb: Callable | None = None
        self.send_cursors = False
        self.cursor_encodings: Sequence[str] = ()
        self.cursor_timer = 0
        self.last_cursor_sent: tuple = ()

    def init_from(self, _protocol, server) -> None:
        self.get_cursor_data_cb = server.get_cursor_data

    def init_state(self) -> None:
        # WindowSource for each Window ID
        self.send_cursors = False
        self.cursor_encodings = ()
        self.last_cursor_sent = ()

    def cleanup(self) -> None:
        self.cancel_cursor_timer()

    def resume(self) -> None:
        self.send_cursor()

    def parse_client_caps(self, c: typedict) -> None:
        self.send_cursors = self.send_windows and c.boolget("cursors")
        self.cursor_encodings = c.strtupleget("encodings.cursor")
        log(f"cursors={self.send_cursors}, cursor encodings={self.cursor_encodings}")

    def get_caps(self) -> dict[str, Any]:
        return {}

    ######################################################################
    # info:
    def get_info(self) -> dict[str, Any]:
        return {
            CursorsMixin.PREFIX: {
                "enabled": self.send_cursors,
                "encodings": self.cursor_encodings,
            },
        }

    def send_cursor(self) -> None:
        if not self.send_cursors or self.suspended or not self.hello_sent:
            return
        # if not pending already, schedule it:
        gbc = self.global_batch_config
        if not self.cursor_timer and gbc:
            delay = max(10, int(gbc.delay / 4))

            def do_send_cursor():
                self.cursor_timer = 0
                cd = self.get_cursor_data_cb()
                if not cd or not cd[0]:
                    self.send_empty_cursor()
                    return
                cursor_data = list(cd[0])
                cursor_sizes = cd[1]
                self.do_send_cursor(delay, cursor_data, cursor_sizes)

            self.cursor_timer = GLib.timeout_add(delay, do_send_cursor)

    def cancel_cursor_timer(self) -> None:
        ct = self.cursor_timer
        if ct:
            self.cursor_timer = 0
            GLib.source_remove(ct)

    def do_send_cursor(self, delay, cursor_data, cursor_sizes, encoding_prefix="") -> None:
        # x11 server core calls this method directly, so check availability again:
        if not self.send_cursors:
            return
        # copy to a new list we can modify (ie: compress):
        cursor_data = list(cursor_data)
        # skip first two fields (if present) as those are coordinates:
        if self.last_cursor_sent and self.last_cursor_sent[2:9] == cursor_data[2:9]:
            log("do_send_cursor(..) cursor identical to the last one we sent, nothing to do")
            return
        self.last_cursor_sent = cursor_data[:9]
        w, h, _xhot, _yhot, serial, pixels, name = cursor_data[2:9]
        # compress pixels if needed:
        encoding = "raw"
        if pixels is not None:
            cpixels: bytes | Compressed = memoryview_to_bytes(pixels)
            try:
                from PIL import Image
            except ImportError:
                Image = None
            if "png" in self.cursor_encodings and Image:
                log(f"do_send_cursor() got {len(cpixels)} bytes of pixel data for {w}x{h} cursor named {name!r}")
                img = Image.frombytes("RGBA", (w, h), cpixels, "raw", "BGRA", w * 4, 1)
                buf = BytesIO()
                img.save(buf, "PNG")
                pngdata = buf.getvalue()
                buf.close()
                cpixels = Compressed("png cursor", pngdata)
                encoding = "png"
                if SAVE_CURSORS:
                    filename = f"raw-cursor-{serial:x}.png"
                    with open(filename, "wb") as f:
                        f.write(pngdata)
                    log("cursor saved to %s", filename)
            elif len(cpixels) >= 256 and ("raw" in self.cursor_encodings or not self.cursor_encodings):
                cpixels = self.compressed_wrapper("cursor", pixels)
                log("do_send_cursor(..) pixels=%s ", cpixels)
                encoding = "raw"
            else:
                log("no supported cursor encodings")
                return
            cursor_data[7] = cpixels
        log("do_send_cursor(..) %sx%s %s cursor name='%s', serial=%#x with delay=%s (cursor_encodings=%s)",
            w, h, (encoding or "empty"), name, serial, delay, self.cursor_encodings)
        args = [encoding_prefix + encoding] + list(cursor_data[:9]) + [cursor_sizes[0]] + list(cursor_sizes[1])
        self.send_more("cursor", *args)

    def send_empty_cursor(self) -> None:
        log("send_empty_cursor(..)")
        self.last_cursor_sent = ()
        self.send_more("cursor", "")
