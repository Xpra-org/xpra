#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from base64 import b64encode

from xpra.net.common import Packet
from xpra.util.objects import AdHocStruct, typedict
from xpra.clipboard.common import parse_greedy
from unit.test_util import silence_warn

try:
    from xpra.client.terminal import clipboard as terminal_clipboard
    from xpra.client.terminal.subsystem import clipboard as clipboard_subsystem
except ImportError:
    terminal_clipboard = None
    clipboard_subsystem = None


def osc52_bytes(text: str) -> bytes:
    return b"\x1b]52;c;" + b64encode(text.encode("utf8")) + b"\x07"


class FakeClient:
    """ the terminal client, as far as the clipboard subsystem is concerned """

    def __init__(self):
        self.written: list[bytes] = []
        self.packets: list[tuple] = []
        self.write_osc52 = self.written.append

    def send_now(self, *packet) -> None:
        self.packets.append(packet)


@unittest.skipIf(terminal_clipboard is None, "the terminal client component is not available")
class OSC52ClipboardTest(unittest.TestCase):

    def make_helper(self, **kwargs):
        packets: list[tuple] = []
        # `osc52_write` defaults to `noop`, the tests inject a collector:
        written: list[bytes] = []
        kwargs.setdefault("can-send", True)
        kwargs.setdefault("can-receive", True)
        kwargs.setdefault("osc52-write", written.append)
        helper = terminal_clipboard.OSC52Clipboard(lambda *packet: packets.append(packet), **kwargs)
        self.addCleanup(helper.cleanup)
        helper.enable_selections(("CLIPBOARD", ))
        return helper, packets, written

    def make_proxy(self, **kwargs):
        helper, _, written = self.make_helper(**kwargs)
        return helper._clipboard_proxies["CLIPBOARD"], written

    def test_osc52_sequence(self):
        # `ESC ] 52 ; c ; <base64> BEL`
        self.assertEqual(terminal_clipboard.osc52("hello"), b"\x1b]52;c;aGVsbG8=\x07")
        self.assertEqual(terminal_clipboard.osc52(""), b"\x1b]52;c;\x07")
        self.assertEqual(terminal_clipboard.osc52("é"), b"\x1b]52;c;w6k=\x07")

    def test_selections(self):
        # OSC 52 can only address the terminal's clipboard,
        # whatever selections the platform may have:
        helper = self.make_helper()[0]
        self.assertEqual(tuple(helper._clipboard_proxies.keys()), ("CLIPBOARD", ))
        self.assertEqual(tuple(helper.local_selections), ("CLIPBOARD", ))
        self.assertEqual(helper.get_remote_selections(), ["CLIPBOARD"])
        self.assertEqual(helper.get_caps()["selections"], ("CLIPBOARD", ))
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        self.assertIsInstance(proxy, terminal_clipboard.OSC52ClipboardProxy)
        self.assertTrue(proxy.is_enabled())
        self.assertIn("CLIPBOARD", repr(proxy))

    def test_greedy_capability(self):
        # this proxy is receive-only and never sends a `clipboard-request`,
        # so the peer must send the contents with the token: that is what `greedy` asks for
        helper = self.make_helper()[0]
        caps = helper.get_caps()
        self.assertEqual(caps.get("greedy"), ("CLIPBOARD", ))
        self.assertEqual(tuple(helper.local_greedy), ("CLIPBOARD", ))
        self.assertTrue(helper.local_greedy_selection("CLIPBOARD"))
        # what the peer makes of it (`xpra.server.source.clipboard`):
        self.assertEqual(parse_greedy(typedict(caps), caps["selections"]), ("CLIPBOARD", ))

    def send_token_packet(self, targets, data) -> Packet:
        """ the wire packet a peer sends for a token with these targets and contents """
        peer, packets, _ = self.make_helper()
        peer_proxy = peer._clipboard_proxies["CLIPBOARD"]
        peer._send_clipboard_token_handler(peer_proxy, {"targets": targets, "data": data})
        self.assertEqual(len(packets), 1, f"expected a single packet, got {packets}")
        return Packet(*packets[0])

    def test_token_round_trip(self):
        helper, _, written = self.make_helper()
        # a greedy client gets the contents with the token:
        packet = self.send_token_packet(("UTF8_STRING", ),
                                        {"UTF8_STRING": ("UTF8_STRING", 8, b"from the peer")})
        helper.process_clipboard_packet(packet)
        self.assertEqual(written, [osc52_bytes("from the peer")])
        # a peer which does not send the contents leaves us with nothing to write,
        # which is why we must ask for them in the capabilities:
        written.clear()
        helper.process_clipboard_packet(self.send_token_packet((), {}))
        self.assertEqual(written, [])

    def test_got_token_text(self):
        proxy, written = self.make_proxy()
        for target, dtype, data, text in (
            ("UTF8_STRING", "UTF8_STRING", "howdy".encode("utf8"), "howdy"),
            ("UTF8_STRING", "UTF8_STRING", "héllo ☃".encode("utf8"), "héllo ☃"),
            ("STRING", "STRING", "café".encode("latin1"), "café"),
            ("TEXT", "TEXT", b"plain", "plain"),
            ("text/plain;charset=utf-8", "UTF8_STRING", "naïve".encode("utf8"), "naïve"),
            # not all peers send bytes:
            ("UTF8_STRING", "UTF8_STRING", "as a string", "as a string"),
        ):
            written.clear()
            proxy.got_token((target, ), {target: (dtype, 8, data)})
            self.assertEqual(written, [osc52_bytes(text)], f"for target {target!r}")

    def test_got_token_ignored(self):
        proxy, written = self.make_proxy()

        def nothing_written(reason: str) -> None:
            self.assertEqual(written, [], f"clipboard data was written {reason}")

        proxy.got_token(("UTF8_STRING", ), {})
        nothing_written("for an empty token")
        proxy.got_token(("UTF8_STRING", ), None)
        nothing_written("for a token without any data")
        # only text targets, only 8 bit formats, only non-empty data:
        proxy.got_token(("image/png", ), {"image/png": ("image/png", 8, b"\x89PNG")})
        nothing_written("for an image target")
        proxy.got_token(("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 32, b"1234")})
        nothing_written("for a 32 bit format")
        proxy.got_token(("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 8, b"")})
        nothing_written("for empty data")

    def test_direction(self):
        token = (("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 8, b"data")})
        # `--clipboard-direction=to-server`: we must not update the terminal's clipboard
        proxy, written = self.make_proxy(**{"can-receive": False})
        self.assertFalse(proxy._can_receive)
        proxy.got_token(*token)
        self.assertEqual(written, [])
        # a disabled selection is never updated either:
        proxy, written = self.make_proxy()
        proxy.set_enabled(False)
        proxy.got_token(*token)
        self.assertEqual(written, [])
        # `--clipboard-direction=to-client` still writes to the terminal:
        proxy, written = self.make_proxy(**{"can-send": False})
        self.assertFalse(proxy._can_send)
        proxy.got_token(*token)
        self.assertEqual(written, [osc52_bytes("data")])

    def test_without_a_writer_nothing_is_emitted(self):
        # `osc52_write` defaults to `noop`: a helper built without one must not raise
        from xpra.common import noop
        helper = terminal_clipboard.OSC52Clipboard(lambda *packet: None,
                                                   **{"can-send": True, "can-receive": True})
        self.addCleanup(helper.cleanup)
        helper.enable_selections(("CLIPBOARD", ))
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        self.assertIs(proxy.osc52_write, noop)
        proxy.got_token(("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 8, b"dropped")})

    def test_too_much_data(self):
        proxy, written = self.make_proxy()
        text = "x" * terminal_clipboard.MAX_OSC52_SIZE
        with silence_warn(terminal_clipboard):
            proxy.got_token(("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 8, text.encode())})
        self.assertEqual(written, [])

    def test_get_contents(self):
        proxy = self.make_proxy()[0]
        contents = []
        proxy.get_contents("TARGETS", lambda *args: contents.append(args))
        self.assertEqual(len(contents), 1)
        dtype, dformat, data = contents[0]
        self.assertEqual((dtype, dformat), ("ATOM", 32))
        self.assertIsInstance(data, tuple)
        # we cannot read the terminal's clipboard, so we have nothing to offer:
        self.assertEqual(data, ())
        contents = []
        proxy.get_contents("UTF8_STRING", lambda *args: contents.append(args))
        self.assertEqual(contents, [("UTF8_STRING", 0, b"")])

    def test_never_claims(self):
        helper, packets, _ = self.make_helper()
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        # the peer claiming the selection does not make us claim ours:
        proxy.got_token(("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 8, b"data")}, True)
        self.assertFalse(proxy._have_token)
        proxy.claim()
        proxy.do_emit_token()
        helper.send_all_tokens()
        self.assertEqual(packets, [])
        self.assertEqual(proxy._sent_token_events, 0)


@unittest.skipIf(clipboard_subsystem is None, "the terminal client component is not available")
class TerminalClipboardClientTest(unittest.TestCase):

    def make_subsystem(self, client, clipboard="yes", direction="both"):
        subsystem = clipboard_subsystem.TerminalClipboardClient()
        # the subsystem is normally constructed with its client:
        subsystem.client = client
        opts = AdHocStruct()
        opts.clipboard = clipboard
        opts.clipboard_direction = direction
        opts.local_clipboard = "CLIPBOARD"
        opts.remote_clipboard = "CLIPBOARD"
        subsystem.init(opts)
        return subsystem

    def test_make_clipboard_helper(self):
        client = FakeClient()
        subsystem = self.make_subsystem(client)
        helper = subsystem.make_clipboard_helper()
        self.addCleanup(helper.cleanup)
        self.assertIsInstance(helper, terminal_clipboard.OSC52Clipboard)
        self.assertEqual(repr(helper), "OSC52Clipboard")
        self.assertTrue(helper.can_send)
        self.assertTrue(helper.can_receive)
        # the hello capabilities ask the server to push the contents with the token:
        self.assertEqual(helper.get_caps().get("greedy"), ("CLIPBOARD", ))
        # the writes go to the client's terminal:
        helper.enable_selections(("CLIPBOARD", ))
        proxy = helper._clipboard_proxies["CLIPBOARD"]
        proxy.got_token(("UTF8_STRING", ), {"UTF8_STRING": ("UTF8_STRING", 8, b"from the server")})
        self.assertEqual(client.written, [osc52_bytes("from the server")])
        self.assertEqual(client.packets, [])

    def test_direction_options(self):
        subsystem = self.make_subsystem(FakeClient(), direction="to-server")
        helper = subsystem.make_clipboard_helper()
        self.addCleanup(helper.cleanup)
        self.assertTrue(helper.can_send)
        self.assertFalse(helper.can_receive)
        self.assertFalse(helper._clipboard_proxies["CLIPBOARD"]._can_receive)

    def test_clipboard_options(self):
        # `--clipboard=TYPE:option=value`
        subsystem = self.make_subsystem(FakeClient(), clipboard="osc52:max-send-size=1024")
        helper = subsystem.make_clipboard_helper()
        self.addCleanup(helper.cleanup)
        self.assertEqual(helper.max_clipboard_send_size, 1024)

    def test_disabled(self):
        subsystem = self.make_subsystem(FakeClient(), clipboard="no")
        self.assertIsNone(subsystem.make_clipboard_helper())
        self.assertFalse(subsystem.client_supports_clipboard)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
