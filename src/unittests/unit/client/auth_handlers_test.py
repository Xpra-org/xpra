#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.os_util import OSEnvContext


class FakeClient:
	def __init__(self):
		self.challenge_reply_passwords = []
	def send_challenge_reply(self, _packet, password):
		self.challenge_reply_passwords.append(password)

class AuthHandlersTest(unittest.TestCase):

	def _test_handler(self, success, password, handler_class, **kwargs):
		return self.do_test_handler(FakeClient(), success, password, handler_class, **kwargs)

	def do_test_handler(self, client, success, password, handler_class, **kwargs):
		h = handler_class(client, **kwargs)
		assert repr(h)
		server_salt = kwargs.pop("server-salt", "0"*32)
		digest = kwargs.pop("digest", "xor")
		salt_digest = kwargs.pop("salt-digest", "xor")
		packet = ("challenge", server_salt, "", digest, salt_digest)
		r = h.handle(packet)
		assert r==success, "expected %s(%s) to return %s but got %s (handler class=%s)" % (
			h.handle, packet, success, r, handler_class)
		if success:
			passwords = h.client.challenge_reply_passwords
			assert len(passwords)==1
			assert passwords[0]==password
			h.get_digest()
		#client_salt = ""
		#salt = gendigest(salt_digest, client_salt, server_salt)
		#challenge_response = gendigest(actual_digest, password, salt)
		return h

	def test_prompt(self):
		from xpra.client.auth.prompt_handler import Handler
		client = FakeClient()
		password = "prompt-password"
		def rec(packet, _prompt):
			client.send_challenge_reply(packet, password)
			return True
		client.do_process_challenge_prompt = rec
		self.do_test_handler(client, True, password, Handler, digest="gss:token-type")

	def test_env_handler(self):
		from xpra.client.auth.env_handler import Handler
		with OSEnvContext():
			os.environ["XPRA_PASSWORD"] = "password1"
			self._test_handler(True, "password1", Handler)
		with OSEnvContext():
			os.environ["XPRA_PASSWORD2"] = "password2"
			self._test_handler(True, "password2", Handler, name="XPRA_PASSWORD2")
		with OSEnvContext():
			name = "XPRA_TEST_VARIABLE_DOES_NOT_EXIST"
			try:
				del os.environ[name]
			except KeyError:
				pass
			self._test_handler(False, None, Handler, name=name)

	def test_file_handler(self):
		from xpra.client.auth.file_handler import Handler
		password = b"password"
		try:
			f = tempfile.NamedTemporaryFile(prefix="test-client-file-auth", delete=False)
			f.file.write(password)
			f.file.flush()
			f.close()
			self._test_handler(True, password, Handler, filename=f.name)
			#using the default password file from the client:
			client = FakeClient()
			client.password_file = [f.name]
			self.do_test_handler(client, True, password, Handler)
		finally:
			#remove file, auth should fail:
			os.unlink(f.name)
			self._test_handler(False, None, Handler, filename=f.name)

	def test_uri_handler(self):
		from xpra.client.auth.uri_handler import Handler
		password = b"password"
		client = FakeClient()
		client.password = password
		self.do_test_handler(client, True, password, Handler)


def main():
	unittest.main()


if __name__ == '__main__':
	main()
