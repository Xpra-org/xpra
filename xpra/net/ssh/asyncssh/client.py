# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import os
import re
import stat
import sys
import tempfile
from typing import Any
from collections.abc import Sequence

from xpra.exit_codes import ExitCode
from xpra.log import Logger
from xpra.net.aio.thread import get_threaded_loop
from xpra.net.bytestreams import SOCKET_TIMEOUT
from xpra.net.connect import host_target_string
from xpra.net.ssh.asyncssh.connection import SSHStreamConnection
from xpra.platform.info import get_username
from xpra.platform.paths import get_ssh_known_hosts_files
from xpra.scripts.args import shellquote
from xpra.scripts.config import InitExit
from xpra.scripts.pinentry import confirm, input_pass
from xpra.util.env import envbool, envint
from xpra.util.io import umask_context
from xpra.util.parsing import str_to_bool

log = Logger("network", "ssh")

try:
    import asyncssh
except ImportError:
    asyncssh = None

if asyncssh and log.is_debug_enabled():
    import logging
    logging.getLogger("asyncssh").setLevel(logging.DEBUG)


WINDOW_SIZE = envint("XPRA_SSH_WINDOW_SIZE", 2 ** 27 - 1)
TIMEOUT = envint("XPRA_SSH_TIMEOUT", 60)
VERIFY_HOSTKEY = envbool("XPRA_SSH_VERIFY_HOSTKEY", True)
VERIFY_STRICT = envbool("XPRA_SSH_VERIFY_STRICT", False)
ADD_KEY = envbool("XPRA_SSH_ADD_KEY", True)
PASSWORD_RETRY = envint("XPRA_SSH_PASSWORD_RETRY", 2)
PASSPHRASE_RETRY = max(1, min(5, envint("XPRA_SSH_PASSPHRASE_RETRY", 3)))
SSH_AGENT = envbool("XPRA_SSH_AGENT", False)
TEST_COMMAND_TIMEOUT = envint("XPRA_SSH_TEST_COMMAND_TIMEOUT", 10)

MSYS_DEFAULT_PATH = os.environ.get("XPRA_MSYS_DEFAULT_PATH", "/mingw64/bin/xpra")
CYGWIN_DEFAULT_PATH = os.environ.get("XPRA_CYGWIN_DEFAULT_PATH", "/cygdrive/c/Program Files/Xpra/Xpra_cmd.exe")
DEFAULT_WIN32_INSTALL_PATH = "C:\\Program Files\\Xpra"
WIN32_REGISTRY_QUERY = 'REG QUERY "HKEY_LOCAL_MACHINE\\Software\\Xpra" /v InstallPath'

AUTH_MODES: Sequence[str] = os.environ.get(
    "XPRA_ASYNCSSH_AUTH_MODES", "agent,publickey,password"
).split(",")


def get_ssh_config_files() -> list[str]:
    """Return existing system and per-user OpenSSH client config files."""
    etc = "/etc" if sys.prefix == "/usr" else os.path.join(sys.prefix, "etc")
    candidates = (
        os.path.join(etc, "ssh", "ssh_config"),
        os.path.expanduser("~/.ssh/config"),
        os.path.expanduser("~/ssh/config"),
    )
    return [filename for filename in candidates if os.path.isfile(filename)]


def get_known_hosts_files() -> list[str]:
    return [
        filename for path in get_ssh_known_hosts_files()
        if os.path.isfile(filename := os.path.expanduser(path))
    ]


def host_key_name(host: str, port: int) -> str:
    return f"[{host}]:{port}" if port and port != 22 else host


class HostKeyManager:
    """Validate unknown AsyncSSH host keys using Xpra's confirmation UI."""

    def __init__(self, known_hosts, strict: bool, add_key: bool, verify_dns: bool):
        self.known_hosts = known_hosts
        self.strict = strict
        self.add_key = add_key
        self.verify_dns = verify_dns

    def validate(self, host: str, addr: str, port: int, key) -> bool:
        matched = self.known_hosts.match(host, addr, port if port != 22 else None)
        known_keys = matched[0]
        changed = bool(known_keys)
        key_type = key.get_algorithm().replace("ssh-", "")
        fingerprint = key.get_fingerprint("sha256")
        if changed:
            log.warn("Warning: SSH server key mismatch")
            qinfo = [
                "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!",
                "Someone could be eavesdropping on you right now (man-in-the-middle attack).",
                "It is also possible that the host key has just been changed.",
                f"The fingerprint for the {key_type} key sent by the remote host is",
                fingerprint,
            ]
        else:
            log.warn("Warning: unknown SSH host %r", host)
            qinfo = [
                f"The authenticity of host {host!r} can't be established.",
                f"{key_type} key fingerprint is",
                fingerprint,
            ]

        dnscheck: bool | str = ""
        if self.verify_dns:
            try:
                from xpra.net.ssh.sshfp import do_check_host_key
                dnscheck = do_check_host_key(host, key.get_algorithm(), key.public_data)
            except Exception as e:
                log("SSHFP validation failed", exc_info=True)
                dnscheck = f"error checking SSHFP record: {e}"
        if dnscheck is True:
            log.info("found a valid SSHFP record for host %s", host)
        elif dnscheck:
            qinfo += ["SSHFP validation failed:", str(dnscheck)]

        if self.strict and dnscheck is not True:
            log.warn("Host key verification failed")
            return False
        if dnscheck is not True and not confirm(qinfo):
            return False
        if self.add_key:
            self.save(host, addr, port, key, changed)
        return True

    @staticmethod
    def _remove_old_key(filename: str, host: str, addr: str, port: int, key) -> None:
        with open(filename, "rb") as known_hosts_file:
            lines = known_hosts_file.readlines()
        host_names = {host_key_name(host, port), host_key_name(addr, port)}
        algorithm = key.get_algorithm()
        changed = False
        output = []
        for line in lines:
            fields = line.split(None, 2)
            if len(fields) < 3 or fields[0].startswith(b"@"):
                output.append(line)
                continue
            try:
                line_algorithm = fields[1].decode("ascii")
                patterns = fields[0].decode("utf8").split(",")
            except UnicodeDecodeError:
                output.append(line)
                continue
            if line_algorithm != algorithm:
                output.append(line)
                continue
            remaining = [pattern for pattern in patterns if pattern not in host_names]
            if len(remaining) != len(patterns):
                changed = True
                if remaining:
                    output.append(",".join(remaining).encode("utf8") + b" " + fields[1] + b" " + fields[2])
                continue
            if len(patterns) == 1 and patterns[0].startswith("|"):
                try:
                    matched = asyncssh.import_known_hosts(line.decode("utf8")).match(
                        host, addr, port if port != 22 else None
                    )
                except (UnicodeDecodeError, ValueError):
                    pass
                else:
                    if any(old_key.get_algorithm() == algorithm for old_key in matched[0]):
                        changed = True
                        continue
            output.append(line)
        if not changed:
            return
        mode = stat.S_IMODE(os.stat(filename).st_mode)
        fd, tmpname = tempfile.mkstemp(prefix=".known_hosts.", dir=os.path.dirname(filename))
        try:
            os.chmod(tmpname, mode)
            with os.fdopen(fd, "wb") as known_hosts_file:
                known_hosts_file.writelines(output)
            os.replace(tmpname, filename)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmpname)
            except OSError:
                pass
            raise

    @classmethod
    def save(cls, host: str, addr: str, port: int, key, replace: bool = False) -> None:
        filenames = [os.path.expanduser(path) for path in get_ssh_known_hosts_files()]
        existing = [filename for filename in filenames if os.path.isfile(filename)]
        missing = [filename for filename in filenames if filename not in existing]
        if replace:
            for filename in existing:
                try:
                    cls._remove_old_key(filename, host, addr, port, key)
                except OSError:
                    log("failed to replace old SSH host key in %r", filename, exc_info=True)
        line = host_key_name(host, port).encode("utf8") + b" " + key.export_public_key("openssh").strip() + b"\n"
        for filename in existing + missing:
            try:
                parent = os.path.dirname(filename)
                if not os.path.exists(parent):
                    os.makedirs(parent, mode=0o700)
                elif not os.path.isdir(parent):
                    continue
                with umask_context(0o133):
                    with open(filename, "ab") as known_hosts_file:
                        known_hosts_file.write(line)
                log.info("saved SSH host key to %r", filename)
                return
            except OSError as e:
                log("failed to save SSH host key to %r", filename, exc_info=True)
                log.error("Error saving SSH host key to %r: %s", filename, e)


class PasswordManager:
    def __init__(self, username: str, host: str, password: str, retries: int):
        self.username = username
        self.host = host
        self.password = password
        self.retries = max(0, retries)
        self.attempt = 0

    async def get_password(self) -> str | None:
        if self.password:
            password = self.password
            self.password = ""
            return password
        if self.attempt >= self.retries:
            return None
        self.attempt += 1
        prompt = f"please enter the SSH password for {self.username}@{self.host}:"
        return await asyncio.to_thread(input_pass, prompt) or None


class PassphraseManager:
    """Prompt only for encrypted keys, despite AsyncSSH calling us for all keys."""

    def __call__(self, filename) -> str | None:
        if not asyncssh:
            return None
        try:
            asyncssh.read_private_key(filename)
            return None
        except asyncssh.KeyEncryptionError:
            pass
        except asyncssh.KeyImportError as e:
            message = str(e).lower()
            if "passphrase" not in message and "encrypted" not in message:
                return None
        except OSError:
            return None
        for attempt in range(1, PASSPHRASE_RETRY + 1):
            prompt = f"please enter the passphrase for:\n{filename}"
            if PASSPHRASE_RETRY > 1:
                prompt += f"\n(attempt {attempt} of {PASSPHRASE_RETRY})"
            passphrase = input_pass(prompt)
            if not passphrase:
                return None
            try:
                asyncssh.read_private_key(filename, passphrase=passphrase)
                return passphrase
            except asyncssh.KeyEncryptionError:
                continue
            except (OSError, asyncssh.KeyImportError):
                return None
        return None


def make_client_factory(host_key_manager: HostKeyManager):
    class XpraSSHClient(asyncssh.SSHClient):
        def validate_host_public_key(self, host: str, addr: str, port: int, key) -> bool:
            return host_key_manager.validate(host, addr, port, key)

        def debug_msg_received(self, msg: str, lang: str, always_display: bool) -> None:
            log("SSH debug message%s: %s", (lang, always_display), msg)

    return XpraSSHClient


def configbool(config: dict[str, Any], key: str, default_value=True) -> bool:
    return str_to_bool(config.get(key), default_value)


def get_auth_modes(config: dict[str, Any]) -> list[str]:
    auth = config.get("auth")
    if auth:
        return [mode.strip().lower() for mode in str(auth).split("+") if mode.strip()]
    return [mode.strip().lower() for mode in AUTH_MODES if mode.strip()]


def build_connection_options(display_desc: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    config = dict(display_desc.get("asyncssh-config", {}))
    # Most existing connection files use the paramiko-prefixed option name.
    config.update(display_desc.get("paramiko-config", {}))
    username = display_desc.get(f"{prefix}username", "")
    host = display_desc.get(f"{prefix}host", display_desc.get("host", ""))
    password = display_desc.get(f"{prefix}password", "")
    key = display_desc.get(f"{prefix}key", "")
    modes = get_auth_modes(config)
    public_key = any(mode in ("agent", "key", "publickey") for mode in modes)
    password_auth = "password" in modes
    verify_hostkey = configbool(config, "verify-hostkey", VERIFY_HOSTKEY)
    if display_desc.get("strict-host-check") is False:
        verify_hostkey = False

    known_hosts = None
    client_factory = None
    if verify_hostkey:
        files = get_known_hosts_files()
        try:
            known_hosts = asyncssh.read_known_hosts(files) if files else asyncssh.import_known_hosts("")
        except (OSError, ValueError) as e:
            raise InitExit(ExitCode.SSH_KEY_FAILURE, f"failed to load SSH host keys: {e}") from None
        strict = configbool(config, "stricthostkeychecking", VERIFY_STRICT)
        add_key = configbool(config, "addkey", ADD_KEY)
        verify_dns = configbool(config, "verifyhostkeydns", True)
        client_factory = make_client_factory(HostKeyManager(known_hosts, strict, add_key, verify_dns))

    options: dict[str, Any] = {
        "known_hosts": known_hosts,
        "public_key_auth": public_key,
        "password_auth": password_auth,
        "kbdint_auth": password_auth,
        "connect_timeout": TIMEOUT,
        "login_timeout": TIMEOUT,
        "agent_forwarding": configbool(config, "agent", SSH_AGENT),
    }
    if client_factory:
        options["client_factory"] = client_factory
    config_files = get_ssh_config_files()
    if config_files:
        options["config"] = config_files
    if username:
        options["username"] = username
    if password_auth:
        retries = int(config.get("numberofpasswordprompts", PASSWORD_RETRY))
        options["password"] = PasswordManager(username or get_username(), host, password, retries).get_password
    if public_key:
        options["passphrase"] = PassphraseManager()
        if key:
            options["client_keys"] = [os.path.abspath(os.path.expanduser(key))]
    else:
        options["client_keys"] = None
        options["agent_path"] = None
    if "agent" not in modes:
        options["agent_path"] = None
    return options


async def run_test_command(connection, cmd: str):
    return await connection.run(
        cmd,
        check=False,
        timeout=TEST_COMMAND_TIMEOUT,
        request_pty=False,
        x11_forwarding=False,
    )


def output_lines(result) -> list[str]:
    output = result.stdout or ""
    if isinstance(output, bytes):
        output = output.decode("utf8", "replace")
    return output.splitlines()


async def detect_os_name(connection) -> str:
    result = await run_test_command(connection, "echo %OS%")
    lines = output_lines(result)
    if result.exit_status == 0 and lines and lines[-1] != "%OS%":
        return lines[-1]
    result = await run_test_command(connection, "echo $OSTYPE")
    lines = output_lines(result)
    if result.exit_status == 0 and lines:
        return lines[-1]
    return "unknown"


async def get_install_path(connection, osname: str) -> str:
    cmd = WIN32_REGISTRY_QUERY.replace("/", "//") if osname == "msys" else WIN32_REGISTRY_QUERY
    result = await run_test_command(connection, cmd)
    if result.exit_status:
        return ""
    for line in output_lines(result):
        if match := re.search(r"InstallPath\s*\w*\s*(.*)", line):
            return match.group(1).strip()
    return ""


async def find_command(connection, find_command: str, command: str) -> str:
    result = await run_test_command(connection, f"{find_command} {command}")
    if result.exit_status:
        return ""
    for line in output_lines(result):
        line = line.strip()
        if not line or line == "OK":
            continue
        if line.startswith(f"alias {command}="):
            return line.split("=", 1)[1].strip("'")
        return line
    return ""


async def find_remote_xpra(connection, remote_xpra: Sequence[str]) -> str:
    osname = await detect_os_name(connection)

    def winpath(path: str) -> str:
        if osname == "msys":
            return path.replace("\\", "\\\\")
        if osname == "cygwin":
            return "/cygdrive/" + path.replace(":\\", "/").replace("\\", "/")
        return path

    find_command_name = ""
    for xpra_cmd in remote_xpra:
        if osname.startswith("Windows") or osname in ("msys", "cygwin"):
            if install_path := await get_install_path(connection, osname):
                return winpath(f"{install_path}\\Xpra_cmd.exe")
            if "/" not in xpra_cmd and "\\" not in xpra_cmd:
                test_path = winpath(f"{DEFAULT_WIN32_INSTALL_PATH}\\{xpra_cmd}")
                if (await run_test_command(connection, f'dir "{test_path}"')).exit_status == 0:
                    return test_path
        if not find_command_name and not osname.startswith("Windows"):
            find_command_name = "command -v"
            if (await run_test_command(connection, "command")).exit_status:
                find_command_name = "which"
        if find_command_name:
            if found := await find_command(connection, find_command_name, xpra_cmd):
                return found
        if xpra_cmd == "xpra" and osname in ("msys", "cygwin"):
            default_path = CYGWIN_DEFAULT_PATH if osname == "cygwin" else MSYS_DEFAULT_PATH
            if default_path and (await run_test_command(
                    connection, f"command -v '{default_path}'")).exit_status == 0:
                return default_path
    return ""


def build_remote_command(xpra_cmd: str, proxy_command: Sequence[str],
                         socket_dirs: Sequence[str], display_as_args: Sequence[str]) -> str:
    args = [xpra_cmd, *proxy_command]
    args += [f"--socket-dirs={socket_dir}" for socket_dir in socket_dirs]
    args += display_as_args
    return " ".join(shellquote(arg) for arg in args)


async def open_xpra_stream(connection, display_desc: dict[str, Any]):
    remote_port = int(display_desc.get("remote_port", 0))
    if remote_port:
        reader, writer = await connection.open_connection("localhost", remote_port, window=WINDOW_SIZE)
        return reader, writer, None
    remote_xpra = display_desc["remote_xpra"]
    xpra_cmd = await find_remote_xpra(connection, remote_xpra) or "xpra"
    socket_dirs = list(display_desc.get("socket_dirs", ()))
    if socket_dir := display_desc.get("socket_dir", ""):
        if socket_dir not in socket_dirs:
            socket_dirs.insert(0, socket_dir)
    cmd = build_remote_command(xpra_cmd, display_desc["proxy_command"],
                               socket_dirs, display_desc["display_as_args"])
    log("asyncssh create_process(%r)", cmd)
    process = await connection.create_process(
        cmd,
        encoding=None,
        window=WINDOW_SIZE,
        request_pty=False,
        x11_forwarding=False,
    )

    async def log_stderr() -> None:
        try:
            while line := await process.stderr.readline():
                text = line.rstrip(b"\r\n").decode("utf8", "replace")
                if text:
                    log.info(" SSH: %r", text)
        except Exception:
            log("asyncssh stderr reader", exc_info=True)

    asyncio.create_task(log_stderr())
    return process.stdout, process.stdin, process


async def do_connect(display_desc: dict[str, Any]):
    host = display_desc["host"]
    port = int(display_desc.get("port", 0))
    extra_connections = []
    options = build_connection_options(display_desc)

    async def close_extra_connections() -> None:
        for extra in reversed(extra_connections):
            extra.close()
            try:
                await extra.wait_closed()
            except Exception:
                log("closing failed asyncssh tunnel", exc_info=True)

    try:
        if "proxy_host" in display_desc:
            proxy_host = display_desc["proxy_host"]
            proxy_port = int(display_desc.get("proxy_port", 0))
            proxy_options = build_connection_options(display_desc, "proxy_")
            proxy_connection = await asyncssh.connect(proxy_host, proxy_port or (), **proxy_options)
            extra_connections.append(proxy_connection)
            options["tunnel"] = proxy_connection
        connection = await asyncssh.connect(host, port or (), **options)
        try:
            reader, writer, process = await open_xpra_stream(connection, display_desc)
        except Exception:
            connection.close()
            await connection.wait_closed()
            raise
    except asyncssh.HostKeyNotVerifiable as e:
        await close_extra_connections()
        raise InitExit(ExitCode.SSH_KEY_FAILURE, f"SSH host key verification failed: {e}") from None
    except asyncssh.PermissionDenied as e:
        await close_extra_connections()
        raise InitExit(ExitCode.SSH_FAILURE, f"SSH authentication failed for {host!r}: {e}") from None
    except (asyncio.TimeoutError, TimeoutError):
        await close_extra_connections()
        raise InitExit(ExitCode.SSH_FAILURE, f"SSH connection to {host!r} timed out") from None
    except (OSError, asyncssh.Error) as e:
        await close_extra_connections()
        raise InitExit(ExitCode.SSH_FAILURE, f"SSH connection to {host!r} failed: {e}") from None
    except Exception:
        await close_extra_connections()
        raise
    endpoint = (host, port or 22)
    info = {"host": host, "port": port or 22, "backend": "asyncssh"}
    return SSHStreamConnection(get_threaded_loop(), reader, writer, connection,
                               endpoint, info, display_desc, process, extra_connections)


def connect_to(display_desc: dict[str, Any]) -> SSHStreamConnection:
    log("asyncssh.connect_to(%s)", display_desc)
    if not asyncssh:
        raise InitExit(ExitCode.SSH_FAILURE, "asyncssh is not available")
    threaded_loop = get_threaded_loop()
    connection = threaded_loop.sync(do_connect, display_desc)
    host = display_desc["host"]
    port = int(display_desc.get("port", 0)) or 22
    username = display_desc.get("username", "") or get_username()
    display = display_desc.get("display", "")
    connection.target = host_target_string("ssh", username, host, port, display)
    if "proxy_host" in display_desc:
        proxy_host = display_desc["proxy_host"]
        proxy_port = int(display_desc.get("proxy_port", 0)) or 22
        proxy_username = display_desc.get("proxy_username", "") or get_username()
        proxy_target = host_target_string("ssh", proxy_username, proxy_host, proxy_port)
        connection.target += f" via {proxy_target}"
    connection.timeout = SOCKET_TIMEOUT
    return connection
