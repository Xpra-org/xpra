# This file is part of Xpra.
# Copyright (C) 2018-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import shlex
from subprocess import PIPE, Popen

from xpra.scripts.main import (
    InitException, InitExit,
    shellquote, host_target_string,
    )
from xpra.net.bytestreams import ConnectionClosedException
from xpra.make_thread import start_thread
from xpra.exit_codes import ExitCode
from xpra.os_util import (
    bytestostr,
    restore_script_env, get_saved_env,
    WIN32, OSX, POSIX,
    )
from xpra.util import envbool
from xpra.log import Logger, is_debug_enabled

#pylint: disable=import-outside-toplevel

log = Logger("network", "ssh")
if log.is_debug_enabled():
    import logging
    logging.getLogger("paramiko").setLevel(logging.DEBUG)

INITENV_COMMAND = os.environ.get("XPRA_INITENV_COMMAND", "")    #"xpra initenv"
MAGIC_QUOTES = envbool("XPRA_SSH_MAGIC_QUOTES", True)


def connect_failed(_message):
    #by the time ssh fails, we may have entered the gtk main loop
    #(and more than once thanks to the clipboard code..)
    if "gi.repository.Gtk" in sys.modules:
        import gi
        gi.require_version("Gtk", "3.0")  # @UndefinedVariable
        from gi.repository import Gtk  # @UnresolvedImport
        Gtk.main_quit()


def connect_to(display_desc, opts=None, debug_cb=None, ssh_fail_cb=None):
    if not ssh_fail_cb:
        ssh_fail_cb = connect_failed
    sshpass_command = None
    cmd = list(display_desc["full_ssh"])
    kwargs = {}
    env = display_desc.get("env")
    if env is None:
        env = get_saved_env()
    if display_desc.get("is_putty"):
        # special env used by plink:
        env = os.environ.copy()
        env["PLINK_PROTOCOL"] = "ssh"
    kwargs["stderr"] = sys.stderr
    try:
        if WIN32:
            from subprocess import (
                CREATE_NEW_PROCESS_GROUP, CREATE_NEW_CONSOLE, STARTUPINFO, STARTF_USESHOWWINDOW,  # @UnresolvedImport
                )
            startupinfo = STARTUPINFO()
            startupinfo.dwFlags |= STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0     #aka win32.con.SW_HIDE
            flags = CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
            kwargs.update({
                "startupinfo"   : startupinfo,
                "creationflags" : flags,
                "stderr"        : PIPE,
                })
        elif not display_desc.get("exit_ssh", False) and not OSX:
            kwargs["start_new_session"] = True
        remote_xpra = display_desc["remote_xpra"]
        assert remote_xpra
        socket_dir = display_desc.get("socket_dir")
        proxy_command = display_desc["proxy_command"]       #ie: ["_proxy_start"]
        display_as_args = display_desc["display_as_args"]   #ie: ["--start=xterm", "--env=SSH_AGENT_UUID={uuid}", ":10"]
        remote_cmd = ""
        for x in remote_xpra:
            check = "if" if not remote_cmd else "elif"
            if x=="xpra":
                #no absolute path, so use "command -v" to check that the command exists:
                pc = [f'{check} command -v "{x}" > /dev/null 2>&1; then']
            else:
                pc = [f'{check} [ -x {x} ]; then']
            pc += [x] + proxy_command + [shellquote(x) for x in display_as_args]
            if socket_dir:
                pc.append(f"--socket-dir={socket_dir}")
            remote_cmd += " ".join(pc)+";"
        remote_cmd += "else echo \"no run-xpra command found\"; exit 1; fi"
        if INITENV_COMMAND:
            remote_cmd = INITENV_COMMAND + ";" + remote_cmd
        #how many times we need to escape the remote command string
        #depends on how many times the ssh command is parsed
        nssh = sum(int(x=="ssh") for x in cmd)
        if nssh>=2 and MAGIC_QUOTES:
            for _ in range(nssh):
                remote_cmd = shlex.quote(remote_cmd)
        else:
            remote_cmd = f"'{remote_cmd}'"
        cmd.append(f"sh -c {remote_cmd}")
        if debug_cb:
            debug_cb(f"starting {cmd[0]} tunnel")
        #non-string arguments can make Popen choke,
        #instead of lazily converting everything to a string, we validate the command:
        for x in cmd:
            if not isinstance(x, str):
                raise InitException(f"argument is not a string: {x} ({type(x)}), found in command: {cmd}")
        password = display_desc.get("password")
        if password and not display_desc.get("is_putty", False):
            from xpra.platform.paths import get_sshpass_command
            sshpass_command = get_sshpass_command()
            if sshpass_command:
                #sshpass -e ssh ...
                cmd.insert(0, sshpass_command)
                cmd.insert(1, "-e")
                env["SSHPASS"] = password
                #the password will be used by ssh via sshpass,
                #don't try to authenticate again over the ssh-proxy connection,
                #which would trigger warnings if the server does not require
                #authentication over unix-domain-sockets:
                opts.password = None
                del display_desc["password"]

        kwargs["env"] = restore_script_env(env)

        if is_debug_enabled("ssh"):
            log.info("executing ssh command: " + " ".join(f"\"{x}\"" for x in cmd))
        child = Popen(cmd, stdin=PIPE, stdout=PIPE, **kwargs)
    except OSError as e:
        cmd_info = " ".join(repr(x) for x in cmd)
        raise InitExit(ExitCode.SSH_FAILURE,
                       f"Error running ssh command {cmd_info!r}: {e}") from None
    def abort_test(action):
        """ if ssh dies, we don't need to try to read/write from its sockets """
        e = child.poll()
        if e is not None:
            had_connected = conn.input_bytecount>0 or conn.output_bytecount>0
            if had_connected:
                error_message = f"cannot {action} using SSH"
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
                    error_message += f": {sshpass_error}"
            if debug_cb:
                debug_cb(error_message)
            if ssh_fail_cb:
                ssh_fail_cb(error_message)
            if "ssh_abort" not in display_desc:
                display_desc["ssh_abort"] = True
                if not had_connected:
                    log.error("Error: SSH connection to the xpra server failed")
                    if sshpass_error:
                        log.error(f" {sshpass_error}")
                    else:
                        log.error(" check your username, hostname, display number, firewall, etc")
                    display_name = display_desc["display_name"]
                    log.error(f" for server: {display_name}")
                else:
                    log.error(f"The SSH process has terminated with exit code {e}")
                cmd_info = " ".join(display_desc["full_ssh"])
                log.error(" the command line used was:")
                log.error(f" {cmd_info}")
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
                    log.error(f"Error closing ssh tunnel {name}: {e}")
            if not display_desc.get("exit_ssh", False):
                #leave it running
                return
        try:
            if child.poll() is None:
                child.terminate()
        except Exception as e:
            log.error(f"Error trying to stop ssh tunnel process: {e}")
    host = display_desc["host"]
    port = display_desc.get("port", 22)
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
    if kwargs.get("stderr")==PIPE:
        def stderr_reader():
            errs = []
            while child.poll() is None:
                try:
                    v = child.stderr.readline()
                except OSError:
                    log("stderr_reader()", exc_info=True)
                    break
                if not v:
                    log(f"SSH EOF on stderr of {cmd}")
                    break
                s = bytestostr(v).rstrip("\n\r")
                if s:
                    errs.append(s)
            if errs:
                log.warn("remote SSH stderr:")
                for e in errs:
                    log.warn(f" {e}")
        start_thread(stderr_reader, "ssh-stderr-reader", daemon=True)
    return conn
