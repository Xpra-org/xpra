# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Any

from xpra.exit_codes import ExitCode
from xpra.net.tls.common import (
    get_ssl_logger,
    SSL_VERIFY_WRONG_HOST, SSL_VERIFY_SELF_SIGNED, SSL_VERIFY_IP_MISMATCH,
    SSL_VERIFY_HOSTNAME_MISMATCH, SSL_VERIFY_CODES, SSLVerifyFailure, CERT_FILENAME, SSL_CERT_FILENAME,
)
from xpra.net.tls.file import (
    find_ssl_cert, load_ssl_options,
    save_ssl_options, find_ssl_config_file, save_ssl_config_file,
)
from xpra.net.tls.parsing import (
    parse_ssl_options_mask, parse_ssl_verify_mask, parse_ssl_protocol, parse_ssl_verify_mode,
)
from xpra.scripts.config import InitExit, InitException
from xpra.util.env import envbool, envint
from xpra.util.parsing import parse_encoded_bin_data
from xpra.util.str_fn import print_nested_dict, Ellipsizer

SSL_RETRY = envbool("XPRA_SSL_RETRY", True)
SSL_HANDSHAKE_TIMEOUT = envint("XPRA_SSL_HANDSHAKE_TIMEOUT", 20)


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


def get_peer_cert_data(ssl_sock) -> str:
    """
    The PEM certificate the peer presented, even if the handshake failed to verify it.
    This requires Python 3.13 or later, `getpeercert()` refuses incomplete handshakes.
    """
    get_unverified_chain = getattr(ssl_sock, "get_unverified_chain", None)
    if not get_unverified_chain:
        return ""
    try:
        chain = get_unverified_chain()
        if not chain:
            return ""
        cert = chain[0]
        if isinstance(cert, bytes):
            import ssl
            return ssl.DER_cert_to_PEM_cert(cert)
        # Python 3.13.0 returns `_ssl.Certificate` objects:
        return cert.public_bytes()
    except (OSError, ValueError, AttributeError):
        get_ssl_logger()("get_unverified_chain()", exc_info=True)
        return ""


def ssl_handshake(ssl_sock, timeout: float = SSL_HANDSHAKE_TIMEOUT) -> None:
    log = get_ssl_logger()
    # the socket is usually in blocking mode (see `do_wrap_socket`),
    # don't wait forever for a peer that never completes the handshake:
    previous_timeout = ssl_sock.gettimeout()
    ssl_sock.settimeout(timeout)
    try:
        ssl_sock.do_handshake(True)
        log.info("SSL handshake complete, %s", ssl_sock.version())
        log_ssl_info(ssl_sock)
    except Exception as e:
        log("do_handshake", exc_info=True)
        log_ssl_info(ssl_sock)
        import ssl
        status = ExitCode.SSL_FAILURE
        if isinstance(e, (ssl.SSLEOFError, ConnectionError)):
            # the handshake did not complete, so the socket is unusable:
            raise InitExit(status, "the connection was closed during the SSL handshake") from None
        if isinstance(e, TimeoutError):
            raise InitExit(status, f"SSL handshake timed out after {timeout} seconds") from None
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
            raise SSLVerifyFailure(status, msg, verify_code, get_peer_cert_data(ssl_sock)) from None
        raise InitExit(status, f"SSL handshake failed: {e}") from None
    finally:
        try:
            ssl_sock.settimeout(previous_timeout)
        except OSError:
            log("failed to restore the socket timeout", exc_info=True)


def get_ssl_wrap_socket_context(cert: str = "", key: str = "", key_password: str = "",
                                ca_certs: str = "", ca_data: str = "",
                                protocol: str = "TLS",
                                client_verify_mode: str = "optional", server_verify_mode: str = "required",
                                verify_flags: str = "X509_STRICT",
                                check_hostname: bool = False, server_hostname: str = "",
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
        parsed_ca_data = parse_encoded_bin_data(ca_data or "")
        log(" cadata=%s", Ellipsizer(parsed_ca_data))
        if parsed_ca_data:
            context.load_verify_locations(cadata=parsed_ca_data)
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


def get_cert_fingerprint(cert_data: str) -> str:
    import ssl
    from hashlib import sha256
    try:
        digest = sha256(ssl.PEM_cert_to_DER_cert(cert_data)).hexdigest().upper()
    except ValueError:
        return ""
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def get_cert_file_fingerprint(filename: str) -> str:
    try:
        with open(filename, encoding="latin1") as f:
            return get_cert_fingerprint(f.read())
    except OSError:
        get_ssl_logger()("failed to read %r", filename, exc_info=True)
        return ""


def warn_certificate_changed(e: InitExit, cert_file: str, cert_data: str) -> None:
    """
    The server may have been re-configured, or the connection may have been intercepted.
    The log is not visible to everyone, so we also explain it in the error that the user is shown,
    in case they don't replace the certificate.
    """
    log = get_ssl_logger()
    e.args = (f"the server's certificate does not match the one accepted previously: {e}", )
    log.warn("Warning: the server's certificate does not match the one accepted previously")
    log.warn(" previous certificate: %r", cert_file)
    log.warn(" previous SHA256 fingerprint: %s", get_cert_file_fingerprint(cert_file) or "unknown")
    log.warn(" new SHA256 fingerprint: %s", get_cert_fingerprint(cert_data) or "unknown")
    log.warn(" if the server's certificate has been changed legitimately,")
    # the saved options refer to this certificate, so remove both:
    log.warn(" delete %r and connect again", os.path.dirname(cert_file))


def get_server_certificate(display_desc: dict[str, Any], server_hostname: str) -> str:
    """
    Download the server's certificate without verifying it.
    Unlike `ssl.get_server_certificate`, this connects the same way the client does,
    so a `proxy-host` is honoured: the destination may only be reachable through it,
    and we must not resolve it locally or connect to it directly.
    """
    import ssl
    from xpra.net.connect import retry_socket_connect
    log = get_ssl_logger()
    # the server was reachable a moment ago, don't keep retrying if it isn't anymore:
    options = dict(display_desc, retry=False)
    try:
        sock = retry_socket_connect(options)
    except (OSError, ValueError, InitExit):
        log("retry_socket_connect(%s)", options, exc_info=True)
        return ""
    try:
        # use the same protocol, ciphers, options and client certificate as the connection that failed,
        # or the server may refuse a handshake it would otherwise accept, but don't verify anything:
        ssl_options = {k.replace("-", "_"): v for k, v in (display_desc.get("ssl-options") or {}).items()}
        ssl_options.update({
            "server_side": False,
            "server_verify_mode": "none",
            "check_hostname": False,
            "server_hostname": server_hostname,
        })
        context = get_ssl_wrap_socket_context(**ssl_options)[0]
        sock.settimeout(SSL_HANDSHAKE_TIMEOUT)
        with context.wrap_socket(sock, server_hostname=server_hostname) as ssl_sock:
            der = ssl_sock.getpeercert(binary_form=True)
        return ssl.DER_cert_to_PEM_cert(der) if der else ""
    except (OSError, ValueError, TypeError, ssl.SSLError, InitException):
        log("get_server_certificate(%s, %s)", display_desc, server_hostname, exc_info=True)
        return ""
    finally:
        sock.close()


def ssl_retry(e, display_desc: dict[str, Any]) -> dict[str, Any]:
    """
    Ask the user whether to accept the certificate that failed verification.
    Returns the ssl options to change before connecting again, if any.
    The socket is gone by the time we get here,
    so we use the connection target from `display_desc` and the certificate recorded in `e`.
    """
    log = get_ssl_logger()
    log("ssl_retry(%s, %s) SSL_RETRY=%s", e, display_desc, SSL_RETRY)
    if not SSL_RETRY:
        return {}
    if not isinstance(e, SSLVerifyFailure):
        return {}
    # we may be able to ask the user if he wants to accept this certificate
    verify_code = e.verify_code
    if verify_code not in (
            SSL_VERIFY_SELF_SIGNED, SSL_VERIFY_WRONG_HOST,
            SSL_VERIFY_IP_MISMATCH, SSL_VERIFY_HOSTNAME_MISMATCH,
    ):
        log("ssl_retry: %s not handled here", SSL_VERIFY_CODES.get(verify_code, verify_code))
        return {}
    host = display_desc.get("host", "")
    port = display_desc.get("port", 0)
    ssl_options = display_desc.get("ssl-options") or {}
    # the same host and port that `get_ssl_options` loads the saved options from:
    server_hostname = ssl_options.get("server-hostname") or host
    if not server_hostname or not port:
        log("ssl_retry: unknown target %r, port %r", server_hostname, port)
        return {}
    log("ssl_retry: server_hostname=%s, port=%s, ssl verify_code=%s (%i)",
        server_hostname, port, SSL_VERIFY_CODES.get(verify_code, verify_code), verify_code)

    def confirm(*args) -> bool:
        from xpra.scripts import pinentry
        ret = pinentry.confirm(*args)
        log("run_pinentry_confirm(..) returned %r", ret)
        return ret

    msg = str(e)
    title = "SSL Certificate Verification Failure"
    # self-signed cert:
    if verify_code == SSL_VERIFY_SELF_SIGNED:
        ca_certs = ssl_options.get("ca-certs", "default")
        default_ca_certs = ca_certs in ("", "default")
        # perhaps we already have the certificate for this hostname
        cert_file = find_ssl_config_file(server_hostname, port, CERT_FILENAME)
        if not default_ca_certs and not (cert_file and os.path.abspath(ca_certs) == cert_file):
            log("self-signed cert does not match %r", ca_certs)
            return {}
        if cert_file and default_ca_certs and not e.cert_data:
            # we can't tell if it is the certificate that failed, so try it:
            log("retrying with %r", cert_file)
            return {"ca-certs": cert_file}
        cert_data = e.cert_data
        if not cert_data:
            # older Python versions can't give us the certificate that failed, download it.
            # This connects by hostname again, so it may reach a different peer (ie: round-robin DNS),
            # that's fine: the certificate we show the fingerprint of is the one we save and trust,
            # and the retry is verified against it, whichever peer it reaches:
            cert_data = get_server_certificate(display_desc, server_hostname)
            if not cert_data:
                log.warn("Warning: failed to get server certificate from %s:%s", host, port)
                return {}
            log("downloaded ssl cert data for %s:%s: %s", host, port, Ellipsizer(cert_data))
        fingerprint = get_cert_fingerprint(cert_data)
        # ask the user if he wants to accept this certificate:
        lines = (msg, f"SHA256 fingerprint: {fingerprint}") if fingerprint else (msg, )
        prompt = "Do you want to accept this certificate?"
        if cert_file:
            previous_fingerprint = get_cert_file_fingerprint(cert_file)
            if fingerprint == previous_fingerprint:
                if default_ca_certs:
                    log("retrying with %r", cert_file)
                    return {"ca-certs": cert_file}
                log("the certificate matches %r, the verification failed for another reason", cert_file)
                return {}
            warn_certificate_changed(e, cert_file, cert_data)
            title = "SSL Certificate Changed"
            lines = (
                "The server's certificate does not match the one accepted previously.",
                "The server may have been re-configured, or the connection may have been intercepted.",
                f"Previous SHA256 fingerprint: {previous_fingerprint or 'unknown'}",
                f"New SHA256 fingerprint: {fingerprint or 'unknown'}",
            )
            prompt = "Do you want to replace the certificate accepted previously?"
        if not confirm(lines, title, prompt):
            return {}
        filename = save_ssl_config_file(server_hostname, port,
                                        CERT_FILENAME, "certificate", cert_data.encode("latin1"))
        if not filename:
            log.warn("Warning: failed to save certificate data")
            return {}
        mods = {"ca-certs": filename}
    else:
        # ask the user if he wants to skip verifying the host
        if not confirm((msg,), title, "Do you want to connect anyway?"):
            return {}
        log.info(title)
        log.info(" user chose to connect anyway")
        log.info(" retrying without checking the hostname")
        mods = {"check-hostname": False}
    options = load_ssl_options(server_hostname, port)
    options.update(mods)
    save_ssl_options(server_hostname, port, options)
    return mods
