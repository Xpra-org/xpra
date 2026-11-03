# This file is part of Xpra.
# Copyright (C) 2026 kogeler
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Exercise notification delivery with the actual configured window composite."""

import subprocess
import sys
import textwrap
import unittest


SCRIPT = textwrap.dedent("""
    import sys
    import unittest
    from types import SimpleNamespace
    from unittest.mock import Mock
    from xpra.client.base import features

    systray, has_window, has_tray = map(int, sys.argv[1:])
    features.systray = bool(systray)
    features.tray = bool(has_tray)
    # Production resolves features before importing this composite.
    from xpra.client.subsystem.window import WindowClient
    from xpra.client.subsystem.notification import NotificationClient
    from xpra.client.subsystem.tray import TrayClient

    client = SimpleNamespace(subsystems={}, idle_add=Mock(),
                             timeout_add=Mock(), source_remove=Mock())
    expected_tray = None
    if has_tray:
        tray = TrayClient(client)
        tray.tray = object()
        client.subsystems['tray'] = tray
        expected_tray = tray.tray
    if has_window:
        window = WindowClient(client)
        client.subsystems['window'] = window
        if systray:
            expected_tray = object()
            window._id_to_window[7] = SimpleNamespace(
                is_tray=lambda: True, _metadata={'pid': 42},
                title='example', tray_widget=expected_tray,
            )
    notification = NotificationClient(client)
    notification.enabled = True
    notification.notifier = Mock()
    notification._show_notification('', 1, 'example', 0, '', 'hello',
                                    'body', (), {'pid': 42}, 1000, None)
    notification.notifier.show_notify.assert_called_once()
    check = unittest.TestCase()
    check.assertIs(notification.notifier.show_notify.call_args.args[1], expected_tray)
    check.assertEqual(notification.notifier.show_notify.call_args.args[5:7], ('', 'hello'))
""")


class NotificationTrayTest(unittest.TestCase):
    def test_actual_window_composition_with_optional_tray_features(self):
        for systray, window, tray in ((0, 1, 1), (0, 1, 0), (1, 1, 1), (1, 0, 1), (0, 0, 0)):
            with self.subTest(systray=systray, window=window, tray=tray):
                # Each real composite is imported once with its own startup flags.
                result = subprocess.run(
                    [sys.executable, "-c", SCRIPT, str(systray), str(window), str(tray)],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
