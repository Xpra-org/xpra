# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import socket
import time
from optparse import OptionParser, OptionGroup
import logging
from subprocess import Popen, PIPE
import signal
import shlex

from xpra import __version__ as XPRA_VERSION
from xpra.dotxpra import DotXpra
from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED
from xpra.platform.options import add_client_options
from xpra.platform.paths import get_default_socket_dir
from xpra.platform import init as platform_init
from xpra.net.bytestreams import TwoFileConnection, SocketConnection
from xpra.scripts.config import ENCODINGS, ENCRYPTION_CIPHERS, make_defaults_struct, show_codec_help, parse_bool


def warn(msg):
    sys.stderr.write(msg+"\n")

def nox():
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]
    # This is an error on Fedora/RH, so make it an error everywhere so it will
    # be noticed:
    import warnings
    warnings.filterwarnings("error", "could not open display")


def main(script_file, cmdline):
    platform_init()
    if os.name=="posix" and os.getuid()==0:
        warn("\nWarning: running as root")
    try:
        import glib
        glib.set_prgname("Xpra")
    except:
        pass
    #################################################################
    ## NOTE NOTE NOTE
    ##
    ## If you modify anything here, then remember to update the man page
    ## (xpra.1) as well!
    ##
    ## NOTE NOTE NOTE
    #################################################################
    supports_shadow = SHADOW_SUPPORTED
    supports_server = LOCAL_SERVERS_SUPPORTED
    if supports_server:
        try:
            from xpra.x11.wait_for_x_server import wait_for_x_server    #@UnresolvedImport @UnusedImport
        except:
            supports_server = False

    command_options = [
                        "\t%prog attach [DISPLAY]\n",
                        "\t%prog detach [DISPLAY]\n",
                        "\t%prog screenshot filename [DISPLAY]\n",
                        "\t%prog info [DISPLAY]\n",
                        "\t%prog version [DISPLAY]\n"
                      ]
    if supports_server:
        command_options = ["\t%prog start DISPLAY\n",
                           "\t%prog stop [DISPLAY]\n",
                           "\t%prog list\n",
                           "\t%prog upgrade DISPLAY\n",
                           ] + command_options
    if supports_shadow:
        command_options.append("\t%prog shadow DISPLAY\n")
    if not supports_server:
        command_options.append("(This xpra installation does not support starting local servers.)")

    hidden_options = {}
    parser = OptionParser(version="xpra v%s" % XPRA_VERSION,
                          usage="\n" + "".join(command_options))
    defaults = make_defaults_struct()
    if supports_server or supports_shadow:
        group = OptionGroup(parser, "Server Options",
                    "These options are only relevant on the server when using the 'start', 'upgrade' or 'shadow' mode.")
        parser.add_option_group(group)
    if supports_server:
        group.add_option("--start-child", action="append",
                          dest="start_child", metavar="CMD", default=defaults.start_child,
                          help="program to spawn in new server (may be repeated) (default: %default)")
        group.add_option("--exit-with-children", action="store_true",
                          dest="exit_with_children", default=defaults.exit_with_children,
                          help="Terminate server when --start-child command(s) exit")
    else:
        hidden_options["start_child"] = None
        hidden_options["exit_with_children"] = False
    if supports_server or supports_shadow:
        group.add_option("--no-daemon", action="store_false",
                          dest="daemon", default=True,
                          help="Don't daemonize when running as a server")
        group.add_option("--log-file", action="store",
                      dest="log_file", default=defaults.log_file,
                      help="When daemonizing, this is where the log messages will go (default: %s)."
                      + " If a relative filename is specified the it is relative to --socket-dir,"
                      + " the value of '$DISPLAY' will be substituted with the actual display used"
                      )
    else:
        hidden_options["daemon"] = False
        hidden_options["log_file"] = defaults.log_file
    if supports_server:
        group.add_option("--use-display", action="store_true",
                          dest="use_display", default=defaults.use_display,
                          help="Use an existing display rather than starting one with xvfb")
        group.add_option("--xvfb", action="store",
                          dest="xvfb",
                          default=defaults.xvfb,
                          metavar="CMD",
                          help="How to run the headless X server (default: '%default')")
    else:
        hidden_options["use_display"] = False
        hidden_options["xvfb"] = ''
    if supports_server or supports_shadow:
        group.add_option("--bind-tcp", action="append",
                          dest="bind_tcp", default=defaults.bind_tcp,
                          metavar="[HOST]:PORT",
                          help="Listen for connections over TCP (use --password-file to secure it)."
                            + " You may specify this option multiple times with different host and port combinations")
    else:
        hidden_options["bind_tcp"] = []
    if supports_server:
        group.add_option("--no-pulseaudio", action="store_false",
                      dest="pulseaudio", default=defaults.pulseaudio,
                      help="Disable starting of a pulseaudio server for the session")
        group.add_option("--pulseaudio-command", action="store",
                      dest="pulseaudio_command", default=defaults.pulseaudio_command,
                      help="The command used to start the pulseaudio server (default: '%default')")
    else:
        hidden_options["pulseaudio"] = False
        hidden_options["pulseaudio_command"] = ""

    group = OptionGroup(parser, "Server Controlled Features",
                "These options can be used to turn certain features on or off, "
                "they can be specified on the client or on the server, "
                "but the client cannot enable them if they are disabled on the server.")
    parser.add_option_group(group)
    group.add_option("--no-clipboard", action="store_false",
                      dest="clipboard", default=defaults.clipboard,
                      help="Disable clipboard support")
    group.add_option("--no-notifications", action="store_false",
                      dest="notifications", default=defaults.notifications,
                      help="Disable forwarding of system notifications")
    group.add_option("--no-system-tray", action="store_false",
                      dest="system_tray", default=defaults.system_tray,
                      help="Disable forwarding of system tray icons")
    group.add_option("--no-cursors", action="store_false",
                      dest="cursors", default=defaults.cursors,
                      help="Disable forwarding of custom application mouse cursors")
    group.add_option("--no-bell", action="store_false",
                      dest="bell", default=defaults.bell,
                      help="Disable forwarding of the system bell")
    group.add_option("--no-mmap", action="store_false",
                      dest="mmap", default=defaults.mmap,
                      help="Disable memory mapped transfers for local connections")
    group.add_option("--readonly", action="store_true",
                      dest="readonly", default=defaults.readonly,
                      help="Ignore all keyboard input and mouse events from the clients")
    group.add_option("--enable-sharing", action="store_true",
                      dest="sharing", default=defaults.sharing,
                      help="Allow more than one client to connect to the same session")
    group.add_option("--no-speaker", action="store_false",
                      dest="speaker", default=defaults.speaker,
                      help="Disable forwarding of sound output to the client(s)")
    CODEC_HELP = """Specify the codec(s) to use for forwarding the %s sound output.
This parameter can be specified multiple times and the order in which the codecs
are specified defines the preferred codec order.
Use the special value 'help' to get a list of options.
When unspecified, all the available codecs are allowed and the first one is used."""
    group.add_option("--speaker-codec", action="append",
                      dest="speaker_codec", default=defaults.speaker_codec,
                      help=CODEC_HELP % "speaker")
    group.add_option("--no-microphone", action="store_false",
                      dest="microphone", default=defaults.microphone,
                      help="Disable forwarding of sound input to the server")
    group.add_option("--microphone-codec", action="append",
                      dest="microphone_codec", default=defaults.microphone_codec,
                      help=CODEC_HELP % "microphone")

    group = OptionGroup(parser, "Client Picture Encoding and Compression Options",
                "These options are used by the client to specify the desired picture and network data compression."
                "They may also be specified on the server as default values for those clients that do not set them.")
    parser.add_option_group(group)
    group.add_option("--encoding", action="store",
                      metavar="ENCODING", default=defaults.encoding,
                      dest="encoding", type="str",
                      help="What image compression algorithm to use: %s." % (", ".join(ENCODINGS)) +
                            " Default: %default."
                      )
    if "jpeg" in ENCODINGS:
        group.add_option("-b", "--max-bandwidth", action="store",
                          dest="max_bandwidth", type="float", default=defaults.max_bandwidth, metavar="BANDWIDTH (kB/s)",
                          help="Specify the link's maximal receive speed to auto-adjust JPEG quality, 0.0 disables. (default: %default)")
    else:
        hidden_options["max_bandwidth"] = 0
    if len(set(("jpeg", "webp", "x264")).intersection(set(ENCODINGS)))>0:
        group.add_option("--min-quality", action="store",
                          metavar="MIN-LEVEL",
                          dest="min_quality", type="int", default=defaults.min_quality,
                          help="Sets the minimum x264 encoding quality allowed in automatic quality setting (from 1 to 100, 0 to leave unset). Default: %default.")
        group.add_option("--quality", action="store",
                          metavar="LEVEL",
                          dest="quality", type="int", default=defaults.quality,
                          help="Use a fixed image compression quality - only relevant to lossy encodings (1-100, 0 to use automatic setting). Default: %default.")
    else:
        hidden_options["min_quality"] = defaults.min_quality
        hidden_options["quality"] = defaults.quality
    if "x264" in ENCODINGS:
        group.add_option("--min-speed", action="store",
                          metavar="SPEED",
                          dest="min_speed", type="int", default=defaults.min_speed,
                          help="Sets the minimum x264 encoding speed allowed in automatic speed setting (1-100, 0 to leave unset). Default: %default.")
        group.add_option("--speed", action="store",
                          metavar="SPEED",
                          dest="speed", type="int", default=defaults.speed,
                          help="Use x264 image compression with the given encoding speed (1-100, 0 to use automatic setting). Default: %default.")
    else:
        hidden_options["min_speed"] = defaults.min_speed
        hidden_options["speed"] = defaults.speed
    group.add_option("--auto-refresh-delay", action="store",
                      dest="auto_refresh_delay", type="float", default=defaults.auto_refresh_delay,
                      metavar="DELAY",
                      help="Idle delay in seconds before doing an automatic lossless refresh."
                      + " 0.0 to disable."
                      + " Default: %default.")
    group.add_option("-z", "--compress", action="store",
                      dest="compression_level", type="int", default=defaults.compression_level,
                      metavar="LEVEL",
                      help="How hard to work on compressing data."
                      + " You generally do not need to use this option,"
                      + " the default value should be adequate,"
                      + " picture data is compressed separately (see --encoding)."
                      + " 0 to disable compression,"
                      + " 9 for maximal (slowest) compression. Default: %default.")

    group = OptionGroup(parser, "Client Features Options",
                "These options control client features that affect the appearance or the keyboard.")
    parser.add_option_group(group)
    group.add_option("--opengl", action="store",
                      dest="opengl", default=defaults.opengl,
                      help="Use OpenGL accelerated rendering, options: yes,no,auto. Default: %default.")
    group.add_option("--no-windows", action="store_false",
                      dest="windows", default=defaults.windows,
                      help="Tells the server not to send any window data, only notifications and bell events will be forwarded (if enabled).")
    group.add_option("--session-name", action="store",
                      dest="session_name", default=defaults.session_name,
                      help="The name of this session, which may be used in notifications, menus, etc. Default: Xpra")
    group.add_option("--client-toolkit", action="store",
                      dest="client_toolkit", default=defaults.client_toolkit,
                      help="The type of client toolkit. Default: %s")

    group.add_option("--title", action="store",
                      dest="title", default=defaults.title,
                      help="Text which is shown as window title, may use remote metadata variables (default: '%default')")
    group.add_option("--window-icon", action="store",
                          dest="window_icon", default=defaults.window_icon,
                          help="Path to the default image which will be used for all windows (the application may override this)")
    # let the platform specific code add its own options:
    # adds "--no-tray" for platforms that support it
    add_client_options(group)
    hidden_options["no_tray"] =  False
    hidden_options["delay_tray"] =  False
    group.add_option("--tray-icon", action="store",
                          dest="tray_icon", default=defaults.tray_icon,
                          help="Path to the image which will be used as icon for the system-tray or dock")
    group.add_option("--key-shortcut", action="append",
                      dest="key_shortcut", type="str", default=defaults.key_shortcut,
                      help="Define key shortcuts that will trigger specific actions."
                      + " Defaults to 'Meta+Shift+F4:quit' if no shortcuts are defined.")
    group.add_option("--no-keyboard-sync", action="store_false",
                      dest="keyboard_sync", default=defaults.keyboard_sync,
                      help="Disable keyboard state synchronization, prevents keys from repeating on high latency links but also may disrupt applications which access the keyboard directly")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Advanced Options",
                "These options apply to both client and server. Please refer to the man page for details.")
    parser.add_option_group(group)
    group.add_option("--password-file", action="store",
                      dest="password_file", default=defaults.password_file,
                      help="The file containing the password required to connect (useful to secure TCP mode)")
    group.add_option("--dpi", action="store",
                      dest="dpi", default=defaults.dpi,
                      help="The 'dots per inch' value that client applications should try to honour (default: %default)")
    default_socket_dir_str = defaults.socket_dir or "$XPRA_SOCKET_DIR or '~/.xpra'"
    group.add_option("--socket-dir", action="store",
                      dest="socket_dir", default=defaults.socket_dir,
                      help="Directory to place/look for the socket files in (default: %s)" % default_socket_dir_str)
    debug_default = ""
    if defaults.debug:
        debug_default = "all"
    group.add_option("-d", "--debug", action="store",
                      dest="debug", default=debug_default, metavar="FILTER1,FILTER2,...",
                      help="List of categories to enable debugging for (or \"all\")")
    group.add_option("--ssh", action="store",
                      dest="ssh", default=defaults.ssh, metavar="CMD",
                      help="How to run ssh (default: '%default')")
    group.add_option("--mmap-group", action="store_true",
                      dest="mmap_group", default=defaults.mmap_group,
                      help="When creating the mmap file with the client, set the group permission on the mmap file to the same value as the owner of the server socket file we connect to (default: '%default')")
    group.add_option("--enable-pings", action="store_true",
                      dest="pings", default=defaults.pings,
                      help="Send ping packets every second to gather latency statistics")
    group.add_option("--clipboard-filter-file", action="store",
                      dest="clipboard_filter_file", default=defaults.clipboard_filter_file,
                      help="Name of a file containing regular expressions of clipboard contents that must be filtered out")
    group.add_option("--remote-xpra", action="store",
                      dest="remote_xpra", default=defaults.remote_xpra,
                      metavar="CMD",
                      help="How to run xpra on the remote host (default: '%default')")
    if len(ENCRYPTION_CIPHERS)>0:
        group.add_option("--encryption", action="store",
                          dest="encryption", default=defaults.encryption,
                          metavar="ALGO",
                          help="Specifies the encryption cipher to use, only %s is currently supported. (default: None)" % (", ".join(ENCRYPTION_CIPHERS)))
    else:
        hidden_options["encryption"] = ''

    options, args = parser.parse_args(cmdline[1:])
    if not args:
        parser.error("need a mode")

    #ensure all the option fields are set even though
    #some options are not shown to the user:
    for k,v in hidden_options.items():
        if not hasattr(options, k):
            setattr(options, k, v)
    try:
        int(options.dpi)
    except Exception, e:
        parser.error("invalid dpi: %s" % e)
    if options.encoding and options.encoding not in ENCODINGS:
        parser.error("encoding %s is not supported, try: %s" % (options.encoding, ", ".join(ENCODINGS)))
    if options.encryption:
        assert len(ENCRYPTION_CIPHERS)>0, "cannot use encryption: no ciphers available"
        if options.encryption not in ENCRYPTION_CIPHERS:
            parser.error("encryption %s is not supported, try: %s" % (options.encryption, ", ".join(ENCRYPTION_CIPHERS)))
        if not options.password_file:
            parser.error("encryption %s cannot be used without a password (see --password-file option)" % options.encryption)
    #ensure opengl is either True, False or None
    options.opengl = parse_bool("opengl", options.opengl)

    def toggle_logging(level):
        if not options.debug:
            logging.root.setLevel(level)
            return
        categories = options.debug.split(",")
        for cat in categories:
            if cat.startswith("-"):
                logging.getLogger(cat[1:]).setLevel(logging.INFO)
            if cat == "all":
                logger = logging.root
            else:
                logger = logging.getLogger(cat)
            logger.setLevel(level)

    def dump_frames(*arsg):
        import traceback
        frames = sys._current_frames()
        print("")
        print("found %s frames:" % len(frames))
        for fid,frame in frames.items():
            print("%s - %s:" % (fid, frame))
            traceback.print_stack(frame)
        print("")

    #configure default logging handler:
    mode = args.pop(0)
    if mode in ("start", "upgrade", "attach", "shadow"):
        if show_codec_help("attach" not in cmdline[1:],
                           options.speaker_codec, options.microphone_codec):
            return 0
        logging.basicConfig(format="%(asctime)s %(message)s")
    else:
        logging.root.addHandler(logging.StreamHandler(sys.stdout))

    #set debug log on if required:
    if options.debug:
        toggle_logging(logging.DEBUG)
    else:
        toggle_logging(logging.INFO)

    #register posix signals for debugging:
    if os.name=="posix":
        def sigusr1(*args):
            dump_frames()
            toggle_logging(logging.DEBUG)
        def sigusr2(*args):
            toggle_logging(logging.INFO)
        signal.signal(signal.SIGUSR1, sigusr1)
        signal.signal(signal.SIGUSR2, sigusr2)

    if (mode in ("start", "upgrade") and supports_server) or \
        (mode=="shadow" and supports_shadow):
        if len(args)>0 and mode=="start":
            #ie: "xpra start ssh:HOST:DISPLAY --start-child=xterm"
            if args[0].startswith("ssh/") or args[0].startswith("ssh:"):
                return run_remote_server(parser, options, args)
        nox()
        from xpra.scripts.server import run_server
        return run_server(parser, options, mode, script_file, args)
    elif mode in ("attach", "detach", "screenshot", "version", "info"):
        return run_client(parser, options, args, mode)
    elif mode == "stop" and supports_server:
        nox()
        return run_stop(parser, options, args)
    elif mode == "list" and supports_server:
        return run_list(parser, options, args)
    elif mode in ("_proxy", "_proxy_start") and supports_server:
        nox()
        return run_proxy(parser, options, script_file, args, mode=="_proxy_start")
    else:
        parser.error("invalid mode '%s'" % mode)
        return 1


def parse_display_name(error_cb, opts, display_name):
    desc = {"display_name" : display_name}
    if display_name.startswith("ssh:") or display_name.startswith("ssh/"):
        separator = display_name[3] # ":" or "/"
        desc["type"] = "ssh"
        desc["proxy_command"] = ["_proxy"]
        desc["local"] = False
        parts = display_name.split(separator)
        if len(parts)>2:
            host = separator.join(parts[1:-1])
            desc["display"] = ":" + parts[-1]
            desc["display_as_args"] = [desc["display"]]
        else:
            host = parts[1]
            desc["display"] = None
            desc["display_as_args"] = []
        desc["ssh"] = shlex.split(opts.ssh)
        full_ssh = desc["ssh"]
        upos = host.find("@")
        if upos>=0:
            username = host[:upos]
            host = host[upos+1:]
            ppos = username.find(":")
            if ppos>=0:
                password = username[ppos+1:]
                username = username[:ppos]
                desc["password"] = password
            desc["username"] = username
            full_ssh += ["-l", username]
        desc["host"] = host
        full_ssh += ["-T", desc["host"]]
        desc["full_ssh"] = full_ssh
        remote_xpra = opts.remote_xpra.split()
        if opts.socket_dir:
            #ie: XPRA_SOCKET_DIR=/tmp .xpra/run-xpra _proxy :10
            remote_xpra.append("--socket-dir=%s" % opts.socket_dir)
        desc["remote_xpra"] = remote_xpra
        if desc.get("password") is None and opts.password_file and os.path.exists(opts.password_file):
            try:
                try:
                    passwordFile = open(opts.password_file, "rb")
                    desc["password"] = passwordFile.read()
                finally:
                    passwordFile.close()
            except Exception, e:
                print("failed to read password file %s: %s", opts.password_file, e)
        return desc
    elif display_name.startswith(":"):
        desc["type"] = "unix-domain"
        desc["local"] = True
        desc["display"] = display_name
        desc["socket_dir"] = opts.socket_dir or get_default_socket_dir()
        return desc
    elif display_name.startswith("tcp:") or display_name.startswith("tcp/"):
        separator = display_name[3] # ":" or "/"
        desc["type"] = "tcp"
        desc["local"] = False
        parts = display_name.split(separator)
        if len(parts)!=3:
            error_cb("invalid tcp connection string, use tcp/HOST/PORT or tcp:host:port")
        port = int(parts[-1])
        if port<=0 or port>=65536:
            error_cb("invalid port number: %s" % port)
        desc["port"] = port
        desc["host"] = separator.join(parts[1:-1])
        if desc["host"] == "":
            desc["host"] = "127.0.0.1"
        return desc
    else:
        error_cb("unknown format for display name: %s" % display_name)

def pick_display(parser, opts, extra_args):
    if len(extra_args) == 0:
        # Pick a default server
        sockdir = DotXpra(opts.socket_dir or get_default_socket_dir())
        servers = sockdir.sockets()
        live_servers = [display
                        for (state, display) in servers
                        if state is DotXpra.LIVE]
        if len(live_servers) == 0:
            parser.error("cannot find a live server to connect to")
        elif len(live_servers) == 1:
            return parse_display_name(parser.error, opts, live_servers[0])
        else:
            parser.error("there are multiple servers running, please specify")
    elif len(extra_args) == 1:
        return parse_display_name(parser.error, opts, extra_args[0])
    else:
        parser.error("too many arguments")

def _socket_connect(sock, endpoint, description):
    sock.connect(endpoint)
    sock.settimeout(None)
    return SocketConnection(sock, sock.getsockname(), sock.getpeername(), description)

def connect_or_fail(display_desc):
    try:
        return connect_to(display_desc)
    except Exception, e:
        sys.exit("connection failed: %s" % e)

def ssh_connect_failed(message):
    #by the time ssh fails, we may have entered the gtk main loop
    #(and more than once thanks to the clipboard code..)
    from xpra.gtk_common.quit import gtk_main_quit_really
    gtk_main_quit_really()

def connect_to(display_desc, debug_cb=None, ssh_fail_cb=ssh_connect_failed):
    display_name = display_desc["display_name"]
    dtype = display_desc["type"]
    if dtype == "ssh":
        cmd = display_desc["full_ssh"]
        if sys.platform.startswith("win"):
            #use putty plink.exe syntax
            #unless it looks like we're using a cygwin ssh exe:
            ssh_cmd = display_desc.get("ssh", [""])[0].lower()
            if not (ssh_cmd.endswith("ssh") or ssh_cmd.endswith("ssh.exe")):
                password = display_desc.get("password")
                if password:
                    cmd += ["-pw", password]
                cmd.append("-ssh")
                cmd.append("-agent")
        cmd += display_desc["remote_xpra"] + display_desc["proxy_command"] + display_desc["display_as_args"]
        try:
            kwargs = {}
            kwargs["stderr"] = sys.stderr
            if os.name=="posix" and not sys.platform.startswith("darwin"):
                def setsid():
                    #run in a new session
                    os.setsid()
                kwargs["preexec_fn"] = setsid
            elif sys.platform.startswith("win"):
                from subprocess import CREATE_NEW_PROCESS_GROUP, CREATE_NEW_CONSOLE
                flags = CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
                kwargs["creationflags"] = flags
                kwargs["stderr"] = PIPE
            if debug_cb:
                debug_cb("starting %s tunnel" % str(cmd[0]))
                #debug_cb("starting ssh: %s with kwargs=%s" % (str(cmd), kwargs))
            child = Popen(cmd, stdin=PIPE, stdout=PIPE, **kwargs)
        except OSError, e:
            raise Exception("Error running ssh program '%s': %s" % (cmd, e))
        def abort_test(action):
            """ if ssh dies, we don't need to try to read/write from its sockets """
            e = child.poll()
            if e is not None:
                error_message = "cannot %s using %s: the SSH process has terminated with exit code=%s" % (action, display_desc["full_ssh"], e)
                if debug_cb:
                    debug_cb(error_message)
                if ssh_fail_cb:
                    ssh_fail_cb(error_message)
                raise IOError(error_message)
        def stop_tunnel():
            if os.name=="posix":
                #on posix, the tunnel may be shared with other processes
                #so don't kill it... which may leave it behind after use.
                #but at least make sure we close all the pipes:
                for name,fd in {"stdin" : child.stdin,
                                "stdout" : child.stdout,
                                "stderr" : child.stderr}.items():
                    try:
                        if fd:
                            fd.close()
                    except Exception, e:
                        print("error closing ssh tunnel %s: %s" % (name, e))
                return
            try:
                if child.poll() is None:
                    #only supported on win32 since Python 2.7
                    if hasattr(child, "terminate"):
                        child.terminate()
                    elif hasattr(os, "kill"):
                        os.kill(child.pid, signal.SIGTERM)
                    else:
                        raise Exception("cannot find function to kill subprocess")
            except Exception, e:
                print("error trying to stop ssh tunnel process: %s" % e)
        return TwoFileConnection(child.stdin, child.stdout, abort_test, target=display_name, info="SSH", close_cb=stop_tunnel)

    elif dtype == "unix-domain":
        sockdir = DotXpra(display_desc["socket_dir"])
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(5)
        sockfile = sockdir.socket_path(display_desc["display"])
        return _socket_connect(sock, sockfile, display_name)

    elif dtype == "tcp":
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        tcp_endpoint = (display_desc["host"], display_desc["port"])
        return _socket_connect(sock, tcp_endpoint, display_name)

    else:
        assert False, "unsupported display type in connect: %s" % dtype


def run_client(parser, opts, extra_args, mode):
    if mode=="screenshot":
        if len(extra_args)==0:
            parser.error("invalid number of arguments for screenshot mode")
        screenshot_filename = extra_args[0]
        extra_args = extra_args[1:]

    if mode in ("attach"):
        sys.stdout.write("xpra client version %s\n" % XPRA_VERSION)
        sys.stdout.flush()

    conn = connect_or_fail(pick_display(parser, opts, extra_args))
    if opts.compression_level < 0 or opts.compression_level > 9:
        parser.error("Compression level must be between 0 and 9 inclusive.")
    if opts.quality!=-1 and (opts.quality < 0 or opts.quality > 100):
        parser.error("Quality must be between 0 and 100 inclusive. (or -1 to disable)")

    if mode=="screenshot":
        from xpra.client.gobject_client_base import ScreenshotXpraClient
        app = ScreenshotXpraClient(conn, opts, screenshot_filename)
    elif mode=="info":
        from xpra.client.gobject_client_base import InfoXpraClient
        app = InfoXpraClient(conn, opts)
    elif mode=="version":
        from xpra.client.gobject_client_base import VersionXpraClient
        app = VersionXpraClient(conn, opts)
    else:
        app = None
        if opts.client_toolkit:
            toolkits = {}
            try:
                import gtk.gdk                      #@UnusedImport
                import xpra.client.gtk2             #@UnusedImport
                toolkits["gtk2"] = "xpra.client.gtk2.client"
            except:
                pass
            try:
                from gi.repository import Gtk       #@UnresolvedImport @UnusedImport
                import xpra.client.gtk3             #@UnusedImport
                toolkits["gtk3"] = "xpra.client.gtk3.client"
            except:
                pass
            try:
                from PyQt4 import QtCore, QtGui     #@UnusedImport
                import xpra.client.qt4              #@UnusedImport
                toolkits["qt4"] = "xpra.client.qt4.client"
            except Exception, e:
                print("failed to load qt client: %s", e)
                pass
            client_module = toolkits.get(opts.client_toolkit)
            if client_module is None:
                parser.error("invalid client toolkit: %s, try one of: %s" % (
                            opts.client_toolkit, ", ".join(toolkits.keys())))
            else:
                toolkit_module = __import__(client_module, globals(), locals(), ['XpraClient'])
                #print("toolkit_module(%s)=%s" % (client_module, toolkit_module))
                if toolkit_module:
                    app = toolkit_module.XpraClient(conn, opts)
        if not app:
            from xpra.client.client import XpraClient
            app = XpraClient(conn, opts)
        def handshake_complete(*args):
            from xpra.log import Logger
            log = Logger()
            if mode=="detach":
                log.info("handshake-complete: detaching")
                app.quit(0)
            elif mode=="attach":
                log.info("Attached to %s (press Control-C to detach)\n" % conn.target)
        if hasattr(app, "connect"):
            app.connect("handshake-complete", handshake_complete)
    return do_run_client(app, conn.target, mode)

def do_run_client(app, target, mode):
    try:
        try:
            return app.run()
        except KeyboardInterrupt:
            return -signal.SIGINT
    finally:
        app.cleanup()

def run_remote_server(parser, opts, args):
    """ Uses the regular XpraClient with patched proxy arguments to tell run_proxy to start the server """
    params = parse_display_name(parser.error, opts, args[0])
    #add special flags to "display_as_args"
    proxy_args = [params["display"]]
    if opts.start_child:
        for c in opts.start_child:
            proxy_args.append("--start-child=%s" % c)
    if opts.exit_with_children:
        proxy_args.append("--exit-with-children")
    params["display_as_args"] = proxy_args
    #and use _proxy_start subcommand:
    params["proxy_command"] = ["_proxy_start"]
    conn = connect_or_fail(params)
    from xpra.client.client import XpraClient
    app = XpraClient(conn, opts)
    do_run_client(app, params["display_name"], "attach")

def run_proxy(parser, opts, script_file, args, start_server=False):
    from xpra.server.proxy import XpraProxy
    assert "gtk" not in sys.modules
    if start_server:
        assert len(args)==1
        display_name = args[0]
        #we must use a subprocess to avoid messing things up - yuk
        cmd = [script_file, "start"]+args
        if opts.start_child and len(opts.start_child)>0:
            for x in opts.start_child:
                cmd.append("--start-child=%s" % x)
        if opts.exit_with_children:
            cmd.append("--exit-with-children")
        def setsid():
            os.setsid()
        Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, preexec_fn=setsid)
        dotxpra = DotXpra()
        start = time.time()
        while dotxpra.server_state(display_name, 1)!=DotXpra.LIVE:
            if time.time()-start>5:
                warn("server failed to start after %.1f seconds - sorry!" % (time.time()-start))
                return
            time.sleep(0.10)
    server_conn = connect_or_fail(pick_display(parser, opts, args))
    app = XpraProxy(TwoFileConnection(sys.stdout, sys.stdin, info="stdin/stdout"), server_conn)
    signal.signal(signal.SIGINT, app.quit)
    signal.signal(signal.SIGTERM, app.quit)
    app.run()
    return  0

def run_stop(parser, opts, extra_args):
    assert "gtk" not in sys.modules
    from xpra.client.gobject_client_base import StopXpraClient

    def show_final_state(display):
        sockdir = DotXpra(opts.socket_dir)
        for _ in range(6):
            final_state = sockdir.server_state(display)
            if final_state is DotXpra.LIVE:
                time.sleep(0.5)
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

    display_desc = pick_display(parser, opts, extra_args)
    conn = connect_or_fail(display_desc)
    e = 1
    try:
        app = StopXpraClient(conn, opts)
        e = app.run()
    finally:
        app.cleanup()
    if display_desc["local"]:
        show_final_state(display_desc["display"])
    else:
        print("Sent shutdown command")
    return  e


def may_cleanup_socket(sockdir, state, display, clean_states=[DotXpra.DEAD]):
    sys.stdout.write("\t%s session at %s" % (state, display))
    if state in clean_states:
        try:
            os.unlink(sockdir.socket_path(display))
        except OSError:
            pass
        else:
            sys.stdout.write(" (cleaned up)")
    sys.stdout.write("\n")

def run_list(parser, opts, extra_args):
    assert "gtk" not in sys.modules
    if extra_args:
        parser.error("too many arguments for mode")
    sockdir = DotXpra(opts.socket_dir)
    results = sockdir.sockets()
    if not results:
        sys.stdout.write("No xpra sessions found\n")
        return  1
    sys.stdout.write("Found the following xpra sessions:\n")
    for state, display in results:
        may_cleanup_socket(sockdir, state, display)
    #now, re-probe the "unknown" ones:
    unknown = [display for state, display in results if state==DotXpra.UNKNOWN]
    if len(unknown)>0:
        sys.stdout.write("Re-probing unknown sessions: %s\n" % (", ".join(unknown)))
    counter = 0
    while len(unknown)>0 and counter<5:
        time.sleep(1)
        counter += 1
        probe_list = list(unknown)
        unknown = []
        for display in probe_list:
            state = sockdir.server_state(display)
            if state is DotXpra.DEAD:
                may_cleanup_socket(sockdir, state, display)
            elif state is DotXpra.UNKNOWN:
                unknown.append(display)
            else:
                sys.stdout.write("\t%s session at %s\n" % (state, display))
    #now cleanup those still unknown:
    clean_states = [DotXpra.DEAD, DotXpra.UNKNOWN]
    for display in unknown:
        state = sockdir.server_state(display)
        may_cleanup_socket(sockdir, state, display, clean_states=clean_states)
    return 0


if __name__ == "__main__":
    code = main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
