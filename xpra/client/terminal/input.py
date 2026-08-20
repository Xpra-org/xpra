# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Final
from dataclasses import dataclass
from collections.abc import Sequence

from xpra.util.env import envint
from xpra.log import Logger

log = Logger("client", "terminal")

# give up on an escape sequence that never terminates
# (a misbehaving terminal must not be able to make us buffer forever):
MAX_ESCAPE: Final[int] = envint("XPRA_TERMINAL_MAX_ESCAPE", 8192)

ESC: Final[int] = 0x1B
BEL: Final[int] = 0x07
DEL: Final[int] = 0x7F
BACKSLASH: Final[int] = 0x5C

# kitty keyboard protocol modifier bits (the value sent on the wire is these bits + 1):
MOD_SHIFT: Final[int] = 1
MOD_ALT: Final[int] = 2
MOD_CTRL: Final[int] = 4
MOD_SUPER: Final[int] = 8
MOD_HYPER: Final[int] = 16
MOD_META: Final[int] = 32
MOD_CAPS_LOCK: Final[int] = 64
MOD_NUM_LOCK: Final[int] = 128

# kitty event types:
KEY_PRESS: Final[int] = 1
KEY_REPEAT: Final[int] = 2
KEY_RELEASE: Final[int] = 3

# the unicode code points kitty uses for the keys that also have a legacy encoding:
KEY_TAB: Final[int] = 9
KEY_ENTER: Final[int] = 13
KEY_ESCAPE: Final[int] = 27
KEY_BACKSPACE: Final[int] = 127

# `CSI <n> ; <mods> <letter>` functional keys, normalized to kitty's private use area numbers.
# (`E` is kitty's `KP_Begin`, the rest are the classic xterm cursor / function keys)
CSI_LETTER_KEYS: Final[dict[int, int]] = {
    ord("A"): 57352,        # Up
    ord("B"): 57353,        # Down
    ord("C"): 57351,        # Right
    ord("D"): 57350,        # Left
    ord("E"): 57427,        # KP_Begin
    ord("F"): 57357,        # End
    ord("H"): 57356,        # Home
    ord("P"): 57364,        # F1
    ord("Q"): 57365,        # F2
    ord("S"): 57367,        # F4
}

# `SS3 <letter>`, ie: `ESC O P` for F1.
# `CSI R` is deliberately absent from `CSI_LETTER_KEYS` because that is the cursor position report,
# but `SS3 R` is unambiguously F3:
SS3_KEYS: Final[dict[int, int]] = {
    ord("A"): 57352,        # Up
    ord("B"): 57353,        # Down
    ord("C"): 57351,        # Right
    ord("D"): 57350,        # Left
    ord("E"): 57427,        # KP_Begin
    ord("F"): 57357,        # End
    ord("H"): 57356,        # Home
    ord("M"): 57414,        # KP_Enter
    ord("P"): 57364,        # F1
    ord("Q"): 57365,        # F2
    ord("R"): 57366,        # F3
    ord("S"): 57367,        # F4
}

# `CSI <n> ; <mods> ~` functional keys:
CSI_TILDE_KEYS: Final[dict[int, int]] = {
    1: 57356,               # Home
    2: 57348,               # Insert
    3: 57349,               # Delete
    4: 57357,               # End
    5: 57354,               # Page_Up
    6: 57355,               # Page_Down
    7: 57356,               # Home
    8: 57357,               # End
    11: 57364,              # F1
    12: 57365,              # F2
    13: 57366,              # F3
    14: 57367,              # F4
    15: 57368,              # F5
    17: 57369,              # F6
    18: 57370,              # F7
    19: 57371,              # F8
    20: 57372,              # F9
    21: 57373,              # F10
    23: 57374,              # F11
    24: 57375,              # F12
    29: 57363,              # Menu
}

# control bytes that are keys in their own right rather than `ctrl` + a letter:
C0_KEYS: Final[dict[int, int]] = {
    0x08: KEY_BACKSPACE,
    0x09: KEY_TAB,
    0x0D: KEY_ENTER,
    DEL: KEY_BACKSPACE,
}

# SGR mouse modifier bits, mapped onto the kitty modifier bits used by `KeyEvent.mods`
# so that a single `keys.modifier_names()` call covers both event kinds:
SGR_MODIFIERS: Final[dict[int, int]] = {
    4: MOD_SHIFT,
    8: MOD_ALT,
    16: MOD_CTRL,
}

NEED_MORE: Final[int] = 0


@dataclass(slots=True)
class KeyEvent:
    """ a key as reported by the terminal, before any keysym translation """
    code: int = 0
    shifted: int = 0
    base: int = 0
    mods: int = 0
    event_type: int = KEY_PRESS
    text: str = ""


@dataclass(slots=True)
class MouseEvent:
    """ a pointer event decoded from an SGR (1006 / 1016) mouse report """
    x: int = 0
    y: int = 0
    button: int = 0
    event: str = ""
    mods: int = 0


@dataclass(slots=True)
class GraphicsResponse:
    """ the terminal's answer to a kitty graphics command: `ESC _ G i=<id>;OK ESC \\` """
    image_id: int = 0
    ok: bool = False
    message: str = ""


@dataclass(slots=True)
class KeyboardFlagsResponse:
    """ the terminal's answer to `CSI ? u`: the keyboard protocol flags currently in effect """
    flags: int = 0


@dataclass(slots=True)
class TextReport:
    """ a `CSI <kind> ; <values...> t` window report, ie kind 4 = text area size in pixels """
    kind: int = 0
    values: tuple[int, ...] = ()


def utf8_length(first: int) -> int:
    """ the length of the utf8 sequence starting with this byte, 0 if it cannot start one """
    if first < 0x80:
        return 1
    if first < 0xC0:
        return 0
    if first < 0xE0:
        return 2
    if first < 0xF0:
        return 3
    if first < 0xF8:
        return 4
    return 0


def parse_params(raw: bytes) -> list[list[int]]:
    """ split `1:2;3:4` into `[[1, 2], [3, 4]]`, using -1 for missing or invalid values """
    groups: list[list[int]] = []
    for part in raw.split(b";"):
        group: list[int] = []
        for value in part.split(b":"):
            group.append(int(value) if value.isdigit() else -1)
        groups.append(group)
    return groups


def parse_key_params(code: int, groups: Sequence[Sequence[int]]) -> list[object]:
    """ build a `KeyEvent` from an already decoded key code and the `;` separated parameters """
    if code <= 0:
        return []
    first = groups[0] if groups else []
    shifted = first[1] if len(first) > 1 and first[1] > 0 else 0
    base = first[2] if len(first) > 2 and first[2] > 0 else 0
    second = groups[1] if len(groups) > 1 else []
    raw_mods = second[0] if second and second[0] > 0 else 1
    event_type = second[1] if len(second) > 1 and second[1] > 0 else KEY_PRESS
    if event_type not in (KEY_PRESS, KEY_REPEAT, KEY_RELEASE):
        event_type = KEY_PRESS
    text = ""
    if len(groups) > 2:
        text = "".join(chr(c) for c in groups[2] if 0 < c <= 0x10FFFF)
    return [KeyEvent(code, shifted, base, max(0, raw_mods - 1), event_type, text)]


def parse_mouse_params(groups: Sequence[Sequence[int]], final: int) -> list[object]:
    """ decode the `b;x;y` parameters of an SGR mouse report """
    if len(groups) != 3:
        return []
    values = [group[0] for group in groups]
    if min(values) < 0:
        return []
    b, x, y = values
    mods = 0
    for sgr_bit, mod_bit in SGR_MODIFIERS.items():
        if b & sgr_bit:
            mods |= mod_bit
    low = b & 3
    group = (b >> 6) & 3
    if group == 0:
        # 3 means "no button": a 1003 motion report, or a legacy release
        button = 0 if low == 3 else low + 1
    else:
        # 4..7 are the wheel, 8..11 and 12..15 the extra buttons
        button = group * 4 + low
    if group == 1:
        event = "wheel"
    elif b & 32:
        event = "motion"
    else:
        event = "press" if final == ord("M") else "release"
    return [MouseEvent(x, y, button, event, mods)]


def parse_graphics_response(body: bytes) -> list[object]:
    """ decode the payload of an APC graphics answer: `G i=<id>[,...];<message>` """
    if body[:1] != b"G":
        return []
    text = body[1:].decode("latin1")
    control, _, message = text.partition(";")
    image_id = 0
    for kv in control.split(","):
        key, _, value = kv.partition("=")
        if key == "i" and value.isdigit():
            image_id = int(value)
    return [GraphicsResponse(image_id, message == "OK", message)]


class InputParser:
    """
    Incremental parser for everything a terminal can send back on stdin:
    kitty keyboard protocol events, legacy key bytes, SGR mouse reports,
    kitty graphics answers, keyboard flag answers and `CSI ... t` reports.

    Feeding the same bytes one at a time or all at once yields the same events.
    Malformed sequences are skipped without raising and without hiding the input that follows them.
    """
    __slots__ = ("_buf", )

    def __init__(self):
        self._buf = b""

    def __repr__(self):
        return f"InputParser({len(self._buf)} bytes buffered)"

    @property
    def pending(self) -> int:
        """ the number of bytes buffered, waiting for the rest of an escape sequence """
        return len(self._buf)

    def feed(self, data: bytes) -> list[object]:
        """ add bytes to the buffer and return every event that can now be decoded """
        self._buf += data
        return self._parse(False)

    def flush(self) -> list[object]:
        """ drain whatever is left buffered - a lone `ESC` becomes an `Escape` key press """
        return self._parse(True)

    def _parse(self, force: bool) -> list[object]:
        events: list[object] = []
        buf = self._buf
        pos = 0
        end = len(buf)
        while pos < end:
            size, new_events = self._parse_one(buf, pos)
            if size == NEED_MORE:
                if not force:
                    break
                size, new_events = self._force_one(buf, pos)
            events += new_events
            pos += size
        self._buf = buf[pos:]
        return events

    def _force_one(self, buf: bytes, pos: int) -> tuple[int, list[object]]:
        """
        Give up on the incomplete sequence at `pos`, which always runs to the end of the buffer.
        A lone `ESC` is the `Escape` key. Everything else is a truncated escape sequence
        (or a truncated utf8 character) and is dropped whole: decoding its bytes one at a time
        would type the sequence's parameters into the focused window, so a `CSI u` key event
        split by a stall in the byte stream would turn `ESC [ 9 7 ; 1` into `[ 9 7 ; 1`.
        The cost is `alt` + one of the bytes which start a sequence (`ESC [` is both the start
        of a control sequence and how a legacy terminal reports `alt` + `[`), which the kitty
        keyboard protocol reports as an unambiguous `CSI u` event anyway.
        """
        size = len(buf) - pos
        if size == 1 and buf[pos] == ESC:
            return 1, [KeyEvent(KEY_ESCAPE)]
        log("dropping %i incomplete input bytes: %r", size, buf[pos:])
        return size, []

    def _parse_one(self, buf: bytes, pos: int) -> tuple[int, list[object]]:
        if buf[pos] == ESC:
            return self._parse_escape(buf, pos)
        return self._parse_legacy(buf, pos, 0)

    def _parse_escape(self, buf: bytes, pos: int) -> tuple[int, list[object]]:
        if pos + 1 >= len(buf):
            return NEED_MORE, []
        c = buf[pos + 1]
        if c == ord("["):
            return self._parse_csi(buf, pos)
        if c == ord("_"):
            return self._parse_apc(buf, pos)
        if c == ord("]"):
            return self._skip_string(buf, pos, True)
        if c in (ord("P"), ord("^"), ord("X")):
            return self._skip_string(buf, pos, False)
        # note: `ESC ]`, `ESC P`, `ESC _`, `ESC ^` and `ESC X` are also how a legacy terminal
        # reports alt + `]`, `P`, `_`, `^` and `X`. The string sequences win because we only
        # ever run with the kitty keyboard protocol enabled, where those keys arrive as `CSI u`
        if c == ord("O"):
            return self._parse_ss3(buf, pos)
        if c == ESC:
            # the first `ESC` is the `Escape` key, the second one starts a new sequence:
            return 1, [KeyEvent(KEY_ESCAPE)]
        # `ESC` followed by anything else is that key with `alt` held:
        size, events = self._parse_legacy(buf, pos + 1, MOD_ALT)
        if size == NEED_MORE:
            return NEED_MORE, []
        return size + 1, events

    def _parse_ss3(self, buf: bytes, pos: int) -> tuple[int, list[object]]:
        if pos + 2 >= len(buf):
            return NEED_MORE, []
        final = buf[pos + 2]
        if not 0x20 <= final <= 0x7E:
            # not a final byte at all: skip the `ESC O` and re-parse from there
            return 2, []
        code = SS3_KEYS.get(final, 0)
        if not code:
            log("unknown SS3 sequence %r", buf[pos:pos + 3])
            return 3, []
        return 3, [KeyEvent(code)]

    def _parse_csi(self, buf: bytes, pos: int) -> tuple[int, list[object]]:
        end = len(buf)
        i = pos + 2
        start = i
        while i < end and 0x30 <= buf[i] <= 0x3F:
            i += 1
            if i - pos > MAX_ESCAPE:
                # consume everything scanned so far: re-parsing those bytes
                # would turn the sequence's parameters into key presses
                log("giving up on an unterminated control sequence")
                return i - pos, []
        params = buf[start:i]
        start = i
        while i < end and 0x20 <= buf[i] <= 0x2F:
            i += 1
            if i - pos > MAX_ESCAPE:
                # consume everything scanned so far: re-parsing those bytes
                # would turn the sequence's parameters into key presses
                log("giving up on an unterminated control sequence")
                return i - pos, []
        intermediates = buf[start:i]
        if i >= end:
            return NEED_MORE, []
        final = buf[i]
        if not 0x40 <= final <= 0x7E:
            # aborted mid-sequence: drop what we have but leave the offending byte alone,
            # it may well be the `ESC` starting a perfectly valid sequence
            log("control sequence aborted by byte %#x", final)
            return i - pos, []
        return i + 1 - pos, self._csi_events(params, intermediates, final)

    def _csi_events(self, params: bytes, intermediates: bytes, final: int) -> list[object]:
        if intermediates:
            log("ignoring control sequence with intermediates %r", intermediates)
            return []
        prefix = params[:1] if params[:1] in (b"<", b"=", b">", b"?") else b""
        rest = params[len(prefix):]
        if final == ord("u"):
            if prefix == b"?":
                return [KeyboardFlagsResponse(int(rest) if rest.isdigit() else 0)]
            if prefix:
                return []
            groups = parse_params(rest)
            code = groups[0][0] if groups and groups[0] else -1
            return parse_key_params(code, groups)
        if prefix == b"<" and final in (ord("M"), ord("m")):
            return parse_mouse_params(parse_params(rest), final)
        if prefix:
            log("ignoring private control sequence %r %r", params, chr(final))
            return []
        if final == ord("~"):
            groups = parse_params(rest)
            number = groups[0][0] if groups and groups[0] else -1
            code = CSI_TILDE_KEYS.get(number, 0)
            if not code:
                log("ignoring unknown functional key %r", number)
                return []
            return parse_key_params(code, groups)
        if final in CSI_LETTER_KEYS:
            return parse_key_params(CSI_LETTER_KEYS[final], parse_params(rest))
        if final == ord("t"):
            groups = parse_params(rest)
            values = tuple(group[0] for group in groups)
            if not values or values[0] < 0:
                return []
            return [TextReport(values[0], values[1:])]
        log("ignoring unknown control sequence %r %r", params, chr(final))
        return []

    def _parse_apc(self, buf: bytes, pos: int) -> tuple[int, list[object]]:
        size, body = self._scan_string(buf, pos, False)
        if size == NEED_MORE or body is None:
            return size, []
        return size, parse_graphics_response(body)

    def _skip_string(self, buf: bytes, pos: int, allow_bel: bool) -> tuple[int, list[object]]:
        size, _ = self._scan_string(buf, pos, allow_bel)
        return size, []

    def _scan_string(self, buf: bytes, pos: int, allow_bel: bool) -> tuple[int, bytes | None]:
        """ scan a string sequence (OSC / DCS / APC / PM / SOS) and return its body """
        end = len(buf)
        i = pos + 2
        while i < end:
            c = buf[i]
            if allow_bel and c == BEL:
                return i + 1 - pos, buf[pos + 2:i]
            if c == ESC:
                if i + 1 >= end:
                    break
                if buf[i + 1] == BACKSLASH:
                    return i + 2 - pos, buf[pos + 2:i]
                # not a string terminator: give up here rather than swallow what follows
                log("string sequence aborted by an escape character")
                return i - pos, None
            i += 1
            if i - pos > MAX_ESCAPE:
                log("giving up on an unterminated string sequence")
                return i - pos, None
        return NEED_MORE, None

    def _parse_legacy(self, buf: bytes, pos: int, mods: int) -> tuple[int, list[object]]:
        """ decode a key that is not using the kitty keyboard protocol """
        b = buf[pos]
        code = C0_KEYS.get(b, 0)
        if code:
            return 1, [KeyEvent(code, mods=mods)]
        if b < 0x20:
            # `ctrl` + a letter, or one of `@ [ \\ ] ^ _`:
            code = b + 96 if 1 <= b <= 26 else b + 64
            return 1, [KeyEvent(code, mods=mods | MOD_CTRL)]
        size = utf8_length(b)
        if size == 0:
            log("dropping invalid utf8 byte %#x", b)
            return 1, []
        if pos + size > len(buf):
            return NEED_MORE, []
        try:
            text = buf[pos:pos + size].decode("utf8")
        except UnicodeDecodeError:
            # skip a single byte so that the bytes following it can still be decoded:
            log("dropping invalid utf8 sequence starting with %#x", b)
            return 1, []
        return size, [KeyEvent(ord(text), mods=mods, text=text)]
