#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
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
from xpra.util import csv, envbool, envint, unsetenv, repr_ellipsized, nonl, pver, DEFAULT_PORT, DEFAULT_PORTS
from xpra.exit_codes import EXIT_SSL_FAILURE, EXIT_STR, EXIT_UNSUPPORTED
from xpra.os_util import (
    get_util_logger, getuid, getgid, pollwait,
    monotonic_time, setsid, bytestostr, use_tty,
    WIN32, OSX, POSIX, PYTHON2, PYTHON3, SIGNAMES, is_Ubuntu, getUbuntuVersion,
    )
from xpra.scripts.parsing import (
    info, warn, error,
    parse_vsock, parse_env, is_local,
    fixup_defaults, validated_encodings, validate_encryption, do_parse_cmdline, show_sound_codec_help,
    supports_shadow, supports_server, supports_proxy, supports_mdns,
    )
from xpra.scripts.config import (
    OPTION_TYPES, TRUE_OPTIONS, CLIENT_OPTIONS, NON_COMMAND_LINE_OPTIONS, CLIENT_ONLY_OPTIONS,
    START_COMMAND_OPTIONS, BIND_OPTIONS, PROXY_START_OVERRIDABLE_OPTIONS, OPTIONS_ADDED_SINCE_V1, OPTIONS_COMPAT_NAMES,
    InitException, InitInfo, InitExit,
    fixup_options, dict_to_validated_config, get_xpra_defaults_dirs, get_defaults, read_xpra_conf,
    make_defaults_struct, parse_bool, has_sound_support, name_to_field,
    )
from xpra.log import is_debug_enabled, Logger
assert info and warn and error, "used by modules importing those from here"

NO_ROOT_WARNING = envbool("XPRA_NO_ROOT_WARNING", False)
CLIPBOARD_CLASS = os.environ.get("XPRA_CLIPBOARD_CLASS")
WAIT_SERVER_TIMEOUT = envint("WAIT_SERVER_TIMEOUT", 90)
CONNECT_TIMEOUT = envint("XPRA_CONNECT_TIMEOUT", 20)
SYSTEMD_RUN = envbool("XPRA_SYSTEMD_RUN", True)
LOG_SYSTEMD_WRAP = envbool("XPRA_LOG_SYSTEMD_WRAP", True)
VERIFY_X11_SOCKET_TIMEOUT = envint("XPRA_VERIFY_X11_SOCKET_TIMEOUT", 1)
LIST_REPROBE_TIMEOUT = envint("XPRA_LIST_REPROBE_TIMEOUT", 10)


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
    ml = envint("XPRA_MEM_USAGE_LOGGER")
    if ml>0:
        from xpra.util import start_mem_watcher
        start_mem_watcher(ml)

    if sys.flags.optimize>0:
        sys.stderr.write("************************************************************\n")
        sys.stderr.write("Warning: the python optimize flag is set to %i\n" % sys.flags.optimize)
        sys.stderr.write(" xpra is very likely to crash\n")
        sys.stderr.write("************************************************************\n")
        sleep(5)

    from xpra.platform import clean as platform_clean, command_error, command_info
    if len(cmdline)==1:
        cmdline.append("gui")
    #we may have needed this variable to get here,
    #and we may need to use it again to launch new commands:
    if "XPRA_ALT_PYTHON_RETRY" in os.environ:
        del os.environ["XPRA_ALT_PYTHON_RETRY"]

    #turn off gdk scaling to make sure we get the actual window geometry:
    os.environ["GDK_SCALE"]="1"
    #client side decorations break window geometry,
    #disable this "feature" unless explicitly enabled:
    if PYTHON3 and os.environ.get("GTK_CSD") is None:
        os.environ["GTK_CSD"] = "0"

    if envbool("XPRA_NOMD5", False):
        import hashlib
        def nomd5(*_args):
            raise ValueError("md5 support is disabled")
        hashlib.algorithms_available.remove("md5")
        hashlib.md5 = nomd5

    if OSX and PYTHON2 and any(x in cmdline for x in ("_sound_record", "_sound_play", "_sound_query")):
        #bug 2365: force gi bindings early on macos
        from xpra.gtk_common.gobject_compat import want_gtk3
        want_gtk3(True)

    def debug_exc(msg="run_mode error"):
        get_util_logger().debug(msg, exc_info=True)

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
        try:
            sys.stdout.close()
        except (IOError, OSError):
            pass
        try:
            sys.stderr.close()
        except (IOError, OSError):
            pass


def configure_logging(options, mode):
    if mode in (
        "showconfig", "info", "id", "attach", "listen", "launcher", "stop", "print",
        "control", "list", "list-mdns", "sessions", "mdns-gui", "bug-report",
        "opengl", "opengl-probe", "opengl-test",
        "test-connect",
        "encoding", "webcam", "clipboard-test",
        "keyboard", "keyboard-test", "keymap", "gui-info", "network-info", "path-info",
        "printing-info", "version-info", "gtk-info",
        "colors-test", "colors-gradient-test", "transparent-colors", "transparent-window",
        ):
        s = sys.stdout
    else:
        s = sys.stderr
    to = s
    if PYTHON3:
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
    if mode in (
        "start", "start-desktop", "upgrade", "upgrade-desktop",
        "attach", "listen", "shadow", "proxy",
        "_sound_record", "_sound_play",
        "stop", "print", "showconfig",
        "request-start", "request-start-desktop", "request-shadow",
        "_dialog", "_pass",
        ):
        if "help" in options.speaker_codec or "help" in options.microphone_codec:
            server_mode = mode not in ("attach", "listen")
            codec_help = show_sound_codec_help(server_mode, options.speaker_codec, options.microphone_codec)
            raise InitInfo("\n".join(codec_help))
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
            if not cat:
                continue
            if cat[0]=="-":
                add_disabled_category(cat[1:])
                disable_debug_for(cat[1:])
            else:
                add_debug_category(cat)
                enable_debug_for(cat)

    #always log debug level, we just use it selectively (see above)
    logging.root.setLevel(logging.INFO)


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
        except IOError:
            pass
    try:
        p = Popen(cmd)
        return p.wait()
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
            #detect if we should use it:
            if is_Ubuntu() and getUbuntuVersion()>=(18,) and (os.environ.get("SSH_TTY") or os.environ.get("SSH_CLIENT")):
                #would fail
                systemd_run = False
            else:
                from xpra.os_util import is_systemd_pid1
                if is_systemd_pid1():
                    cmd = ["systemd-run", "--quiet", "--user", "--scope", "--", "true"]
                    proc = Popen(cmd, stdin=None, stdout=None, stderr=None, shell=False)
                    r = pollwait(proc, timeout=1)
                    if r is None:
                        try:
                            proc.terminate()
                        except:
                            pass
                    systemd_run = r==0
                else:
                    systemd_run = False
        if systemd_run:
            #check if we have wrapped it already (or if disabled via env var)
            if SYSTEMD_RUN:
                #make sure we run via the same interpreter,
                #inject it into the command line if we have to:
                argv = list(sys.argv)
                if argv[0].find("python")<0:
                    argv.insert(0, "python%i" % sys.version_info[0])
                return systemd_run_wrap(mode, argv, options.systemd_run_args)

    configure_env(options.env)
    configure_logging(options, mode)
    configure_network(options)

    if not mode.startswith("_sound_"):
        #only the sound subcommands should ever actually import GStreamer:
        try:
            from xpra.sound.gstreamer_util import prevent_import
            prevent_import()
        except ImportError:
            pass
        #sound commands don't want to set the name
        #(they do it later to prevent glib import conflicts)
        #"attach" does it when it received the session name from the server
        if mode not in ("attach", "listen", "start", "start-desktop", "upgrade", "upgrade-desktop", "proxy", "shadow"):
            from xpra.platform import set_name
            set_name("Xpra", "Xpra %s" % mode.strip("_"))

    if mode in (
        "start", "start-desktop",
        "shadow", "attach", "listen",
        "request-start", "request-start-desktop", "request-shadow",
        ):
        options.encodings = validated_encodings(options.encodings)

    try:
        if mode in ("start", "start-desktop", "shadow") and display_is_remote:
            #ie: "xpra start ssh://USER@HOST:SSHPORT/DISPLAY --start-child=xterm"
            return run_remote_server(error_cb, options, args, mode, defaults)
        if (mode in ("start", "start-desktop", "upgrade", "upgrade-desktop") and supports_server) or \
            (mode=="shadow" and supports_shadow) or (mode=="proxy" and supports_proxy):
            try:
                cwd = os.getcwd()
            except OSError:
                os.chdir("/")
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
                        NO_RETRY = [EXIT_OK] + list(range(128, 128+16))
                        if app.completed_startup:
                            #if we had connected to the session,
                            #we can ignore more error codes:
                            from xpra.exit_codes import (
                                EXIT_CONNECTION_LOST, EXIT_REMOTE_ERROR,
                                EXIT_INTERNAL_ERROR, EXIT_FILE_TOO_BIG,
                                )
                            NO_RETRY += [
                                    EXIT_CONNECTION_LOST,
                                    EXIT_REMOTE_ERROR,
                                    EXIT_INTERNAL_ERROR,
                                    EXIT_FILE_TOO_BIG,
                                    ]
                        if r in NO_RETRY:
                            return r
                        if r==EXIT_FAILURE:
                            err = "unknown general failure"
                        else:
                            err = EXIT_STR.get(r, r)
                    except Exception as e:
                        log = Logger("proxy")
                        log("failed to start via proxy", exc_info=True)
                        err = str(e)
                    if start_via_proxy is True:
                        raise InitException("failed to start-via-proxy: %s" % (err,))
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
        elif mode in (
            "attach", "listen", "detach",
            "screenshot", "version", "info", "id",
            "control", "_monitor", "top", "print",
            "connect-test", "request-start", "request-start-desktop", "request-shadow",
            ):
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
        elif mode == "launcher":
            from xpra.client.gtk_base.client_launcher import main as launcher_main
            return launcher_main(["xpra"]+args)
        elif mode == "gui":
            from xpra.gtk_common.gui import main as gui_main        #@Reimport
            return gui_main()
        elif mode == "bug-report":
            from xpra.scripts.bug_report import main as bug_main    #@Reimport
            bug_main(["xpra"]+args)
        elif mode in (
            "_proxy",
            "_proxy_start",
            "_proxy_start_desktop",
            "_proxy_shadow_start",
            ) and (supports_server or supports_shadow):
            nox()
            return run_proxy(error_cb, options, script_file, args, mode, defaults)
        elif mode in ("_sound_record", "_sound_play", "_sound_query"):
            if not has_sound_support():
                error_cb("no sound support!")
            from xpra.sound.wrapper import run_sound
            return run_sound(mode, error_cb, options, args)
        elif mode=="_dialog":
            return run_dialog(args)
        elif mode=="_pass":
            return run_pass(args)
        elif mode=="opengl":
            return run_glcheck(options)
        elif mode=="opengl-probe":
            return run_glprobe(options)
        elif mode=="opengl-test":
            return run_glprobe(options, True)
        elif mode=="encoding":
            from xpra.codecs import loader
            return loader.main()
        elif mode=="webcam":
            from xpra.scripts import show_webcam
            return show_webcam.main()
        elif mode=="clipboard-test":
            from xpra.gtk_common import gtk_view_clipboard
            return gtk_view_clipboard.main()
        elif mode=="keyboard":
            from xpra.platform import keyboard
            return keyboard.main()
        elif mode=="keyboard-test":
            from xpra.gtk_common import gtk_view_keyboard
            return gtk_view_keyboard.main()
        elif mode=="keymap":
            from xpra.gtk_common import keymap
            return keymap.main()
        elif mode=="gtk-info":
            from xpra.scripts import gtk_info
            return gtk_info.main()
        elif mode=="gui-info":
            from xpra.platform import gui
            return gui.main()
        elif mode=="network-info":
            from xpra.net import net_util
            return net_util.main()
        elif mode=="path-info":
            from xpra.platform import paths
            return paths.main()
        elif mode=="printing-info":
            from xpra.platform import printing
            return printing.main()
        elif mode=="version-info":
            from xpra.scripts import version
            return version.main()
        elif mode=="colors-test":
            from xpra.client.gtk_base.example import colors
            return colors.main()
        elif mode=="colors-gradient-test":
            from xpra.client.gtk_base.example import colors_gradient
            return colors_gradient.main()
        elif mode=="transparent-colors":
            from xpra.client.gtk_base.example import transparent_colors
            return transparent_colors.main()
        elif mode=="transparent-window":
            from xpra.client.gtk_base.example import transparent_window
            return transparent_window.main()
        elif mode == "initenv":
            if not POSIX:
                raise InitExit(EXIT_UNSUPPORTED, "initenv is not supported on this OS")
            from xpra.server.server_util import xpra_runner_shell_script, write_runner_shell_scripts
            script = xpra_runner_shell_script(script_file, os.getcwd(), options.socket_dir)
            write_runner_shell_scripts(script, False)
            return 0
        elif mode == "showconfig":
            return run_showconfig(options, args)
        elif mode == "showsetting":
            return run_showsetting(options, args)
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

def parse_ssh_string(ssh_setting):
    if is_debug_enabled("ssh"):
        get_util_logger().debug("parse_ssh_string(%s)" % ssh_setting)
    ssh_cmd = ssh_setting
    from xpra.platform.features import DEFAULT_SSH_COMMAND
    if ssh_setting=="auto":
        #try paramiko:
        try:
            from xpra.net.ssh import nogssapi_context
            with nogssapi_context():
                import paramiko
            assert paramiko
            ssh_cmd = "paramiko"
            if is_debug_enabled("ssh"):
                get_util_logger().info("using paramiko")
        except ImportError as e:
            if is_debug_enabled("ssh"):
                get_util_logger().info("no paramiko: %s" % e)
            ssh_cmd = DEFAULT_SSH_COMMAND
    return shlex.split(ssh_cmd)

def add_ssh_args(username, password, host, ssh_port, is_putty=False, is_paramiko=False):
    args = []
    if password and is_putty:
        args += ["-pw", password]
    if username and not is_paramiko:
        args += ["-l", username]
    if ssh_port and ssh_port!=22:
        #grr why bother doing it different?
        if is_putty:
            args += ["-P", str(ssh_port)]
        elif not is_paramiko:
            args += ["-p", str(ssh_port)]
    if not is_paramiko:
        args += ["-T", host]
    return args

def add_ssh_proxy_args(username, password, host, ssh_port, pkey, ssh, is_putty=False, is_paramiko=False):
    args = []
    proxyline = ssh
    if is_putty:
        proxyline += ["-nc", "%host:%port"]
        if pkey:
            # tortoise plink works with either slash, backslash needs too much escaping
            # because of the weird way it's passed through as a ProxyCommand
            proxyline += [ "-i", "\"" + pkey.replace("\\", "/") + "\""]
    elif not is_paramiko:
        proxyline += ["-W", "%h:%p"]
    # the double quotes are in case the password has something like "&"
    proxyline += add_ssh_args(username, password, host, ssh_port, is_putty, is_paramiko)
    if is_putty:
        args += ["-proxycmd", " ".join(proxyline)]
    elif not is_paramiko:
        args += ["-o", "ProxyCommand " + " ".join(proxyline)]
    return args


def parse_proxy_attributes(display_name):
    import re
    # Notes:
    # (1) this regex permits a "?" in the password or username (because not just splitting at "?").
    #     It doesn't look for the next  "?" until after the "@", where a "?" really indicates
    #     another field.
    # (2) all characters including "@"s go to "userpass" until the *last* "@" after which it all goes
    #     to "hostport"
    reout = re.search("\\?proxy=(?P<p>((?P<userpass>.+)@)?(?P<hostport>[^?]+))", display_name)
    if not reout:
        return display_name, {}
    try:
        desc_tmp = dict()
        # This one should *always* return a host, and should end with an optional numeric port
        hostport = reout.group("hostport")
        hostport_match = re.match(r"(?P<host>[^:]+)($|:(?P<port>\d+)$)", hostport)
        if not hostport_match:
            raise RuntimeError("bad format for 'hostport': '%s'" % hostport)
        host = hostport_match.group("host")
        if not host:
            raise RuntimeError("bad format: missing host in '%s'" % hostport)
        desc_tmp["proxy_host"] = host
        if hostport_match.group("port"):
            try:
                desc_tmp["proxy_port"] = int(hostport_match.group("port"))
            except ValueError:
                raise RuntimeError("bad format: proxy port '%s' is not a number" % hostport_match.group("port"))
        userpass = reout.group("userpass")
        if userpass:
            # The username ends at the first colon. This decision was not unique: I could have
            # allowed one colon in username if there were two in the string.
            userpass_match = re.match("(?P<username>[^:]+)(:(?P<password>.+))?", userpass)
            if not userpass_match:
                raise RuntimeError("bad format for 'userpass': '%s'" % userpass)
            # If there is a "userpass" part, then it *must* have a username
            username = userpass_match.group("username")
            if not username:
                raise RuntimeError("bad format: missing username in '%s'" % userpass)
            desc_tmp["proxy_username"] = username
            password = userpass_match.group("password")
            if password:
                desc_tmp["proxy_password"] = password
    except RuntimeError:
        sshlog = Logger("ssh")
        sshlog.error("bad proxy argument: " + reout.group(0))
        return display_name, {}
    else:
        # rip out the part we've processed
        display_name = display_name[:reout.start()] + display_name[reout.end():]
        return display_name, desc_tmp

def parse_display_name(error_cb, opts, display_name, session_name_lookup=False):
    if WIN32:
        from xpra.platform.win32.dotxpra import PIPE_PREFIX
    else:
        PIPE_PREFIX = None
    if display_name.startswith("/") and POSIX:
        display_name = "socket://"+display_name
    desc = {"display_name" : display_name}
    display_name, proxy_attrs = parse_proxy_attributes(display_name)
    desc.update(proxy_attrs)

    #split the display name on ":" or "/"
    scpos = display_name.find(":")
    slpos = display_name.find("/")
    if scpos<0 and slpos<0:
        match = None
        if POSIX:
            #maybe this is just the display number without the ":" prefix?
            try:
                display_name = ":%i" % int(display_name)
                match = True
            except ValueError:
                pass
        elif WIN32:
            display_name = "named-pipe://%s%s" % (PIPE_PREFIX, display_name)
            match = True
        if session_name_lookup and not match:
            #try to find a session whose "session-name" matches:
            match = find_session_by_name(opts, display_name)
            if match:
                display_name = match
    #display_name may have been updated, re-parse it:
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
                #ie: fe80::c1:ac45:7351:ea69%eth1:14500 -> ["fe80::c1:ac45:7351:ea69", "eth1:14500"]
                devsep = host.split("%")
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
        if s:
            #strip anything after "?" or "#"
            #TODO: parse those attributes
            for x in ("?", "#"):
                s = s.split(x)[0]
            try:
                assert [int(x) for x in s.split(".")]   #ie: ":10.0" -> [10, 0]
                display = ":" + s       #ie: ":10.0"
            except ValueError:
                display = s             #ie: "tcp://somehost:10000/"
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
        ssh = parse_ssh_string(opts.ssh)
        full_ssh = ssh[:]

        #maybe restrict to win32 only?
        ssh_cmd = ssh[0].lower()
        is_putty = ssh_cmd.endswith("plink") or ssh_cmd.endswith("plink.exe")
        is_paramiko = ssh_cmd=="paramiko"
        if is_paramiko:
            desc["is_paramiko"] = is_paramiko
        if is_putty:
            desc["is_putty"] = True
            #special env used by plink:
            env = os.environ.copy()
            env["PLINK_PROTOCOL"] = "ssh"

        username, password, host, ssh_port = parse_host_string(host, 22)
        if username:
            #TODO: let parse_host_string set it?
            desc["username"] = username
            opts.username = username
        if ssh_port and ssh_port!=22:
            desc["ssh-port"] = ssh_port
        full_ssh += add_ssh_args(username, password, host, ssh_port, is_putty, is_paramiko)
        if "proxy_host" in desc:
            proxy_username = desc.get("proxy_username", "")
            proxy_password = desc.get("proxy_password", "")
            proxy_host = desc["proxy_host"]
            proxy_port = desc.get("proxy_port", 22)
            proxy_key = desc.get("proxy_key", "")
            full_ssh += add_ssh_proxy_args(proxy_username, proxy_password, proxy_host, proxy_port,
                                           proxy_key, ssh, is_putty, is_paramiko)
        desc.update({
            "host"          : host,
            "full_ssh"      : full_ssh,
            "remote_xpra"   : opts.remote_xpra,
            })
        if opts.socket_dir:
            desc["socket_dir"] = opts.socket_dir
        if password is None and opts.password_file:
            for x in opts.password_file:
                if os.path.exists(x):
                    try:
                        with open(opts.password_file, "rb") as f:
                            desc["password"] = f.read()
                        break
                    except Exception as e:
                        warn("Error: failed to read the password file '%s':\n" % x)
                        warn(" %s\n" % e)
        return desc
    elif protocol=="socket":
        #use the socketfile specified:
        slash = afterproto.find("/")
        if 0<afterproto.find(":")<slash:
            #ie: username:password/run/user/1000/xpra/hostname-number
            #remove username and password prefix:
            parse_username_and_password(afterproto[:slash])
            sockfile = afterproto[slash:]
        elif afterproto.find("@")>=0:
            #ie: username:password@/run/user/1000/xpra/hostname-number
            parts = afterproto.split("@")
            parse_username_and_password("@".join(parts[:-1]))
            sockfile = parts[-1]
        else:
            sockfile = afterproto
        assert not WIN32, "unix-domain sockets are not supported on MS Windows"
        desc.update({
                "type"          : "unix-domain",
                "local"         : True,
                "socket_dir"    : os.path.basename(sockfile),
                "socket_dirs"   : opts.socket_dirs,
                "socket_path"   : sockfile,
                })
        opts.display = None
        return desc
    elif display_name.startswith(":"):
        assert not WIN32, "X11 display names are not supported on MS Windows"
        desc.update({
                "type"          : "unix-domain",
                "local"         : True,
                "display"       : display_name,
                "socket_dirs"   : opts.socket_dirs})
        opts.display = display_name
        if opts.socket_dir:
            desc["socket_dir"] = opts.socket_dir
        return desc
    elif protocol in ("tcp", "ssl", "udp", "ws", "wss"):
        desc.update({
                     "type"     : protocol,
                     })
        if len(parts) not in (1, 2, 3):
            error_cb("invalid %s connection string,\n" % protocol
                     +" use %s://[username[:password]@]host[:port][/display]\n" % protocol)
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
    elif WIN32 or display_name.startswith("named-pipe:"):
        if afterproto.find("@")>=0:
            parts = afterproto.split("@")
            parse_username_and_password("@".join(parts[:-1]))
            pipe_name = parts[-1]
        else:
            pipe_name = afterproto
        if not pipe_name.startswith(PIPE_PREFIX):
            pipe_name = "%s%s" % (PIPE_PREFIX, pipe_name)
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
    if not extra_args:
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
    if len(extra_args) == 1:
        return parse_display_name(error_cb, opts, extra_args[0], session_name_lookup=True)
    error_cb("too many arguments (%i): %s" % (len(extra_args), extra_args))
    return None

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
    if not allservers:
        error_cb(nomatch)
    if len(allservers)>1:
        #maybe the same server is available under multiple paths
        displays = set(v[1] for v in allservers)
        if len(displays)==1:
            #they all point to the same display, use the first one:
            allservers = allservers[:1]
    if len(allservers)>1 and noproxy:
        #try to ignore proxy instances:
        displays = set(v[1] for v in noproxy)
        if len(displays)==1:
            #they all point to the same display, use the first one:
            allservers = noproxy[:1]
    if len(allservers) > 1:
        error_cb("there are multiple servers running, please specify")
    assert len(allservers)==1
    sockdir, name, path = allservers[0]
    #ie: ("/tmp", "desktop-10", "/tmp/desktop-10")
    return sockdir, name, path


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


def socket_connect(dtype, host, port):
    if dtype=="udp":
        socktype = socket.SOCK_DGRAM
    else:
        socktype = socket.SOCK_STREAM
    family = 0  #any
    try:
        addrinfo = socket.getaddrinfo(host, port, family, socktype)
    except Exception as e:
        raise InitException("cannot get %s address of%s: %s" % ({
            socket.AF_INET6 : " IPv6",
            socket.AF_INET  : " IPv4",
            }.get(family, ""), (host, port), e))
    retry = 0
    start = monotonic_time()
    while True:
        #try each one:
        for addr in addrinfo:
            sockaddr = addr[-1]
            family = addr[0]
            sock = socket.socket(family, socktype)
            if dtype!="udp":
                from xpra.net.bytestreams import SOCKET_TIMEOUT
                sock.settimeout(SOCKET_TIMEOUT)
            try:
                sock.connect(sockaddr)
                sock.settimeout(None)
                return sock
            except Exception as e:
                log = Logger("network")
                log("failed to connect using %s%s for %s", sock.connect, sockaddr, addr, exc_info=True)
        if monotonic_time()-start>=CONNECT_TIMEOUT:
            break
        if retry==0:
            log = Logger("network")
            log.info("failed to connect to %s:%s, retrying for %i seconds", host, port, CONNECT_TIMEOUT)
        retry += 1
        import time
        time.sleep(1)
    raise InitException("failed to connect to %s:%s" % (host, port))


def get_host_target_string(display_desc, port_key="port", prefix=""):
    dtype = display_desc["type"]
    username = display_desc.get(prefix+"username")
    host = display_desc[prefix+"host"]
    try:
        port = int(display_desc.get(prefix+port_key))
        if port<0 or port>=2**16:
            port = 0
    except ValueError:
        port = 0
    display = display_desc.get(prefix+"display", "")
    return host_target_string(dtype, username, host, port, display)

def host_target_string(dtype, username, host, port, display):
    target = "%s://" % dtype
    if username:
        target += "%s@" % username
    target += host
    default_port = DEFAULT_PORTS.get(dtype, 0)
    if port and port!=default_port:
        target += ":%i" % port
    if display and display.startswith(":"):
        display = display[1:]
    target += "/%s" % (display or "")
    return target


def connect_to(display_desc, opts=None, debug_cb=None, ssh_fail_cb=None):
    from xpra.net.bytestreams import SOCKET_TIMEOUT, VSOCK_TIMEOUT, SocketConnection
    display_name = display_desc["display_name"]
    dtype = display_desc["type"]
    if dtype == "ssh":
        from xpra.net.ssh import ssh_paramiko_connect_to, ssh_exec_connect_to
        if display_desc.get("is_paramiko", False):
            return ssh_paramiko_connect_to(display_desc)
        return ssh_exec_connect_to(display_desc, opts, debug_cb, ssh_fail_cb)

    if dtype == "unix-domain":
        if not hasattr(socket, "AF_UNIX"):
            raise InitExit(EXIT_UNSUPPORTED, "unix domain sockets are not available on this operating system")
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(SOCKET_TIMEOUT)
        def sockpathfail_cb(msg):
            raise InitException(msg)
        sockpath = get_sockpath(display_desc, sockpathfail_cb)
        display_desc["socket_path"] = sockpath
        try:
            sock.connect(sockpath)
        except Exception as e:
            get_util_logger().debug("failed to connect using %s%s", sock.connect, sockpath, exc_info=True)
            raise InitException("failed to connect to '%s':\n %s" % (sockpath, e))
        sock.settimeout(None)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), display_name, dtype)
        conn.timeout = SOCKET_TIMEOUT
        target = "socket://"
        if display_desc.get("username"):
            target += "%s@" % display_desc.get("username")
        target += sockpath
        conn.target = target
        return conn

    if dtype == "named-pipe":
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
            try:
                if e.args[0]==errno.ENOENT:
                    raise InitException("the named pipe '%s' does not exist" % pipe_name)
            except AttributeError:
                pass
            raise InitException("failed to connect to the named pipe '%s':\n %s" % (pipe_name, e))
        conn = NamedPipeConnection(pipe_name, pipe_handle)
        conn.timeout = SOCKET_TIMEOUT
        conn.target = "namedpipe://%s/" % pipe_name
        return conn

    if dtype == "vsock":
        cid, iport = display_desc["vsock"]
        from xpra.net.vsock import (        #pylint: disable=no-name-in-module
            connect_vsocket,
            CID_TYPES, CID_ANY, PORT_ANY,    #@UnresolvedImport
            )
        sock = connect_vsocket(cid=cid, port=iport)
        sock.timeout = VSOCK_TIMEOUT
        sock.settimeout(None)
        conn = SocketConnection(sock, "local", "host", (CID_TYPES.get(cid, cid), iport), dtype)
        conn.target = "vsock://%s:%s" % (
            "any" if cid==CID_ANY else cid,
            "any" if iport==PORT_ANY else iport,
            )
        return conn

    if dtype in ("tcp", "ssl", "ws", "wss", "udp"):
        host = display_desc["host"]
        port = display_desc["port"]
        sock = socket_connect(dtype, host, port)
        sock.settimeout(None)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), display_name, dtype)

        if dtype=="udp":
            #mmap mode requires all packets to be received,
            #so we can free up the mmap chunks regularly
            opts.mmap = False
        strict_host_check = display_desc.get("strict-host-check")
        if strict_host_check is False:
            opts.ssl_server_verify_mode = "none"
        if dtype in ("ssl", "wss"):
            if not opts.ssl_server_hostname:
                #if the server hostname was not specified explicitly,
                #use the one from the connection string:
                opts.ssl_server_hostname = host
            wrap_socket = ssl_wrap_socket_fn(opts, server_side=False)
            sock = wrap_socket(sock)
            assert sock, "failed to wrap socket %s" % sock
            conn._socket = sock
            conn.timeout = SOCKET_TIMEOUT

        #wrap in a websocket:
        if dtype in ("ws", "wss"):
            host = display_desc["host"]
            port = display_desc.get("port", 0)
            #do the websocket upgrade and switch to binary
            try:
                from xpra.net.websockets.common import client_upgrade
            except ImportError as e:
                raise InitExit(EXIT_UNSUPPORTED, "cannot handle websocket connection: %s" % e)
            else:
                client_upgrade(conn.read, conn.write, host, port)
        conn.target = get_host_target_string(display_desc)
        return conn
    raise InitException("unsupported display type: %s" % dtype)


def ssl_wrap_socket_fn(opts, server_side=True):
    if server_side and not opts.ssl_cert:
        raise InitException("you must specify an 'ssl-cert' file to use 'bind-ssl' sockets")
    ssllog = Logger("ssl")
    ssllog("ssl_wrap_socket_fn(.., %s)", server_side)
    import ssl
    if server_side:
        verify_mode = opts.ssl_client_verify_mode
    else:
        verify_mode = opts.ssl_server_verify_mode
    ssllog("ssl_wrap_socket_fn: verify_mode(%s)=%s", server_side, verify_mode)
    #ca-certs:
    ssl_ca_certs = opts.ssl_ca_certs
    if ssl_ca_certs=="default":
        ssl_ca_certs = None
    ssllog("ssl_wrap_socket_fn: ca_certs=%s", ssl_ca_certs)
    #parse verify-mode:
    ssl_cert_reqs = getattr(ssl, "CERT_%s" % verify_mode.upper(), None)
    if ssl_cert_reqs is None:
        values = [k[len("CERT_"):].lower() for k in dir(ssl) if k.startswith("CERT_")]
        raise InitException("invalid ssl-server-verify-mode '%s', must be one of: %s" % (verify_mode, csv(values)))
    ssllog("ssl_wrap_socket_fn: cert_reqs=%#x", ssl_cert_reqs)
    #parse protocol:
    ssl_protocol = getattr(ssl, "PROTOCOL_%s" % (opts.ssl_protocol.upper().replace("V", "v")), None)
    if ssl_protocol is None:
        values = [k[len("PROTOCOL_"):] for k in dir(ssl) if k.startswith("PROTOCOL_")]
        raise InitException("invalid ssl-protocol '%s', must be one of: %s" % (opts.ssl_protocol, csv(values)))
    ssllog("ssl_wrap_socket_fn: protocol=%#x", ssl_protocol)
    #cadata may be hex encoded:
    cadata = opts.ssl_ca_data
    if cadata:
        import binascii
        try:
            cadata = binascii.unhexlify(cadata)
        except (TypeError, binascii.Error):
            import base64
            cadata = base64.b64decode(cadata)
    ssllog("ssl_wrap_socket_fn: cadata=%s", repr_ellipsized(cadata))

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
    ssllog("ssl_wrap_socket_fn: verify_flags=%#x", ssl_verify_flags)
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
    ssllog("ssl_wrap_socket_fn: options=%#x", ssl_options)

    context = ssl.SSLContext(ssl_protocol)
    context.set_ciphers(opts.ssl_ciphers)
    context.verify_mode = ssl_cert_reqs
    context.verify_flags = ssl_verify_flags
    context.options = ssl_options
    ssllog("ssl_wrap_socket_fn: cert=%s, key=%s", opts.ssl_cert, opts.ssl_key)
    if opts.ssl_cert:
        SSL_KEY_PASSWORD = os.environ.get("XPRA_SSL_KEY_PASSWORD")
        context.load_cert_chain(certfile=opts.ssl_cert or None, keyfile=opts.ssl_key or None, password=SSL_KEY_PASSWORD)
    if ssl_cert_reqs!=ssl.CERT_NONE:
        if server_side:
            purpose = ssl.Purpose.CLIENT_AUTH   #@UndefinedVariable
        else:
            purpose = ssl.Purpose.SERVER_AUTH   #@UndefinedVariable
            context.check_hostname = opts.ssl_check_hostname
            ssllog("ssl_wrap_socket_fn: check_hostname=%s", opts.ssl_check_hostname)
            if context.check_hostname:
                if not opts.ssl_server_hostname:
                    raise InitException("ssl error: check-hostname is set but server-hostname is not")
                kwargs["server_hostname"] = opts.ssl_server_hostname
        ssllog("ssl_wrap_socket_fn: load_default_certs(%s)", purpose)
        context.load_default_certs(purpose)

        ssl_ca_certs = opts.ssl_ca_certs
        if not ssl_ca_certs or ssl_ca_certs.lower()=="default":
            ssllog("ssl_wrap_socket_fn: loading default verify paths")
            context.set_default_verify_paths()
        elif not os.path.exists(ssl_ca_certs):
            raise InitException("invalid ssl-ca-certs file or directory: %s" % ssl_ca_certs)
        elif os.path.isdir(ssl_ca_certs):
            ssllog("ssl_wrap_socket_fn: loading ca certs from directory '%s'", ssl_ca_certs)
            context.load_verify_locations(capath=ssl_ca_certs)
        else:
            ssllog("ssl_wrap_socket_fn: loading ca certs from file '%s'", ssl_ca_certs)
            assert os.path.isfile(ssl_ca_certs), "'%s' is not a valid ca file" % ssl_ca_certs
            context.load_verify_locations(cafile=ssl_ca_certs)
        #handle cadata:
        if cadata:
            #PITA: because of a bug in the ssl module, we can't pass cadata,
            #so we use a temporary file instead:
            import tempfile
            with tempfile.NamedTemporaryFile(prefix='cadata') as f:
                ssllog("ssl_wrap_socket_fn: loading cadata '%s'", repr_ellipsized(cadata))
                ssllog(" using temporary file '%s'", f.name)
                f.file.write(cadata)
                f.file.flush()
                context.load_verify_locations(cafile=f.name)
    elif opts.ssl_check_hostname and not server_side:
        ssllog("cannot check hostname client side with verify mode %s", verify_mode)
    wrap_socket = context.wrap_socket
    del opts
    def do_wrap_socket(tcp_socket):
        ssllog("do_wrap_socket(%s)", tcp_socket)
        if WIN32:
            #on win32, setting the tcp socket to blocking doesn't work?
            #we still hit the following errors that we need to retry:
            from xpra.net import bytestreams
            bytestreams.CAN_RETRY_EXCEPTIONS = (ssl.SSLWantReadError, ssl.SSLWantWriteError)
        if not WIN32 or not PYTHON3:
            tcp_socket.setblocking(True)
        from xpra.exit_codes import EXIT_SSL_FAILURE, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE
        try:
            ssl_sock = wrap_socket(tcp_socket, **kwargs)
        except Exception as e:
            ssllog.debug("do_wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
            SSLEOFError = getattr(ssl, "SSLEOFError", None)
            if SSLEOFError and isinstance(e, SSLEOFError):
                return None
            raise InitExit(EXIT_SSL_FAILURE, "Cannot wrap socket %s: %s" % (tcp_socket, e))
        if not server_side:
            try:
                ssl_sock.do_handshake(True)
            except Exception as e:
                ssllog.debug("do_handshake", exc_info=True)
                SSLEOFError = getattr(ssl, "SSLEOFError", None)
                if SSLEOFError and isinstance(e, SSLEOFError):
                    return None
                status = EXIT_SSL_FAILURE
                SSLCertVerificationError = getattr(ssl, "SSLCertVerificationError", None)
                if SSLCertVerificationError and isinstance(e, SSLCertVerificationError) or getattr(e, "reason", None)=="CERTIFICATE_VERIFY_FAILED":
                    try:
                        msg = e.args[1].split(":", 2)[2]
                    except:
                        msg = str(e)
                    #ssllog.warn("host failed SSL verification: %s", msg)
                    status = EXIT_SSL_CERTIFICATE_VERIFY_FAILURE
                else:
                    msg = str(e)
                raise InitExit(status, "SSL handshake failed: %s" % msg)
        return ssl_sock
    return do_wrap_socket


def run_dialog(extra_args):
    from xpra.client.gtk_base.confirm_dialog import show_confirm_dialog
    return show_confirm_dialog(extra_args)

def run_pass(extra_args):
    from xpra.client.gtk_base.pass_dialog import show_pass_dialog
    return show_pass_dialog(extra_args)


def get_sockpath(display_desc, error_cb):
    #if the path was specified, use that:
    sockpath = display_desc.get("socket_path")
    if not sockpath:
        #find the socket using the display:
        dotxpra = DotXpra(
            display_desc.get("socket_dir"),
            display_desc.get("socket_dirs"),
            display_desc.get("username", ""),
            display_desc.get("uid", 0),
            display_desc.get("gid", 0),
            )
        display = display_desc["display"]
        def socket_details(state=DotXpra.LIVE):
            return dotxpra.socket_details(matching_state=state, matching_display=display)
        dir_servers = socket_details()
        if display and not dir_servers:
            state = dotxpra.get_display_state(display)
            if state in (DotXpra.UNKNOWN, DotXpra.DEAD):
                #found the socket for this specific display in UNKNOWN state,
                #or not found any sockets at all (DEAD),
                #this could be a server starting up,
                #so give it a bit of time:
                log = Logger("network")
                if state==DotXpra.UNKNOWN:
                    log.info("server socket for display %s is in %s state", display, DotXpra.UNKNOWN)
                else:
                    log.info("server socket for display %s not found", display)
                log.info(" waiting up to %i seconds", CONNECT_TIMEOUT)
                start = monotonic_time()
                while monotonic_time()-start<CONNECT_TIMEOUT:
                    state = dotxpra.get_display_state(display)
                    log("get_display_state(%s)=%s", display, state)
                    if state in (dotxpra.LIVE, dotxpra.INACCESSIBLE):
                        #found a final state
                        break
                    import time
                    time.sleep(0.1)
                dir_servers = socket_details()
        sockpath = single_display_match(dir_servers, error_cb,
                                        nomatch="cannot find live server for display %s" % display)[-1]
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
        return 0
    app = get_client_app(error_cb, opts, extra_args, mode)
    return do_run_client(app)

def get_client_app(error_cb, opts, extra_args, mode):
    validate_encryption(opts)
    if mode=="screenshot":
        if not extra_args:
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
    elif mode == "top":
        from xpra.client.top_client import TopClient
        app = TopClient(connect(), opts)
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
            app = make_client(error_cb, opts)
        except RuntimeError as e:
            #exceptions at this point are still initialization exceptions
            raise InitException(e.args[0])
        ehelp = "help" in opts.encodings
        if ehelp:
            from xpra.codecs.codec_constants import PREFERED_ENCODING_ORDER
            opts.encodings = PREFERED_ENCODING_ORDER
        app.init(opts)
        if opts.encoding=="auto":
            opts.encoding = ""
        if opts.encoding or ehelp:
            err = opts.encoding and (opts.encoding not in app.get_encodings())
            einfo = ""
            if err and opts.encoding!="help":
                einfo = "invalid encoding: %s\n" % opts.encoding
            if opts.encoding=="help" or ehelp or err:
                from xpra.codecs.loader import encodings_help
                encodings = ["auto"] + app.get_encodings()
                raise InitInfo(einfo+"%s xpra client supports the following encodings:\n * %s" %
                               (app.client_toolkit(), "\n * ".join(encodings_help(encodings))))
        def handshake_complete(*_args):
            log = get_util_logger()
            try:
                conn = app._protocol._conn
            except AttributeError:
                return
            log.info("Attached to %s", conn.target)
            log.info(" (press Control-C to detach)\n")
        if hasattr(app, "after_handshake"):
            app.after_handshake(handshake_complete)
        app.init_ui(opts)
        if request_mode:
            sns = get_start_new_session_dict(opts, request_mode, extra_args)
            extra_args = ["socket:%s" % opts.system_proxy_socket]
            app.hello_extra = {
                "start-new-session" : sns,
                "connect"           : True,
                }
            #we have consumed the start[-child] options
            app.start_child_new_commands = []
            app.start_new_commands = []

        def connect_to_server():
            conn, display_desc = connect()
            app.display_desc = display_desc
            #UGLY warning: connect will parse the display string,
            #which may change the username and password..
            app.username = opts.username
            app.password = opts.password
            app.display = opts.display
            app.setup_connection(conn)
            return conn

        try:
            if mode=="listen":
                if extra_args:
                    raise InitException("cannot specify extra arguments with 'listen' mode")
                from xpra.platform import get_username
                from xpra.net.socket_util import (
                    get_network_logger, setup_local_sockets, peek_connection,
                    create_sockets, add_listen_socket, accept_connection,
                    )
                sockets = create_sockets(opts, error_cb)
                #we don't have a display,
                #so we can't automatically create sockets:
                if "auto" in opts.bind:
                    opts.bind.remove("auto")
                local_sockets = setup_local_sockets(opts.bind,
                                                    opts.socket_dir, opts.socket_dirs,
                                                    None, False,
                                                    opts.mmap_group, opts.socket_permissions,
                                                    get_username(), getuid, getgid)
                sockets += local_sockets
                listen_cleanup = []
                socket_cleanup = []
                def new_connection(socktype, sock, handle=0):
                    from xpra.make_thread import start_thread
                    netlog = get_network_logger()
                    netlog("new_connection%s", (socktype, sock, handle))
                    conn = accept_connection(socktype, sock)
                    #start a thread so we can sleep in peek_connection:
                    start_thread(handle_new_connection, "handle new connection: %s" % conn, daemon=True, args=(conn, ))
                    return True
                def handle_new_connection(conn):
                    #see if this is a redirection:
                    netlog = get_network_logger()
                    peek_data, line1 = peek_connection(conn)
                    netlog("handle_new_connection(%s) line1=%s", conn, line1)
                    if line1:
                        from xpra.net.common import SOCKET_TYPES
                        uri = bytestostr(line1)
                        for socktype in SOCKET_TYPES:
                            if uri.startswith("%s://" % socktype):
                                run_socket_cleanups()
                                netlog.info("connecting to %s", uri)
                                extra_args[:] = [uri, ]
                                conn = connect_to_server()
                                app._protocol.start()
                                app.idle_add(app.send_hello)
                                return
                    app.idle_add(do_handle_connection, conn)
                def do_handle_connection(conn):
                    app.setup_connection(conn)
                    protocol = app._protocol
                    protocol.start()
                    app.send_hello()
                    #stop listening for new connections:
                    run_socket_cleanups()
                def run_socket_cleanups():
                    for cleanup in listen_cleanup:
                        cleanup()
                    listen_cleanup[:] = []
                    #close the sockets:
                    for cleanup in socket_cleanup:
                        cleanup()
                    socket_cleanup[:] = []
                for socktype, sock, sinfo, cleanup_socket in sockets:
                    socket_cleanup.append(cleanup_socket)
                    cleanup = add_listen_socket(socktype, sock, sinfo, new_connection)
                    if cleanup:
                        listen_cleanup.append(cleanup)
            else:
                connect_to_server()
        except Exception as e:
            may_notify = getattr(app, "may_notify", None)
            if may_notify:
                from xpra.util import XPRA_FAILURE_NOTIFICATION_ID
                body = str(e)
                if body.startswith("failed to connect to"):
                    lines = body.split("\n")
                    summary = "Xpra client %s" % lines[0]
                    body = "\n".join(lines[1:])
                else:
                    summary = "Xpra client failed to connect"
                may_notify(XPRA_FAILURE_NOTIFICATION_ID, summary, body, icon_name="disconnected")
            app.cleanup()
            raise
    return app

def run_opengl_probe():
    from xpra.os_util import pollwait
    from xpra.platform.paths import get_nodock_command
    log = Logger("opengl")
    cmd = get_nodock_command()+["opengl-probe"]
    env = os.environ.copy()
    if is_debug_enabled("opengl"):
        cmd += ["-d", "opengl"]
    else:
        env["NOTTY"] = "1"
    start = monotonic_time()
    try:
        kwargs = {}
        if POSIX:
            kwargs["close_fds"] = True
        try:
            from subprocess import DEVNULL
        except ImportError:
            DEVNULL = open(os.devnull, 'wb')
        proc = Popen(cmd, shell=False, stderr=DEVNULL, env=env, **kwargs)
    except Exception as e:
        log.warn("Warning: failed to execute OpenGL probe command")
        log.warn(" %s", e)
        return "probe-failed:%s" % e
    r = pollwait(proc)
    log("OpenGL probe command returned %s for command=%s", r, cmd)
    end = monotonic_time()
    log("probe took %ims", 1000*(end-start))
    if r==0:
        return "probe-success"
    if r==1:
        return "probe-crash"
    if r==2:
        return "probe-warning"
    if r==3:
        return "probe-error"
    if r is None:
        msg = "timeout"
    elif r>128:
        msg = SIGNAMES.get(r-128)
    else:
        msg = SIGNAMES.get(0-r, 0-r)
    log.warn("Warning: OpenGL probe failed: %s", msg)
    return "probe-failed:%s" % msg

def make_client(error_cb, opts):
    if POSIX and os.environ.get("GDK_BACKEND") is None and not OSX:
        os.environ["GDK_BACKEND"] = "x11"
    if opts.opengl=="probe":
        if os.environ.get("XDG_SESSION_TYPE")=="wayland":
            opts.opengl = "no"
        else:
            opts.opengl = run_opengl_probe()
    from xpra.platform.gui import init as gui_init
    gui_init()

    from xpra.scripts.config import FALSE_OPTIONS, OFF_OPTIONS
    def b(v):
        return str(v).lower() not in FALSE_OPTIONS
    def bo(v):
        return str(v).lower() not in FALSE_OPTIONS or str(v).lower() in OFF_OPTIONS
    impwarned = []
    def impcheck(*modules):
        for mod in modules:
            try:
                __import__("xpra.%s" % mod, {}, {}, [])
            except ImportError:
                if mod not in impwarned:
                    impwarned.append(mod)
                    log = get_util_logger()
                    log("impcheck%s", modules, exc_info=True)
                    log.warn("Warning: missing %s module", mod)
                return False
        return True
    from xpra.client import mixin_features
    mixin_features.display          = opts.windows
    mixin_features.windows          = opts.windows
    mixin_features.audio            = (bo(opts.speaker) or bo(opts.microphone)) and impcheck("sound")
    mixin_features.webcam           = bo(opts.webcam) and impcheck("codecs")
    mixin_features.clipboard        = b(opts.clipboard) and impcheck("clipboard")
    mixin_features.notifications    = opts.notifications and impcheck("notifications")
    mixin_features.dbus             = opts.dbus_proxy and impcheck("dbus")
    mixin_features.mmap             = b(opts.mmap)
    mixin_features.logging          = b(opts.remote_logging)
    mixin_features.tray             = b(opts.tray)
    mixin_features.network_state    = True
    mixin_features.encoding         = opts.windows
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
    from xpra.scripts.config import dict_to_config
    defaults = dict_to_config(get_defaults())
    fixup_options(defaults)
    for x in PROXY_START_OVERRIDABLE_OPTIONS:
        fn = x.replace("-", "_")
        v = getattr(opts, fn)
        dv = getattr(defaults, fn, None)
        if v and v!=dv:
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
        for x in get_start_server_args(opts, compat=True):
            proxy_args.append(x)
        #we have consumed the start[-child] options
        opts.start_child = []
        opts.start = []
        params["display_as_args"] = proxy_args
        #and use a proxy subcommand to start the server:
        params["proxy_command"] = [{
                                   "shadow"         : "_proxy_shadow_start",
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
            except ValueError:
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
                except (IOError, OSError):
                    pass
                else:
                    #print("found display path '%s'" % socket_path)
                    displays.append(v)
            except Exception as e:
                warn("failure on %s: %s" % (socket_path, e))
    return displays

def guess_X11_display(dotxpra, current_display, uid=getuid(), gid=getgid()):
    displays = [":%s" % x for x in find_X11_displays(max_display_no=10, match_uid=uid, match_gid=gid)]
    if current_display and current_display not in displays:
        displays.append(current_display)
    if len(displays)!=1:
        #try without uid match:
        displays = [":%s" % x for x in find_X11_displays(max_display_no=10, match_gid=gid)]
        if len(displays)!=1:
            #try without gid match:
            displays = [":%s" % x for x in find_X11_displays(max_display_no=10)]
    if not displays:
        raise InitExit(1, "could not detect any live X11 displays")
    if len(displays)>1:
        #since we are here to shadow,
        #assume we want to shadow a real X11 server,
        #so remove xpra's own displays to narrow things down:
        results = dotxpra.sockets()
        xpra_displays = [display for _, display in results]
        displays = list(set(displays)-set(xpra_displays))
        if not displays:
            raise InitExit(1, "could not detect any live plain X11 displays,\n"
                           +" only multiple xpra displays: %s" % csv(xpra_displays))
    if current_display:
        return current_display
    if len(displays)!=1:
        raise InitExit(1, "too many live X11 displays to choose from: %s" % csv(displays))
    return displays[0]


def no_gtk():
    if OSX and PYTHON2:
        #on macos, we may have loaded the bindings already
        #and this is not a problem there
        return
    gtk = sys.modules.get("gtk") or sys.modules.get("gi.repository.Gtk")
    if gtk is None:
        #all good, not loaded
        return
    try:
        assert gtk.ver is None
    except AttributeError:
        #got an exception, probably using the gi bindings
        #which insert a fake gtk module to trigger exceptions
        return
    raise Exception("the gtk module is already loaded: %s" % gtk)


def run_glprobe(opts, show=False):
    props = do_run_glcheck(opts, show)
    if not props.get("success", False):
        return 3
    if not props.get("safe", False):
        return 2
    return 0

def do_run_glcheck(opts, show=False):
    #suspend all logging:
    saved_level = None
    log = Logger("opengl")
    log("do_run_glcheck(.., %s)" % show)
    if not is_debug_enabled("opengl") or not use_tty():
        saved_level = logging.root.getEffectiveLevel()
        logging.root.setLevel(logging.WARN)
    try:
        from xpra.client.gl.window_backend import (
            get_opengl_backends,
            get_gl_client_window_module,
            test_gl_client_window,
            )
        opengl_str = (opts.opengl or "").lower()
        force_enable = opengl_str.split(":")[0] in TRUE_OPTIONS
        backends = get_opengl_backends(opengl_str)
        log("run_glprobe() backends=%s", backends)
        opengl_props, gl_client_window_module = get_gl_client_window_module(backends, force_enable)
        log("do_run_glcheck() opengl_props=%s, gl_client_window_module=%s", opengl_props, gl_client_window_module)
        if gl_client_window_module and (opengl_props.get("safe", False) or force_enable):
            gl_client_window_class = gl_client_window_module.GLClientWindow
            pixel_depth = int(opts.pixel_depth)
            log("do_run_glcheck() gl_client_window_class=%s, pixel_depth=%s", gl_client_window_class, pixel_depth)
            if pixel_depth not in (0, 16, 24, 30) and pixel_depth<32:
                pixel_depth = 0
            draw_result = test_gl_client_window(gl_client_window_class, pixel_depth=pixel_depth, show=show)
            opengl_props.update(draw_result)
        return opengl_props
    except Exception as e:
        if is_debug_enabled("opengl"):
            log("do_run_glcheck(..)", exc_info=True)
        if use_tty():
            sys.stderr.write("error:\n")
            sys.stderr.write("%s\n" % e)
            sys.stderr.flush()
        return {
            "success"   : False,
            "message"   : str(e).replace("\n", " "),
            }
    finally:
        if saved_level is not None:
            logging.root.setLevel(saved_level)

def run_glcheck(opts):
    try:
        props = do_run_glcheck(opts)
    except Exception as e:
        sys.stdout.write("error=%s\n" % nonl(e))
        return 1
    for k in sorted(props.keys()):
        v = props[k]
        #skip not human readable:
        if k not in ("extensions", "glconfig", "GLU.extensions", ):
            try:
                if k.endswith("dims"):
                    vstr = csv(v)
                else:
                    vstr = pver(v)
            except ValueError:
                vstr = str(v)
            sys.stdout.write("%s=%s\n" % (str(k), vstr))
    return 0


def start_server_subprocess(script_file, args, mode, opts, username="", uid=getuid(), gid=getgid(), env=os.environ.copy(), cwd=None):
    log = get_util_logger()
    log("start_server_subprocess%s", (script_file, args, mode, opts, uid, gid, env, cwd))
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs, username, uid=uid, gid=gid)
    #we must use a subprocess to avoid messing things up - yuk
    assert mode in ("start", "start-desktop", "shadow")
    if OSX:
        #we can't verify on macos because importing GtkosxApplication
        #will import Gtk, and we need GtkosxApplication early to find the paths
        return
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
                display_name = guess_X11_display(dotxpra, None, uid, gid)
            #we now know the display name, so add it:
            args = [display_name]
        opts.exit_with_client = True

    #get the list of existing sockets so we can spot the new ones:
    if display_name.startswith("S"):
        matching_display = None
    else:
        matching_display = display_name
    existing_sockets = set(dotxpra.socket_paths(check_uid=uid,
                                                matching_state=dotxpra.LIVE,
                                                matching_display=matching_display))
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
            if e.args[0]!=errno.EACCES:
                warn("Error: shadow may not start,\n"
                     +" the launch agent file '%s' seems to be missing:%s.\n" % (LAUNCH_AGENT_FILE, e))
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
                log("subprocess displayfd pipes: %s", (r_pipe, w_pipe))
                cmd.append("--displayfd=%s" % w_pipe)
                close_fds = False
                def no_close_pipes():
                    from xpra.os_util import close_fds as osclose_fds
                    if PYTHON3:
                        try:
                            for fd in (r_pipe, w_pipe):
                                os.set_inheritable(fd, True)
                        except:
                            log.error("no_close_pipes()", exc_info=True)
                    osclose_fds([0, 1, 2, r_pipe, w_pipe])
                preexec_fn = no_close_pipes
        log("start_server_subprocess: command=%s", csv(["'%s'" % x for x in cmd]))
        proc = Popen(cmd, shell=False, close_fds=close_fds, env=env, cwd=cwd, preexec_fn=preexec_fn)
        log("proc=%s", proc)
        if POSIX and not OSX and not matching_display:
            from xpra.platform.displayfd import read_displayfd, parse_displayfd
            buf = read_displayfd(r_pipe, proc=None) #proc deamonizes!
            try:
                os.close(r_pipe)
            except OSError:
                pass
            try:
                os.close(w_pipe)
            except OSError:
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
    fdefaults = defaults.clone()
    fixup_options(fdefaults)
    args = []
    for x, ftype in OPTION_TYPES.items():
        if x in NON_COMMAND_LINE_OPTIONS or x in CLIENT_ONLY_OPTIONS:
            continue
        if compat and x in OPTIONS_ADDED_SINCE_V1:
            continue
        fn = x.replace("-", "_")
        ov = getattr(opts, fn)
        dv = getattr(defaults, fn)
        fv = getattr(fdefaults, fn)
        if ftype==list:
            #compare lists using their csv representation:
            if csv(ov)==csv(dv) or csv(ov)==csv(fv):
                continue
        if ov in (dv, fv):
            continue    #same as the default
        argname = "--%s=" % x
        if compat:
            argname = OPTIONS_COMPAT_NAMES.get(argname, argname)
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
                    args.append("%s%s" % (argname, e))
            else:
                #those can be specified as CSV: (ie: "--encodings=png,jpeg,rgb")
                args.append("%s%s" % (argname, ",".join(str(v) for v in ov)))
        elif ftype==bool:
            if compat and x in ("exit-with-children", "use-display", "mmap-group"):
                #older servers don't take a bool value for those options,
                #it is disabled unless specified:
                if ov:
                    args.append("--%s" % x)
            else:
                args.append("%s%s" % (argname, ["no", "yes"][int(ov)]))
        elif ftype in (int, float, str):
            args.append("%s%s" % (argname, ov))
        else:
            raise InitException("unknown option type '%s' for '%s'" % (ftype, x))
    return args


def identify_new_socket(proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, matching_uid=0):
    log = get_util_logger()
    log("identify_new_socket%s",
        (proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, matching_uid))
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
    if mode in ("_proxy_start", "_proxy_start_desktop", "_proxy_shadow_start"):
        server_mode = {
                       "_proxy_start"           : "start",
                       "_proxy_start_desktop"   : "start-desktop",
                       "_proxy_shadow_start"    : "shadow",
                       }[mode]
        #strip defaults, only keep extra ones:
        for x in ("start", "start-child",
                  "start-after-connect", "start-child-after-connect",
                  "start-on-connect", "start-child-on-connect",
                  "start-on-last-client-exit", "start-child-on-last-client-exit",
                  ):
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
    app.run()
    return 0

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
        if final_state is DotXpra.UNKNOWN:
            print("How odd... I'm not sure what's going on with xpra at %s" % display)
            return 1
        if final_state is DotXpra.LIVE:
            print("Failed to shutdown xpra at %s" % display)
            return 1
        raise Exception("invalid state: %s" % final_state)

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
        if len(displays)==1:
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


def may_cleanup_socket(state, display, sockpath, clean_states=(DotXpra.DEAD,)):
    sys.stdout.write("\t%s session at %s" % (state, display))
    if state in clean_states:
        try:
            stat_info = os.stat(sockpath)
            if stat_info.st_uid==getuid():
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
        except (IndexError, ValueError):
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
                display = text.get("display", "")
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
    def mdns_add(interface, _protocol, name, _stype, domain, host, address, port, text):
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
            if stat_info.st_uid==getuid():
                reprobe.append(x)
        except OSError:
            pass
    if reprobe:
        sys.stdout.write("Re-probing unknown sessions in: %s\n" % csv(list(set(x[0] for x in unknown))))
        counter = 0
        timeout = LIST_REPROBE_TIMEOUT
        while reprobe and counter<timeout:
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
            if reprobe and timeout==LIST_REPROBE_TIMEOUT:
                #if all the remaining sockets are old,
                #we don't need to poll for very long,
                #as they're very likely to be dead:
                newest = 0
                import time
                for x in reprobe:
                    sockpath = x[2]
                    try:
                        mtime = os.stat(sockpath).st_mtime
                    except Exception:
                        pass
                    else:
                        newest = max(mtime, newest)
                elapsed = time.time()-newest
                if elapsed>60*5:
                    #wait maximum 3 seconds for old sockets
                    timeout = min(LIST_REPROBE_TIMEOUT, 3)
        #now cleanup those still unknown:
        clean_states = [DotXpra.DEAD, DotXpra.UNKNOWN]
        for state, display, sockpath in unknown:
            state = dotxpra.get_server_state(sockpath)
            may_cleanup_socket(state, display, sockpath, clean_states=clean_states)
    return 0

def run_showconfig(options, args):
    log = get_util_logger()
    d = dict_to_validated_config({})
    fixup_options(d)
    #this one is normally only probed at build time:
    #(so probe it here again)
    if POSIX:
        try:
            from xpra.platform.pycups_printing import get_printer_definition
            for mimetype in ("pdf", "postscript"):
                pdef = get_printer_definition(mimetype)
                if pdef:
                    #ie: d.pdf_printer = "/usr/share/ppd/cupsfilters/Generic-PDF_Printer-PDF.ppd"
                    setattr(d, "%s_printer" % mimetype, pdef)
        except Exception:
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
                       "start-on-last-client-exit", "start-child-on-last-client-exit",
                       ]
        if WIN32:
            #"exit-ssh"?
            HIDDEN += ["lpadmin", "daemon", "use-display", "mmap-group", "mdns"]
        if not OSX:
            HIDDEN += ["dock-icon", "swap-keys"]
    for opt, otype in sorted(OPTION_TYPES.items()):
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
            w("%-20s  (used)   = %-32s  %s", opt, vstr(otype, cv), type(cv))
            w("%-20s (default) = %-32s  %s", opt, vstr(otype, dv), type(dv))
        else:
            i("%-20s           = %s", opt, vstr(otype, cv))

def vstr(otype, v):
    #just used to quote all string values
    if v is None:
        if otype==bool:
            return "auto"
        return ""
    if isinstance(v, str):
        return "'%s'" % nonl(v)
    if isinstance(v, (tuple, list)):
        return csv(vstr(otype, x) for x in v)
    return str(v)

def run_showsetting(options, args):
    if not args:
        raise InitException("specify a setting to display")

    log = get_util_logger()

    settings = []
    for arg in args:
        otype = OPTION_TYPES.get(arg)
        if not otype:
            log.warn("'%s' is not a valid setting", arg)
        else:
            settings.append(arg)

    from xpra.platform import get_username
    dirs = get_xpra_defaults_dirs(username=get_username(), uid=getuid(), gid=getgid())

    #default config:
    config = get_defaults()
    def show_settings():
        for setting in settings:
            value = config.get(setting)
            log.info("%-20s: %-40s (%s)", setting, vstr(value), type(value))

    log.info("* default config:")
    show_settings()
    for d in dirs:
        config.clear()
        config.update(read_xpra_conf(d))
        log.info("* '%s':", d)
        show_settings()
    return 0


if __name__ == "__main__":
    code = main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
