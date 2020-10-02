# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import shlex
import socket
import signal
from subprocess import PIPE, Popen

from xpra.scripts.main import InitException, InitExit, shellquote, host_target_string
from xpra.platform.paths import get_ssh_known_hosts_files
from xpra.platform import get_username
from xpra.scripts.config import parse_bool
from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT, ConnectionClosedException
from xpra.exit_codes import (
    EXIT_SSH_KEY_FAILURE, EXIT_SSH_FAILURE,
    EXIT_CONNECTION_FAILED,
    )
from xpra.os_util import (
    bytestostr, osexpand, load_binary_file,
    nomodule_context, umask_context, is_main_thread,
    WIN32, OSX, POSIX,
    )
from xpra.util import envint, envbool, nonl, engs, csv
from xpra.log import Logger, is_debug_enabled

log = Logger("network", "ssh")

INITENV_COMMAND = os.environ.get("XPRA_INITENV_COMMAND", "xpra initenv")
WINDOW_SIZE = envint("XPRA_SSH_WINDOW_SIZE", 2**27-1)
TIMEOUT = envint("XPRA_SSH_TIMEOUT", 60)
SKIP_UI = envbool("XPRA_SKIP_UI", False)

VERIFY_HOSTKEY = envbool("XPRA_SSH_VERIFY_HOSTKEY", True)
VERIFY_STRICT = envbool("XPRA_SSH_VERIFY_STRICT", False)
ADD_KEY = envbool("XPRA_SSH_ADD_KEY", True)
#which authentication mechanisms are enabled with paramiko:
NONE_AUTH = envbool("XPRA_SSH_NONE_AUTH", True)
PASSWORD_AUTH = envbool("XPRA_SSH_PASSWORD_AUTH", True)
AGENT_AUTH = envbool("XPRA_SSH_AGENT_AUTH", True)
KEY_AUTH = envbool("XPRA_SSH_KEY_AUTH", True)
PASSWORD_AUTH = envbool("XPRA_SSH_PASSWORD_AUTH", True)
PASSWORD_RETRY = envint("XPRA_SSH_PASSWORD_RETRY", 2)
assert PASSWORD_RETRY>=0
MAGIC_QUOTES = envbool("XPRA_SSH_MAGIC_QUOTES", True)


def keymd5(k) -> str:
    import binascii
    f = bytestostr(binascii.hexlify(k.get_fingerprint()))
    s = "MD5"
    while f:
        s += ":"+f[:2]
        f = f[2:]
    return s


def force_focus():
    from xpra.platform.gui import force_focus as _force_focus
    _force_focus()

def dialog_run(dialog) -> int:
    from gi.repository import GLib
    if is_main_thread():
        force_focus()
        dialog.show()
        try:
            return dialog.run()
        finally:
            dialog.destroy()
    #do a little dance if we're not running in the main thread:
    #block this thread and wait for the main thread to run the dialog
    from threading import Event
    e = Event()
    code = []
    def main_thread_run():
        force_focus()
        dialog.show()
        try:
            r = dialog.run()
        finally:
            dialog.destroy()
        code.append(r)
        e.set()
    GLib.idle_add(main_thread_run)
    e.wait()
    log("dialog_run(%s) code=%s", dialog, code)
    return code[0]

def dialog_pass(title="Password Input", prompt="enter password", icon="") -> str:
    from xpra.client.gtk_base.pass_dialog import PasswordInputDialogWindow
    dialog = PasswordInputDialogWindow(title, prompt, icon)
    try:
        if dialog_run(dialog)==0:
            return dialog.get_password()
        return None
    finally:
        dialog.destroy()

def dialog_confirm(title, prompt, qinfo=(), icon="", buttons=(("OK", 1),)) -> int:
    from xpra.client.gtk_base.confirm_dialog import ConfirmDialogWindow
    dialog = ConfirmDialogWindow(title, prompt, qinfo, icon, buttons)
    try:
        r = dialog_run(dialog)
    finally:
        dialog.destroy()
    return r


def confirm_key(info=()) -> bool:
    if SKIP_UI:
        return False
    from xpra.platform.paths import get_icon_filename
    from xpra.os_util import use_tty
    if not use_tty():
        icon = get_icon_filename("authentication", "png") or ""
        prompt = "Are you sure you want to continue connecting?"
        code = dialog_confirm("Confirm Key", prompt, info, icon, buttons=[("yes", 200), ("NO", 201)])
        log("dialog return code=%s", code)
        r = code==200
        log.info("host key %sconfirmed", ["not ", ""][r])
        return r
    log("confirm_key(%s) will use stdin prompt", nonl(info))
    prompt = "Are you sure you want to continue connecting (yes/NO)? "
    sys.stderr.write(os.linesep.join(info)+os.linesep+prompt)
    try:
        v = sys.stdin.readline().rstrip(os.linesep)
    except KeyboardInterrupt:
        sys.exit(128+signal.SIGINT)
    return v and v.lower() in ("y", "yes")

def input_pass(prompt) -> str:
    if SKIP_UI:
        return None
    from xpra.platform.paths import get_icon_filename
    from xpra.os_util import use_tty
    if not use_tty():
        icon = get_icon_filename("authentication", "png") or ""
        return dialog_pass("Password Input", prompt, icon)
    from getpass import getpass
    try:
        return getpass(prompt)
    except KeyboardInterrupt:
        sys.exit(128+signal.SIGINT)


class SSHSocketConnection(SocketConnection):

    def __init__(self, ssh_channel, sock, sockname, peername, target, info=None):
        super().__init__(ssh_channel, sockname, peername, target, "ssh", info)
        self._raw_socket = sock

    def start_stderr_reader(self):
        from xpra.make_thread import start_thread
        start_thread(self._stderr_reader, "ssh-stderr-reader", daemon=True)

    def _stderr_reader(self):
        #stderr = self._socket.makefile_stderr(mode="rb", bufsize=1)
        chan = self._socket
        stderr = chan.makefile_stderr("rb", 1)
        errs = []
        while self.active:
            v = stderr.readline()
            if not v:
                log("SSH EOF on stderr of %s", chan.get_name())
                return
            errs.append(bytestostr(v.rstrip(b"\n\r")))
        if errs:
            log.warn("remote SSH stderr:")
            for e in errs:
                log.warn(" %s", e)

    def peek(self, n):
        if not self._raw_socket:
            return None
        return self._raw_socket.recv(n, socket.MSG_PEEK)

    def get_socket_info(self) -> dict:
        if not self._raw_socket:
            return {}
        return self.do_get_socket_info(self._raw_socket)

    def get_info(self) -> dict:
        i = SocketConnection.get_info(self)
        s = self._socket
        if s:
            i["ssh-channel"] = {
                "id"    : s.get_id(),
                "name"  : s.get_name(),
                }
        return i


class SSHProxyCommandConnection(SSHSocketConnection):
    def __init__(self, ssh_channel, peername, target, info):
        super().__init__(ssh_channel, None, None, peername, target, info)
        self.process = None

    def error_is_closed(self, e) -> bool:
        p = self.process
        if p:
            #if the process has terminated,
            #then the connection must be closed:
            if p[0].poll() is not None:
                return True
        return super().error_is_closed(e)

    def get_socket_info(self) -> dict:
        p = self.process
        if not p:
            return {}
        proc, _ssh, cmd = p
        return {
            "process" : {
                "pid"       : proc.pid,
                "returncode": proc.returncode,
                "command"   : cmd,
                }
            }

    def close(self):
        try:
            super().close()
        except Exception:
            #this can happen if the proxy command gets a SIGINT,
            #it's closed already and we don't care
            log("SSHProxyCommandConnection.close()", exc_info=True)


def ssh_paramiko_connect_to(display_desc):
    #plain socket attributes:
    dtype = display_desc["type"]
    host = display_desc["host"]
    port = display_desc.get("ssh-port", 22)
    #ssh and command attributes:
    username = display_desc.get("username") or get_username()
    if "proxy_host" in display_desc:
        display_desc.setdefault("proxy_username", get_username())
    password = display_desc.get("password")
    remote_xpra = display_desc["remote_xpra"]
    proxy_command = display_desc["proxy_command"]       #ie: "_proxy_start"
    socket_dir = display_desc.get("socket_dir")
    display = display_desc.get("display")
    display_as_args = display_desc["display_as_args"]   #ie: "--start=xterm :10"
    paramiko_config = display_desc.copy()
    paramiko_config.update(display_desc.get("paramiko-config", {}))
    socket_info = {
            "host"  : host,
            "port"  : port,
            }
    def get_keyfiles(host_config, config_name="key"):
        keyfiles = (host_config or {}).get("identityfile") or get_default_keyfiles()
        keyfile = paramiko_config.get(config_name)
        if keyfile:
            keyfiles.insert(0, keyfile)
        return keyfiles

    with nogssapi_context():
        from paramiko import SSHConfig, ProxyCommand
        ssh_config = SSHConfig()
        user_config_file = os.path.expanduser("~/.ssh/config")
        sock = None
        host_config = None
        if os.path.exists(user_config_file):
            with open(user_config_file) as f:
                ssh_config.parse(f)
            log("parsed user config '%s': %i hosts found", user_config_file, len(ssh_config.get_hostnames()))
            host_config = ssh_config.lookup(host)
            if host_config:
                log("got host config for '%s': %s", host, host_config)
                chost = host_config.get("hostname", host)
                cusername = host_config.get("user", username)
                cport = host_config.get("port", port)
                try:
                    port = int(cport)
                except ValueError:
                    raise InitExit(EXIT_SSH_FAILURE, "invalid ssh port specified: '%s'" % cport)
                proxycommand = host_config.get("proxycommand")
                if proxycommand:
                    log("found proxycommand='%s' for host '%s'", proxycommand, chost)
                    sock = ProxyCommand(proxycommand)
                    log("ProxyCommand(%s)=%s", proxycommand, sock)
                    from xpra.child_reaper import getChildReaper
                    cmd = getattr(sock, "cmd", [])
                    def proxycommand_ended(proc):
                        log("proxycommand_ended(%s) exit code=%s", proc, proc.poll())
                    getChildReaper().add_process(sock.process, "paramiko-ssh-client", cmd, True, True,
                                                 callback=proxycommand_ended)
                    proxy_keys = get_keyfiles(host_config, "proxy_key")
                    log("proxy keys=%s", proxy_keys)
                    from paramiko.client import SSHClient
                    ssh_client = SSHClient()
                    ssh_client.load_system_host_keys()
                    log("ssh proxy command connect to %s", (chost, cport, sock))
                    ssh_client.connect(chost, cport, sock=sock)
                    transport = ssh_client.get_transport()
                    do_ssh_paramiko_connect_to(transport, chost,
                                               cusername, password,
                                               host_config or ssh_config.lookup("*"),
                                               proxy_keys,
                                               paramiko_config)
                    chan = paramiko_run_remote_xpra(transport, proxy_command, remote_xpra, socket_dir, display_as_args)
                    peername = (chost, cport)
                    conn = SSHProxyCommandConnection(chan, peername, peername, socket_info)
                    conn.target = host_target_string("ssh", cusername, chost, cport, display)
                    conn.timeout = SOCKET_TIMEOUT
                    conn.start_stderr_reader()
                    conn.process = (sock.process, "ssh", cmd)
                    from xpra.net import bytestreams
                    from paramiko.ssh_exception import ProxyCommandFailure
                    bytestreams.CLOSED_EXCEPTIONS = tuple(list(bytestreams.CLOSED_EXCEPTIONS)+[ProxyCommandFailure])
                    return conn

        keys = get_keyfiles(host_config)
        from xpra.scripts.main import socket_connect
        from paramiko.transport import Transport
        from paramiko import SSHException
        if "proxy_host" in display_desc:
            proxy_host = display_desc["proxy_host"]
            proxy_port = display_desc.get("proxy_port", 22)
            proxy_username = display_desc.get("proxy_username", username)
            proxy_password = display_desc.get("proxy_password", password)
            proxy_keys = get_keyfiles(host_config, "proxy_key")
            sock = socket_connect(dtype, proxy_host, proxy_port)
            middle_transport = Transport(sock)
            middle_transport.use_compression(False)
            try:
                middle_transport.start_client()
            except SSHException as e:
                log("start_client()", exc_info=True)
                raise InitExit(EXIT_SSH_FAILURE, "SSH negotiation failed: %s" % e) from None
            proxy_host_config = ssh_config.lookup(host)
            do_ssh_paramiko_connect_to(middle_transport, proxy_host,
                                       proxy_username, proxy_password,
                                       proxy_host_config or ssh_config.lookup("*"),
                                       proxy_keys,
                                       paramiko_config)
            log("Opening proxy channel")
            chan_to_middle = middle_transport.open_channel("direct-tcpip", (host, port), ('localhost', 0))

            transport = Transport(chan_to_middle)
            transport.use_compression(False)
            try:
                transport.start_client()
            except SSHException as e:
                log("start_client()", exc_info=True)
                raise InitExit(EXIT_SSH_FAILURE, "SSH negotiation failed: %s" % e)
            do_ssh_paramiko_connect_to(transport, host,
                                       username, password,
                                       host_config or ssh_config.lookup("*"),
                                       keys,
                                       paramiko_config)
            chan = paramiko_run_remote_xpra(transport, proxy_command, remote_xpra, socket_dir, display_as_args)
            peername = (host, port)
            conn = SSHProxyCommandConnection(chan, peername, peername, socket_info)
            conn.target = "%s via %s" % (
                host_target_string("ssh", username, host, port, display),
                host_target_string("ssh", proxy_username, proxy_host, proxy_port, None),
                )
            conn.timeout = SOCKET_TIMEOUT
            conn.start_stderr_reader()
            return conn

        #plain TCP connection to the server,
        #we open it then give the socket to paramiko:
        sock = socket_connect(dtype, host, port)
        sockname = sock.getsockname()
        peername = sock.getpeername()
        log("paramiko socket_connect: sockname=%s, peername=%s", sockname, peername)
        transport = Transport(sock)
        transport.use_compression(False)
        try:
            transport.start_client()
        except SSHException as e:
            log("start_client()", exc_info=True)
            raise InitExit(EXIT_SSH_FAILURE, "SSH negotiation failed: %s" % e) from None
        do_ssh_paramiko_connect_to(transport, host, username, password,
                                   host_config or ssh_config.lookup("*"),
                                   keys,
                                   paramiko_config)
        chan = paramiko_run_remote_xpra(transport, proxy_command, remote_xpra, socket_dir, display_as_args)
        conn = SSHSocketConnection(chan, sock, sockname, peername, (host, port), socket_info)
        conn.target = host_target_string("ssh", username, host, port, display)
        conn.timeout = SOCKET_TIMEOUT
        conn.start_stderr_reader()
        return conn


#workaround incompatibility between paramiko and gssapi:
class nogssapi_context(nomodule_context):

    def __init__(self):
        super().__init__("gssapi")


def get_default_keyfiles():
    dkf = os.environ.get("XPRA_SSH_DEFAULT_KEYFILES", None)
    if dkf is not None:
        return [x for x in dkf.split(":") if x]
    return [osexpand(os.path.join("~/", ".ssh", keyfile)) for keyfile in ("id_ed25519", "id_ecdsa", "id_rsa", "id_dsa")]


def do_ssh_paramiko_connect_to(transport, host, username, password, host_config=None, keyfiles=None, paramiko_config=None):
    from paramiko import SSHException, PasswordRequiredException
    from paramiko.agent import Agent
    from paramiko.hostkeys import HostKeys
    log("do_ssh_paramiko_connect_to%s", (transport, host, username, password, host_config, keyfiles, paramiko_config))
    log("SSH transport %s", transport)

    def configvalue(key):
        #if the paramiko config has a setting, honour it:
        if paramiko_config and key in paramiko_config:
            return paramiko_config.get(key)
        #fallback to the value from the host config:
        return (host_config or {}).get(key)
    def configbool(key, default_value=True):
        return parse_bool(key, configvalue(key), default_value)
    def configint(key, default_value=0):
        v = configvalue(key)
        if v is None:
            return default_value
        return int(v)

    host_key = transport.get_remote_server_key()
    assert host_key, "no remote server key"
    log("remote_server_key=%s", keymd5(host_key))
    if configbool("verify-hostkey", VERIFY_HOSTKEY):
        host_keys = HostKeys()
        host_keys_filename = None
        KNOWN_HOSTS = get_ssh_known_hosts_files()
        for known_hosts in KNOWN_HOSTS:
            host_keys.clear()
            try:
                path = os.path.expanduser(known_hosts)
                if os.path.exists(path):
                    host_keys.load(path)
                    log("HostKeys.load(%s) successful", path)
                    host_keys_filename = path
                    break
            except IOError:
                log("HostKeys.load(%s)", known_hosts, exc_info=True)

        log("host keys=%s", host_keys)
        keys = host_keys.lookup(host)
        known_host_key = (keys or {}).get(host_key.get_name())
        def keyname():
            return host_key.get_name().replace("ssh-", "")
        if host_key==known_host_key:
            assert host_key
            log("%s host key '%s' OK for host '%s'", keyname(), keymd5(host_key), host)
        else:
            dnscheck = ""
            if configbool("verifyhostkeydns"):
                try:
                    from xpra.net.sshfp import check_host_key
                    dnscheck = check_host_key(host, host_key)
                except ImportError as e:
                    log("verifyhostkeydns failed", exc_info=True)
                    log.warn("Warning: cannot check SSHFP DNS records")
                    log.warn(" %s", e)
            log("dnscheck=%s", dnscheck)
            def adddnscheckinfo(q):
                if dnscheck is not True:
                    if dnscheck:
                        q += [
                            "SSHFP validation failed:",
                            dnscheck
                            ]
                    else:
                        q += [
                            "SSHFP validation failed"
                            ]
            if dnscheck is True:
                #DNSSEC provided a matching record
                log.info("found a valid SSHFP record for host %s", host)
            elif known_host_key:
                log.warn("Warning: SSH server key mismatch")
                qinfo = [
"WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!",
"IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!",
"Someone could be eavesdropping on you right now (man-in-the-middle attack)!",
"It is also possible that a host key has just been changed.",
"The fingerprint for the %s key sent by the remote host is" % keyname(),
keymd5(host_key),
]
                adddnscheckinfo(qinfo)
                if configbool("stricthostkeychecking", VERIFY_STRICT):
                    log.warn("Host key verification failed.")
                    #TODO: show alert with no option to accept key
                    qinfo += [
                        "Please contact your system administrator.",
                        "Add correct host key in %s to get rid of this message.",
                        "Offending %s key in %s" % (keyname(), host_keys_filename),
                        "ECDSA host key for %s has changed and you have requested strict checking." % keyname(),
                        ]
                    sys.stderr.write(os.linesep.join(qinfo))
                    transport.close()
                    raise InitExit(EXIT_SSH_KEY_FAILURE, "SSH Host key has changed")
                if not confirm_key(qinfo):
                    transport.close()
                    raise InitExit(EXIT_SSH_KEY_FAILURE, "SSH Host key has changed")

            else:
                assert (not keys) or (host_key.get_name() not in keys)
                if not keys:
                    log.warn("Warning: unknown SSH host")
                else:
                    log.warn("Warning: unknown %s SSH host key", keyname())
                qinfo = [
                    "The authenticity of host '%s' can't be established." % (host,),
                    "%s key fingerprint is" % keyname(),
                    keymd5(host_key),
                    ]
                adddnscheckinfo(qinfo)
                if not confirm_key(qinfo):
                    transport.close()
                    raise InitExit(EXIT_SSH_KEY_FAILURE, "Unknown SSH host '%s'" % host)

            if configbool("addkey", ADD_KEY):
                try:
                    if not host_keys_filename:
                        #the first one is the default,
                        #ie: ~/.ssh/known_hosts on posix
                        host_keys_filename = os.path.expanduser(KNOWN_HOSTS[0])
                    log("adding %s key for host '%s' to '%s'", keyname(), host, host_keys_filename)
                    if not os.path.exists(host_keys_filename):
                        keys_dir = os.path.dirname(host_keys_filename)
                        if not os.path.exists(keys_dir):
                            log("creating keys directory '%s'", keys_dir)
                            os.mkdir(keys_dir, 0o700)
                        elif not os.path.isdir(keys_dir):
                            log.warn("Warning: '%s' is not a directory")
                            log.warn(" key not saved")
                        if os.path.exists(keys_dir) and os.path.isdir(keys_dir):
                            log("creating known host file '%s'", host_keys_filename)
                            with umask_context(0o133):
                                with open(host_keys_filename, 'a+'):
                                    pass
                    host_keys.add(host, host_key.get_name(), host_key)
                    host_keys.save(host_keys_filename)
                except OSError as e:
                    log("failed to add key to '%s'", host_keys_filename)
                    log.error("Error adding key to '%s'", host_keys_filename)
                    log.error(" %s", e)
                except Exception as e:
                    log.error("cannot add key", exc_info=True)
    else:
        log("ssh host key verification skipped")


    def auth_agent():
        agent = Agent()
        agent_keys = agent.get_keys()
        log("agent keys: %s", agent_keys)
        if agent_keys:
            for agent_key in agent_keys:
                log("trying ssh-agent key '%s'", keymd5(agent_key))
                try:
                    transport.auth_publickey(username, agent_key)
                    if transport.is_authenticated():
                        log("authenticated using agent and key '%s'", keymd5(agent_key))
                        break
                except SSHException:
                    log("agent key '%s' rejected", keymd5(agent_key), exc_info=True)
            if not transport.is_authenticated():
                log.info("agent authentication failed, tried %i key%s", len(agent_keys), engs(agent_keys))

    def auth_publickey():
        log("trying public key authentication using %s", keyfiles)
        for keyfile_path in keyfiles:
            if not os.path.exists(keyfile_path):
                log("no keyfile at '%s'", keyfile_path)
                continue
            log("trying '%s'", keyfile_path)
            key = None
            import paramiko
            for pkey_classname in ("RSA", "DSS", "ECDSA", "Ed25519"):
                pkey_class = getattr(paramiko, "%sKey" % pkey_classname, None)
                if pkey_class is None:
                    log("no %s key type", pkey_classname)
                    continue
                log("trying to load as %s", pkey_classname)
                try:
                    key = pkey_class.from_private_key_file(keyfile_path)
                    log.info("loaded %s private key from '%s'", pkey_classname, keyfile_path)
                    break
                except PasswordRequiredException as e:
                    log("%s keyfile requires a passphrase; %s", keyfile_path, e)
                    passphrase = input_pass("please enter the passphrase for %s:" % (keyfile_path,))
                    if passphrase:
                        try:
                            key = pkey_class.from_private_key_file(keyfile_path, passphrase)
                            log.info("loaded %s private key from '%s'", pkey_classname, keyfile_path)
                        except SSHException as e:
                            log("from_private_key_file", exc_info=True)
                            log.info("cannot load key from file '%s':", keyfile_path)
                            log.info(" %s", e)
                    break
                except Exception as e:
                    log("auth_publickey() loading as %s", pkey_classname, exc_info=True)
                    key_data = load_binary_file(keyfile_path)
                    if key_data and key_data.find(b"BEGIN OPENSSH PRIVATE KEY")>=0 and paramiko.__version__<"2.7":
                        log.warn("Warning: private key '%s'", keyfile_path)
                        log.warn(" this file seems to be using OpenSSH's own format")
                        log.warn(" please convert it to something more standard (ie: PEM)")
                        log.warn(" so it can be used with the paramiko backend")
                        log.warn(" or switch to the OpenSSH backend with '--ssh=ssh'")
            if key:
                log("auth_publickey using %s as %s: %s", keyfile_path, pkey_classname, keymd5(key))
                try:
                    transport.auth_publickey(username, key)
                except SSHException as e:
                    log("key '%s' rejected", keyfile_path, exc_info=True)
                    log.info("SSH authentication using key '%s' failed:", keyfile_path)
                    log.info(" %s", e)
                else:
                    if transport.is_authenticated():
                        break
            else:
                log.error("Error: cannot load private key '%s'", keyfile_path)

    def auth_none():
        log("trying none authentication")
        try:
            transport.auth_none(username)
        except SSHException:
            log("auth_none()", exc_info=True)

    def auth_password():
        log("trying password authentication")
        try:
            transport.auth_password(username, password)
        except SSHException as e:
            log("auth_password(..)", exc_info=True)
            log.info("SSH password authentication failed:")
            log.info(" %s", getattr(e, "message", e))

    def auth_interactive():
        log("trying interactive authentication")
        class iauthhandler:
            def __init__(self):
                self.authcount = 0
            def handlestuff(self, _title, _instructions, prompt_list):
                p = []
                for pent in prompt_list:
                    if self.authcount==0 and password:
                        p.append(password)
                    else:
                        p.append(input_pass(pent[0]))
                    self.authcount += 1
                return p
        try:
            myiauthhandler = iauthhandler()
            transport.auth_interactive(username, myiauthhandler.handlestuff, "")
        except SSHException as e:
            log("auth_interactive(..)", exc_info=True)
            log.info("SSH password authentication failed:")
            log.info(" %s", getattr(e, "message", e))

    banner = transport.get_banner()
    if banner:
        log.info("SSH server banner:")
        for x in banner.splitlines():
            log.info(" %s", x)

    if paramiko_config and "auth" in paramiko_config:
        auth = paramiko_config.get("auth", "").split("+")
        AUTH_OPTIONS = ("none", "agent", "key", "password")
        if any(a for a in auth if a not in AUTH_OPTIONS):
            raise InitExit(EXIT_SSH_FAILURE, "invalid ssh authentication module specified: %s" %
                           csv(a for a in auth if a not in AUTH_OPTIONS))
    else:
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
    #def doauth(authtype):
    #    return authtype in auth and not transport.is_authenticated()

    log("starting authentication, authentication methods: %s", auth)
    # per the RFC we probably should do none first always and read off the supported
    # methods, however, the current code seems to work fine with OpenSSH
    while not transport.is_authenticated() and auth:
        a = auth.pop(0)
        log("auth=%s", a)
        if a=="none":
            auth_none()
        elif a=="agent":
            auth_agent()
        elif a=="key":
            auth_publickey()
        elif a=="password":
            auth_interactive()
            if not transport.is_authenticated():
                if password:
                    auth_password()
                else:
                    tries = configint("numberofpasswordprompts", PASSWORD_RETRY)
                    for _ in range(tries):
                        password = input_pass("please enter the SSH password for %s@%s:" % (username, host))
                        if not password:
                            break
                        auth_password()
                        if transport.is_authenticated():
                            break
    if not transport.is_authenticated():
        transport.close()
        raise InitExit(EXIT_CONNECTION_FAILED, "SSH Authentication on %s failed" % host)


def paramiko_run_test_command(transport, cmd):
    from paramiko import SSHException
    log("run_test_command('%s')", cmd)
    try:
        chan = transport.open_session(window_size=None, max_packet_size=0, timeout=60)
        chan.set_name("find %s" % cmd)
    except SSHException as e:
        log("open_session", exc_info=True)
        raise InitExit(EXIT_SSH_FAILURE, "failed to open SSH session: %s" % e) from None
    chan.exec_command(cmd)
    out = chan.makefile().read()
    err = chan.makefile_stderr().read()
    code = chan.recv_exit_status()
    log("exec_command('%s')=%s, out=%s, err=%s", cmd, code, out, err)
    chan.close()
    return out, err, code

def paramiko_run_remote_xpra(transport, xpra_proxy_command=None, remote_xpra=None, socket_dir=None, display_as_args=None):
    from paramiko import SSHException
    assert remote_xpra
    log("will try to run xpra from: %s", remote_xpra)
    def rtc(cmd):
        return paramiko_run_test_command(transport, cmd)
    tried = set()
    for xpra_cmd in remote_xpra:
        if xpra_cmd.lower() in ("xpra.exe", "xpra_cmd.exe"):
            #win32 mode, quick and dirty platform test first:
            r = rtc("ver")
            if r[2]!=0:
                continue
            #let's find where xpra is installed:
            r = rtc("FOR /F \"usebackq tokens=3*\" %A IN (`REG QUERY \"HKEY_LOCAL_MACHINE\Software\Xpra\" /v InstallPath`) DO (echo %A %B)")
            if r[2]==0:
                #found in registry:
                lines = r[0].splitlines()
                installpath = bytestostr(lines[-1])
                xpra_cmd = "%s\\%s" % (installpath, xpra_cmd)
                xpra_cmd = xpra_cmd.replace("\\", "\\\\")
                log("using '%s'", xpra_cmd)
        elif xpra_cmd.endswith(".exe"):
            #assume this path exists
            pass
        else:
            #assume Posix and find that command:
            r = rtc("which %s" % xpra_cmd)
            if r[2]!=0:
                continue
        if xpra_cmd in tried:
            continue
        tried.add(xpra_cmd)
        cmd = '"' + xpra_cmd + '" ' + ' '.join(shellquote(x) for x in xpra_proxy_command)
        if socket_dir:
            cmd += " \"--socket-dir=%s\"" % socket_dir
        if display_as_args:
            cmd += " "
            cmd += " ".join(shellquote(x) for x in display_as_args)
        log("cmd(%s, %s)=%s", xpra_proxy_command, display_as_args, cmd)

        #see https://github.com/paramiko/paramiko/issues/175
        #WINDOW_SIZE = 2097152
        log("trying to open SSH session, window-size=%i, timeout=%i", WINDOW_SIZE, TIMEOUT)
        try:
            chan = transport.open_session(window_size=WINDOW_SIZE, max_packet_size=0, timeout=TIMEOUT)
            chan.set_name("run-xpra")
        except SSHException as e:
            log("open_session", exc_info=True)
            raise InitExit(EXIT_SSH_FAILURE, "failed to open SSH session: %s" % e) from None
        else:
            log("channel exec_command(%s)" % cmd)
            chan.exec_command(cmd)
            return chan
    raise Exception("all SSH remote proxy commands have failed")


def ssh_connect_failed(_message):
    #by the time ssh fails, we may have entered the gtk main loop
    #(and more than once thanks to the clipboard code..)
    if "gtk" in sys.modules or "gi.repository.Gtk" in sys.modules:
        from xpra.gtk_common.quit import gtk_main_quit_really
        gtk_main_quit_really()


def ssh_exec_connect_to(display_desc, opts=None, debug_cb=None, ssh_fail_cb=ssh_connect_failed):
    if not ssh_fail_cb:
        ssh_fail_cb = ssh_connect_failed
    sshpass_command = None
    try:
        cmd = list(display_desc["full_ssh"])
        kwargs = {}
        env = display_desc.get("env")
        kwargs["stderr"] = sys.stderr
        if WIN32:
            from subprocess import CREATE_NEW_PROCESS_GROUP, CREATE_NEW_CONSOLE, STARTUPINFO, STARTF_USESHOWWINDOW
            startupinfo = STARTUPINFO()
            startupinfo.dwFlags |= STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0     #aka win32.con.SW_HIDE
            kwargs["startupinfo"] = startupinfo
            flags = CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
            kwargs["creationflags"] = flags
            kwargs["stderr"] = PIPE
        elif not display_desc.get("exit_ssh", False) and not OSX:
            kwargs["start_new_session"] = True
        remote_xpra = display_desc["remote_xpra"]
        assert remote_xpra
        socket_dir = display_desc.get("socket_dir")
        proxy_command = display_desc["proxy_command"]       #ie: "_proxy_start"
        display_as_args = display_desc["display_as_args"]   #ie: "--start=xterm :10"
        remote_cmd = ""
        for x in remote_xpra:
            if not remote_cmd:
                check = "if"
            else:
                check = "elif"
            if x=="xpra":
                #no absolute path, so use "which" to check that the command exists:
                pc = ['%s which "%s" > /dev/null 2>&1; then' % (check, x)]
            else:
                pc = ['%s [ -x %s ]; then' % (check, x)]
            pc += [x] + proxy_command + [shellquote(x) for x in display_as_args]
            if socket_dir:
                pc.append("--socket-dir=%s" % socket_dir)
            remote_cmd += " ".join(pc)+";"
        remote_cmd += "else echo \"no run-xpra command found\"; exit 1; fi"
        if INITENV_COMMAND:
            remote_cmd = INITENV_COMMAND + ";" + remote_cmd
        #how many times we need to escape the remote command string
        #depends on how many times the ssh command is parsed
        if MAGIC_QUOTES:
            nssh = sum(int(x=="ssh") for x in cmd)
            for _ in range(nssh):
                remote_cmd = shlex.quote(remote_cmd)
        else:
            remote_cmd = "'%s'" % remote_cmd
        cmd.append("sh -c %s" % remote_cmd)
        if debug_cb:
            debug_cb("starting %s tunnel" % str(cmd[0]))
        #non-string arguments can make Popen choke,
        #instead of lazily converting everything to a string, we validate the command:
        for x in cmd:
            if not isinstance(x, str):
                raise InitException("argument is not a string: %s (%s), found in command: %s" % (x, type(x), cmd))
        password = display_desc.get("password")
        if password and not display_desc.get("is_putty", False):
            from xpra.platform.paths import get_sshpass_command
            sshpass_command = get_sshpass_command()
            if sshpass_command:
                #sshpass -e ssh ...
                cmd.insert(0, sshpass_command)
                cmd.insert(1, "-e")
                if env is None:
                    env = os.environ.copy()
                env["SSHPASS"] = password
                #the password will be used by ssh via sshpass,
                #don't try to authenticate again over the ssh-proxy connection,
                #which would trigger warnings if the server does not require
                #authentication over unix-domain-sockets:
                opts.password = None
                del display_desc["password"]
        if env:
            kwargs["env"] = env
        if is_debug_enabled("ssh"):
            log.info("executing ssh command: %s" % (" ".join("\"%s\"" % x for x in cmd)))
        child = Popen(cmd, stdin=PIPE, stdout=PIPE, **kwargs)
    except OSError as e:
        raise InitExit(EXIT_SSH_FAILURE,
                       "Error running ssh command '%s': %s" % (" ".join("\"%s\"" % x for x in cmd), e))
    def abort_test(action):
        """ if ssh dies, we don't need to try to read/write from its sockets """
        e = child.poll()
        if e is not None:
            had_connected = conn.input_bytecount>0 or conn.output_bytecount>0
            if had_connected:
                error_message = "cannot %s using SSH" % action
            else:
                error_message = "SSH connection failure"
            sshpass_error = None
            if sshpass_command:
                sshpass_error = {
                                 1  : "Invalid command line argument",
                                 2  : "Conflicting arguments given",
                                 3  : "General runtime error",
                                 4  : "Unrecognized response from ssh (parse error)",
                                 5  : "Invalid/incorrect password",
                                 6  : "Host public key is unknown. sshpass exits without confirming the new key.",
                                 }.get(e)
                if sshpass_error:
                    error_message += ": %s" % sshpass_error
            if debug_cb:
                debug_cb(error_message)
            if ssh_fail_cb:
                ssh_fail_cb(error_message)
            if "ssh_abort" not in display_desc:
                display_desc["ssh_abort"] = True
                if not had_connected:
                    log.error("Error: SSH connection to the xpra server failed")
                    if sshpass_error:
                        log.error(" %s", sshpass_error)
                    else:
                        log.error(" check your username, hostname, display number, firewall, etc")
                    display_name = display_desc["display_name"]
                    log.error(" for server: %s", display_name)
                else:
                    log.error("The SSH process has terminated with exit code %s", e)
                cmd_info = " ".join(display_desc["full_ssh"])
                log.error(" the command line used was:")
                log.error(" %s", cmd_info)
            raise ConnectionClosedException(error_message) from None
    def stop_tunnel():
        if POSIX:
            #on posix, the tunnel may be shared with other processes
            #so don't kill it... which may leave it behind after use.
            #but at least make sure we close all the pipes:
            for name,fd in {
                            "stdin" : child.stdin,
                            "stdout" : child.stdout,
                            "stderr" : child.stderr,
                            }.items():
                try:
                    if fd:
                        fd.close()
                except Exception as e:
                    print("error closing ssh tunnel %s: %s" % (name, e))
            if not display_desc.get("exit_ssh", False):
                #leave it running
                return
        try:
            if child.poll() is None:
                child.terminate()
        except Exception as e:
            print("error trying to stop ssh tunnel process: %s" % e)
    host = display_desc["host"]
    port = display_desc.get("ssh-port", 22)
    username = display_desc.get("username")
    display = display_desc.get("display")
    info = {
        "host"  : host,
        "port"  : port,
        }
    from xpra.net.bytestreams import TwoFileConnection
    conn = TwoFileConnection(child.stdin, child.stdout,
                             abort_test, target=(host, port),
                             socktype="ssh", close_cb=stop_tunnel, info=info)
    conn.endpoint = host_target_string("ssh", username, host, port, display)
    conn.timeout = 0            #taken care of by abort_test
    conn.process = (child, "ssh", cmd)
    return conn
