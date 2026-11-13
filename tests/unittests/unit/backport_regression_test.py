import os
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class BackportRegressionTest(unittest.TestCase):
    def test_world_writable_for_other_user(self):
        from xpra.os_util import is_writable
        info = SimpleNamespace(st_uid=100, st_gid=200, st_mode=stat.S_IWOTH)
        with patch("xpra.os_util.os.stat", return_value=info), \
                patch("xpra.os_util.os.statvfs", return_value=SimpleNamespace(f_flag=0)):
            self.assertTrue(is_writable("example", 300, 400))

    def test_fips_digests(self):
        from xpra.net.digest import get_digests
        with patch("_hashlib.get_fips_mode", return_value=1):
            digests = get_digests()
        self.assertTrue(digests)
        self.assertTrue(all(x.startswith("hmac+") for x in digests))

    def test_disconnected_notification(self):
        from xpra.server.mixins.notification import NotificationForwarder
        server = NotificationForwarder()
        server.notifications = True
        server.get_server_source = Mock(return_value=None)
        server.notifications_forwarder = Mock()
        server._process_notification_close(None, ("notification-close", 1, 1, "expired"))
        server._process_notification_action(None, ("notification-action", 1, "default"))
        self.assertEqual(server.notifications_forwarder.mock_calls, [])

    def test_vfb_cleanup_process_group(self):
        from xpra.x11.vfb_util import kill_xvfb
        with patch("xpra.x11.vfb_util.os.getpgid", return_value=42), \
                patch("xpra.x11.vfb_util.os.killpg") as killpg, \
                patch.dict(os.environ, {"XAUTHORITY": ""}):
            kill_xvfb(42)
        killpg.assert_called_once()

    def test_control_socket_tries_all_directories(self):
        from xpra.server.proxy.proxy_instance_process import ProxyInstanceProcess
        instance = ProxyInstanceProcess.__new__(ProxyInstanceProcess)
        instance.socket_dirs = ("first", "second")
        instance.create_control_socket_at = Mock(side_effect=(False, True))
        self.assertTrue(instance.create_control_socket())
        self.assertEqual(instance.create_control_socket_at.call_count, 2)


if __name__ == "__main__":
    unittest.main()
