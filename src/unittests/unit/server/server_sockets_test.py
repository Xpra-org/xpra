#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import unittest
import tempfile

from xpra.util import repr_ellipsized
from xpra.os_util import load_binary_file, pollwait, OSX, POSIX
from xpra.exit_codes import EXIT_OK, EXIT_CONNECTION_LOST, EXIT_CONNECTION_FAILED, EXIT_SSL_FAILURE, EXIT_STR, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE
from xpra.net.net_util import get_free_tcp_port
from unit.server_test_util import ServerTestUtil, log


def estr(r):
	s = EXIT_STR.get(r)
	if s:
		return "%s : %s" % (r, s)
	return str(r)


class ServerSocketsTest(ServerTestUtil):

	def start_server(self, *args):
		server_proc = self.run_xpra(["start", "--no-daemon"]+list(args))
		if pollwait(server_proc, 10) is not None:
			r = server_proc.poll()
			raise Exception("server failed to start with args=%s, returned %s" % (args, estr(r)))
		return server_proc

	def _test_connect(self, server_args=(), auth="none", client_args=(), password=None, uri_prefix=":", exit_code=0):
		display_no = self.find_free_display_no()
		display = ":%s" % display_no
		log("starting test server on %s", display)
		server = self.start_server(display, "--auth=%s" % auth, "--printing=no", *server_args)
		#we should always be able to get the version:
		uri = uri_prefix + str(display_no)
		client = self.run_xpra(["version", uri] + server_args)
		if pollwait(client, 5)!=0:
			r = client.poll()
			if client.poll() is None:
				client.terminate()
			raise Exception("version client failed to connect, returned %s" % estr(r))
		#try to connect
		cmd = ["connect-test", uri] + client_args
		f = None
		if password:
			f = self._temp_file(password)
			cmd += ["--password-file=%s" % f.name]
			cmd += ["--challenge-handlers=file:filename=%s" % f.name]
		client = self.run_xpra(cmd)
		r = pollwait(client, 10)
		if f:
			f.close()
		if client.poll() is None:
			client.terminate()
		server.terminate()
		if r!=exit_code:
			raise Exception("expected info client to return %s but got %s" % (estr(exit_code), estr(r)))
		pollwait(server, 10)

	def test_default_socket(self):
		self._test_connect([], "allow", [], b"hello", ":", EXIT_OK)

	def test_tcp_socket(self):
		port = get_free_tcp_port()
		self._test_connect(["--bind-tcp=0.0.0.0:%i" % port], "allow", [], b"hello", "tcp://127.0.0.1:%i/" % port, EXIT_OK)
		port = get_free_tcp_port()
		self._test_connect(["--bind-tcp=0.0.0.0:%i" % port], "allow", [], b"hello", "ws://127.0.0.1:%i/" % port, EXIT_OK)

	def test_ws_socket(self):
		port = get_free_tcp_port()
		self._test_connect(["--bind-ws=0.0.0.0:%i" % port], "allow", [], b"hello", "ws://127.0.0.1:%i/" % port, EXIT_OK)


	def test_ssl(self):
		server = None
		display_no = self.find_free_display_no()
		display = ":%s" % display_no
		tcp_port = get_free_tcp_port()
		ws_port = get_free_tcp_port()
		wss_port = get_free_tcp_port()
		ssl_port = get_free_tcp_port()
		try:
			tmpdir = tempfile.mkdtemp(suffix='ssl-xpra')
			keyfile = os.path.join(tmpdir, "key.pem")
			outfile = os.path.join(tmpdir, "out.pem")
			openssl_command = [
				"openssl", "req", "-new", "-newkey", "rsa:4096", "-days", "2", "-nodes", "-x509",
				"-subj", "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost",
				"-keyout", keyfile, "-out", outfile,
				]
			openssl = self.run_command(openssl_command)
			assert pollwait(openssl, 20)==0, "openssl certificate generation failed"
			#combine the two files:
			certfile = os.path.join(tmpdir, "cert.pem")
			with open(certfile, 'wb') as cert:
				for fname in (keyfile, outfile):
					with open(fname, 'rb') as f:
						cert.write(f.read())
			cert_data = load_binary_file(certfile)
			log("generated cert data: %s", repr_ellipsized(cert_data))
			if not cert_data:
				#cannot run openssl? (happens from rpmbuild)
				log.warn("SSL test skipped, cannot run '%s'", b" ".join(openssl_command))
				return
			server_args = [
				"--bind-tcp=0.0.0.0:%i" % tcp_port,
				"--bind-ws=0.0.0.0:%i" % ws_port,
				"--bind-wss=0.0.0.0:%i" % wss_port,
				"--bind-ssl=0.0.0.0:%i" % ssl_port,
				"--ssl=on",
				"--html=on",
				"--ssl-cert=%s" % certfile,
				]

			log("starting test ssl server on %s", display)
			server = self.start_server(display, *server_args)

			#test it with openssl client:
			for port in (tcp_port, ssl_port):
				openssl_verify_command = ("openssl", "s_client", "-connect", "127.0.0.1:%i" % port, "-CAfile", certfile)
				devnull = os.open(os.devnull, os.O_WRONLY)
				openssl = self.run_command(openssl_verify_command, stdin=devnull, shell=True)
				r = pollwait(openssl, 10)
				assert r==0, "openssl certificate verification failed, returned %s" % r

			def test_connect(uri, exit_code, *client_args):
				cmd = ["info", uri] + list(client_args)
				client = self.run_xpra(cmd)
				r = pollwait(client, 5)
				if client.poll() is None:
					client.terminate()
				assert r==exit_code, "expected info client to return %s but got %s" % (exit_code, client.poll())
			noverify = "--ssl-server-verify-mode=none"
			#connect to ssl socket:
			test_connect("ssl://127.0.0.1:%i/" % ssl_port, EXIT_OK, noverify)
			#tcp socket should upgrade to ssl:
			test_connect("ssl://127.0.0.1:%i/" % tcp_port, EXIT_OK, noverify)
			#tcp socket should upgrade to ws and ssl:
			test_connect("wss://127.0.0.1:%i/" % tcp_port, EXIT_OK, noverify)
			#ws socket should upgrade to ssl:
			test_connect("wss://127.0.0.1:%i/" % ws_port, EXIT_OK, noverify)

			#self signed cert should fail without noverify:
			test_connect("ssl://127.0.0.1:%i/" % ssl_port, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE)
			test_connect("ssl://127.0.0.1:%i/" % tcp_port, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE)
			test_connect("wss://127.0.0.1:%i/" % ws_port, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE)
			test_connect("wss://127.0.0.1:%i/" % wss_port, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE)

		finally:
			shutil.rmtree(tmpdir)
			if server:
				server.terminate()

	def test_bind_tmpdir(self):
		#remove socket dirs from default arguments temporarily:
		saved_default_xpra_args = ServerSocketsTest.default_xpra_args
		tmpdir = os.environ.get("TMPDIR", "/tmp")
		ServerSocketsTest.default_xpra_args = [
			x for x in saved_default_xpra_args if not x.startswith("--socket-dir")
			] + ["--socket-dirs=%s" % tmpdir]
		for _ in range(10):
			log("")
		try:
			tmpdir = tempfile.mkdtemp(suffix='xpra')
			#run with this extra socket-dir:
			args = ["--socket-dir=%s" % tmpdir]
			#tell the client about it, or don't - both cases should work:
			#(it will also use the default socket dirs)
			self._test_connect(args, "none", args, None, ":", EXIT_OK)
			self._test_connect(args, "none", [], None, ":", EXIT_OK)
			#now run with ONLY this socket dir:
			ServerSocketsTest.default_xpra_args = [x for x in saved_default_xpra_args if not x.startswith("--socket-dir")]
			args = ["--socket-dirs=%s" % tmpdir]
			#tell the client:
			self._test_connect(args, "none", args, None, ":", EXIT_OK)
			#if the client doesn't know about the socket location, it should fail:
			self._test_connect(args, "none", [], None, ":", EXIT_CONNECTION_LOST)
			#use the exact path to the socket:
			from xpra.platform.dotxpra_common import PREFIX
			self._test_connect(args, "none", [], None, "socket:"+os.path.join(tmpdir, PREFIX))
		finally:
			ServerSocketsTest.default_xpra_args = saved_default_xpra_args
			shutil.rmtree(tmpdir)

	def get_run_env(self):
		env = ServerTestUtil.get_run_env(self)
		#we want commands to timeout quickly
		env["XPRA_CONNECT_TIMEOUT"] = "5"
		return env


def main():
	if POSIX and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
