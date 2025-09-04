# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Any

from xpra.exit_codes import ExitCode
from xpra.net.ssl.common import (
    get_ssl_logger,
    SSL_VERIFY_WRONG_HOST, SSL_VERIFY_SELF_SIGNED, SSL_VERIFY_IP_MISMATCH,
    SSL_VERIFY_HOSTNAME_MISMATCH, SSL_VERIFY_CODES, SSLVerifyFailure, CERT_FILENAME, SSL_CERT_FILENAME,
)
from xpra.net.ssl.file import (
    find_ssl_cert, load_ssl_options,
    save_ssl_options, find_ssl_config_file, save_ssl_config_file,
)
from xpra.net.ssl.parsing import (
    parse_ssl_options_mask, parse_ssl_verify_mask, parse_ssl_protocol, parse_ssl_verify_mode,
)
from xpra.scripts.config import InitExit, InitException
from xpra.util.env import envbool
from xpra.util.parsing import parse_encoded_bin_data
from xpra.util.str_fn import print_nested_dict, Ellipsizer

SSL_RETRY = envbool("XPRA_SSL_RETRY", True)


def ssl_wrap_socket(sock, **kwargs):
    context, wrap_kwargs = get_ssl_wrap_socket_context(**kwargs)
    log = get_ssl_logger()
    log("ssl_wrap_socket(%s, %s) context=%s, wrap_kwargs=%s", sock, kwargs, context, wrap_kwargs)
    return do_wrap_socket(sock, context, **wrap_kwargs)


def log_ssl_info(ssl_sock) -> None:
    log = get_ssl_logger()
    log("server_hostname=%s", ssl_sock.server_hostname)
    cipher = ssl_sock.cipher()
    if cipher:
        log.info(" %s, %s bits", cipher[0], cipher[2])
    try:
        cert = ssl_sock.getpeercert()
    except ValueError:
        pass
    else:
        if cert:
            log("certificate:")
            print_nested_dict(ssl_sock.getpeercert(), prefix=" ", print_fn=log)


def ssl_handshake(ssl_sock) -> None:
    log = get_ssl_logger()
    try:
        ssl_sock.do_handshake(True)
        log.info("SSL handshake complete, %s", ssl_sock.version())
        log_ssl_info(ssl_sock)
    except Exception as e:
        log("do_handshake", exc_info=True)
        log_ssl_info(ssl_sock)
        import ssl
        ssleof_error = getattr(ssl, "SSLEOFError", None)
        if ssleof_error and isinstance(e, ssleof_error):
            return
        status = ExitCode.SSL_FAILURE
        ssl_cert_verification_error = getattr(ssl, "SSLCertVerificationError", None)
        if ssl_cert_verification_error and isinstance(e, ssl_cert_verification_error):
            verify_code = getattr(e, "verify_code", 0)
            log("verify_code=%s", SSL_VERIFY_CODES.get(verify_code, verify_code))
            try:
                msg = getattr(e, "verify_message") or (e.args[1].split(":", 2)[2])
            except (ValueError, IndexError):
                msg = str(e)
            status = ExitCode.SSL_CERTIFICATE_VERIFY_FAILURE
            log("host failed SSL verification: %s", msg)
            raise SSLVerifyFailure(status, msg, verify_code, ssl_sock) from None
        raise InitExit(status, f"SSL handshake failed: {e}") from None


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
    log = get_ssl_logger()
    log("get_ssl_wrap_socket_context%s", (
        cert, key, ca_certs, ca_data, protocol, client_verify_mode, server_verify_mode, verify_flags,
        check_hostname, server_hostname, options, ciphers, server_side)
        )
    ssl_cert_reqs = parse_ssl_verify_mode(client_verify_mode if server_side else server_verify_mode)
    log(" verify_mode for server_side=%s : %s", server_side, ssl_cert_reqs)
    # parse protocol:
    import ssl
    kwargs: dict[str, bool | str] = {
        "server_side": server_side,
        "do_handshake_on_connect": False,
        "suppress_ragged_eofs": True,
    }
    if not server_side:
        kwargs["server_hostname"] = server_hostname
    proto = parse_ssl_protocol(protocol, server_side)
    context = ssl.SSLContext(proto)
    context.set_ciphers(ciphers)
    if not server_side:
        context.check_hostname = check_hostname
    context.verify_mode = ssl_cert_reqs
    # we can't specify the type hint without depending on the `ssl` module:
    # noinspection PyTypeChecker
    context.verify_flags = parse_ssl_verify_mask(verify_flags)
    context.options = parse_ssl_options_mask(options)
    log(" cert=%s, key=%s", cert, key)
    if cert:
        if cert == "auto":
            # try to locate the cert file from known locations
            cert = find_ssl_cert()
            if not cert:
                raise InitException("failed to automatically locate an SSL certificate to use")
        # Important: keep key_password=None when no password is available
        key_password = key_password or os.environ.get("XPRA_SSL_KEY_PASSWORD")
        log("context.load_cert_chain%s", (cert or None, key or None, key_password))
        try:
            # we must pass a `None` value to ignore `keyfile`:
            context.load_cert_chain(certfile=cert, keyfile=key or None, password=key_password)
        except ssl.SSLError as e:
            log("load_cert_chain", exc_info=True)
            raise InitException(f"SSL error, failed to load certificate chain: {e}") from e
    if ssl_cert_reqs != ssl.CERT_NONE:
        log(" check_hostname=%s, server_hostname=%s", check_hostname, server_hostname)
        purpose = ssl.Purpose.CLIENT_AUTH if server_side else ssl.Purpose.SERVER_AUTH
        if not server_side and context.check_hostname and not server_hostname:
            raise InitException("ssl error: check-hostname is set but server-hostname is not")
        log(" load_default_certs(%s)", purpose)
        context.load_default_certs(purpose)

        # ca-certs:
        if ca_certs == "default":
            ca_certs = ""
        elif ca_certs == "auto":
            ca_certs = find_ssl_cert("ca-cert.pem")
        log(" ca-certs=%s", ca_certs)

        if not ca_certs or ca_certs.lower() == "default":
            log(" using default certs")
            # load_default_certs already calls set_default_verify_paths()
        elif not os.path.exists(ca_certs):
            raise InitException(f"invalid ssl-ca-certs file or directory: {ca_certs}")
        elif os.path.isdir(ca_certs):
            log(" loading ca certs from directory '%s'", ca_certs)
            context.load_verify_locations(capath=ca_certs)
        else:
            log(" loading ca certs from file '%s'", ca_certs)
            if not os.path.isfile(ca_certs):
                raise InitException(f"{ca_certs!r} is not a valid ca file")
            context.load_verify_locations(cafile=ca_certs)
        # ca_data may be hex encoded:
        ca_data = parse_encoded_bin_data(ca_data or "")
        log(" cadata=%s", Ellipsizer(ca_data))
        if ca_data:
            context.load_verify_locations(cadata=ca_data)
    elif check_hostname and not server_side:
        log("cannot check hostname client side with verify mode %s", ssl_cert_reqs)
    return context, kwargs


def do_wrap_socket(tcp_socket, context, **kwargs):
    wrap_socket = context.wrap_socket
    assert tcp_socket
    log = get_ssl_logger()
    log("do_wrap_socket(%s, %s, %s)", tcp_socket, context, kwargs)
    tcp_socket.setblocking(True)
    from ssl import SSLEOFError
    try:
        return wrap_socket(tcp_socket, **kwargs)
    except (InitExit, InitException):
        log.debug("wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
        raise
    except SSLEOFError:
        log.debug("wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
        return None
    except Exception as e:
        log.debug("wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
        raise InitExit(ExitCode.SSL_FAILURE, f"Cannot wrap socket {tcp_socket}: {e}") from None


def ssl_retry(e, ssl_ca_certs: str) -> dict[str, Any]:
    log = get_ssl_logger()
    log("ssl_retry(%s, %s) SSL_RETRY=%s", e, ssl_ca_certs, SSL_RETRY)
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
    log("ssl_retry: peername=%s, server_hostname=%s", addr, server_hostname)
    if verify_code not in (
            SSL_VERIFY_SELF_SIGNED, SSL_VERIFY_WRONG_HOST,
            SSL_VERIFY_IP_MISMATCH, SSL_VERIFY_HOSTNAME_MISMATCH,
    ):
        log("ssl_retry: %s not handled here", SSL_VERIFY_CODES.get(verify_code, verify_code))
        return {}
    if not server_hostname:
        log("ssl_retry: no server hostname")
        return {}
    log("ssl_retry: server_hostname=%s, ssl verify_code=%s (%i)",
        server_hostname, SSL_VERIFY_CODES.get(verify_code, verify_code), verify_code)

    def confirm(*args) -> bool:
        from xpra.scripts import pinentry
        ret = pinentry.confirm(*args)
        log("run_pinentry_confirm(..) returned %r", ret)
        return ret

    options = load_ssl_options(server_hostname, port)
    # self-signed cert:
    if verify_code == SSL_VERIFY_SELF_SIGNED:
        if ssl_ca_certs not in ("", "default"):
            log("self-signed cert does not match %r", ssl_ca_certs)
            return {}
        # perhaps we already have the certificate for this hostname
        cert_file = find_ssl_config_file(server_hostname, port, CERT_FILENAME)
        if cert_file:
            log("retrying with %r", cert_file)
            options["ca-certs"] = cert_file
            return options
        # download the certificate data
        import ssl
        try:
            cert_data = ssl.get_server_certificate(addr)
        except ssl.SSLError:
            cert_data = ""
        if not cert_data:
            log.warn("Warning: failed to get server certificate from %s", addr)
            return {}
        log("downloaded ssl cert data for %s: %s", addr, Ellipsizer(cert_data))
        # ask the user if he wants to accept this certificate:
        title = "SSL Certificate Verification Failure"
        prompt = "Do you want to accept this certificate?"
        if not confirm((msg,), title, prompt):
            return {}
        filename = save_ssl_config_file(server_hostname, port,
                                        CERT_FILENAME, "certificate", cert_data.encode("latin1"))
        if not filename:
            log.warn("Warning: failed to save certificate data")
            return {}
        options["ca-certs"] = filename
        save_ssl_options(server_hostname, port, options)
        return options
    if verify_code in (SSL_VERIFY_WRONG_HOST, SSL_VERIFY_IP_MISMATCH, SSL_VERIFY_HOSTNAME_MISMATCH):
        # ask the user if he wants to skip verifying the host
        title = "SSL Certificate Verification Failure"
        prompt = "Do you want to connect anyway?"
        r = confirm((msg,), title, prompt)
        log("run_pinentry_confirm(..) returned %r", r)
        if r:
            log.info(title)
            log.info(" user chose to connect anyway")
            log.info(" retrying without checking the hostname")
            options["check-hostname"] = False
            save_ssl_options(server_hostname, port, options)
            return options
    return {}
