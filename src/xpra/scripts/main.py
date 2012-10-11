# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
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

import xpra
from xpra.dotxpra import DotXpra
from xpra.platform import (XPRA_LOCAL_SERVERS_SUPPORTED,
                           DEFAULT_SSH_CMD,
                           GOT_PASSWORD_PROMPT_SUGGESTION,
                           add_client_options)
from xpra.bytestreams import TwoFileConnection, SocketConnection

from wimpiggy.gobject_compat import import_gobject, is_gtk3
import_gobject()
try:
    import Image
    assert Image
    _has_PIL = True
except:
    _has_PIL = False
ENCODINGS = []
if is_gtk3():
    """ with gtk3, we get png via cairo out of the box
        but we need PIL for the others:
    """
    ENCODINGS.append("png")
    if _has_PIL:
        ENCODINGS.append("jpeg")
        ENCODINGS.append("rgb24")
else:
    """ with gtk2, we get rgb24 via gdk pixbuf out of the box
        but we need PIL for the others:
    """
    if _has_PIL:
        ENCODINGS.append("png")
        ENCODINGS.append("jpeg")
    ENCODINGS.append("rgb24")
#we need rgb24 for x264 and vpx (as well as the cython bindings and libraries):
if "rgb24" in ENCODINGS:
    try:
        from xpra import vpx            #@UnusedImport
        try:
            from xpra.vpx import codec      #@UnusedImport @UnresolvedImport @Reimport
            ENCODINGS.insert(0, "vpx")
        except Exception, e:
            print("cannot load vpx codec: %s" % e)
    except ImportError, e:
        #the vpx module does not exist
        #xpra was probably built with --without-vpx
        pass
    try:
        from xpra import x264           #@UnusedImport
        try:
            from xpra.x264 import codec     #@UnusedImport @UnresolvedImport
            ENCODINGS.insert(0, "x264")
        except Exception, e:
            print("cannot load x264 codec: %s" % e)
    except ImportError, e:
        #the x264 module does not exist
        #xpra was probably built with --without-x264
        pass
    try:
        from xpra.webm.decode import DecodeRGB      #@UnusedImport
        from xpra.webm.encode import EncodeRGB      #@UnusedImport
        ENCODINGS.append("webp")
    except ImportError, e:
        #the webm module does not exist
        #xpra was probably built with --without-webp
        pass
    except Exception, e:
        print("cannot load webp: %s" % e)
ENCRYPTION_CIPHERS = []
try:
    from Crypto.Cipher import AES
    assert AES
    ENCRYPTION_CIPHERS.append("AES")
except:
    pass


def read_xpra_conf(conf_dir):
    d = {}
    if not os.path.exists(conf_dir) or not os.path.isdir(conf_dir):
        return  d
    conf_file = os.path.join(conf_dir, 'xpra.conf')
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        return  d
    f = open(conf_file, "rU")
    for line in f:
        sline = line.strip()
        if len(sline) == 0:
            continue
        if sline[0] in ( '!', '#' ):
            continue
        if sline.find("=")<=0:
            continue
        props = sline.split("=", 1)
        assert len(props)==2
        name = props[0].strip()
        value = props[1].strip()
        current_value = d.get(name)
        if current_value:
            if type(current_value)==list:
                d[name] = current_value + [value]
            else:
                d[name] = [current_value, value]
        else:
            d[name] = value
    f.close()
    return  d

def read_xpra_defaults():
    #first, read the global defaults:
    if sys.platform.startswith("win"):
        conf_dir = os.path.dirname(sys.executable)
    elif sys.prefix == '/usr':
        conf_dir = '/etc/xpra'
    else:
        conf_dir = sys.prefix + '/etc/xpra/'
    defaults = read_xpra_conf(conf_dir)
    #now load the per-user config over it:
    if sys.platform.startswith("win"):
        conf_dir = os.path.join(os.environ.get("APPDATA"), "Xpra")
    else:
        conf_dir = os.path.expanduser("~/.xpra")
    user_defaults = read_xpra_conf(conf_dir)
    for k,v in user_defaults.items():
        defaults[k] = v
    return defaults

def nox():
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]
    # This is an error on Fedora/RH, so make it an error everywhere so it will
    # be noticed:
    import warnings
    warnings.filterwarnings("error", "could not open display")

def main(script_file, cmdline):
    #################################################################
    ## NOTE NOTE NOTE
    ##
    ## If you modify anything here, then remember to update the man page
    ## (xpra.1) as well!
    ##
    ## NOTE NOTE NOTE
    #################################################################
    defaults = read_xpra_defaults()
    def parse_or_use_default(varname, default_value, parse_function):
        """ Utility method for parsing defaults """
        v = defaults.get(varname)
        if not v:
            return default_value
        try:
            pv = parse_function(v)
            if pv is not None:
                return pv
        except Exception, e:
            print("invalid value '%s' for %s: %s, using default value %s instead" % (v, varname, e, default_value))
        return default_value
    def bool_default(varname, default_value):
        def bool_parse(v):
            if type(v)==str:
                v = v.lower()
            if v in ["yes", "true", "1"]:
                return  True
            if v in ["no", "false", "0"]:
                return  False
        return parse_or_use_default(varname, default_value, bool_parse)
    def int_default(varname, default_value):
        return parse_or_use_default(varname, default_value, int)
    def float_default(varname, default_value):
        return parse_or_use_default(varname, default_value, float)
    def string_list(varname, default_value):
        v = defaults.get(varname)
        if v is None:
            return default_value
        if type(v)==list:
            return v
        return [str(v)]

    if XPRA_LOCAL_SERVERS_SUPPORTED:
        start_str = "\t%prog start DISPLAY\n"
        list_str = "\t%prog list\n"
        upgrade_str = "\t%prog upgrade DISPLAY"
        note_str = ""
        stop_str = "\t%prog stop [DISPLAY]\n"
    else:
        start_str = ""
        list_str = ""
        upgrade_str = ""
        note_str = "(This xpra installation does not support starting local servers.)"
        stop_str = ""
    parser = OptionParser(version="xpra v%s" % xpra.__version__,
                          usage="".join(["\n",
                                         start_str,
                                         "\t%prog attach [DISPLAY]\n",
                                         "\t%prog detach [DISPLAY]\n",
                                         "\t%prog screenshot filename [DISPLAY]\n",
                                         "\t%prog info [DISPLAY]\n",
                                         "\t%prog version [DISPLAY]\n",
                                         stop_str,
                                         list_str,
                                         upgrade_str,
                                         note_str]))
    if XPRA_LOCAL_SERVERS_SUPPORTED:
        group = OptionGroup(parser, "Server Options",
                    "These options are only relevant on the server when using the 'start' or 'upgrade' mode.")
        group.add_option("--start-child", action="append",
                          dest="children", metavar="CMD", default=string_list("start-child", [""]),
                          help="program to spawn in new server (may be repeated) (default: '%default')")
        group.add_option("--exit-with-children", action="store_true",
                          dest="exit_with_children", default=False,
                          help="Terminate server when --start-child command(s) exit")
        group.add_option("--no-daemon", action="store_false",
                          dest="daemon", default=True,
                          help="Don't daemonize when running as a server")
        group.add_option("--use-display", action="store_true",
                          dest="use_display", default=False,
                          help="Use an existing display rather than starting one with xvfb")
        DEFAULT_XVFB = "Xvfb -dpi 96 +extension Composite -screen 0 3840x2560x24+32 -nolisten tcp -noreset -auth $XAUTHORITY"
        group.add_option("--xvfb", action="store",
                          dest="xvfb",
                          default=defaults.get("xvfb", DEFAULT_XVFB),
                          metavar="CMD",
                          help="How to run the headless X server (default: '%default')")
        group.add_option("--bind-tcp", action="store",
                          dest="bind_tcp", default=None,
                          metavar="[HOST]:PORT",
                          help="Listen for connections over TCP (insecure)")
        parser.add_option_group(group)

    group = OptionGroup(parser, "Server Controlled Features",
                "These options can be used to turn on or off certain features, "
                "they can be specified on the client or on the server, "
                "but the client cannot enable them if they are disabled on the server.")
    group.add_option("--no-clipboard", action="store_false",
                      dest="clipboard", default=bool_default("clipboard", True),
                      help="Disable clipboard support")
    group.add_option("--no-pulseaudio", action="store_false",
                      dest="pulseaudio", default=bool_default("pulseaudio", True),
                      help="Disable pulseaudio support via X11 root window properties")
    group.add_option("--no-notifications", action="store_false",
                      dest="notifications", default=bool_default("notifications", True),
                      help="Disable forwarding of system notifications")
    group.add_option("--no-cursors", action="store_false",
                      dest="cursors", default=bool_default("cursors", True),
                      help="Disable forwarding of custom application mouse cursors")
    group.add_option("--no-bell", action="store_false",
                      dest="bell", default=bool_default("bell", True),
                      help="Disable forwarding of the system bell")
    group.add_option("--no-mmap", action="store_false",
                      dest="mmap", default=bool_default("mmap", True),
                      help="Disable memory mapped transfers for local connections")
    group.add_option("--readonly", action="store_true",
                      dest="readonly", default=bool_default("readonly", False),
                      help="Ignore all keyboard input and mouse events from the clients")
    group.add_option("--enable-sharing", action="store_true",
                      dest="sharing", default=bool_default("sharing", False),
                      help="Allow more than one client to connect to the same session")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Client Picture Encoding and Compression Options",
                "These options are used by the client to specify the desired picture and network data compression.")
    default_encoding = defaults.get("encoding", ENCODINGS[0])
    group.add_option("--encoding", action="store",
                      metavar="ENCODING", default=default_encoding,
                      dest="encoding", type="str",
                      help="What image compression algorithm to use: %s. Default: %s" % (", ".join(ENCODINGS), default_encoding))
    if "jpeg" in ENCODINGS:
        group.add_option("--jpeg-quality", action="store",
                          metavar="LEVEL",
                          dest="quality", type="int", default=None,
                          help="Deprecated - use 'quality'")
        group.add_option("--quality", action="store",
                          metavar="LEVEL",
                          dest="quality", type="int", default=int_default("quality", -1),
                          help="Use image compression with the given quality - only relevant to lossy encodings (1-100, -1 to disable). Default: %default.")
        group.add_option("-b", "--max-bandwidth", action="store",
                          dest="max_bandwidth", type="float", default=0.0, metavar="BANDWIDTH (kB/s)",
                          help="Specify the link's maximal receive speed to auto-adjust JPEG quality, 0.0 disables. (default: disabled)")
    group.add_option("--auto-refresh-delay", action="store",
                      dest="auto_refresh_delay", type="float", default=float_default("auto-refresh-delay", 1.0),
                      metavar="DELAY",
                      help="Idle delay in seconds before doing an automatic lossless refresh."
                      + " 0.0 to disable."
                      + " Default: %default.")
    DEFAULT_COMPRESS = 1
    compress_str = defaults.get("compress", str(DEFAULT_COMPRESS))
    try:
        compress = int(compress_str)
    except:
        print("WARNING: invalid default value for 'compress' option, using default: %s" % DEFAULT_COMPRESS)
        compress = DEFAULT_COMPRESS
    group.add_option("-z", "--compress", action="store",
                      dest="compression_level", type="int", default=compress,
                      metavar="LEVEL",
                      help="How hard to work on compressing data."
                      + " You generally do not need to use this option,"
                      + " the default value should be adequate."
                      + " 0 to disable compression,"
                      + " 9 for maximal (slowest) compression. Default: %default.")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Client Features Options",
                "These options control client features that affect the appearance or the keyboard.")
    group.add_option("--no-windows", action="store_false",
                      dest="windows_enabled", default=True,
                      help="Tells the server not to send any window data, only notifications and bell events will be forwarded - if enabled.")
    group.add_option("--session-name", action="store",
                      dest="session_name", default=None,
                      help="The name of this session, which may be used in notifications, menus, etc. Default: Xpra")
    group.add_option("--title", action="store",
                      dest="title", default="@title@ on @client-machine@",
                      help="Text which is shown as window title, may use remote metadata variables (default: '@title@ on @client-machine@')")
    group.add_option("--window-icon", action="store",
                          dest="window_icon", default=None,
                          help="Path to the default image which will be used for all windows (the application may override this)")
    # let the platform specific code add its own options:
    # adds "--no-tray" for platforms that support it
    add_client_options(group)
    group.add_option("--tray-icon", action="store",
                          dest="tray_icon", default=None,
                          help="Path to the image which will be used as icon for the system-tray or dock")
    group.add_option("--key-shortcut", action="append",
                      dest="key_shortcuts", type="str", default=[],
                      help="Define key shortcuts that will trigger specific actions."
                      + " Defaults to 'Meta+Shift+F4:quit' if no shortcuts are defined.")
    group.add_option("--no-keyboard-sync", action="store_false",
                      dest="keyboard_sync", default=bool_default("keyboard-sync", True),
                      help="Disable keyboard state synchronization, prevents keys from repeating on high latency links but also may disrupt applications which access the keyboard directly")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Advanced Options",
                "These options apply to both client and server. Please refer to the man page for details.")
    group.add_option("--password-file", action="store",
                      dest="password_file", default=None,
                      help="The file containing the password required to connect (useful to secure TCP mode)")
    group.add_option("--dpi", action="store",
                      dest="dpi", default=int_default("dpi", 96),
                      help="The 'dots per inch' value that client applications should try to honour (default: %default)")
    default_socket_dir = defaults.get("socket-dir")
    default_socket_dir_str = default_socket_dir or "$XPRA_SOCKET_DIR or '~/.xpra'"
    group.add_option("--socket-dir", action="store",
                      dest="sockdir", default=default_socket_dir,
                      help="Directory to place/look for the socket files in (default: %s)" % default_socket_dir_str)
    debug_default = None
    if bool_default("debug", False):
        debug_default = "all"
    group.add_option("-d", "--debug", action="store",
                      dest="debug", default=debug_default, metavar="FILTER1,FILTER2,...",
                      help="List of categories to enable debugging for (or \"all\")")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Advanced Client Options",
                "Please refer to the man page for details.")
    group.add_option("--ssh", action="store",
                      dest="ssh", default=defaults.get("ssh", DEFAULT_SSH_CMD), metavar="CMD",
                      help="How to run ssh (default: '%default')")
    group.add_option("--mmap-group", action="store_true",
                      dest="mmap_group", default=bool_default("mmap-group", False),
                      help="When creating the mmap file with the client, set the group permission on the mmap file to the same value as the owner of the server socket file we connect to (default: '%default')")
    group.add_option("--enable-pings", action="store_true",
                      dest="send_pings", default=bool_default("pings", False),
                      help="Send ping packets every second to gather latency statistics")
    group.add_option("--remote-xpra", action="store",
                      dest="remote_xpra", default=".xpra/run-xpra",
                      metavar="CMD",
                      help="How to run xpra on the remote host (default: '%default')")
    if len(ENCRYPTION_CIPHERS)>0:
        group.add_option("--encryption", action="store",
                          dest="encryption", default=None,
                          metavar="CMD",
                          help="Specifies the encryption cipher to use, only %s is currently supported. (default: None)" % (", ".join(ENCRYPTION_CIPHERS)))
    parser.add_option_group(group)

    options, args = parser.parse_args(cmdline[1:])
    if not args:
        parser.error("need a mode")
    if "jpeg" not in ENCODINGS:
        #ensure the default values are set even though
        #the option is not shown to the user as it is not available
        options.quality = 80
        options.max_bandwidth = 0
    try:
        int(options.dpi)
    except Exception, e:
        parser.error("invalid dpi: %s" % e)
    if len(ENCRYPTION_CIPHERS)==0:
        #if no encryption options are available the option is not shown
        #but we still need to set a value to avoid errors later on:
        options.encryption = ""
    if options.encoding and options.encoding not in ENCODINGS:
        parser.error("encoding %s is not supported, try: %s" % (options.encoding, ", ".join(ENCODINGS)))
    if options.encryption:
        assert len(ENCRYPTION_CIPHERS)>0
        if options.encryption not in ENCRYPTION_CIPHERS:
            parser.error("encryption %s is not supported, try: %s" % (options.encryption, ", ".join(ENCRYPTION_CIPHERS)))
        if not options.password_file:
            parser.error("encryption %s cannot be used without a password (see --password-file option)" % options.encryption)

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
    if mode in ("start", "upgrade", "attach"):
        logging.basicConfig(format="%(asctime)s %(message)s")
    else:
        logging.root.addHandler(logging.StreamHandler(sys.stdout))

    #set debug log on if required:
    if options.debug is not None:
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

    if mode in ("start", "upgrade") and XPRA_LOCAL_SERVERS_SUPPORTED:
        nox()
        from xpra.scripts.server import run_server
        return run_server(parser, options, mode, script_file, args)
    elif mode in ("attach", "detach", "screenshot", "version", "info"):
        return run_client(parser, options, args, mode)
    elif mode == "stop" and XPRA_LOCAL_SERVERS_SUPPORTED:
        nox()
        return run_stop(parser, options, args)
    elif mode == "list" and XPRA_LOCAL_SERVERS_SUPPORTED:
        return run_list(parser, options, args)
    elif mode == "_proxy" and XPRA_LOCAL_SERVERS_SUPPORTED:
        nox()
        return run_proxy(parser, options, args)
    else:
        parser.error("invalid mode '%s'" % mode)
        return 1

def get_default_socket_dir():
    return os.environ.get("XPRA_SOCKET_DIR", "~/.xpra")

def parse_display_name(parser, opts, display_name):
    desc = {"display_name" : display_name}
    if display_name.startswith("ssh:") or display_name.startswith("ssh/"):
        separator = display_name[3] # ":" or "/"
        desc["type"] = "ssh"
        desc["local"] = False
        parts = display_name.split(separator)
        if len(parts)>2:
            desc["host"] = separator.join(parts[1:-1])
            desc["display"] = parts[-1]
            desc["display"] = ":" + desc["display"]
            desc["display_as_args"] = [desc["display"]]
        else:
            desc["host"] = parts[1]
            desc["display"] = None
            desc["display_as_args"] = []
        desc["ssh"] = shlex.split(opts.ssh)
        desc["full_ssh"] = desc["ssh"] + ["-T", desc["host"]]
        remote_xpra = opts.remote_xpra.split()
        if opts.sockdir:
            #ie: XPRA_SOCKET_DIR=/tmp .xpra/run-xpra _proxy :10
            remote_xpra.append("--socket-dir=%s" % opts.sockdir)
        desc["remote_xpra"] = remote_xpra
        desc["full_remote_xpra"] = desc["full_ssh"] + desc["remote_xpra"]
        return desc
    elif display_name.startswith(":"):
        desc["type"] = "unix-domain"
        desc["local"] = True
        desc["display"] = display_name
        desc["sockdir"] = opts.sockdir or get_default_socket_dir()
        return desc
    elif display_name.startswith("tcp:") or display_name.startswith("tcp/"):
        separator = display_name[3] # ":" or "/"
        desc["type"] = "tcp"
        desc["local"] = False
        parts = display_name.split(separator)
        port = int(parts[-1])
        if port<=0 or port>=65536:
            parser.error("invalid port number: %s" % port)
        desc["port"] = port
        desc["host"] = separator.join(parts[1:-1])
        if desc["host"] == "":
            desc["host"] = "127.0.0.1"
        return desc
    else:
        parser.error("unknown format for display name: %s" % display_name)

def pick_display(parser, opts, extra_args):
    if len(extra_args) == 0:
        # Pick a default server
        sockdir = DotXpra(opts.sockdir or get_default_socket_dir())
        servers = sockdir.sockets()
        live_servers = [display
                        for (state, display) in servers
                        if state is DotXpra.LIVE]
        if len(live_servers) == 0:
            parser.error("cannot find a live server to connect to")
        elif len(live_servers) == 1:
            return parse_display_name(parser, opts, live_servers[0])
        else:
            parser.error("there are multiple servers running, please specify")
    elif len(extra_args) == 1:
        return parse_display_name(parser, opts, extra_args[0])
    else:
        parser.error("too many arguments")

def _socket_connect(sock, endpoint, description):
    try:
        sock.settimeout(10)
        sock.connect(endpoint)
    except socket.error, e:
        sys.exit("Connection failed: %s" % (e,))
        return
    sock.settimeout(None)
    return SocketConnection(sock, sock.getsockname(), sock.getpeername(), description)

def connect_or_fail(display_desc):
    display_name = display_desc["display_name"]
    if display_desc["type"] == "ssh":
        cmd = (display_desc["full_remote_xpra"]
               + ["_proxy"] + display_desc["display_as_args"])
        try:
            child = Popen(cmd, stdin=PIPE, stdout=PIPE)
        except OSError, e:
            sys.exit("Error running ssh program '%s': %s" % (cmd[0], e))
        def abort_test(action):
            """ if ssh dies, we don't need to try to read/write from its sockets """
            e = child.poll()
            if e is not None:
                error_message = "cannot %s using %s: the SSH process has terminated with exit code=%s" % (action, display_desc["full_ssh"], e)
                print(error_message)
                from wimpiggy.util import gtk_main_quit_really
                gtk_main_quit_really()
                raise IOError(error_message)
        return TwoFileConnection(child.stdin, child.stdout, abort_test, target=display_name)

    elif display_desc["type"] == "unix-domain":
        sockdir = DotXpra(display_desc["sockdir"])
        sock = socket.socket(socket.AF_UNIX)
        sockfile = sockdir.socket_path(display_desc["display"])
        return _socket_connect(sock, sockfile, display_name)

    elif display_desc["type"] == "tcp":
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_endpoint = (display_desc["host"], display_desc["port"])
        return _socket_connect(sock, tcp_endpoint, display_name)

    else:
        assert False, "unsupported display type in connect"


def run_client(parser, opts, extra_args, mode):
    if mode=="screenshot":
        if len(extra_args)==0:
            parser.error("invalid number of arguments for screenshot mode")
        screenshot_filename = extra_args[0]
        extra_args = extra_args[1:]

    conn = connect_or_fail(pick_display(parser, opts, extra_args))
    if opts.compression_level < 0 or opts.compression_level > 9:
        parser.error("Compression level must be between 0 and 9 inclusive.")
    if opts.quality!=-1 and (opts.quality < 0 or opts.quality > 100):
        parser.error("Quality must be between 0 and 100 inclusive. (or -1 to disable)")

    if mode=="screenshot":
        from xpra.client_base import ScreenshotXpraClient
        app = ScreenshotXpraClient(conn, opts, screenshot_filename)
    elif mode=="info":
        from xpra.client_base import InfoXpraClient
        app = InfoXpraClient(conn, opts)
    elif mode=="version":
        from xpra.client_base import VersionXpraClient
        app = VersionXpraClient(conn, opts)
    else:
        from xpra.client import XpraClient
        app = XpraClient(conn, opts)
    def got_gibberish_msg(obj, data):
        if str(data).find("assword")>0:
            sys.stdout.write("Your ssh program appears to be asking for a password.\n"
                             + GOT_PASSWORD_PROMPT_SUGGESTION)
            sys.stdout.flush()
        if str(data).find("login")>=0:
            sys.stdout.write("Your ssh program appears to be asking for a username.\n"
                             "Perhaps try using something like 'ssh:USER@host:display'?\n")
            sys.stdout.flush()
    app.connect("received-gibberish", got_gibberish_msg)
    def handshake_complete(*args):
        from wimpiggy.log import Logger
        log = Logger()
        if mode=="detach":
            log.info("handshake-complete: detaching")
            app.quit(0)
        elif mode=="attach":
            log.info("Attached to %s (press Control-C to detach)\n" % conn.target)
    app.connect("handshake-complete", handshake_complete)
    def client_SIGINT(*args):
        print("received SIGINT, closing")
        app.quit(-signal.SIGINT)
    signal.signal(signal.SIGINT, client_SIGINT)
    try:
        try:
            return app.run()
        except KeyboardInterrupt, e:
            return -signal.SIGINT
    finally:
        app.cleanup()

def run_proxy(parser, opts, extra_args):
    from xpra.proxy import XpraProxy
    assert "gtk" not in sys.modules
    server_conn = connect_or_fail(pick_display(parser, opts, extra_args))
    app = XpraProxy(TwoFileConnection(sys.stdout, sys.stdin), server_conn)
    app.run()
    return  0

def run_stop(parser, opts, extra_args):
    assert "gtk" not in sys.modules
    from xpra.client_base import StopXpraClient

    def show_final_state(display):
        sockdir = DotXpra(opts.sockdir)
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


def run_list(parser, opts, extra_args):
    assert "gtk" not in sys.modules
    if extra_args:
        parser.error("too many arguments for mode")
    sockdir = DotXpra(opts.sockdir)
    results = sockdir.sockets()
    if not results:
        sys.stdout.write("No xpra sessions found\n")
        return  1
    sys.stdout.write("Found the following xpra sessions:\n")
    for state, display in results:
        sys.stdout.write("\t%s session at %s" % (state, display))
        if state is DotXpra.DEAD:
            try:
                os.unlink(sockdir.socket_path(display))
            except OSError:
                pass
            else:
                sys.stdout.write(" (cleaned up)")
        sys.stdout.write("\n")
    return 0

if __name__ == "__main__":
    code = main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
