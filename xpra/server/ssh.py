# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import shlex
import socket
import base64
import hashlib
import binascii
from typing import Any
from subprocess import Popen, PIPE
from threading import Event
from collections.abc import Callable, Sequence
import paramiko

from xpra.net.bytestreams import pretty_socket
from xpra.util.str_fn import csv, decode_str
from xpra.util.env import envint, osexpand, first_time
from xpra.os_util import getuid, WIN32, POSIX
from xpra.util.thread import start_thread
from xpra.util.parsing import str_to_bool
from xpra.common import SSH_AGENT_DISPATCH, SizedBuffer, BACKWARDS_COMPATIBLE
from xpra.platform.paths import get_ssh_conf_dirs, get_xpra_command, get_app_dir
from xpra.log import Logger

log = Logger("network", "ssh")

BANNER = os.environ.get("XPRA_SSH_BANNER", "Xpra SSH Server")
SERVER_WAIT = envint("XPRA_SSH_SERVER_WAIT", 20)
AUTHORIZED_KEYS = "~/.ssh/authorized_keys"
AUTHORIZED_KEYS_HASHES = os.environ.get("XPRA_AUTHORIZED_KEYS_HASHES",
                                        "md5,sha1,sha224,sha256,sha384,sha512").split(",")


def get_keyclass(keytype: str):
    if not keytype:
        return None
    # 'dsa' -> 'DSS'
    if keytype == "dsa" and hasattr(paramiko, "DSSKey"):
        return paramiko.DSSKey
    keyclass = getattr(paramiko, keytype.upper() + "Key", None)
    if keyclass:
        return keyclass
    keyclass = getattr(paramiko, keytype.upper() + "Key", None)
    if keyclass:
        return keyclass
    # Ed25519Key
    return getattr(paramiko, keytype[:1].upper() + keytype[1:] + "Key", None)


def detect_ssh_stanza(cmd: list[str]) -> Sequence[str]:
    # plain 'ssh' clients execute a long command with if+else statements,
    # try to detect it and extract the actual command the client is trying to run.
    # ie:
    # ['sh', '-c',
    #  elif type "xpra" > /dev/null 2>&1; then xpra _proxy;\
    #  elif [ -x /usr/local/bin/xpra ]; then /usr/local/bin/xpra _proxy;\
    #  else echo "no xpra command found"; exit 1; fi']
    # if .* ; then .*/xpra _proxy;
    log(f"parse cmd={cmd} (len={len(cmd)})")
    if len(cmd) == 1:  # ie: 'thelongcommand'
        parse_cmd = cmd[0]
    elif len(cmd) == 3 and cmd[:2] == ["sh", "-c"]:  # ie: 'sh' '-c' 'thelongcommand'
        parse_cmd = cmd[2]
    else:
        return ()
    # for older clients, try to parse the long command
    # and identify the subcommands from there
    subcommands: dict[str, list[str]] = {}
    ifparts = parse_cmd.split("if ")
    log(f"ifparts={ifparts}")
    for s in ifparts:
        if any(s.startswith(x) for x in (
                "type \"xpra\"", "which \"xpra\"", "command -v \"xpra\"", "[ -x ")
               ) and s.find("then ") > 0:
            then_str = s.split("then ", 1)[1]
            # ie: then_str="$XDG_RUNTIME_DIR/xpra/xpra _proxy; el"
            if then_str.find(";") > 0:
                then_str = then_str.split(";")[0]
            parts = shlex.split(then_str)
            log(f"parts({then_str})={parts}")
            if len(parts) >= 2:
                subcommand = parts[1]  # ie: "_proxy"
                if subcommand not in subcommands:
                    subcommands[subcommand] = parts
    log(f"subcommands={subcommands}")
    return subcommands.get("_proxy", ())


def find_fingerprint(filename: str, fingerprint) -> bool:
    hex_fingerprint = binascii.hexlify(fingerprint)
    log(f"looking for key fingerprint {hex_fingerprint!r} in {filename!r}")
    count = 0
    with open(filename, encoding="latin1") as f:
        for line in f:
            if line.startswith("#"):
                continue
            line = line.strip("\n\r")
            try:
                key = base64.b64decode(line.strip().split()[1].encode('ascii'))
            except Exception as e:
                log(f"ignoring line {line}: {e}")
                continue
            for hash_algo in AUTHORIZED_KEYS_HASHES:
                try:
                    hash_class = getattr(hashlib, hash_algo)  # ie: hashlib.md5
                    hash_instance = hash_class(key)  # can raise ValueError (ie: on FIPS compliant systems)
                except (AttributeError, ValueError):
                    hash_instance = None
                if not hash_instance:
                    if first_time(f"hash-{hash_algo}-missing"):
                        log.warn(f"Warning: unsupported hash {hash_algo!r}")
                        log.warn(f" in {filename!r}")
                    continue
                fp_plain = hash_instance.hexdigest()
                log(f"{hash_algo}({line})={fp_plain}")
                if fp_plain == hex_fingerprint:
                    return True
            count += 1
    log(f"no match in {count} keys from {filename!r}")
    return False


def proxy_start(channel, subcommand: str, args: list[str]) -> None:
    log(f"ssh proxy-start({channel}, {subcommand}, {args})")
    if subcommand == "_proxy_shadow_start":
        server_mode = "shadow"
    else:
        # ie: "_proxy_start_desktop" -> "start-desktop"
        server_mode = subcommand.replace("_proxy_", "").replace("_", "-")
    log.info(f"ssh channel starting proxy {server_mode} session")
    cmd = get_xpra_command() + [subcommand] + args
    try:
        # pylint: disable=consider-using-with
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, bufsize=0, close_fds=True)
        proc.poll()
    except OSError:
        log.error(f"Error starting proxy subcommand `{subcommand}`", exc_info=True)
        log.error(f" with args={args}")
        return
    # pylint: disable=import-outside-toplevel
    from xpra.util.child_reaper import get_child_reaper

    def proxy_ended(*args) -> None:
        log("proxy_ended(%s)", args)

    def close() -> None:
        if proc.poll() is None:
            proc.terminate()

    get_child_reaper().add_process(proc, f"proxy-start-{subcommand}", cmd, True, True, proxy_ended)

    def proc_to_channel(read: Callable[[int], SizedBuffer], send: Callable[[SizedBuffer], int]) -> None:
        while proc.poll() is None:
            # log("proc_to_channel(%s, %s) waiting for data", read, send)
            try:
                r = read(4096)
            except paramiko.buffered_pipe.PipeTimeout:
                log(f"proc_to_channel({read}, {send})", exc_info=True)
                close()
                return
            # log("proc_to_channel(%s, %s) %i bytes: %s", read, send, len(r or b""), ellipsizer(r))
            while r:
                try:
                    sent = send(r)
                    r = r[sent:]
                except OSError:
                    log(f"proc_to_channel({read}, {send})", exc_info=True)
                    close()
                    return

    # forward to/from the process and the channel:

    def stderr_reader() -> None:
        proc_to_channel(proc.stderr.read, channel.send_stderr)

    def stdout_reader() -> None:
        proc_to_channel(proc.stdout.read, channel.send)

    def stdin_reader() -> None:
        # read from channel, write to stdin
        stdin = proc.stdin
        while proc.poll() is None:
            r = channel.recv(4096)
            if not r:
                close()
                break
            stdin.write(r)
            stdin.flush()

    tname = subcommand.replace("_proxy_", "proxy-").replace("_", "-")
    start_thread(stderr_reader, f"{tname}-stderr", True)
    start_thread(stdout_reader, f"{tname}-stdout", True)
    start_thread(stdin_reader, f"{tname}-stdin", True)
    channel.proxy_process = proc


# emulate a basic echo command,
def get_echo_value(echo: str) -> str:
    if WIN32:
        if echo.startswith("%") and echo.endswith("%"):
            envname = echo[1:-1]
            if envname in ("OS", "windir"):
                return os.environ.get(envname, "")
    else:
        if echo.startswith("$"):
            envname = echo[1:]
            if envname in ("OSTYPE",):
                return sys.platform
    return ""


class SSHServer(paramiko.ServerInterface):
    def __init__(self, none_auth=False, pubkey_auth=True, password_auth=None, options=None, display_name=""):
        self.event = Event()
        self.none_auth = none_auth
        self.pubkey_auth = pubkey_auth
        self.password_auth = password_auth
        self.proxy_channel = None
        self.options = options or {}
        self.display_name = display_name
        self.agent = None
        self.transport = None

    def get_banner(self) -> tuple[str, str]:
        return f"{BANNER}\n\r", "EN"

    def get_allowed_auths(self, username: str) -> str:
        # return "gssapi-keyex,gssapi-with-mic,password,publickey"
        mods = []
        if self.none_auth:
            mods.append("none")
        if self.pubkey_auth:
            mods.append("publickey")
        if self.password_auth:
            mods.append("password")
        log("get_allowed_auths(%s)=%s", username, mods)
        return ",".join(mods)

    @staticmethod
    def check_channel_request(kind: str, chanid) -> int:
        log("check_channel_request(%s, %s)", kind, chanid)
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_forward_agent_request(self, channel) -> bool:
        log(f"check_channel_forward_agent_request({channel}) SSH_AGENT_DISPATCH={SSH_AGENT_DISPATCH}")
        if SSH_AGENT_DISPATCH:
            # pylint: disable=import-outside-toplevel
            from paramiko.agent import AgentServerProxy
            self.agent = AgentServerProxy(self.transport)
            ssh_auth_sock = self.agent.get_env().get("SSH_AUTH_SOCK")
            log(f"agent SSH_AUTH_SOCK={ssh_auth_sock}")
            return bool(ssh_auth_sock)
        return False

    def check_auth_none(self, username: str) -> int:
        log("check_auth_none(%s) none_auth=%s", username, self.none_auth)
        if self.none_auth:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username: str, password: str) -> int:
        log("check_auth_password(%s, %s) password_auth=%s", username, "*" * len(password), self.password_auth)
        if not self.password_auth or not self.password_auth(username, password):
            return paramiko.AUTH_FAILED
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username: str, key) -> int:
        log("check_auth_publickey(%s, %r) pubkey_auth=%s", username, key, self.pubkey_auth)
        if not self.pubkey_auth:
            return paramiko.AUTH_FAILED
        if not POSIX or getuid() != 0:
            # pylint: disable=import-outside-toplevel
            import getpass
            sysusername = getpass.getuser()
            if sysusername != username:
                log.warn("Warning: ssh password authentication failed,")
                log.warn(" username does not match:")
                log.warn(f" expected {sysusername!r}, got {username!r}")
                return paramiko.AUTH_FAILED
        authorized_keys_filename = osexpand(AUTHORIZED_KEYS)
        if not os.path.exists(authorized_keys_filename) or not os.path.isfile(authorized_keys_filename):
            log("file '%s' does not exist", authorized_keys_filename)
            return paramiko.AUTH_FAILED
        fingerprint = key.get_fingerprint()
        if find_fingerprint(authorized_keys_filename, fingerprint):
            return paramiko.OPEN_SUCCEEDED
        return paramiko.AUTH_FAILED

    @staticmethod
    def check_auth_gssapi_keyex(username: str, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None) -> int:
        log("check_auth_gssapi_keyex%s", (username, gss_authenticated, cc_file))
        return paramiko.AUTH_FAILED

    @staticmethod
    def check_auth_gssapi_with_mic(username: str, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None) -> int:
        log("check_auth_gssapi_with_mic%s", (username, gss_authenticated, cc_file))
        return paramiko.AUTH_FAILED

    @staticmethod
    def check_channel_shell_request(channel) -> bool:
        log(f"check_channel_shell_request({channel})")
        return False

    def setup_agent(self, cmd) -> None:
        if SSH_AGENT_DISPATCH and self.agent:
            auth_sock = self.agent.get_env().get("SSH_AUTH_SOCK")
            log(f"paramiko agent socket={auth_sock!r}")
            if auth_sock:
                # pylint: disable=import-outside-toplevel
                from xpra.net.ssh.agent import setup_proxy_ssh_socket
                setup_proxy_ssh_socket(cmd, auth_sock=auth_sock)

    def check_channel_exec_request(self, channel, command: str) -> bool:
        def fail(*messages) -> bool:
            for m in messages:
                log.warn(m)
            self.event.set()
            channel.close()
            return False

        def csend(exit_status=0, out=None, err=None) -> bool:
            channel.exec_response = (exit_status, out, err)
            self.event.set()
            return True

        log(f"check_channel_exec_request({channel}, {command!r})")
        cmd = shlex.split(decode_str(command))
        log(f"check_channel_exec_request: cmd={cmd}")
        if cmd[0] == "command" and len(cmd) == 1:
            return csend(out="\r\n")
        if cmd == ["command", "-v", "xpra"]:
            return csend(out="xpra\r\n")
        if cmd[0] == "ver" and len(cmd) == 1:
            if WIN32 and BACKWARDS_COMPATIBLE:
                # older xpra versions run this command to detect win32:
                return csend(out="Microsoft Windows")
            return csend(1, err=f"{cmd[0]}: not found\r\n")
        if cmd[0] == "echo" and len(cmd) == 2:
            # echo can be used to detect the platform,
            # so emulate a basic echo command,
            # just enough for the os detection to work:
            echo = get_echo_value(cmd[1]) + "\r\n"
            log(f"exec request {cmd} returning: {echo!r}")
            return csend(out=echo)
        if WIN32 and (" ".join(cmd)).find("REG QUERY") >= 0 and str(cmd).find(
                r"HKEY_LOCAL_MACHINE\\Software\\Xpra") > 0:
            # this batch command is used to detect the xpra.exe installation path
            # (see xpra/net/ssh.py)
            return csend(out=f"InstallPath {get_app_dir()}\r\n")
        if cmd[0] in ("type", "which") and len(cmd) == 2:
            xpra_cmd = cmd[-1]  # ie: $XDG_RUNTIME_DIR/xpra/xpra or "xpra"
            # only allow '*xpra' commands:
            if any(xpra_cmd.lower().endswith(x) for x in ("xpra", "xpra_cmd.exe", "xpra.exe")):
                # we don't really allow the xpra command to be executed anyway,
                # so just reply that it exists:
                return csend(out="xpra\r\n")
            return csend(1, err=f"type: {xpra_cmd!r}: not found\r\n")
        if (cmd[0].endswith("xpra") or cmd[0].endswith("Xpra_cmd.exe")) and len(cmd) >= 2:
            subcommand = cmd[1].strip("\"'").rstrip(";")
            log(f"ssh xpra subcommand: {subcommand}")
            if subcommand.startswith("_proxy_"):
                proxy_start_enabled = str_to_bool(self.options.get("proxy-start"), False)
                if not proxy_start_enabled:
                    return fail(f"Warning: received a {subcommand!r} session request",
                                " this feature is not enabled with the builtin ssh server")
                proxy_start(channel, subcommand, cmd[2:])
            elif subcommand == "_proxy":
                display_name = getattr(self, "display_name", "")
                # if specified, the display name must match this session:
                display = ""
                for arg in cmd[2:]:
                    if not arg.startswith("--"):
                        display = arg
                if display and display_name != display:
                    return fail(f"Warning: the display requested {display!r}",
                                f" does not match the current display {display_name!r}")
                log(f"ssh 'xpra {subcommand}' subcommand: display_name={display_name!r}, agent={self.agent}")
                self.setup_agent(cmd)
            else:
                return fail(f"Warning: unsupported xpra subcommand '{cmd[1]}'")
            # we're ready to use this socket as an xpra channel
            self._run_proxy(channel)
            return True
        proxy_cmd = detect_ssh_stanza(cmd)
        if proxy_cmd:
            self.setup_agent(proxy_cmd)
            self._run_proxy(channel)
            return True
        return fail("Warning: unsupported ssh command:", f" {cmd!r}")

    def _run_proxy(self, channel) -> None:
        pc = self.proxy_channel
        log(f"run_proxy({channel}) proxy-channel={pc}")
        if pc:
            self.proxy_channel = None
            pc.close()
        self.proxy_channel = channel
        self.event.set()

    @staticmethod
    def check_channel_pty_request(channel, term, width: int, height: int,
                                  pixelwidth: int, pixelheight: int, modes) -> bool:
        log("check_channel_pty_request%s", (channel, term, width, height, pixelwidth, pixelheight, modes))
        # refusing to open a pty:
        return False

    @staticmethod
    def enable_auth_gssapi() -> bool:
        log("enable_auth_gssapi()")
        return False


PREFIX = "ssh_host_"
SUFFIX = "_key"


def load_host_key(ff: str):
    f = os.path.basename(ff)
    if not (f.startswith(PREFIX) and f.endswith(SUFFIX)):
        log.warn(f"Warning: unrecognized key file format {ff!r}")
        log.warn(f" key filenames should start with {PREFIX!r} and end with {SUFFIX!r}")
        return None
    keytype = f[len(PREFIX):-len(SUFFIX)]
    keyclass = get_keyclass(keytype)
    if not keyclass:
        log.warn(f"Warning: unknown host key format '{f}'")
        log(f"key type {f!r} is not supported, cannot load {ff!r}")
        return None
    log(f"loading {keytype} key from {ff!r} using {keyclass}")
    try:
        return keyclass(filename=ff)
    except OSError:
        log(f"cannot add host key {ff!r}", exc_info=True)
    except paramiko.SSHException as e:
        log(f"error adding host key {ff!r}", exc_info=True)
        log.error(f"Error: cannot add {keytype} host key {ff!r}:")
        log.estr(e)
    return None


def close_all(transport, conn) -> None:
    if transport:
        log(f"close() closing {transport}")
        try:
            transport.close()
        except Exception:
            log(f"{transport}.close()", exc_info=True)
    log(f"close() closing {conn}")
    try:
        conn.close()
    except Exception:
        log(f"{conn}.close()")


def load_server_host_keys(host_keyfile: str) -> dict[Any, str]:
    host_keys = {}

    def add_host_key(key_path: str) -> bool:
        host_key = load_host_key(key_path)
        if host_key and host_key not in host_keys:
            host_keys[host_key] = key_path
        return bool(host_key)

    if host_keyfile:
        if not add_host_key(host_keyfile):
            log.error(f"Error: failed to load host key {host_keyfile!r}")
        return host_keys

    ssh_key_dirs = get_ssh_conf_dirs()
    log("trying to load ssh host keys from: " + csv(ssh_key_dirs))
    for d in ssh_key_dirs:
        fd = osexpand(d)
        log(f"osexpand({d})={fd}")
        if not os.path.exists(fd) or not os.path.isdir(fd):
            log(f"ssh host key directory {fd!r} is invalid")
            continue
        for f in os.listdir(fd):
            if f.startswith(PREFIX) and f.endswith(SUFFIX):
                add_host_key(os.path.join(fd, f))
    return host_keys


def make_ssh_server_connection(conn, socket_options: dict,
                               none_auth: bool = False,
                               password_auth: Callable[[str, str], bool] | None = None,
                               display_name: str = ""):
    log("make_ssh_server_connection%s", (conn, socket_options, none_auth, password_auth))
    ssh_server = SSHServer(none_auth=none_auth, password_auth=password_auth, options=socket_options,
                           display_name=display_name)
    DoGSSAPIKeyExchange = str_to_bool(socket_options.get("ssh-gss-key-exchange", False), False)
    sock = conn._socket
    t = None

    def close() -> None:
        close_all(t, conn)

    try:
        t = paramiko.Transport(sock, gss_kex=DoGSSAPIKeyExchange)
        ssh_server.transport = t
        gss_host = socket_options.get("ssh-gss-host", socket.getfqdn(""))
        t.set_gss_host(gss_host)
        # load host keys:
        host_keyfile: str = socket_options.get("ssh-host-key", "")
        host_keys = load_server_host_keys(host_keyfile)
        if not host_keys:
            log.error("Error: cannot start SSH server,")
            log.error(" no readable SSH host keys found")
            close()
            return None
        log("loaded host keys: %s", tuple(host_keys.values()))
        # add them to the transport:
        for host_key in host_keys.keys():
            t.add_server_key(host_key)
        t.start_server(server=ssh_server)
    except EOFError:
        log("SSH connection closed", exc_info=True)
        close()
        return None
    except paramiko.SSHException as e:
        log("failed to start ssh server", exc_info=True)
        log.error("Error handling SSH connection:")
        log.estr(e)
        close()
        return None
    while t.is_active():
        try:
            chan = t.accept(SERVER_WAIT)
            if chan is None:
                log.warn("Warning: SSH channel setup failed")
                log.warn(" closing connection %s", conn)
                # prevent errors trying to access this connection, now likely dead:
                conn.set_active(False)
                close()
                return None
        except paramiko.SSHException as e:
            log("failed to open ssh channel", exc_info=True)
            log.error("Error opening channel:")
            log.estr(e)
            close()
            return None
        log(f"client authenticated, accepted channel={chan}")
        timedout = not ssh_server.event.wait(SERVER_WAIT)
        if timedout:
            log.warn("Warning: timeout waiting for xpra SSH subcommand,")
            log.warn(" closing connection from " + pretty_socket(conn.target))
            close()
            return None
        proxy_channel = ssh_server.proxy_channel
        if proxy_channel:
            if getattr(proxy_channel, "proxy_process", None):
                log("proxy channel is handled using a subprocess")
                return None
            from xpra.net.ssh.paramiko.util import SSHSocketConnection
            return SSHSocketConnection(proxy_channel, sock,
                                       conn.local, conn.endpoint, conn.target,
                                       socket_options=socket_options)
        exec_response = getattr(chan, "exec_response", None)
        log(f"proxy channel={proxy_channel}, timedout={timedout}, exec_response={exec_response}")
        if exec_response:
            exit_status, out, err = exec_response
            if out:
                chan.sendall(out)
            if err:
                chan.sendall_stderr(err)
            chan.send_exit_status(exit_status)
            chan.close()
            # the client may now make another request on a new channel:
            ssh_server.event.clear()
    return None
