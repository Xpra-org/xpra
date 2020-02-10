# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import socket
from subprocess import Popen, PIPE
from threading import Event
import paramiko

from xpra.net.ssh import SSHSocketConnection
from xpra.util import csv, envint, first_time
from xpra.os_util import osexpand, getuid, bytestostr, WIN32, POSIX, monotonic_time
from xpra.platform.paths import get_ssh_conf_dirs
from xpra.log import Logger

log = Logger("network", "ssh")

SERVER_WAIT = envint("XPRA_SSH_SERVER_WAIT", 20)
AUTHORIZED_KEYS = "~/.ssh/authorized_keys"
AUTHORIZED_KEYS_HASHES = os.environ.get("XPRA_AUTHORIZED_KEYS_HASHES", "md5,sha1,sha224,sha256,sha384,sha512").split(",")


class SSHServer(paramiko.ServerInterface):
    def __init__(self, none_auth=False, pubkey_auth=True, password_auth=None):
        self.event = Event()
        self.none_auth = none_auth
        self.pubkey_auth = pubkey_auth
        self.password_auth = password_auth
        self.proxy_channel = None

    def get_allowed_auths(self, username):
        #return "gssapi-keyex,gssapi-with-mic,password,publickey"
        mods = []
        if self.none_auth:
            mods.append("none")
        if self.pubkey_auth:
            mods.append("publickey")
        if self.password_auth:
            mods.append("password")
        log("get_allowed_auths(%s)=%s", username, mods)
        return ",".join(mods)

    def check_channel_request(self, kind, chanid):
        log("check_channel_request(%s, %s)", kind, chanid)
        if kind=="session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_none(self, username):
        log("check_auth_none(%s) none_auth=%s", username, self.none_auth)
        if self.none_auth:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username, password):
        log("check_auth_password(%s, %s) password_auth=%s", username, "*"*len(password), self.password_auth)
        if not self.password_auth or not self.password_auth(username, password):
            return paramiko.AUTH_FAILED
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        log("check_auth_publickey(%s, %r) pubkey_auth=%s", username, key, self.pubkey_auth)
        if not self.pubkey_auth:
            return paramiko.AUTH_FAILED
        if not POSIX or getuid()!=0:
            import getpass
            sysusername = getpass.getuser()
            if sysusername!=username:
                log.warn("Warning: ssh password authentication failed,")
                log.warn(" username does not match:")
                log.warn(" expected '%s', got '%s'", sysusername, username)
                return paramiko.AUTH_FAILED
        authorized_keys_filename = osexpand(AUTHORIZED_KEYS)
        if not os.path.exists(authorized_keys_filename) or not os.path.isfile(authorized_keys_filename):
            log("file '%s' does not exist", authorized_keys_filename)
            return paramiko.AUTH_FAILED
        import base64
        import binascii
        fingerprint = key.get_fingerprint()
        hex_fingerprint = binascii.hexlify(fingerprint)
        log("looking for key fingerprint '%s' in '%s'", hex_fingerprint, authorized_keys_filename)
        count = 0
        with open(authorized_keys_filename, "rb") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                line = line.strip("\n\r")
                try:
                    key = base64.b64decode(line.strip().split()[1].encode('ascii'))
                except Exception as e:
                    log("ignoring line '%s': %s", line, e)
                    continue
                import hashlib
                for hash_algo in AUTHORIZED_KEYS_HASHES:
                    hash_instance = None
                    try:
                        hash_class = getattr(hashlib, hash_algo) #ie: hashlib.md5
                        hash_instance = hash_class(key)     #can raise ValueError (ie: on FIPS compliant systems)
                    except ValueError:
                        hash_instance = None
                    if not hash_instance:
                        if first_time("hash-%s-missing" % hash_algo):
                            log.warn("Warning: unsupported hash '%s'", hash_algo)
                        continue
                    fp_plain = hash_instance.hexdigest()
                    log("%s(%s)=%s", hash_algo, line, fp_plain)
                    if fp_plain==hex_fingerprint:
                        return paramiko.OPEN_SUCCEEDED
                count += 1
        log("no match in %i keys from '%s'", count, authorized_keys_filename)
        return paramiko.AUTH_FAILED

    def check_auth_gssapi_keyex(self, username, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None):
        log("check_auth_gssapi_keyex%s", (username, gss_authenticated, cc_file))
        return paramiko.AUTH_FAILED

    def check_auth_gssapi_with_mic(self, username, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None):
        log("check_auth_gssapi_with_mic%s", (username, gss_authenticated, cc_file))
        return paramiko.AUTH_FAILED

    def check_channel_shell_request(self, channel):
        log("check_channel_shell_request(%s)", channel)
        return False

    def check_channel_exec_request(self, channel, command):
        def chan_send(send_fn, data, timeout=5):
            start = monotonic_time()
            while data and monotonic_time()-start<timeout:
                sent = send_fn(data)
                if not sent:
                    break
                data = data[sent:]
        #TODO: close channel after use? when?
        log("check_channel_exec_request(%s, %s)", channel, command)
        try:
            cmd = shlex.split(command.decode("utf8"))
        except UnicodeDecodeError:
            cmd = shlex.split(bytestostr(command))
        if cmd[0] in ("type", "which") and len(cmd)==2:
            xpra_cmd = cmd[1]   #ie: $XDG_RUNTIME_DIR/xpra/run-xpra or "xpra"
            if not POSIX:
                assert WIN32
                #we can't execute "type" or "which" on win32,
                #so we just answer as best we can
                #and only accept "xpra" as argument:
                if xpra_cmd.strip("\"")=="xpra":
                    chan_send(channel.send, "xpra is xpra")
                    channel.send_exit_status(0)
                else:
                    chan_send(channel.send_stderr, "type: %s: not found" % xpra_cmd)
                    channel.send_exit_status(1)
                return True
            #we don't want to use a shell,
            #but we need to expand the file argument:
            cmd[1] = osexpand(xpra_cmd)
            try:
                proc = Popen(cmd, stdout=PIPE, stderr=PIPE, close_fds=not WIN32)
                out, err = proc.communicate()
            except Exception as e:
                log("check_channel_exec_request(%s, %s)", channel, command, exc_info=True)
                chan_send(channel.send_stderr, "failed to execute command: %s" % e)
                channel.send_exit_status(1)
            else:
                chan_send(channel.send, out)
                chan_send(channel.send_stderr, err)
                channel.send_exit_status(proc.returncode)
        elif cmd[0].endswith("xpra") and len(cmd)>=2:
            subcommand = cmd[1].strip("\"'").rstrip(";")
            log("ssh xpra subcommand: %s", subcommand)
            if subcommand!="_proxy":
                log.warn("Warning: unsupported xpra subcommand '%s'", cmd[1])
                return False
            #we're ready to use this socket as an xpra channel
            self._run_proxy(channel)
        else:
            #plain 'ssh' clients execute a long command with if+else statements,
            #try to detect it and extract the actual command the client is trying to run.
            #ie:
            #['sh', '-c',
            # ': run-xpra _proxy;xpra initenv;\
            #  if [ -x $XDG_RUNTIME_DIR/xpra/run-xpra ]; then $XDG_RUNTIME_DIR/xpra/run-xpra _proxy;\
            #  elif [ -x ~/.xpra/run-xpra ]; then ~/.xpra/run-xpra _proxy;\
            #  elif type "xpra" > /dev/null 2>&1; then xpra _proxy;\
            #  elif [ -x /usr/local/bin/xpra ]; then /usr/local/bin/xpra _proxy;\
            #  else echo "no run-xpra command found"; exit 1; fi']
            #if .* ; then .*/run-xpra _proxy;
            log("parse cmd=%s (len=%i)", cmd, len(cmd))
            if len(cmd)==1:         #ie: 'thelongcommand'
                parse_cmd = cmd[0]
            elif len(cmd)==3 and cmd[:2]==["sh", "-c"]:     #ie: 'sh' '-c' 'thelongcommand'
                parse_cmd = cmd[2]
            else:
                parse_cmd = ""
            #for older clients, try to parse the long command
            #and identify the subcommands from there
            subcommands = []
            for s in parse_cmd.split("if "):
                if (s.startswith("type \"xpra\"") or s.startswith("which \"xpra\"") or s.startswith("[ -x")) and s.find("then ")>0:
                    then_str = s.split("then ", 1)[1]
                    #ie: then_str="$XDG_RUNTIME_DIR/xpra/run-xpra _proxy; el"
                    if then_str.find(";")>0:
                        then_str = then_str.split(";")[0]
                    parts = shlex.split(then_str)
                    if len(parts)>=2:
                        subcommand = parts[1]       #ie: "_proxy"
                        subcommands.append(subcommand)
            log("subcommands=%s", subcommands)
            if subcommands and tuple(set(subcommands))[0]=="_proxy":
                self._run_proxy(channel)
            else:
                log.warn("Warning: unsupported ssh command:")
                log.warn(" %s", cmd)
                return False
        return True

    def _run_proxy(self, channel):
        pc = self.proxy_channel
        if pc:
            self.proxy_channel = None
            pc.close()
        self.proxy_channel = channel
        self.event.set()

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        log("check_channel_pty_request%s", (channel, term, width, height, pixelwidth, pixelheight, modes))
        return False

    def enable_auth_gssapi(self):
        log("enable_auth_gssapi()")
        return False


def make_ssh_server_connection(conn, socket_options, none_auth=False, password_auth=None):
    log("make_ssh_server_connection%s", (conn, socket_options, none_auth, password_auth))
    ssh_server = SSHServer(none_auth=none_auth, password_auth=password_auth)
    DoGSSAPIKeyExchange = False
    sock = conn._socket
    t = None
    def close():
        if t:
            log("close() closing %s", t)
            try:
                t.close()
            except Exception:
                log("%s.close()", t, exc_info=True)
        log("close() closing %s", conn)
        try:
            conn.close()
        except Exception:
            log("%s.close()", conn)
    try:
        t = paramiko.Transport(sock, gss_kex=DoGSSAPIKeyExchange)
        gss_host = socket_options.get("ssh-gss-host", socket.getfqdn(""))
        t.set_gss_host(gss_host)
        #load host keys:
        PREFIX = "ssh_host_"
        SUFFIX = "_key"
        host_keys = {}
        def add_host_key(fd, f):
            ff = os.path.join(fd, f)
            keytype = f[len(PREFIX):-len(SUFFIX)]
            if not keytype:
                log.warn("Warning: unknown host key format '%s'", f)
                return False
            keyclass = getattr(paramiko, "%sKey" % keytype.upper(), None)
            if keyclass is None:
                #Ed25519Key
                keyclass = getattr(paramiko, "%s%sKey" % (keytype[:1].upper(), keytype[1:]), None)
            if keyclass is None:
                log("key type %s is not supported, cannot load '%s'", keytype, ff)
                return False
            log("loading %s key from '%s' using %s", keytype, ff, keyclass)
            try:
                host_key = keyclass(filename=ff)
                if host_key not in host_keys:
                    host_keys[host_key] = ff
                    t.add_server_key(host_key)
                    return True
            except IOError as e:
                log("cannot add host key '%s'", ff, exc_info=True)
            except paramiko.SSHException as e:
                log("error adding host key '%s'", ff, exc_info=True)
                log.error("Error: cannot add %s host key '%s':", keytype, ff)
                log.error(" %s", e)
            return False
        host_key = socket_options.get("ssh-host-key")
        if host_key:
            d, f = os.path.split(host_key)
            if f.startswith(PREFIX) and f.endswith(SUFFIX):
                add_host_key(d, f)
            if not host_keys:
                log.error("Error: failed to load host key '%s'", host_key)
                close()
                return None
        else:
            ssh_key_dirs = get_ssh_conf_dirs()
            log("trying to load ssh host keys from: %s", csv(ssh_key_dirs))
            for d in ssh_key_dirs:
                fd = osexpand(d)
                log("osexpand(%s)=%s", d, fd)
                if not os.path.exists(fd) or not os.path.isdir(fd):
                    log("ssh host key directory '%s' is invalid", fd)
                    continue
                for f in os.listdir(fd):
                    if f.startswith(PREFIX) and f.endswith(SUFFIX):
                        add_host_key(fd, f)
            if not host_keys:
                log.error("Error: cannot start SSH server,")
                log.error(" no readable SSH host keys found in:")
                log.error(" %s", csv(ssh_key_dirs))
                close()
                return None
        log("loaded host keys: %s", tuple(host_keys.values()))
        t.start_server(server=ssh_server)
    except (paramiko.SSHException, EOFError) as e:
        log("failed to start ssh server", exc_info=True)
        log.error("Error handling SSH connection:")
        log.error(" %s", e)
        close()
        return None
    try:
        chan = t.accept(SERVER_WAIT)
        if chan is None:
            log.warn("Warning: SSH channel setup failed")
            #prevent errors trying to access this connection, now likely dead:
            conn.set_active(False)
            close()
            return None
    except paramiko.SSHException as e:
        log("failed to open ssh channel", exc_info=True)
        log.error("Error opening channel:")
        log.error(" %s", e)
        close()
        return None
    log("client authenticated, channel=%s", chan)
    ssh_server.event.wait(SERVER_WAIT)
    log("proxy channel=%s", ssh_server.proxy_channel)
    if not ssh_server.event.is_set() or not ssh_server.proxy_channel:
        from xpra.net.bytestreams import pretty_socket
        log.warn("Warning: timeout waiting for xpra SSH subcommand,")
        log.warn(" closing connection from %s", pretty_socket(conn.target))
        close()
        return None
    log("client authenticated, channel=%s", chan)
    return SSHSocketConnection(ssh_server.proxy_channel, sock, conn.local, conn.endpoint, conn.target)
