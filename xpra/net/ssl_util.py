# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from typing import Any
from collections.abc import Sequence

from xpra.exit_codes import ExitCode
from xpra.os_util import WIN32, POSIX, OSX, is_admin
from xpra.util.io import load_binary_file, umask_context
from xpra.scripts.config import InitExit, InitException, TRUE_OPTIONS
from xpra.util.env import osexpand, envbool
from xpra.util.parsing import parse_encoded_bin_data
from xpra.util.str_fn import print_nested_dict, csv, Ellipsizer, std

SSL_RETRY = envbool("XPRA_SSL_RETRY", True)

SSL_ATTRIBUTES: Sequence[str] = (
    "cert", "key", "ca-certs", "ca-data",
    "protocol",
    "client-verify-mode", "server-verify-mode", "verify-flags",
    "check-hostname", "server-hostname",
    "options", "ciphers",
)

KEY_SIZE = 4096
KEY_DAYS = 3650
KEY_SUBJ = "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost"

KEY_FILENAME = "key.pem"
CERT_FILENAME = "cert.pem"
SSL_CERT_FILENAME = "ssl-cert.pem"

logger = None


def get_ssl_logger():
    global logger
    if not logger:
        from xpra.log import Logger
        logger = Logger("network", "ssl")
    return logger


def get_ssl_attributes(opts, server_side: bool = True, overrides: dict | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {
        "server-side": server_side,
    }
    for attr in SSL_ATTRIBUTES:
        v = (overrides or {}).get(attr)
        if v is None and opts:
            fn = attr.replace("-", "_")
            ssl_attr = f"ssl_{fn}"  # ie: "ssl_ca_certs"
            v = getattr(opts, ssl_attr)
        args[attr] = v
    return args


def find_ssl_cert(filename: str = SSL_CERT_FILENAME) -> str:
    ssllog = get_ssl_logger()
    # try to locate the cert file from known locations
    from xpra.platform.paths import get_ssl_cert_dirs  # pylint: disable=import-outside-toplevel
    dirs = get_ssl_cert_dirs()
    ssllog(f"find_ssl_cert({filename}) get_ssl_cert_dirs()={dirs}")
    for d in dirs:
        p = osexpand(d)
        if not os.path.exists(p):
            ssllog(f"ssl cert dir {p!r} does not exist")
            continue
        f = os.path.join(p, filename)
        if not os.path.exists(f):
            ssllog(f"ssl cert {f!r} does not exist")
            continue
        if not os.path.isfile(f):
            ssllog.warn(f"Warning: {f!r} is not a file")
            continue
        if not os.access(f, os.R_OK):
            ssllog.info(f"SSL certificate file {f!r} is not accessible")
            continue
        ssllog(f"found ssl cert {f!r}")
        return os.path.abspath(f)
    return ""


def ssl_wrap_socket(sock, **kwargs):
    context, wrap_kwargs = get_ssl_wrap_socket_context(**kwargs)
    ssllog = get_ssl_logger()
    ssllog("ssl_wrap_socket(%s, %s) context=%s, wrap_kwargs=%s", sock, kwargs, context, wrap_kwargs)
    return do_wrap_socket(sock, context, **wrap_kwargs)


def log_ssl_info(ssl_sock) -> None:
    ssllog = get_ssl_logger()
    ssllog("server_hostname=%s", ssl_sock.server_hostname)
    cipher = ssl_sock.cipher()
    if cipher:
        ssllog.info(" %s, %s bits", cipher[0], cipher[2])
    try:
        cert = ssl_sock.getpeercert()
    except ValueError:
        pass
    else:
        if cert:
            ssllog("certificate:")
            print_nested_dict(ssl_sock.getpeercert(), prefix=" ", print_fn=ssllog)


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


def ssl_handshake(ssl_sock) -> None:
    ssllog = get_ssl_logger()
    try:
        ssl_sock.do_handshake(True)
        ssllog.info("SSL handshake complete, %s", ssl_sock.version())
        log_ssl_info(ssl_sock)
    except Exception as e:
        ssllog("do_handshake", exc_info=True)
        log_ssl_info(ssl_sock)
        import ssl
        ssleof_error = getattr(ssl, "SSLEOFError", None)
        if ssleof_error and isinstance(e, ssleof_error):
            return
        status = ExitCode.SSL_FAILURE
        ssl_cert_verification_error = getattr(ssl, "SSLCertVerificationError", None)
        if ssl_cert_verification_error and isinstance(e, ssl_cert_verification_error):
            verify_code = getattr(e, "verify_code", 0)
            ssllog("verify_code=%s", SSL_VERIFY_CODES.get(verify_code, verify_code))
            try:
                msg = getattr(e, "verify_message") or (e.args[1].split(":", 2)[2])
            except (ValueError, IndexError):
                msg = str(e)
            status = ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE
            ssllog("host failed SSL verification: %s", msg)
            raise SSLVerifyFailure(status, msg, verify_code, ssl_sock) from None
        raise InitExit(status, f"SSL handshake failed: {e}") from None


def get_ssl_verify_mode(verify_mode_str: str):
    # parse verify-mode:
    import ssl
    ssl_cert_reqs = getattr(ssl, "CERT_" + verify_mode_str.upper(), None)
    if ssl_cert_reqs is None:
        values = [k[len("CERT_"):].lower() for k in dir(ssl) if k.startswith("CERT_")]
        raise InitException(f"invalid ssl-server-verify-mode {verify_mode_str!r}, must be one of: " + csv(values))
    return ssl_cert_reqs


def get_ssl_wrap_socket_context(cert="", key="", key_password="", ca_certs="", ca_data="",
                                protocol: str = "TLS",
                                client_verify_mode: str = "optional", server_verify_mode: str = "required",
                                verify_flags: str = "X509_STRICT",
                                check_hostname: bool = False, server_hostname="",
                                options: str = "ALL,NO_COMPRESSION", ciphers: str = "DEFAULT",
                                server_side: bool = True):
    if server_side and not cert:
        cert = find_ssl_cert(SSL_CERT_FILENAME)
        if not cert:
            raise InitException("you must specify an 'ssl-cert' file to use ssl sockets")
    ssllog = get_ssl_logger()
    ssllog("get_ssl_wrap_socket_context%s", (
        cert, key, ca_certs, ca_data,
        protocol,
        client_verify_mode, server_verify_mode,
        verify_flags,
        check_hostname, server_hostname,
        options, ciphers,
        server_side)
    )
    if server_side:
        ssl_cert_reqs = get_ssl_verify_mode(client_verify_mode)
    else:
        ssl_cert_reqs = get_ssl_verify_mode(server_verify_mode)
    ssllog(" verify_mode for server_side=%s : %s", server_side, ssl_cert_reqs)
    # ca-certs:
    if ca_certs == "default":
        ca_certs = ""
    elif ca_certs == "auto":
        ca_certs = find_ssl_cert("ca-cert.pem")
    ssllog(" ca-certs=%s", ca_certs)
    # parse protocol:
    import ssl
    if protocol.upper() == "TLS":
        protocol = "TLS_SERVER" if server_side else "TLS_CLIENT"
    proto = getattr(ssl, "PROTOCOL_" + protocol.upper().replace("TLSV", "TLSv"), None)
    if proto is None:
        values = [k[len("PROTOCOL_"):] for k in dir(ssl) if k.startswith("PROTOCOL_")]
        raise InitException(f"invalid ssl-protocol {protocol!r}, must be one of: " + csv(values))
    ssllog(" protocol=%#x", proto)
    # ca_data may be hex encoded:
    ca_data = parse_encoded_bin_data(ca_data or "")
    ssllog(" cadata=%s", Ellipsizer(ca_data))

    kwargs: dict[str, bool | str] = {
        "server_side": server_side,
        "do_handshake_on_connect": False,
        "suppress_ragged_eofs": True,
    }
    # parse ssl-verify-flags as CSV:
    ssl_verify_flags = 0
    for x in verify_flags.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "VERIFY_" + x.upper(), None)
        if v is None:
            raise InitException(f"invalid ssl verify-flag: {x!r}")
        ssl_verify_flags |= v
    ssllog(" verify-flags=%#x", ssl_verify_flags)
    # parse ssl-options as CSV:
    ssl_options = 0
    for x in options.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "OP_" + x.upper(), None)
        if v is None:
            raise InitException(f"invalid ssl option: {x!r}")
        ssl_options |= v
    ssllog(" options=%#x", ssl_options)

    context = ssl.SSLContext(proto)
    context.set_ciphers(ciphers)
    if not server_side:
        context.check_hostname = check_hostname
    context.verify_mode = ssl_cert_reqs
    context.verify_flags = ssl_verify_flags
    context.options = ssl_options
    ssllog(" cert=%s, key=%s", cert, key)
    if cert:
        if cert == "auto":
            # try to locate the cert file from known locations
            cert = find_ssl_cert()
            if not cert:
                raise InitException("failed to automatically locate an SSL certificate to use")
        key_password = key_password or os.environ.get("XPRA_SSL_KEY_PASSWORD")
        ssllog("context.load_cert_chain%s", (cert or None, key or None, key_password))
        try:
            # we must pass a `None` value to ignore `keyfile`:
            context.load_cert_chain(certfile=cert, keyfile=key or None, password=key_password)
        except ssl.SSLError as e:
            ssllog("load_cert_chain", exc_info=True)
            raise InitException(f"SSL error, failed to load certificate chain: {e}") from e
    # if not server_side and (check_hostname or (ca_certs and ca_certs.lower()!="default")):
    if not server_side:
        kwargs["server_hostname"] = server_hostname
    if ssl_cert_reqs != ssl.CERT_NONE:
        if server_side:
            purpose = ssl.Purpose.CLIENT_AUTH
        else:
            purpose = ssl.Purpose.SERVER_AUTH
            ssllog(" check_hostname=%s, server_hostname=%s", check_hostname, server_hostname)
            if context.check_hostname and not server_hostname:
                raise InitException("ssl error: check-hostname is set but server-hostname is not")
        ssllog(" load_default_certs(%s)", purpose)
        context.load_default_certs(purpose)

        if not ca_certs or ca_certs.lower() == "default":
            ssllog(" using default certs")
            # load_default_certs already calls set_default_verify_paths()
        elif not os.path.exists(ca_certs):
            raise InitException(f"invalid ssl-ca-certs file or directory: {ca_certs}")
        elif os.path.isdir(ca_certs):
            ssllog(" loading ca certs from directory '%s'", ca_certs)
            context.load_verify_locations(capath=ca_certs)
        else:
            ssllog(" loading ca certs from file '%s'", ca_certs)
            if not os.path.isfile(ca_certs):
                raise InitException(f"{ca_certs!r} is not a valid ca file")
            context.load_verify_locations(cafile=ca_certs)
        if ca_data:
            context.load_verify_locations(cadata=ca_data)
    elif check_hostname and not server_side:
        ssllog("cannot check hostname client side with verify mode %s", ssl_cert_reqs)
    return context, kwargs


def do_wrap_socket(tcp_socket, context, **kwargs):
    wrap_socket = context.wrap_socket
    assert tcp_socket
    ssllog = get_ssl_logger()
    ssllog("do_wrap_socket(%s, %s, %s)", tcp_socket, context, kwargs)
    import ssl
    if WIN32:
        # on win32, setting the tcp socket to blocking doesn't work?
        # we still hit the following errors that we need to retry:
        from xpra.net import bytestreams
        bytestreams.CAN_RETRY_EXCEPTIONS = (ssl.SSLWantReadError, ssl.SSLWantWriteError)
    else:
        tcp_socket.setblocking(True)
    try:
        ssl_sock = wrap_socket(tcp_socket, **kwargs)
    except (InitExit, InitException):
        ssllog.debug("wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
        raise
    except Exception as e:
        ssllog.debug("wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
        ssleof_error = getattr(ssl, "SSLEOFError", None)
        if ssleof_error and isinstance(e, ssleof_error):
            return None
        raise InitExit(ExitCode.SSL_FAILURE, f"Cannot wrap socket {tcp_socket}: {e}") from None
    return ssl_sock


def ssl_retry(e, ssl_ca_certs: str) -> dict[str, Any]:
    ssllog = get_ssl_logger()
    ssllog("ssl_retry(%s, %s) SSL_RETRY=%s", e, ssl_ca_certs, SSL_RETRY)
    if not SSL_RETRY:
        return {}
    if not isinstance(e, SSLVerifyFailure):
        return {}
    # we may be able to ask the user if he wants to accept this certificate
    verify_code = e.verify_code
    ssl_sock = e.ssl_sock
    msg = str(e)
    del e
    addr = ssl_sock.getpeername()[:2]
    port = addr[-1]
    server_hostname = ssl_sock.server_hostname
    ssllog("ssl_retry: peername=%s, server_hostname=%s", addr, server_hostname)
    if verify_code not in (
            SSL_VERIFY_SELF_SIGNED, SSL_VERIFY_WRONG_HOST,
            SSL_VERIFY_IP_MISMATCH, SSL_VERIFY_HOSTNAME_MISMATCH,
    ):
        ssllog("ssl_retry: %s not handled here", SSL_VERIFY_CODES.get(verify_code, verify_code))
        return {}
    if not server_hostname:
        ssllog("ssl_retry: no server hostname")
        return {}
    ssllog("ssl_retry: server_hostname=%s, ssl verify_code=%s (%i)",
           server_hostname, SSL_VERIFY_CODES.get(verify_code, verify_code), verify_code)

    def confirm(*args) -> bool:
        from xpra.scripts import pinentry
        ret = pinentry.confirm(*args)
        ssllog("run_pinentry_confirm(..) returned %r", ret)
        return ret

    options = load_ssl_options(server_hostname, port)
    # self-signed cert:
    if verify_code == SSL_VERIFY_SELF_SIGNED:
        if ssl_ca_certs not in ("", "default"):
            ssllog("self-signed cert does not match %r", ssl_ca_certs)
            return {}
        # perhaps we already have the certificate for this hostname
        cert_file = find_ssl_config_file(server_hostname, port, CERT_FILENAME)
        if cert_file:
            ssllog("retrying with %r", cert_file)
            options["ca-certs"] = cert_file
            return options
        # download the certificate data
        import ssl
        try:
            cert_data = ssl.get_server_certificate(addr)
        except ssl.SSLError:
            cert_data = None
        if not cert_data:
            ssllog.warn("Warning: failed to get server certificate from %s", addr)
            return {}
        ssllog("downloaded ssl cert data for %s: %s", addr, Ellipsizer(cert_data))
        # ask the user if he wants to accept this certificate:
        title = "SSL Certificate Verification Failure"
        prompt = "Do you want to accept this certificate?"
        if not confirm((msg,), title, prompt):
            return {}
        filename = save_ssl_config_file(server_hostname, port,
                                        CERT_FILENAME, "certificate", cert_data.encode("latin1"))
        if not filename:
            ssllog.warn("Warning: failed to save certificate data")
            return {}
        options["ca-certs"] = filename
        save_ssl_options(server_hostname, port, options)
        return options
    if verify_code in (SSL_VERIFY_WRONG_HOST, SSL_VERIFY_IP_MISMATCH, SSL_VERIFY_HOSTNAME_MISMATCH):
        # ask the user if he wants to skip verifying the host
        title = "SSL Certificate Verification Failure"
        prompt = "Do you want to connect anyway?"
        r = confirm((msg,), title, prompt)
        ssllog("run_pinentry_confirm(..) returned %r", r)
        if r:
            ssllog.info(title)
            ssllog.info(" user chose to connect anyway")
            ssllog.info(" retrying without checking the hostname")
            options["check-hostname"] = False
            save_ssl_options(server_hostname, port, options)
            return options
    return {}


def load_ssl_options(server_hostname: str, port: int) -> dict[str, Any]:
    ssllog = get_ssl_logger()
    f = find_ssl_config_file(server_hostname, port, "options")
    options = {}
    if f:
        try:
            with open(f, encoding="utf8") as fd:
                for line in fd.readlines():
                    line = line.rstrip("\n\r")
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("=", 1)
                    if len(parts) != 2:
                        continue
                    k, v = parts
                    if k not in SSL_ATTRIBUTES:
                        ssllog("Warning: unknown SSL attribute %r in %r", k, f)
                        continue
                    # some options use boolean values, convert them back:
                    options[k] = (v.lower() in TRUE_OPTIONS) if k in ("check-hostname",) else v
        except OSError as e:
            ssllog.warn("Warning: failed to read %r: %s", f, e)
    ssllog("load_ssl_options%s=%s (from %r)", (server_hostname, port), options, f)
    return options


def save_ssl_options(server_hostname: str, port, options: dict) -> str:
    ssllog = get_ssl_logger()
    boptions = b"\n".join(("{}={}".format(k.replace("_", "-"), v)).encode("latin1") for k, v in options.items())
    boptions += b"\n"
    f = save_ssl_config_file(server_hostname, port,
                             "options", "configuration options", boptions)
    ssllog("save_ssl_options%s saved to %r", (server_hostname, port, options), f)
    return f


def find_ssl_config_file(hostname: str, port=443, filename=CERT_FILENAME) -> str:
    return do_find_ssl_config_file(hostname, port, filename) or do_find_ssl_config_file(hostname, 0, filename)


def do_find_ssl_config_file(server_hostname: str, port=443, filename=CERT_FILENAME) -> str:
    ssllog = get_ssl_logger()
    from xpra.platform.paths import get_ssl_hosts_config_dirs
    dirs = get_ssl_hosts_config_dirs()
    host_dirname = std(server_hostname, extras="-.:#_")
    if port:
        host_dirname += f"_{port}"
    host_dirs = [os.path.join(osexpand(d), host_dirname) for d in dirs]
    ssllog(f"looking for {filename!r} in {host_dirs}")
    for d in host_dirs:
        f = os.path.join(d, filename)
        if os.path.exists(f):
            ssllog(f"found {f}")
            return os.path.abspath(f)
    return ""


def save_ssl_config_file(server_hostname: str, port=443,
                         filename=CERT_FILENAME, fileinfo="certificate", filedata=b"") -> str:
    ssllog = get_ssl_logger()
    from xpra.platform.paths import get_ssl_hosts_config_dirs
    dirs = get_ssl_hosts_config_dirs()
    host_dirname = std(server_hostname, extras="-.:#_")
    if port:
        host_dirname += f"_{port}"
    host_dirs = [os.path.join(osexpand(d), host_dirname) for d in dirs]
    ssllog(f"save_ssl_config_file%s dirs={dirs}, host_dirname={host_dirname}, host_dirs={host_dirs}",
           (server_hostname, port, filename, fileinfo, Ellipsizer(filedata)), )
    # if there is an existing host config dir, try to use it:
    for d in [x for x in host_dirs if os.path.exists(x)]:
        f = os.path.join(d, filename)
        try:
            with open(f, "wb") as fd:
                fd.write(filedata)
            ssllog.info(f"saved SSL {fileinfo} to {f!r}")
            return f
        except OSError:
            ssllog(f"failed to save SSL {fileinfo} to {f!r}", exc_info=True)
    # try to create a host config dir:
    for d in host_dirs:
        folders = os.path.normpath(d).split(os.sep)
        # we have to be careful and create the 'ssl' dir with 0o700 permissions
        # but any directory above that can use 0o755
        try:
            ssl_dir_index = len(folders) - 1
            while ssl_dir_index > 0 and folders[ssl_dir_index] != "ssl":
                ssl_dir_index -= 1
            if ssl_dir_index > 1:
                parent = os.path.join(*folders[:ssl_dir_index - 1])
                ssl_dir = os.path.join(*folders[:ssl_dir_index])
                os.makedirs(parent, exist_ok=True)
                os.makedirs(ssl_dir, mode=0o700, exist_ok=True)
            os.makedirs(d, mode=0o700)
            f = os.path.join(d, filename)
            with open(f, "wb") as fd:
                fd.write(filedata)
            ssllog.info(f"saved SSL {fileinfo} to {f!r}")
            return f
        except OSError:
            ssllog(f"failed to save cert data to {d!r}", exc_info=True)
    return ""


def gen_ssl_cert() -> tuple[str, str]:
    log = get_ssl_logger()
    keypath = find_ssl_cert(KEY_FILENAME)
    certpath = find_ssl_cert(CERT_FILENAME)
    if keypath and certpath:
        log.info("found an existing SSL certificate:")
        log.info(f" {keypath!r}")
        log.info(f" {certpath!r}")
        return keypath, certpath
    from shutil import which
    openssl = which("openssl") or os.environ.get("OPENSSL", "")
    if not openssl:
        raise InitExit(ExitCode.SSL_FAILURE, "cannot find openssl executable")
    openssl_config = ""
    creationflags = 0
    if WIN32:
        from xpra.platform.paths import get_app_dir
        from subprocess import CREATE_NO_WINDOW
        creationflags = CREATE_NO_WINDOW
        openssl_config = os.path.join(get_app_dir(), "etc", "ssl", "openssl.cnf")
    if is_admin():
        # running as root, use global location:
        if OSX:
            xpra_dir = "/Library/Application Support/Xpra"
        elif WIN32:
            from xpra.platform.win32.paths import get_program_data_dir
            xpra_dir = os.path.join(get_program_data_dir(), "Xpra")
        else:
            prefix = "" if sys.prefix == "/usr" else sys.prefix
            xpra_dir = f"{prefix}/etc/xpra"
        ssldir = f"{xpra_dir}/ssl"
        if not os.path.exists(xpra_dir):
            os.mkdir(ssldir, 0o777)
        if not os.path.exists(ssldir):
            os.mkdir(ssldir, 0o777)
    else:
        from xpra.platform.paths import get_ssl_cert_dirs
        dirs = [d for d in get_ssl_cert_dirs() if not d.startswith("/etc") and not d.startswith("/usr") and d != "./"]
        # use the first writeable one:
        log(f"testing ssl dirs: {dirs}")
        ssldir = ""
        for sdir in dirs:
            path = osexpand(sdir)
            if os.path.exists(path) and os.path.isdir(path) and os.access(path, os.W_OK):
                ssldir = path
                log(f"found writeable ssl dir {ssldir!r}")
                break
        if not ssldir:
            # we may have to create the parent directories:
            log("no ssl dir found, trying to create one")
            for sdir in dirs:
                path = osexpand(sdir)
                head = path
                create_dirs = []
                while head:
                    head, tail = os.path.split(head)        #ie: "/home/user/.config/xpra", "ssl"
                    log(f"{head=}, {tail=}")
                    if tail:
                        create_dirs.append(tail)
                    else:
                        break
                    if tail.find("xpra") >= 0:
                        # don't create directories above our one
                        break
                if create_dirs and head:
                    while create_dirs:
                        tail = create_dirs.pop()
                        head = os.path.join(head, tail)
                        try:
                            os.mkdir(head, 0o777)
                        except OSError as e:
                            log(f"failed to create {head!r} for {path!r}: {e}")
                            continue
                    ssldir = path
                    log(f"created {ssldir!r}")
                    break
    keypath = f"{ssldir}/{KEY_FILENAME}"
    certpath = f"{ssldir}/{CERT_FILENAME}"
    cmd = [
        openssl,
        "req", "-new",
        "-newkey", f"rsa:{KEY_SIZE}",
        "-days", f"{KEY_DAYS}",
        "-nodes", "-x509",
        "-subj", KEY_SUBJ,
        "-keyout", keypath,
        "-out", certpath,
    ]
    if openssl_config and os.path.exists(openssl_config):
        cmd += ["-config", openssl_config]
    log.info("generating a new SSL certificate:")
    log.info(f" {keypath!r}")
    log.info(f" {certpath!r}")
    log(f"openssl command: {cmd}")
    from subprocess import Popen
    with umask_context(0o022):
        with Popen(cmd, creationflags=creationflags) as p:
            exit_code = p.wait()
    if exit_code != 0:
        raise InitExit(ExitCode.FAILURE, f"openssl command returned {exit_code}")
    key = load_binary_file(keypath)
    cert = load_binary_file(certpath)
    sslcert = key+cert
    sslcertpath = f"{ssldir}/{SSL_CERT_FILENAME}"
    with open(sslcertpath, "wb") as f:
        if POSIX:
            os.fchmod(f.fileno(), 0o600)
        f.write(sslcert)
    return keypath, certpath


def strip_cert(data: bytes) -> bytes:
    BEGIN = b"-----BEGIN CERTIFICATE-----"
    if data.find(BEGIN) >= 0:
        data = BEGIN + data.split(BEGIN, 1)[1]
    END = b"-----END CERTIFICATE-----"
    if data.find(END) > 0:
        data = data.split(END, 1)[0] + END + b"\n"
    return data
