#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest


class TestVfbUtil(unittest.TestCase):

    # valid_xauth
    def test_valid_xauth_empty(self):
        from xpra.x11.vfb_util import valid_xauth
        assert valid_xauth("") == ""

    def test_valid_xauth_missing_file(self):
        from xpra.x11.vfb_util import valid_xauth
        assert valid_xauth("/tmp/xpra-test-this-does-not-exist-xauth") == ""

    def test_valid_xauth_existing(self):
        from xpra.x11.vfb_util import valid_xauth
        with tempfile.NamedTemporaryFile() as tf:
            result = valid_xauth(tf.name)
            # result is either the path (writable) or "" (not writable)
            assert result in (tf.name, "")

    # save_input_conf
    def test_save_input_conf_pointer(self):
        from xpra.x11.vfb_util import save_input_conf
        with tempfile.TemporaryDirectory() as d:
            path = save_input_conf(d, 0, "pointer", "test-uuid-1234", os.getuid(), os.getgid())
            assert os.path.isfile(path), f"expected file at {path}"
            with open(path) as fh:
                content = fh.read()
            assert "InputClass" in content
            assert "test-uuid-1234" in content
            assert "Pointer" in content
            assert "00-pointer.conf" in path

    def test_save_input_conf_touchpad(self):
        from xpra.x11.vfb_util import save_input_conf
        with tempfile.TemporaryDirectory() as d:
            path = save_input_conf(d, 1, "touchpad", "uuid-5678", os.getuid(), os.getgid())
            assert os.path.isfile(path)
            with open(path) as fh:
                content = fh.read()
            assert "Touchpad" in content
            assert "uuid-5678" in content

    # get_xvfb_env
    def test_get_xvfb_env_returns_dict(self):
        from xpra.x11.vfb_util import get_xvfb_env
        env = get_xvfb_env("/usr/bin/Xvfb")
        assert isinstance(env, dict)

    def test_get_xvfb_env_xephyr_uses_display(self):
        from xpra.x11.vfb_util import get_xvfb_env
        from xpra.util.env import OSEnvContext
        with OSEnvContext(DISPLAY=":42"):
            env = get_xvfb_env("/usr/bin/Xephyr")
            assert "DISPLAY" in env

    # patch_xvfb_command_fps
    def test_patch_fps_update_existing(self):
        from xpra.x11.vfb_util import patch_xvfb_command_fps
        cmd = ["/usr/bin/Xvfb", "-fakescreenfps", "10"]
        patch_xvfb_command_fps(cmd, 60)
        idx = cmd.index("-fakescreenfps")
        assert cmd[idx + 1] == "60", f"expected '60', got {cmd[idx+1]!r}"

    def test_patch_fps_no_fakescreenfps(self):
        from xpra.x11.vfb_util import patch_xvfb_command_fps
        cmd = ["/usr/bin/Xvfb"]
        # should not raise, may or may not add -fakescreenfps
        patch_xvfb_command_fps(cmd, 30)

    # patch_xvfb_command_geometry
    def test_patch_geometry_too_short_geom(self):
        from xpra.x11.vfb_util import patch_xvfb_command_geometry
        cmd = ["/usr/bin/Xvfb"]
        original = list(cmd)
        patch_xvfb_command_geometry(cmd, (1920,), 24)
        assert cmd == original, "should not modify cmd for incomplete geometry"

    def test_patch_geometry_non_xvfb(self):
        from xpra.x11.vfb_util import patch_xvfb_command_geometry
        cmd = ["/usr/bin/Xorg", "-screen", "800x600x24"]
        original = list(cmd)
        patch_xvfb_command_geometry(cmd, (1920, 1080), 24)
        assert cmd == original, "should not modify Xorg command"

    def test_patch_geometry_xvfb_replaces_screen(self):
        from xpra.x11.vfb_util import patch_xvfb_command_geometry
        cmd = ["/usr/bin/Xvfb", "-screen", "0", "1024x768x24"]
        patch_xvfb_command_geometry(cmd, (1920, 1080), 32)
        assert "-screen" in cmd
        assert "1920x1080x32" in cmd

    def test_patch_geometry_xvfb_default_depth(self):
        from xpra.x11.vfb_util import patch_xvfb_command_geometry
        # pixel_depth=0 → defaults to 32
        cmd = ["/usr/bin/Xvfb"]
        patch_xvfb_command_geometry(cmd, (800, 600), 0)
        assert "800x600x32" in cmd

    def test_patch_geometry_invalid_depth(self):
        from xpra.x11.vfb_util import patch_xvfb_command_geometry
        cmd = ["/usr/bin/Xvfb"]
        with self.assertRaises(ValueError):
            patch_xvfb_command_geometry(cmd, (1024, 768), 7)

    def test_patch_geometry_xephyr(self):
        from xpra.x11.vfb_util import patch_xvfb_command_geometry
        cmd = ["/usr/bin/Xephyr"]
        patch_xvfb_command_geometry(cmd, (1280, 720), 16)
        assert "-screen" in cmd
        assert "1280x720x16" in cmd

    # patch_uinput
    def test_patch_uinput_no_config_arg(self):
        from xpra.x11.vfb_util import patch_uinput
        cmd = ["/usr/bin/Xorg"]
        assert patch_uinput(cmd) is False

    def test_patch_uinput_config_present(self):
        from xpra.x11.vfb_util import patch_uinput
        cmd = ["/usr/bin/Xorg", "-config", "/etc/xpra/xorg.conf"]
        result = patch_uinput(cmd)
        assert result is True

    def test_patch_uinput_config_last_raises(self):
        from xpra.x11.vfb_util import patch_uinput
        from xpra.scripts.config import InitException
        cmd = ["/usr/bin/Xorg", "-config"]
        with self.assertRaises(InitException):
            patch_uinput(cmd)

    # patch_pixel_depth
    def test_patch_depth_update_existing(self):
        from xpra.x11.vfb_util import patch_pixel_depth
        cmd = ["/usr/bin/Xvfb", "-depth", "16"]
        patch_pixel_depth(cmd, 32)
        idx = cmd.index("-depth")
        assert cmd[idx + 1] == "32"

    def test_patch_depth_add_for_xorg(self):
        from xpra.x11.vfb_util import patch_pixel_depth
        cmd = ["/usr/bin/Xorg"]
        patch_pixel_depth(cmd, 24)
        assert "-depth" in cmd
        assert "24" in cmd

    def test_patch_depth_no_add_for_xvfb(self):
        from xpra.x11.vfb_util import patch_pixel_depth
        cmd = ["/usr/bin/Xvfb"]
        original = list(cmd)
        patch_pixel_depth(cmd, 24)
        assert cmd == original, "Xvfb should not auto-add -depth"

    def test_patch_depth_last_raises(self):
        from xpra.x11.vfb_util import patch_pixel_depth
        from xpra.scripts.config import InitException
        cmd = ["/usr/bin/Xvfb", "-depth"]
        with self.assertRaises(InitException):
            patch_pixel_depth(cmd, 24)

    # get_logfile_arg
    def test_get_logfile_arg_found(self):
        from xpra.x11.vfb_util import get_logfile_arg
        cmd = ["/usr/bin/Xorg", "-logfile", "/var/log/xorg.log"]
        assert get_logfile_arg(cmd) == "/var/log/xorg.log"

    def test_get_logfile_arg_absent(self):
        from xpra.x11.vfb_util import get_logfile_arg
        assert get_logfile_arg(["/usr/bin/Xorg"]) == ""

    def test_get_logfile_arg_last_raises(self):
        from xpra.x11.vfb_util import get_logfile_arg
        from xpra.scripts.config import InitException
        with self.assertRaises(InitException):
            get_logfile_arg(["/usr/bin/Xorg", "-logfile"])

    # check_xvfb_process
    def test_check_xvfb_process_none(self):
        from xpra.x11.vfb_util import check_xvfb_process
        assert check_xvfb_process(None) is True

    def test_check_xvfb_process_none_with_args(self):
        from xpra.x11.vfb_util import check_xvfb_process
        assert check_xvfb_process(None, cmd="Xvfb", timeout=0) is True


def main():
    unittest.main()


if __name__ == '__main__':
    main()
