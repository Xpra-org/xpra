# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import fcntl
import struct
import termios
from typing import Final
from collections.abc import Sequence

from xpra.util.env import envint, osexpand
from xpra.util.thread import check_main_thread
from xpra.log import Logger

log = Logger("client", "terminal")

# the terminal geometry to assume when the terminal does not report one
# (`get_root_size()` is called long before we can query the real terminal):
DEFAULT_COLUMNS: Final[int] = 80
DEFAULT_ROWS: Final[int] = 24
# the cell size to assume when the terminal does not report its pixel size,
# and before the client has measured it:
DEFAULT_CELL_WIDTH: Final[int] = envint("XPRA_TERMINAL_CELL_WIDTH", 10)
DEFAULT_CELL_HEIGHT: Final[int] = envint("XPRA_TERMINAL_CELL_HEIGHT", 20)
# terminals are not physical screens, assume the usual 96 DPI:
DPI: Final[int] = envint("XPRA_TERMINAL_DPI", 96)
# flight recorder: append a copy of every byte written to the terminal to this file,
# so a corrupted session can be diagnosed - and replayed - offline:
CAPTURE_FILE: Final[str] = os.environ.get("XPRA_TERMINAL_CAPTURE", "")
# kitty keyboard protocol flags: 1=disambiguate, 2=report event types,
# 4=report alternate keys, 8=report all keys as escape codes, 16=report associated text.
# 16 is what tells us that shift+`a` produced `A` rather than `a`, and 4 is the fallback
# for the key releases which the protocol never reports any text for:
KEYBOARD_FLAGS: Final[int] = envint("XPRA_TERMINAL_KEYBOARD_FLAGS", 31)

CSI: Final[bytes] = b"\x1b["
ALT_SCREEN_ON: Final[bytes] = b"\x1b[?1049h"
ALT_SCREEN_OFF: Final[bytes] = b"\x1b[?1049l"
CURSOR_HIDE: Final[bytes] = b"\x1b[?25l"
CURSOR_SHOW: Final[bytes] = b"\x1b[?25h"
KEYBOARD_POP: Final[bytes] = b"\x1b[<u"
# 1002: button event tracking, 1003: any event tracking, 1006: SGR encoding, 1016: SGR pixel encoding
MOUSE_MODES: Final[tuple[int, ...]] = (1002, 1003, 1006, 1016)

# `TIOCGWINSZ` is the primary source of the terminal's pixel size, but a pty allocated by an
# intermediary which only forwards rows and columns (`docker exec` and friends) reports zeroes.
# These are the XTWINOPS queries the kitty graphics protocol documents as the fallback:
# `CSI 14 t` is answered with `CSI 4 ; <height> ; <width> t` (the text area, in pixels),
# `CSI 16 t` with `CSI 6 ; <height> ; <width> t` (the pixel size of a single cell):
TEXT_AREA_QUERY: Final[bytes] = b"\x1b[14t"
CELL_SIZE_QUERY: Final[bytes] = b"\x1b[16t"
SIZE_QUERIES: Final[tuple[bytes, ...]] = (TEXT_AREA_QUERY, CELL_SIZE_QUERY)
# the `kind` of the `CSI <kind> ; ... t` reports those queries are answered with:
TEXT_AREA_REPORT: Final[int] = 4
CELL_SIZE_REPORT: Final[int] = 6

# indexes into the list returned by `termios.tcgetattr`:
IFLAG: Final[int] = 0
OFLAG: Final[int] = 1
CFLAG: Final[int] = 2
LFLAG: Final[int] = 3
CC: Final[int] = 6

# the flags `cfmakeraw` clears, see POSIX.1-2017 chapter 11 "General Terminal Interface":
IFLAG_RAW_MASK: Final[int] = (termios.BRKINT | termios.ICRNL | termios.IGNBRK | termios.IGNCR |
                              termios.IGNPAR | termios.INLCR | termios.INPCK | termios.ISTRIP |
                              termios.IXANY | termios.IXOFF | termios.IXON | termios.PARMRK)
LFLAG_RAW_MASK: Final[int] = (termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ECHONL |
                              termios.ICANON | termios.IEXTEN | termios.ISIG | termios.NOFLSH |
                              termios.TOSTOP)

WINSIZE_FORMAT: Final[str] = "HHHH"      # struct winsize: ws_row, ws_col, ws_xpixel, ws_ypixel
WINSIZE_ZERO: Final[bytes] = b"\0" * 8


def make_raw(mode) -> None:
    """ apply `cfmakeraw` semantics in place to a mode list obtained from `termios.tcgetattr` """
    mode[IFLAG] &= ~IFLAG_RAW_MASK
    mode[OFLAG] &= ~termios.OPOST
    mode[CFLAG] = (mode[CFLAG] & ~(termios.CSIZE | termios.PARENB)) | termios.CS8
    mode[LFLAG] &= ~LFLAG_RAW_MASK
    # non canonical input, MIN=1 TIME=0: a read blocks until at least one byte is available
    cc = list(mode[CC])
    cc[termios.VMIN] = 1
    cc[termios.VTIME] = 0
    mode[CC] = cc


def get_terminal_size(fd: int) -> tuple[int, int, int, int]:
    """
    Query the terminal geometry: `(cols, rows, width_px, height_px)`.
    Terminals that do not report a pixel size return zeroes for the last two values,
    and everything is zero when the file descriptor is not a terminal.
    """
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, WINSIZE_ZERO)
        rows, cols, width_px, height_px = struct.unpack(WINSIZE_FORMAT, packed)
    except (OSError, ValueError, struct.error):
        log("get_terminal_size(%i)", fd, exc_info=True)
        return 0, 0, 0, 0
    return cols, rows, width_px, height_px


def cell_size_from_report(kind: int, values: Sequence[int], cols: int = 0, rows: int = 0) -> tuple[int, int]:
    """
    The `(width, height)` pixel size of a single terminal cell, derived from a `CSI ... t` report.
    A cell size report gives it directly, a text area report needs the terminal's `cols` and `rows`.
    Returns `(0, 0)` for a report we cannot use.
    """
    if len(values) < 2 or min(values[:2]) <= 0:
        return 0, 0
    height, width = values[0], values[1]
    if kind == CELL_SIZE_REPORT:
        return width, height
    if kind == TEXT_AREA_REPORT and cols > 0 and rows > 0:
        cell = (width // cols, height // rows)
        return cell if min(cell) > 0 else (0, 0)
    return 0, 0


class TerminalOutput:
    """
    The single writer to the terminal.
    The file object is injected so that tests can capture the bytes we emit.
    """
    __slots__ = ("fileobj", "failed", "capture")

    def __init__(self, fileobj):
        self.fileobj = fileobj
        self.failed = False
        self.capture = None
        if CAPTURE_FILE:
            try:
                self.capture = open(osexpand(CAPTURE_FILE), "ab")
            except OSError as e:
                log.warn("Warning: cannot open capture file %r", CAPTURE_FILE)
                log.warn(f" {e}")

    def __repr__(self):
        return f"TerminalOutput({self.fileobj})"

    def write(self, data: bytes) -> None:
        if self.failed or not data:
            return
        # all terminal writes must happen on the UI thread:
        check_main_thread()
        if self.capture is not None:
            try:
                self.capture.write(data)
            except (OSError, ValueError):
                self.capture = None
        try:
            # a raw (unbuffered) writer may write less than the whole buffer
            # (a signal arriving mid-write does exactly that): anything short
            # of a full write would truncate an escape sequence, so loop.
            # buffered writers return the full length (or `None`):
            view = memoryview(data)
            while view:
                written = self.fileobj.write(view)
                if written is None or written >= len(view):
                    break
                if written <= 0:
                    raise OSError(f"terminal write returned {written!r}")
                view = view[written:]
        except (OSError, ValueError) as e:
            self.failed = True
            log("write(%i bytes)", len(data), exc_info=True)
            log.warn("Warning: cannot write to the terminal")
            log.warn(f" {e}")

    def flush(self) -> None:
        if self.failed:
            return
        check_main_thread()
        if self.capture is not None:
            try:
                self.capture.flush()
            except (OSError, ValueError):
                self.capture = None
        try:
            self.fileobj.flush()
        except (OSError, ValueError) as e:
            self.failed = True
            log("flush()", exc_info=True)
            log.warn("Warning: cannot flush the terminal output")
            log.warn(f" {e}")


class TerminalContext:
    """
    Owns the terminal modes: raw input, alternate screen, hidden cursor,
    the kitty keyboard protocol flags and the mouse reporting modes.
    `exit` undoes exactly what `enter` did, in reverse order, and is idempotent.
    """
    __slots__ = ("fd", "output", "saved", "entered")

    def __init__(self, fd: int, output: TerminalOutput):
        self.fd = fd
        self.output = output
        self.saved = None
        self.entered = False

    def __repr__(self):
        return f"TerminalContext({self.fd}, active={self.entered})"

    @property
    def active(self) -> bool:
        return self.entered

    def enter(self) -> None:
        if self.entered:
            return
        try:
            self.saved = termios.tcgetattr(self.fd)
            mode = termios.tcgetattr(self.fd)
            make_raw(mode)
            termios.tcsetattr(self.fd, termios.TCSADRAIN, mode)
        except (termios.error, OSError) as e:
            # not a terminal, or a terminal we cannot configure:
            # still emit the escape sequences, the output may be a pipe into a real terminal
            self.saved = None
            log("enter()", exc_info=True)
            log.warn("Warning: cannot switch the terminal to raw mode")
            log.warn(f" {e}")
        self.entered = True
        output = self.output
        output.write(ALT_SCREEN_ON)
        output.write(CURSOR_HIDE)
        output.write(CSI + b">%iu" % KEYBOARD_FLAGS)
        for mode_id in MOUSE_MODES:
            output.write(CSI + b"?%ih" % mode_id)
        for query in SIZE_QUERIES:
            output.write(query)
        output.flush()

    def exit(self) -> None:
        if not self.entered:
            return
        self.entered = False
        output = self.output
        for mode_id in reversed(MOUSE_MODES):
            output.write(CSI + b"?%il" % mode_id)
        output.write(KEYBOARD_POP)
        output.write(CURSOR_SHOW)
        output.write(ALT_SCREEN_OFF)
        output.flush()
        saved = self.saved
        self.saved = None
        if saved is None:
            return
        try:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, saved)
        except (termios.error, OSError):
            log("exit()", exc_info=True)
