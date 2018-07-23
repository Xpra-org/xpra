# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import socket
import paramiko

from subprocess import Popen, PIPE
from threading import Event

from xpra.log import Logger
log = Logger("network", "ssh")

from xpra.net.ssh import SSHSocketConnection
from xpra.util import csv, envint
from xpra.os_util import osexpand, WIN32


SSH_KEY_DIRS = "/etc/ssh", "/usr/local/etc/ssh", "~/.ssh", "~/ssh/"
SERVER_WAIT = envint("XPRA_SSH_SERVER_WAIT", 20)


class SSHServer(paramiko.ServerInterface):
    def __init__(self, none_auth=False, pubkey_auth=True, password_auth=None):
        self.event = Event()
        self.none_auth = none_auth
        self.pubkey_auth = pubkey_auth
        self.password_auth = password_auth
        self.proxy_channel = None

    def get_allowed_auths(self, username):
        log("get_allowed_auths(%s)", username)
        #return "gssapi-keyex,gssapi-with-mic,password,publickey"
        mods = []
        if self.none_auth:
            mods.append("none")
        if self.pubkey_auth:
            mods.append("publickey")
        if self.password_auth:
            mods.append("password")
        return csv(mods)

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
        #TODO: verify key
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
        #TODO: close channel after use? when?
        log("check_channel_exec_request(%s, %s)", channel, command)
        cmd = shlex.split(command)
        if cmd[0]=="type" and len(cmd)==2:
            #we don't want to use a shell,
            #but we need to expand the file argument:
            cmd[1] = osexpand(cmd[1])
            try:
                proc = Popen(cmd, stdin=None, stdout=PIPE, stderr=PIPE, close_fds=not WIN32, shell=False)
                out, err = proc.communicate()
            except Exception as e:
                log("check_channel_exec_request(%s, %s)", channel, command, exc_info=True)
                channel.send_stderr("failed to execute command: %s", e)
                channel.send_exit_status(1)
            else:
                while out:
                    sent = channel.send(out)
                    if not sent:
                        break
                    out = out[sent:]
                while err:
                    sent = channel.send_stderr(err)
                    if not sent:
                        break
                    err = err[sent:]
                channel.send_exit_status(proc.returncode)
        elif cmd[0].endswith("xpra") and len(cmd)>=2:
            subcommand = cmd[1].strip("\"'")
            log("ssh xpra subcommand: %s", subcommand)
            if subcommand=="_proxy":
                #we're ready to use this socket as an xpra channel
                pc = self.proxy_channel
                if pc:
                    self.proxy_channel = None
                    pc.close()
                self.proxy_channel = channel
                self.event.set()
            else:
                log.warn("Warning: unsupported xpra subcommand '%s'", cmd[1])
                return False
        else:
            log.warn("Warning: unsupported ssh command:")
            log.warn(" %s", cmd)
            return False
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        log("check_channel_pty_request%s", (channel, term, width, height, pixelwidth, pixelheight, modes))
        return False

    def enable_auth_gssapi(self):
        log("enable_auth_gssapi()")
        return False


def make_ssh_server_connection(conn, password_auth=None):
    log("make_ssh_server_connection(%s)", conn)
    ssh_server = SSHServer(password_auth=password_auth)
    DoGSSAPIKeyExchange = False
    try:
        t = paramiko.Transport(conn._socket, gss_kex=DoGSSAPIKeyExchange)
        t.set_gss_host(socket.getfqdn(""))
        host_keys = {}
        log("trying to load ssh host keys from: %s", csv(SSH_KEY_DIRS))
        for d in SSH_KEY_DIRS:
            fd = osexpand(d)
            log("osexpand(%s)=%s", d, fd)
            if not os.path.exists(fd) or not os.path.isdir(fd):
                log("ssh host key directory '%s' is invalid", fd)
                continue
            for f in os.listdir(fd):
                PREFIX = "ssh_host_"
                SUFFIX = "_key"
                if f.startswith(PREFIX) and f.endswith(SUFFIX):
                    ff = os.path.join(fd, f)
                    keytype = f[len(PREFIX):-len(SUFFIX)]
                    if keytype:
                        keyclass = getattr(paramiko, "%sKey" % keytype.upper(), None)
                        if keyclass is None:
                            #Ed25519Key
                            keyclass = getattr(paramiko, "%s%sKey" % (keytype[:1].upper(), keytype[1:]), None)
                        if keyclass is None:
                            log("key type %s is not supported, cannot load '%s'", keytype, ff)
                            continue
                        log("loading %s key from '%s' using %s", keytype, ff, keyclass)
                        try:
                            host_key = keyclass(filename=ff)
                            if host_key not in host_keys:
                                host_keys[host_key] = ff
                                t.add_server_key(host_key)
                        except IOError as e:
                            log("cannot add host key '%s'", ff, exc_info=True)
                        except paramiko.SSHException as e:
                            log("error adding host key '%s'", ff, exc_info=True)
                            log.error("Error: cannot add %s host key '%s':", keytype, ff)
                            log.error(" %s", e)
        if not host_keys:
            log.error("Error: cannot start SSH server,")
            log.error(" no SSH host keys found in:")
            log.error(" %s", csv(SSH_KEY_DIRS))
            t.close()
            conn.close()
            return None
        log("loaded host keys: %s", tuple(host_keys.values()))
        t.start_server(server=ssh_server)
    except paramiko.SSHException as e:
        log("failed to start ssh server", exc_info=True)
        log.error("Error handling SSH connection:")
        log.error(" %s", e)
        t.close()
        conn.close()
        return None
    try:
        chan = t.accept(SERVER_WAIT)
        if chan is None:
            log.warn("Warning: SSH channel setup failed")
            t.close()
            conn.close()
            return None
    except paramiko.SSHException as e:
        log("failed to open ssh channel", exc_info=True)
        log.error("Error opening channel:")
        log.error(" %s", e)
        t.close()
        conn.close()
        return None
    log("client authenticated, channel=%s", chan)
    ssh_server.event.wait(SERVER_WAIT)
    log("proxy channel=%s", ssh_server.proxy_channel)
    if not ssh_server.event.is_set() or not ssh_server.proxy_channel:
        log.error("Error: timeout waiting for xpra SSH subcommand")
        t.close()
        conn.close()
        return None
    #log("client authenticated, channel=%s", chan)
    return SSHSocketConnection(ssh_server.proxy_channel, conn._socket, target="ssh client")
