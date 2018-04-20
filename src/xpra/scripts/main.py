#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import stat
import socket
from time import sleep
import logging
from subprocess import Popen, PIPE
import signal
import shlex
import traceback

from xpra.platform.dotxpra import DotXpra
from xpra.util import csv, envbool, envint, DEFAULT_PORT
from xpra.exit_codes import EXIT_SSL_FAILURE, EXIT_SSH_FAILURE, EXIT_STR
from xpra.os_util import get_util_logger, getuid, getgid, monotonic_time, setsid, bytestostr, WIN32, OSX, POSIX
from xpra.scripts.parsing import info, warn, error, \
    parse_vsock, parse_env, is_local, \
    fixup_defaults, validated_encodings, validate_encryption, do_parse_cmdline, show_sound_codec_help, \
    supports_shadow, supports_server, supports_proxy, supports_mdns
from xpra.scripts.config import OPTION_TYPES, CLIENT_OPTIONS, NON_COMMAND_LINE_OPTIONS, CLIENT_ONLY_OPTIONS, START_COMMAND_OPTIONS, BIND_OPTIONS, PROXY_START_OVERRIDABLE_OPTIONS, OPTIONS_ADDED_SINCE_V1, \
    InitException, InitInfo, InitExit, \
    fixup_options, dict_to_validated_config, \
    make_defaults_struct, parse_bool, has_sound_support, name_to_field
assert info and warn and error, "used by modules importing those from here"

NO_ROOT_WARNING = envbool("XPRA_NO_ROOT_WARNING", False)
INITENV_COMMAND = os.environ.get("XPRA_INITENV_COMMAND", "xpra initenv")
CLIPBOARD_CLASS = os.environ.get("XPRA_CLIPBOARD_CLASS")
SSH_DEBUG = envbool("XPRA_SSH_DEBUG", False)
WAIT_SERVER_TIMEOUT = envint("WAIT_SERVER_TIMEOUT", 15)
SYSTEMD_RUN = envbool("XPRA_SYSTEMD_RUN", True)
LOG_SYSTEMD_WRAP = envbool("XPRA_LOG_SYSTEMD_WRAP", True)
VERIFY_X11_SOCKET_TIMEOUT = envint("XPRA_VERIFY_X11_SOCKET_TIMEOUT", 1)


def nox():
    DISPLAY = os.environ.get("DISPLAY")
    if DISPLAY is not None:
        del os.environ["DISPLAY"]
    # This is an error on Fedora/RH, so make it an error everywhere so it will
    # be noticed:
    import warnings
    warnings.filterwarnings("error", "could not open display")
    return DISPLAY


def main(script_file, cmdline):
    from xpra.platform import clean as platform_clean, command_error, command_info, get_main_fallback
    if len(cmdline)==1:
        fm = get_main_fallback(cmdline[0])
        if fm:
            return fm()

    def debug_exc(msg="run_mode error"):
        get_util_logger().debug(msg, exc_info=True)

    try:
        try:
            defaults = make_defaults_struct()
            fixup_defaults(defaults)
            options, args = do_parse_cmdline(cmdline, defaults)
            if not args:
                raise InitExit(-1, "xpra: need a mode")
            mode = args.pop(0)
            def err(*args):
                raise InitException(*args)
            return run_mode(script_file, err, options, args, mode, defaults)
        except SystemExit:
            debug_exc()
            raise
        except InitExit as e:
            debug_exc()
            if str(e) and e.args and (e.args[0] or len(e.args)>1):
                command_info("%s" % e)
            return e.status
        except InitInfo as e:
            debug_exc()
            command_info("%s" % e)
            return 0
        except InitException as e:
            debug_exc()
            command_error("xpra initialization error:\n %s" % e)
            return 1
        except AssertionError as e:
            debug_exc()
            command_error("xpra initialization error:\n %s" % e)
            traceback.print_tb(sys.exc_info()[2])
            return 1
        except Exception:
            debug_exc()
            command_error("xpra main error:\n%s" % traceback.format_exc())
            return 1
    finally:
        platform_clean()


def configure_logging(options, mode):
    if mode in ("showconfig", "info", "id", "control", "list", "list-mdns", "sessions", "mdns-gui", "attach", "stop", "print", "opengl", "test-connect"):
        s = sys.stdout
    else:
        s = sys.stderr
    to = s
    if sys.version_info[0]==3:
        try:
            import codecs
            #print("locale.getpreferredencoding()=%s" % (locale.getpreferredencoding(),))
            #python3 has a buffer attribute,
            #which we must use if we want to be able to write bytes:
            sbuf = getattr(s, "buffer", s)
            to = codecs.getwriter("utf-8")(sbuf, "replace")
        except:
            pass
    #a bit naughty here, but it's easier to let xpra.log initialize
    #the logging system every time, and just undo things here..
    from xpra.log import setloghandler, enable_color, enable_format, LOG_FORMAT, NOPREFIX_FORMAT
    setloghandler(logging.StreamHandler(to))
    if mode in ("start", "start-desktop", "upgrade", "attach", "shadow", "proxy", "_sound_record", "_sound_play", "stop", "print", "showconfig", "request-start", "request-start-desktop", "request-shadow"):
        if "help" in options.speaker_codec or "help" in options.microphone_codec:
            info = show_sound_codec_help(mode!="attach", options.speaker_codec, options.microphone_codec)
            raise InitInfo("\n".join(info))
        fmt = LOG_FORMAT
        if mode in ("stop", "showconfig"):
            fmt = NOPREFIX_FORMAT
        if envbool("XPRA_COLOR_LOG", hasattr(to, "fileno") and os.isatty(to.fileno())):
            enable_color(to, fmt)
        else:
            enable_format(fmt)

    from xpra.log import add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for
    if options.debug:
        categories = options.debug.split(",")
        for cat in categories:
            if len(cat)==0:
                continue
            if cat[0]=="-":
                add_disabled_category(cat[1:])
                disable_debug_for(cat[1:])
            else:
                add_debug_category(cat)
                enable_debug_for(cat)

    #always log debug level, we just use it selectively (see above)
    logging.root.setLevel(logging.DEBUG)

    #register posix signals for debugging:
    if POSIX:
        from xpra.util import dump_all_frames, dump_gc_frames
        def idle_add(fn, *args):
            from xpra.gtk_common.gobject_compat import import_glib
            glib = import_glib()
            glib.idle_add(fn, *args)
        def sigusr1(*_args):
            info = get_util_logger().info
            info("SIGUSR1")
            idle_add(dump_all_frames, info)
        def sigusr2(*_args):
            info = get_util_logger().info
            info("SIGUSR2")
            idle_add(dump_gc_frames, info)
        signal.signal(signal.SIGUSR1, sigusr1)
        signal.signal(signal.SIGUSR2, sigusr2)

def configure_network(options):
    from xpra.net import compression, packet_encoding
    ecs = compression.get_enabled_compressors()
    for c in compression.ALL_COMPRESSORS:
        enabled = c in ecs and c in options.compressors
        setattr(compression, "use_%s" % c, enabled)
    if not ecs:
        #force compression level to zero since we have no compressors available:
        options.compression_level = 0
    ees = packet_encoding.get_enabled_encoders()
    count = 0
    for pe in packet_encoding.ALL_ENCODERS:
        enabled = pe in ees and pe in options.packet_encoders
        setattr(packet_encoding, "use_%s" % pe, enabled)
        count += int(enabled)
    #verify that at least one encoder is available:
    if not count:
        raise InitException("at least one valid packet encoder must be enabled")

def configure_env(env_str):
    if env_str:
        env = parse_env(env_str)
        if POSIX and getuid()==0:
            #running as root!
            #sanitize: only allow "safe" environment variables
            #as these may have been specified by a non-root user
            env = dict((k,v) for k,v in env.items() if k.startswith("XPRA_"))
        os.environ.update(env)


def systemd_run_command(mode, systemd_run_args, user=True):
    cmd = ["systemd-run", "--description" , "xpra-%s" % mode, "--scope"]
    if user:
        cmd.append("--user")
    if not LOG_SYSTEMD_WRAP:
        cmd.append("--quiet")
    if systemd_run_args:
        cmd += shlex.split(systemd_run_args)
    return cmd

def systemd_run_wrap(mode, args, systemd_run_args):
    cmd = systemd_run_command(mode, systemd_run_args)
    cmd += args
    cmd.append("--systemd-run=no")
    if LOG_SYSTEMD_WRAP:
        stderr = sys.stderr
        try:
            stderr.write("using systemd-run to wrap '%s' server command\n" % mode)
            stderr.write("%s\n" % " ".join(["'%s'" % x for x in cmd]))
        except:
            pass
    try:
        p = Popen(cmd)
        p.wait()
    except KeyboardInterrupt:
        return 128+signal.SIGINT


def isdisplaytype(args, dtype):
    return len(args)>0 and (args[0].startswith("%s/" % dtype) or args[0].startswith("%s:" % dtype))

def run_mode(script_file, error_cb, options, args, mode, defaults):
    #configure default logging handler:
    if POSIX and getuid()==0 and options.uid==0 and mode!="proxy" and not NO_ROOT_WARNING:
        warn("\nWarning: running as root")

    ssh_display = isdisplaytype(args, "ssh")
    tcp_display = isdisplaytype(args, "tcp")
    ssl_display = isdisplaytype(args, "ssl")
    vsock_display = isdisplaytype(args, "vsock")
    display_is_remote = ssh_display or tcp_display or ssl_display or vsock_display

    if mode in ("start", "start_desktop", "shadow") and not display_is_remote:
        systemd_run = parse_bool("systemd-run", options.systemd_run)
        if systemd_run is None:
            #detect:
            from xpra.os_util import is_systemd_pid1
            systemd_run = is_systemd_pid1()
        if systemd_run:
            #check if we have wrapped it already (or if disabled via env var)
            if SYSTEMD_RUN:
                return systemd_run_wrap(mode, sys.argv, options.systemd_run_args)

    configure_env(options.env)
    configure_logging(options, mode)
    configure_network(options)

    if not mode.startswith("_sound_"):
        #only the sound subcommands should ever actually import GStreamer:
        try:
            from xpra.sound.gstreamer_util import prevent_import
            prevent_import()
        except:
            pass
        #sound commands don't want to set the name
        #(they do it later to prevent glib import conflicts)
        #"attach" does it when it received the session name from the server
        if mode not in ("attach", "start", "start-desktop", "upgrade", "proxy", "shadow"):
            from xpra.platform import set_name
            set_name("Xpra", "Xpra %s" % mode.strip("_"))

    if mode in ("start", "start-desktop", "shadow", "attach", "request-start", "request-start-desktop", "request-shadow"):
        options.encodings = validated_encodings(options.encodings)

    try:
        if mode in ("start", "start-desktop", "shadow") and display_is_remote:
            #ie: "xpra start ssh:HOST:DISPLAY --start-child=xterm"
            return run_remote_server(error_cb, options, args, mode, defaults)
        elif (mode in ("start", "start-desktop", "upgrade") and supports_server) or \
            (mode=="shadow" and supports_shadow) or (mode=="proxy" and supports_proxy):
            try:
                cwd = os.getcwd()
            except:
                cwd = "/"
            env = os.environ.copy()
            start_via_proxy = parse_bool("start-via-proxy", options.start_via_proxy)
            if start_via_proxy is not False and (not POSIX or getuid()!=0) and options.daemon:
                try:
                    from xpra import client
                    assert client
                except ImportError as e:
                    if start_via_proxy is True:
                        error_cb("cannot start-via-proxy: xpra client is not installed")
                else:
                    err = None
                    try:
                        #this will use the client "start-new-session" feature,
                        #to start a new session and connect to it at the same time:
                        app = get_client_app(error_cb, options, args, "request-%s" % mode)
                        r = do_run_client(app)
                        from xpra.exit_codes import EXIT_OK, EXIT_FAILURE
                        #OK or got a signal:
                        NO_RETRY = [EXIT_OK] + range(128, 128+16)
                        if app.completed_startup:
                            #if we had connected to the session,
                            #we can ignore more error codes:
                            from xpra.exit_codes import EXIT_CONNECTION_LOST, EXIT_REMOTE_ERROR, EXIT_INTERNAL_ERROR, EXIT_FILE_TOO_BIG
                            NO_RETRY += [
                                    EXIT_CONNECTION_LOST,
                                    EXIT_REMOTE_ERROR,
                                    EXIT_INTERNAL_ERROR,
                                    EXIT_FILE_TOO_BIG,
                                    ]
                        if r in NO_RETRY:
                            return r
                        elif r==EXIT_FAILURE:
                            err = "unknown general failure"
                        else:
                            err = EXIT_STR.get(r, r)
                    except Exception as e:
                        err = str(e)
                    if start_via_proxy is True:
                        raise InitException("failed to start-via-proxy: %s" % err)
                    #warn and fall through to regular server start:
                    warn("Warning: cannot use the system proxy for '%s' subcommand," % (mode, ))
                    warn(" %s" % (err,))
                    warn(" more information may be available in your system log")
                    #re-exec itself and disable start-via-proxy:
                    args = sys.argv[:]+["--start-via-proxy=no"]
                    #warn("re-running with: %s" % (args,))
                    os.execv(args[0], args)
                    #this code should be unreachable!
                    return 1
            current_display = nox()
            try:
                from xpra import server
                assert server
                from xpra.scripts.server import run_server, add_when_ready
            except ImportError as e:
                error_cb("Xpra server is not installed")
            if options.attach is True:
                def attach_client():
                    from xpra.platform.paths import get_xpra_command
                    cmd = get_xpra_command()+["attach"]
                    display_name = os.environ.get("DISPLAY")
                    if display_name:
                        cmd += [display_name]
                    #options has been "fixed up", make sure this has too:
                    fixup_options(defaults)
                    for x in CLIENT_OPTIONS:
                        f = x.replace("-", "_")
                        try:
                            d = getattr(defaults, f)
                            c = getattr(options, f)
                        except Exception as e:
                            print("error on %s: %s" % (f, e))
                            continue
                        if c!=d:
                            if OPTION_TYPES.get(x)==list:
                                v = csv(c)
                            else:
                                v = str(c)
                            cmd.append("--%s=%s" % (x, v))
                    preexec_fn = None
                    if POSIX and not OSX:
                        preexec_fn = setsid
                    proc = Popen(cmd, close_fds=True, preexec_fn=preexec_fn, cwd=cwd, env=env)
                    from xpra.child_reaper import getChildReaper
                    getChildReaper().add_process(proc, "client-attach", cmd, ignore=True, forget=False)
                add_when_ready(attach_client)
            return run_server(error_cb, options, mode, script_file, args, current_display)
        elif mode in ("attach", "detach", "screenshot", "version", "info", "id", "control", "_monitor", "print", "connect-test", "request-start", "request-start-desktop", "request-shadow"):
            return run_client(error_cb, options, args, mode)
        elif mode in ("stop", "exit"):
            nox()
            return run_stopexit(mode, error_cb, options, args)
        elif mode == "list":
            return run_list(error_cb, options, args)
        elif mode == "list-mdns" and supports_mdns:
            return run_list_mdns(error_cb, args)
        elif mode == "mdns-gui" and supports_mdns:
            return run_mdns_gui(error_cb, options)
        elif mode == "sessions":
            return run_sessions_gui(error_cb, options)
        elif mode in ("_proxy", "_proxy_start", "_proxy_start_desktop", "_shadow_start") and (supports_server or supports_shadow):
            nox()
            return run_proxy(error_cb, options, script_file, args, mode, defaults)
        elif mode in ("_sound_record", "_sound_play", "_sound_query"):
            if not has_sound_support():
                error_cb("no sound support!")
            from xpra.sound.wrapper import run_sound
            return run_sound(mode, error_cb, options, args)
        elif mode=="opengl":
            return run_glcheck(options)
        elif mode == "initenv":
            from xpra.server.server_util import xpra_runner_shell_script, write_runner_shell_scripts
            script = xpra_runner_shell_script(script_file, os.getcwd(), options.socket_dir)
            write_runner_shell_scripts(script, False)
            return 0
        elif mode == "showconfig":
            return run_showconfig(options, args)
        else:
            error_cb("invalid mode '%s'" % mode)
            return 1
    except KeyboardInterrupt as e:
        info("\ncaught %s, exiting" % repr(e))
        return 128+signal.SIGINT


def find_session_by_name(opts, session_name):
    from xpra.platform.paths import get_nodock_command
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
    socket_paths = dotxpra.socket_paths(check_uid=getuid(), matching_state=DotXpra.LIVE)
    if not socket_paths:
        return None
    id_sessions = {}
    for socket_path in socket_paths:
        cmd = get_nodock_command()+["id", "socket://%s" % socket_path]
        proc = Popen(cmd, stdin=None, stdout=PIPE, stderr=PIPE, shell=False)
        id_sessions[socket_path] = proc
    now = monotonic_time()
    import time
    while any(proc.poll() is None for proc in id_sessions.values()) and monotonic_time()-now<10:
        time.sleep(0.5)
    session_uuid_to_path = {}
    for socket_path, proc in id_sessions.items():
        if proc.poll()==0:
            out, err = proc.communicate()
            d = {}
            for line in bytestostr(out or err).splitlines():
                try:
                    k,v = line.split("=", 1)
                    d[k] = v
                except ValueError:
                    continue
            name = d.get("session-name")
            uuid = d.get("uuid")
            if name==session_name and uuid:
                session_uuid_to_path[uuid] = socket_path
    if not session_uuid_to_path:
        return None
    if len(session_uuid_to_path)>1:
        raise InitException("more than one session found matching '%s'" % session_name)
    return "socket://%s" % tuple(session_uuid_to_path.values())[0]

def parse_display_name(error_cb, opts, display_name, session_name_lookup=False):
    desc = {"display_name" : display_name}
    #split the display name on ":" or "/"
    scpos = display_name.find(":")
    slpos = display_name.find("/")
    if scpos<0 and slpos<0:
        if session_name_lookup:
            #try to find a session whose "session-name" matches:
            match = find_session_by_name(opts, display_name)
            if match:
                display_name = match
                scpos = display_name.find(":")
                slpos = display_name.find("/")
    if scpos<0 and slpos<0:
        error_cb("unknown format for display name: %s" % display_name)
    if scpos<0:
        pos = slpos
    elif slpos<0:
        pos = scpos
    else:
        pos = min(scpos, slpos)
    protocol = display_name[:pos]
    #the separator between the protocol and the rest can be ":", "/" or "://"
    #but the separator value we use thereafter can only be ":" or "/"
    #because we want strings like ssl://host:port/DISPLAY to be parsed into ["ssl", "host:port", "DISPLAY"]
    psep = ""
    if display_name[pos]==":":
        psep += ":"
        pos += 1
    scount = 0
    while display_name[pos]=="/" and scount<2:
        psep += "/"
        pos += 1
        scount += 1
    if protocol=="socket":
        #socket paths may start with a slash!
        #so socket:/path means that the slash is part of the path
        if psep==":/":
            psep = psep[:-1]
            pos -= 1
    if psep not in (":", "/", "://"):
        error_cb("unknown format for protocol separator '%s' in display name: %s" % (psep, display_name))
    afterproto = display_name[pos:]         #ie: "host:port/DISPLAY"
    separator = psep[-1]                    #ie: "/"
    parts = afterproto.split(separator)     #ie: "host:port", "DISPLAY"

    def parse_username_and_password(s):
        ppos = s.find(":")
        if ppos>=0:
            password = s[ppos+1:]
            username = s[:ppos]
        else:
            username = s
            password = ""
        #fugly: we override the command line option after parsing the string:
        if username:
            desc["username"] = username
            opts.username = username
        if password:
            opts.password = password
            desc["password"] = password
        return username, password

    def parse_host_string(host, default_port=DEFAULT_PORT):
        """
            Parses [username[:password]@]host[:port]
            and returns username, password, host, port
            missing arguments will be empty (username and password) or 0 (port)
        """
        upos = host.rfind("@")
        username = None
        password = None
        port = default_port
        if upos>=0:
            #HOST=username@host
            username, password = parse_username_and_password(host[:upos])
            host = host[upos+1:]
        port_str = None
        if host.count(":")>=2:
            #more than 2 ":", assume this is IPv6:
            if host.startswith("["):
                #if we have brackets, we can support: "[HOST]:SSHPORT"
                epos = host.find("]")
                if epos<0:
                    error_cb("invalid host format, expected IPv6 [..]")
                port_str = host[epos+1:]        #ie: ":22"
                if port_str.startswith(":"):
                    port_str = port_str[1:]     #ie: "22"
                host = host[:epos+1]            #ie: "[HOST]"
            else:
                devsep = host.split("%")        #ie: fe80::c1:ac45:7351:ea69%eth1:14500 -> ["fe80::c1:ac45:7351:ea69", "eth1:14500"]
                if len(devsep)==2:
                    parts = devsep[1].split(":", 1)     #ie: "eth1:14500" -> ["eth1", "14500"]
                    if len(parts)==2:
                        host = "%s%%%s" % (devsep[0], parts[0])
                        port_str = parts[1]     #ie: "14500"
                else:
                    parts = host.split(":")
                    if len(parts[-1])>4:
                        port_str = parts[-1]
                        host = ":".join(parts[:-1])
                    else:
                        #otherwise, we have to assume they are all part of IPv6
                        #we could count them at split at 8, but that would be just too fugly
                        pass
            desc["ipv6"] = True
        elif host.find(":")>0:
            host, port_str = host.split(":", 1)
        if port_str:
            try:
                port = int(port_str)
            except ValueError:
                error_cb("invalid port number specified: %s" % port_str)
        if port<=0 or port>=2**16:
            error_cb("invalid port number: %s" % port)
        desc["port"] = port
        if host=="":
            host = "127.0.0.1"
        desc["host"] = host
        desc["local"] = is_local(host)
        return username, password, host, port

    def parse_remote_display(s):
        if not s:
            return
        #strip anything after "?" or "#"
        #TODO: parse those attributes
        for x in ("?", "#"):
            s = s.split(x)[0]
        display = ":" + s
        desc["display"] = display
        opts.display = display
        desc["display_as_args"] = [display]

    if protocol=="ssh":
        desc.update({
                "type"             : "ssh",
                "proxy_command"    : ["_proxy"],
                "exit_ssh"         : opts.exit_ssh,
                 })
        desc["display"] = None
        desc["display_as_args"] = []
        if len(parts)>1:
            #ssh:HOST:DISPLAY or ssh/HOST/DISPLAY
            host = separator.join(parts[0:-1])
            if parts[-1]:
                parse_remote_display(parts[-1])
        else:
            #ssh:HOST or ssh/HOST
            host = parts[0]
        #ie: ssh=["/usr/bin/ssh", "-v"]
        ssh = shlex.split(opts.ssh)
        desc["ssh"] = ssh
        full_ssh = ssh

        #maybe restrict to win32 only?
        ssh_cmd = ssh[0].lower()
        is_putty = ssh_cmd.endswith("plink") or ssh_cmd.endswith("plink.exe")
        desc["is_putty"] = is_putty

        username, password, host, ssh_port = parse_host_string(host, 22)
        if password and is_putty:
            full_ssh += ["-pw", password]
        if username:
            desc["username"] = username
            opts.username = username
            full_ssh += ["-l", username]
        if ssh_port and ssh_port!=22:
            #grr why bother doing it different?
            desc["ssh-port"] = ssh_port
            if is_putty:
                #special env used by plink:
                env = os.environ.copy()
                env["PLINK_PROTOCOL"] = "ssh"
                desc["env"] = env
                full_ssh += ["-P", str(ssh_port)]
            else:
                full_ssh += ["-p", str(ssh_port)]

        full_ssh += ["-T", host]
        desc.update({
                     "host"     : host,
                     "full_ssh" : full_ssh
                     })
        desc["remote_xpra"] = opts.remote_xpra
        if opts.socket_dir:
            desc["socket_dir"] = opts.socket_dir
        if desc.get("password") is None and opts.password_file:
            for x in opts.password_file:
                if os.path.exists(x):
                    try:
                        with open(opts.password_file, "rb") as f:
                            desc["password"] = f.read()
                        break
                    except Exception as e:
                        warn("Error: failed to read the password file '%s':\n", x)
                        warn(" %s\n", e)
        return desc
    elif protocol=="socket":
        #use the socketfile specified:
        if afterproto.find("@")>=0:
            parts = afterproto.split("@")
            parse_username_and_password("@".join(parts[:-1]))
            sockfile = parts[-1]
        else:
            sockfile = afterproto
        desc.update({
                "type"          : "unix-domain",
                "local"         : True,
                "display"       : display_name,
                "socket_dir"    : os.path.basename(sockfile),
                "socket_dirs"   : opts.socket_dirs,
                "socket_path"   : sockfile,
                })
        opts.display = display_name
        return desc
    elif display_name.startswith(":"):
        desc.update({
                "type"          : "unix-domain",
                "local"         : True,
                "display"       : display_name,
                "socket_dirs"   : opts.socket_dirs})
        opts.display = display_name
        if opts.socket_dir:
            desc["socket_dir"] = opts.socket_dir
        return desc
    elif protocol in ("tcp", "ssl", "udp"):
        desc.update({
                     "type"     : protocol,
                     })
        if len(parts) not in (1, 2, 3):
            error_cb("invalid %s connection string, use %s/[username[:password]@]host[:port][/display] or %s:[username[:password]@]host[:port]" % (protocol * 3))
        #display (optional):
        if separator=="/" and len(parts)==2:
            parse_remote_display(parts[-1])
            parts = parts[:-1]
        host = ":".join(parts)
        username, password, host, port = parse_host_string(host)
        assert port>0, "no port specified in %s" % host
        return desc
    elif protocol=="vsock":
        #use the vsock specified:
        cid, iport = parse_vsock(afterproto)
        desc.update({
                "type"          : "vsock",
                "local"         : False,
                "display"       : display_name,
                "vsock"         : (cid, iport),
                })
        opts.display = display_name
        return desc
    elif protocol in ("ws", "wss"):
        try:
            import websocket
            assert websocket
        except ImportError as e:
            raise InitException("the websocket client module cannot be loaded: %s" % e)
        host = afterproto
        if host.find("?")>=0:
            host, _ = host.split("?", 1)
        if host.find("/")>=0:
            host, extra = host.split("/", 1)
        else:
            extra = ""
        username, password, host, port = parse_host_string(host)
        parse_remote_display(extra)
        desc.update({
                "type"          : protocol,     #"ws" or "wss"
                "host"          : host,
                "port"          : port,
                })
        return desc
    elif WIN32 or display_name.startswith("named-pipe:"):
        if afterproto.find("@")>=0:
            parts = afterproto.split("@")
            parse_username_and_password("@".join(parts[:-1]))
            pipe_name = parts[-1]
        else:
            pipe_name = afterproto
        desc.update({
                     "type"             : "named-pipe",
                     "local"            : True,
                     "display"          : "DISPLAY",
                     "named-pipe"       : pipe_name,
                     })
        opts.display = display_name
        return desc
    else:
        error_cb("unknown format for display name: %s" % display_name)

def pick_display(error_cb, opts, extra_args):
    if len(extra_args) == 0:
        # Pick a default server
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        dir_servers = dotxpra.socket_details(matching_state=DotXpra.LIVE)
        try:
            sockdir, display, sockpath = single_display_match(dir_servers, error_cb)
        except:
            if getuid()==0 and opts.system_proxy_socket:
                display = ":PROXY"
                sockdir = os.path.dirname(opts.system_proxy_socket)
                sockpath = opts.system_proxy_socket
            else:
                raise
        desc = {
            "local"             : True,
            "display"           : display,
            "display_name"      : display,
            }
        if WIN32:
            desc.update({
                "type"              : "named-pipe",
                "named-pipe"        : sockpath,
                })
        else:
            desc.update({
                "type"          : "unix-domain",
                "socket_dir"    : sockdir,
                "socket_path"   : sockpath,
                })
        return desc
    elif len(extra_args) == 1:
        return parse_display_name(error_cb, opts, extra_args[0], session_name_lookup=True)
    else:
        error_cb("too many arguments (%i): %s" % (len(extra_args), extra_args))

def single_display_match(dir_servers, error_cb, nomatch="cannot find any live servers to connect to"):
    #ie: {"/tmp" : [LIVE, "desktop-10", "/tmp/desktop-10"]}
    #aggregate all the different locations:
    allservers = []
    noproxy = []
    for sockdir, servers in dir_servers.items():
        for state, display, path in servers:
            if state==DotXpra.LIVE:
                allservers.append((sockdir, display, path))
                if not display.startswith(":proxy-"):
                    noproxy.append((sockdir, display, path))
    if len(allservers)==0:
        error_cb(nomatch)
    if len(allservers)>1:
        #maybe the same server is available under multiple paths
        displays = set([v[1] for v in allservers])
        if len(displays)==1:
            #they all point to the same display, use the first one:
            allservers = allservers[:1]
    if len(allservers)>1 and len(noproxy)>0:
        #try to ignore proxy instances:
        displays = set([v[1] for v in noproxy])
        if len(displays)==1:
            #they all point to the same display, use the first one:
            allservers = noproxy[:1]
    if len(allservers) > 1:
        error_cb("there are multiple servers running, please specify")
    assert len(allservers)==1
    sockdir, name, path = allservers[0]
    #ie: ("/tmp", "desktop-10", "/tmp/desktop-10")
    return sockdir, name, path


def _socket_connect(sock, endpoint, description, dtype, info={}):
    from xpra.net.bytestreams import SocketConnection, pretty_socket
    try:
        sock.connect(endpoint)
    except Exception as e:
        get_util_logger().debug("failed to connect using %s%s", sock.connect, endpoint, exc_info=True)
        raise InitException("failed to connect to '%s':\n %s" % (pretty_socket(endpoint), e))
    sock.settimeout(None)
    return SocketConnection(sock, sock.getsockname(), sock.getpeername(), description, dtype, info)

def connect_or_fail(display_desc, opts):
    try:
        return connect_to(display_desc, opts)
    except InitException:
        raise
    except InitExit:
        raise
    except InitInfo:
        raise
    except Exception as e:
        get_util_logger().debug("failed to connect", exc_info=True)
        raise InitException("connection failed: %s" % e)

def ssh_connect_failed(message):
    #by the time ssh fails, we may have entered the gtk main loop
    #(and more than once thanks to the clipboard code..)
    if "gtk" in sys.modules or "gi.repository.Gtk" in sys.modules:
        from xpra.gtk_common.quit import gtk_main_quit_really
        gtk_main_quit_really()


def connect_to(display_desc, opts=None, debug_cb=None, ssh_fail_cb=ssh_connect_failed):
    from xpra.net.bytestreams import SOCKET_TIMEOUT, VSOCK_TIMEOUT
    from xpra.net.common import ConnectionClosedException
    display_name = display_desc["display_name"]
    dtype = display_desc["type"]
    conn = None
    if dtype == "ssh":
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
                    log = get_util_logger()
                    if not had_connected:
                        log.error("Error: SSH connection to the xpra server failed")
                        if sshpass_error:
                            log.error(" %s", sshpass_error)
                        else:
                            log.error(" check your username, hostname, display number, firewall, etc")
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
        from xpra.net.bytestreams import TwoFileConnection
        info = {}
        target = "ssh://"
        username = display_desc.get("username")
        if username:
            target += "%s@" % username
        host = display_desc.get("host")
        info["host"] = host
        target += host
        ssh_port = display_desc.get("ssh-port")
        if ssh_port:
            info["port"] = ssh_port
            target += ":%i" % ssh_port
        display = display_desc.get("display")
        target += "/%s" % (display or "")
        conn = TwoFileConnection(child.stdin, child.stdout, abort_test, target=target, socktype=dtype, close_cb=stop_tunnel, info=info)
        conn.timeout = 0            #taken care of by abort_test
        conn.process = (child, "ssh", cmd)

    elif dtype == "unix-domain":
        if not hasattr(socket, "AF_UNIX"):
            raise InitException("unix domain sockets are not available on this operating system")
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(SOCKET_TIMEOUT)
        def sockpathfail_cb(msg):
            raise InitException(msg)
        sockpath = get_sockpath(display_desc, sockpathfail_cb)
        display_desc["socket_path"] = sockpath
        try:
            conn = _socket_connect(sock, sockpath, display_name, dtype)
            #now that we know it:
            if "socket_dir" not in display_desc:
                display_desc["socket_dir"] = os.path.dirname(sockpath)
        except (InitException, InitExit, InitInfo) as e:
            raise
        except Exception as e:
            raise InitException("cannot connect to %s: %s" % (sockpath, e))
        conn.timeout = SOCKET_TIMEOUT

    elif dtype == "named-pipe":
        pipe_name = display_desc["named-pipe"]
        if not WIN32:
            raise InitException("named pipes are only supported on MS Windows")
        import errno
        from xpra.platform.win32.dotxpra import PIPE_PATH, PIPE_ROOT
        from xpra.platform.win32.namedpipes.connection import NamedPipeConnection, connect_to_namedpipe
        if pipe_name.startswith(PIPE_ROOT):
            #absolute pipe path already specified
            path = pipe_name
        else:
            path = PIPE_PATH+pipe_name
        try:
            pipe_handle = connect_to_namedpipe(path)
        except Exception as e:
            if e[0]==errno.ENOENT:
                raise InitException("the named pipe '%s' does not exist" % pipe_name)
            raise InitException("failed to connect to the named pipe '%s':\n %s" % (pipe_name, e))
        conn = NamedPipeConnection(pipe_name, pipe_handle)
        conn.timeout = SOCKET_TIMEOUT

    elif dtype == "vsock":
        cid, iport = display_desc["vsock"]
        from xpra.net.vsock import connect_vsocket, CID_TYPES       #@UnresolvedImport
        sock = connect_vsocket(cid=cid, port=iport)
        sock.timeout = VSOCK_TIMEOUT
        sock.settimeout(None)
        from xpra.net.bytestreams import SocketConnection
        return SocketConnection(sock, "local", "host", (CID_TYPES.get(cid, cid), iport), dtype)

    elif dtype in ("tcp", "ssl", "ws", "wss", "udp"):
        if display_desc.get("ipv6"):
            assert socket.has_ipv6, "no IPv6 support"
            family = socket.AF_INET6
        else:
            family = socket.AF_INET
        host = display_desc["host"]
        port = display_desc["port"]
        info = {
            "host" : host,
            "port" : port,
            }
        try:
            addrinfo = socket.getaddrinfo(host, port, family)
        except Exception as e:
            raise InitException("cannot get %s address of %s: %s" % ({
                socket.AF_INET6 : "IPv6",
                socket.AF_INET  : "IPv4",
                }.get(family, family), (host, port), e))
        sockaddr = addrinfo[0][-1]
        if dtype=="udp":
            opts.mmap = False
            sock = socket.socket(family, socket.SOCK_DGRAM)
        else:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
        strict_host_check = display_desc.get("strict-host-check")
        if strict_host_check is False:
            opts.ssl_server_verify_mode = "none"
        conn = _socket_connect(sock, sockaddr, display_name, dtype, info)
        if dtype in ("ssl", "wss"):
            wrap_socket = ssl_wrap_socket_fn(opts, server_side=False)
            sock = wrap_socket(sock)
            assert sock, "failed to wrap socket %s" % sock
            conn._socket = sock
        conn.timeout = SOCKET_TIMEOUT

        #wrap in a websocket:
        if dtype in ("ws", "wss"):
            host = display_desc["host"]
            port = display_desc.get("port", 0)
            if port>0:
                host += ":%i" % port
            import websocket
            if envbool("XPRA_WEBSOCKET_DEBUG"):
                websocket.enableTrace(True)
            url = "%s://%s/" % (dtype, host)
            from xpra.net.bytestreams import Connection, log as connlog
            subprotocols = ["binary", "base64"]
            try:
                ws = websocket.create_connection(url, SOCKET_TIMEOUT, subprotocols=subprotocols, socket=sock)
            except (IndexError, ValueError) as e:
                connlog("websocket.create_connection%s", (url, SOCKET_TIMEOUT, subprotocols, sock), exc_info=True)
                raise InitException("websocket connection failed, not a websocket capable server port: %s" % e)
            class WebSocketClientConnection(Connection):
                def __init__(self, ws, target, socktype, info):
                    Connection.__init__(self, target, socktype, info)
                    self._socket = ws

                def peek(self, _n):
                    return None

                def untilConcludes(self, *args):
                    try:
                        return Connection.untilConcludes(self, *args)
                    except websocket.WebSocketTimeoutException as e:
                        raise ConnectionClosedException(e)

                def read(self, n):
                    #FIXME: we should try to honour n
                    return self._read(self._socket.recv)

                def write(self, buf):
                    return self._write(self._socket.send, buf)

                def close(self):
                    try:
                        i = self.get_socket_info()
                    except:
                        i = self._socket
                    connlog("%s.close() for socket=%s", self, i)
                    Connection.close(self)
                    self._socket.close()
                    self._socket = None
                    connlog("%s.close() done", self)

                def __repr__(self):
                    return "%s %s" % (self.socktype, self.target)

                def get_info(self):
                    d = Connection.get_info(self)
                    d["protocol-type"] = "websocket"
                    ws = self._socket
                    if ws:
                        d.update({
                                  "sub-protocol"    : ws.getsubprotocol() or "",
                                  "headers"         : ws.getheaders() or {},
                                  "fileno"          : ws.fileno(),
                                  "status"          : ws.getstatus(),
                                  "connected"       : ws.connected,
                                  })
                    return d
            return WebSocketClientConnection(ws, conn.target, {"ws" : "websocket", "wss" : "secure websocket"}.get(dtype, dtype), info)
    else:
        raise InitException("unsupported display type: %s" % dtype)
    return conn


def ssl_wrap_socket_fn(opts, server_side=True):
    if server_side and not opts.ssl_cert:
        raise InitException("you must specify an 'ssl-cert' file to use 'bind-ssl' sockets")
    import ssl
    if server_side:
        verify_mode = opts.ssl_client_verify_mode
    else:
        verify_mode = opts.ssl_server_verify_mode
    #ca-certs:
    ssl_ca_certs = opts.ssl_ca_certs
    if ssl_ca_certs=="default":
        ssl_ca_certs = None
    #parse verify-mode:
    ssl_cert_reqs = getattr(ssl, "CERT_%s" % verify_mode.upper(), None)
    if ssl_cert_reqs is None:
        values = [k[len("CERT_"):].lower() for k in dir(ssl) if k.startswith("CERT_")]
        raise InitException("invalid ssl-server-verify-mode '%s', must be one of: %s" % (verify_mode, csv(values)))
    #parse protocol:
    ssl_protocol = getattr(ssl, "PROTOCOL_%s" % (opts.ssl_protocol.upper().replace("V", "v")), None)
    if ssl_protocol is None:
        values = [k[len("PROTOCOL_"):] for k in dir(ssl) if k.startswith("PROTOCOL_")]
        raise InitException("invalid ssl-protocol '%s', must be one of: %s" % (opts.ssl_protocol, csv(values)))
    #cadata may be hex encoded:
    cadata = opts.ssl_ca_data
    if cadata:
        try:
            import binascii
            cadata = binascii.unhexlify(cadata)
        except:
            pass

    kwargs = {
              "server_side"             : server_side,
              "do_handshake_on_connect" : False,
              "suppress_ragged_eofs"    : True,
              }
    #parse ssl-verify-flags as CSV:
    ssl_verify_flags = 0
    for x in opts.ssl_verify_flags.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "VERIFY_"+x.upper(), None)
        if v is None:
            raise InitException("invalid ssl verify-flag: %s" % x)
        ssl_verify_flags |= v
    #parse ssl-options as CSV:
    ssl_options = 0
    for x in opts.ssl_options.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "OP_"+x.upper(), None)
        if v is None:
            raise InitException("invalid ssl option: %s" % x)
        ssl_options |= v

    context = ssl.SSLContext(ssl_protocol)
    context.set_ciphers(opts.ssl_ciphers)
    context.verify_mode = ssl_cert_reqs
    context.verify_flags = ssl_verify_flags
    context.options = ssl_options
    if opts.ssl_cert:
        context.load_cert_chain(certfile=opts.ssl_cert or None, keyfile=opts.ssl_key or None, password=None)
    if ssl_cert_reqs!=ssl.CERT_NONE:
        if server_side:
            purpose = ssl.Purpose.CLIENT_AUTH   #@UndefinedVariable
        else:
            purpose = ssl.Purpose.SERVER_AUTH   #@UndefinedVariable
            context.check_hostname = opts.ssl_check_hostname
            if context.check_hostname:
                if not opts.ssl_server_hostname:
                    raise InitException("ssl error: check-hostname is set but server-hostname is not")
                kwargs["server_hostname"] = opts.ssl_server_hostname
        context.load_default_certs(purpose)

        ssl_ca_certs = opts.ssl_ca_certs
        if not ssl_ca_certs or ssl_ca_certs.lower()=="default":
            context.set_default_verify_paths()
        elif not os.path.exists(ssl_ca_certs):
            raise InitException("invalid ssl-ca-certs file or directory: %s" % ssl_ca_certs)
        elif os.path.isdir(ssl_ca_certs):
            context.load_verify_locations(capath=ssl_ca_certs)
        else:
            assert os.path.isfile(ssl_ca_certs), "'%s' is not a valid ca file" % ssl_ca_certs
            context.load_verify_locations(cafile=ssl_ca_certs)
        #handle cadata:
        if cadata:
            #PITA: because of a bug in the ssl module, we can't pass cadata,
            #so we use a temporary file instead:
            import tempfile
            f = tempfile.NamedTemporaryFile(prefix='cadata')
            f.file.write(cadata)
            f.file.flush()
            context.load_verify_locations(cafile=f.name)
            f.close()
    elif opts.ssl_check_hostname and not server_side:
        raise InitException("cannot check hostname with verify mode %s" % verify_mode)
    wrap_socket = context.wrap_socket
    del opts
    def do_wrap_socket(tcp_socket):
        if WIN32:
            #on win32, setting the tcp socket to blocking doesn't work?
            #we still hit the following errors that we need to retry:
            from xpra.net import bytestreams
            bytestreams.CAN_RETRY_EXCEPTIONS = (ssl.SSLWantReadError, ssl.SSLWantWriteError)
        tcp_socket.setblocking(True)
        try:
            ssl_sock = wrap_socket(tcp_socket, **kwargs)
        except Exception as e:
            get_util_logger().debug("do_wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
            SSLEOFError = getattr(ssl, "SSLEOFError", None)
            if SSLEOFError and isinstance(e, SSLEOFError):
                return None
            raise InitExit(EXIT_SSL_FAILURE, "Cannot wrap socket %s: %s" % (tcp_socket, e))
        if not server_side:
            try:
                ssl_sock.do_handshake(True)
            except Exception as e:
                get_util_logger().debug("do_handshake", exc_info=True)
                SSLEOFError = getattr(ssl, "SSLEOFError", None)
                if SSLEOFError and isinstance(e, SSLEOFError):
                    return None
                raise InitExit(EXIT_SSL_FAILURE, "SSL handshake failed: %s" % e)
        return ssl_sock
    return do_wrap_socket


def get_sockpath(display_desc, error_cb):
    #if the path was specified, use that:
    sockpath = display_desc.get("socket_path")
    if not sockpath:
        #find the socket using the display:
        dotxpra = DotXpra(display_desc.get("socket_dir"), display_desc.get("socket_dirs"), display_desc.get("username", ""), display_desc.get("uid", 0), display_desc.get("gid", 0))
        display = display_desc["display"]
        dir_servers = dotxpra.socket_details(matching_state=DotXpra.LIVE, matching_display=display)
        _, _, sockpath = single_display_match(dir_servers, error_cb, nomatch="cannot find live server for display %s" % display)
    return sockpath

def run_client(error_cb, opts, extra_args, mode):
    if mode in ("attach", "detach") and len(extra_args)==1 and extra_args[0]=="all":
        #run this command for each display:
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        displays = dotxpra.displays(check_uid=getuid(), matching_state=DotXpra.LIVE)
        if not displays:
            sys.stdout.write("No xpra sessions found\n")
            return 1
        #we have to locate the 'all' command line argument,
        #so we can replace it with each display we find,
        #but some other command line arguments can take a value of 'all',
        #so we have to make sure that the one we find does not belong to the argument before
        index = None
        for i, arg in enumerate(sys.argv):
            if i==0 or arg!="all":
                continue
            prevarg = sys.argv[i-1]
            if prevarg[0]=="-" and (prevarg.find("=")<0 or len(prevarg)==2):
                #ie: [.., "--csc-modules", "all"] or [.., "-d", "all"]
                continue
            index = i
            break
        if not index:
            raise InitException("'all' command line argument could not be located")
        cmd = sys.argv[:index]+sys.argv[index+1:]
        for display in displays:
            dcmd = cmd + [display]
            Popen(dcmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, close_fds=not WIN32, shell=False)
        return
    app = get_client_app(error_cb, opts, extra_args, mode)
    return do_run_client(app)

def get_client_app(error_cb, opts, extra_args, mode):
    validate_encryption(opts)
    if mode=="screenshot":
        if len(extra_args)==0:
            error_cb("invalid number of arguments for screenshot mode")
        screenshot_filename = extra_args[0]
        extra_args = extra_args[1:]

    request_mode = None
    if mode in ("request-start", "request-start-desktop", "request-shadow"):
        request_mode = mode.replace("request-", "")

    try:
        from xpra import client
        assert client
    except ImportError as e:
        error_cb("Xpra client is not installed")

    if opts.compression_level < 0 or opts.compression_level > 9:
        error_cb("Compression level must be between 0 and 9 inclusive.")
    if opts.quality!=-1 and (opts.quality < 0 or opts.quality > 100):
        error_cb("Quality must be between 0 and 100 inclusive. (or -1 to disable)")

    def connect():
        desc = pick_display(error_cb, opts, extra_args)
        return connect_or_fail(desc, opts), desc

    if mode=="screenshot":
        from xpra.client.gobject_client_base import ScreenshotXpraClient
        app = ScreenshotXpraClient(connect(), opts, screenshot_filename)
    elif mode=="info":
        from xpra.client.gobject_client_base import InfoXpraClient
        app = InfoXpraClient(connect(), opts)
    elif mode=="id":
        from xpra.client.gobject_client_base import IDXpraClient
        app = IDXpraClient(connect(), opts)
    elif mode=="connect-test":
        from xpra.client.gobject_client_base import ConnectTestXpraClient
        app = ConnectTestXpraClient(connect(), opts)
    elif mode=="_monitor":
        from xpra.client.gobject_client_base import MonitorXpraClient
        app = MonitorXpraClient(connect(), opts)
    elif mode=="control":
        from xpra.client.gobject_client_base import ControlXpraClient
        if len(extra_args)<=1:
            error_cb("not enough arguments for 'control' mode")
        args = extra_args[1:]
        extra_args = extra_args[:1]
        app = ControlXpraClient(connect(), opts)
        app.set_command_args(args)
    elif mode=="print":
        from xpra.client.gobject_client_base import PrintClient
        if len(extra_args)<=1:
            error_cb("not enough arguments for 'print' mode")
        args = extra_args[1:]
        extra_args = extra_args[:1]
        app = PrintClient(connect(), opts)
        app.set_command_args(args)
    elif mode=="version":
        from xpra.client.gobject_client_base import VersionXpraClient
        app = VersionXpraClient(connect(), opts)
    elif mode=="detach":
        from xpra.client.gobject_client_base import DetachXpraClient
        app = DetachXpraClient(connect(), opts)
    elif request_mode and opts.attach is not True:
        from xpra.client.gobject_client_base import RequestStartClient
        sns = get_start_new_session_dict(opts, request_mode, extra_args)
        extra_args = ["socket:%s" % opts.system_proxy_socket]
        app = RequestStartClient(connect(), opts)
        app.hello_extra = {"connect" : False}
        app.start_new_session = sns
    else:
        try:
            from xpra.platform.gui import init as gui_init
            gui_init()
            app = make_client(error_cb, opts)
        except RuntimeError as e:
            #exceptions at this point are still initialization exceptions
            raise InitException(e.message)
        ehelp = "help" in opts.encodings
        if ehelp:
            from xpra.codecs.loader import PREFERED_ENCODING_ORDER
            opts.encodings = PREFERED_ENCODING_ORDER
        app.init(opts)
        if opts.encoding=="auto":
            opts.encoding = ""
        if opts.encoding or ehelp:
            err = opts.encoding and (opts.encoding not in app.get_encodings())
            info = ""
            if err and opts.encoding!="help":
                info = "invalid encoding: %s\n" % opts.encoding
            if opts.encoding=="help" or ehelp or err:
                from xpra.codecs.loader import encodings_help
                encodings = ["auto"] + app.get_encodings()
                raise InitInfo(info+"%s xpra client supports the following encodings:\n * %s" % (app.client_toolkit(), "\n * ".join(encodings_help(encodings))))
        def handshake_complete(*_args):
            log = get_util_logger()
            target = conn.target
            info = conn.get_info()
            host = info.get("host")
            if host:
                target = "%s" % host
                port = info.get("port")
                if port:
                    target += ":%s" % port
                target += " via %s" % conn.socktype
            log.info("Attached to %s", target)
            log.info(" (press Control-C to detach)\n")
        if hasattr(app, "after_handshake"):
            app.after_handshake(handshake_complete)
        app.init_ui(opts, extra_args)
        if request_mode:
            sns = get_start_new_session_dict(opts, request_mode, extra_args)
            extra_args = ["socket:%s" % opts.system_proxy_socket]
            app.hello_extra = {
                "start-new-session" : sns,
                "connect"           : True,
                }
        try:
            conn, display_desc = connect()
            #UGLY warning: connect will parse the display string,
            #which may change the username and password..
            app.username = opts.username
            app.password = opts.password
            app.display = opts.display
            app.display_desc = display_desc
            app.setup_connection(conn)
        except Exception as e:
            app.cleanup()
            raise
    return app

def make_client(error_cb, opts):
    from xpra.platform.features import CLIENT_MODULES
    for client_module in CLIENT_MODULES:
        #ie: "xpra.client.gtk2.client"
        toolkit_module = __import__(client_module, globals(), locals(), ['XpraClient'])
        if toolkit_module:
            return toolkit_module.XpraClient()
    error_cb("could not load %s" % csv(CLIENT_MODULES))

def do_run_client(app):
    try:
        return app.run()
    except KeyboardInterrupt:
        return -signal.SIGINT
    finally:
        app.cleanup()


def get_start_new_session_dict(opts, mode, extra_args):
    sns = {
           "mode"           : mode,     #ie: "start-desktop"
           }
    if len(extra_args)==1:
        sns["display"] = extra_args[0]
    for x in PROXY_START_OVERRIDABLE_OPTIONS:
        fn = x.replace("-", "_")
        v = getattr(opts, fn)
        if v:
            sns[x] = v
    #make sure the server will start in the same path we were called from:
    #(despite being started by a root owned process from a different directory)
    if not opts.chdir:
        sns["chdir"] = os.getcwd()
    return sns

def shellquote(s):
    return '"' + s.replace('"', '\\"') + '"'

def strip_defaults_start_child(start_child, defaults_start_child):
    if start_child and defaults_start_child:
        #ensure we don't pass start / start-child commands
        #which came from defaults (the configuration files)
        #only the ones specified on the command line:
        #(and only remove them once so the command line can re-add the same ones!)
        for x in defaults_start_child:
            if x in start_child:
                start_child.remove(x)
    return start_child

def run_remote_server(error_cb, opts, args, mode, defaults):
    """ Uses the regular XpraClient with patched proxy arguments to tell run_proxy to start the server """
    params = parse_display_name(error_cb, opts, args[0])
    hello_extra = {}
    #strip defaults, only keep extra ones:
    for x in START_COMMAND_OPTIONS:     # ["start", "start-child", etc]
        fn = x.replace("-", "_")
        v = strip_defaults_start_child(getattr(opts, fn), getattr(defaults, fn))
        setattr(opts, fn, v)
    if isdisplaytype(args, "ssh"):
        #add special flags to "display_as_args"
        proxy_args = []
        if params.get("display") is not None:
            proxy_args.append(params["display"])
        for x in get_start_server_args(opts, True):
            proxy_args.append(shellquote(x))
        params["display_as_args"] = proxy_args
        #and use a proxy subcommand to start the server:
        params["proxy_command"] = [{
                                   "shadow"         : "_shadow_start",
                                   "start"          : "_proxy_start",
                                   "start-desktop"  : "_proxy_start_desktop",
                                   }.get(mode)]
    else:
        #tcp, ssl or vsock:
        sns = {
               "mode"           : mode,
               "display"        : params.get("display", ""),
               }
        for x in START_COMMAND_OPTIONS:
            fn = x.replace("-", "_")
            v = getattr(opts, fn)
            if v:
                sns[x] = v
        hello_extra = {"start-new-session" : sns}

    def connect():
        return connect_or_fail(params, opts)

    if opts.attach is False:
        from xpra.client.gobject_client_base import WaitForDisconnectXpraClient, RequestStartClient
        if isdisplaytype(args, "ssh"):
            #ssh will start the instance we requested,
            #then we just detach and we're done
            app = WaitForDisconnectXpraClient((connect(), params), opts)
        else:
            app = RequestStartClient((connect(), params), opts)
            app.start_new_session = sns
        app.hello_extra = {"connect" : False}
    else:
        app = make_client(error_cb, opts)
        app.init(opts)
        app.init_ui(opts)
        app.hello_extra = hello_extra
        app.setup_connection(connect())
    return do_run_client(app)


X11_SOCKET_DIR = "/tmp/.X11-unix/"

def find_X11_displays(max_display_no=None, match_uid=None, match_gid=None):
    displays = []
    if os.path.exists(X11_SOCKET_DIR) and os.path.isdir(X11_SOCKET_DIR):
        for x in os.listdir(X11_SOCKET_DIR):
            socket_path = os.path.join(X11_SOCKET_DIR, x)
            if not x.startswith("X"):
                warn("path '%s' does not look like an X11 socket" % socket_path)
                continue
            try:
                v = int(x[1:])
            except:
                warn("'%s' does not parse as a display number" % x)
                continue
            try:
                #arbitrary: only shadow automatically displays below 10..
                if max_display_no and v>max_display_no:
                    #warn("display no %i too high (max %i)" % (v, max_display_no))
                    continue
                #check that this is a socket
                sstat = os.stat(socket_path)
                if match_uid is not None and sstat.st_uid!=match_uid:
                    #print("display socket %s does not match uid %i (uid=%i)" % (socket_path, match_uid, sstat.st_uid))
                    continue
                if match_gid is not None and sstat.st_gid!=match_gid:
                    #print("display socket %s does not match gid %i (gid=%i)" % (socket_path, match_gid, sstat.st_gid))
                    continue
                is_socket = stat.S_ISSOCK(sstat.st_mode)
                if not is_socket:
                    warn("display path '%s' is not a socket!" % socket_path)
                    continue
                try:
                    if VERIFY_X11_SOCKET_TIMEOUT:
                        sockpath = os.path.join(X11_SOCKET_DIR, "X%i" % v)
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.settimeout(VERIFY_X11_SOCKET_TIMEOUT)
                        sock.connect(sockpath)
                except:
                    pass
                else:
                    #print("found display path '%s'" % socket_path)
                    displays.append(v)
            except Exception as e:
                warn("failure on %s: %s" % (socket_path, e))
    return displays

def guess_X11_display(dotxpra, uid=getuid(), gid=getgid()):
    displays = [":%s" % x for x in find_X11_displays(max_display_no=10, match_uid=uid, match_gid=gid)]
    if len(displays)!=1:
        #try without uid match:
        displays = [":%s" % x for x in find_X11_displays(max_display_no=10, match_gid=gid)]
        if len(displays)!=1:
            #try without gid match:
            displays = [":%s" % x for x in find_X11_displays(max_display_no=10)]
    if len(displays)==0:
        raise InitExit(1, "could not detect any live X11 displays")
    if len(displays)>1:
        #since we are here to shadow,
        #assume we want to shadow a real X11 server,
        #so remove xpra's own displays to narrow things down:
        results = dotxpra.sockets()
        xpra_displays = [display for _, display in results]
        displays = list(set(displays)-set(xpra_displays))
        if len(displays)==0:
            raise InitExit(1, "could not detect any live plain X11 displays, only multiple xpra displays: %s" % csv(xpra_displays))
    if len(displays)!=1:
        raise InitExit(1, "too many live X11 displays to choose from: %s" % csv(displays))
    return displays[0]


def no_gtk():
    gtk = sys.modules.get("gtk") or sys.modules.get("gi.repository.Gtk")
    if gtk is None:
        #all good, not loaded
        return
    try:
        assert gtk.ver is None
    except:
        #got an exception, probably using the gi bindings
        #which insert a fake gtk module to trigger exceptions
        return
    raise Exception("the gtk module is already loaded: %s" % gtk)


def run_glcheck(opts):
    from xpra.util import pver
    from xpra.client.gl.gtk_base.gtkgl_check import check_support
    try:
        props = check_support(force_enable=opts.opengl)
    except Exception as e:
        sys.stdout.write("error=%s\n" % e)
        return 1
    for k in sorted(props.keys()):
        v = props[k]
        #skip not human readable:
        if k not in ("extensions", "glconfig"):
            sys.stdout.write("%s=%s\n" % (str(k), pver(v)))
    return 0


def start_server_subprocess(script_file, args, mode, opts, username="", uid=getuid(), gid=getgid(), env=os.environ.copy(), cwd=None):
    log = get_util_logger()
    log("start_server_subprocess%s", (script_file, args, mode, opts, uid, gid, env, cwd))
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs, username, uid=uid, gid=gid)
    #we must use a subprocess to avoid messing things up - yuk
    assert mode in ("start", "start-desktop", "shadow")
    if mode in ("start", "start-desktop"):
        if len(args)==1:
            display_name = args[0]
        elif len(args)==0:
            #let the server get one from Xorg via displayfd:
            display_name = 'S' + str(os.getpid())
        else:
            raise InitException("%s: expected 0 or 1 arguments but got %s: %s" % (mode, len(args), args))
    else:
        assert mode=="shadow"
        assert len(args) in (0, 1), "starting shadow server: expected 0 or 1 arguments but got %s: %s" % (len(args), args)
        display_name = None
        if OSX or WIN32:
            #no need for a specific display
            display_name = ":0"
        else:
            if len(args)==1 and args[0] and args[0][0]==":":
                #display_name was provided:
                display_name = args[0]
            else:
                display_name = guess_X11_display(dotxpra, uid, gid)
            #we now know the display name, so add it:
            args = [display_name]
        opts.exit_with_client = True

    #get the list of existing sockets so we can spot the new ones:
    if display_name.startswith("S"):
        matching_display = None
    else:
        matching_display = display_name
    existing_sockets = set(dotxpra.socket_paths(check_uid=uid, matching_state=dotxpra.LIVE, matching_display=matching_display))
    log("start_server_subprocess: existing_sockets=%s", existing_sockets)

    cmd = [script_file, mode] + args        #ie: ["/usr/bin/xpra", "start-desktop", ":100"]
    cmd += get_start_server_args(opts, uid, gid)      #ie: ["--exit-with-children", "--start-child=xterm"]
    #when starting via the system proxy server,
    #we may already have a XPRA_PROXY_START_UUID,
    #specified by the proxy-start command:
    new_server_uuid = parse_env(opts.env or []).get("XPRA_PROXY_START_UUID")
    if not new_server_uuid:
        #generate one now:
        from xpra.os_util import get_hex_uuid
        new_server_uuid = get_hex_uuid()
        cmd.append("--env=XPRA_PROXY_START_UUID=%s" % new_server_uuid)
    if mode=="shadow" and OSX:
        #launch the shadow server via launchctl so it will have GUI access:
        LAUNCH_AGENT = "org.xpra.Agent"
        LAUNCH_AGENT_FILE = "/System/Library/LaunchAgents/%s.plist" % LAUNCH_AGENT
        try:
            os.stat(LAUNCH_AGENT_FILE)
        except Exception as e:
            #ignore access denied error, launchctl runs as root
            import errno
            if e[0]!=errno.EACCES:
                warn("Error: shadow may not start,\n the launch agent file '%s' seems to be missing:%s.\n" % (LAUNCH_AGENT_FILE, e))
        argfile = os.path.expanduser("~/.xpra/shadow-args")
        with open(argfile, "w") as f:
            f.write('["Xpra", "--no-daemon"')
            for x in cmd[1:]:
                f.write(', "%s"' % x)
            f.write(']')
        launch_commands = [
                           ["launchctl", "unload", LAUNCH_AGENT_FILE],
                           ["launchctl", "load", "-S", "Aqua", LAUNCH_AGENT_FILE],
                           ["launchctl", "start", LAUNCH_AGENT],
                           ]
        log("start_server_subprocess: launch_commands=%s", launch_commands)
        for x in launch_commands:
            proc = Popen(x, shell=False, close_fds=True, env=env, cwd=cwd)
            proc.wait()
        proc = None
    else:
        #useful for testing failures that cause the whole XDG_RUNTIME_DIR to get nuked
        #(and the log file with it):
        #cmd.append("--log-file=/tmp/proxy.log")
        close_fds = True
        preexec_fn = None
        if POSIX:
            cmd.append("--daemon=yes")
            cmd.append("--systemd-run=no")
            if getuid()==0 and (uid!=0 or gid!=0):
                cmd.append("--uid=%i" % uid)
                cmd.append("--gid=%i" % gid)
            if not OSX and not matching_display:
                #use "--displayfd" switch to tell us which display was chosen:
                r_pipe, w_pipe = os.pipe()
                cmd.append("--displayfd=%s" % w_pipe)
                close_fds = False
                def preexec_fn():
                    from xpra.os_util import close_fds as osclose_fds
                    osclose_fds([0, 1, 2, r_pipe, w_pipe])
        log("start_server_subprocess: command=%s", csv(["'%s'" % x for x in cmd]))
        proc = Popen(cmd, shell=False, close_fds=close_fds, env=env, cwd=cwd, preexec_fn=preexec_fn)
        log("proc=%s", proc)
        if POSIX and not OSX and not matching_display:
            from xpra.platform.displayfd import read_displayfd, parse_displayfd
            buf = read_displayfd(r_pipe, proc=None) #proc deamonizes!
            try:
                os.close(r_pipe)
            except:
                pass
            try:
                os.close(w_pipe)
            except:
                pass
            def displayfd_err(msg):
                log.error("Error: displayfd failed")
                log.error(" %s", msg)
            n = parse_displayfd(buf, displayfd_err)
            if n is not None:
                matching_display = ":%s" % n
                log("displayfd=%s", matching_display)
    socket_path, display = identify_new_socket(proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, uid)
    return proc, socket_path, display

def get_start_server_args(opts, uid=getuid(), gid=getgid(), compat=False):
    defaults = make_defaults_struct(uid=uid, gid=gid)
    fixup_options(defaults)
    args = []
    for x, ftype in OPTION_TYPES.items():
        if x in NON_COMMAND_LINE_OPTIONS or x in CLIENT_ONLY_OPTIONS:
            continue
        if compat and x in OPTIONS_ADDED_SINCE_V1:
            continue
        fn = x.replace("-", "_")
        ov = getattr(opts, fn)
        dv = getattr(defaults, fn)
        if ov==dv:
            continue    #same as the default
        #lists are special cased depending on how OptionParse will be parsing them:
        if ftype==list:
            #warn("%s: %s vs %s\n" % (x, ov, dv))
            if x in START_COMMAND_OPTIONS+BIND_OPTIONS+[
                     "pulseaudio-configure-commands",
                     "speaker-codec", "microphone-codec",
                     "key-shortcut", "start-env", "env",
                     "socket-dirs",
                     ]:
                #individual arguments (ie: "--start=xterm" "--start=gedit" ..)
                for e in ov:
                    args.append("--%s=%s" % (x, e))
            else:
                #those can be specified as CSV: (ie: "--encodings=png,jpeg,rgb")
                args.append("--%s=%s" % (x, ",".join(str(x) for x in ov)))
        elif ftype==bool:
            if compat and x in ("exit-with-children", "use-display", "mmap-group"):
                #older servers don't take a bool value for those options,
                #it is disabled unless specified:
                if ov:
                    args.append("--%s" % x)
            else:
                args.append("--%s=%s" % (x, ["no", "yes"][int(ov)]))
        elif ftype in (int, float, str):
            args.append("--%s=%s" % (x, ov))
        else:
            raise InitException("unknown option type '%s' for '%s'" % (ftype, x))
    return args


def identify_new_socket(proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, matching_uid=0):
    log = get_util_logger()
    log("identify_new_socket%s", (proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, matching_uid))
    #wait until the new socket appears:
    start = monotonic_time()
    UUID_PREFIX = "uuid="
    DISPLAY_PREFIX = "display="
    from xpra.platform.paths import get_nodock_command
    while monotonic_time()-start<WAIT_SERVER_TIMEOUT and (proc is None or proc.poll() in (None, 0)):
        sockets = set(dotxpra.socket_paths(check_uid=matching_uid, matching_state=dotxpra.LIVE, matching_display=matching_display))
        #sort because we prefer a socket in /run/* to one in /home/*:
        new_sockets = tuple(reversed(tuple(sockets-existing_sockets)))
        log("identify_new_socket new_sockets=%s", new_sockets)
        for socket_path in new_sockets:
            #verify that this is the right server:
            try:
                #we must use a subprocess to avoid messing things up - yuk
                cmd = get_nodock_command()+["id", "socket:%s" % socket_path]
                p = Popen(cmd, stdin=None, stdout=PIPE, stderr=PIPE)
                stdout, _ = p.communicate()
                if p.returncode==0:
                    try:
                        out = stdout.decode('utf-8')
                    except:
                        try:
                            out = stdout.decode()
                        except:
                            out = bytestostr(stdout)
                    lines = out.splitlines()
                    log("id(%s): %s", socket_path, csv(lines))
                    found = False
                    display = matching_display
                    for line in lines:
                        if line.startswith(UUID_PREFIX):
                            this_uuid = line[len(UUID_PREFIX):]
                            if this_uuid==new_server_uuid:
                                found = True
                        elif line.startswith(DISPLAY_PREFIX):
                            display = line[len(DISPLAY_PREFIX):]
                            if display and display==matching_display:
                                found = True
                    if found:
                        assert display, "display value not found in id output"
                        log("identify_new_socket found match: path=%s, display=%s", socket_path, display)
                        return socket_path, display
            except Exception as e:
                warn("error during server process detection: %s" % e)
        sleep(0.10)
    raise InitException("failed to identify the new server display!")

def run_proxy(error_cb, opts, script_file, args, mode, defaults):
    no_gtk()
    if mode in ("_proxy_start", "_proxy_start_desktop", "_shadow_start"):
        server_mode = {
                       "_proxy_start"           : "start",
                       "_proxy_start_desktop"   : "start-desktop",
                       "_shadow_start"          : "shadow",
                       }.get(mode)
        #strip defaults, only keep extra ones:
        for x in ("start", "start-child",
                  "start-after-connect", "start-child-after-connect",
                  "start-on-connect", "start-child-on-connect"):
            fn = x.replace("-", "_")
            v = strip_defaults_start_child(getattr(opts, fn), getattr(defaults, fn))
            setattr(opts, fn, v)
        proc, socket_path, display = start_server_subprocess(script_file, args, server_mode, opts)
        if not socket_path:
            #if we return non-zero, we will try the next run-xpra script in the list..
            return 0
        display = parse_display_name(error_cb, opts, "socket:%s" % socket_path)
        if proc and proc.poll() is None:
            #start a thread just to reap server startup process (yuk)
            #(as the server process will exit as it daemonizes)
            from xpra.make_thread import start_thread
            start_thread(proc.wait, "server-startup-reaper")
    else:
        #use display specified on command line:
        display = pick_display(error_cb, opts, args)
    server_conn = connect_or_fail(display, opts)
    from xpra.scripts.fdproxy import XpraProxy
    from xpra.net.bytestreams import TwoFileConnection
    app = XpraProxy("xpra-pipe-proxy", TwoFileConnection(sys.stdout, sys.stdin, socktype="stdin/stdout"), server_conn)
    signal.signal(signal.SIGINT, app.quit)
    signal.signal(signal.SIGTERM, app.quit)
    app.run()
    return  0

def run_stopexit(mode, error_cb, opts, extra_args):
    assert mode in ("stop", "exit")
    no_gtk()

    def show_final_state(display_desc):
        #this is for local sockets only!
        display = display_desc["display"]
        sockdir = display_desc.get("socket_dir", "")
        sockdirs = display_desc.get("socket_dirs", [])
        sockdir = DotXpra(sockdir, sockdirs)
        sockfile = get_sockpath(display_desc, error_cb)
        #first 5 seconds: just check if the socket still exists:
        #without connecting (avoid warnings and log messages on server)
        for _ in range(25):
            if not os.path.exists(sockfile):
                break
            sleep(0.2)
        #next 5 seconds: actually try to connect
        for _ in range(10):
            final_state = sockdir.get_server_state(sockfile, 1)
            if final_state is DotXpra.DEAD:
                break
            else:
                sleep(0.5)
        if final_state is DotXpra.DEAD:
            print("xpra at %s has exited." % display)
            return 0
        elif final_state is DotXpra.UNKNOWN:
            print("How odd... I'm not sure what's going on with xpra at %s" % display)
            return 1
        elif final_state is DotXpra.LIVE:
            print("Failed to shutdown xpra at %s" % display)
            return 1
        else:
            assert False, "invalid state: %s" % final_state
            return 1

    def multimode(displays):
        sys.stdout.write("Trying to %s %i displays:\n" % (mode, len(displays)))
        sys.stdout.write(" %s\n" % csv(displays))
        procs = []
        #["xpra", "stop", ..]
        from xpra.platform.paths import get_nodock_command
        cmd = get_nodock_command()+[mode, "--socket-dir=%s" % opts.socket_dir]
        for x in opts.socket_dirs:
            if x:
                cmd.append("--socket-dirs=%s" % x)
        #use a subprocess per display:
        for display in displays:
            dcmd = cmd + [display]
            proc = Popen(dcmd)
            procs.append(proc)
        start = monotonic_time()
        live = procs
        while monotonic_time()-start<10 and live:
            live = [x for x in procs if x.poll() is None]
        return 0

    if len(extra_args)==1 and extra_args[0]=="all":
        #stop or exit all
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        displays = dotxpra.displays(check_uid=getuid(), matching_state=DotXpra.LIVE)
        if not displays:
            sys.stdout.write("No xpra sessions found\n")
            return 1
        elif len(displays)==1:
            #fall through, but use the display we found:
            extra_args = displays
        else:
            assert len(displays)>1
            return multimode(displays)
    elif len(extra_args)>1:
        return multimode(extra_args)

    display_desc = pick_display(error_cb, opts, extra_args)
    conn = connect_or_fail(display_desc, opts)
    app = None
    e = 1
    try:
        if mode=="stop":
            from xpra.client.gobject_client_base import StopXpraClient
            app = StopXpraClient((conn, display_desc), opts)
        else:
            assert mode=="exit"
            from xpra.client.gobject_client_base import ExitXpraClient
            app = ExitXpraClient((conn, display_desc), opts)
        e = app.run()
    finally:
        if app:
            app.cleanup()
    if e==0:
        if display_desc["local"] and display_desc.get("display"):
            show_final_state(display_desc)
        else:
            print("Sent shutdown command")
    return e


def may_cleanup_socket(state, display, sockpath, clean_states=[DotXpra.DEAD]):
    sys.stdout.write("\t%s session at %s" % (state, display))
    if state in clean_states:
        try:
            stat_info = os.stat(sockpath)
            if stat_info.st_uid==os.getuid():
                os.unlink(sockpath)
                sys.stdout.write(" (cleaned up)")
        except OSError as e:
            sys.stdout.write(" (delete failed: %s)" % e)
    sys.stdout.write("\n")

def run_sessions_gui(error_cb, options):
    mdns = supports_mdns and options.mdns
    if mdns:
        return run_mdns_gui(error_cb, options)
    from xpra.client.gtk_base import sessions_gui
    return sessions_gui.do_main(options)

def run_mdns_gui(error_cb, options):
    from xpra.net.mdns import get_listener_class
    listener = get_listener_class()
    if not listener:
        error_cb("sorry, 'mdns-gui' is not supported on this platform yet")
    from xpra.client.gtk_base import mdns_gui
    return mdns_gui.do_main(options)

def run_list_mdns(error_cb, extra_args):
    no_gtk()
    if len(extra_args)<=1:
        try:
            MDNS_WAIT = int(extra_args[0])
        except:
            MDNS_WAIT = 5
    else:
        error_cb("too many arguments for mode")
    assert supports_mdns
    from xpra.net.mdns import XPRA_MDNS_TYPE
    try:
        from xpra.net.mdns.avahi_listener import AvahiListener
    except ImportError:
        error_cb("sorry, 'list-mdns' is not supported on this platform yet")
    from xpra.net.net_util import if_indextoname
    from xpra.dbus.common import loop_init
    from xpra.gtk_common.gobject_compat import import_glib
    glib = import_glib()
    loop_init()
    import collections
    found = collections.OrderedDict()
    shown = set()
    def show_new_found():
        new_found = [x for x in found.keys() if x not in shown]
        for uq in new_found:
            recs = found[uq]
            for i, rec in enumerate(recs):
                iface, _, _, host, address, port, text = rec
                uuid = text.get("uuid")
                display = text.get("display")
                mode = text.get("mode", "")
                username = text.get("username", "")
                session = text.get("session")
                dtype = text.get("type")
                if i==0:
                    print("* user '%s' on '%s'" % (username, host))
                    if session:
                        print(" %s session '%s', uuid=%s" % (dtype, session, uuid))
                    elif uuid:
                        print(" uuid=%s" % uuid)
                print(" + %s endpoint on host %s, port %i, interface %s" % (mode, address, port, iface))
                dstr = ""
                if display.startswith(":"):
                    dstr = display[1:]
                uri = "%s/%s@%s:%s/%s" % (mode, username, address, port, dstr)
                print("   \"%s\"" % uri)
            shown.add(uq)
    def mdns_add(interface, protocol, name, stype, domain, host, address, port, text):
        text = text or {}
        iface = interface
        if if_indextoname:
            iface = if_indextoname(interface)
        username = text.get("username", "")
        uq = text.get("uuid", len(found)), username, host
        found.setdefault(uq, []).append((iface, name, domain, host, address, port, text))
        glib.timeout_add(1000, show_new_found)
    listener = AvahiListener(XPRA_MDNS_TYPE, mdns_add=mdns_add)
    print("Looking for xpra services via mdns")
    try:
        glib.idle_add(listener.start)
        loop = glib.MainLoop()
        glib.timeout_add(MDNS_WAIT*1000, loop.quit)
        loop.run()
    finally:
        listener.stop()
    if not found:
        print("no services found")
    else:
        from xpra.util import engs
        print("%i service%s found" % (len(found), engs(found)))


def run_list(error_cb, opts, extra_args):
    no_gtk()
    if extra_args:
        error_cb("too many arguments for mode")
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
    results = dotxpra.socket_details()
    if not results:
        sys.stdout.write("No xpra sessions found\n")
        return 0
    sys.stdout.write("Found the following xpra sessions:\n")
    unknown = []
    for socket_dir, values in results.items():
        sys.stdout.write("%s:\n" % socket_dir)
        for state, display, sockpath in values:
            may_cleanup_socket(state, display, sockpath)
            if state is DotXpra.UNKNOWN:
                unknown.append((socket_dir, display, sockpath))
    #now, re-probe the "unknown" ones:
    #but only re-probe the ones we own:
    reprobe = []
    for x in unknown:
        try:
            stat_info = os.stat(x[2])
            if stat_info.st_uid==os.getuid():
                reprobe.append(x)
        except OSError:
            pass
    if reprobe:
        sys.stdout.write("Re-probing unknown sessions in: %s\n" % csv(list(set([x[0] for x in unknown]))))
        counter = 0
        while reprobe and counter<5:
            sleep(1)
            counter += 1
            probe_list = list(reprobe)
            unknown = []
            for v in probe_list:
                socket_dir, display, sockpath = v
                state = dotxpra.get_server_state(sockpath, 1)
                if state is DotXpra.DEAD:
                    may_cleanup_socket(state, display, sockpath)
                elif state is DotXpra.UNKNOWN:
                    unknown.append(v)
                else:
                    sys.stdout.write("\t%s session at %s (%s)\n" % (state, display, socket_dir))
            reprobe = unknown
        #now cleanup those still unknown:
        clean_states = [DotXpra.DEAD, DotXpra.UNKNOWN]
        for state, display, sockpath in unknown:
            state = dotxpra.get_server_state(sockpath)
            may_cleanup_socket(state, display, sockpath, clean_states=clean_states)
    return 0

def run_showconfig(options, args):
    log = get_util_logger()
    from xpra.util import nonl
    d = dict_to_validated_config({})
    fixup_options(d)
    #this one is normally only probed at build time:
    #(so probe it here again)
    if POSIX:
        try:
            from xpra.platform.pycups_printing import get_printer_definition
            for mimetype in ("pdf", "postscript"):
                pdef = get_printer_definition(mimetype)
                #ie: d.pdf_printer = "/usr/share/ppd/cupsfilters/Generic-PDF_Printer-PDF.ppd"
                setattr(d, "%s_printer" % mimetype, pdef)
        except:
            pass
    VIRTUAL = ["mode"]       #no such option! (it's a virtual one for the launch by config files)
    #hide irrelevant options:
    HIDDEN = []
    if not "all" in args:
        #this logic probably belongs somewhere else:
        if OSX or WIN32:
            #these options don't make sense on win32 or osx:
            HIDDEN += ["socket-dirs", "socket-dir",
                       "wm-name", "pulseaudio-command", "pulseaudio", "xvfb", "input-method",
                       "socket-permissions", "fake-xinerama", "dbus-proxy", "xsettings",
                       "exit-with-children", "start-new-commands",
                       "start", "start-child",
                       "start-after-connect", "start-child-after-connect",
                       "start-on-connect", "start-child-on-connect",
                       ]
        if WIN32:
            #"exit-ssh"?
            HIDDEN += ["lpadmin", "daemon", "use-display", "mmap-group", "mdns"]
        if not OSX:
            HIDDEN += ["dock-icon", "swap-keys"]
    def vstr(v):
        #just used to quote all string values
        if type(v)==str:
            return "'%s'" % nonl(v)
        if type(v) in (tuple, list) and len(v)>0:
            return csv(vstr(x) for x in v)
        return str(v)
    for opt in sorted(OPTION_TYPES.keys()):
        if opt in VIRTUAL:
            continue
        i = log.info
        w = log.warn
        if args:
            if ("all" not in args) and (opt not in args):
                continue
        elif opt in HIDDEN:
            i = log.debug
            w = log.debug
        k = name_to_field(opt)
        dv = getattr(d, k)
        cv = getattr(options, k, dv)
        if cv!=dv:
            w("%-20s  (used)   = %-32s  %s", opt, vstr(cv), type(cv))
            w("%-20s (default) = %-32s  %s", opt, vstr(dv), type(dv))
        else:
            i("%-20s           = %s", opt, vstr(cv))


if __name__ == "__main__":
    code = main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
