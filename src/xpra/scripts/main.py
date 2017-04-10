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
import optparse
import logging
from subprocess import Popen, PIPE
import signal
import shlex
import traceback

from xpra import __version__ as XPRA_VERSION        #@UnresolvedImport
from xpra.platform.dotxpra import DotXpra
from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED, CAN_DAEMONIZE
from xpra.util import csv, envbool, envint, DEFAULT_PORT
from xpra.os_util import getuid, getgid, monotonic_time, setsid, WIN32, OSX
from xpra.scripts.config import OPTION_TYPES, CLIENT_OPTIONS, \
    InitException, InitInfo, InitExit, \
    fixup_debug_option, fixup_options, dict_to_validated_config, \
    make_defaults_struct, parse_bool, print_bool, print_number, validate_config, has_sound_support, name_to_field


NO_ROOT_WARNING = envbool("XPRA_NO_ROOT_WARNING", False)
INITENV_COMMAND = os.environ.get("XPRA_INITENV_COMMAND", "xpra initenv")
CLIPBOARD_CLASS = os.environ.get("XPRA_CLIPBOARD_CLASS")
SSH_DEBUG = envbool("XPRA_SSH_DEBUG", False)
WAIT_SERVER_TIMEOUT = envint("WAIT_SERVER_TIMEOUT", 15)


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

def warn(msg):
    #use this function to print warnings
    #we must write to stderr to prevent
    #the output from interfering when running as proxy over ssh
    #(which uses stdin / stdout as communication channel)
    sys.stderr.write(msg+"\n")

def nox():
    DISPLAY = os.environ.get("DISPLAY")
    if DISPLAY is not None:
        del os.environ["DISPLAY"]
    # This is an error on Fedora/RH, so make it an error everywhere so it will
    # be noticed:
    import warnings
    warnings.filterwarnings("error", "could not open display")
    return DISPLAY


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
                sys.stderr.write(("Warning: invalid 'help' option found in '%s' configuration\n" % k) +
                             " this should only be used as a command line argument\n")
            if k in ("encoding", "debug", "sound-source"):
                setattr(defaults, fn, "")
            else:
                v.remove("help")


def main(script_file, cmdline):
    from xpra.platform import clean as platform_clean, command_error, command_info, get_main_fallback
    if len(cmdline)==1:
        fm = get_main_fallback()
        if fm:
            return fm()

    def debug_exc(msg="run_mode error"):
        from xpra.log import Logger
        log = Logger("util")
        log(msg, exc_info=True)

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


def do_replace_option(cmdline, oldoption, newoption):
    if oldoption in cmdline:
        cmdline.remove(oldoption)
        cmdline.append(newoption)
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

def full_version_str():
    s = XPRA_VERSION
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS
        s += "-r%i%s" % (REVISION, ["","M"][int(LOCAL_MODIFICATIONS>0)])
    except:
        pass
    return s

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
                           "\t%prog stop [DISPLAY]\n",
                           "\t%prog exit [DISPLAY]\n",
                           "\t%prog list\n",
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
    group.add_option("--exit-with-children", action="store_true",
                      dest="exit_with_children", default=defaults.exit_with_children,
                      help="Terminate the server when the last --start-child command(s) exit")
    legacy_bool_parse("start-new-commands")
    group.add_option("--start-new-commands", action="store", metavar="yes|no",
                      dest="start_new_commands", default=defaults.start_new_commands,
                      help="Allows clients to execute new commands on the server. Default: %s." % enabled_str(defaults.start_new_commands))
    legacy_bool_parse("proxy-start-sessions")
    group.add_option("--proxy-start-sessions", action="store", metavar="yes|no",
                      dest="proxy_start_sessions", default=defaults.proxy_start_sessions,
                      help="Allows proxy servers to start new sessions on demand. Default: %s." % enabled_str(defaults.proxy_start_sessions))
    group.add_option("--dbus-launch", action="store",
                      dest="dbus_launch", metavar="CMD", default=defaults.dbus_launch,
                      help="Start the session within a dbus-launch context, leave empty to turn off. Default: %default.")
    group.add_option("--start-env", action="append",
                      dest="start_env", default=list(defaults.start_env or []),
                      help="Define environment variables used with 'start-child' and 'start', can be specified multiple times. Default: %s." % ", ".join([("'%s'" % x) for x in (defaults.start_env or []) if not x.startswith("#")]))
    if os.name=="posix":
        legacy_bool_parse("systemd-run")
        group.add_option("--systemd-run", action="store", metavar="yes|no|auto",
                          dest="systemd_run", default=defaults.systemd_run,
                          help="Wrap server start commands with systemd-run. Default: %default.")
        group.add_option("--systemd-run-args", action="store", metavar="ARGS",
                          dest="systemd_run_args", default=defaults.systemd_run_args,
                          help="Command line arguments passed to systemd-run. Default: '%default'.")
    else:
        ignore({"systemd_run"       : "no",
                "systemd_run_args"  : ""})

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
    if (supports_server or supports_shadow) and CAN_DAEMONIZE:
        group.add_option("--daemon", action="store", metavar="yes|no",
                          dest="daemon", default=defaults.daemon,
                          help="Daemonize when running as a server (default: %s)" % enabled_str(defaults.daemon))
        group.add_option("--attach", action="store", metavar="yes|no|auto",
                          dest="attach", default=defaults.attach,
                          help="Attach a client as soon as the server has started (default: %s)" % enabled_or_auto(defaults.attach))
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
                "daemon"    : False,
                "attach"    : "no",
                "pidfile"   : defaults.pidfile,
                "log_file"  : defaults.log_file,
                "log_dir"   : defaults.log_dir,
                })

    legacy_bool_parse("printing")
    legacy_bool_parse("file-transfer")
    legacy_bool_parse("open-files")
    group.add_option("--file-transfer", action="store", metavar="yes|no",
                      dest="file_transfer", default=defaults.file_transfer,
                      help="Support file transfers. Default: %s." % enabled_str(defaults.file_transfer))
    group.add_option("--open-files", action="store", metavar="yes|no",
                      dest="open_files", default=defaults.open_files,
                      help="Automatically open uploaded files (potentially dangerous). Default: %s." % enabled_str(defaults.file_transfer))
    group.add_option("--printing", action="store", metavar="yes|no",
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
        ignore({"exit_with_client" : False})
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
        group.add_option("--fake-xinerama", action="store", metavar="yes|no",
                          dest="fake_xinerama",
                          default=defaults.fake_xinerama,
                          help="Setup fake xinerama support for the session. Default: %s." % enabled_str(defaults.fake_xinerama))
    else:
        ignore({"use-display"   : False,
                "xvfb"          : '',
                "fake-xinerama" : defaults.fake_xinerama})
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
        group.add_option("--bind-ssl", action="append",
                          dest="bind_ssl", default=list(defaults.bind_ssl or []),
                          metavar="[HOST]:PORT",
                          help="Listen for connections over SSL (use --ssl-auth to secure it)."
                            + " You may specify this option multiple times with different host and port combinations")
    else:
        ignore({"bind" : []})
        ignore({"bind-tcp" : []})
        ignore({"bind-ssl" : []})
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
        ignore({"mdns" : False})
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
                "These options can be used to turn certain features on or off, "
                "they can be specified on the client or on the server, "
                "but the client cannot enable them if they are disabled on the server.")
    parser.add_option_group(group)
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
    legacy_bool_parse("global-menus")
    group.add_option("--global-menus", action="store",
                      dest="global_menus", default=defaults.global_menus, metavar="yes|no",
                      help="Forward application global menus. Default: %s." % enabled_str(defaults.global_menus))
    legacy_bool_parse("xsettings")
    if os.name=="posix":
        group.add_option("--xsettings", action="store", metavar="yes|no",
                          dest="xsettings", default=defaults.xsettings,
                          help="xsettings synchronization. Default: %s." % enabled_str(defaults.xsettings))
    else:
        ignore({"xsettings" : False})
    legacy_bool_parse("mmap")
    group.add_option("--mmap", action="store", metavar="yes|no|mmap-filename",
                      dest="mmap", default=defaults.mmap,
                      help="Use memory mapped transfers for local connections. Default: %s." % defaults.mmap)
    legacy_bool_parse("sharing")
    group.add_option("--sharing", action="store", metavar="yes|no",
                      dest="sharing", default=defaults.sharing,
                      help="Allow more than one client to connect to the same session. Default: %s." % enabled_str(defaults.sharing))
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
        ignore({"av-sync"           : False,
                "speaker"           : "no",
                "speaker-codec"     : [],
                "microphone"        : "no",
                "microphone-codec"  : [],
                "sound-source"      : ""})

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
    if (supports_server or supports_shadow):
        group.add_option("--video-encoders", action="store",
                          dest="video_encoders", default=defaults.video_encoders,
                          help="Specify which video encoders to enable, to get a list of all the options specify 'help'")
    else:
        ignore({"video-encoders" : []})
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
                      dest="compressors", default=", ".join(defaults.compressors),
                      help="The packet compressors to enable. Default: %default.")
    group.add_option("--packet-encoders", action="store",
                      dest="packet_encoders", default=", ".join(defaults.packet_encoders),
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
    group.add_option("--opengl", action="store", metavar="yes|no|auto",
                      dest="opengl", default=defaults.opengl,
                      help="Use OpenGL accelerated rendering. Default: %s." % print_bool("opengl", defaults.opengl))
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
                      help="Define environment variables which will apply to this process and all subprocesses, can be specified multiple times. Default: %s." % ", ".join([("'%s'" % x) for x in (defaults.env or []) if not x.startswith("#")]))
    group.add_option("--password-file", action="store",
                      dest="password_file", default=defaults.password_file,
                      help="The file containing the password required to connect (useful to secure TCP mode). Default: '%default'.")
    group.add_option("--input-method", action="store",
                      dest="input_method", default=defaults.input_method,
                      help="Which X11 input method to configure for client applications started with start or start-child (default: '%default', options: none, keep, xim, IBus, SCIM, uim)")
    group.add_option("--dpi", action="store",
                      dest="dpi", default=defaults.dpi,
                      help="The 'dots per inch' value that client applications should try to honour, from 10 to 1000 or 0 for automatic setting. Default: %s." % print_number(defaults.dpi))
    group.add_option("--pixel-depth", action="store",
                      dest="pixel_depth", default=defaults.pixel_depth,
                      help="The bits per pixel of the virtual framebuffer (8, 16, 24 or 30). Default: %s." % defaults.pixel_depth)
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
    group.add_option("--auth", action="store",
                      dest="auth", default=defaults.auth,
                      help="The authentication module to use (default: '%default')")
    group.add_option("--tcp-auth", action="store",
                      dest="tcp_auth", default=defaults.tcp_auth,
                      help="The authentication module to use for TCP sockets (default: '%default')")
    group.add_option("--ssl-auth", action="store",
                      dest="ssl_auth", default=defaults.ssl_auth,
                      help="The authentication module to use for SSL sockets (default: '%default')")
    if vsock:
        group.add_option("--vsock-auth", action="store",
                         dest="vsock_auth", default=defaults.vsock_auth,
                         help="The authentication module to use for vsock sockets (default: '%default')")
    else:
        ignore({"vsock-auth" : ""})
    ignore({"password"           : defaults.password})
    if os.name=="posix":
        group.add_option("--mmap-group", action="store_true",
                          dest="mmap_group", default=defaults.mmap_group,
                          help="When creating the mmap file with the client, set the group permission on the mmap file to the same value as the owner of the server socket file we connect to (default: '%default')")
        group.add_option("--socket-permissions", action="store",
                          dest="socket_permissions", default=defaults.socket_permissions,
                          help="When creating the server unix domain socket, what file access mode to use (default: '%default')")
    else:
        ignore({"mmap-group"            : False,
                "socket-permissions"    : defaults.socket_permissions})

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

    #only use the default bind option if the user hasn't specified one on the command line:
    if not options.bind:
        #use the default:
        options.bind = defaults_bind

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
        except Exception as e:
            raise InitInfo(e)
            source_plugins = []
        if source_plugins:
            raise InitInfo("The following sound source plugins may be used (default: %s):\n" % source_plugins[0]+
                           "\n".join([" * "+p.ljust(16)+NAME_TO_INFO_PLUGIN.get(p, "") for p in source_plugins]))
        raise InitInfo("No sound source plugins found!")

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
        raise InitException("invalid dpi: %s" % e)
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
    #ensure opengl is either True, False or None
    options.opengl = parse_bool("opengl", options.opengl)
    return options, args

def validate_encryption(opts):
    do_validate_encryption(opts.auth, opts.tcp_auth, opts.encryption, opts.tcp_encryption, opts.password_file, opts.encryption_keyfile, opts.tcp_encryption_keyfile)

def do_validate_encryption(auth, tcp_auth, encryption, tcp_encryption, password_file, encryption_keyfile, tcp_encryption_keyfile):
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

def dump_frames(*arsg):
    frames = sys._current_frames()
    print("")
    print("found %s frames:" % len(frames))
    for fid,frame in frames.items():
        print("%s - %s:" % (fid, frame))
        traceback.print_stack(frame)
    print("")

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
        info.append("speaker codecs available: %s" % (", ".join(all_speaker_codecs)))
    elif len(invalid_sc):
        info.append("WARNING: some of the specified speaker codecs are not available: %s" % (", ".join(invalid_sc)))
        for x in invalid_sc:
            speaker_codecs.remove(x)
    elif len(speaker_codecs)==0:
        speaker_codecs += all_speaker_codecs

    all_microphone_codecs = props.strlistget("decoders")
    invalid_mc = [x for x in microphone_codecs if x not in all_microphone_codecs]
    hm = "help" in microphone_codecs
    if hm:
        info.append("microphone codecs available: %s" % (", ".join(all_microphone_codecs)))
    elif len(invalid_mc):
        info.append("WARNING: some of the specified microphone codecs are not available: %s" % (", ".join(invalid_mc)))
        for x in invalid_mc:
            microphone_codecs.remove(x)
    elif len(microphone_codecs)==0:
        microphone_codecs += all_microphone_codecs
    return info

def configure_logging(options, mode):
    to = sys.stderr
    if mode in ("showconfig", "info", "control", "list", "list-mdns", "mdns-gui", "attach", "stop", "version", "print", "opengl", "test-connect"):
        to = sys.stdout
    #a bit naughty here, but it's easier to let xpra.log initialize
    #the logging system every time, and just undo things here..
    from xpra.log import setloghandler, enable_color, enable_format, LOG_FORMAT, NOPREFIX_FORMAT
    setloghandler(logging.StreamHandler(to))
    if mode in ("start", "start-desktop", "upgrade", "attach", "shadow", "proxy", "_sound_record", "_sound_play", "stop", "print", "showconfig"):
        if "help" in options.speaker_codec or "help" in options.microphone_codec:
            info = show_sound_codec_help(mode!="attach", options.speaker_codec, options.microphone_codec)
            raise InitInfo("\n".join(info))
        fmt = LOG_FORMAT
        if mode in ("stop", "showconfig"):
            fmt = NOPREFIX_FORMAT
        if (hasattr(to, "fileno") and os.isatty(to.fileno())) or envbool("XPRA_FORCE_COLOR_LOG", False):
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
    if os.name=="posix":
        def sigusr1(*args):
            dump_frames()
        signal.signal(signal.SIGUSR1, sigusr1)

def configure_network(options):
    from xpra.net import compression, packet_encoding
    for c in compression.ALL_COMPRESSORS:
        enabled = c in compression.get_enabled_compressors() and c in options.compressors
        setattr(compression, "use_%s" % c, enabled)
    if not compression.get_enabled_compressors():
        #force compression level to zero since we have no compressors available:
        options.compression_level = 0
    for pe in packet_encoding.ALL_ENCODERS:
        enabled = pe in packet_encoding.get_enabled_encoders() and pe in options.packet_encoders
        setattr(packet_encoding, "use_%s" % pe, enabled)
    #verify that at least one encoder is available:
    if not packet_encoding.get_enabled_encoders():
        raise InitException("at least one valid packet encoder must be enabled (not '%s')" % options.packet_encoders)

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

def configure_env(options):
    if options.env:
        os.environ.update(parse_env(options.env))


def systemd_run_wrap(mode, args, systemd_run_args):
    cmd = ["systemd-run", "--description" , "xpra-%s" % mode, "--scope", "--user"]
    if systemd_run_args:
        cmd += shlex.split(systemd_run_args)
    cmd += args
    cmd.append("--systemd-run=no")
    print("using systemd-run to wrap '%s' server command" % mode)
    print("%s" % " ".join(["'%s'" % x for x in cmd]))
    try:
        p = Popen(cmd)
        p.wait()
    except KeyboardInterrupt:
        return 128+signal.SIGINT

def isdisplaytype(args, dtype):
    return len(args)>0 and (args[0].startswith("%s/" % dtype) or args[0].startswith("%s:" % dtype))

def run_mode(script_file, error_cb, options, args, mode, defaults):
    #configure default logging handler:
    if os.name=="posix" and getuid()==0 and mode!="proxy" and not NO_ROOT_WARNING:
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
            wrapit = envbool("XPRA_SYSTEMD_RUN", True)
            if wrapit:
                return systemd_run_wrap(mode, sys.argv, options.systemd_run_args)

    configure_env(options)
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

    try:
        if mode in ("start", "start-desktop", "shadow") and display_is_remote:
            #ie: "xpra start ssh:HOST:DISPLAY --start-child=xterm"
            return run_remote_server(error_cb, options, args, mode, defaults)
        elif (mode in ("start", "start-desktop", "upgrade") and supports_server) or \
            (mode=="shadow" and supports_shadow) or (mode=="proxy" and supports_proxy):
            cwd = os.getcwd()
            env = os.environ.copy()
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
                    proc = Popen(cmd, close_fds=True, preexec_fn=setsid, cwd=cwd, env=env)
                    from xpra.child_reaper import getChildReaper
                    getChildReaper().add_process(proc, "client-attach", cmd, ignore=True, forget=False)
                add_when_ready(attach_client)
            return run_server(error_cb, options, mode, script_file, args, current_display)
        elif mode in ("attach", "detach", "screenshot", "version", "info", "control", "_monitor", "print", "connect-test"):
            return run_client(error_cb, options, args, mode)
        elif mode in ("stop", "exit") and (supports_server or supports_shadow):
            nox()
            return run_stopexit(mode, error_cb, options, args)
        elif mode == "list" and (supports_server or supports_shadow):
            return run_list(error_cb, options, args)
        elif mode == "list-mdns" and supports_mdns:
            return run_list_mdns(error_cb, options, args)
        elif mode == "mdns-gui" and supports_mdns:
            return run_mdns_gui(error_cb, options, args)
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
            from xpra.scripts.server import xpra_runner_shell_script, write_runner_shell_scripts
            script = xpra_runner_shell_script(script_file, os.getcwd(), options.socket_dir)
            write_runner_shell_scripts(script, False)
            return 0
        elif mode == "showconfig":
            return run_showconfig(options, args)
        else:
            error_cb("invalid mode '%s'" % mode)
            return 1
    except KeyboardInterrupt as e:
        sys.stderr.write("\ncaught %s, exiting\n" % repr(e))
        return 128+signal.SIGINT


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

def parse_display_name(error_cb, opts, display_name):
    desc = {"display_name" : display_name}
    def parse_host_string(host, default_port=DEFAULT_PORT):
        """
            Parses [username[:password]@]host[:port]
            and returns username, password, host, port
            missing arguments will be empty (username and password) or 0 (port)
        """
        upos = host.find("@")
        username = None
        password = None
        port = default_port
        if upos>=0:
            #HOST=username@host
            username = host[:upos]
            host = host[upos+1:]
            ppos = username.find(":")
            if ppos>=0:
                password = username[ppos+1:]
                username = username[:ppos]
                desc["password"] = password
                opts.password = password
            if username:
                desc["username"] = username
                #fugly: we override the command line option after parsing the string:
                opts.username = username
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
                host = host[1:epos]                 #ie: "HOST"
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

    if display_name.lower().startswith("ssh:") or display_name.lower().startswith("ssh/"):
        separator = display_name[3] # ":" or "/"
        desc.update({
                "type"             : "ssh",
                "proxy_command"    : ["_proxy"],
                "exit_ssh"         : opts.exit_ssh,
                 })
        parts = display_name.split(separator)
        desc["display"] = None
        desc["display_as_args"] = []
        if len(parts)>2:
            #ssh:HOST:DISPLAY or ssh/HOST/DISPLAY
            host = separator.join(parts[1:-1])
            if parts[-1]:
                display = ":" + parts[-1]
                desc["display"] = display
                opts.display = display
                desc["display_as_args"] = [display]
        else:
            #ssh:HOST or ssh/HOST
            host = parts[1]
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
        if desc.get("password") is None and opts.password_file and os.path.exists(opts.password_file):
            try:
                with open(opts.password_file, "rb") as f:
                    desc["password"] = f.read()
            except Exception as e:
                sys.stderr.write("Error: failed to read the password file '%s':\n", opts.password_file)
                sys.stderr.write(" %s\n", e)
        return desc
    elif display_name.startswith("socket:"):
        #use the socketfile specified:
        sockfile = display_name[len("socket:"):]
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
    elif display_name.startswith("tcp:") or display_name.startswith("tcp/") or \
            display_name.startswith("ssl:") or display_name.startswith("ssl/"):
        ctype = display_name[:3]        #ie: "ssl" or "tcp"
        separator = display_name[3]     # ":" or "/"
        desc.update({
                     "type"     : ctype,
                     })
        parts = display_name.split(separator)
        if len(parts) not in (2, 3, 4):
            error_cb("invalid %s connection string, use %s/[username[:password]@]host[:port][/display] or %s:[username[:password]@]host[:port]" % (ctype * 3))
        #display (optional):
        if separator=="/" and len(parts)==3:
            display = parts[2]
            if display:
                try:
                    v = int(display)
                    display = ":%s" % v
                except:
                    pass
                desc["display"] = display
                opts.display = display
            parts = parts[:-1]
        host = ":".join(parts[1:])
        username, password, host, port = parse_host_string(host)
        assert port>0, "no port specified in %s" % host
        return desc
    elif display_name.startswith("vsock:") or display_name.startswith("vsock/"):
        #use the vsock specified:
        vsock_str = display_name[len("vsock:"):]
        cid, iport = parse_vsock(vsock_str)
        desc.update({
                "type"          : "vsock",
                "local"         : False,
                "display"       : display_name,
                "vsock"         : (cid, iport),
                })
        opts.display = display_name
        return desc
    elif display_name.startswith("ws:") or display_name.startswith("wss:") or display_name.startswith("ws/") or display_name.startswith("wss/"):
        if display_name.startswith("wss"):
            separator = display_name[3] # ":" or "/"
        else:
            assert display_name.startswith("ws")
            separator = display_name[2] # ":" or "/"
        try:
            import websocket
            assert websocket
        except ImportError as e:
            raise InitException("the websocket client module cannot be loaded: %s" % e)
        ws_proto, host = display_name.split(separator, 1)
        if host.find("?")>=0:
            host, _ = host.split("?", 1)
        if host.find("/")>=0:
            host, extra = host.split("/", 1)
        else:
            extra = ""
        username, password, host, port = parse_host_string(host)
        #TODO: parse attrs after "/" and ?"
        desc.update({
                "type"          : ws_proto,     #"ws" or "wss"
                "display"       : extra,
                "host"          : host,
                "port"          : port,
                })
        print("ws:%s" % desc)
        return desc
    elif WIN32 or display_name.startswith("named-pipe:"):
        pipe_name = display_name
        if display_name.startswith("named-pipe:"):
            pipe_name = display_name[len("named-pipe:"):]
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
        sockdir, display, path = single_display_match(dir_servers, error_cb)
        if WIN32:
            return {
                    "type"              : "named-pipe",
                    "local"             : True,
                    "display"           : display,
                    "display_name"      : display,
                    "named-pipe"        : path,
                    }
        return {
                "type"          : "unix-domain",
                "local"         : True,
                "display"       : display,
                "display_name"  : display,
                "socket_dir"    : sockdir,
                "socket_path"   : path
                }
    elif len(extra_args) == 1:
        return parse_display_name(error_cb, opts, extra_args[0])
    else:
        error_cb("too many arguments")

def single_display_match(dir_servers, error_cb):
    #ie: {"/tmp" : [LIVE, "desktop-10", "/tmp/desktop-10"]}
    #aggregate all the different locations:
    allservers = []
    for sockdir, servers in dir_servers.items():
        for state, display, path in servers:
            if state==DotXpra.LIVE:
                allservers.append((sockdir, display, path))
    if len(allservers) == 0:
        error_cb("cannot find any live servers to connect to")
    if len(allservers) > 1:
        #maybe the same server is available under multiple paths
        displays = set([v[1] for v in allservers])
        if len(displays)==1:
            #they all point to the same display, use the first one:
            allservers = allservers[:1]
        else:
            error_cb("there are multiple servers running, please specify")
    assert len(allservers)==1, "len(dir_servers)=%s" % len(dir_servers)
    sockdir, name, path = allservers[0]
    #ie: ("/tmp", "desktop-10", "/tmp/desktop-10")
    return sockdir, name, path


def _socket_connect(sock, endpoint, description, dtype):
    from xpra.net.bytestreams import SocketConnection, pretty_socket
    try:
        sock.connect(endpoint)
    except Exception as e:
        from xpra.log import Logger
        log = Logger("network")
        log("failed to connect", exc_info=True)
        raise InitException("failed to connect to '%s':\n %s" % (pretty_socket(endpoint), e))
    sock.settimeout(None)
    return SocketConnection(sock, sock.getsockname(), sock.getpeername(), description, dtype)

def connect_or_fail(display_desc, opts):
    try:
        return connect_to(display_desc, opts)
    except InitException:
        raise
    except Exception as e:
        from xpra.log import Logger
        log = Logger("network")
        log("failed to connect", exc_info=True)
        raise InitException("connection failed: %s" % e)

def ssh_connect_failed(message):
    #by the time ssh fails, we may have entered the gtk main loop
    #(and more than once thanks to the clipboard code..)
    if "gtk" in sys.modules or "gi.repository.Gtk" in sys.modules:
        from xpra.gtk_common.quit import gtk_main_quit_really
        gtk_main_quit_really()


def connect_to(display_desc, opts=None, debug_cb=None, ssh_fail_cb=ssh_connect_failed):
    from xpra.net.bytestreams import TCP_NODELAY, SOCKET_TIMEOUT, VSOCK_TIMEOUT
    from xpra.net import ConnectionClosedException  #@UnresolvedImport
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
            if not display_desc.get("exit_ssh", False) and not OSX:
                kwargs["preexec_fn"] = setsid
            elif WIN32:
                from subprocess import CREATE_NEW_PROCESS_GROUP, CREATE_NEW_CONSOLE
                flags = CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
                kwargs["creationflags"] = flags
                kwargs["stderr"] = PIPE
            remote_xpra = display_desc["remote_xpra"]
            assert len(remote_xpra)>0
            remote_commands = []
            socket_dir = display_desc.get("socket_dir")
            for x in remote_xpra:
                #ie: ["~/.xpra/run-xpra"] + ["_proxy"] + [":10"]
                pc = [x] + display_desc["proxy_command"] + display_desc["display_as_args"]
                if socket_dir:
                    pc.append("--socket-dir=%s" % socket_dir)
                remote_commands.append((" ".join(pc)))
            #ie: ~/.xpra/run-xpra _proxy || $XDG_RUNTIME_DIR/run-xpra _proxy
            remote_cmd = " || ".join(remote_commands)
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
            raise InitException("Error running ssh command '%s': %s" % (" ".join("\"%s\"" % x for x in cmd), e))
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
                    from xpra.log import Logger
                    log = Logger()
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
            if os.name=="posix":
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
        target = "ssh/"
        username = display_desc.get("username")
        if username:
            target += "%s@" % username
        target += display_desc.get("host")
        ssh_port = display_desc.get("ssh-port")
        if ssh_port:
            target += ":%i" % ssh_port
        display = display_desc.get("display")
        target += "/%s" % (display or "")
        conn = TwoFileConnection(child.stdin, child.stdout, abort_test, target=target, socktype=dtype, close_cb=stop_tunnel)
        conn.timeout = 0            #taken care of by abort_test
        conn.process = (child, "ssh", cmd)

    elif dtype == "unix-domain":
        if not hasattr(socket, "AF_UNIX"):
            return False, "unix domain sockets are not available on this operating system"
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

    elif dtype in ("tcp", "ssl", "ws", "wss"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, TCP_NODELAY)
        strict_host_check = display_desc.get("strict-host-check")
        if strict_host_check is False:
            opts.ssl_server_verify_mode = "none"
        tcp_endpoint = (display_desc["host"], display_desc["port"])
        conn = _socket_connect(sock, tcp_endpoint, display_name, dtype)
        if dtype in ("ssl", "wss"):
            wrap_socket = ssl_wrap_socket_fn(opts, server_side=False)
            sock = wrap_socket(sock)
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
            try:
                ws = websocket.create_connection(url, SOCKET_TIMEOUT, subprotocols=["binary", "base64"], socket=sock)
            except ValueError as e:
                raise InitException("websocket connection failed: %s" % e)
            from xpra.net.bytestreams import Connection, log as connlog
            class WebSocketClientConnection(Connection):
                def __init__(self, ws, target, socktype):
                    Connection.__init__(self, target, socktype)
                    self._socket = ws

                def peek(self, n):
                    return None

                def untilConcludes(self, *args):
                    try:
                        return Connection.untilConcludes(self, *args)
                    except websocket.WebSocketTimeoutException as e:
                        raise ConnectionClosedException(e)

                def read(self, n):
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
            return WebSocketClientConnection(ws, "websocket", host)
    else:
        assert False, "unsupported display type in connect: %s" % dtype
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
              "do_handshake_on_connect" : True,
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
        try:
            ssl_sock = wrap_socket(tcp_socket, **kwargs)
        except Exception as e:
            SSLEOFError = getattr(ssl, "SSLEOFError", None)
            if SSLEOFError and isinstance(e, SSLEOFError):
                return None
            raise
        #ensure we handle ssl exceptions as we should from now on:
        from xpra.net.bytestreams import init_ssl
        init_ssl()
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
        _, _, sockpath = single_display_match(dir_servers, error_cb)
    return sockpath

def run_client(error_cb, opts, extra_args, mode):
    validate_encryption(opts)
    if mode=="screenshot":
        if len(extra_args)==0:
            error_cb("invalid number of arguments for screenshot mode")
        screenshot_filename = extra_args[0]
        extra_args = extra_args[1:]

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
        def handshake_complete(*args):
            from xpra.log import Logger
            log = Logger()
            log.info("Attached to %s (press Control-C to detach)\n" % conn.target)
        if hasattr(app, "after_handshake"):
            app.after_handshake(handshake_complete)
        app.init_ui(opts, extra_args)
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
    return do_run_client(app)

def make_client(error_cb, opts):
    from xpra.platform.features import CLIENT_MODULES
    for client_module in CLIENT_MODULES:
        #ie: "xpra.client.gtk2.client"
        toolkit_module = __import__(client_module, globals(), locals(), ['XpraClient'])
        if toolkit_module:
            return toolkit_module.XpraClient()
    error_cb("could not load %s" % ", ".join(CLIENT_MODULES))

def do_run_client(app):
    try:
        return app.run()
    except KeyboardInterrupt:
        return -signal.SIGINT
    finally:
        app.cleanup()

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
    start_child = []
    if opts.start_child:
        start_child = strip_defaults_start_child(opts.start_child, defaults.start_child)
    start = []
    if opts.start:
        start = strip_defaults_start_child(opts.start, defaults.start)
    if isdisplaytype(args, "ssh"):
        #add special flags to "display_as_args"
        proxy_args = []
        if params.get("display") is not None:
            proxy_args.append(params["display"])
        for c in start_child:
            proxy_args.append(shellquote("--start-child=%s" % c))
        for c in start:
            proxy_args.append(shellquote("--start=%s" % c))
        #key=value options we forward:
        for x in ("session-name", "encoding", "socket-dir", "dpi"):
            v = getattr(opts, x.replace("-", "_"))
            if v:
                proxy_args.append("--%s=%s" % (x, v))
        #these options must be enabled explicitly (no disable option for most of them):
        for e in ("exit-with-children", "mmap-group", "readonly"):
            if getattr(opts, e.replace("-", "_")) is True:
                proxy_args.append("--%s" % e)
        #older versions only support disabling:
        for e in ("pulseaudio", "mmap",
                  "system-tray", "clipboard", "bell"):
            if getattr(opts, e.replace("-", "_")) is False:
                proxy_args.append("--no-%s" % e)
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
               "start"          : start,
               "start-child"    : start_child,
               "mode"           : mode,
               "display"        : params.get("display", ""),
               }
        for x in ("exit-with-children", "exit-with-client",
                  "session-name", "encoding", "socket-dir", "dpi",
                  "pulseaudio", "mmap",
                  "system-tray", "clipboard", "bell"):
            v = getattr(opts, x.replace("-", "_"))
            if v:
                sns[x] = v
        hello_extra = {"start-new-session" : sns}

    def connect():
        return connect_or_fail(params, opts)

    if opts.attach is False:
        from xpra.client.gobject_client_base import ConnectTestXpraClient
        app = ConnectTestXpraClient((connect(), params), opts)
    else:
        app = make_client(error_cb, opts)
        app.init(opts)
        app.init_ui(opts)
        app.hello_extra = hello_extra
        app.setup_connection(connect())
    do_run_client(app)

def find_X11_displays(max_display_no=None, match_uid=None, match_gid=None):
    displays = []
    X11_SOCKET_DIR = "/tmp/.X11-unix/"
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
            raise InitExit(1, "could not detect any live plain X11 displays, only multiple xpra displays: %s" % ", ".join(xpra_displays))
    if len(displays)!=1:
        raise InitExit(1, "too many live X11 displays to choose from: %s" % ", ".join(displays))
    return displays[0]


def no_gtk():
    gtk = sys.modules.get("gtk")
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
    from xpra.client.gl.gl_check import check_support
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


def setuidgid(uid, gid):
    if os.name!="posix":
        return
    from xpra.log import Logger
    log = Logger("server")
    if os.getuid()!=uid or os.getgid()!=gid:
        #find the username for the given uid:
        from pwd import getpwuid
        try:
            username = getpwuid(uid).pw_name
        except KeyError:
            raise Exception("uid %i not found" % uid)
        #set the groups:
        if hasattr(os, "initgroups"):   # python >= 2.7
            os.initgroups(username, gid)
        else:
            import grp      #@UnresolvedImport
            groups = [gr.gr_gid for gr in grp.getgrall() if (username in gr.gr_mem)]
            os.setgroups(groups)
    #change uid and gid:
    try:
        if os.getgid()!=gid:
            os.setgid(gid)
    except OSError as e:
        log.error("Error: cannot change gid to %i:", gid)
        if os.getgid()==0:
            #don't run as root!
            raise
        log.error(" %s", e)
        log.error(" continuing with gid=%i", os.getgid())
    try:
        if os.getuid()!=uid:
            os.setuid(uid)
    except OSError as e:
        log.error("Error: cannot change uid to %i:", uid)
        if os.getuid()==0:
            #don't run as root!
            raise
        log.error(" %s", e)
        log.error(" continuing with gid=%i", os.getuid())
    log("new uid=%s, gid=%s", os.getuid(), os.getgid())


def start_server_subprocess(script_file, args, mode, defaults,
                            socket_dir, socket_dirs,
                            start=[], start_child=[],
                            exit_with_children=False, exit_with_client=False,
                            uid=0, gid=0):
    username = ""
    home = ""
    if os.name=="posix":
        import pwd
        e = pwd.getpwuid(uid)
        username = e.pw_name
        home = e.pw_dir
    dotxpra = DotXpra(socket_dir, socket_dirs, username, uid=uid, gid=gid)
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

    #get the list of existing sockets so we can spot the new ones:
    if display_name.startswith("S"):
        matching_display = None
    else:
        matching_display = display_name
    existing_sockets = set(dotxpra.socket_paths(check_uid=uid, matching_state=dotxpra.LIVE, matching_display=matching_display))

    cmd = [script_file, mode] + args        #ie: ["/usr/bin/xpra", "start-desktop", ":100"]
    if start_child:
        for x in start_child:
            cmd.append("--start-child=%s" % x)
    if start:
        for x in start:
            cmd.append("--start=%s" % x)
    if exit_with_children:
        cmd.append("--exit-with-children")
    if exit_with_client or mode=="shadow":
        cmd.append("--exit-with-client")
    cmd.append("--socket-dir=%s" % (socket_dir or ""))
    for x in socket_dirs:
        cmd.append("--socket-dirs=%s" % (x or ""))
    #add a unique uuid to the server env:
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
                sys.stderr.write("Error: shadow may not start,\n the launch agent file '%s' seems to be missing:%s.\n" % (LAUNCH_AGENT_FILE, e))
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
        for x in launch_commands:
            proc = Popen(x, shell=False, close_fds=True)
            proc.wait()
        proc = None
    else:
        def preexec():
            setsid()
            if uid!=0 or gid!=0:
                setuidgid(uid, gid)
        cmd.append("--systemd-run=no")
        server_env = os.environ.copy()
        if username:
            server_env.update({
                               "USER"       : username,
                               "USERNAME"   : username,
                               "HOME"       : home or os.path.join("/home", username),
                               })
        proc = Popen(cmd, shell=False, close_fds=True, env=server_env, preexec_fn=preexec)
    socket_path = identify_new_socket(proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, uid)
    return proc, socket_path

def identify_new_socket(proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, matching_uid=0):
    #wait until the new socket appears:
    start = monotonic_time()
    match_display_name = None
    if display_name:
        match_display_name = "server.display=%s" % display_name
    from xpra.platform.paths import get_nodock_command
    while monotonic_time()-start<WAIT_SERVER_TIMEOUT and (proc is None or proc.poll() in (None, 0)):
        sockets = set(dotxpra.socket_paths(check_uid=matching_uid, matching_state=dotxpra.LIVE, matching_display=matching_display))
        new_sockets = list(sockets-existing_sockets)
        for socket_path in new_sockets:
            #verify that this is the right server:
            try:
                #we must use a subprocess to avoid messing things up - yuk
                cmd = get_nodock_command()+["info", "socket:%s" % socket_path]
                p = Popen(cmd, stdin=None, stdout=PIPE, stderr=PIPE)
                stdout, _ = p.communicate()
                if p.returncode==0:
                    try:
                        out = stdout.decode('utf-8')
                    except:
                        try:
                            out = stdout.decode()
                        except:
                            from xpra.os_util import bytestostr
                            out = bytestostr(stdout)
                    PREFIX = "env.XPRA_PROXY_START_UUID="
                    for line in out.splitlines():
                        if line.startswith(PREFIX):
                            info_uuid = line[len(PREFIX):]
                            if info_uuid==new_server_uuid:
                                #found it!
                                return socket_path
                        if match_display_name and match_display_name==line:
                            #found it
                            return socket_path
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
        start_child = strip_defaults_start_child(opts.start_child, defaults.start_child)
        start = strip_defaults_start_child(opts.start, defaults.start)
        proc, socket_path = start_server_subprocess(script_file, args, server_mode, defaults,
                                                     opts.socket_dir, opts.socket_dirs,
                                                     start, start_child, opts.exit_with_children, opts.exit_with_client,
                                                     getuid(), getgid())
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
    no_gtk()

    def show_final_state(exit_code, display_desc):
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
            if final_state is DotXpra.LIVE:
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

    display_desc = pick_display(error_cb, opts, extra_args)
    conn = connect_or_fail(display_desc, opts)
    app = None
    e = 1
    try:
        if mode=="stop":
            from xpra.client.gobject_client_base import StopXpraClient
            app = StopXpraClient((conn, display_desc), opts)
        elif mode=="exit":
            from xpra.client.gobject_client_base import ExitXpraClient
            app = ExitXpraClient((conn, display_desc), opts)
        else:
            raise Exception("invalid mode: %s" % mode)
        e = app.run()
    finally:
        if app:
            app.cleanup()
    if e==0:
        if display_desc["local"]:
            show_final_state(app.exit_code, display_desc)
        else:
            print("Sent shutdown command")
    return  e


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

def run_mdns_gui(error_cb, opts, extra_args):
    from xpra.net.mdns import get_listener_class
    listener = get_listener_class()
    if not listener:
        error_cb("sorry, 'mdns-gui' is not supported on this platform yet")
    from xpra.client.gtk_base.mdns_gui import main
    main()

def run_list_mdns(error_cb, opts, extra_args):
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
    from xpra.log import Logger
    log = Logger("util")
    from xpra.util import nonl
    d = dict_to_validated_config({})
    fixup_options(d)
    #this one is normally only probed at build time:
    #(so probe it here again)
    if os.name=="posix":
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
                       "exit-with-children", "start-new-commands", "start", "start-child"]
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
            return ", ".join(vstr(x) for x in v)
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
