# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from time import monotonic
from typing import Sequence, NoReturn

from xpra.common import noerr
from xpra.exit_codes import ExitCode, ExitValue
from xpra.scripts.config import InitException, InitExit

SSL_VERIFY_EXPIRED = 10
SSL_VERIFY_WRONG_HOST = 20
SSL_VERIFY_SELF_SIGNED = 18
SSL_VERIFY_UNTRUSTED_ROOT = 19
SSL_VERIFY_IP_MISMATCH = 64
SSL_VERIFY_HOSTNAME_MISMATCH = 62
SSL_VERIFY_CODES: dict[int, str] = {
    SSL_VERIFY_EXPIRED: "expired",  # also revoked!
    SSL_VERIFY_WRONG_HOST: "wrong host",
    SSL_VERIFY_SELF_SIGNED: "self-signed",
    SSL_VERIFY_UNTRUSTED_ROOT: "untrusted-root",
    SSL_VERIFY_IP_MISMATCH: "ip-mismatch",
    SSL_VERIFY_HOSTNAME_MISMATCH: "hostname-mismatch",
}


class SSLVerifyFailure(InitExit):
    def __init__(self, status, msg, verify_code, ssl_sock):
        super().__init__(status, msg)
        self.verify_code = verify_code
        self.ssl_sock = ssl_sock


KEY_FILENAME = "key.pem"
CERT_FILENAME = "cert.pem"
SSL_CERT_FILENAME = "ssl-cert.pem"
SSL_ATTRIBUTES: Sequence[str] = (
    "cert", "key", "ca-certs", "ca-data",
    "protocol",
    "client-verify-mode", "server-verify-mode", "verify-flags",
    "check-hostname", "server-hostname",
    "options", "ciphers",
)

logger = None


def get_ssl_logger():
    global logger
    if not logger:
        from xpra.log import Logger
        logger = Logger("network", "ssl")
    return logger


def _error_handler(*args) -> NoReturn:
    raise InitException(*args)


def get_remote_proxy_command_output(options, args: list[str], cmdline: list[str], subcommand="setup-ssl") -> tuple[dict, bytes]:
    if len(args) != 1:
        raise InitExit(ExitCode.FAILURE, "a single optional argument may be specified")
    arg = args[0]
    from xpra.scripts.parsing import parse_display_name
    disp = parse_display_name(_error_handler, options, arg, cmdline)
    if disp.get("type", "") != "ssh":
        raise InitExit(ExitCode.FAILURE, "argument must be an ssh URL")
    disp["display_as_args"] = []
    disp["proxy_command"] = [subcommand, ]

    from xpra.net.ssh import util
    util.LOG_EOF = False

    def ssh_fail(*_args) -> NoReturn:
        sys.exit(int(ExitCode.SSH_FAILURE))

    def ssh_log(*args) -> None:
        from xpra.log import Logger
        Logger("ssh").debug(*args)

    from xpra.net.connect import connect_to_ssh
    conn = connect_to_ssh(disp, options, debug_cb=ssh_log, ssh_fail_cb=ssh_fail)
    data = b""
    until = monotonic() + 30
    while monotonic() < until:
        bdata = conn.read(4096)
        if not bdata:
            break
        data += bdata
    noerr(conn.close)
    return disp, data


def setup_ssl(options, args: list[str], cmdline: list[str]) -> ExitValue:
    from xpra.net.tls.file import strip_cert, gen_ssl_cert, save_ssl_config_file
    if args:
        disp, data = get_remote_proxy_command_output(options, args, cmdline, "setup-ssl")
        if not data:
            raise InitExit(ExitCode.FAILURE, "no certificate data received, check the command output")
        data = strip_cert(data)
        host = disp["host"]
        save_ssl_config_file(host, port=0, filename="cert.pem", fileinfo="certificate", filedata=data)
        return ExitCode.OK
    _keyfile, certfile = gen_ssl_cert()
    from xpra.util.io import load_binary_file
    cert = load_binary_file(certfile)
    sys.stdout.write(cert.decode("latin1"))
    return 0


def show_ssl(options, args: list[str], cmdline: list[str]) -> ExitValue:
    from xpra.net.tls.file import strip_cert, find_ssl_cert
    if args:
        _disp, data = get_remote_proxy_command_output(options, args, cmdline, "show-ssl")
        if not data:
            raise InitExit(ExitCode.FAILURE, "no certificate data received, check the command output")
        cert = strip_cert(data)
    else:
        from xpra.log import Logger
        log = Logger("ssl")
        keypath = find_ssl_cert(KEY_FILENAME)
        certpath = find_ssl_cert(CERT_FILENAME)
        if not keypath or not certpath:
            log.info("no certificate found")
            return ExitCode.NO_DATA
        log.info("found an existing SSL certificate:")
        log.info(f" {keypath!r}")
        log.info(f" {certpath!r}")
        from xpra.util.io import load_binary_file
        cert = load_binary_file(certpath)
    sys.stdout.write(cert.decode("latin1"))
    return ExitCode.OK
