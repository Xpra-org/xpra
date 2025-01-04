#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=line-too-long

import os
import sys
import unittest
import tempfile
import uuid
import hmac
from time import monotonic
from typing import Callable

from xpra.os_util import WIN32, OSX, POSIX, get_hex_uuid
from xpra.util.env import OSEnvContext
from xpra.util.str_fn import strtobytes
from xpra.util.objects import typedict
from xpra.net.digest import get_digests, get_digest_module, gendigest, get_salt


def temp_filename(prefix="") -> str:
    return os.path.join(tempfile.gettempdir(), "file-auth-%s-test-%s" % (prefix, monotonic()))


class TempFileContext:

    def __init__(self, prefix="prefix"):
        self.prefix = prefix
        self.filename = ""
        self.file = None

    def __enter__(self):
        if WIN32:
            # NamedTemporaryFile doesn't work for reading on win32...
            self.filename = temp_filename(self.prefix)
            self.file = open(self.filename, 'w')
        else:
            self.file = tempfile.NamedTemporaryFile(mode="w", prefix=self.prefix)
            self.filename = self.file.name
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        if WIN32 and self.filename:
            os.unlink(self.filename)


class TestAuth(unittest.TestCase):

    def a(self, name: str):
        pmod = "xpra.auth"
        auth_module = __import__(pmod, globals(), locals(), [name], 0)
        mod = getattr(auth_module, name, None)
        assert mod, f"cannot load {name} from {pmod}"
        assert str(mod)
        return mod

    def _init_auth(self, mod_name: str, **kwargs):
        mod = self.a(mod_name)
        a = self.do_init_auth(mod, **kwargs)
        assert repr(a)
        return a

    def do_init_auth(self, module, **kwargs):
        try:
            c = module.Authenticator
        except AttributeError:
            raise Exception("module %s does not contain an Authenticator class!") from None
        # some auth modules require this to function:
        if "connection" not in kwargs:
            kwargs["connection"] = "fake-connection-data"
        # exec auth would fail during rpmbuild without a default command:
        if "command" not in kwargs:
            kwargs["command"] = "/bin/true"
        kwargs["username"] = kwargs.get("username", "foo")
        return c(**kwargs)

    def _test_module(self, module):
        a = self._init_auth(module)
        assert a
        assert str(a)
        assert repr(a)
        if a.requires_challenge():
            salt, digest = a.get_challenge(get_digests())
            assert salt and digest
        a = self._init_auth(module)
        assert a
        if a.requires_challenge():
            salt = digest = ""
            try:
                salt, digest = a.get_challenge(("invalid-digest",))
            except ValueError:
                pass
            else:
                raise RuntimeError(f"invalid digest should raise a ValueError, but got ({salt}, {digest})")

    def capsauth(self, a, challenge_response=None, client_salt=None) -> bool:
        caps = typedict()
        if challenge_response is not None:
            caps["challenge_response"] = challenge_response
        if client_salt is not None:
            caps["challenge_client_salt"] = client_salt
        return a.authenticate(caps)

    def test_all(self) -> None:
        test_modules = ["reject", "allow", "none", "file", "multifile", "env", "password"]
        try:
            self.a("pam")
            test_modules.append("pam")
        except Exception:
            pass
        if sys.platform.startswith("win"):
            self.a("win32")
            test_modules.append("win32")
        if POSIX:
            test_modules.append("exec")
        for module in test_modules:
            self._test_module(module)

    def test_fail(self) -> None:
        try:
            fa = self._init_auth("fail")
        except Exception:
            fa = None
        assert fa is None, "'fail_auth' did not fail!"

    def test_reject(self) -> None:
        a = self._init_auth("reject")
        assert a.requires_challenge()
        c, mac = a.get_challenge(get_digests())
        assert a.get_uid() == -1
        assert a.get_gid() == -1
        assert not a.get_password()
        assert c and mac
        assert not a.get_sessions()
        assert not a.get_passwords()
        assert a.choose_salt_digest("xor") == "xor"
        for x in (None, "bar"):
            assert not self.capsauth(a, x, c)
            assert not self.capsauth(a, x, x)

    def test_none(self) -> None:
        a = self._init_auth("none")
        assert not a.requires_challenge()
        salt, digest = a.get_challenge(get_digests())
        assert not (salt or digest)
        assert not a.get_password()
        for x in (None, "bar"):
            assert self.capsauth(a, x, "")
            assert self.capsauth(a, "", x)

    def test_allow(self) -> None:
        a = self._init_auth("allow")
        assert a.requires_challenge()
        assert a.get_challenge(get_digests())
        assert not a.get_passwords()
        for x in (None, "bar"):
            assert self.capsauth(a, x, "")
            assert self.capsauth(a, "", x)

    def _test_hmac_auth(self, mod_name: str, password: str, **kwargs) -> None:
        for test_password in (password, "somethingelse"):
            a = self._init_auth(mod_name, **kwargs)
            assert a.requires_challenge()
            assert a.get_passwords()
            salt, mac = a.get_challenge(tuple(x for x in get_digests() if x.startswith("hmac")))
            assert salt
            assert mac.startswith("hmac"), "invalid mac: %s" % mac
            client_salt = strtobytes(uuid.uuid4().hex + uuid.uuid4().hex)
            salt_digest = a.choose_salt_digest(get_digests())
            auth_salt = strtobytes(gendigest(salt_digest, client_salt, salt))
            digestmod = get_digest_module(mac)
            verify = hmac.HMAC(strtobytes(test_password), auth_salt, digestmod=digestmod).hexdigest()
            passed = self.capsauth(a, verify, client_salt)
            assert passed == (test_password == password), "expected authentication to %s with %s vs %s" % (
                ["fail", "succeed"][test_password == password], test_password, password)
            assert not self.capsauth(a, verify,
                                     client_salt), "should not be able to athenticate again with the same values"

    def test_env(self) -> None:
        for var_name in ("XPRA_PASSWORD", "SOME_OTHER_VAR_NAME"):
            password = uuid.uuid4().hex
            os.environ[var_name] = password
            try:
                kwargs = {}
                if var_name != "XPRA_PASSWORD":
                    kwargs["name"] = var_name
                self._test_hmac_auth("env", password, name=var_name)
            finally:
                del os.environ[var_name]

    def test_password(self) -> None:
        password = uuid.uuid4().hex
        self._test_hmac_auth("password", password, value=password)

    def _test_file_auth(self, mod_name: str, genauthdata: Callable, display_count: int = 0):
        # no file, no go:
        a = self._init_auth(mod_name)
        assert a.requires_challenge()
        p = a.get_passwords()
        assert not p, "got passwords from %s: %s" % (a, p)
        # challenge twice is a fail
        salt, digest = a.get_challenge(get_digests())
        assert salt and digest
        salt, digest = a.get_challenge(get_digests())
        assert not (salt or digest)
        salt, digest = a.get_challenge(get_digests())
        assert not (salt or digest)
        # muck:
        # 0 - OK
        # 1 - bad: with warning about newline
        # 2 - verify bad passwords
        # 3 - verify no password
        for muck in (0, 1, 2, 3):
            with TempFileContext(prefix=mod_name) as context:
                f = context.file
                filename = context.filename
                with f:
                    a = self._init_auth(mod_name, filename=filename)
                    password, filedata = genauthdata(a)
                    if muck != 3:
                        f.write(filedata)
                    if muck == 1:
                        f.write("\n")
                    f.flush()
                    assert a.requires_challenge()
                    server_salt, digest = a.get_challenge(get_digests())
                    assert get_digest_module(digest)
                    assert server_salt
                    assert digest in get_digests()
                    assert digest != "xor"
                    # this is what a client does,
                    # see send_challenge_reply in client_base
                    client_salt = get_salt(len(server_salt))
                    salt_digest = a.choose_salt_digest(get_digests())
                    assert salt_digest and isinstance(salt_digest, str)
                    auth_salt = gendigest(salt_digest, client_salt, server_salt)
                    assert isinstance(auth_salt,
                                      bytes), f"auth salt is {type(auth_salt)}, expected bytes for {salt_digest!r}"
                    if muck == 0:
                        verify = gendigest(digest, password, auth_salt)
                        assert isinstance(verify, bytes), f"value is {type(verify)}, expected bytes for {digest!r}"
                        assert self.capsauth(a, verify, client_salt), "%s failed" % a.authenticate
                        if display_count > 0:
                            sessions = a.get_sessions()
                            assert len(sessions) >= 3
                            displays = sessions[2]
                            assert len(displays) == display_count, "expected %i displays but got %i : %s" % (
                                display_count, len(sessions), sessions)
                        assert not self.capsauth(a, verify, client_salt), "authenticated twice!"
                        passwords = a.get_passwords()
                        assert len(passwords) == 1, f"expected just one password in file, got {len(passwords)}"
                        assert password in passwords, f"expected to find {password} in {passwords}"
                    else:
                        for verify in ("whatever", None, "bad"):
                            assert not self.capsauth(a, verify, client_salt)
        return a

    def test_file(self) -> None:

        def genfiledata(_a) -> tuple[str, str]:
            password = uuid.uuid4().hex
            return password, password

        self._test_file_auth("file", genfiledata)
        # no digest -> no challenge
        a = self._init_auth("file", filename="foo")
        assert a.requires_challenge()
        try:
            a.get_challenge(("not-a-valid-digest",))
        except ValueError:
            pass
        else:
            raise RuntimeError("invalid digest should raise a ValueError")
        a.password_filename = "./this-path-should-not-exist"
        assert not a.load_password_file()
        assert a.stat_password_filetime() == 0
        # inaccessible:
        if POSIX:
            filename = "./test-file-auth-%s-%s" % (get_hex_uuid(), os.getpid())
            with open(filename, 'wb') as f:
                os.fchmod(f.fileno(), 0o200)  #write-only
            a.password_filename = filename
            a.load_password_file()

    def test_multifile(self):
        def genfiledata(a) -> tuple[str, str]:
            password = uuid.uuid4().hex
            lines = [
                "#comment",
                "%s|%s|||" % (a.username, password),
                "incompleteline",
                "duplicateentry|pass1",
                "duplicateentry|pass2",
                "user|pass",
                "otheruser|otherpassword|1000|1000||env1=A,env2=B|compression=0",
            ]
            return password, "\n".join(lines)

        self._test_file_auth("multifile", genfiledata, 1)

        def nodata(_a) -> tuple[str, str]:
            return "abc", ""

        try:
            self._test_file_auth("multifile", nodata, 1)
        except AssertionError:
            pass
        else:
            raise Exception("authentication with no data should have failed")

    def test_sqlite(self):
        from xpra.auth.sqlite import main as sqlite_main
        filename = temp_filename("sqlite")
        password = "hello"

        def t():
            self._test_hmac_auth("sqlite", password, filename=filename)

        def vf(reason):
            try:
                t()
            except Exception:
                pass
            else:
                raise Exception("sqlite auth should have failed: %s" % reason)

        vf("the database has not been created yet")
        assert sqlite_main(["main", filename, "create"]) == 0
        vf("the user has not been added yet")
        assert sqlite_main(["main", filename, "add", "foo", password]) == 0
        t()
        assert sqlite_main(["main", filename, "remove", "foo"]) == 0
        vf("the user has been removed")
        assert sqlite_main(["main", filename, "add", "foo", "wrongpassword"]) == 0
        vf("the password should not match")

    def test_peercred(self) -> None:
        if not POSIX or OSX:
            # can't be used!
            return
        # no connection supplied:
        pc = self._init_auth("peercred")
        assert not pc.requires_challenge()
        assert not self.capsauth(pc)
        assert pc.get_uid() == -1 and pc.get_gid() == -1
        # now with a connection object:
        from xpra.util.thread import start_thread
        sockpath = "./socket-test"
        try:
            os.unlink(sockpath)
        except OSError:
            pass
        from xpra.net.bytestreams import SocketConnection
        import socket
        sock = socket.socket(socket.AF_UNIX)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(sockpath)
        sock.listen(5)
        verified = []
        to_close: list[Callable] = [sock.close]

        def wait_for_connection() -> None:
            conn, addr = sock.accept()
            s = SocketConnection(conn, sockpath, addr, sockpath, "unix")
            pc = self._init_auth("peercred", connection=s)
            assert not pc.requires_challenge()
            assert pc.get_uid() == os.getuid()
            verified.append(True)
            to_close.append(s.close)

        t = start_thread(wait_for_connection, "socket listener", daemon=True)
        # connect a client:
        client = socket.socket(socket.AF_UNIX)
        client.settimeout(5)
        client.connect(sockpath)
        to_close.append(client.close)
        # wait for it to trigger auth:
        t.join(5)
        for close in to_close:
            try:
                close()
            except OSError:
                pass
        assert verified

    def test_hosts(self) -> None:
        # cannot be tested (would require root to edit the hosts.deny file)
        pass

    def test_exec(self) -> None:
        if not POSIX:
            return

        def exec_cmd(cmd: str, success=True) -> None:
            kwargs = {
                "command": cmd,
                "timeout": 2,
            }
            a = self._init_auth("exec", **kwargs)
            assert not a.requires_challenge(), f"{a} should not require a challenge"
            expected = ["failed", "succeeded"][success]
            assert self.capsauth(a) == success, f"{a} should have {expected} using cmd={cmd}"

        exec_cmd("/bin/true", True)
        exec_cmd("/bin/false", False)

    def test_keycloak(self) -> None:
        try:
            self._init_auth("keycloak")
            import oauthlib
        except ImportError as e:
            print("Warning: keycloak auth test skipped")
            print(f" {e}")
            return

        def t(digests=None, response=None, **kwargs):
            a = self._init_auth("keycloak", **kwargs)
            assert a.requires_challenge(), "%s should require a challenge" % a
            if digests is not None:
                salt, digest = a.get_challenge(digests)
                assert salt and digest, "cannot get challenge for digests %s" % (digests,)
            if response is not None:
                assert a.check(response), "check failed for response %s" % (response,)

        def f(digests=None, response=None, **kwargs):
            try:
                t(digests, response, **kwargs)
            except (AssertionError, ValueError, oauthlib.oauth2.rfc6749.errors.OAuth2Error, TypeError):
                pass
            else:
                raise Exception("keycloak auth should have failed with arguments: %s" % (kwargs,))

        t()
        # only 'authorization_code' is supported:
        f(grant_type="foo")
        t(grant_type="authorization_code")
        # only 'keycloak' digest is supported:
        f(digests=("xor",))
        t(digests=("xor", "keycloak",))
        t(digests=("keycloak",))
        # we can't provide a valid response:
        # these are not valid json strings:
        for invalid in (True, False, 10, 1.1, [1, 2, 3], (4, 5, 6)):
            f(digests=("keycloak",), response=invalid)
        # these are valid json strings, but not valid reponses (not dicts for a start):
        for invalid in (b"\"hello\"", "\"foo\"", "\"foobar\""):
            f(digests=("keycloak",), response=invalid)
        # these are valid json strings that return a dict, but no valid authorization code:
        f(digests=("keycloak",), response="{\"foo\":\"bar\"}")
        f(digests=("keycloak",), response="{\"error\": 404, \"code\":\"authorization_code\"}")
        f(digests=("keycloak",), response="{\"code\":\"authorization_code\"}")
        # non-https URL should fail:
        f(server_url="http://localhost:8080/")
        with OSEnvContext(OAUTHLIB_INSECURE_TRANSPORT="1"):
            # and succeed with insecure override:
            t(server_url="http://localhost:8080/")


def main():
    import logging
    from xpra.log import set_default_level
    from xpra.log import enable_color
    enable_color()
    if "-v" in sys.argv:
        set_default_level(logging.DEBUG)
    else:
        set_default_level(logging.CRITICAL)
    try:
        from xpra import auth
        assert auth
    except ImportError as e:
        print("non server build, skipping auth module test: %s" % e)
        return
    unittest.main()


if __name__ == '__main__':
    main()
