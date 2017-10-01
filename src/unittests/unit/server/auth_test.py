#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
import tempfile
import uuid
import hmac
import hashlib
from xpra.util import xor
from xpra.os_util import strtobytes, bytestostr
from xpra.net.crypto import get_digest_module, gendigest

try:
	from xpra.server.auth import fail_auth, reject_auth, allow_auth, none_auth, file_auth, multifile_auth, env_auth, password_auth
except:
	pass

class FakeOpts(object):
	def __init__(self, d={}):
		self._d = d
	def __getattr__(self, name):
		return self._d.get(name)

class TestAuth(unittest.TestCase):

	def _init_auth(self, module, options={}, username="foo", **kwargs):
		opts = FakeOpts(options)
		module.init(opts)
		log = getattr(module, "log", None)
		if log:
			import logging
			log.logger.setLevel(logging.CRITICAL)
		try:
			c = module.Authenticator
		except Exception as e:
			raise Exception("module %s does not contain an Authenticator class!")
		try:
			return c(username, **kwargs)
		except Exception as e:
			raise Exception("failed to instantiate %s: %s" % (c, e))

	def _test_module(self, module):
		a = self._init_auth(module)
		assert a
		assert a is not None
		if a.requires_challenge():
			challenge = a.get_challenge()
			assert challenge

	def test_all(self):
		test_modules = [
						reject_auth,
						allow_auth,
						none_auth,
						file_auth,
						multifile_auth,
						env_auth,
						password_auth,
						]
		try:
			from xpra.server.auth import pam_auth
			test_modules.append(pam_auth)
		except Exception:
			pass
		if sys.platform.startswith("win"):
			from xpra.server.auth import win32_auth
			test_modules.append(win32_auth)
		for module in test_modules:
			self._test_module(module)

	def test_fail(self):
		try:
			fa = fail_auth()
		except:
			fa = None
		assert fa is None, "%s did not fail!" % fail_auth

	def test_reject(self):
		a = self._init_auth(reject_auth)
		assert a.requires_challenge()
		c, mac = a.get_challenge()
		assert c and mac
		assert not a.get_sessions()
		assert not a.get_password()
		for x in (None, "bar"):
			assert not a.authenticate(x, c)
			assert not a.authenticate(x, x)

	def test_none(self):
		a = self._init_auth(none_auth)
		assert not a.requires_challenge()
		assert a.get_challenge() is None
		assert not a.get_password()
		for x in (None, "bar"):
			assert a.authenticate(x, "")
			assert a.authenticate("", x)

	def test_allow(self):
		a = self._init_auth(allow_auth)
		assert a.requires_challenge()
		assert a.get_challenge()
		assert not a.get_password()
		for x in (None, "bar"):
			assert a.authenticate(x, "")
			assert a.authenticate("", x)

	def _test_hmac_auth(self, auth_class, password, **kwargs):
		for x in (password, "somethingelse"):
			a = self._init_auth(auth_class, **kwargs)
			assert a.requires_challenge()
			assert a.get_password()
			salt, mac = a.get_challenge()
			assert salt
			assert mac=="hmac", "invalid mac: %s" % mac
                        client_salt = strtobytes(uuid.uuid4().hex+uuid.uuid4().hex)[:len(salt)]
			salt_digest = a.choose_salt_digest(get_digests())
			assert salt_digest
			auth_salt = strtobytes(gendigest(salt_digest, client_salt, salt))
			verify = hmac.HMAC(strtobytes(x), auth_salt, digestmod=hashlib.md5).hexdigest()
			passed = a.authenticate(verify, client_salt)
			assert passed == (x==password), "expected authentication to %s with %s vs %s" % (["fail", "succeed"][x==password], x, password)
			assert not a.authenticate(verify, client_salt)

	def test_env(self):
		for var_name in ("XPRA_PASSWORD", "SOME_OTHER_VAR_NAME"):
			password = strtobytes(uuid.uuid4().hex)
			os.environ[var_name] = bytestostr(password)
			try:
				kwargs = {}
				if var_name!="XPRA_PASSWORD":
					kwargs["name"] = var_name
				self._test_hmac_auth(env_auth, password, name=var_name)
			finally:
				del os.environ[var_name]

	def test_password(self):
		password = strtobytes(uuid.uuid4().hex)
		self._test_hmac_auth(password_auth, password, value=password)


	def _test_file_auth(self, name, module, genauthdata):
		#no file, no go:
		a = self._init_auth(module)
		assert a.requires_challenge()
		p = a.get_password()
		assert not p, "got a password from %s: %s" % (a, p)
		#challenge twice is a fail
		assert a.get_challenge()
		assert not a.get_challenge()
		assert not a.get_challenge()
		for muck in (0, 1):
			f = tempfile.NamedTemporaryFile(prefix=name)
			filename = f.name
			with f:
				a = self._init_auth(module, {"password_file" : filename})
				password, filedata = genauthdata(a)
				#print("saving password file data='%s' to '%s'" % (filedata, filename))
				f.write(strtobytes(filedata))
				f.flush()
				assert a.requires_challenge()
				salt, mac = a.get_challenge()
				assert salt
				assert mac=="hmac"
				password = strtobytes(password)
				client_salt = strtobytes(uuid.uuid4().hex+uuid.uuid4().hex)
				auth_salt = strtobytes(xor(salt, client_salt))
				if muck==0:
					verify = hmac.HMAC(password, auth_salt, digestmod=hashlib.md5).hexdigest()
					assert a.authenticate(verify, client_salt)
					assert not a.authenticate(verify, client_salt)
					assert a.get_password()==password
				elif muck==1:
					for verify in ("whatever", None, "bad"):
						assert not a.authenticate(verify, client_salt)

	def test_file(self):
		def genfiledata(a):
			password = uuid.uuid4().hex
			return password, password
		self._test_file_auth("file", file_auth, genfiledata)

	def test_multifile(self):
		def genfiledata(a):
			password = uuid.uuid4().hex
			return password, "%s|%s|||" % (a.username, password)
		self._test_file_auth("multifile", multifile_auth, genfiledata)


def main():
	try:
		from xpra.server import auth
		assert auth
	except ImportError as e:
		print("non server build, skipping auth module test: %s" % e)
		return
	unittest.main()

if __name__ == '__main__':
	main()
