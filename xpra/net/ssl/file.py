# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any

from xpra.exit_codes import ExitCode
from xpra.net.ssl.common import KEY_FILENAME, CERT_FILENAME, SSL_CERT_FILENAME, SSL_ATTRIBUTES, get_ssl_logger
from xpra.os_util import is_admin, OSX, WIN32, POSIX
from xpra.scripts.config import InitExit
from xpra.util.parsing import TRUE_OPTIONS
from xpra.util.env import osexpand
from xpra.util.io import umask_context, load_binary_file
from xpra.util.str_fn import std, Ellipsizer

KEY_SIZE = 4096
KEY_DAYS = 3650
KEY_SUBJ = "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost"


def find_ssl_cert(filename: str = SSL_CERT_FILENAME) -> str:
    log = get_ssl_logger()
    # try to locate the cert file from known locations
    from xpra.platform.paths import get_ssl_cert_dirs  # pylint: disable=import-outside-toplevel
    dirs = get_ssl_cert_dirs()
    log(f"find_ssl_cert({filename}) get_ssl_cert_dirs()={dirs}")
    for d in dirs:
        p = osexpand(d)
        if not os.path.exists(p):
            log(f"ssl cert dir {p!r} does not exist")
            continue
        f = os.path.join(p, filename)
        if not os.path.exists(f):
            log(f"ssl cert {f!r} does not exist")
            continue
        if not os.path.isfile(f):
            log.warn(f"Warning: {f!r} is not a file")
            continue
        if not os.access(f, os.R_OK):
            log.info(f"SSL certificate file {f!r} is not accessible")
            continue
        log(f"found ssl cert {f!r}")
        return os.path.abspath(f)
    return ""


def load_ssl_options(server_hostname: str, port: int) -> dict[str, bool | str]:
    log = get_ssl_logger()
    f = find_ssl_config_file(server_hostname, port, "options")
    options: dict[str, bool | str] = {}
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
                        log("Warning: unknown SSL attribute %r in %r", k, f)
                        continue
                    # some options use boolean values, convert them back:
                    options[k] = (v.lower() in TRUE_OPTIONS) if k in ("check-hostname",) else v
        except OSError as e:
            log.warn("Warning: failed to read %r: %s", f, e)
    log("load_ssl_options%s=%s (from %r)", (server_hostname, port), options, f)
    return options


def save_ssl_options(server_hostname: str, port, options: dict) -> str:
    log = get_ssl_logger()
    boptions = b"\n".join(("{}={}".format(k.replace("_", "-"), v)).encode("latin1") for k, v in options.items())
    boptions += b"\n"
    f = save_ssl_config_file(server_hostname, port,
                             "options", "configuration options", boptions)
    log("save_ssl_options%s saved to %r", (server_hostname, port, options), f)
    return f


def find_ssl_config_file(hostname: str, port=443, filename=CERT_FILENAME) -> str:
    return do_find_ssl_config_file(hostname, port, filename) or do_find_ssl_config_file(hostname, 0, filename)


def do_find_ssl_config_file(server_hostname: str, port=443, filename=CERT_FILENAME) -> str:
    log = get_ssl_logger()
    from xpra.platform.paths import get_ssl_hosts_config_dirs
    dirs = get_ssl_hosts_config_dirs()
    host_dirname = std(server_hostname, extras="-.:#_")
    if port:
        host_dirname += f"_{port}"
    host_dirs = [os.path.join(osexpand(d), host_dirname) for d in dirs]
    log(f"looking for {filename!r} in {host_dirs}")
    for d in host_dirs:
        f = os.path.join(d, filename)
        if os.path.exists(f):
            log(f"found {f}")
            return os.path.abspath(f)
    return ""


def save_ssl_config_file(server_hostname: str, port=443,
                         filename=CERT_FILENAME, fileinfo="certificate", filedata=b"") -> str:
    log = get_ssl_logger()
    from xpra.platform.paths import get_ssl_hosts_config_dirs
    dirs = get_ssl_hosts_config_dirs()
    host_dirname = std(server_hostname, extras="-.:#_")
    if port:
        host_dirname += f"_{port}"
    host_dirs = [os.path.join(osexpand(d), host_dirname) for d in dirs]
    log(f"save_ssl_config_file%s dirs={dirs}, host_dirname={host_dirname}, host_dirs={host_dirs}",
        (server_hostname, port, filename, fileinfo, Ellipsizer(filedata)), )
    # if there is an existing host config dir, try to use it:
    for d in [x for x in host_dirs if os.path.exists(x)]:
        f = os.path.join(d, filename)
        try:
            with open(f, "wb") as fd:
                fd.write(filedata)
            log.info(f"saved SSL {fileinfo} to {f!r}")
            return f
        except OSError:
            log(f"failed to save SSL {fileinfo} to {f!r}", exc_info=True)
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
                folder = folders[0]
                parent = os.path.join(folder, *folders[1:ssl_dir_index - 1])
                ssl_dir = os.path.join(folder, *folders[1:ssl_dir_index])
                os.makedirs(parent, exist_ok=True)
                os.makedirs(ssl_dir, mode=0o700, exist_ok=True)
            os.makedirs(d, mode=0o700)
            f = os.path.join(d, filename)
            with open(f, "wb") as fd:
                fd.write(filedata)
            log.info(f"saved SSL {fileinfo} to {f!r}")
            return f
        except OSError:
            log(f"failed to save cert data to {d!r}", exc_info=True)
    return ""


def get_gen_ssl_cert_dir() -> str:
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
        return ssldir
    from xpra.platform.paths import get_ssl_cert_dirs
    dirs = [d for d in get_ssl_cert_dirs() if not d.startswith("/etc") and not d.startswith("/usr") and d != "./"]
    # use the first writeable one:
    log = get_ssl_logger()
    log(f"testing ssl dirs: {dirs}")
    for sdir in dirs:
        ssldir = osexpand(sdir)
        if os.path.exists(ssldir) and os.path.isdir(ssldir) and os.access(ssldir, os.W_OK):
            log(f"found writeable ssl dir {ssldir!r}")
            return ssldir
    # we may have to create the parent directories:
    log("no existing ssl dir found, trying to create one")
    for sdir in dirs:
        ssldir = osexpand(sdir)
        head = ssldir
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
                    log(f"failed to create {head!r} for {ssldir!r}: {e}")
                    continue
            log(f"created {ssldir!r}")
            return ssldir
    raise RuntimeError("unable to locate or create an ssl certificate directory")


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
    ssldir = get_gen_ssl_cert_dir()
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
    openssl_config = ""
    creationflags = 0
    if WIN32:
        from xpra.platform.paths import get_app_dir
        from subprocess import CREATE_NO_WINDOW
        creationflags = CREATE_NO_WINDOW
        openssl_config = os.path.join(get_app_dir(), "etc", "ssl", "openssl.cnf")
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
