# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import socket
import sys
from time import sleep, monotonic
from typing import Any, NoReturn
from collections.abc import Sequence

from xpra.scripts.main import InitException, InitExit, shellquote, host_target_string
from xpra.platform.paths import get_ssh_known_hosts_files
from xpra.platform.info import get_username
from xpra.scripts.config import str_to_bool, TRUE_OPTIONS
from xpra.scripts.pinentry import input_pass, confirm
from xpra.net.ssh.util import get_default_keyfiles, LOG_EOF
from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT
from xpra.util.thread import start_thread
from xpra.exit_codes import ExitCode
from xpra.util.io import load_binary_file, stderr_print, umask_context
from xpra.common import noerr
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool, envfloat, first_time
from xpra.log import Logger

# pylint: disable=import-outside-toplevel

log = Logger("network", "ssh")
if log.is_debug_enabled():
    import logging

    logging.getLogger("paramiko").setLevel(logging.DEBUG)

from paramiko.ssh_exception import SSHException, ProxyCommandFailure, PasswordRequiredException  # noqa: E402
from paramiko.transport import Transport  # noqa: E402

WINDOW_SIZE = envint("XPRA_SSH_WINDOW_SIZE", 2 ** 27 - 1)
TIMEOUT = envint("XPRA_SSH_TIMEOUT", 60)

VERIFY_HOSTKEY = envbool("XPRA_SSH_VERIFY_HOSTKEY", True)
VERIFY_STRICT = envbool("XPRA_SSH_VERIFY_STRICT", False)
ADD_KEY = envbool("XPRA_SSH_ADD_KEY", True)
# which authentication mechanisms are enabled with paramiko:
NONE_AUTH = envbool("XPRA_SSH_NONE_AUTH", True)
PASSWORD_AUTH = envbool("XPRA_SSH_PASSWORD_AUTH", True)
AGENT_AUTH = envbool("XPRA_SSH_AGENT_AUTH", True)
KEY_AUTH = envbool("XPRA_SSH_KEY_AUTH", True)
PASSWORD_RETRY = envint("XPRA_SSH_PASSWORD_RETRY", 2)
SSH_AGENT = envbool("XPRA_SSH_AGENT", False)
BANNER = envbool("XPRA_SSH_BANNER", True)
assert PASSWORD_RETRY >= 0
LOG_FAILED_CREDENTIALS = envbool("XPRA_LOG_FAILED_CREDENTIALS", False)
TEST_COMMAND_TIMEOUT = envint("XPRA_SSH_TEST_COMMAND_TIMEOUT", 10)
EXEC_STDOUT_TIMEOUT = envfloat("XPRA_SSH_EXEC_STDOUT_TIMEOUT", 2)
EXEC_STDERR_TIMEOUT = envfloat("XPRA_SSH_EXEC_STDERR_TIMEOUT", 0)

MSYS_DEFAULT_PATH = os.environ.get("XPRA_MSYS_DEFAULT_PATH", "/mingw64/bin/xpra")
CYGWIN_DEFAULT_PATH = os.environ.get("XPRA_CYGWIN_DEFAULT_PATH", "/cygdrive/c/Program Files/Xpra/Xpra_cmd.exe")
DEFAULT_WIN32_INSTALL_PATH = "C:\\Program Files\\Xpra"
WIN_OPENSSH_AGENT = envbool("XPRA_WIN_OPENSSH_AGENT", False)
WIN_OPENSSH_AGENT_MODULE = "win_openssh.OpenSSHAgentConnection"

PARAMIKO_SESSION_LOST = "No existing session"

WIN32_REGISTRY_QUERY = "REG QUERY \"HKEY_LOCAL_MACHINE\\Software\\Xpra\" /v InstallPath"

AUTH_MODES: Sequence[str] = ("none", "agent", "key", "password")


def keymd5(k) -> str:
    import binascii
    f = binascii.hexlify(k.get_fingerprint()).decode("latin1")
    s = "MD5"
    while f:
        s += ":" + f[:2]
        f = f[2:]
    return s


if BANNER:
    from paramiko import auth_handler

    class AuthHandlerOverride(auth_handler.AuthHandler):

        def _parse_userauth_banner(self, m):
            banner = m.get_string()
            self.banner = banner
            if banner:
                try:
                    text = banner.decode("utf8")
                except UnicodeDecodeError:
                    text = repr(banner)
                log.info("SSH Authentication Banner:")
                for msg in text.splitlines():
                    log.info(f" {msg!r}")

    auth_handler.AuthHandler = AuthHandlerOverride
    from paramiko import transport
    transport.AuthHandler = AuthHandlerOverride


class SSHSocketConnection(SocketConnection):

    def __init__(self, ssh_channel, sock, sockname: str | tuple | list,
                 peername, target, info=None, socket_options=None):
        self._raw_socket = sock
        super().__init__(ssh_channel, sockname, peername, target, "ssh", info, socket_options)

    def get_raw_socket(self):
        return self._raw_socket

    def start_stderr_reader(self) -> None:
        start_thread(self._stderr_reader, "ssh-stderr-reader", daemon=True)

    def _stderr_reader(self) -> None:
        chan = self._socket
        stderr = chan.makefile_stderr("rb", 1)
        while self.active:
            v = stderr.readline()
            if not v:
                if LOG_EOF and self.active:
                    log.info("SSH EOF on stderr of %s", chan.get_name())
                break
            s = v.rstrip(b"\n\r").decode()
            if s:
                log.info(" SSH: %r", s)

    def peek(self, n) -> bytes:
        if not self._raw_socket:
            return b""
        return self._raw_socket.recv(n, socket.MSG_PEEK)

    def get_socket_info(self) -> dict[str, Any]:
        if not self._raw_socket:
            return {}
        return self.do_get_socket_info(self._raw_socket)

    def get_info(self) -> dict[str, Any]:
        i = super().get_info()
        s = self._socket
        if s:
            i["ssh-channel"] = {
                "id": s.get_id(),
                "name": s.get_name(),
            }
        return i


class SSHProxyCommandConnection(SSHSocketConnection):
    def __init__(self, ssh_channel, peername, target, info):
        super().__init__(ssh_channel, None, "", peername, target, info)
        self.process = None

    def error_is_closed(self, e) -> bool:
        p = self.process
        if p:
            # if the process has terminated,
            # then the connection must be closed:
            if p[0].poll() is not None:
                return True
        return super().error_is_closed(e)

    def get_socket_info(self) -> dict[str, Any]:
        p = self.process
        if not p:
            return {}
        proc, _ssh, cmd = p
        return {
            "process": {
                "pid": proc.pid,
                "returncode": proc.returncode,
                "command": cmd,
            }
        }

    def close(self) -> None:
        try:
            super().close()
        except OSError:
            # this can happen if the proxy command gets a SIGINT,
            # it's closed already and we don't care
            log("SSHProxyCommandConnection.close()", exc_info=True)


def safe_lookup(config_obj, hostname: str) -> dict:
    try:
        _lookup = getattr(config_obj, "_lookup", None)
        import paramiko
        # older versions don't have the same signature for `_lookup`:
        if _lookup and getattr(paramiko, "__version_info__", (0, )) >= (3, 3):
            # completely duplicate the paramiko logic since they're unwilling to merge a trivial change :(
            options = _lookup(hostname=hostname)
            # Inject HostName if it was not set (this used to be done incidentally
            # during tokenization, for some reason).
            if "hostname" not in options:
                options["hostname"] = hostname
            # Handle canonicalization
            canon = options.get("canonicalizehostname", None) in ("yes", "always")
            maxdots = int(options.get("canonicalizemaxdots", 1))
            if canon and hostname.count(".") <= maxdots:
                # NOTE: OpenSSH manpage does not explicitly state this, but its
                # implementation for CanonicalDomains is 'split on any whitespace'.
                domains = options.get("canonicaldomains", "").split()
                hostname = config_obj.canonicalize(hostname, options, domains)
                # Overwrite HostName again here (this is also what OpenSSH does)
                options["hostname"] = hostname
                options = _lookup(
                    hostname, options, canonical=True, final=True
                )
            else:
                options = _lookup(
                    hostname, options, canonical=False, final=True
                )
        else:
            options = config_obj.lookup(hostname)
        return dict(options or {})
    except ImportError as e:
        log("%s.lookup(%s)", config_obj, hostname, exc_info=True)
        log.warn(f"Warning: unable to load SSH host config for {hostname!r}:")
        log.warn(f" {e}")
        if isinstance(e, ModuleNotFoundError):
            log.warn(" (looks like a 'paramiko' distribution packaging issue)")
    except KeyError as e:
        log("%s.lookup(%s)", config_obj, hostname, exc_info=True)
        log.info(f"paramiko ssh config lookup error for host {hostname!r}")
        if first_time("paramiko-#2338"):
            log.info(" %s: %s", type(e), e)
            log.info(" the paramiko project looks unmaintained:")
            log.info(" https://github.com/paramiko/paramiko/pull/2338")
    return {}


def connect_to(display_desc: dict) -> SSHSocketConnection:
    log(f"connect_to({display_desc})")
    # plain socket attributes:
    host: str = display_desc["host"]
    port: int = display_desc.get("port", 22)
    peername: tuple[str, int] | tuple[str, int, int, int] = (host, port)
    # ssh and command attributes:
    username: str = display_desc.get("username") or get_username()
    if "proxy_host" in display_desc:
        display_desc.setdefault("proxy_username", get_username())
    password: str = display_desc.get("password", "")
    remote_xpra = display_desc["remote_xpra"]
    proxy_command = display_desc["proxy_command"]  # ie: "_proxy_start"
    socket_dir: str = display_desc.get("socket_dir", "")
    display: str = display_desc.get("display", "")
    display_as_args: list[str] = display_desc["display_as_args"]  # ie: "--start=xterm :10"
    paramiko_config: dict = display_desc.copy()
    paramiko_config.update(display_desc.get("paramiko-config", {}))
    socket_info: dict[str, Any] = {
        "host": host,
        "port": port,
    }

    def fail(msg: str) -> NoReturn:
        log("connect_to(%s)", display_desc, exc_info=True)
        raise InitExit(ExitCode.SSH_FAILURE, msg) from None

    from paramiko import SSHConfig, ProxyCommand
    ssh_config = SSHConfig()

    etc = "etc" if sys.prefix == "/usr" else sys.prefix + "/etc"
    for config_file in (
            f"{etc}/ssh/ssh_config",
            os.path.expanduser("~/.ssh/config"),
    ):
        if not os.path.exists(config_file):
            continue
        with open(config_file, encoding="utf8") as f:
            try:
                ssh_config.parse(f)
            except Exception as e:
                log(f"parse({config_file})", exc_info=True)
                log.error(f"Error parsing {config_file!r}:")
                log.estr(e)
        log(f"parsed ssh config {config_file!r}")
    try:
        log("%i hosts found", len(ssh_config.get_hostnames()))
    except KeyError:
        pass

    def ssh_lookup(key) -> dict:
        return safe_lookup(ssh_config, key)

    host_config: dict = ssh_lookup("*")
    host_config.update(ssh_lookup(host))
    log(f"host_config({host})={host_config}")

    def get_keyfiles(config_name="key") -> list[str]:
        keyfiles = host_config.get("identityfile") or get_default_keyfiles()
        keyfile = paramiko_config.get(config_name)
        if keyfile:
            keyfiles.insert(0, keyfile)
        return keyfiles

    if host_config:
        # paramiko does not strip comments from configs:
        # https://github.com/Xpra-org/xpra/issues/4503
        def safeget(key: str, default_value: str | int) -> Any:
            value = host_config.get(key, default_value)
            if isinstance(value, str):
                value = value.split("#", 1)[0]
            return value
        log(f"got host config for {host!r}: {host_config}")
        host = safeget("hostname", host)
        username = safeget("user", username)
        port = safeget("port", port)
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise InitExit(ExitCode.SSH_FAILURE, f"invalid ssh port specified: {port!r}") from None
        proxycommand = host_config.get("proxycommand")
        if proxycommand:
            log(f"found proxycommand={proxycommand!r} for host {host!r}")
            sock = ProxyCommand(proxycommand)
            log(f"ProxyCommand({proxycommand})={sock}")
            from xpra.util.child_reaper import getChildReaper
            cmd = getattr(sock, "cmd", [])

            def proxycommand_ended(proc):
                log(f"proxycommand_ended({proc}) exit code={proc.poll()}")

            getChildReaper().add_process(sock.process, "paramiko-ssh-client", cmd, True, True,
                                         callback=proxycommand_ended)
            proxy_keys = get_keyfiles("proxy_key")
            log(f"{proxy_keys=}")
            from paramiko.client import SSHClient
            ssh_client = SSHClient()
            ssh_client.load_system_host_keys()
            log("ssh proxy command connect to %s", (host, port, sock))
            ssh_client.connect(host, port, sock=sock)
            transport = ssh_client.get_transport()
            do_connect_to(transport, host,
                          username, password,
                          host_config,
                          proxy_keys,
                          paramiko_config)
            chan = run_remote_xpra(transport, proxy_command, remote_xpra, socket_dir, display_as_args)
            peername = (host, port)
            conn = SSHProxyCommandConnection(chan, peername, peername, socket_info)
            conn.target = host_target_string("ssh", username, host, port, display)
            conn.timeout = SOCKET_TIMEOUT
            conn.start_stderr_reader()
            conn.process = (sock.process, "ssh", cmd)
            from xpra.net import bytestreams
            bytestreams.CLOSED_EXCEPTIONS = tuple(list(bytestreams.CLOSED_EXCEPTIONS) + [ProxyCommandFailure])
            return conn

    keys = get_keyfiles()
    from xpra.net.socket_util import socket_connect
    if "proxy_host" in display_desc:
        proxy_host = display_desc["proxy_host"]
        proxy_port = int(display_desc.get("proxy_port", 22))
        proxy_username = display_desc.get("proxy_username", username)
        proxy_password = display_desc.get("proxy_password", password)
        proxy_keys = get_keyfiles("proxy_key")
        sock = socket_connect(proxy_host, proxy_port)
        if not sock:
            fail(f"SSH proxy transport failed to connect to {proxy_host}:{proxy_port}")
        middle_transport = do_connect(sock, proxy_host,
                                      proxy_username, proxy_password,
                                      ssh_lookup(host) or ssh_lookup("*"),
                                      proxy_keys,
                                      paramiko_config)
        log("Opening proxy channel")
        chan_to_middle = middle_transport.open_channel("direct-tcpip", (host, port), ("localhost", 0))
        transport = do_connect(chan_to_middle, host,
                               username, password,
                               host_config,
                               keys,
                               paramiko_config)
        chan = run_remote_xpra(transport, proxy_command, remote_xpra, socket_dir, display_as_args)
        conn = SSHProxyCommandConnection(chan, peername, peername, socket_info)
        to_str = host_target_string("ssh", username, host, port, display)
        proxy_str = host_target_string("ssh", proxy_username, proxy_host, proxy_port)
        conn.target = f"{to_str} via {proxy_str}"
        conn.timeout = SOCKET_TIMEOUT
        conn.start_stderr_reader()
        return conn

    # plain TCP connection to the server,
    # we open it then give the socket to paramiko:
    auth_modes = get_auth_modes(paramiko_config, host_config, password)
    log(f"authentication modes={auth_modes}")
    sock = None
    transport = None
    sockname = host
    while not transport:
        sock = socket_connect(host, port)
        if not sock:
            fail(f"SSH failed to connect to {host}:{port}")
        sockname = sock.getsockname()
        peername = sock.getpeername()
        log(f"paramiko socket_connect: sockname={sockname}, peername={peername}")
        try:
            transport = do_connect(sock, host, username, password,
                                   host_config,
                                   keys,
                                   paramiko_config,
                                   auth_modes)
        except SSHAuthenticationError as e:
            log(f"paramiko authentication errors on socket {sock} with modes {auth_modes}: {e.errors}",
                exc_info=True)
            pw_errors = []
            for errs in e.errors.values():
                pw_errors += errs
            if ("key" in auth_modes or "agent" in auth_modes) and PARAMIKO_SESSION_LOST in pw_errors:
                # try connecting again but without 'key' and 'agent' authentication:
                # see https://github.com/Xpra-org/xpra/issues/3223
                for m in ("key", "agent"):
                    try:
                        auth_modes.remove(m)
                    except KeyError:
                        pass
                log.info(f"retrying SSH authentication with modes {csv(auth_modes)}")
                continue
            raise
        finally:
            if sock and not transport:
                noerr(sock.shutdown)
                noerr(sock.close)
                sock = None

    remote_port: int = display_desc.get("remote_port", 0)
    if remote_port:
        # we want to connect directly to a remote port,
        # we don't need to run a command
        chan = transport.open_channel("direct-tcpip", ("localhost", remote_port), ('localhost', 0))
        log(f"direct channel to remote port {remote_port} : {chan}")
    else:
        chan = run_remote_xpra(transport, proxy_command, remote_xpra,
                               socket_dir, display_as_args, paramiko_config)
    conn = SSHSocketConnection(chan, sock, sockname, peername, (host, port), socket_info)
    conn.target = host_target_string("ssh", username, host, port, display)
    conn.timeout = SOCKET_TIMEOUT
    conn.start_stderr_reader()
    log(f"paramiko_client.connect_to({display_desc})={conn}")
    return conn


def get_auth_modes(paramiko_config, host_config: dict, password: str) -> list[str]:
    def configvalue(key: str):
        # if the paramiko config has a setting, honour it:
        if paramiko_config and key in paramiko_config:
            return paramiko_config.get(key)
        # fallback to the value from the host config:
        return host_config.get(key)

    def configbool(key: str, default_value=True) -> bool:
        return str_to_bool(configvalue(key), default_value)

    auth_str = configvalue("auth")
    if auth_str:
        return auth_str.split("+")
    auth = []
    if configbool("noneauthentication", NONE_AUTH):
        auth.append("none")
    if password and configbool("passwordauthentication", PASSWORD_AUTH):
        auth.append("password")
    if configbool("agentauthentication", AGENT_AUTH):
        auth.append("agent")
    # Some people do two-factor using KEY_AUTH to kick things off, so this happens first
    if configbool("keyauthentication", KEY_AUTH):
        auth.append("key")
    if not password and configbool("passwordauthentication", PASSWORD_AUTH):
        auth.append("password")
    return auth


class IAuthHandler:
    def __init__(self, password):
        self.authcount = 0
        self.password = password

    def handle_request(self, title: str, instructions, prompt_list) -> list:
        log("handle_request%s counter=%i", (title, instructions, prompt_list), self.authcount)
        p = []
        for pent in prompt_list:
            if self.password:
                p.append(self.password)
                self.password = None
            else:
                p.append(input_pass(pent[0]))
        self.authcount += 1
        log(f"handle_request(..) returning {len(p)} values")
        return p


def do_connect(chan, host: str, username: str, password: str,
               host_config: dict, keyfiles: list[str], paramiko_config: dict, auth_modes=AUTH_MODES):
    transport = Transport(chan)
    transport.use_compression(False)
    log("SSH transport %s", transport)
    try:
        transport.start_client()
    except SSHException as e:
        log("SSH negotiation failed", exc_info=True)
        raise InitExit(ExitCode.SSH_FAILURE, "SSH negotiation failed: %s" % e) from None
    return do_connect_to(transport, host, username, password,
                         host_config, keyfiles, paramiko_config, auth_modes)


def do_connect_to(transport, host: str, username: str, password: str,
                  host_config=None, keyfiles=None, paramiko_config=None, auth_modes=AUTH_MODES):
    log("do_connect_to%s", (transport, host, username, password, host_config, keyfiles, paramiko_config))

    def configvalue(key: str) -> Any:
        # if the paramiko config has a setting, honour it:
        if paramiko_config and key in paramiko_config:
            return paramiko_config.get(key)
        # fallback to the value from the host config:
        return (host_config or {}).get(key)

    def configbool(key: str, default_value=True) -> bool:
        return str_to_bool(configvalue(key), default_value)

    def configint(key: str, default_value=0) -> int:
        v = configvalue(key)
        if v is None:
            return default_value
        return int(v)

    host_key = transport.get_remote_server_key()
    assert host_key, "no remote server key"
    log("remote_server_key=%s", keymd5(host_key))
    if configbool("verify-hostkey", VERIFY_HOSTKEY):
        from paramiko.hostkeys import HostKeys
        host_keys = HostKeys()
        host_keys_filename = None
        known_hosts_files = get_ssh_known_hosts_files()
        for known_hosts in known_hosts_files:
            host_keys.clear()
            try:
                path = os.path.expanduser(known_hosts)
                if os.path.exists(path):
                    host_keys.load(path)
                    log("HostKeys.load(%s) successful", path)
                    host_keys_filename = path
                    break
            except OSError:
                log("HostKeys.load(%s)", known_hosts, exc_info=True)

        log("host keys=%s", host_keys)
        keys = safe_lookup(host_keys, host)
        known_host_key = keys.get(host_key.get_name())

        def keyname():
            return host_key.get_name().replace("ssh-", "")

        if known_host_key and host_key == known_host_key:
            assert host_key
            log("%s host key '%s' OK for host '%s'", keyname(), keymd5(host_key), host)
        else:
            dnscheck = ""
            if configbool("verifyhostkeydns"):
                try:
                    from xpra.net.ssh.sshfp import check_host_key
                    dnscheck = check_host_key(host, host_key)
                except ImportError as e:
                    log("verifyhostkeydns failed", exc_info=True)
                    log.info("cannot check SSHFP DNS records")
                    log.info(" %s", e)
            log("dnscheck=%s", dnscheck)

            def adddnscheckinfo(q: list[str]):
                if dnscheck is not True:
                    if dnscheck:
                        q.append("SSHFP validation failed:")
                        q.append(str(dnscheck))
                    else:
                        q.append("SSHFP validation failed")

            if dnscheck is True:
                # DNSSEC provided a matching record
                log.info("found a valid SSHFP record for host %s", host)
            elif known_host_key:
                log.warn("Warning: SSH server key mismatch")
                qinfo: list[str] = [
                    "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!",
                    "IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!",
                    "Someone could be eavesdropping on you right now (man-in-the-middle attack)!",
                    "It is also possible that a host key has just been changed.",
                    f"The fingerprint for the {keyname()} key sent by the remote host is",
                    keymd5(host_key),
                ]
                adddnscheckinfo(qinfo)
                if configbool("stricthostkeychecking", VERIFY_STRICT):
                    log.warn("Host key verification failed.")
                    # TODO: show alert with no option to accept key
                    qinfo += [
                        "Please contact your system administrator.",
                        "Add correct host key in %s to get rid of this message.",
                        f"Offending {keyname()} key in {host_keys_filename}",
                        f"ECDSA host key for {keyname()} has changed and you have requested strict checking.",
                    ]
                    stderr_print(os.linesep.join(qinfo))
                    transport.close()
                    raise InitExit(ExitCode.SSH_KEY_FAILURE, "SSH Host key has changed")
                if not confirm(qinfo):
                    transport.close()
                    raise InitExit(ExitCode.SSH_KEY_FAILURE, "SSH Host key has changed")
                log.info("host key confirmed")
            else:
                assert (not keys) or (host_key.get_name() not in keys)
                if not keys:
                    log.warn("Warning: unknown SSH host '%s'", host)
                else:
                    log.warn("Warning: unknown %s SSH host key", keyname())
                qinfo = [
                    f"The authenticity of host {host!r} can't be established.",
                    f"{keyname()} key fingerprint is",
                    keymd5(host_key),
                ]
                adddnscheckinfo(qinfo)
                if not confirm(qinfo):
                    transport.close()
                    raise InitExit(ExitCode.SSH_KEY_FAILURE, f"Unknown SSH host {host!r}")
                log.info("host key confirmed")
            if configbool("addkey", ADD_KEY) and known_hosts_files:
                try:
                    if not host_keys_filename:
                        # the first one is the default,
                        # ie: ~/.ssh/known_hosts on posix
                        host_keys_filename = os.path.expanduser(known_hosts_files[0])
                    log(f"adding {keyname()} key for host {host!r} to {host_keys_filename!r}")
                    if not os.path.exists(host_keys_filename):
                        keys_dir = os.path.dirname(host_keys_filename)
                        if not os.path.exists(keys_dir):
                            log(f"creating keys directory {keys_dir!r}")
                            os.mkdir(keys_dir, 0o700)
                        elif not os.path.isdir(keys_dir):
                            log.warn(f"Warning: {keys_dir!r} is not a directory")
                            log.warn(" key not saved")
                        if os.path.exists(keys_dir) and os.path.isdir(keys_dir):
                            log(f"creating known host file {host_keys_filename!r}")
                            with umask_context(0o133):
                                with open(host_keys_filename, "ab+"):
                                    "file has been created"
                    host_keys.add(host, host_key.get_name(), host_key)
                    host_keys.save(host_keys_filename)
                except OSError as e:
                    log(f"failed to add key to {host_keys_filename!r}")
                    log.error(f"Error adding key to {host_keys_filename!r}")
                    log.error(f" {e}")
                except Exception:
                    log.error("cannot add key", exc_info=True)
    else:
        log("ssh host key verification skipped")

    auth_errors: dict[str, list[str]] = {}

    def auth_agent() -> None:
        from paramiko.agent import Agent
        agent = Agent()
        agent_keys = agent.get_keys()
        log("agent keys: %s", agent_keys)
        if agent_keys:
            for agent_key in agent_keys:
                log("trying ssh-agent key '%s'", keymd5(agent_key))
                try:
                    transport.auth_publickey(username, agent_key)
                    log("tried ssh-agent key '%s'", keymd5(agent_key))
                    if transport.is_authenticated():
                        log("authenticated using agent and key '%s'", keymd5(agent_key))
                        return
                except AttributeError as e:
                    log(f"auth_publickey({username}, {agent_key})")
                    log.warn("Warning: paramiko bug during public key agent authentication")
                    log.warn(f" {type(e)}: {e}")
                    log.warn(f" using key {type(agent_key)}: {agent_key}")
                except SSHException as e:
                    auth_errors.setdefault("agent", []).append(str(e))
                    log.info("SSH agent key '%s' rejected for user '%s'", keymd5(agent_key), username)
                    log("%s%s", transport.auth_publickey, (username, agent_key), exc_info=True)
                    if str(e) == PARAMIKO_SESSION_LOST:
                        # no point in trying more keys
                        break
            if not transport.is_authenticated():
                log.info("agent authentication failed, tried %i keys", len(agent_keys))

    def auth_publickey() -> None:
        log(f"trying public key authentication using {keyfiles}")
        for keyfile_path in keyfiles:
            if not os.path.exists(keyfile_path):
                log(f"no keyfile at {keyfile_path!r}")
                continue
            log(f"trying {keyfile_path!r}")
            key = None
            import paramiko
            try_key_formats: Sequence[str] = ()
            for kf in ("RSA", "DSS", "ECDSA", "Ed25519"):
                if keyfile_path.lower().endswith(kf.lower()):
                    try_key_formats = (kf,)
                    break
            if not try_key_formats:
                try_key_formats = ("RSA", "DSS", "ECDSA", "Ed25519")
            pkey_classname = None
            for pkey_classname in try_key_formats:
                pkey_class = getattr(paramiko, f"{pkey_classname}Key", None)
                if pkey_class is None:
                    log(f"no {pkey_classname} key type")
                    continue
                log(f"trying to load as {pkey_classname}")
                key = None
                try:
                    key = pkey_class.from_private_key_file(keyfile_path)
                    log.info(f"loaded {pkey_classname} private key from {keyfile_path!r}")
                    break
                except PasswordRequiredException as e:
                    log(f"{keyfile_path!r} keyfile requires a passphrase: {e}")
                    passphrase = input_pass(f"please enter the passphrase for {keyfile_path!r}")
                    if passphrase:
                        try:
                            key = pkey_class.from_private_key_file(keyfile_path, passphrase)
                            log.info(f"loaded {pkey_classname} private key from {keyfile_path!r}")
                        except SSHException as ke:
                            log("from_private_key_file", exc_info=True)
                            log.info(f"cannot load key from file {keyfile_path}:")
                            for emsg in str(ke).split(". "):
                                if emsg.startswith("('"):
                                    emsg = emsg[2:]
                                if emsg.endswith(")."):
                                    emsg = emsg[:-2]
                                if emsg:
                                    log.info(" %s.", emsg)
                    break
                except Exception:
                    log(f"auth_publickey() loading as {pkey_classname}", exc_info=True)
                    key_data = load_binary_file(keyfile_path)
                    if key_data and key_data.find(b"BEGIN OPENSSH PRIVATE KEY") >= 0:
                        log(" (OpenSSH private key file)")
            if key:
                log(f"auth_publickey using {keyfile_path!r} as {pkey_classname}: {keymd5(key)}")
                try:
                    transport.auth_publickey(username, key)
                except SSHException as e:
                    auth_errors.setdefault("key", []).append(str(e))
                    log(f"key {keyfile_path!r} rejected", exc_info=True)
                    log.info(f"SSH authentication using key {keyfile_path!r} failed:")
                    log.info(f" {e}")
                    if str(e) == PARAMIKO_SESSION_LOST:
                        # no point in trying more keys
                        break
                else:
                    if transport.is_authenticated():
                        break
            else:
                log.error(f"Error: cannot load private key {keyfile_path!r}")

    def auth_none() -> None:
        log("trying none authentication")
        try:
            transport.auth_none(username)
        except SSHException as e:
            auth_errors.setdefault("none", []).append(str(e))
            log("auth_none()", exc_info=True)

    def auth_password() -> None:
        log("trying password authentication")
        try:
            transport.auth_password(username, password)
        except SSHException as authe:
            estr = getattr(authe, "message", str(authe))
            auth_errors.setdefault("password", []).append(estr)
            log("auth_password(..)", exc_info=True)
            emsgs = estr.split(";")
        else:
            emsgs = []
        if not transport.is_authenticated():
            log.info("SSH password authentication failed:")
            for emsg in emsgs:
                log.info(f" {emsg}")
            if log.is_debug_enabled() and LOG_FAILED_CREDENTIALS:
                log.info(f" invalid username {username!r} or password {password!r}")

    def auth_interactive() -> None:
        log("trying interactive authentication")
        try:
            iauthhandler = IAuthHandler(password)
            transport.auth_interactive(username, iauthhandler.handle_request, "")
        except SSHException as authe:
            estr = getattr(authe, "message", str(authe))
            auth_errors.setdefault("interactive", []).append(estr)
            log("auth_interactive(..)", exc_info=True)
            log.info("SSH password authentication failed:")
            for emsg in getattr(authe, "message", estr).split(";"):
                log.info(f" {emsg}")

    banner = transport.get_banner()
    if banner:
        log.info("SSH server banner:")
        for x in banner.splitlines():
            log.info(f" {x}")

    log(f"starting authentication, authentication methods: {auth_modes}")
    auth = list(auth_modes)
    # per the RFC we probably should do none first always and read off the supported
    # methods, however, the current code seems to work fine with OpenSSH
    while not transport.is_authenticated() and auth:
        a = auth.pop(0)
        log("auth=%s", a)
        if a == "none":
            auth_none()
        elif a == "agent":
            auth_agent()
        elif a == "key":
            auth_publickey()
        elif a == "password":
            auth_interactive()
            if not transport.is_authenticated():
                if password:
                    auth_password()
                else:
                    tries = configint("numberofpasswordprompts", PASSWORD_RETRY)
                    for _ in range(tries):
                        password = input_pass(f"please enter the SSH password for {username}@{host}")
                        if not password:
                            break
                        auth_password()
                        if transport.is_authenticated():
                            break
        else:
            log.warn(f"Warning: invalid authentication mechanism {a}")
        # detect session-lost problems:
        # (no point in continuing without a session)
        if auth_errors and not transport.is_authenticated():
            for err_strs in auth_errors.values():
                if PARAMIKO_SESSION_LOST in err_strs:
                    raise SSHAuthenticationError(host, auth_errors)
    if not transport.is_authenticated():
        transport.close()
        log(f"authentication errors: {auth_errors}")
        raise SSHAuthenticationError(host, auth_errors)
    return transport


class SSHAuthenticationError(InitExit):
    def __init__(self, host, errors):
        super().__init__(ExitCode.CONNECTION_FAILED, f"SSH Authentication failed for {host!r}")
        self.errors = errors


def run_test_command(transport, cmd: str) -> tuple[list[str], list[str], int]:
    log(f"run_test_command(transport, {cmd})")
    try:
        chan = transport.open_session(window_size=None, max_packet_size=0, timeout=60)
        chan.set_name(f"run-test:{cmd}")
    except SSHException as e:
        log("open_session", exc_info=True)
        raise InitExit(ExitCode.SSH_FAILURE, f"failed to open SSH session: {e}") from None
    chan.exec_command(cmd)
    log(f"exec_command({cmd!r}) returned")
    start = monotonic()
    while not chan.exit_status_ready():
        if monotonic() - start > TEST_COMMAND_TIMEOUT:
            chan.close()
            raise InitException(f"SSH test command {cmd!r} timed out")
        log("exit status is not ready yet, sleeping")
        sleep(0.01)
    code = chan.recv_exit_status()
    log(f"exec_command({cmd!r})={code}")

    def chan_read(fileobj) -> list[str]:
        try:
            return fileobj.readlines()
        except OSError:
            log(f"chan_read({fileobj})", exc_info=True)
            return []
        finally:
            noerr(fileobj.close)

    # don't wait too long for the data:
    chan.settimeout(EXEC_STDOUT_TIMEOUT)
    out = chan_read(chan.makefile())
    log(f"exec_command out={out!r}")
    chan.settimeout(EXEC_STDERR_TIMEOUT)
    err = chan_read(chan.makefile_stderr())
    log(f"exec_command err={err!r}")
    chan.close()
    return out, err, code


def run_remote_xpra(transport, xpra_proxy_command=None, remote_xpra=None,
                    socket_dir=None, display_as_args=None, paramiko_config=None):
    log("run_remote_xpra%s", (transport, xpra_proxy_command, remote_xpra,
                              socket_dir, display_as_args, paramiko_config))
    assert remote_xpra
    log(f"will try to run xpra from: {remote_xpra}")

    def rtc(cmd: str) -> tuple[list[str], list[str], int]:
        return run_test_command(transport, cmd)

    def detectosname() -> str:
        # first, try a syntax that should work with any ssh server:
        r = rtc("echo %OS%")
        if r[2] == 0 and r[0]:
            name = r[0][-1].rstrip("\n\r")
            log(f"echo %OS%={name!r}")
            if name != "%OS%":
                # MS Windows OS will return "Windows_NT" here
                log.info(f"ssh server OS is {name!r}")
                return name
        # this should work on all other OSes:
        r = rtc("echo $OSTYPE")
        if r[2] == 0 and r[0]:
            name = r[0][-1].rstrip("\n\r")
            log(f"OSTYPE={name!r}")
            log.info(f"ssh server OS is {name!r}")
            return name
        return "unknown"

    def getexeinstallpath():
        cmd = WIN32_REGISTRY_QUERY
        if osname == "msys":
            # escape for msys shell:
            cmd = cmd.replace("/", "//")
        r = rtc(cmd)
        if r[2] != 0:
            return None
        out = r[0]
        for line in out:
            qmatch = re.search(r"InstallPath\s*\w*\s*(.*)", line)
            if qmatch:
                return qmatch.group(1).rstrip("\n\r")
        return None

    osname = detectosname()
    tried = set()
    find_command = None
    for xpra_cmd in remote_xpra:
        found = False
        if osname.startswith("Windows") or osname in ("msys", "cygwin"):
            # on MS Windows,
            # always prefer the application path found in the registry:
            def winpath(p) -> str:
                if osname == "msys":
                    return p.replace("\\", "\\\\")
                if osname == "cygwin":
                    return "/cygdrive/" + p.replace(":\\", "/").replace("\\", "/")
                return p

            installpath = getexeinstallpath()
            if installpath:
                xpra_cmd = winpath(f"{installpath}\\Xpra_cmd.exe")
                found = True
            elif xpra_cmd.find("/") < 0 and xpra_cmd.find("\\") < 0:
                test_path = winpath(f"{DEFAULT_WIN32_INSTALL_PATH}\\{xpra_cmd}")
                cmd = f'dir "{test_path}"'
                r = rtc(cmd)
                if r[2] == 0:
                    xpra_cmd = test_path
                    found = True
        if not found and not find_command and not osname.startswith("Windows"):
            if rtc("command")[2] == 0:
                find_command = "command -v"
            else:
                find_command = "which"
        if not found and find_command:
            r = rtc(f"{find_command} {xpra_cmd}")
            out = r[0]
            if r[2] == 0 and out:
                # use the actual path returned by 'command -v' or 'which':
                try:
                    xpra_cmd = out[-1].rstrip("\n\r ").lstrip("\t ")
                except Exception as e:
                    log(f"cannot get command from {xpra_cmd}: {e}")
                else:
                    if xpra_cmd.startswith(f"alias {xpra_cmd}="):
                        # ie: "alias xpra='xpra -d proxy'" -> "xpra -d proxy"
                        xpra_cmd = xpra_cmd.split("=", 1)[1].strip("'")
                    found = bool(xpra_cmd)
            elif xpra_cmd == "xpra" and osname in ("msys", "cygwin"):
                default_path = CYGWIN_DEFAULT_PATH if osname == "cygwin" else MSYS_DEFAULT_PATH
                if default_path:
                    # try the default system installation path
                    r = rtc(f"command -v '{default_path}'")
                    if r[2] == 0:
                        xpra_cmd = default_path  # ie: "/mingw64/bin/xpra"
                        found = True
        if not found or xpra_cmd in tried:
            continue
        log(f"adding {xpra_cmd=!r}")
        tried.add(xpra_cmd)
        cmd = '"' + xpra_cmd + '" ' + ' '.join(shellquote(x) for x in xpra_proxy_command)
        if socket_dir:
            cmd += f" \"--socket-dir={socket_dir}\""
        if display_as_args:
            cmd += " "
            cmd += " ".join(shellquote(x) for x in display_as_args)
        log(f"cmd({xpra_proxy_command}, {display_as_args})={cmd}")

        # see https://github.com/paramiko/paramiko/issues/175
        # WINDOW_SIZE = 2097152
        log(f"trying to open SSH session, window-size={WINDOW_SIZE}, timeout={TIMEOUT}")
        try:
            chan = transport.open_session(window_size=WINDOW_SIZE, max_packet_size=0, timeout=TIMEOUT)
            chan.set_name("run-xpra")
        except SSHException as e:
            log("open_session", exc_info=True)
            raise InitExit(ExitCode.SSH_FAILURE, f"failed to open SSH session: {e}") from None
        agent_option = str((paramiko_config or {}).get("agent", SSH_AGENT)) or "no"
        log(f"paramiko {agent_option=}")
        if agent_option.lower() in TRUE_OPTIONS:
            if not WIN_OPENSSH_AGENT and WIN_OPENSSH_AGENT_MODULE not in sys.modules:
                log(f"preventing {WIN_OPENSSH_AGENT_MODULE!r} from loading")
                sys.modules[WIN_OPENSSH_AGENT_MODULE] = None
            log.info("paramiko SSH agent forwarding enabled")
            from paramiko.agent import AgentRequestHandler
            AgentRequestHandler(chan)
        log(f"channel exec_command({cmd!r})")
        chan.exec_command(cmd)
        log("exec_command sent, returning channel for service")
        return chan
    raise RuntimeError("all SSH remote proxy commands have failed - is xpra installed on the remote host?")
