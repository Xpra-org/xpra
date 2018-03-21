#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import optparse

from xpra.version_util import full_version_str
from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED, CAN_DAEMONIZE
from xpra.util import envbool, csv
from xpra.os_util import getuid, WIN32, OSX, POSIX
from xpra.scripts.config import OPTION_TYPES, InitException, InitInfo, InitExit, fixup_debug_option, fixup_options, \
    make_defaults_struct, parse_bool, print_number, validate_config, has_sound_support, name_to_field


def enabled_str(v, true_str="yes", false_str="no"):
    if v:
        return true_str
    return false_str

def enabled_or_auto(v):
    return bool_or(v, None, true_str="yes", false_str="no", other_str="auto")

def bool_or(v, other_value, true_str, false_str, other_str):
    vs = str(v).lower()
    if vs==other_value:
        return other_str
    bv = parse_bool("", v)
    return enabled_str(bv, true_str, false_str)

def sound_option(v):
    #ensures we return only: "on", "off" or "disabled" given any value
    if v=="no":
        v = "disabled"
    return bool_or(v, "disabled", "on", "off", "disabled")


def info(msg):
    #use this function to print warnings
    #we must write to stderr to prevent
    #the output from interfering when running as proxy over ssh
    #(which uses stdin / stdout as communication channel)
    try:
        sys.stderr.write(msg+"\n")
        sys.stderr.flush()
    except:
        if POSIX:
            import syslog
            syslog.syslog(syslog.LOG_INFO, msg)

def warn(msg):
    #use this function to print warnings
    #we must write to stderr to prevent
    #the output from interfering when running as proxy over ssh
    #(which uses stdin / stdout as communication channel)
    try:
        sys.stderr.write(msg+"\n")
        sys.stderr.flush()
    except:
        if POSIX:
            import syslog
            syslog.syslog(syslog.LOG_WARNING, msg)

def error(msg):
    #use this function to print warnings
    #we must write to stderr to prevent
    #the output from interfering when running as proxy over ssh
    #(which uses stdin / stdout as communication channel)
    try:
        sys.stderr.write(msg+"\n")
        sys.stderr.flush()
    except:
        if POSIX:
            import syslog
            syslog.syslog(syslog.LOG_ERR, msg)


supports_proxy  = True
supports_shadow = SHADOW_SUPPORTED
supports_server = LOCAL_SERVERS_SUPPORTED
if supports_server:
    try:
        from xpra.x11.bindings.wait_for_x_server import wait_for_x_server    #@UnresolvedImport @UnusedImport
    except:
        supports_server = False
try:
    from xpra.net import mdns
    supports_mdns = bool(mdns)
except:
    supports_mdns = False


#this parse doesn't exit when it encounters an error,
#allowing us to deal with it better and show a UI message if needed.
class ModifiedOptionParser(optparse.OptionParser):
    def error(self, msg):
        raise InitException(msg)
    def exit(self, status=0, msg=None):
        raise InitExit(status, msg)


def fixup_defaults(defaults):
    for k in ("debug", "encoding", "sound-source", "microphone-codec", "speaker-codec"):
        fn = k.replace("-", "_")
        v = getattr(defaults, fn)
        if "help" in v:
            if not envbool("XPRA_SKIP_UI", False):
                #skip-ui: we're running in subprocess, don't bother spamming stderr
                warn(("Warning: invalid 'help' option found in '%s' configuration\n" % k) +
                             " this should only be used as a command line argument\n")
            if k in ("encoding", "debug", "sound-source"):
                setattr(defaults, fn, "")
            else:
                v.remove("help")

def do_replace_option(cmdline, oldoption, newoption):
    for i, x in enumerate(cmdline):
        if x==oldoption:
            cmdline[i] = newoption
        elif newoption.find("=")<0 and x.startswith("%s=" % oldoption):
            cmdline[i] = "%s=%s" % (newoption, x.split("=", 1)[1])

def do_legacy_bool_parse(cmdline, optionname, newoptionname=None):
    #find --no-XYZ or --XYZ
    #and replace it with --XYZ=yes|no
    no = "--no-%s" % optionname
    yes = "--%s" % optionname
    if newoptionname is None:
        newoptionname = optionname
    do_replace_option(cmdline, no, "--%s=no" % optionname)
    do_replace_option(cmdline, yes, "--%s=yes" % optionname)

def ignore_options(args, options):
    for x in options:
        o = "--%s" % x      #ie: --use-display
        while o in args:
            args.remove(o)
        o = "--%s=" % x     #ie: --bind-tcp=....
        remove = []
        #find all command line arguments starting with this option:
        for v in args:
            if v.startswith(o):
                remove.append(v)
        #and remove them all:
        for r in remove:
            while r in args:
                args.remove(r)


def parse_env(env):
    d = {}
    for ev in env:
        try:
            if ev.startswith("#"):
                continue
            v = ev.split("=", 1)
            if len(v)!=2:
                warn("Warning: invalid environment option '%s'", ev)
                continue
            d[v[0]] = os.path.expandvars(v[1])
        except Exception as e:
            warn("Warning: cannot parse environment option '%s':", ev)
            warn(" %s", e)
    return d


def parse_URL(url):
    from urlparse import urlparse, parse_qs
    up = urlparse(url)
    address = up.netloc
    qpos = url.find("?")
    options = {}
    if qpos>0:
        params_str = url[qpos+1:]
        params = parse_qs(params_str, keep_blank_values=True)
        f_params = {}
        #print("params=%s" % str(params))
        for k,v in params.items():
            t = OPTION_TYPES.get(k)
            if t is not None and t!=list:
                v = v[0]
            f_params[k] = v
        options = validate_config(f_params)
    al = address.lower()
    if not al.startswith(":") and not al.startswith("tcp") and not al.startswith("ssh"):
        #assume tcp if not specified
        address = "tcp:%s" % address
    return address, options


def parse_cmdline(cmdline):
    defaults = make_defaults_struct()
    return do_parse_cmdline(cmdline, defaults)

def do_parse_cmdline(cmdline, defaults):
    #################################################################
    ## NOTE NOTE NOTE
    ##
    ## If you modify anything here, then remember to update the man page
    ## (xpra.1) as well!
    ##
    ## NOTE NOTE NOTE
    #################################################################
    command_options = [
                        "\t%prog attach [DISPLAY]\n",
                        "\t%prog detach [DISPLAY]\n",
                        "\t%prog screenshot filename [DISPLAY]\n",
                        "\t%prog info [DISPLAY]\n",
                        "\t%prog control DISPLAY command [arg1] [arg2]..\n",
                        "\t%prog print DISPLAY filename\n",
                        "\t%prog version [DISPLAY]\n"
                        "\t%prog showconfig\n"
                        "\t%prog list\n"
                        "\t%prog sessions\n"
                        "\t%prog stop [DISPLAY]\n"
                        "\t%prog exit [DISPLAY]\n"
                      ]
    if supports_mdns:
        command_options.append("\t%prog list-mdns\n")
        command_options.append("\t%prog mdns-gui\n")
    server_modes = []
    if supports_server:
        server_modes.append("start")
        server_modes.append("start-desktop")
        server_modes.append("upgrade")
        command_options = ["\t%prog start [DISPLAY]\n",
                           "\t%prog start-desktop [DISPLAY]\n",
                           "\t%prog upgrade [DISPLAY]\n",
                           ] + command_options
    if supports_shadow:
        server_modes.append("shadow")
        command_options.append("\t%prog shadow [DISPLAY]\n")
    if not supports_server:
        command_options.append("(This xpra installation does not support starting local servers.)")

    version = "xpra v%s" % full_version_str()
    parser = ModifiedOptionParser(version=version, usage="\n" + "".join(command_options))
    hidden_options = {
                      "display"         : defaults.display,
                      "wm-name"         : defaults.wm_name,
                      "download-path"   : defaults.download_path,
                      }
    def replace_option(oldoption, newoption):
        do_replace_option(cmdline, oldoption, newoption)
    def legacy_bool_parse(optionname, newoptionname=None):
        do_legacy_bool_parse(cmdline, optionname, newoptionname)
    def ignore(defaults):
        ignore_options(cmdline, defaults.keys())
        for k,v in defaults.items():
            hidden_options[k.replace("-", "_")] = v
    group = optparse.OptionGroup(parser, "Server Options",
                "These options are only relevant on the server when using the %s mode." %
                " or ".join(["'%s'" % x for x in server_modes]))
    parser.add_option_group(group)
    #we support remote start, so we need those even if we don't have server support:
    group.add_option("--start", action="append",
                      dest="start", metavar="CMD", default=list(defaults.start or []),
                      help="program to spawn in new server (may be repeated). Default: %default.")
    group.add_option("--start-child", action="append",
                      dest="start_child", metavar="CMD", default=list(defaults.start_child or []),
                      help="program to spawn in new server, taken into account by the exit-with-children option (may be repeated to run multiple commands). Default: %default.")
    group.add_option("--start-after-connect", action="append",
                      dest="start_after_connect", default=defaults.start_after_connect,
                      help="program to spawn in new server after the first client has connected (may be repeated). Default: %default.")
    group.add_option("--start-child-after-connect", action="append",
                      dest="start_child_after_connect", default=defaults.start_child_after_connect,
                      help="program to spawn in new server after the first client has connected, taken into account by the exit-with-children option (may be repeated to run multiple commands). Default: %default.")
    group.add_option("--start-on-connect", action="append",
                      dest="start_on_connect", default=defaults.start_on_connect,
                      help="program to spawn in new server every time a client connects (may be repeated). Default: %default.")
    group.add_option("--start-child-on-connect", action="append",
                      dest="start_child_on_connect", default=defaults.start_child_on_connect,
                      help="program to spawn in new server every time a client connects, taken into account by the exit-with-children option (may be repeated). Default: %default.")
    group.add_option("--exec-wrapper", action="store",
                      dest="exec_wrapper", metavar="CMD", default=defaults.exec_wrapper,
                      help="Wrapper for executing commands. Default: %default.")
    legacy_bool_parse("terminate-children")
    group.add_option("--terminate-children", action="store", metavar="yes|no",
                      dest="terminate_children", default=defaults.terminate_children,
                      help="Terminate all the child commands on server stop. Default: %default")
    legacy_bool_parse("exit-with-children")
    group.add_option("--exit-with-children", action="store", metavar="yes|no",
                      dest="exit_with_children", default=defaults.exit_with_children,
                      help="Terminate the server when the last --start-child command(s) exit")
    legacy_bool_parse("start-new-commands")
    group.add_option("--start-new-commands", action="store", metavar="yes|no",
                      dest="start_new_commands", default=defaults.start_new_commands,
                      help="Allows clients to execute new commands on the server. Default: %s." % enabled_str(defaults.start_new_commands))
    legacy_bool_parse("start-via-proxy")
    group.add_option("--start-via-proxy", action="store", metavar="yes|no|auto",
                      dest="start_via_proxy", default=defaults.start_via_proxy,
                      help="Start servers via the system proxy server. Default: %default.")
    legacy_bool_parse("proxy-start-sessions")
    group.add_option("--proxy-start-sessions", action="store", metavar="yes|no",
                      dest="proxy_start_sessions", default=defaults.proxy_start_sessions,
                      help="Allows proxy servers to start new sessions on demand. Default: %s." % enabled_str(defaults.proxy_start_sessions))
    group.add_option("--dbus-launch", action="store",
                      dest="dbus_launch", metavar="CMD", default=defaults.dbus_launch,
                      help="Start the session within a dbus-launch context, leave empty to turn off. Default: %default.")
    group.add_option("--start-env", action="append",
                      dest="start_env", default=list(defaults.start_env or []),
                      help="Define environment variables used with 'start-child' and 'start', can be specified multiple times. Default: %s." % csv(("'%s'" % x) for x in (defaults.start_env or []) if not x.startswith("#")))
    if POSIX:
        legacy_bool_parse("systemd-run")
        group.add_option("--systemd-run", action="store", metavar="yes|no|auto",
                          dest="systemd_run", default=defaults.systemd_run,
                          help="Wrap server start commands with systemd-run. Default: %default.")
        group.add_option("--systemd-run-args", action="store", metavar="ARGS",
                          dest="systemd_run_args", default=defaults.systemd_run_args,
                          help="Command line arguments passed to systemd-run. Default: '%default'.")
    else:
        ignore({"systemd_run"       : defaults.systemd_run,
                "systemd_run_args"  : defaults.systemd_run_args})

    legacy_bool_parse("html")
    if supports_server or supports_shadow:
        group.add_option("--tcp-proxy", action="store",
                          dest="tcp_proxy", default=defaults.tcp_proxy,
                          metavar="HOST:PORT",
                          help="The address to which non-xpra packets will be forwarded. Default: '%default'.")
        group.add_option("--html", action="store",
                          dest="html", default=defaults.html,
                          metavar="on|off|[HOST:]PORT",
                          help="Enable the web server and the html5 client. Default: '%default'.")
    else:
        ignore({"tcp_proxy" : "",
                "html"      : ""})
    legacy_bool_parse("daemon")
    legacy_bool_parse("attach")
    if POSIX and getuid()==0:
        group.add_option("--uid", action="store",
                          dest="uid", default=defaults.uid,
                          help="The user id to change to when the server is started by root. Default: %s." % defaults.uid)
        group.add_option("--gid", action="store",
                          dest="gid", default=defaults.gid,
                          help="The group id to change to when the server is started by root. Default: %s." % defaults.gid)
    else:
        ignore({
                "uid"   : defaults.uid,
                "gid"   : defaults.gid,
                })
    if (supports_server or supports_shadow) and CAN_DAEMONIZE:
        group.add_option("--daemon", action="store", metavar="yes|no",
                          dest="daemon", default=defaults.daemon,
                          help="Daemonize when running as a server (default: %s)" % enabled_str(defaults.daemon))
        group.add_option("--chdir", action="store", metavar="DIR",
                          dest="chdir", default=defaults.chdir,
                          help="Change to this directory (default: %s)" % enabled_str(defaults.chdir))
        group.add_option("--pidfile", action="store",
                      dest="pidfile", default=defaults.pidfile,
                      help="Write the process id to this file (default: '%default')")
        group.add_option("--log-dir", action="store",
                      dest="log_dir", default=defaults.log_dir,
                      help="The directory where log files are placed"
                      )
        group.add_option("--log-file", action="store",
                      dest="log_file", default=defaults.log_file,
                      help="When daemonizing, this is where the log messages will go. Default: '%default'."
                      + " If a relative filename is specified the it is relative to --log-dir,"
                      + " the value of '$DISPLAY' will be substituted with the actual display used"
                      )
    else:
        ignore({
                "daemon"    : defaults.daemon,
                "pidfile"   : defaults.pidfile,
                "log_file"  : defaults.log_file,
                "log_dir"   : defaults.log_dir,
                "chdir"     : defaults.chdir,
                })
    group.add_option("--attach", action="store", metavar="yes|no|auto",
                      dest="attach", default=defaults.attach,
                      help="Attach a client as soon as the server has started (default: %s)" % enabled_or_auto(defaults.attach))

    legacy_bool_parse("printing")
    legacy_bool_parse("file-transfer")
    legacy_bool_parse("open-files")
    legacy_bool_parse("open-url")
    group.add_option("--file-transfer", action="store", metavar="yes|no|ask",
                      dest="file_transfer", default=defaults.file_transfer,
                      help="Support file transfers. Default: %s." % enabled_str(defaults.file_transfer))
    group.add_option("--open-files", action="store", metavar="yes|no|ask",
                      dest="open_files", default=defaults.open_files,
                      help="Automatically open uploaded files (potentially dangerous). Default: '%default'.")
    group.add_option("--open-url", action="store", metavar="yes|no|ask",
                      dest="open_url", default=defaults.open_url,
                      help="Automatically open URL (potentially dangerous). Default: '%default'.")
    group.add_option("--printing", action="store", metavar="yes|no|ask",
                      dest="printing", default=defaults.printing,
                      help="Support printing. Default: %s." % enabled_str(defaults.printing))
    if supports_server:
        group.add_option("--lpadmin", action="store",
                          dest="lpadmin", default=defaults.lpadmin,
                          metavar="COMMAND",
                          help="Specify the lpadmin command to use. Default: '%default'.")
        group.add_option("--lpinfo", action="store",
                          dest="lpinfo", default=defaults.lpinfo,
                          metavar="COMMAND",
                          help="Specify the lpinfo command to use. Default: '%default'.")
    else:
        ignore({
                "lpadmin"               : defaults.lpadmin,
                "lpinfo"                : defaults.lpinfo,
                })
    #options without command line equivallents:
    hidden_options["pdf-printer"] = defaults.pdf_printer
    hidden_options["postscript-printer"] = defaults.postscript_printer
    hidden_options["add-printer-options"] = defaults.add_printer_options
    hidden_options["file-size-limit"] = defaults.file_size_limit
    hidden_options["open-command"] = defaults.open_command

    legacy_bool_parse("exit-with-client")
    if (supports_server or supports_shadow):
        group.add_option("--exit-with-client", action="store", metavar="yes|no",
                          dest="exit_with_client", default=defaults.exit_with_client,
                          help="Terminate the server when the last client disconnects. Default: %s" % enabled_str(defaults.exit_with_client))
    else:
        ignore({"exit_with_client" : defaults.exit_with_client})
    group.add_option("--idle-timeout", action="store",
                      dest="idle_timeout", type="int", default=defaults.idle_timeout,
                      help="Disconnects the client when idle (0 to disable). Default: %s seconds" % defaults.idle_timeout)
    group.add_option("--server-idle-timeout", action="store",
                      dest="server_idle_timeout", type="int", default=defaults.server_idle_timeout,
                      help="Exits the server when idle (0 to disable). Default: %s seconds" % defaults.server_idle_timeout)
    legacy_bool_parse("fake-xinerama")
    legacy_bool_parse("use-display")
    if supports_server:
        group.add_option("--use-display", action="store", metavar="yes|no",
                          dest="use_display", default=defaults.use_display,
                          help="Use an existing display rather than starting one with the xvfb command. Default: %s" % enabled_str(defaults.use_display))
        group.add_option("--xvfb", action="store",
                          dest="xvfb",
                          default=defaults.xvfb,
                          metavar="CMD",
                          help="How to run the headless X server. Default: '%default'.")
        group.add_option("--displayfd", action="store", metavar="FD",
                          dest="displayfd", default=defaults.displayfd,
                          help="The xpra server will write the display number back on this file descriptor as a newline-terminated string.")
        group.add_option("--fake-xinerama", action="store", metavar="yes|no",
                          dest="fake_xinerama",
                          default=defaults.fake_xinerama,
                          help="Setup fake xinerama support for the session. Default: %s." % enabled_str(defaults.fake_xinerama))
    else:
        ignore({
            "use-display"   : defaults.use_display,
            "xvfb"          : defaults.xvfb,
            "displayfd"     : defaults.displayfd,
            "fake-xinerama" : defaults.fake_xinerama,
            })
    group.add_option("--resize-display", action="store",
                      dest="resize_display", default=defaults.resize_display, metavar="yes|no",
                      help="Whether the server display should be resized to match the client resolution. Default: %s." % enabled_str(defaults.resize_display))
    defaults_bind = defaults.bind
    if supports_server or supports_shadow:
        group.add_option("--bind", action="append",
                          dest="bind", default=[],
                          metavar="SOCKET",
                          help="Listen for connections over %s. You may specify this option multiple times to listen on different locations. Default: %s" % (["unix domain sockets","named pipes"][WIN32], csv(defaults_bind)))
        group.add_option("--bind-tcp", action="append",
                          dest="bind_tcp", default=list(defaults.bind_tcp or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over TCP (use --tcp-auth to secure it)."
                            + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-udp", action="append",
                          dest="bind_udp", default=list(defaults.bind_udp or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over UDP (use --udp-auth to secure it)."
                            + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-ws", action="append",
                          dest="bind_ws", default=list(defaults.bind_ws or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over Websocket (use --ws-auth to secure it)."
                            + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-wss", action="append",
                          dest="bind_wss", default=list(defaults.bind_wss or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over HTTPS / wss (secure Websocket). Use --wss-auth to secure it."
                            + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-ssl", action="append",
                          dest="bind_ssl", default=list(defaults.bind_ssl or []),
                          metavar="[HOST]:PORT",
                          help="Listen for connections over SSL. Use --ssl-auth to secure it."
                            + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-rfb", action="append",
                          dest="bind_rfb", default=list(defaults.bind_rfb or []),
                          metavar="[HOST]:PORT",
                          help="Listen for RFB connections. Use --rfb-auth to secure it."
                            + " You may specify this option multiple times with different host and port combinations")
    else:
        ignore({
            "bind"      : defaults.bind,
            "bind-tcp"  : defaults.bind_tcp,
            "bind-udp"  : defaults.bind_udp,
            "bind-ws"   : defaults.bind_ws,
            "bind-wss"  : defaults.bind_wss,
            "bind-ssl"  : defaults.bind_ssl,
            "bind-rfb"  : defaults.bind_rfb,
            })
    try:
        from xpra.net import vsock
    except:
        vsock = None
    if vsock:
        group.add_option("--bind-vsock", action="append",
                          dest="bind_vsock", default=list(defaults.bind_vsock or []),
                          metavar="[CID]:[PORT]",
                          help="Listen for connections over VSOCK."
                            + " You may specify this option multiple times with different CID and port combinations")
    else:
        ignore({"bind-vsock" : []})
    legacy_bool_parse("mdns")
    if (supports_server or supports_shadow):
        group.add_option("--mdns", action="store", metavar="yes|no",
                          dest="mdns", default=defaults.mdns,
                          help="Publish the session information via mDNS. Default: %s." % enabled_str(defaults.mdns))
    else:
        ignore({"mdns" : defaults.mdns})
    legacy_bool_parse("pulseaudio")
    legacy_bool_parse("dbus-proxy")
    legacy_bool_parse("dbus-control")
    if supports_server:
        group.add_option("--pulseaudio", action="store", metavar="yes|no|auto",
                      dest="pulseaudio", default=defaults.pulseaudio,
                      help="Start a pulseaudio server for the session. Default: %s." % enabled_or_auto(defaults.pulseaudio))
        group.add_option("--pulseaudio-command", action="store",
                      dest="pulseaudio_command", default=defaults.pulseaudio_command,
                      help="The command used to start the pulseaudio server. Default: '%default'.")
        group.add_option("--pulseaudio-configure-commands", action="append",
                      dest="pulseaudio_configure_commands", default=defaults.pulseaudio_configure_commands,
                      help="The commands used to configure the pulseaudio server. Default: '%default'.")
        group.add_option("--dbus-proxy", action="store", metavar="yes|no",
                      dest="dbus_proxy", default=defaults.dbus_proxy,
                      help="Forward dbus calls from the client. Default: %s." % enabled_str(defaults.dbus_proxy))
        group.add_option("--dbus-control", action="store", metavar="yes|no",
                      dest="dbus_control", default=defaults.dbus_control,
                      help="Allows the server to be controlled via its dbus interface. Default: %s." % enabled_str(defaults.dbus_control))
    else:
        ignore({"pulseaudio"            : defaults.pulseaudio,
                "pulseaudio-command"    : defaults.pulseaudio_command,
                "dbus-proxy"            : defaults.dbus_proxy,
                "dbus-control"          : defaults.dbus_control,
                "pulseaudio-configure-commands" : defaults.pulseaudio_configure_commands,
                })

    group = optparse.OptionGroup(parser, "Server Controlled Features",
                "These options be specified on the client or on the server, "
                "but the server's settings will have precedence over the client's.")
    parser.add_option_group(group)
    replace_option("--bwlimit", "--bandwidth-limit")
    group.add_option("--bandwidth-limit", action="store",
                      dest="bandwidth_limit", default=defaults.bandwidth_limit,
                      help="Limit the bandwidth used. The value is specified in bits per second, use the value '0' to disable restrictions. Default: '%default'.")
    replace_option("--readwrite", "--readonly=no")
    replace_option("--readonly", "--readonly=yes")
    group.add_option("--readonly", action="store", metavar="yes|no",
                      dest="readonly", default=defaults.readonly,
                      help="Disable keyboard input and mouse events from the clients. Default: %s." % enabled_str(defaults.readonly))
    legacy_bool_parse("clipboard")
    group.add_option("--clipboard", action="store", metavar="yes|no|clipboard-type",
                      dest="clipboard", default=defaults.clipboard,
                      help="Enable clipboard support. Default: %s." % defaults.clipboard)
    group.add_option("--clipboard-direction", action="store", metavar="to-server|to-client|both",
                      dest="clipboard_direction", default=defaults.clipboard_direction,
                      help="Direction of clipboard synchronization. Default: %s." % defaults.clipboard_direction)
    legacy_bool_parse("notifications")
    group.add_option("--notifications", action="store", metavar="yes|no",
                      dest="notifications", default=defaults.notifications,
                      help="Forwarding of system notifications. Default: %s." % enabled_str(defaults.notifications))
    legacy_bool_parse("system-tray")
    group.add_option("--system-tray", action="store", metavar="yes|no",
                      dest="system_tray", default=defaults.system_tray,
                      help="Forward of system tray icons. Default: %s." % enabled_str(defaults.system_tray))
    legacy_bool_parse("cursors")
    group.add_option("--cursors", action="store", metavar="yes|no",
                      dest="cursors", default=defaults.cursors,
                      help="Forward custom application mouse cursors. Default: %s." % enabled_str(defaults.cursors))
    legacy_bool_parse("bell")
    group.add_option("--bell", action="store",
                      dest="bell", default=defaults.bell, metavar="yes|no",
                      help="Forward the system bell. Default: %s." % enabled_str(defaults.bell))
    legacy_bool_parse("webcam")
    group.add_option("--webcam", action="store",
                      dest="webcam", default=defaults.webcam,
                      help="Webcam forwarding, can be used to specify a device. Default: %s." % defaults.webcam)
    legacy_bool_parse("mousewheel")
    group.add_option("--mousewheel", action="store",
                      dest="mousewheel", default=defaults.mousewheel,
                      help="Mouse wheel forwarding, can be used to disable the device or invert some axes. Default: %s." % defaults.webcam)
    from xpra.platform.features import INPUT_DEVICES
    if len(INPUT_DEVICES)>1:
        group.add_option("--input-devices", action="store", metavar="APINAME",
                          dest="input_devices", default=defaults.input_devices,
                          help="Which API to use for input devices. Default: %s." % defaults.input_devices)
    else:
        ignore({"input-devices" : INPUT_DEVICES[0]})
    legacy_bool_parse("global-menus")
    group.add_option("--global-menus", action="store",
                      dest="global_menus", default=defaults.global_menus, metavar="yes|no",
                      help="Forward application global menus. Default: %s." % enabled_str(defaults.global_menus))
    legacy_bool_parse("xsettings")
    if POSIX:
        group.add_option("--xsettings", action="store", metavar="yes|no",
                          dest="xsettings", default=defaults.xsettings,
                          help="xsettings synchronization. Default: %s." % enabled_str(defaults.xsettings))
    else:
        ignore({"xsettings" : defaults.xsettings})
    legacy_bool_parse("mmap")
    group.add_option("--mmap", action="store", metavar="yes|no|mmap-filename",
                      dest="mmap", default=defaults.mmap,
                      help="Use memory mapped transfers for local connections. Default: %s." % defaults.mmap)
    replace_option("--enable-sharing", "--sharing=yes")
    legacy_bool_parse("sharing")
    group.add_option("--sharing", action="store", metavar="yes|no",
                      dest="sharing", default=defaults.sharing,
                      help="Allow more than one client to connect to the same session. Default: %s." % enabled_or_auto(defaults.sharing))
    legacy_bool_parse("lock")
    group.add_option("--lock", action="store", metavar="yes|no",
                      dest="lock", default=defaults.lock,
                      help="Prevent sessions from being taken over by new clients. Default: %s." % enabled_or_auto(defaults.lock))
    legacy_bool_parse("remote-logging")
    group.add_option("--remote-logging", action="store", metavar="yes|no|both",
                      dest="remote_logging", default=defaults.remote_logging,
                      help="Forward all the client's log output to the server. Default: %s." % enabled_str(defaults.remote_logging))
    legacy_bool_parse("speaker")
    legacy_bool_parse("microphone")
    legacy_bool_parse("av-sync")
    if has_sound_support():
        group.add_option("--speaker", action="store", metavar="on|off|disabled",
                          dest="speaker", default=defaults.speaker,
                          help="Forward sound output to the client(s). Default: %s." % sound_option(defaults.speaker))
        CODEC_HELP = """Specify the codec(s) to use for forwarding the %s sound output.
    This parameter can be specified multiple times and the order in which the codecs
    are specified defines the preferred codec order.
    Use the special value 'help' to get a list of options.
    When unspecified, all the available codecs are allowed and the first one is used."""
        group.add_option("--speaker-codec", action="append",
                          dest="speaker_codec", default=list(defaults.speaker_codec or []),
                          help=CODEC_HELP % "speaker")
        group.add_option("--microphone", action="store", metavar="on|off|disabled",
                          dest="microphone", default=defaults.microphone,
                          help="Forward sound input to the server. Default: %s." % sound_option(defaults.microphone))
        group.add_option("--microphone-codec", action="append",
                          dest="microphone_codec", default=list(defaults.microphone_codec or []),
                          help=CODEC_HELP % "microphone")
        group.add_option("--sound-source", action="store",
                          dest="sound_source", default=defaults.sound_source,
                          help="Specifies which sound system to use to capture the sound stream (use 'help' for options)")
        group.add_option("--av-sync", action="store",
                          dest="av_sync", default=defaults.av_sync,
                          help="Try to synchronize sound and video. Default: %s." % enabled_str(defaults.av_sync))
    else:
        ignore({"av-sync"           : defaults.av_sync,
                "speaker"           : defaults.speaker,
                "speaker-codec"     : defaults.speaker_codec,
                "microphone"        : defaults.microphone,
                "microphone-codec"  : defaults.microphone_codec,
                "sound-source"      : defaults.sound_source,
                })

    group = optparse.OptionGroup(parser, "Encoding and Compression Options",
                "These options are used by the client to specify the desired picture and network data compression."
                "They may also be specified on the server as default settings.")
    parser.add_option_group(group)
    group.add_option("--encodings", action="store",
                      dest="encodings", default=defaults.encodings,
                      help="Specify which encodings are allowed. Default: %s." % csv(defaults.encodings))
    group.add_option("--encoding", action="store",
                      metavar="ENCODING", default=defaults.encoding,
                      dest="encoding", type="str",
                      help="Which image compression algorithm to use, specify 'help' to get a list of options."
                            " Default: %default."
                      )
    group.add_option("--video-encoders", action="store",
                      dest="video_encoders", default=defaults.video_encoders,
                      help="Specify which video encoders to enable, to get a list of all the options specify 'help'")
    hidden_options["proxy-video-encoders"] =  defaults.proxy_video_encoders
    group.add_option("--csc-modules", action="store",
                      dest="csc_modules", default=defaults.csc_modules,
                      help="Specify which colourspace conversion modules to enable, to get a list of all the options specify 'help'. Default: %default.")
    group.add_option("--video-decoders", action="store",
                      dest="video_decoders", default=defaults.video_decoders,
                      help="Specify which video decoders to enable, to get a list of all the options specify 'help'")
    group.add_option("--video-scaling", action="store",
                      metavar="SCALING",
                      dest="video_scaling", type="str", default=defaults.video_scaling,
                      help="How much automatic video downscaling should be used, from 1 (rarely) to 100 (aggressively), 0 to disable. Default: %default.")
    group.add_option("--min-quality", action="store",
                      metavar="MIN-LEVEL",
                      dest="min_quality", type="int", default=defaults.min_quality,
                      help="Sets the minimum encoding quality allowed in automatic quality setting, from 1 to 100, 0 to leave unset. Default: %default.")
    group.add_option("--quality", action="store",
                      metavar="LEVEL",
                      dest="quality", type="int", default=defaults.quality,
                      help="Use a fixed image compression quality - only relevant to lossy encodings, from 1 to 100, 0 to use automatic setting. Default: %default.")
    group.add_option("--min-speed", action="store",
                      metavar="SPEED",
                      dest="min_speed", type="int", default=defaults.min_speed,
                      help="Sets the minimum encoding speed allowed in automatic speed setting, from 1 to 100, 0 to leave unset. Default: %default.")
    group.add_option("--speed", action="store",
                      metavar="SPEED",
                      dest="speed", type="int", default=defaults.speed,
                      help="Use image compression with the given encoding speed, from 1 to 100, 0 to use automatic setting. Default: %default.")
    group.add_option("--auto-refresh-delay", action="store",
                      dest="auto_refresh_delay", type="float", default=defaults.auto_refresh_delay,
                      metavar="DELAY",
                      help="Idle delay in seconds before doing an automatic lossless refresh."
                      + " 0.0 to disable."
                      + " Default: %default.")
    group.add_option("--compressors", action="store",
                      dest="compressors", default=csv(defaults.compressors),
                      help="The packet compressors to enable. Default: %default.")
    group.add_option("--packet-encoders", action="store",
                      dest="packet_encoders", default=csv(defaults.packet_encoders),
                      help="The packet encoders to enable. Default: %default.")
    group.add_option("-z", "--compress", action="store",
                      dest="compression_level", type="int", default=defaults.compression_level,
                      metavar="LEVEL",
                      help="How hard to work on compressing data."
                      + " You generally do not need to use this option,"
                      + " the default value should be adequate,"
                      + " picture data is compressed separately (see --encoding)."
                      + " 0 to disable compression,"
                      + " 9 for maximal (slowest) compression. Default: %default.")

    group = optparse.OptionGroup(parser, "Client Features Options",
                "These options control client features that affect the appearance or the keyboard.")
    parser.add_option_group(group)
    legacy_bool_parse("opengl")
    group.add_option("--opengl", action="store", metavar="(yes|no|auto)[:backends]",
                      dest="opengl", default=defaults.opengl,
                      help="Use OpenGL accelerated rendering. Default: %s." % defaults.opengl)
    legacy_bool_parse("windows")
    group.add_option("--windows", action="store", metavar="yes|no",
                      dest="windows", default=defaults.windows,
                      help="Forward windows. Default: %s." % enabled_str(defaults.windows))
    group.add_option("--session-name", action="store",
                      dest="session_name", default=defaults.session_name,
                      help="The name of this session, which may be used in notifications, menus, etc. Default: 'Xpra'.")
    group.add_option("--max-size", action="store",
                      dest="max_size", default=defaults.max_size,
                      metavar="MAX_SIZE",
                      help="The maximum size for all windows, ie: 800x600. Default: '%default'.")
    group.add_option("--desktop-scaling", action="store",
                      dest="desktop_scaling", default=defaults.desktop_scaling,
                      metavar="SCALING",
                      help="How much to scale the client desktop by."
                            " This value can be specified in the form of absolute pixels: \"WIDTHxHEIGHT\""
                            " as a fraction: \"3/2\" or just as a decimal number: \"1.5\"."
                            " You can also specify each dimension individually: \"2x1.5\"."
                            " Default: '%default'.")
    legacy_bool_parse("desktop-fullscreen")
    group.add_option("--desktop-fullscreen", action="store",
                      dest="desktop_fullscreen", default=defaults.desktop_fullscreen,
                      help="Make the window fullscreen if it is from a desktop or shadow server, scaling it to fit the screen."
                            " Default: '%default'.")
    group.add_option("--border", action="store",
                      dest="border", default=defaults.border,
                      help="The border to draw inside xpra windows to distinguish them from local windows."
                        "Format: color[,size]. Default: '%default'")
    group.add_option("--title", action="store",
                      dest="title", default=defaults.title,
                      help="Text which is shown as window title, may use remote metadata variables. Default: '%default'.")
    group.add_option("--window-close", action="store",
                          dest="window_close", default=defaults.window_close,
                          help="The action to take when a window is closed by the client. Valid options are: 'forward', 'ignore', 'disconnect'. Default: '%default'.")
    group.add_option("--window-icon", action="store",
                          dest="window_icon", default=defaults.window_icon,
                          help="Path to the default image which will be used for all windows (the application may override this)")
    if OSX:
        group.add_option("--dock-icon", action="store",
                              dest="dock_icon", default=defaults.dock_icon,
                              help="Path to the icon shown in the dock")
        do_legacy_bool_parse(cmdline, "swap-keys")
        group.add_option("--swap-keys", action="store", metavar="yes|no",
                          dest="swap_keys", default=defaults.swap_keys,
                          help="Swap the 'Command' and 'Control' keys. Default: %s" % enabled_str(defaults.swap_keys))
        ignore({"tray"                : defaults.tray})
        ignore({"delay-tray"          : defaults.delay_tray})
    else:
        ignore({"swap-keys"           : defaults.swap_keys})
        ignore({"dock-icon"           : defaults.dock_icon})
        do_legacy_bool_parse(cmdline, "tray")
        if WIN32:
            extra_text = ", this will also disable notifications"
        else:
            extra_text = ""
        parser.add_option("--tray", action="store", metavar="yes|no",
                          dest="tray", default=defaults.tray,
                          help="Enable Xpra's own system tray menu%s. Default: %s" % (extra_text, enabled_str(defaults.tray)))
        do_legacy_bool_parse(cmdline, "delay-tray")
        parser.add_option("--delay-tray", action="store", metavar="yes|no",
                          dest="delay_tray", default=defaults.delay_tray,
                          help="Waits for the first events before showing the system tray%s. Default: %s" % (extra_text, enabled_str(defaults.delay_tray)))

    group.add_option("--tray-icon", action="store",
                          dest="tray_icon", default=defaults.tray_icon,
                          help="Path to the image which will be used as icon for the system-tray or dock")
    group.add_option("--shortcut-modifiers", action="store",
                      dest="shortcut_modifiers", type="str", default=defaults.shortcut_modifiers,
                      help="Default set of modifiers required by the key shortcuts. Default %default.")
    group.add_option("--key-shortcut", action="append",
                      dest="key_shortcut", type="str", default=list(defaults.key_shortcut or []),
                      help="Define key shortcuts that will trigger specific actions."
                      + "If no shortcuts are defined, it defaults to: \n%s" % ("\n ".join(defaults.key_shortcut or [])))
    legacy_bool_parse("keyboard-sync")
    group.add_option("--keyboard-sync", action="store", metavar="yes|no",
                      dest="keyboard_sync", default=defaults.keyboard_sync,
                      help="Synchronize keyboard state. Default: %s." % enabled_str(defaults.keyboard_sync))
    group.add_option("--keyboard-raw", action="store", metavar="yes|no",
                      dest="keyboard_raw", default=defaults.keyboard_raw,
                      help="Send raw keyboard keycodes. Default: %s." % enabled_str(defaults.keyboard_raw))
    group.add_option("--keyboard-layout", action="store", metavar="LAYOUT",
                      dest="keyboard_layout", default=defaults.keyboard_layout,
                      help="The keyboard layout to use. Default: %default.")
    group.add_option("--keyboard-layouts", action="store", metavar="LAYOUTS",
                      dest="keyboard_layouts", default=defaults.keyboard_layouts,
                      help="The keyboard layouts to enable. Default: %s." % csv(defaults.keyboard_layouts))
    group.add_option("--keyboard-variant", action="store", metavar="VARIANT",
                      dest="keyboard_variant", default=defaults.keyboard_variant,
                      help="The keyboard layout variant to use. Default: %default.")
    group.add_option("--keyboard-variants", action="store", metavar="VARIANTS",
                      dest="keyboard_variants", default=defaults.keyboard_variant,
                      help="The keyboard layout variants to enable. Default: %s." % csv(defaults.keyboard_variants))
    group.add_option("--keyboard-options", action="store", metavar="OPTIONS",
                      dest="keyboard_options", default=defaults.keyboard_options,
                      help="The keyboard layout options to use. Default: %default.")

    group = optparse.OptionGroup(parser, "SSL Options",
                "These options apply to both client and server. Please refer to the man page for details.")
    parser.add_option_group(group)
    group.add_option("--ssl", action="store",
                      dest="ssl", default=defaults.ssl,
                      help="Whether to enable SSL on TCP sockets and for what purpose (requires 'ssl-cert'). Default: '%s'."  % enabled_str(defaults.ssl))
    group.add_option("--ssl-key", action="store",
                      dest="ssl_key", default=defaults.ssl_key,
                      help="Key file to use. Default: '%default'.")
    group.add_option("--ssl-cert", action="store",
                      dest="ssl_cert", default=defaults.ssl_cert,
                      help="Certifcate file to use. Default: '%default'.")
    group.add_option("--ssl-protocol", action="store",
                      dest="ssl_protocol", default=defaults.ssl_protocol,
                      help="Specifies which version of the SSL protocol to use. Default: '%default'.")
    group.add_option("--ssl-ca-certs", action="store",
                      dest="ssl_ca_certs", default=defaults.ssl_ca_certs,
                      help="The ca_certs file contains a set of concatenated 'certification authority' certificates, or you can set this to a directory containing CAs files. Default: '%default'.")
    group.add_option("--ssl-ca-data", action="store",
                      dest="ssl_ca_data", default=defaults.ssl_ca_data,
                      help="PEM or DER encoded certificate data, optionally converted to hex. Default: '%default'.")
    group.add_option("--ssl-ciphers", action="store",
                      dest="ssl_ciphers", default=defaults.ssl_ciphers,
                      help="Sets the available ciphers, it should be a string in the OpenSSL cipher list format. Default: '%default'.")
    group.add_option("--ssl-client-verify-mode", action="store",
                      dest="ssl_client_verify_mode", default=defaults.ssl_client_verify_mode,
                      help="Whether to try to verify the client's certificates and how to behave if verification fails. Default: '%default'.")
    group.add_option("--ssl-server-verify-mode", action="store",
                      dest="ssl_server_verify_mode", default=defaults.ssl_server_verify_mode,
                      help="Whether to try to verify the server's certificates and how to behave if verification fails. Default: '%default'.")
    group.add_option("--ssl-verify-flags", action="store",
                      dest="ssl_verify_flags", default=defaults.ssl_verify_flags,
                      help="The flags for certificate verification operations. Default: '%default'.")
    group.add_option("--ssl-check-hostname", action="store", metavar="yes|no",
                      dest="ssl_check_hostname", default=defaults.ssl_check_hostname,
                      help="Whether to match the peer cert's hostname or accept any host, dangerous. Default: '%s'." % enabled_str(defaults.ssl_check_hostname))
    group.add_option("--ssl-server-hostname", action="store", metavar="hostname",
                      dest="ssl_server_hostname", default=defaults.ssl_server_hostname,
                      help="The server hostname to match. Default: '%default'.")
    group.add_option("--ssl-options", action="store", metavar="options",
                      dest="ssl_options", default=defaults.ssl_options,
                      help="Set of SSL options enabled on this context. Default: '%default'.")

    group = optparse.OptionGroup(parser, "Advanced Options",
                "These options apply to both client and server. Please refer to the man page for details.")
    parser.add_option_group(group)
    group.add_option("--env", action="append",
                      dest="env", default=list(defaults.env or []),
                      help="Define environment variables which will apply to this process and all subprocesses, can be specified multiple times. Default: %s." % csv(("'%s'" % x) for x in (defaults.env or []) if not x.startswith("#")))
    group.add_option("--challenge-handlers", action="store",
                      dest="challenge_handlers", default=defaults.challenge_handlers,
                      help="Which handlers to use for processing server authentication challenges. Default: %default.")
    group.add_option("--password-file", action="append",
                      dest="password_file", default=defaults.password_file,
                      help="The file containing the password required to connect (useful to secure TCP mode). Default: %s." % csv(defaults.password_file))
    group.add_option("--forward-xdg-open", action="store",
                      dest="forward_xdg_open", default=defaults.forward_xdg_open,
                      help="Intercept calls to xdg-open and forward them to the client. Default: '%default'.")
    group.add_option("--input-method", action="store",
                      dest="input_method", default=defaults.input_method,
                      help="Which X11 input method to configure for client applications started with start or start-child (default: '%default', options: none, keep, xim, IBus, SCIM, uim)")
    group.add_option("--dpi", action="store",
                      dest="dpi", default=defaults.dpi,
                      help="The 'dots per inch' value that client applications should try to honour, from 10 to 1000 or 0 for automatic setting. Default: %s." % print_number(defaults.dpi))
    group.add_option("--pixel-depth", action="store",
                      dest="pixel_depth", default=defaults.pixel_depth,
                      help="The bits per pixel of the virtual framebuffer when starting a server (8, 16, 24 or 30), or for rendering when starting a client. Default: %s." % (defaults.pixel_depth or "0 (auto)"))
    group.add_option("--sync-xvfb", action="store",
                      dest="sync_xvfb", default=defaults.sync_xvfb,
                      help="How often to synchronize the virtual framebuffer used for X11 seamless servers (0 to disable). Default: %s." % defaults.sync_xvfb)
    group.add_option("--socket-dirs", action="append",
                      dest="socket_dirs", default=[],
                      help="Directories to look for the socket files in. Default: %s." % os.path.pathsep.join("'%s'" % x for x in defaults.socket_dirs))
    default_socket_dir_str = defaults.socket_dir or "$XPRA_SOCKET_DIR or the first valid directory in socket-dirs"
    group.add_option("--socket-dir", action="store",
                      dest="socket_dir", default=defaults.socket_dir,
                      help="Directory to place/look for the socket files in. Default: '%s'." % default_socket_dir_str)
    group.add_option("--system-proxy-socket", action="store",
                      dest="system_proxy_socket", default=defaults.system_proxy_socket,
                      help="The socket path to use to contact the system-wide proxy server. Default: '%default'.")
    group.add_option("--rfb-upgrade", action="store",
                      dest="rfb_upgrade", default=defaults.rfb_upgrade,
                      help="Upgrade TCP sockets to send a RFB handshake after this delay (in seconds). Default: '%default'.")
    group.add_option("-d", "--debug", action="store",
                      dest="debug", default=defaults.debug, metavar="FILTER1,FILTER2,...",
                      help="List of categories to enable debugging for (you can also use \"all\" or \"help\", default: '%default')")
    group.add_option("--ssh", action="store",
                      dest="ssh", default=defaults.ssh, metavar="CMD",
                      help="How to run ssh. Default: '%default'.")
    legacy_bool_parse("exit-ssh")
    group.add_option("--exit-ssh", action="store", metavar="yes|no|auto",
                      dest="exit_ssh", default=defaults.exit_ssh,
                      help="Terminate SSH when disconnecting. Default: %default.")
    group.add_option("--username", action="store",
                      dest="username", default=defaults.username,
                      help="The username supplied by the client for authentication. Default: '%default'.")
    group.add_option("--auth", action="append",
                      dest="auth", default=list(defaults.auth or []),
                      help="The authentication module to use (default: '%default')")
    group.add_option("--tcp-auth", action="append",
                      dest="tcp_auth", default=list(defaults.tcp_auth or []),
                      help="The authentication module to use for TCP sockets (default: '%default')")
    group.add_option("--udp-auth", action="append",
                      dest="udp_auth", default=list(defaults.udp_auth or []),
                      help="The authentication module to use for UDP sockets (default: '%default')")
    group.add_option("--ws-auth", action="append",
                      dest="ws_auth", default=list(defaults.ws_auth or []),
                      help="The authentication module to use for Websockets (default: '%default')")
    group.add_option("--wss-auth", action="append",
                      dest="wss_auth", default=list(defaults.wss_auth or []),
                      help="The authentication module to use for Secure Websockets (default: '%default')")
    group.add_option("--ssl-auth", action="append",
                      dest="ssl_auth", default=list(defaults.ssl_auth or []),
                      help="The authentication module to use for SSL sockets (default: '%default')")
    group.add_option("--rfb-auth", action="append",
                      dest="rfb_auth", default=list(defaults.rfb_auth or []),
                      help="The authentication module to use for RFB sockets (default: '%default')")
    if vsock:
        group.add_option("--vsock-auth", action="append",
                         dest="vsock_auth", default=list(defaults.vsock_auth or []),
                         help="The authentication module to use for vsock sockets (default: '%default')")
    else:
        ignore({"vsock-auth" : defaults.vsock_auth})
    group.add_option("--min-port", action="store",
                      dest="min_port", default=defaults.min_port,
                      help="The minimum port number allowed when creating UDP or TCP sockets (default: '%default')")
    ignore({"password"           : defaults.password})
    if POSIX:
        group.add_option("--mmap-group", action="store_true",
                          dest="mmap_group", default=defaults.mmap_group,
                          help="When creating the mmap file with the client, set the group permission on the mmap file to the same value as the owner of the server socket file we connect to (default: '%default')")
        group.add_option("--socket-permissions", action="store",
                          dest="socket_permissions", default=defaults.socket_permissions,
                          help="When creating the server unix domain socket, what file access mode to use (default: '%default')")
    else:
        ignore({"mmap-group"            : defaults.mmap_group,
                "socket-permissions"    : defaults.socket_permissions,
                })

    replace_option("--enable-pings", "--pings=5")
    group.add_option("--pings", action="store", metavar="yes|no",
                      dest="pings", default=defaults.pings,
                      help="How often to send ping packets (in seconds, use zero to disable). Default: %s." % defaults.pings)
    group.add_option("--clipboard-filter-file", action="store",
                      dest="clipboard_filter_file", default=defaults.clipboard_filter_file,
                      help="Name of a file containing regular expressions of clipboard contents that must be filtered out")
    group.add_option("--local-clipboard", action="store",
                      dest="local_clipboard", default=defaults.local_clipboard,
                      metavar="SELECTION",
                      help="Name of the local clipboard selection to be synchronized when using the translated clipboard (default: %default)")
    group.add_option("--remote-clipboard", action="store",
                      dest="remote_clipboard", default=defaults.remote_clipboard,
                      metavar="SELECTION",
                      help="Name of the remote clipboard selection to be synchronized when using the translated clipboard (default: %default)")
    group.add_option("--remote-xpra", action="store",
                      dest="remote_xpra", default=defaults.remote_xpra,
                      metavar="CMD",
                      help="How to run xpra on the remote host (default: %s)" % (" or ".join(defaults.remote_xpra)))
    group.add_option("--encryption", action="store",
                      dest="encryption", default=defaults.encryption,
                      metavar="ALGO",
                      help="Specifies the encryption cipher to use, specify 'help' to get a list of options. (default: None)")
    group.add_option("--encryption-keyfile", action="store",
                      dest="encryption_keyfile", default=defaults.encryption_keyfile,
                      metavar="FILE",
                      help="Specifies the file containing the encryption key. (default: '%default')")
    group.add_option("--tcp-encryption", action="store",
                      dest="tcp_encryption", default=defaults.tcp_encryption,
                      metavar="ALGO",
                      help="Specifies the encryption cipher to use for TCP sockets, specify 'help' to get a list of options. (default: None)")
    group.add_option("--tcp-encryption-keyfile", action="store",
                      dest="tcp_encryption_keyfile", default=defaults.tcp_encryption_keyfile,
                      metavar="FILE",
                      help="Specifies the file containing the encryption key to use for TCP sockets. (default: '%default')")

    options, args = parser.parse_args(cmdline[1:])

    #ensure all the option fields are set even though
    #some options are not shown to the user:
    for k,v in hidden_options.items():
        if not hasattr(options, k):
            setattr(options, k.replace("-", "_"), v)

    #deal with boolean fields by converting them to a boolean value:
    for k,t in OPTION_TYPES.items():
        if t==bool:
            fieldname = name_to_field(k)
            if not hasattr(options, fieldname):
                #some fields may be missing if they're platform specific
                continue
            v = getattr(options, fieldname)
            bv = parse_bool(fieldname, v)
            if bv!=v:
                setattr(options, fieldname, bv)

    #process "help" arguments early:
    from xpra.log import STRUCT_KNOWN_FILTERS
    options.debug = fixup_debug_option(options.debug)
    if options.debug:
        categories = options.debug.split(",")
        for cat in categories:
            if cat=="help":
                h = []
                for category, d in STRUCT_KNOWN_FILTERS.items():
                    h.append("%s:" % category)
                    for k,v in d.items():
                        h.append(" * %-16s: %s" % (k,v))
                raise InitInfo("known logging filters: \n%s" % "\n".join(h))
    if options.sound_source=="help":
        from xpra.sound.gstreamer_util import NAME_TO_INFO_PLUGIN
        try:
            from xpra.sound.wrapper import query_sound
            source_plugins = query_sound().strlistget("sources", [])
            source_default = query_sound().strget("source.default", "")
        except Exception as e:
            raise InitInfo(e)
            source_plugins = []
        if source_plugins:
            raise InitInfo("The following sound source plugins may be used (default: %s):\n" % source_default+
                           "\n".join([" * "+p.ljust(16)+NAME_TO_INFO_PLUGIN.get(p, "") for p in source_plugins]))
        raise InitInfo("No sound source plugins found!")

    #only use the default bind option if the user hasn't specified one on the command line:
    if not options.bind:
        #use the default:
        options.bind = defaults_bind

    #special handling for URL mode:
    #xpra attach xpra://[mode:]host:port/?param1=value1&param2=value2
    if len(args)==2 and args[0]=="attach" and (args[1].startswith("xpra://") or args[1].startswith("xpras://")):
        url = args[1]
        address, params = parse_URL(url)
        for k,v in validate_config(params).items():
            setattr(options, k.replace("-", "_"), v)
        if url.startswith("xpras://tcp"):
            address = "ssl" + address[3:]
        args[1] = address

    #special case for things stored as lists, but command line option is a CSV string:
    #and may have "none" or "all" special values
    fixup_options(options, defaults)

    try:
        options.dpi = int(options.dpi)
    except Exception as e:
        raise InitException("invalid dpi value '%s': %s" % (options.dpi, e))
    if options.max_size:
        try:
            #split on "," or "x":
            w,h = [int(x.strip()) for x in options.max_size.replace(",", "x").split("x", 1)]
            assert w>=0 and h>0 and w<32768 and h<32768
        except:
            raise InitException("invalid max-size: %s" % options.max_size)
        options.max_size = "%sx%s" % (w, h)
    if options.encryption_keyfile and not options.encryption:
        options.encryption = "AES"
    if options.tcp_encryption_keyfile and not options.tcp_encryption:
        options.tcp_encryption = "AES"
    return options, args

def validated_encodings(encodings):
    from xpra.codecs.loader import PREFERED_ENCODING_ORDER
    validated = [x for x in PREFERED_ENCODING_ORDER if x.lower() in encodings]
    if not validated:
        raise InitException("no valid encodings specified")
    return validated

def validate_encryption(opts):
    do_validate_encryption(opts.auth, opts.tcp_auth, opts.encryption, opts.tcp_encryption, opts.encryption_keyfile, opts.tcp_encryption_keyfile)

def do_validate_encryption(auth, tcp_auth, encryption, tcp_encryption, encryption_keyfile, tcp_encryption_keyfile):
    if not encryption and not tcp_encryption:
        #don't bother initializing anything
        return
    from xpra.net.crypto import crypto_backend_init
    crypto_backend_init()
    if not encryption and not tcp_encryption:
        return
    env_key = os.environ.get("XPRA_ENCRYPTION_KEY")
    pass_key = os.environ.get("XPRA_PASSWORD")
    from xpra.net.crypto import ENCRYPTION_CIPHERS
    if not ENCRYPTION_CIPHERS:
        raise InitException("cannot use encryption: no ciphers available (a crypto library must be installed)")
    if encryption=="help" or tcp_encryption=="help":
        raise InitInfo("the following encryption ciphers are available: %s" % csv(ENCRYPTION_CIPHERS))
    if encryption and encryption not in ENCRYPTION_CIPHERS:
        raise InitException("encryption %s is not supported, try: %s" % (encryption, csv(ENCRYPTION_CIPHERS)))
    if tcp_encryption and tcp_encryption not in ENCRYPTION_CIPHERS:
        raise InitException("encryption %s is not supported, try: %s" % (tcp_encryption, csv(ENCRYPTION_CIPHERS)))
    if encryption and not encryption_keyfile and not env_key and not auth:
        raise InitException("encryption %s cannot be used without an authentication module or keyfile (see --encryption-keyfile option)" % encryption)
    if tcp_encryption and not tcp_encryption_keyfile and not env_key and not tcp_auth:
        raise InitException("tcp-encryption %s cannot be used without a tcp authentication module or keyfile (see --tcp-encryption-keyfile option)" % tcp_encryption)
    if pass_key and env_key and pass_key==env_key:
        raise InitException("encryption and authentication should not use the same value")
    #discouraged but not illegal:
    #if password_file and encryption_keyfile and password_file==encryption_keyfile:
    #    if encryption:
    #        raise InitException("encryption %s should not use the same file as the password authentication file" % encryption)
    #    elif tcp_encryption:
    #        raise InitException("tcp-encryption %s should not use the same file as the password authentication file" % tcp_encryption)

def show_sound_codec_help(is_server, speaker_codecs, microphone_codecs):
    from xpra.sound.wrapper import query_sound
    props = query_sound()
    if not props:
        return ["sound is not supported - gstreamer not present or not accessible"]
    info = []
    all_speaker_codecs = props.strlistget("decoders")
    invalid_sc = [x for x in speaker_codecs if x not in all_speaker_codecs]
    hs = "help" in speaker_codecs
    if hs:
        info.append("speaker codecs available: %s" % csv(all_speaker_codecs))
    elif len(invalid_sc):
        info.append("WARNING: some of the specified speaker codecs are not available: %s" % csv(invalid_sc))
        for x in invalid_sc:
            speaker_codecs.remove(x)
    elif len(speaker_codecs)==0:
        speaker_codecs += all_speaker_codecs

    all_microphone_codecs = props.strlistget("decoders")
    invalid_mc = [x for x in microphone_codecs if x not in all_microphone_codecs]
    hm = "help" in microphone_codecs
    if hm:
        info.append("microphone codecs available: %s" % csv(all_microphone_codecs))
    elif len(invalid_mc):
        info.append("WARNING: some of the specified microphone codecs are not available: %s" % (", ".join(invalid_mc)))
        for x in invalid_mc:
            microphone_codecs.remove(x)
    elif len(microphone_codecs)==0:
        microphone_codecs += all_microphone_codecs
    return info


def parse_vsock(vsock_str):
    from xpra.net.vsock import STR_TO_CID, CID_ANY, PORT_ANY    #@UnresolvedImport
    if not vsock_str.find(":")>=0:
        raise InitException("invalid vsocket format '%s'" % vsock_str)
    cid_str, port_str = vsock_str.split(":", 1)
    if cid_str.lower() in ("auto", "any"):
        cid = CID_ANY
    else:
        try:
            cid = int(cid_str)
        except ValueError:
            cid = STR_TO_CID.get(cid_str.upper())
            if cid is None:
                raise InitException("invalid vsock cid '%s'" % cid_str)
    if port_str.lower() in ("auto", "any"):
        iport = PORT_ANY
    else:
        try:
            iport = int(port_str)
        except ValueError:
            raise InitException("invalid vsock port '%s'" % port_str)
    return cid, iport


def is_local(host):
    return host.lower() in ("localhost", "127.0.0.1", "::1")
