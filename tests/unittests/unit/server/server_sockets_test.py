#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import unittest
import tempfile
from time import monotonic
from subprocess import Popen

from xpra.util.str_fn import repr_ellipsized
from xpra.util.env import envint
from xpra.os_util import OSX, POSIX
from xpra.util.io import load_binary_file, pollwait
from xpra.exit_codes import ExitCode, ExitValue
from xpra.platform.dotxpra import DISPLAY_PREFIX
from unit.test_util import get_free_tcp_port
from unit.server_test_util import ServerTestUtil, log, estr, log_gap

CONNECT_WAIT = envint("XPRA_TEST_CONNECT_WAIT", 60)
SUBPROCESS_WAIT = envint("XPRA_TEST_SUBPROCESS_WAIT", CONNECT_WAIT * 2)

NOVERIFY = "--ssl-server-verify-mode=none"
NOHOSTNAME = "--ssl-check-hostname=no"


class GenSSLCertContext:
    __slots__ = ("tmpdir", "keyfile", "outfile", "certfile")

    def __init__(self):
        self._clear()

    def _clear(self):
        self.tmpdir = self.keyfile = self.outfile = self.certfile = ""

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp(suffix='ssl-xpra')
        self.keyfile = os.path.join(self.tmpdir, "key.pem")
        self.outfile = os.path.join(self.tmpdir, "out.pem")
        openssl_command = [
            "openssl", "req", "-new", "-newkey", "rsa:4096", "-days", "2", "-nodes", "-x509",
            "-subj", "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost",
            "-keyout", self.keyfile, "-out", self.outfile,
        ]
        proc = Popen(args=openssl_command)
        assert pollwait(proc, 20) == 0, "openssl certificate generation failed"
        # combine the two files:
        self.certfile = os.path.join(self.tmpdir, "cert.pem")
        with open(self.certfile, "wb") as cf:
            for fname in (self.keyfile, self.outfile):
                with open(fname, "rb") as f:
                    cf.write(f.read())
        cert_data = load_binary_file(self.certfile)
        log("generated cert data: %s", repr_ellipsized(cert_data))
        if not cert_data:
            # cannot run openssl? (happens from rpmbuild)
            raise RuntimeError("SSL test skipped, cannot run " + " ".join(openssl_command))
        return self

    def __exit__(self, *_args):
        for f in (self.keyfile, self.outfile, self.certfile):
            os.unlink(f)
        os.rmdir(self.tmpdir)
        self._clear()

    def __repr__(self):
        return "GenSSLCertContext"


class ServerSocketsTest(ServerTestUtil):

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        cls.default_xpra_args += [
            "--start-new-commands=no",
            "--video-encoders=none",
            "--csc-modules=none",
            "--video-decoders=none",
            "--encodings=rgb",
            "--mdns=no",
            "--webcam=no",
        ]

    def get_run_env(self):
        env = super().get_run_env()
        env["XPRA_CONNECT_TIMEOUT"] = str(CONNECT_WAIT)
        return env

    def start_server(self, *args):
        server_proc = self.run_xpra(["start", "--no-daemon"] + list(args))
        if pollwait(server_proc, 10) is not None:
            r = server_proc.poll()
            raise Exception(f"server failed to start with args={args}, returned {estr(r)}")
        return server_proc

    def _test_connect(self, server_args=(), client_args=(), password=None, uri_prefix=DISPLAY_PREFIX, exit_code=0):
        display_no = self.find_free_display_no()
        display = f":{display_no}"
        log(f"starting test server on {display}")
        server = self.start_server(display, "--printing=no", *server_args)
        # we should always be able to get the version:
        uri = uri_prefix + str(display_no)
        start = monotonic()
        while True:
            args = ["version", uri] + list(client_args or ())
            client = self.run_xpra(args)
            r = pollwait(client, CONNECT_WAIT)
            if r == 0:
                break
            if r is None:
                client.terminate()
            if monotonic() - start > SUBPROCESS_WAIT:
                if exit_code == ExitCode.CONNECTION_FAILED:
                    return
                err_msg = f"version client failed to connect using {args}, returned {estr(r)}"
                log.error(err_msg)
                log.error(f" server was started on {display=} with {server_args}")
                raise Exception(err_msg)
        # try to connect
        cmd = ["connect-test", uri] + [x.replace("$DISPLAY_NO", str(display_no)) for x in client_args]
        f = None
        if password:
            f = self._temp_file(password)
            cmd += [f"--password-file={f.name}"]
            cmd += [f"--challenge-handlers=file:filename={f.name}"]
        client = self.run_xpra(cmd)
        r = pollwait(client, SUBPROCESS_WAIT)
        if f:
            f.close()
        if r is None:
            client.terminate()
        server.terminate()
        if r != exit_code:
            log.error("Exit code mismatch")
            log.error(" expected %s (%s)", estr(exit_code), exit_code)
            log.error(" got %s (%s)", estr(r), r)
            log.error(" server args=%s", server_args)
            log.error(" client args=%s", client_args)
            self.verify_exitcode(expected=exit_code, actual=r)
        pollwait(server, 10)

    def test_default_socket(self):
        self._test_connect(["--bind=auto,auth=allow"], [], b"hello", DISPLAY_PREFIX, ExitCode.OK)

    def test_tcp_socket(self):
        port = get_free_tcp_port()
        self._test_connect([f"--bind-tcp=0.0.0.0:{port},auth=allow"], [], b"hello",
                           f"tcp://127.0.0.1:{port}/", ExitCode.OK)
        port = get_free_tcp_port()
        self._test_connect([f"--bind-tcp=0.0.0.0:{port},auth=allow"], [], b"hello",
                           f"ws://127.0.0.1:{port}/", ExitCode.OK)

    def test_ws_socket(self):
        port = get_free_tcp_port()
        self._test_connect([f"--bind-ws=0.0.0.0:{port},auth=allow"], [], b"hello",
                           f"ws://127.0.0.1:{port}/", ExitCode.OK)

    def _gen_ssl(self):
        tmpdir = tempfile.mkdtemp(suffix='ssl-xpra')
        keyfile = os.path.join(tmpdir, "key.pem")
        outfile = os.path.join(tmpdir, "out.pem")
        openssl_command = [
            "openssl", "req", "-new", "-newkey", "rsa:4096", "-days", "2", "-nodes", "-x509",
            "-subj", "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost",
            "-keyout", keyfile, "-out", outfile,
        ]
        openssl = self.run_command(openssl_command)
        assert pollwait(openssl, 20) == 0, "openssl certificate generation failed"
        # combine the two files:
        certfile = tempfile.NamedTemporaryFile(delete=False)
        os.path.join(tmpdir, "cert.pem")
        for fname in (keyfile, outfile):
            with open(fname, 'rb') as f:
                certfile.write(f.read())
        shutil.rmtree(tmpdir)
        cert_data = load_binary_file(certfile.name)
        log("generated cert data: %s", repr_ellipsized(cert_data))
        if not cert_data:
            # cannot run openssl? (happens from rpmbuild)
            raise RuntimeError("SSL test skipped, cannot run " + " ".join(openssl_command))
        return certfile

    def verify_connect(self, uri, exit_code=ExitCode.OK, *client_args):
        cmd = ["info", uri] + list(client_args)
        env = self.get_run_env()
        env["SSL_RETRY"] = "0"
        client = self.run_xpra(cmd, env=env)
        r = pollwait(client, CONNECT_WAIT)
        if client.poll() is None:
            client.terminate()
        r = client.poll()
        self.verify_exitcode(expected=exit_code, actual=r)

    def verify_exitcode(self, client="info client", expected: ExitValue = ExitCode.OK,
                        actual: ExitValue | None = ExitCode.OK):
        if actual is None:
            raise Exception(f"expected {client} to return %s but it is still running" % (estr(expected),))
        if actual != expected:
            raise RuntimeError(f"expected {client} to return %s but got %s" % (estr(expected), estr(actual)))

    def test_quic_socket(self):
        port = get_free_tcp_port()
        try:
            from xpra.net.quic import listener, client
            assert listener and client
        except ImportError as e:
            print(f"quic socket test skipped: {e}")
            return
        display_no = self.find_free_display_no()
        display = f":{display_no}"
        with GenSSLCertContext() as genssl:
            server = None
            try:
                log("starting test quic server on %s", display)
                server = self.start_server(display,
                                           f"--bind-quic=0.0.0.0:{port},auth=allow",
                                           f"--ssl-cert={genssl.certfile}",
                                           f"--ssl-key={genssl.keyfile}",
                                           )

                def tc(exit_code, *client_args):
                    self.verify_connect(f"quic://127.0.0.1:{port}/", exit_code, *client_args)

                # asyncio makes it too difficult to emit the correct exception here:
                # we should be getting ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE..
                tc(ExitCode.CONNECTION_FAILED)
                tc(ExitCode.OK, NOVERIFY, NOHOSTNAME)
            finally:
                if server:
                    server.terminate()

    def test_ssl(self):
        server = None
        display_no = self.find_free_display_no()
        display = f":{display_no}"
        tcp_port = get_free_tcp_port()
        ws_port = get_free_tcp_port()
        wss_port = get_free_tcp_port()
        ssl_port = get_free_tcp_port()
        proto_ports = {
            "tcp": tcp_port,
            "ws": ws_port,
            "wss": wss_port,
            "ssl": ssl_port,
        }
        ports_proto = dict((v, k) for k, v in proto_ports.items())
        with GenSSLCertContext() as genssl:
            try:
                server_args = [
                    "--ssl=on",
                    "--html=on",
                    f"--ssl-cert={genssl.certfile}",
                    f"--ssl-key={genssl.keyfile}",
                ]
                for bind_mode, bind_port in proto_ports.items():
                    server_args.append(f"--bind-{bind_mode}=0.0.0.0:{bind_port},auth=allow")
                log("starting test ssl server on %s", display)
                server = self.start_server(display, *server_args)

                # test it with openssl client:
                for mode, verify_port in proto_ports.items():
                    openssl_verify_command = (
                        "openssl", "s_client", "-connect",
                        "127.0.0.1:%i" % verify_port, "-CAfile", genssl.certfile,
                    )
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    openssl = self.run_command(openssl_verify_command, stdin=devnull, shell=True)
                    r = pollwait(openssl, 10)
                    if r != 0:
                        raise RuntimeError(f"openssl certificate returned {r} for {mode} port {verify_port}")

                errors: list[str] = []

                def tc(mode: str, port: int):
                    uri = f"{mode}://foo:bar@127.0.0.1:{port}/"
                    stype = ports_proto.get(port, "").rjust(5)
                    try:
                        self.verify_connect(uri, ExitCode.OK, NOVERIFY, NOHOSTNAME)
                    except RuntimeError as e:
                        err = f"failed to connect to {stype} port using mode {mode} with uri {uri!r} and {NOVERIFY!r} {NOHOSTNAME!r}: {e}"
                        log.error(f"Error: {err}")
                        errors.append(err)
                    # without `NOHOSTNAME`, connection should fail with a SSL failure:
                    try:
                        self.verify_connect(uri, ExitCode.SSL_FAILURE, NOVERIFY)
                    except RuntimeError as e:
                        err = f"connect to {stype} port using uri {uri} with {NOVERIFY!r}: {e}"
                        log.error(f"Error: {err}")
                        errors.append(err)
                    # without `NOVERIFY`:
                    try:
                        self.verify_connect(uri, ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE, NOHOSTNAME)
                    except RuntimeError as e:
                        err = f"connect to {stype} port using uri {uri} with {NOHOSTNAME!r}: {e}"
                        log.error(f"Error: {err}")
                        errors.append(err)
                    # without any ssl options:
                    try:
                        self.verify_connect(uri, ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE)
                    except RuntimeError as e:
                        err = f"connect to {stype} port using uri {uri}: {e}"
                        log.error(f"Error: {err}")
                        errors.append(err)

                # connect to ssl socket:
                tc("ssl", ssl_port)
                # tcp socket should upgrade to ssl:
                tc("ssl", tcp_port)
                # tcp socket should upgrade to ws and ssl:
                tc("wss", tcp_port)
                # ws socket should upgrade to ssl:
                tc("wss", ws_port)
                if errors:
                    log.error(f"{len(errors)} ssl test errors with server args: {server_args}")
                    msg = "\n* ".join(errors)
                    raise RuntimeError(f"{len(errors)} errors testing ssl sockets:\n* {msg}")
            finally:
                if server:
                    server.terminate()

    def test_bind_tmpdir(self):
        # remove socket dirs from default arguments temporarily:
        saved_args = ServerSocketsTest.default_xpra_args
        tmpsocketdir1 = tempfile.mkdtemp(suffix='xpra')
        tmpsocketdir2 = tempfile.mkdtemp(suffix='xpra')
        tmpsessionsdir = tempfile.mkdtemp(suffix='xpra')
        # hide sessions dir and use a single socket dir location:
        ServerSocketsTest.default_xpra_args = list(filter(lambda x: not x.startswith("--socket-dir"), saved_args))
        server_args = (
            "--socket-dir=%s" % tmpsocketdir1,
            "--socket-dirs=%s" % tmpsocketdir2,
            "--sessions-dir=%s" % tmpsessionsdir,
            "--bind=noabstract",
        )
        log_gap()

        def t(client_args=(), prefix=DISPLAY_PREFIX, exit_code=ExitCode.OK):
            self._test_connect(server_args, client_args, None, prefix, exit_code)

        try:
            # it should not be found by default
            # since we only use hidden temporary locations
            # for both sessions-dir and socket-dir(s):
            t(exit_code=ExitCode.CONNECTION_FAILED)
            # specifying the socket-dir(s) should work:
            for d in (tmpsocketdir1, tmpsocketdir2):
                t(("--socket-dir=%s" % d,))
                t(("--socket-dirs=%s" % d,))
        finally:
            ServerSocketsTest.default_xpra_args = saved_args
            for d in (tmpsocketdir1, tmpsocketdir2, tmpsessionsdir):
                shutil.rmtree(d)


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
