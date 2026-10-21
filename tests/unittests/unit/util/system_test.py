#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>

import errno
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

import xpra
from xpra.util import system


class DistributionTest(unittest.TestCase):

    def test_os_release_is_cached_and_version_is_unquoted(self):
        data = b'NAME="Debian GNU/Linux"\nVERSION_ID="13"\n'
        with patch.object(system, "POSIX", True), patch.object(system, "os_release_file_data", None), \
                patch.object(system, "load_binary_file", return_value=data) as load:
            self.assertTrue(system.is_distribution_variant("Debian"))
            self.assertEqual(system.get_distribution_version_id(), "13")
            self.assertEqual(system.load_os_release_file(), data.decode())
            load.assert_called_once_with("/etc/os-release")

    def test_distribution_fallbacks_and_failures(self):
        with patch.object(system, "POSIX", True), patch.object(system, "load_os_release_file", side_effect=OSError("missing")), \
                patch.object(system, "get_linux_distribution") as distribution:
            for name, query, expected in (("Fedora", "Fedora", True), ("RedHatEnterprise", "RedHat", True), ("Other", "Debian", False)):
                with self.subTest(name=name):
                    distribution.return_value = name, "1", "test"
                    self.assertEqual(system.is_distribution_variant(query), expected)
            distribution.side_effect = ValueError("unknown")
            self.assertFalse(system.is_distribution_variant("Debian"))
            self.assertEqual(system.get_distribution_version_id(), "")
        with patch.object(system, "POSIX", False):
            self.assertFalse(system.is_distribution_variant())
            self.assertEqual(system.get_distribution_version_id(), "")

    def test_arch_and_package_family_detection(self):
        with patch.object(system, "POSIX", True), patch.object(system, "load_os_release_file") as load:
            for data, expected in (('ID="arch"', True), ('ID="manjaro"', True),
                                   ('broken\nID=test\nID_LIKE="debian archlinux"', True), ('ID=other', False), ("", False)):
                with self.subTest(data=data):
                    load.return_value = data
                    self.assertEqual(system.is_Arch(), expected)
            load.return_value = 'NAME="Fedora Linux"\n'
            self.assertTrue(system.is_RPM())
            load.return_value = 'NAME="Ubuntu"\n'
            self.assertTrue(system.is_DEB())
            self.assertEqual(system.get_distribution_version_id(), "")
        with patch.object(system, "POSIX", True), patch.object(system, "load_os_release_file", side_effect=ValueError), \
                patch.object(system, "is_distribution_variant", side_effect=lambda name: name == "Manjaro"):
            self.assertTrue(system.is_Arch())

    def test_lsb_release_parsing_and_caching(self):
        proc = Mock(returncode=0)
        proc.communicate.return_value = ('Distributor ID:\tExample\nRelease: 1.2\nCodename: test\ninvalid\n', "")
        with patch.object(system, "LINUX", True), patch.object(system, "_linux_distribution", ("", "", "")), \
                patch("subprocess.Popen", return_value=proc) as popen:
            self.assertEqual(system.get_linux_distribution(), ("Example", "1.2", "test"))
            self.assertEqual(system.get_linux_distribution(), ("Example", "1.2", "test"))
            popen.assert_called_once()

    def test_lsb_release_failure_uses_legacy_probe_or_unknown(self):
        with patch.object(system, "LINUX", True), patch("subprocess.Popen", side_effect=OSError("missing")), \
                patch("platform.linux_distribution", return_value=("Legacy", "1", "test"), create=True) as legacy:
            with patch.object(system, "_linux_distribution", ("", "", "")):
                self.assertEqual(system.get_linux_distribution(), ("Legacy", "1", "test"))
            legacy.side_effect = AttributeError("removed")
            with patch.object(system, "_linux_distribution", ("", "", "")):
                self.assertEqual(system.get_linux_distribution(), ("unknown", "unknown", "unknown"))


class DisplayDetectionTest(unittest.TestCase):

    def test_wayland_environment_precedence(self):
        for values, expected in (({}, False), ({"WAYLAND_DISPLAY": "wayland-0"}, True),
                                 ({"XDG_SESSION_TYPE": "wayland"}, True), ({"GDK_BACKEND": "wayland"}, True),
                                 ({"GDK_BACKEND": "x11", "WAYLAND_DISPLAY": "wayland-0"}, False)):
            with self.subTest(values=values):
                self.assertEqual(system.is_Wayland(values), expected)
        with patch.object(system, "_saved_env", {"GDK_BACKEND": "wayland"}):
            self.assertTrue(system.is_Wayland())

    def test_x11_backend_overrides(self):
        with patch.dict(os.environ, {"XPRA_NOX11": "1"}):
            self.assertFalse(system.is_X11())
        with patch.dict(os.environ, {"XPRA_NOX11": "0"}):
            for backend, expected in (("x11", True), ("wayland", False)):
                with self.subTest(backend=backend), patch.dict(os.environ, {"GDK_BACKEND": backend}):
                    self.assertEqual(system.is_X11(), expected)
            with patch.object(xpra, "x11", None, create=True):
                self.assertFalse(system.is_X11())

    def test_xwayland_probes_and_missing_extensions(self):
        bindings = SimpleNamespace(isX11=Mock(), isxwayland=Mock())
        with patch.dict(os.environ, {"XPRA_NOX11": "0", "XPRA_GTK": "0", "GDK_BACKEND": ""}), \
                patch.multiple(system, OSX=False, WIN32=False), \
                patch.dict(sys.modules, {"xpra.x11.bindings.xwayland": bindings}):
            for is_x11, is_wayland, expected in ((False, False, False), (True, True, False), (True, False, True)):
                with self.subTest(is_x11=is_x11, is_wayland=is_wayland):
                    bindings.isX11.return_value = is_x11
                    bindings.isxwayland.return_value = is_wayland
                    self.assertEqual(system.is_X11(), expected)
            with patch.dict(sys.modules, {"xpra.x11.bindings.xwayland": None}):
                self.assertTrue(system.is_X11())
            with patch.object(system, "WIN32", True):
                self.assertFalse(system.is_X11())
            with patch.dict(os.environ, {"XPRA_GTK": "1"}), \
                    patch.dict(sys.modules, {"xpra.x11.gtk.bindings": SimpleNamespace(is_X11_Display=lambda: True)}):
                self.assertTrue(system.is_X11())


class SystemProbeTest(unittest.TestCase):

    def test_virtualbox_probes(self):
        with patch.object(os, "name", "posix"):
            self.assertFalse(system.is_VirtualBox())
        with patch("ctypes.cdll.LoadLibrary", return_value=object()), patch.object(os, "name", "nt"):
            self.assertTrue(system.is_VirtualBox())
        with patch("ctypes.cdll.LoadLibrary", side_effect=OSError("missing")), patch.object(os, "name", "nt"):
            with patch("builtins.open", mock_open()):
                self.assertTrue(system.is_VirtualBox())
            for code, expected in ((errno.EACCES, True), (errno.ENOENT, False)):
                with self.subTest(code=code), patch("builtins.open", side_effect=OSError(code, "probe failed")):
                    self.assertEqual(system.is_VirtualBox(), expected)

    def test_platform_names_and_icons(self):
        for platform, expected in (("win32", "win32"), ("darwin", "osx"), ("linux2", "linux"),
                                   ("freebsd14", "freebsd"), ("openbsd7", "openbsd"), ("other", "")):
            with self.subTest(platform=platform):
                self.assertEqual(system.get_platform_icon_name(platform), expected)
        self.assertEqual(system.platform_name("", ""), "unknown")
        self.assertEqual(system.platform_name("linux", ("Debian", "13", "unknown")), "Linux Debian 13")
        self.assertEqual(system.platform_name("other", "1"), "other 1")

    def test_system_configuration_errors_are_isolated(self):
        with patch("sysconfig.get_platform", return_value="test"), patch("sysconfig.get_python_version", return_value="3.14"), \
                patch("sysconfig.get_config_vars", side_effect=ModuleNotFoundError("unavailable")), \
                patch("sysconfig.get_paths", side_effect=RuntimeError("broken")), patch.object(system, "get_util_logger"):
            for win32 in (False, True):
                with self.subTest(win32=win32), patch.object(system, "WIN32", win32):
                    self.assertEqual(system.get_sysconfig_info(), {"platform": "test", "python-version": "3.14"})

    def test_memory_and_load_queries(self):
        with patch.object(os, "sysconf", side_effect=lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key]):
            self.assertEqual(system.get_mem_size(), 4194304)
        with patch.object(os, "sysconf", side_effect=OSError("unavailable")), patch("xpra.log.Logger"):
            self.assertEqual(system.get_mem_size(), 0)
        with patch.object(system, "POSIX", True), patch.object(os, "getloadavg", return_value=(1.2, 2.8, 3.5)):
            self.assertEqual(system.getloadavg(), (1, 2, 3))
        with patch.multiple(system, POSIX=False, WIN32=False):
            self.assertEqual(system.getloadavg(), (0, 0, 0))
        with patch.multiple(system, POSIX=False, WIN32=True), patch.dict(sys.modules, {"psutil": None}):
            self.assertEqual(system.getloadavg(), (0, 0, 0))

    def test_free_threaded_configuration_and_runtime(self):
        with patch("sysconfig.get_config_var", return_value=1):
            self.assertTrue(system.is_free_threaded())
        with patch("sysconfig.get_config_var", return_value=0):
            for enabled in (True, False):
                with patch.object(sys, "_is_gil_enabled", return_value=enabled, create=True):
                    self.assertEqual(system.is_free_threaded(), not enabled)

    def test_platform_release_probes(self):
        with patch.object(system, "WIN32", True), patch.dict(sys.modules, {"xpra.platform.win32": SimpleNamespace(os_name="Windows test")}):
            self.assertEqual(system.platform_release("Server"), "Windows test")
        with patch.multiple(system, WIN32=False, OSX=True), patch("builtins.open", mock_open()), \
                patch("plistlib.load", return_value={"ProductUserVisibleVersion": "15.1"}):
            self.assertEqual(system.platform_release("Darwin"), "15.1")
        with patch.multiple(system, WIN32=False, OSX=True), patch("builtins.open", side_effect=OSError("missing")), \
                patch.object(system, "get_util_logger"):
            self.assertEqual(system.platform_release("Darwin"), "Darwin")

    def test_processor_names(self):
        with patch("platform.system", return_value="Linux"), patch("builtins.open", mock_open(read_data="other\nmodel name : Test CPU\n")):
            self.assertEqual(system.get_processor_name(), "Test CPU")
        with patch("platform.system", return_value="Darwin"), patch("subprocess.check_output", return_value=" Apple CPU\n"), \
                patch.dict(os.environ, {"PATH": "/bin"}):
            self.assertEqual(system.get_processor_name(), "Apple CPU")
            self.assertEqual(os.environ["PATH"], "/bin")
        with patch("platform.system", return_value="Windows"), patch("platform.processor", return_value="Windows CPU"):
            self.assertEqual(system.get_processor_name(), "Windows CPU")

    def test_process_liveness_and_termination_failure(self):
        system.stop_proc(None)
        self.assertFalse(system.is_child_alive(None))
        proc = Mock()
        proc.poll.return_value = 0
        system.stop_proc(proc)
        self.assertFalse(system.is_child_alive(proc))
        proc.terminate.assert_not_called()
        proc.poll.return_value = None
        proc.terminate.side_effect = OSError("already stopped")
        self.assertTrue(system.is_child_alive(proc))
        with patch.object(system, "get_util_logger"):
            system.stop_proc(proc)
        proc.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
