#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

try:
    import paramiko
    HAVE_PARAMIKO = bool(paramiko)
except ImportError:
    HAVE_PARAMIKO = False


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestLoadHostKeys(unittest.TestCase):

    def test_returns_tuple(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        result = load_host_keys()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_filename_is_string(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        filename, _ = load_host_keys()
        assert isinstance(filename, str)

    def test_host_keys_is_hostkeys(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        from paramiko.hostkeys import HostKeys
        _, host_keys = load_host_keys()
        assert isinstance(host_keys, HostKeys)

    def test_with_no_known_hosts(self):
        # Patch platform to return no known hosts files
        from xpra.net.ssh.paramiko.client import load_host_keys
        with patch("xpra.net.ssh.paramiko.client.get_ssh_known_hosts_files", return_value=[]):
            filename, host_keys = load_host_keys()
        assert filename == ""

    def test_with_real_known_hosts_file(self):
        from xpra.net.ssh.paramiko.client import load_host_keys
        from paramiko.rsakey import RSAKey
        from paramiko.hostkeys import HostKeys

        key = RSAKey.generate(1024)
        with tempfile.NamedTemporaryFile(mode="w", suffix="_known_hosts", delete=False) as f:
            path = f.name
            hk = HostKeys()
            hk.add("example.com", key.get_name(), key)
            hk.save(path)

        try:
            with patch("xpra.net.ssh.paramiko.client.get_ssh_known_hosts_files", return_value=[path]):
                filename, host_keys = load_host_keys()
            assert filename == path
            assert len(list(host_keys.keys())) > 0
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestVerifyHostkey(unittest.TestCase):

    def _gen_key(self):
        from paramiko.rsakey import RSAKey
        return RSAKey.generate(1024)

    def test_matching_key_returns_empty_string(self):
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key = self._gen_key()
        host_keys = HostKeys()
        host_keys.add("myhost.example", key.get_name(), key)
        with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=("", host_keys)):
            result = verify_hostkey("myhost.example", key,
                                    verifyhostkeydns=False,
                                    stricthostkeychecking=False,
                                    addkey=False)
        assert result == ""

    def test_different_key_unknown_host(self):
        # host not in known_hosts → prompts; mock confirm() to return False
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key = self._gen_key()
        host_keys = HostKeys()  # empty – host unknown
        with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=("", host_keys)):
            with patch("xpra.net.ssh.paramiko.client.confirm", return_value=False):
                result = verify_hostkey("unknown.host", key,
                                        verifyhostkeydns=False,
                                        stricthostkeychecking=False,
                                        addkey=False)
        assert "Unknown" in result or result != ""

    def test_strict_checking_known_mismatch(self):
        # Known host with a *different* key + strict → returns non-empty error string
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key_stored = self._gen_key()
        key_presented = self._gen_key()
        host_keys = HostKeys()
        host_keys.add("strict.host", key_stored.get_name(), key_stored)
        with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=("", host_keys)):
            result = verify_hostkey("strict.host", key_presented,
                                    verifyhostkeydns=False,
                                    stricthostkeychecking=True,
                                    addkey=False)
        assert result != ""

    def test_confirmed_unknown_with_addkey_true(self):
        # confirm() returns True; addkey=True → saves key (no crash)
        from xpra.net.ssh.paramiko.client import verify_hostkey
        from paramiko.hostkeys import HostKeys
        key = self._gen_key()
        host_keys = HostKeys()
        with tempfile.NamedTemporaryFile(mode="w", suffix="_kh", delete=False) as f:
            path = f.name
        try:
            with patch("xpra.net.ssh.paramiko.client.load_host_keys", return_value=(path, host_keys)):
                with patch("xpra.net.ssh.paramiko.client.confirm", return_value=True):
                    with patch("xpra.net.ssh.paramiko.client.get_ssh_known_hosts_files", return_value=[path]):
                        result = verify_hostkey("newhost.example", key,
                                                verifyhostkeydns=False,
                                                stricthostkeychecking=False,
                                                addkey=True)
            assert result == ""
        finally:
            if os.path.exists(path):
                os.unlink(path)


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestSafeLookup(unittest.TestCase):

    def test_regular_lookup(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        from paramiko import SSHConfig
        import io
        config_text = "Host myserver\n  HostName 192.168.1.1\n  User testuser\n"
        ssh_config = SSHConfig()
        ssh_config.parse(io.StringIO(config_text))
        result = safe_lookup(ssh_config, "myserver")
        assert isinstance(result, dict)
        assert result.get("hostname") == "192.168.1.1"
        assert result.get("user") == "testuser"

    def test_wildcard_lookup(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        from paramiko import SSHConfig
        import io
        config_text = "Host *\n  ServerAliveInterval 60\n"
        ssh_config = SSHConfig()
        ssh_config.parse(io.StringIO(config_text))
        result = safe_lookup(ssh_config, "*")
        assert isinstance(result, dict)

    def test_import_error_returns_empty(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        broken = MagicMock()
        broken.lookup = MagicMock(side_effect=ImportError("test import error"))
        broken._lookup = None
        result = safe_lookup(broken, "some.host")
        assert result == {}

    def test_key_error_returns_empty(self):
        from xpra.net.ssh.paramiko.client import safe_lookup
        broken = MagicMock()
        broken.lookup = MagicMock(side_effect=KeyError("test key error"))
        broken._lookup = None
        result = safe_lookup(broken, "some.host")
        assert result == {}


@unittest.skipUnless(HAVE_PARAMIKO, "paramiko not available")
class TestConnectToErrors(unittest.TestCase):

    def test_missing_host_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({})

    def test_missing_remote_xpra_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({"host": "localhost"})

    def test_missing_proxy_command_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({"host": "localhost", "remote_xpra": ["/usr/bin/xpra"]})

    def test_missing_display_as_args_raises(self):
        from xpra.net.ssh.paramiko.client import connect_to
        with self.assertRaises(KeyError):
            connect_to({
                "host": "localhost",
                "remote_xpra": ["/usr/bin/xpra"],
                "proxy_command": ["_proxy_start"],
            })


def main():
    unittest.main()


if __name__ == "__main__":
    main()
