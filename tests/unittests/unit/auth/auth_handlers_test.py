#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.util.env import OSEnvContext


# pylint: disable=import-outside-toplevel


class AuthHandlersTest(unittest.TestCase):

    def _test_handler(self, success, result, handler_class, **kwargs):
        return self.do_test_handler(success, result, handler_class, **kwargs)

    def do_test_handler(self, success, result, handler_class, **kwargs):
        h = handler_class(**kwargs)
        assert repr(h)
        server_salt = kwargs.pop("server-salt", b"0"*32)
        digest = kwargs.pop("digest", "xor")
        kwargs = {
            "challenge": server_salt,
            "digest": digest,
            "prompt": "test",
        }
        try:
            r = h.handle(**kwargs)
        except Exception:
            print(f"test error on {h.handle}({kwargs})")
            raise
        if not success:
            assert not r, f"expected {h.handle}({kwargs}) to fail but it returned {r} (handler class={handler_class})"
        else:
            assert r == result, f"expected password value {result!r} but got {r}"
            h.get_digest()
        return h

    def test_prompt(self):
        from xpra.challenge.prompt import Handler
        password = "prompt-password"
        self.do_test_handler(True, password, Handler, digest="gss:token-type",
                             challenge_prompt_function=lambda *_args: password)

    def test_env_handler(self):
        from xpra.challenge.env import Handler
        with OSEnvContext():
            os.environ["XPRA_PASSWORD"] = "password1"
            self._test_handler(True, "password1", Handler)
        with OSEnvContext():
            os.environ["XPRA_PASSWORD2"] = "password2"
            self._test_handler(True, "password2", Handler, name="XPRA_PASSWORD2")
        with OSEnvContext():
            name = "XPRA_TEST_VARIABLE_DOES_NOT_EXIST"
            os.environ.pop(name, None)
            self._test_handler(False, None, Handler, name=name)

    def test_file_handler(self):
        from xpra.challenge.file import Handler
        password = b"password"
        try:
            f = tempfile.NamedTemporaryFile(prefix="test-client-file-auth", delete=False)
            f.file.write(password)
            f.file.flush()
            f.close()
            self._test_handler(True, password, Handler, filename=f.name)
        finally:
            # remove file, auth should fail:
            os.unlink(f.name)
            self._test_handler(False, None, Handler, filename=f.name)

    def test_uri_handler(self):
        from xpra.challenge.uri import Handler
        password = "foo"
        self.do_test_handler(True, password, Handler, password=password)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
