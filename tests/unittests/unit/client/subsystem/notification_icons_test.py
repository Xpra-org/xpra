#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO

from xpra.net.common import Packet
from xpra.client.subsystem.notification import NotificationClient
from xpra.client.subsystem.decode import Decode
from xpra.notification.common import ICON_MAX_SIZE
from unit.test_util import stubbable


PAYLOAD = b"payload-the-server-smuggled-in"


def png(width: int, height: int, mode="RGBA") -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new(mode, (width, height), (0, 255, 0, 255)[:len(mode)]).save(buf, "png")
    return buf.getvalue()


def hostile_png(width: int, height: int, mode="RGBA") -> bytes:
    """
    a valid PNG carrying data a decoder is meant to ignore: a text chunk and bytes
    trailing after IEND. Re-encoding the *pixels* is what drops them - which is how we
    tell that the bytes handed to the backends are ours and not the ones off the wire
    (a straight re-encode of the same pixels is byte-identical, so comparing to the
    input proves nothing).
    """
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()
    meta.add_text("Comment", PAYLOAD.decode())
    buf = BytesIO()
    Image.new(mode, (width, height), (0, 255, 0, 255)[:len(mode)]).save(buf, "png", pnginfo=meta)
    return buf.getvalue() + PAYLOAD


class FakeNotifier:
    def __init__(self):
        self.shown = []
        self.closed = []

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                    summary, body, actions, hints, expire_timeout, icon):
        self.shown.append((nid, hints, icon))

    def close_notify(self, nid):
        self.closed.append(nid)

    def cleanup(self):
        """ nothing to clean up """


class FakeClient:
    """ stands in for the owning client: runs `idle_add` inline """

    def __init__(self):
        self.exit_code = None
        self.subsystems: dict[str, object] = {}

    @staticmethod
    def idle_add(fn, *args) -> int:
        fn(*args)
        return 0

    timeout_add = idle_add

    @staticmethod
    def source_remove(_tid: int) -> None:
        """ `idle_add` above runs synchronously, nothing to remove """

    @staticmethod
    def _ui_event() -> None:
        """ recorded by the real client, irrelevant here """


class FakeEncodings:
    PREFIX = "encoding"

    @staticmethod
    def get_core_encodings():
        return "png", "jpeg", "webp"


class NotificationIconsTest(unittest.TestCase):
    """
    every icon the server sends must be re-encoded into a PNG we generated ourselves,
    so that the notification backends (and the notification daemon we hand the icon
    file to) never parse bytes that came off the network.
    """

    def setUp(self):
        self.client = FakeClient()
        self.notifications = NotificationClient(client=self.client)
        self.notifications.enabled = True
        self.notifier = FakeNotifier()
        self.notifications.notifier = self.notifier
        self.client.subsystems = {
            "encoding": FakeEncodings(),
            "notification": self.notifications,
        }

    def show(self, icon=None, hints=None) -> None:
        # no `decode` subsystem: `add_decode_work` runs the decode inline
        self.notifications._process_notification_show(
            Packet("notification-show", "", 1, "app", 0, "", "summary", "body", 10 * 1000,
                   icon or (), ("0", "Hello"), hints or {})
        )

    def test_icon_is_reencoded(self):
        server_png = hostile_png(32, 32)
        self.assertIn(PAYLOAD, server_png)
        self.show(icon=("png", 32, 32, server_png))
        self.assertEqual(len(self.notifier.shown), 1)
        _nid, _hints, icon = self.notifier.shown[0]
        self.assertEqual(icon[0], "png")
        self.assertEqual(icon[1:3], (32, 32))
        # the bytes handed to the notifier are ours: only the pixels survived
        self.assertNotIn(PAYLOAD, bytes(icon[3]))

    def test_dimensions_come_from_the_image_not_the_packet(self):
        # a server claiming a different size (and encoding) than the data it sent:
        self.show(icon=("webp", 4096, 4096, png(16, 24)))
        _nid, _hints, icon = self.notifier.shown[0]
        self.assertEqual(icon[0], "png")
        self.assertEqual(icon[1:3], (16, 24))

    def test_oversized_icon_is_clamped(self):
        self.show(icon=("png", 1024, 512, png(1024, 512, "RGB")))
        _nid, _hints, icon = self.notifier.shown[0]
        self.assertEqual(max(icon[1:3]), ICON_MAX_SIZE)

    def test_undecodable_icon_is_dropped(self):
        self.show(icon=("png", 8, 8, b"<not an image>"))
        _nid, _hints, icon = self.notifier.shown[0]
        self.assertIsNone(icon)

    def test_unsupported_encoding_is_dropped(self):
        self.show(icon=("tiff", 8, 8, png(8, 8)))
        _nid, _hints, icon = self.notifier.shown[0]
        self.assertIsNone(icon)

    def test_icon_hints_are_sanitized(self):
        # `image-data` reaches the dbus backend, `app-icon-data` is written to a temp file:
        server_png = hostile_png(20, 20)
        self.show(hints={
            "app-icon-data": ("png", 20, 20, server_png),
            "image-data": ("png", 20, 20, server_png),
            "urgency": 2,
        })
        _nid, hints, _icon = self.notifier.shown[0]
        for attr in ("app-icon-data", "image-data"):
            self.assertEqual(hints[attr][0], "png")
            self.assertNotIn(PAYLOAD, bytes(hints[attr][3]), f"{attr!r} was not re-encoded")
        self.assertEqual(hints["urgency"], 2, "non-icon hints must be left alone")

    def test_undecodable_hint_is_dropped(self):
        self.show(hints={"image-data": ("png", 8, 8, b"<not an image>")})
        _nid, hints, _icon = self.notifier.shown[0]
        self.assertNotIn("image-data", hints)

    def test_close_cannot_overtake_its_show(self):
        # the show waits for its icon to be decoded, so the close must go through the same
        # FIFO queue - otherwise it would run first and leave the notification on screen
        decode = stubbable(Decode)(client=self.client)
        decode.preload = lambda: None
        decode.install_seccomp = lambda: None
        self.client.subsystems["decode"] = decode
        order = []
        self.notifier.show_notify = lambda *args: order.append("show")
        self.notifier.close_notify = lambda nid: order.append("close")
        decode.run()
        try:
            self.show(icon=("png", 32, 32, png(32, 32)))
            self.notifications._process_notification_close(Packet("notification-close", 1))
            decode.cleanup()
            decode._thread.join(5) if decode._thread else None
        finally:
            self.client.subsystems.pop("decode")
        self.assertEqual(order, ["show", "close"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
