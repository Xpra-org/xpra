#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=line-too-long

import os
import sys
import unittest
import tempfile
import uuid
import hmac
from xpra.os_util import (
    strtobytes, bytestostr,
    monotonic_time,
    WIN32, OSX, POSIX,
    )
from xpra.net.digest import get_digests, get_digest_module, gendigest


def temp_filename(prefix=""):
    return os.path.join(os.environ.get("TEMP", "/tmp"), "file-auth-%s-test-%s" % (prefix, monotonic_time()))


class TempFileContext(object):

    def __init__(self, prefix="prefix"):
        self.prefix = prefix

    def __enter__(self):
        if WIN32:
            #NamedTemporaryFile doesn't work for reading on win32...
            self.filename = temp_filename(self.prefix)
            self.file = open(self.filename, 'wb')
        else:
            self.file = tempfile.NamedTemporaryFile(prefix=self.prefix)
            self.filename = self.file.name
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        if WIN32:
            os.unlink(self.filename)


class FakeOpts(object):
    def __init__(self, d):
        self._d = d or {}
    def __getattr__(self, name):
        return self._d.get(name)

class TestAuth(unittest.TestCase):

    def a(self, name):
        pmod = "xpra.server.auth"
        auth_module = __import__(pmod, globals(), locals(), ["%s_auth" % name], 0)
        mod = getattr(auth_module, "%s_auth" % name, None)
        assert mod, "cannot load '%s_auth' from %s" % (name, pmod)
        return mod

    def _init_auth(self, mod_name, options=None, username="foo", **kwargs):
        mod = self.a(mod_name)
        return self.do_init_auth(mod, options, username, **kwargs)

    def do_init_auth(self, module, options=None, username="foo", **kwargs):
        opts = FakeOpts(options)
        module.init(opts)
        try:
            c = module.Authenticator
        except AttributeError:
            raise Exception("module %s does not contain an Authenticator class!")
        #some auth modules require this to function:
        if "connection" not in kwargs:
            kwargs["connection"] = "fake-connection-data"
        #exec auth would fail during rpmbuild without a default command:
        if "command" not in kwargs:
            kwargs["command"] = "/usr/bin/true"
        return c(username, **kwargs)

    def _test_module(self, module):
        a = self._init_auth(module)
        assert a
        if a.requires_challenge():
            challenge = a.get_challenge(get_digests())
            assert challenge
        a = self._init_auth(module)
        assert a
        if a.requires_challenge():
            try:
                challenge = a.get_challenge(["invalid-digest"])
            except Exception:
                pass
            else:
                assert challenge is None


    def test_all(self):
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

    def test_fail(self):
        try:
            fa = self._init_auth("fail")
        except Exception:
            fa = None
        assert fa is None, "'fail_auth' did not fail!"

    def test_reject(self):
        a = self._init_auth("reject")
        assert a.requires_challenge()
        c, mac = a.get_challenge(get_digests())
        assert c and mac
        assert not a.get_sessions()
        assert not a.get_passwords()
        for x in (None, "bar"):
            assert not a.authenticate(x, c)
            assert not a.authenticate(x, x)

    def test_none(self):
        a = self._init_auth("none")
        assert not a.requires_challenge()
        assert a.get_challenge(get_digests()) is None
        assert not a.get_password()
        for x in (None, "bar"):
            assert a.authenticate(x, "")
            assert a.authenticate("", x)

    def test_allow(self):
        a = self._init_auth("allow")
        assert a.requires_challenge()
        assert a.get_challenge(get_digests())
        assert not a.get_passwords()
        for x in (None, "bar"):
            assert a.authenticate(x, "")
            assert a.authenticate("", x)

    def _test_hmac_auth(self, mod_name, password, **kwargs):
        for test_password in (password, "somethingelse"):
            a = self._init_auth(mod_name, **kwargs)
            assert a.requires_challenge()
            assert a.get_passwords()
            salt, mac = a.get_challenge([x for x in get_digests() if x.startswith("hmac")])
            assert salt
            assert mac.startswith("hmac"), "invalid mac: %s" % mac
            client_salt = strtobytes(uuid.uuid4().hex+uuid.uuid4().hex)
            salt_digest = a.choose_salt_digest(get_digests())
            auth_salt = strtobytes(gendigest(salt_digest, client_salt, salt))
            digestmod = get_digest_module(mac)
            verify = hmac.HMAC(strtobytes(test_password), auth_salt, digestmod=digestmod).hexdigest()
            passed = a.authenticate(verify, client_salt)
            assert passed == (test_password==password), "expected authentication to %s with %s vs %s" % (["fail", "succeed"][test_password==password], test_password, password)
            assert not a.authenticate(verify, client_salt), "should not be able to athenticate again with the same values"

    def test_env(self):
        for var_name in ("XPRA_PASSWORD", "SOME_OTHER_VAR_NAME"):
            password = strtobytes(uuid.uuid4().hex)
            os.environ[var_name] = bytestostr(password)
            try:
                kwargs = {}
                if var_name!="XPRA_PASSWORD":
                    kwargs["name"] = var_name
                self._test_hmac_auth("env", password, name=var_name)
            finally:
                del os.environ[var_name]

    def test_password(self):
        password = strtobytes(uuid.uuid4().hex)
        self._test_hmac_auth("password", password, value=password)


    def _test_file_auth(self, mod_name, genauthdata):
        #no file, no go:
        a = self._init_auth(mod_name)
        assert a.requires_challenge()
        p = a.get_passwords()
        assert not p, "got passwords from %s: %s" % (a, p)
        #challenge twice is a fail
        assert a.get_challenge(get_digests())
        assert not a.get_challenge(get_digests())
        assert not a.get_challenge(get_digests())
        for muck in (0, 1):
            with TempFileContext(prefix=mod_name) as context:
                f = context.file
                filename = context.filename
                with f:
                    a = self._init_auth(mod_name, {"password_file" : [filename]})
                    password, filedata = genauthdata(a)
                    #print("saving password file data='%s' to '%s'" % (filedata, filename))
                    f.write(strtobytes(filedata))
                    f.flush()
                    assert a.requires_challenge()
                    salt, mac = a.get_challenge(get_digests())
                    assert salt
                    assert mac in get_digests()
                    assert mac!="xor"
                    password = strtobytes(password)
                    client_salt = strtobytes(uuid.uuid4().hex+uuid.uuid4().hex)[:len(salt)]
                    salt_digest = a.choose_salt_digest(get_digests())
                    assert salt_digest
                    auth_salt = strtobytes(gendigest(salt_digest, client_salt, salt))
                    if muck==0:
                        digestmod = get_digest_module(mac)
                        verify = hmac.HMAC(password, auth_salt, digestmod=digestmod).hexdigest()
                        assert a.authenticate(verify, client_salt), "%s failed" % a.authenticate
                        assert not a.authenticate(verify, client_salt), "authenticated twice!"
                        passwords = a.get_passwords()
                        assert len(passwords)==1, "expected just one password in file, got %i" % len(passwords)
                        assert password in passwords
                    elif muck==1:
                        for verify in ("whatever", None, "bad"):
                            assert not a.authenticate(verify, client_salt)

    def test_file(self):
        def genfiledata(_a):
            password = uuid.uuid4().hex
            return password, password
        self._test_file_auth("file", genfiledata)

    def test_multifile(self):
        def genfiledata(a):
            password = uuid.uuid4().hex
            return password, "%s|%s|||" % (a.username, password)
        self._test_file_auth("multifile", genfiledata)

    def test_sqlite(self):
        from xpra.server.auth.sqlite_auth import main as sqlite_main
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
        assert sqlite_main(["main", filename, "create"])==0
        vf("the user has not been added yet")
        assert sqlite_main(["main", filename, "add", "foo", password])==0
        t()
        assert sqlite_main(["main", filename, "remove", "foo"])==0
        vf("the user has been removed")
        assert sqlite_main(["main", filename, "add", "foo", "wrongpassword"])==0
        vf("the password should not match")

    def test_peercred(self):
        if not POSIX or OSX:
            #can't be used!
            return
        #no connection supplied:
        pc = self._init_auth("peercred", {})
        assert not pc.requires_challenge()
        assert not pc.authenticate("", "")
        assert pc.get_uid()==-1 and pc.get_gid()==-1
        #now with a connection object:
        from xpra.make_thread import start_thread
        sockpath = "./socket-test"
        try:
            os.unlink(sockpath)
        except (OSError, IOError):
            pass
        from xpra.net.bytestreams import SocketConnection
        import socket
        sock = socket.socket(socket.AF_UNIX)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(sockpath)
        sock.listen(5)
        verified = []
        to_close = [sock]
        def wait_for_connection():
            conn, addr = sock.accept()
            s = SocketConnection(conn, sockpath, addr, sockpath, "unix")
            pc = self._init_auth("peercred", options={}, username="foo", connection=s)
            assert not pc.requires_challenge()
            assert pc.get_uid()==os.getuid()
            verified.append(True)
            to_close.append(s)
        t = start_thread(wait_for_connection, "socket listener", daemon=True)
        #connect a client:
        client = socket.socket(socket.AF_UNIX)
        client.settimeout(5)
        client.connect(sockpath)
        to_close.append(client)
        #wait for it to trigger auth:
        t.join(5)
        for x in to_close:
            try:
                x.close()
            except (OSError, IOError):
                pass
        assert verified

    def test_hosts(self):
        #cannot be tested (would require root to edit the hosts.deny file)
        pass

    def test_exec(self):
        if not POSIX:
            return
        def exec_cmd(cmd, success=True):
            kwargs = {
                "command"         : cmd,
                "timeout"        : 2,
                }
            a = self._init_auth("exec", **kwargs)
            assert not a.requires_challenge(), "%s should not require a challenge" % a
            assert a.authenticate()==success, "%s should have %s using cmd=%s" % (a, ["failed", "succeeded"][success], cmd)
        exec_cmd("/usr/bin/true", True)
        exec_cmd("/usr/bin/false", False)


def main():
    import logging
    from xpra.log import set_default_level
    if "-v" in sys.argv:
        set_default_level(logging.DEBUG)
    else:
        set_default_level(logging.CRITICAL)
    try:
        from xpra.server import auth
        assert auth
    except ImportError as e:
        print("non server build, skipping auth module test: %s" % e)
        return
    unittest.main()

if __name__ == '__main__':
    main()
