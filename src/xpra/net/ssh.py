# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time
import os
import socket

from subprocess import PIPE, Popen

from xpra.log import Logger
log = Logger("network", "ssh")

from xpra.scripts.main import InitException, InitExit
from xpra.platform.paths import get_xpra_command
from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT, ConnectionClosedException
from xpra.exit_codes import EXIT_SSH_KEY_FAILURE, EXIT_SSH_FAILURE
from xpra.os_util import bytestostr, osexpand, monotonic_time, setsid, WIN32, OSX, POSIX
from xpra.util import envint, envbool, nonl, engs

INITENV_COMMAND = os.environ.get("XPRA_INITENV_COMMAND", "xpra initenv")
SSH_DEBUG = envbool("XPRA_SSH_DEBUG", False)
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


def ssh_target_string(display_desc):
    target = "ssh://"
    username = display_desc.get("username")
    if username:
        target += "%s@" % username
    host = display_desc.get("host")
    target += host
    ssh_port = display_desc.get("ssh-port")
    if ssh_port:
        target += ":%i" % ssh_port
    display = display_desc.get("display")
    target += "/%s" % (display or "")
    return target


def keymd5(k):
    import binascii
    f = bytestostr(binascii.hexlify(k.get_fingerprint()))
    s = "MD5"
    while f:
        s += ":"+f[:2]
        f = f[2:]
    return s


def exec_dialog_subprocess(cmd):
    try:
        log("exec_dialog_subprocess(%s)", cmd)
        proc = Popen(cmd, stdin=None, stdout=PIPE, stderr=PIPE, close_fds=True)
        stdout, stderr = proc.communicate()
        log("exec_dialog_subprocess(%s)", cmd)
        if stderr:
            log.warn("Warning: dialog process error output:")
            for x in stderr.splitlines():
                log.warn(" %s", x)
        return proc.returncode, stdout
    except Exception as e:
        log("exec_dialog_subprocess(..)", exc_info=True)
        log.error("Error: failed to execute the dialog subcommand")
        log.error(" %s", e)
        return -1, None

def dialog_pass(title="Password Input", prompt="enter password", icon=""):
    cmd = get_xpra_command()+["_pass", nonl(title), nonl(prompt), icon]
    return exec_dialog_subprocess(cmd)

def dialog_confirm(title, prompt, qinfo="", icon="", buttons=[("OK", 1)]):
    cmd = get_xpra_command()+["_dialog", nonl(title), nonl(prompt), nonl("\\n".join(qinfo)), icon]
    for label, code in buttons:
        cmd.append(nonl(label))
        cmd.append(str(code))
    return exec_dialog_subprocess(cmd)

def confirm_key(info=[]):
    if SKIP_UI:
        return False
    from xpra.platform.paths import get_icon_filename
    from xpra.os_util import use_tty
    if not use_tty():
        icon = get_icon_filename("authentication", "png")
        prompt = "Are you sure you want to continue connecting?"
        code, out = dialog_confirm("Confirm Key", prompt, info, icon, buttons=[("yes", 200), ("NO", 201)])
        log.debug("dialog output: '%s', return code=%s", nonl(out), code)
        r = code==200
        log.info("host key %sconfirmed", ["not ", ""][r])
        return r
    prompt = "Are you sure you want to continue connecting (yes/NO)? "
    sys.stderr.write(os.linesep.join(info)+os.linesep+prompt)
    v = sys.stdin.readline().rstrip(os.linesep)
    return v and v.lower() in ("y", "yes")

def input_pass(prompt):
    if SKIP_UI:
        return None
    from xpra.platform.paths import get_icon_filename
    from xpra.os_util import use_tty
    if not use_tty():
        icon = get_icon_filename("authentication", "png")
        code, out = dialog_pass("Password Input", prompt, icon)
        log.debug("pass dialog output return code=%s", code)
        if code!=0:
            return None
        return out
    from getpass import getpass
    return getpass(prompt)


class SSHSocketConnection(SocketConnection):

    def __init__(self, ssh_channel, sock, target, info={}):
        SocketConnection.__init__(self, ssh_channel, sock.getsockname(), sock.getpeername(), target, "ssh", info)
        self._raw_socket = sock

    def start_stderr_reader(self):
        from xpra.make_thread import start_thread
        start_thread(self._stderr_reader, "ssh-stderr-reader", daemon=True)

    def _stderr_reader(self):
        #stderr = self._socket.makefile_stderr(mode="rb", bufsize=1)
        chan = self._socket
        stderr = chan.makefile_stderr("rb", 1)
        while self.active:
            v = stderr.readline()
            if not v:
                log("SSH EOF on stderr of %s", chan.get_name())
                return
            log.warn("SSH stderr: %s", v)

    def peek(self, n):
        return self._raw_socket.recv(n, socket.MSG_PEEK)

    def get_socket_info(self):
        return self.do_get_socket_info(self._raw_socket)

    def get_info(self):
        i = SocketConnection.get_info(self)
        s = self._socket
        if s:
            i["ssh-channel"] = {
                "id"    : s.get_id(),
                "name"  : s.get_name(),
                }
        return i


def ssh_paramiko_connect_to(display_desc):
    #plain socket attributes:
    dtype = display_desc["type"]
    host = display_desc["host"]
    port = display_desc.get("ssh-port", 22)
    ipv6 = display_desc.get("ipv6", False)
    from xpra.scripts.main import socket_connect
    sock = socket_connect(dtype, host, port, ipv6)
    #ssh and command attributes:
    username = display_desc.get("username")
    if not username:
        import getpass
        username = getpass.getuser()
    password = display_desc.get("password")
    target = ssh_target_string(display_desc)
    remote_xpra = display_desc["remote_xpra"]
    proxy_command = display_desc["proxy_command"]       #ie: "_proxy_start"
    socket_dir = display_desc.get("socket_dir")
    display_as_args = display_desc["display_as_args"]   #ie: "--start=xterm :10"
    return do_ssh_paramiko_connect_to(sock, host, port, username, password, proxy_command, remote_xpra, socket_dir, display_as_args, target)

def do_ssh_paramiko_connect_to(sock, host, port, username, password, proxy_command, remote_xpra, socket_dir, display_as_args, target):
    from paramiko import SSHException, Transport, Agent, RSAKey, PasswordRequiredException
    from paramiko.hostkeys import HostKeys
    transport = Transport(sock)
    transport.use_compression(False)
    log("SSH transport %s", transport)
    try:
        transport.start_client()
    except SSHException:
        raise InitException("SSH negotiation failed")

    host_key = transport.get_remote_server_key()
    assert host_key, "no remote server key"
    log("remote_server_key=%s", keymd5(host_key))
    if VERIFY_HOSTKEY:
        host_keys = HostKeys()
        host_keys_filename = None
        for known_hosts in ("~/.ssh/known_hosts", "~/ssh/known_hosts"):
            host_keys.clear()
            try:
                path = os.path.expanduser(known_hosts)
                if os.path.exists(path):
                    host_keys.load(path)
                    log("HostKeys.load(%s) successful", known_hosts)
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
            if known_host_key:
                log.warn("Warning: SSH server key mismatch")
                qinfo = [
"WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!",
"IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!",
"Someone could be eavesdropping on you right now (man-in-the-middle attack)!",
"It is also possible that a host key has just been changed.",
"The fingerprint for the %s key sent by the remote host is" % keyname(),
keymd5(host_key),
]
                if VERIFY_STRICT:
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
                if not confirm_key(qinfo):
                    transport.close()
                    raise InitExit(EXIT_SSH_KEY_FAILURE, "Unknown SSH host '%s'" % host)

            if ADD_KEY:
                log("adding %s key for host '%s' to '%s'", keyname(), host, host_keys_filename)
                try:
                    host_keys.add(host, host_key.get_name(), host_key)
                    host_keys.save(host_keys_filename)
                except OSError as e:
                    log("failed to add key to '%s'", host_keys_filename)
                    log.error("Error adding key to '%s'", host_keys_filename)
                    log.error(" %s", e)


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
                    log("agent key '%s' rejected", agent_key, exc_info=True)
            if not transport.is_authenticated():
                log.info("agent authentication failed, tried %i key%s", len(agent_keys), engs(agent_keys))

    def auth_pulickey():
        log("trying public key authentication")
        for keyfile in ("id_rsa", "id_dsa"):
            keyfile_path = osexpand(os.path.join("~/", ".ssh", keyfile))
            if not os.path.exists(keyfile_path):
                log("no keyfile at '%s'", keyfile_path)
                continue
            key = None
            try:
                key = RSAKey.from_private_key_file(keyfile_path)
            except PasswordRequiredException:
                log("%s keyfile requires a passphrase", keyfile_path)
                passphrase = input_pass("please enter the passphrase for %s:" % (keyfile_path,))
                if passphrase:
                    try:
                        key = RSAKey.from_private_key_file(keyfile_path, passphrase)
                    except SSHException as e:
                        log("from_private_key_file", exc_info=True)
                        log.info("cannot load key from file '%s':", keyfile_path)
                        log.info(" %s", e)
            if key:
                log("auth_publickey using %s: %s", keyfile_path, keymd5(key))
                try:
                    transport.auth_publickey(username, key)
                except SSHException as e:
                    log("key '%s' rejected", keyfile_path, exc_info=True)
                    log.info("SSH authentication using key '%s' failed:", keyfile_path)
                    log.info(" %s", e)
                else:
                    break

    def auth_none():
        log("trying none authentication")
        try:
            transport.auth_none(username)
        except SSHException as e:
            log("auth_none()", exc_info=True)

    def auth_password():
        log("trying password authentication")
        try:
            transport.auth_password(username, password)
        except SSHException as e:
            log("auth_password(..)", exc_info=True)
            log.info("SSH password authentication failed: %s", e)

    banner = transport.get_banner()
    if banner:
        log.info("SSH server banner:")
        for x in banner.splitlines():
            log.info(" %s", x)

    log("starting authentication")
    if not transport.is_authenticated() and NONE_AUTH:
        auth_none()

    if not transport.is_authenticated() and PASSWORD_AUTH and password:
        auth_password()

    if not transport.is_authenticated() and AGENT_AUTH:
        auth_agent()

    if not transport.is_authenticated() and KEY_AUTH:
        auth_pulickey()

    if not transport.is_authenticated() and PASSWORD_AUTH and not password:
        password = input_pass("please enter the SSH password for %s@%s" % (username, host))
        if password:
            auth_password()
            if not transport.is_authenticated():
                #prompt for password again?
                #only if password auth is accepted?
                pass

    if not transport.is_authenticated():
        transport.close()
        raise InitException("SSH Authentication failed")

    assert len(remote_xpra)>0
    log("will try to run xpra from: %s", remote_xpra)
    for xpra_cmd in remote_xpra:
        try:
            chan = transport.open_session(window_size=None, max_packet_size=0, timeout=60)
            chan.set_name("find %s" % xpra_cmd)
        except SSHException as e:
            log("open_session", exc_info=True)
            raise InitException("failed to open SSH session: %s" % e)
        cmd = "type %s" % xpra_cmd
        log("exec_command('%s')", cmd)
        chan.exec_command(cmd)
        #poll until the command terminates:
        start = monotonic_time()
        while not chan.exit_status_ready():
            if monotonic_time()-start>10:
                chan.close()
                raise InitException("SSH test command '%s' timed out" % cmd)
            log("exit status is not ready yet, sleeping")
            time.sleep(0.01)
        r = chan.recv_exit_status()
        log("exec_command('%s')=%s", cmd, r)
        chan.close()
        if r!=0:
            continue
        cmd = xpra_cmd + " " + " ".join("\"%s\"" % x for x in proxy_command)
        if socket_dir:
            cmd += " \"--socket-dir=%s\"" % socket_dir
        if display_as_args:
            cmd += " "
            cmd += " ".join("\"%s\"" % x for x in display_as_args)

        #see https://github.com/paramiko/paramiko/issues/175
        #WINDOW_SIZE = 2097152
        log("trying to open SSH session, window-size=%i, timeout=%i", WINDOW_SIZE, TIMEOUT)
        try:
            chan = transport.open_session(window_size=WINDOW_SIZE, max_packet_size=0, timeout=TIMEOUT)
            chan.set_name("run-xpra")
        except SSHException as e:
            log("open_session", exc_info=True)
            raise InitException("failed to open SSH session: %s" % e)
        else:
            log("channel exec_command(%s)" % cmd)
            chan.exec_command(cmd)
            info = {
                "host"  : host,
                "port"  : port,
                }
            conn = SSHSocketConnection(chan, sock, target, info)
            conn.timeout = SOCKET_TIMEOUT
            conn.start_stderr_reader()
            child = None
            conn.process = (child, "ssh", cmd)
            return conn
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
        cmd = display_desc["full_ssh"]
        kwargs = {}
        env = display_desc.get("env")
        kwargs["stderr"] = sys.stderr
        if WIN32:
            from subprocess import CREATE_NEW_PROCESS_GROUP, CREATE_NEW_CONSOLE
            flags = CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
            kwargs["creationflags"] = flags
            kwargs["stderr"] = PIPE
        elif not display_desc.get("exit_ssh", False) and not OSX:
            kwargs["preexec_fn"] = setsid
        remote_xpra = display_desc["remote_xpra"]
        assert len(remote_xpra)>0
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
                #no absolute path, so use "type" to check that the command exists:
                pc = ['%s type "%s" > /dev/null 2>&1; then' % (check, x)]
            else:
                pc = ['%s [ -x %s ]; then' % (check, x)]
            pc += [x] + proxy_command + display_as_args
            if socket_dir:
                pc.append("--socket-dir=%s" % socket_dir)
            remote_cmd += " ".join(pc)+";"
        remote_cmd += "else echo \"no run-xpra command found\"; exit 1; fi"
        if INITENV_COMMAND:
            remote_cmd = INITENV_COMMAND + ";" + remote_cmd
        #putty gets confused if we wrap things in shell command:
        if display_desc.get("is_putty", False):
            cmd.append(remote_cmd)
        else:
            #openssh doesn't have this problem,
            #and this gives us better compatibility with weird login shells
            cmd.append("sh -c '%s'" % remote_cmd)
        if debug_cb:
            debug_cb("starting %s tunnel" % str(cmd[0]))
            #debug_cb("starting ssh: %s with kwargs=%s" % (str(cmd), kwargs))
        #non-string arguments can make Popen choke,
        #instead of lazily converting everything to a string, we validate the command:
        for x in cmd:
            if type(x)!=str:
                raise InitException("argument is not a string: %s (%s), found in command: %s" % (x, type(x), cmd))
        password = display_desc.get("password")
        if password:
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
        if SSH_DEBUG:
            sys.stdout.write("executing ssh command: %s\n" % (" ".join("\"%s\"" % x for x in cmd)))
        child = Popen(cmd, stdin=PIPE, stdout=PIPE, **kwargs)
    except OSError as e:
        raise InitExit(EXIT_SSH_FAILURE, "Error running ssh command '%s': %s" % (" ".join("\"%s\"" % x for x in cmd), e))
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
            raise ConnectionClosedException(error_message)
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
    info = {
        "host"  : display_desc["host"],
        "port"  : display_desc.get("ssh-port", 22),
        }
    from xpra.net.bytestreams import TwoFileConnection
    target = ssh_target_string(display_desc)
    conn = TwoFileConnection(child.stdin, child.stdout, abort_test, target=target, socktype="ssh", close_cb=stop_tunnel, info=info)
    conn.timeout = 0            #taken care of by abort_test
    conn.process = (child, "ssh", cmd)
    return conn
