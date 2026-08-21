#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import fcntl
import struct
import termios
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from unit.test_util import silence_error

try:
    from xpra.client.terminal import tty as tty_module
except ImportError:
    tty_module = None

# the exact byte sequences the terminal context is contracted to emit
# (the keyboard flags are an env tunable, so the golden bytes derive from the constant):
if tty_module is not None:
    ENTER = (b"\x1b[?1049h\x1b[?25l" + b"\x1b[>%iu" % tty_module.KEYBOARD_FLAGS +
             b"\x1b[?1002h\x1b[?1003h\x1b[?1006h\x1b[?1016h"
             b"\x1b[14t\x1b[16t")
else:
    ENTER = b""
EXIT = b"\x1b[?1016l\x1b[?1006l\x1b[?1003l\x1b[?1002l\x1b[<u\x1b[?25h\x1b[?1049l"


class RecordingFile:
    """ minimal stand-in for a buffered binary file object """

    def __init__(self, fail=False):
        self.data = b""
        self.flushes = 0
        self.fail = fail

    def write(self, data: bytes) -> None:
        if self.fail:
            raise OSError(5, "Input/output error")
        self.data += data

    def flush(self) -> None:
        if self.fail:
            raise OSError(5, "Input/output error")
        self.flushes += 1


@unittest.skipIf(tty_module is None, "the terminal client tty module is not available")
class TestTerminalOutput(unittest.TestCase):

    def test_write_and_flush(self):
        buf = BytesIO()
        output = tty_module.TerminalOutput(buf)
        output.write(b"hello")
        output.write(b" world")
        output.flush()
        self.assertEqual(buf.getvalue(), b"hello world")

    def test_partial_raw_writes_are_completed(self):
        # a raw (unbuffered) writer may write less than the whole buffer,
        # e.g. when a signal arrives mid-write: the remainder must be written
        # too, anything else would truncate an escape sequence:
        class ShortWriter:
            def __init__(self):
                self.data = b""

            def write(self, data) -> int:
                take = min(3, len(data))
                self.data += bytes(data[:take])
                return take

        writer = ShortWriter()
        output = tty_module.TerminalOutput(writer)
        output.write(b"0123456789abcdef")
        self.assertEqual(writer.data, b"0123456789abcdef")
        self.assertFalse(output.failed)

    def test_write_empty_is_a_noop(self):
        recorder = RecordingFile()
        output = tty_module.TerminalOutput(recorder)
        output.write(b"")
        self.assertEqual(recorder.data, b"")

    def test_flush_is_forwarded(self):
        recorder = RecordingFile()
        output = tty_module.TerminalOutput(recorder)
        output.flush()
        output.flush()
        self.assertEqual(recorder.flushes, 2)

    def test_write_failure_is_not_fatal(self):
        recorder = RecordingFile(fail=True)
        output = tty_module.TerminalOutput(recorder)
        with silence_error(tty_module):
            output.write(b"hello")
            # the writer gives up after the first failure:
            output.write(b"more")
            output.flush()
        self.assertTrue(output.failed)
        self.assertEqual(recorder.data, b"")
        self.assertEqual(recorder.flushes, 0)

    def test_flush_failure_is_not_fatal(self):
        recorder = RecordingFile()
        output = tty_module.TerminalOutput(recorder)
        recorder.fail = True
        with silence_error(tty_module):
            output.flush()
        self.assertTrue(output.failed)


@unittest.skipIf(tty_module is None, "the terminal client tty module is not available")
class TestMakeRaw(unittest.TestCase):

    def setUp(self):
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)

    def test_make_raw_clears_the_expected_flags(self):
        mode = termios.tcgetattr(self.slave)
        tty_module.make_raw(mode)
        self.assertEqual(mode[tty_module.IFLAG] & tty_module.IFLAG_RAW_MASK, 0)
        self.assertEqual(mode[tty_module.OFLAG] & termios.OPOST, 0)
        self.assertEqual(mode[tty_module.LFLAG] & tty_module.LFLAG_RAW_MASK, 0)
        self.assertEqual(mode[tty_module.CFLAG] & termios.CSIZE, termios.CS8)
        self.assertEqual(mode[tty_module.CFLAG] & termios.PARENB, 0)
        self.assertEqual(mode[tty_module.CC][termios.VMIN], 1)
        self.assertEqual(mode[tty_module.CC][termios.VTIME], 0)

    def test_make_raw_does_not_touch_the_terminal(self):
        before = termios.tcgetattr(self.slave)
        mode = termios.tcgetattr(self.slave)
        tty_module.make_raw(mode)
        self.assertEqual(termios.tcgetattr(self.slave), before)


@unittest.skipIf(tty_module is None, "the terminal client tty module is not available")
class TestTerminalContext(unittest.TestCase):

    def setUp(self):
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        self.buf = BytesIO()
        self.output = tty_module.TerminalOutput(self.buf)
        self.context = tty_module.TerminalContext(self.slave, self.output)

    def written(self) -> bytes:
        return self.buf.getvalue()

    def test_defaults(self):
        # 1 disambiguate | 2 event types | 4 alternate keys | 8 all keys as escapes
        # | 16 report associated text.
        # 16 is what makes shift + `a` arrive as `A`, and 2 must stay set:
        # the client uses it to decide whether the terminal reports key releases
        for bit in (1, 2, 4, 8, 16):
            self.assertTrue(tty_module.KEYBOARD_FLAGS & bit, f"keyboard flag {bit} is not requested")
        self.assertEqual(tty_module.MOUSE_MODES, (1002, 1003, 1006, 1016))
        self.assertEqual(tty_module.SIZE_QUERIES, (b"\x1b[14t", b"\x1b[16t"))
        self.assertEqual((tty_module.TEXT_AREA_REPORT, tty_module.CELL_SIZE_REPORT), (4, 6))

    def test_enter_sequence(self):
        self.assertFalse(self.context.active)
        self.context.enter()
        self.assertTrue(self.context.active)
        self.assertEqual(self.written(), ENTER)

    def test_enter_ordering(self):
        self.context.enter()
        data = self.written()
        expected_order = (
            b"\x1b[?1049h",     # alternate screen first
            b"\x1b[?25l",       # then hide the cursor
            b"\x1b[>%iu" % tty_module.KEYBOARD_FLAGS,       # then push the kitty keyboard flags
            b"\x1b[?1002h",     # then the mouse modes, in ascending order
            b"\x1b[?1003h",
            b"\x1b[?1006h",
            b"\x1b[?1016h",
            b"\x1b[14t",        # then ask for the text area and cell pixel sizes
            b"\x1b[16t",
        )
        positions = [data.index(seq) for seq in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(positions), len(set(positions)))

    def test_enter_switches_to_raw_mode(self):
        self.context.enter()
        mode = termios.tcgetattr(self.slave)
        self.assertEqual(mode[tty_module.LFLAG] & (termios.ECHO | termios.ICANON | termios.ISIG), 0)
        self.assertEqual(mode[tty_module.OFLAG] & termios.OPOST, 0)
        self.assertEqual(mode[tty_module.IFLAG] & (termios.ICRNL | termios.IXON), 0)
        self.assertEqual(mode[tty_module.CC][termios.VMIN], 1)

    def test_enter_is_idempotent(self):
        self.context.enter()
        self.context.enter()
        self.assertEqual(self.written(), ENTER)

    def test_exit_sequence(self):
        self.context.enter()
        self.context.exit()
        self.assertEqual(self.written(), ENTER + EXIT)
        self.assertFalse(self.context.active)

    def test_exit_ordering_is_the_reverse_of_enter(self):
        self.context.enter()
        expected_order = (
            b"\x1b[?1016l",     # mouse modes off first, in reverse order
            b"\x1b[?1006l",
            b"\x1b[?1003l",
            b"\x1b[?1002l",
            b"\x1b[<u",         # pop the kitty keyboard flags
            b"\x1b[?25h",       # show the cursor
            b"\x1b[?1049l",     # back to the main screen last
        )
        self.context.exit()
        data = self.written()[len(ENTER):]
        positions = [data.index(seq) for seq in expected_order]
        self.assertEqual(positions, sorted(positions))

    def test_exit_restores_termios(self):
        saved = termios.tcgetattr(self.slave)
        self.context.enter()
        self.assertNotEqual(termios.tcgetattr(self.slave), saved)
        self.context.exit()
        self.assertEqual(termios.tcgetattr(self.slave), saved)

    def test_exit_is_idempotent(self):
        self.context.enter()
        self.context.exit()
        expected = self.written()
        self.context.exit()
        self.context.exit()
        self.assertEqual(self.written(), expected)

    def test_exit_without_enter_is_a_noop(self):
        self.context.exit()
        self.assertEqual(self.written(), b"")
        self.assertFalse(self.context.active)

    def test_enter_after_exit(self):
        self.context.enter()
        self.context.exit()
        self.context.enter()
        self.assertEqual(self.written(), ENTER + EXIT + ENTER)
        self.assertTrue(self.context.active)
        self.context.exit()

    def test_non_terminal_fd_still_emits_the_escape_sequences(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        buf = BytesIO()
        context = tty_module.TerminalContext(read_fd, tty_module.TerminalOutput(buf))
        with silence_error(tty_module):
            context.enter()
            self.assertTrue(context.active)
            self.assertEqual(buf.getvalue(), ENTER)
            context.exit()
        self.assertEqual(buf.getvalue(), ENTER + EXIT)


@unittest.skipIf(tty_module is None, "the terminal client tty module is not available")
class TestTerminalSize(unittest.TestCase):

    def setUp(self):
        self.master, self.slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)

    def set_size(self, rows: int, cols: int, width_px: int, height_px: int) -> None:
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, width_px, height_px))

    def test_size(self):
        self.set_size(24, 80, 640, 480)
        self.assertEqual(tty_module.get_terminal_size(self.slave), (80, 24, 640, 480))

    def test_size_changes(self):
        self.set_size(50, 132, 1584, 1100)
        self.assertEqual(tty_module.get_terminal_size(self.slave), (132, 50, 1584, 1100))
        self.set_size(24, 80, 640, 480)
        self.assertEqual(tty_module.get_terminal_size(self.slave), (80, 24, 640, 480))

    def test_size_from_the_master_side(self):
        self.set_size(24, 80, 640, 480)
        self.assertEqual(tty_module.get_terminal_size(self.master), (80, 24, 640, 480))

    def test_no_pixel_size_reported(self):
        self.set_size(24, 80, 0, 0)
        self.assertEqual(tty_module.get_terminal_size(self.slave), (80, 24, 0, 0))

    def test_large_values(self):
        self.set_size(1000, 2000, 40000, 50000)
        self.assertEqual(tty_module.get_terminal_size(self.slave), (2000, 1000, 40000, 50000))

    def test_not_a_terminal(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        self.assertEqual(tty_module.get_terminal_size(read_fd), (0, 0, 0, 0))

    def test_invalid_fd(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        os.close(write_fd)
        self.assertEqual(tty_module.get_terminal_size(read_fd), (0, 0, 0, 0))


@unittest.skipIf(tty_module is None, "the terminal client tty module is not available")
class TestCellSizeFromReport(unittest.TestCase):
    """ `CSI 14 t` / `CSI 16 t` are the fallback when `TIOCGWINSZ` reports no pixel size """

    def call(self, kind, values, cols=0, rows=0):
        return tty_module.cell_size_from_report(kind, values, cols, rows)

    def test_cell_size_report(self):
        # `CSI 6 ; <height> ; <width> t`:
        self.assertEqual(self.call(tty_module.CELL_SIZE_REPORT, (17, 8)), (8, 17))
        # the terminal size is irrelevant for this report:
        self.assertEqual(self.call(tty_module.CELL_SIZE_REPORT, (20, 10), 80, 24), (10, 20))

    def test_text_area_report(self):
        # `CSI 4 ; <height> ; <width> t` divided by the terminal size:
        self.assertEqual(self.call(tty_module.TEXT_AREA_REPORT, (408, 640), 80, 24), (8, 17))
        # without the terminal size it cannot be used:
        self.assertEqual(self.call(tty_module.TEXT_AREA_REPORT, (408, 640)), (0, 0))

    def test_unusable_reports(self):
        for kind, values, cols, rows in (
            (tty_module.CELL_SIZE_REPORT, (), 0, 0),            # no values
            (tty_module.CELL_SIZE_REPORT, (17, ), 0, 0),        # only one value
            (tty_module.CELL_SIZE_REPORT, (0, 8), 0, 0),        # a zero dimension
            (tty_module.CELL_SIZE_REPORT, (17, -1), 0, 0),      # a missing value
            (tty_module.TEXT_AREA_REPORT, (10, 10), 80, 24),    # smaller than one cell
            (8, (100, 200), 80, 24),                            # a report we did not ask for
        ):
            self.assertEqual(self.call(kind, values, cols, rows), (0, 0), f"kind {kind} {values}")

    def test_from_the_parser(self):
        from xpra.client.terminal.input import InputParser
        events = InputParser().feed(b"\x1b[6;20;10t")
        self.assertEqual(len(events), 1)
        report = events[0]
        self.assertEqual(tty_module.cell_size_from_report(report.kind, report.values), (10, 20))


@unittest.skipIf(tty_module is None, "the terminal client tty module is not available")
class TestCaptureTee(unittest.TestCase):

    def test_capture_records_every_byte(self):
        # `TerminalOutput` opens the capture file per instance,
        # so pinning the module constant is all it takes:
        with tempfile.NamedTemporaryFile() as capture, \
                patch.object(tty_module, "CAPTURE_FILE", capture.name):
            buf = BytesIO()
            out = tty_module.TerminalOutput(buf)
            out.write(b"\x1b_Ga=t;AAAA\x1b\\")
            out.write(b"plain")
            out.flush()
            self.assertEqual(capture.read(), buf.getvalue())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
