#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class WindowsBundleTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[3] / "packaging" / "MSWindows" / "BUILD.py"
        spec = importlib.util.spec_from_file_location("xpra_windows_bundle_build", str(path))
        cls.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.build)

    def test_gio_uses_openssl_without_gnutls(self):
        for light in (False, True):
            with self.subTest(light=light), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                dist = root / "dist"
                lib = dist / "lib"
                typelibs = lib / "girepository-1.0"
                typelibs.mkdir(parents=True)
                (typelibs / "Glib-2.0.typelib").touch()
                (lib / "gdk-pixbuf-2.0" / "2.10.0" / "loaders").mkdir(parents=True)
                prefix = root / "mingw"
                source = prefix / "lib" / "gio" / "modules"
                source.mkdir(parents=True)
                for module in ("libproxy", "openssl", "gnutls"):
                    (source / ("libgio%s.dll" % module)).write_bytes(module.encode("ascii"))
                with patch.object(self.build, "DIST", str(dist)), \
                        patch.object(self.build, "LIB_DIR", str(lib)), \
                        patch.object(self.build, "MINGW_PREFIX", str(prefix)), \
                        patch.object(self.build, "log_command") as command, \
                        patch.object(self.build, "find_delete"), redirect_stdout(io.StringIO()):
                    self.build.fixups(light)
                target = lib / "gio" / "modules"
                self.assertEqual({path.name for path in target.iterdir()}, {
                    "libgiolibproxy.dll", "libgioopenssl.dll",
                })
                self.assertEqual((target / "libgioopenssl.dll").read_bytes(), b"openssl")
                command.assert_called_once_with("gio-querymodules.exe %s/gio/modules" % lib, "gio-cache.log")

    def test_unused_cryptopp_is_removed_without_removing_openssl(self):
        removed = ("libcryptopp.dll", "libcryptopp-8.dll", "libkvazaar-7.dll", "libde265-0.dll")
        kept = ("libcrypto-3-x64.dll", "libssl-3-x64.dll")
        for light in (False, True):
            with self.subTest(light=light), tempfile.TemporaryDirectory() as directory:
                dist = Path(directory)
                lib = dist / "lib"
                lib.mkdir()
                for filename in removed + kept:
                    (lib / filename).touch()
                with patch.object(self.build, "DIST", str(dist)), redirect_stdout(io.StringIO()):
                    self.build.delete_dlls(light)
                self.assertEqual({path.name for path in lib.iterdir()}, set(kept))


if __name__ == '__main__':
    unittest.main()
