# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

from typing import Any
from importlib.util import find_spec
from weakref import WeakKeyDictionary

from xpra.common import SizedBuffer
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.str_fn import Ellipsizer, memoryview_to_bytes
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

log = Logger("cursor")


def get_save_cursors() -> bool:
    if not envbool("XPRA_SAVE_CURSORS", False):
        return False
    # cursors are decoded from the decode thread, which runs under a seccomp filter
    # that blocks file access - writing there would kill the process (see Seccomp.md):
    try:
        from xpra.seccomp import is_enabled
    except ImportError:
        return True
    if is_enabled():
        log.warn("Warning: 'XPRA_SAVE_CURSORS' is ignored because seccomp is enabled")
        return False
    return True


SAVE_CURSORS: bool = get_save_cursors()


def decompress_cursor_data(encoding: str, cpixels: SizedBuffer, serial: int) -> bytes:
    if encoding == "raw":
        return memoryview_to_bytes(cpixels)
    if encoding == "png":
        if SAVE_CURSORS:
            with open(f"raw-cursor-{serial:x}.png", "wb") as f:
                f.write(cpixels)
        from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
        img = open_only(cpixels, ("png",))
        raw = img.tobytes("raw", "BGRA")
        log("used PIL to convert png cursor to raw")
        return raw
    log.warn(f"Warning: invalid cursor encoding: {encoding}")
    return b""


class CursorClient(StubClientSubsystem):
    """
    Add cursor handling
    """
    PREFIX = "cursor"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.server_enabled: bool = False
        self.client_supports: bool = False
        self.enabled: bool = False
        self.default_data = ()
        # cursor tracking state (the toolkit client renders via `set_windows_cursor`
        # and updates these): window -> cursor_data, and the last cursor applied
        # (used to apply the current cursor to newly-shown windows):
        self._cursors: WeakKeyDictionary = WeakKeyDictionary()
        self.last_data: tuple = ()

    def init(self, opts) -> None:
        self.client_supports = opts.cursors

    def load(self) -> None:
        # re-apply cursors when the scaling changes:
        if display := self.get_subsystem("display"):
            display.connect("scaling-changed", self.reset_windows_cursors)

    def preload_decode(self) -> None:
        # `decompress_cursor_data` runs on the decode thread, where a first-time import
        # would be blocked by the seccomp filter - so do it here instead:
        try:
            from xpra.codecs.pillow.decoder import open_only
            log("preload_decode() open_only=%s", open_only)
        except ImportError as e:
            # without pillow we never advertise the `png` cursor encoding (see `get_caps`),
            # so the server can only send us `raw` cursors, which need no decoder:
            log("preload_decode() no pillow decoder: %s", e)

    def get_info(self) -> dict[str, Any]:
        return self.get_caps()

    def get_caps(self) -> dict[str, Any]:
        encodings = ["raw", "default"]
        # weak dependency on `Encodings` subsystem:
        encoding = self.get_subsystem("encoding")
        if encoding and "png" in encoding.get_core_encodings() and find_spec("PIL"):
            encodings.append("png")
        cursor_caps: dict[str, Any] = {
            "encodings": encodings,
            "backwards-compatible": BACKWARDS_COMPATIBLE,
        }
        from xpra.platform.gui import get_default_cursor_size, get_max_cursor_size
        for name, size in {
            "default": get_default_cursor_size(),
            "max": get_max_cursor_size(),
        }.items():
            if min(size) > 0:
                cursor_caps[name] = size
        if BACKWARDS_COMPATIBLE:
            dsize = get_default_cursor_size()
            if max(dsize) > 0:
                # scaling factors are owned by the `display` subsystem:
                display = self.get_subsystem("display")
                xscale, yscale = (display.xscale, display.yscale) if display else (1, 1)
                cursor_caps["size"] = round(sum(get_default_cursor_size()) / (xscale + yscale))
        caps: dict[str, Any] = {CursorClient.PREFIX: cursor_caps}
        if BACKWARDS_COMPATIBLE:
            caps["cursors"] = self.client_supports
        log("cursor caps=%s", caps)
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        cursor = c.get("cursor")
        self.server_enabled = bool(cursor)
        if isinstance(cursor, dict):
            self.default_data = typedict(cursor).tupleget("default", ())
        if BACKWARDS_COMPATIBLE:
            self.server_enabled |= c.boolget("cursors", True)
        self.enabled = self.server_enabled and self.client_supports
        log("parse_server_capabilities(..) cursor=%s, default=%s", self.enabled, self.default_data)
        return True

    # these handlers only queue the work, but they must stay on the UI thread
    # (`main_thread=True`): that hop is what orders them against the window packets
    # (`new-window`, ...) they share the UI thread with - do not "optimize" it away.
    def _process_cursor(self, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        if not self.enabled:
            return
        if len(packet) == 2:
            # marker telling us to use the default cursor:
            self.apply_cursor(packet[1], False)
            return
        if len(packet) < 9:
            raise ValueError(f"invalid cursor packet: only {len(packet)} items")
        new_cursor = list(packet[1:])
        if len(new_cursor) >= 12:
            ssize = new_cursor[10]
            smax = new_cursor[11]
            log("server cursor sizes: default=%s, max=%s", ssize, smax)
        self.add_decode_work(self._decode_cursor, new_cursor)

    def _decode_cursor(self, new_cursor: list) -> None:
        """ this runs from the decode thread (see `xpra/client/subsystem/decode.py`) """
        log("_decode_cursor(%s)", Ellipsizer(new_cursor))
        # trim packet-type:
        encoding = str(new_cursor[0])
        setdefault = encoding.startswith("default:")
        if setdefault:
            encoding = encoding.split(":")[1]
        serial = int(new_cursor[5])
        new_cursor[8] = self.decompress_cursor_data(encoding, new_cursor[8], serial)
        new_cursor[0] = "raw"
        self.idle_add(self.apply_cursor, new_cursor, setdefault)

    def apply_cursor(self, new_cursor, setdefault: bool) -> None:
        """ this runs from the UI thread """
        if setdefault:
            log("setting default cursor=%s", Ellipsizer(new_cursor))
            self.default_data = new_cursor
        else:
            self.set_windows_cursor(self.get_windows(), new_cursor)

    def decompress_cursor_data(self, encoding: str, cpixels: SizedBuffer, serial: int) -> bytes:
        # weak dependency on `Encodings` subsystem:
        enc = self.get_subsystem("encoding")
        core_encodings = enc.get_core_encodings() if enc else ()
        if encoding != "raw" and encoding not in core_encodings:
            raise ValueError(f"cursor encoding {encoding!r} is not supported")
        return decompress_cursor_data(encoding, cpixels, serial)

    def _process_cursor_data(self, packet: Packet) -> None:
        if not self.enabled:
            return
        encoding = packet.get_str(1)
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        xhot = packet.get_u16(4)
        yhot = packet.get_u16(5)
        serial = packet.get_u64(6)
        cpixels = packet.get_bytes(7)
        name = packet.get_str(8)
        self.add_decode_work(self._decode_cursor_data, encoding, w, h, xhot, yhot, serial, cpixels, name)

    def _decode_cursor_data(self, encoding: str, w: int, h: int, xhot: int, yhot: int,
                            serial: int, cpixels: SizedBuffer, name: str) -> None:
        """ this runs from the decode thread (see `xpra/client/subsystem/decode.py`) """
        log("_decode_cursor_data(%s, %s, %s, %s, %s, %#x, %i bytes, %s)",
            encoding, w, h, xhot, yhot, serial, len(cpixels), name)
        pixels = self.decompress_cursor_data(encoding, cpixels, serial)
        cursor_data = ("raw", 0, 0, w, h, xhot, yhot, serial, pixels, name)
        self.idle_add(self.apply_cursor, cursor_data, False)

    def _process_cursor_default(self, packet: Packet) -> None:
        log("setting default cursor: %s", packet)
        if not self.enabled:
            return
        self.reset_cursor()

    def reset_cursor(self) -> None:
        self.set_windows_cursor(self.get_windows(), ())

    def reset_windows_cursors(self, *_args) -> None:
        # re-apply the tracked cursors (e.g. after a scaling change);
        # the toolkit client does the actual rendering:
        log("reset_windows_cursors() resetting cursors for: %s", tuple(self._cursors.keys()))
        for w, cursor_data in tuple(self._cursors.items()):
            self.set_windows_cursor([w], cursor_data)

    def set_windows_cursor(self, client_windows, new_cursor) -> None:
        # record the current cursor, then let the toolkit client render it:
        self.last_data = new_cursor
        self.client.set_windows_cursor(client_windows, new_cursor)

    def init_authenticated_packet_handlers(self) -> None:
        # `main_thread=True` is required for ordering, not for the (trivial) handlers:
        # see `_process_cursor` above
        if BACKWARDS_COMPATIBLE:
            self.add_packets("cursor", main_thread=True)
        self.add_packets("cursor-data", "cursor-default", main_thread=True)
