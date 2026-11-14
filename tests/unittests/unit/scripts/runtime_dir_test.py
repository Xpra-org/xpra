import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.scripts.server import create_runtime_dir


class TestRuntimeDir(unittest.TestCase):

    def test_existing_runtime_dir_modes(self):
        uid, gid = os.getuid(), os.getgid()
        for xrd_mode, xpra_mode, ok in (
            (0o700, 0o700, True),
            (0o700, 0o755, True),
            (0o700, 0o750, True),
            (0o700, 0o775, False),
            (0o700, 0o757, False),
            (0o750, 0o700, False),
            (0o755, 0o755, False),
        ):
            with self.subTest(xrd_mode=oct(xrd_mode), xpra_mode=oct(xpra_mode)), \
                    tempfile.TemporaryDirectory() as parent, \
                    patch("xpra.scripts.server.POSIX", True), \
                    patch("xpra.scripts.server.getuid", return_value=0), \
                    patch("xpra.scripts.server.os.lchown"):
                runtime_dir = os.path.join(parent, str(uid))
                xpra_dir = os.path.join(runtime_dir, "xpra")
                os.mkdir(runtime_dir)
                os.mkdir(xpra_dir)
                os.chmod(xpra_dir, xpra_mode)
                os.chmod(runtime_dir, xrd_mode)
                if ok:
                    self.assertEqual(create_runtime_dir(runtime_dir, uid, gid), runtime_dir)
                else:
                    with self.assertRaises(PermissionError):
                        create_runtime_dir(runtime_dir, uid, gid)
                self.assertEqual(os.stat(runtime_dir).st_mode & 0o777, xrd_mode)
                self.assertEqual(os.stat(xpra_dir).st_mode & 0o777, xpra_mode)


if __name__ == "__main__":
    unittest.main()
