#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=import-outside-toplevel

import sys
import shlex
import os.path
import optparse

from xpra.version_util import full_version_str
from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED, CAN_DAEMONIZE
from xpra.util import envbool, csv, parse_simple_dict, DEFAULT_PORT, DEFAULT_PORTS
from xpra.os_util import getuid, WIN32, OSX, POSIX
from xpra.scripts.config import (
    OPTION_TYPES, FALSE_OPTIONS,
    InitException, InitInfo, InitExit,
    fixup_debug_option, fixup_options,
    make_defaults_struct, parse_bool, print_number,
    validate_config, has_sound_support, name_to_field,
    )


MODE_ALIAS = {
    "seamless"  : "start",
    "desktop"   : "start-desktop",
    }

def enabled_str(v, true_str="yes", false_str="no") -> str:
    if v:
        return true_str
    return false_str

def enabled_or_auto(v):
    return bool_or(v, None, true_str="yes", false_str="no", other_str="auto")

def bool_or(v, other_value, true_str, false_str, other_str):
    vs = str(v).lower()
    if vs==str(other_value).lower():
        return other_str
    bv = parse_bool("", v)
    return enabled_str(bv, true_str, false_str)

def sound_option(v):
    vl = v.lower()
    #ensures we return only: "on", "off" or "disabled" given any value
    if vl=="no":
        vl = "disabled"
    return bool_or(vl, "disabled", "on", "off", "disabled")


def _stderr_write(msg):
    #use this function to print warnings
    #we must write to stderr to prevent
    #the output from interfering when running as proxy over ssh
    #(which uses stdin / stdout as communication channel)
    try:
        sys.stderr.write(msg+"\n")
        sys.stderr.flush()
        return True
    except OSError:
        return False

def info(msg):
    if not _stderr_write(msg) and POSIX:
        import syslog
        syslog.syslog(syslog.LOG_INFO, msg)

def warn(msg):
    if not _stderr_write(msg) and POSIX:
        import syslog
        syslog.syslog(syslog.LOG_WARNING, msg)

def error(msg):
    if not _stderr_write(msg) and POSIX:
        import syslog
        syslog.syslog(syslog.LOG_ERR, msg)


supports_proxy  = True
supports_shadow = SHADOW_SUPPORTED
supports_server = LOCAL_SERVERS_SUPPORTED
if supports_server:
    try:
        from xpra.x11.bindings.wait_for_x_server import wait_for_x_server    #@UnresolvedImport @UnusedImport
    except ImportError:
        supports_server = False
try:
    from xpra.net import mdns
    supports_mdns = bool(mdns)
except ImportError:
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


def parse_env(env) -> dict:
    d = {}
    for ev in env:
        try:
            if ev.startswith("#"):
                continue
            v = ev.split("=", 1)
            if len(v)!=2:
                warn("Warning: invalid environment option '%s'" % ev)
                continue
            d[v[0]] = os.path.expandvars(v[1])
        except Exception as e:
            warn("Warning: cannot parse environment option '%s':" % ev)
            warn(" %s" % e)
    return d


def parse_URL(url):
    from urllib.parse import urlparse, parse_qs
    up = urlparse(url)
    address = up.netloc
    qpos = url.find("?")
    options = {}
    if qpos>0:
        params_str = url[qpos+1:]
        params = parse_qs(params_str, keep_blank_values=True)
        f_params = {}
        for k,v in params.items():
            t = OPTION_TYPES.get(k)
            if t is not None and t!=list:
                v = v[0]
            f_params[k] = v
        options = validate_config(f_params)
    scheme = up.scheme
    if scheme.startswith("xpra+"):
        scheme = scheme[len("xpra+"):]
    if scheme in ("tcp", "ssl", "ssh", "ws", "wss"):
        address = "%s://%s" % (scheme, address)
    return address, options


def _sep_pos(display_name):
    #split the display name on ":" or "/"
    scpos = display_name.find(":")
    slpos = display_name.find("/")
    if scpos<0:
        return slpos
    if slpos<0:
        return scpos
    return min(scpos, slpos)

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
        desc_tmp = {}
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
            port_str = hostport_match.group("port")
            try:
                desc_tmp["proxy_port"] = int(port_str)
            except ValueError:
                raise RuntimeError("bad format: proxy port '%s' is not a number" % port_str) from None
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
        from xpra.log import Logger
        sshlog = Logger("ssh")
        sshlog.error("bad proxy argument: " + reout.group(0))
        return display_name, {}
    else:
        # rip out the part we've processed
        display_name = display_name[:reout.start()] + display_name[reout.end():]
        return display_name, desc_tmp

def parse_remote_display(s):
    if not s:
        return {}
    qpos = s.find("?")
    cpos = s.find(",")
    display = None
    options_str = None
    if qpos>=0 and (qpos<cpos or cpos<0):
        #query string format, ie: "DISPLAY?key1=value1&key2=value2#extra_stuff
        attr_sep = "&"
        parts = s.split("?", 1)
        s = parts[0].split("#")[0]
        options_str = parts[1]
    elif cpos>0 and (cpos<qpos or qpos<0):
        #csv string format,
        # ie: DISPLAY,key1=value1,key2=value2
        # or: key1=value1,key2=value2
        attr_sep = ","
        parts = s.split(",", 1)
        if parts[0].find("=")>0:
            #if the first part is a key=value,
            #assume it is part of the parameters
            parts = ["", s]
            display = ""
        if len(parts)==2:
            options_str = parts[1]
    elif s.find("=")>0:
        #ie: just one key=value
        #(so this is not a display)
        display = ""
        attr_sep = ","
        parts = ["", s]
        options_str = parts[1]
    else:
        parts = []
    if display is None:
        try:
            assert [int(x) for x in s.split(".")]   #ie: ":10.0" -> [10, 0]
            display = ":" + s       #ie: ":10.0"
        except ValueError:
            display = s             #ie: "tcp://somehost:10000/"
    desc = {
        "display"   : display,
        "display_as_args"   : [display],
        }
    if options_str:
        #parse extra attributes
        d = parse_simple_dict(options_str, attr_sep)
        for k,v in d.items():
            if k in desc:
                warn("Warning: cannot override '%s' with URI" % k)
            else:
                desc[k] = v
    return desc

def parse_username_and_password(s):
    ppos = s.find(":")
    if ppos>=0:
        password = s[ppos+1:]
        username = s[:ppos]
    else:
        username = s
        password = ""
    #fugly: we override the command line option after parsing the string:
    desc = {}
    if username:
        desc["username"] = username
    if password:
        desc["password"] = password
    return desc

def parse_host_string(host, default_port=DEFAULT_PORT):
    """
        Parses [username[:password]@]host[:port]
        and returns username, password, host, port
        missing arguments will be empty (username and password) or 0 (port)
    """
    upos = host.rfind("@")
    if upos>=0:
        #HOST=username@host
        desc = parse_username_and_password(host[:upos])
        host = host[upos+1:]
    else:
        desc = {}
    port_str = None
    if host.count(":")>=2:
        #more than 2 ":", assume this is IPv6:
        if host.startswith("["):
            #if we have brackets, we can support: "[HOST]:SSHPORT"
            epos = host.find("]")
            if epos<0:
                raise ValueError("invalid host format, expected IPv6 [..]")
            port_str = host[epos+1:]        #ie: ":22"
            if port_str.startswith(":"):
                port_str = port_str[1:]     #ie: "22"
            host = host[1:epos]            #ie: "[HOST]"
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
            raise ValueError("invalid port number specified: %s" % port_str) from None
    else:
        port = default_port
    if port<=0 or port>=2**16:
        raise ValueError("invalid port number: %s" % port)
    desc.update({
        "host"  : host or "127.0.0.1",
        "port"  : port,
        "local" : is_local(host),
        })
    return desc

def load_password_file(password_file):
    if not password_file:
        return None
    if not os.path.exists(password_file):
        warn("Error: password file '%s' does not exist:\n" % password_file)
        return None
    try:
        with open(password_file, "rb") as f:
            return f.read()
    except Exception as e:
        warn("Error: failed to read the password file '%s':\n" % password_file)
        warn(" %s\n" % e)
    return None


def parse_display_name(error_cb, opts, display_name, find_session_by_name=False):
    if WIN32:
        from xpra.platform.win32.dotxpra import PIPE_PREFIX # pragma: no cover
    else:
        PIPE_PREFIX = None
    if display_name.startswith("/") and POSIX:
        display_name = "socket://"+display_name

    desc = {"display_name" : display_name}
    display_name, proxy_attrs = parse_proxy_attributes(display_name)
    desc.update(proxy_attrs)

    pos = _sep_pos(display_name)
    if pos<0 or (display_name and display_name[0] in "0123456789"):
        match = None
        if POSIX:
            #maybe this is just the display number without the ":" prefix?
            try:
                if pos>0:
                    display_name = ":%i" % int(display_name[:pos])
                else:
                    display_name = ":%i" % int(display_name)
                match = True
            except ValueError:
                pass
        elif WIN32: # pragma: no cover
            display_name = "named-pipe://%s%s" % (PIPE_PREFIX, display_name)
            match = True
        if find_session_by_name and not match:
            #try to find a session whose "session-name" matches:
            match = find_session_by_name(opts, display_name)
            if match:
                display_name = match
    #display_name may have been updated, re-parse it:
    pos = _sep_pos(display_name)
    if pos<0:
        error_cb("unknown format for display name: %s" % display_name)
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
    elif protocol=="rfb":
        protocol = "vnc"
    if psep not in (":", "/", "://"):
        error_cb("unknown format for protocol separator '%s' in display name: %s" % (psep, display_name))
    afterproto = display_name[pos:]         #ie: "host:port/DISPLAY"
    separator = psep[-1]                    #ie: "/"
    parts = afterproto.split(separator, 1)     #ie: "host:port", "DISPLAY"

    def _set_password():
        password = desc.get("password")
        if password is None and opts.password_file is not None and len(opts.password_file)>0:
            password = load_password_file(opts.password_file[0])
            if password:
                desc["password"] = password
        if password:
            opts.password = password

    def _set_username():
        username = desc.get("username")
        if username:
            opts.username = username

    def _parse_username_and_password(s):
        d = parse_username_and_password(s)
        desc.update(d)
        _set_username()
        _set_password()

    def _parse_host_string(host, default_port=DEFAULT_PORT):
        d = parse_host_string(host, default_port)
        desc.update(d)
        _set_username()
        _set_password()

    def _parse_remote_display(s):
        d = parse_remote_display(s)
        desc.update(d)
        opts.display = desc.get("display")

    if protocol in ("ssh", "vnc+ssh"):
        desc.update({
                "type"             : protocol,
                "proxy_command"    : ["_proxy"],
                "exit_ssh"         : opts.exit_ssh,
                "display"          : None,
                "display_as_args"  : [],
                 })
        #desc["proxy_command"] = ["_proxy" if protocol=="ssh" else "_proxy_vnc"]
        host = parts[0]
        if len(parts)>1:
            _parse_remote_display(parts[1])
            if protocol=="vnc+ssh":
                #use a vnc display string with the proxy command
                #and specify the vnc port if we know the display number:
                vnc_uri = "vnc://localhost"
                if opts.display:
                    try:
                        vnc_port = 5900+int(opts.display.lstrip(":"))
                        desc["remote_port"] = vnc_port
                    except ValueError:
                        vnc_uri += "/"
                    else:
                        vnc_uri += ":%i/" % vnc_port
                desc["display_as_args"] = [vnc_uri]
        #ie: ssh=["/usr/bin/ssh", "-v"]
        ssh = parse_ssh_string(opts.ssh)
        full_ssh = ssh[:]

        #maybe restrict to win32 only?
        ssh_cmd = ssh[0].lower()
        is_putty = ssh_cmd.endswith("plink") or ssh_cmd.endswith("plink.exe")
        is_paramiko = ssh_cmd.split(":")[0]=="paramiko"
        if is_paramiko:
            ssh[0] = "paramiko"
            desc["is_paramiko"] = is_paramiko
            if opts.ssh.find(":")>0:
                desc["paramiko-config"] = parse_simple_dict(opts.ssh.split(":", 1)[1])
        if is_putty:
            desc["is_putty"] = True

        _parse_host_string(host, 22)
        ssh_port = desc.pop("port", 22)
        if ssh_port!=22:
            desc["port"] = ssh_port
        username = desc.get("username")
        password = desc.get("password")
        host = desc.get("host")
        key = desc.get("key", None)
        full_ssh += add_ssh_args(username, password, host, ssh_port, key, is_putty, is_paramiko)
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
        return desc

    if protocol=="socket":
        assert not WIN32, "unix-domain sockets are not supported on MS Windows"
        #use the socketfile specified:
        slash = afterproto.find("/")
        if 0<afterproto.find(":")<slash:
            #ie: username:password/run/user/1000/xpra/hostname-number
            #remove username and password prefix:
            _parse_username_and_password(afterproto[:slash])
            sockfile = afterproto[slash:]
        elif afterproto.find("@")>=0:
            #ie: username:password@/run/user/1000/xpra/hostname-number
            parts = afterproto.split("@")
            _parse_username_and_password("@".join(parts[:-1]))
            sockfile = parts[-1]
        else:
            sockfile = afterproto
        desc.update({
                "type"          : "unix-domain",
                "local"         : True,
                "socket_dir"    : os.path.basename(sockfile),
                "socket_dirs"   : opts.socket_dirs,
                "socket_path"   : sockfile,
                })
        opts.display = None
        return desc

    if display_name.startswith(":"):
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

    if protocol in ("tcp", "ssl", "ws", "wss", "vnc"):
        desc["type"] = protocol
        if len(parts) not in (1, 2, 3):
            error_cb("invalid %s connection string,\n" % protocol
                     +" use %s://[username[:password]@]host[:port][/display]\n" % protocol)
        #display (optional):
        if separator=="/" and len(parts)==2:
            _parse_remote_display(parts[-1])
            parts = parts[:-1]
        host = ":".join(parts)
        default_port = DEFAULT_PORTS.get(protocol, DEFAULT_PORT)
        _parse_host_string(host, default_port)
        return desc

    if protocol=="vsock":
        #use the vsock specified:
        cid, iport = parse_vsock(parts[0])
        desc.update({
                "type"          : "vsock",
                "local"         : False,
                "display"       : display_name,
                "vsock"         : (cid, iport),
                })
        opts.display = display_name
        return desc

    if WIN32 or display_name.startswith("named-pipe:"):   # pragma: no cover
        if afterproto.find("@")>=0:
            parts = afterproto.split("@")
            _parse_username_and_password("@".join(parts[:-1]))
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

    error_cb("unknown format for display name: %s" % display_name)


def parse_ssh_string(ssh_setting):
    ssh_cmd = shlex.split(ssh_setting, posix=not WIN32)
    if ssh_cmd[0]=="auto":
        #try paramiko:
        try:
            from xpra.log import is_debug_enabled, Logger
            from xpra.net.ssh import nogssapi_context
            with nogssapi_context():
                import paramiko
            assert paramiko
            ssh_cmd = ["paramiko"]
            if is_debug_enabled("ssh"):
                Logger("ssh").info("using paramiko ssh backend")
        except ImportError as e:
            if is_debug_enabled("ssh"):
                Logger("ssh").info("no paramiko: %s" % e)
            from xpra.platform.features import DEFAULT_SSH_COMMAND
            ssh_cmd = shlex.split(DEFAULT_SSH_COMMAND)
    return ssh_cmd


def add_ssh_args(username, password, host, ssh_port, key, is_putty=False, is_paramiko=False):
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
        if key:
            key_path = os.path.abspath(key)
            if WIN32 and is_putty:
                # tortoise plink works with either slash, backslash needs too much escaping
                # because of the weird way it's passed through as a ProxyCommand
                key_path = "\"" + key.replace("\\", "/") + "\""     # pragma: no cover
            args += ["-i", key_path]
    return args

def add_ssh_proxy_args(username, password, host, ssh_port, pkey, ssh, is_putty=False, is_paramiko=False):
    args = []
    proxyline = ssh
    if is_putty:
        proxyline += ["-nc", "%host:%port"]
    elif not is_paramiko:
        proxyline += ["-W", "%h:%p"]
    # the double quotes are in case the password has something like "&"
    proxyline += add_ssh_args(username, password, host, ssh_port, pkey, is_putty, is_paramiko)
    if is_putty:
        args += ["-proxycmd", " ".join(proxyline)]
    elif not is_paramiko:
        args += ["-o", "ProxyCommand " + " ".join(proxyline)]
    return args


def get_server_modes():
    server_modes = []
    if supports_server:
        server_modes.append("start")
        server_modes.append("start-desktop")
        server_modes.append("upgrade")
    if supports_shadow:
        server_modes.append("shadow")
    return server_modes


def get_subcommands():
    return tuple(x.split(" ")[0] for x in get_usage())


def get_usage():
    command_options = [""]
    if supports_server:
        command_options += ["start [DISPLAY]",
                           "start-desktop [DISPLAY]",
                           "upgrade [DISPLAY]",
                           "upgrade-desktop [DISPLAY]",
                           "recover [DISPLAY]",
                           ]
    if supports_shadow:
        command_options.append("shadow [DISPLAY]")

    command_options += [
                        "attach [DISPLAY]",
                        "detach [DISPLAY]",
                        "info [DISPLAY]",
                        "id [DISPLAY]",
                        "version [DISPLAY]",
                        "stop [DISPLAY]",
                        "exit [DISPLAY]",
                        "clean [DISPLAY1] [DISPLAY2]..",
                        "clean-sockets [DISPLAY]",
                        "clean-displays [DISPLAY]",
                        "screenshot filename [DISPLAY]",
                        "control DISPLAY command [arg1] [arg2]..",
                        "print DISPLAY filename",
                        "shell [DISPLAY]",
                        "showconfig",
                        "list",
                        "list-sessions",
                        "list-windows",
                        "sessions",
                        "launcher",
                        "gui",
                        "start-gui",
                        "bug-report",
                        "toolbox",
                        "displays",
                        "docs",
                        "html5",
                        "autostart",
                        "encoding",
                        "path-info",
                      ]
    if supports_mdns:
        command_options.append("list-mdns")
        command_options.append("mdns-gui")
    return command_options

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

    version = "xpra v%s" % full_version_str()
    usage_strs = ["\t%%prog %s\n" % x for x in get_usage()]
    if not supports_server:
        usage_strs = ["(this xpra installation does not support starting local servers)\n"]+usage_strs
    parser = ModifiedOptionParser(version=version, usage="\n" + "".join(usage_strs))
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
                " or ".join(["'%s'" % x for x in get_server_modes()]))
    parser.add_option_group(group)
    #we support remote start, so we need those even if we don't have server support:
    def dcsv(v):
        return csv(v or ["none"])
    group.add_option("--start", action="append",
                      dest="start", metavar="CMD", default=list(defaults.start or []),
                      help="program to spawn in server (may be repeated). Default: %s." % dcsv(defaults.start))
    group.add_option("--start-late", action="append",
                      dest="start_late", metavar="CMD", default=list(defaults.start_late or []),
                      help="program to spawn in server once initialization is complete (may be repeated). Default: %s." % dcsv(defaults.start_late))
    group.add_option("--start-child", action="append",
                      dest="start_child", metavar="CMD", default=list(defaults.start_child or []),
                      help="program to spawn in server,"
                      +" taken into account by the exit-with-children option"
                      +" (may be repeated to run multiple commands)."
                      +" Default: %s." % dcsv(defaults.start_child))
    group.add_option("--start-child-late", action="append",
                      dest="start_child_late", metavar="CMD", default=list(defaults.start_child_late or []),
                      help="program to spawn in server once initialization is complete"
                      +" taken into account by the exit-with-children option"
                      +" (may be repeated to run multiple commands)."
                      +" Default: %s." % dcsv(defaults.start_child_late))
    group.add_option("--start-after-connect", action="append",
                      dest="start_after_connect", default=defaults.start_after_connect,
                      help="program to spawn in server after the first client has connected (may be repeated)."
                      +" Default: %s." % dcsv(defaults.start_after_connect))
    group.add_option("--start-child-after-connect", action="append",
                      dest="start_child_after_connect", default=defaults.start_child_after_connect,
                      help="program to spawn in server after the first client has connected,"
                      +" taken into account by the exit-with-children option"
                      +" (may be repeated to run multiple commands)."
                      +" Default: %s." % dcsv(defaults.start_child_after_connect))
    group.add_option("--start-on-connect", action="append",
                      dest="start_on_connect", default=defaults.start_on_connect,
                      help="program to spawn in server every time a client connects (may be repeated)."
                      +" Default: %s." % dcsv(defaults.start_on_connect))
    group.add_option("--start-child-on-connect", action="append",
                      dest="start_child_on_connect", default=defaults.start_child_on_connect,
                      help="program to spawn in server every time a client connects,"
                      +" taken into account by the exit-with-children option (may be repeated)."
                      +" Default: %s." % dcsv(defaults.start_child_on_connect))
    group.add_option("--start-on-last-client-exit", action="append",
                      dest="start_on_last_client_exit", default=defaults.start_on_last_client_exit,
                      help="program to spawn in server every time a client disconnects"
                      +" and there are no other clients left (may be repeated)."
                      +" Default: %s." % dcsv(defaults.start_on_last_client_exit))
    group.add_option("--start-child-on-last-client-exit", action="append",
                      dest="start_child_on_last_client_exit", default=defaults.start_child_on_last_client_exit,
                      help="program to spawn in server every time a client disconnects"
                      +" and there are no other clients left,"
                      +" taken into account by the exit-with-children option (may be repeated)."
                      +" Default: %s." % dcsv(defaults.start_child_on_last_client_exit))
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
                      help="Allows clients to execute new commands on the server."
                      +" Default: %s." % enabled_str(defaults.start_new_commands))
    legacy_bool_parse("start-via-proxy")
    group.add_option("--start-via-proxy", action="store", metavar="yes|no|auto",
                      dest="start_via_proxy", default=defaults.start_via_proxy,
                      help="Start servers via the system proxy server. Default: %default.")
    legacy_bool_parse("proxy-start-sessions")
    group.add_option("--proxy-start-sessions", action="store", metavar="yes|no",
                      dest="proxy_start_sessions", default=defaults.proxy_start_sessions,
                      help="Allows proxy servers to start new sessions on demand."
                      +" Default: %s." % enabled_str(defaults.proxy_start_sessions))
    group.add_option("--dbus-launch", action="store",
                      dest="dbus_launch", metavar="CMD", default=defaults.dbus_launch,
                      help="Start the session within a dbus-launch context,"
                      +" leave empty to turn off. Default: %default.")
    group.add_option("--source", action="append",
                      dest="source", default=list(defaults.source or []),
                      help="Script to source into the server environment. Default: %s." % csv(
                          ("'%s'" % x) for x in (defaults.source or []) if not x.startswith("#")))
    group.add_option("--source-start", action="append",
                      dest="source_start", default=list(defaults.source_start or []),
                      help="Script to source into the environment used for starting commands. Default: %s." % csv(
                          ("'%s'" % x) for x in (defaults.source_start or []) if not x.startswith("#")))
    group.add_option("--start-env", action="append",
                      dest="start_env", default=list(defaults.start_env or []),
                      help="Define environment variables used with 'start-child' and 'start',"
                      +" can be specified multiple times. Default: %s." % csv(
                          ("'%s'" % x) for x in (defaults.start_env or []) if not x.startswith("#")))
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
        group.add_option("--http-scripts", action="store",
                          dest="http_scripts", default=defaults.http_scripts,
                          metavar="off|all|SCRIPTS",
                          help="Enable the builtin web server scripts. Default: '%default'.")
    else:
        ignore({"tcp_proxy" : "",
                "html"      : ""})
    legacy_bool_parse("daemon")
    legacy_bool_parse("attach")
    if POSIX and getuid()==0:
        group.add_option("--uid", action="store",
                          dest="uid", default=defaults.uid,
                          help="The user id to change to when the server is started by root."
                          +" Default: %s." % defaults.uid)
        group.add_option("--gid", action="store",
                          dest="gid", default=defaults.gid,
                          help="The group id to change to when the server is started by root."
                          +" Default: %s." % defaults.gid)
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
                      help="Attach a client as soon as the server has started"
                      +" (default: %s)" % enabled_or_auto(defaults.attach))

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
    group.add_option("--file-size-limit", action="store", metavar="SIZE",
                      dest="file_size_limit", default=defaults.file_size_limit,
                      help="Maximum size of file transfers. Default: %s." % defaults.file_size_limit)
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

    legacy_bool_parse("exit-with-client")
    if (supports_server or supports_shadow):
        group.add_option("--exit-with-client", action="store", metavar="yes|no",
                          dest="exit_with_client", default=defaults.exit_with_client,
                          help="Terminate the server when the last client disconnects."
                          +" Default: %s" % enabled_str(defaults.exit_with_client))
    else:
        ignore({"exit_with_client" : defaults.exit_with_client})
    group.add_option("--idle-timeout", action="store",
                      dest="idle_timeout", type="int", default=defaults.idle_timeout,
                      help="Disconnects the client when idle (0 to disable)."
                      +" Default: %s seconds" % defaults.idle_timeout)
    group.add_option("--server-idle-timeout", action="store",
                      dest="server_idle_timeout", type="int", default=defaults.server_idle_timeout,
                      help="Exits the server when idle (0 to disable)."
                      +" Default: %s seconds" % defaults.server_idle_timeout)
    legacy_bool_parse("fake-xinerama")
    legacy_bool_parse("use-display")
    if supports_server:
        group.add_option("--use-display", action="store", metavar="yes|no|auto",
                          dest="use_display", default=defaults.use_display,
                          help="Use an existing display rather than starting one with the xvfb command."
                          +" Default: %s" % enabled_str(defaults.use_display))
        group.add_option("--xvfb", action="store",
                          dest="xvfb",
                          default=defaults.xvfb,
                          metavar="CMD",
                          help="How to run the headless X server. Default: '%default'.")
        group.add_option("--displayfd", action="store", metavar="FD",
                          dest="displayfd", default=defaults.displayfd,
                          help="The xpra server will write the display number back on this file descriptor"
                          +" as a newline-terminated string.")
        group.add_option("--fake-xinerama", action="store", metavar="path|auto|no",
                          dest="fake_xinerama",
                          default=defaults.fake_xinerama,
                          help="Setup fake xinerama support for the session. "+
                          "You can specify the path to the libfakeXinerama.so library or a boolean."
                          +" Default: %s." % enabled_str(defaults.fake_xinerama))
    else:
        ignore({
            "use-display"   : defaults.use_display,
            "xvfb"          : defaults.xvfb,
            "displayfd"     : defaults.displayfd,
            "fake-xinerama" : defaults.fake_xinerama,
            })
    group.add_option("--resize-display", action="store",
                      dest="resize_display", default=defaults.resize_display, metavar="yes|no|widthxheight",
                      help="Whether the server display should be resized to match the client resolution."
                      +" Default: %s." % enabled_str(defaults.resize_display))
    defaults_bind = defaults.bind
    if supports_server or supports_shadow:
        group.add_option("--bind", action="append",
                          dest="bind", default=[],
                          metavar="SOCKET",
                          help="Listen for connections over %s." % ("named pipes" if WIN32 else "unix domain sockets")
                          +" You may specify this option multiple times to listen on different locations."
                          +" Default: %s" % dcsv(defaults_bind))
        group.add_option("--bind-tcp", action="append",
                          dest="bind_tcp", default=list(defaults.bind_tcp or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over TCP."
                          + " Use --tcp-auth to secure it."
                          + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-ws", action="append",
                          dest="bind_ws", default=list(defaults.bind_ws or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over Websocket."
                          + " Use --ws-auth to secure it."
                          + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-wss", action="append",
                          dest="bind_wss", default=list(defaults.bind_wss or []),
                          metavar="[HOST]:[PORT]",
                          help="Listen for connections over HTTPS / wss (secure Websocket)."
                          + " Use --wss-auth to secure it."
                          + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-ssl", action="append",
                          dest="bind_ssl", default=list(defaults.bind_ssl or []),
                          metavar="[HOST]:PORT",
                          help="Listen for connections over SSL."
                          + " Use --ssl-auth to secure it."
                          + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-ssh", action="append",
                          dest="bind_ssh", default=list(defaults.bind_ssh or []),
                          metavar="[HOST]:PORT",
                          help="Listen for connections using SSH transport."
                          + " Use --ssh-auth to secure it."
                          + " You may specify this option multiple times with different host and port combinations")
        group.add_option("--bind-rfb", action="append",
                          dest="bind_rfb", default=list(defaults.bind_rfb or []),
                          metavar="[HOST]:PORT",
                          help="Listen for RFB connections."
                          + " Use --rfb-auth to secure it."
                          + " You may specify this option multiple times with different host and port combinations")
    else:
        ignore({
            "bind"      : defaults.bind,
            "bind-tcp"  : defaults.bind_tcp,
            "bind-ws"   : defaults.bind_ws,
            "bind-wss"  : defaults.bind_wss,
            "bind-ssl"  : defaults.bind_ssl,
            "bind-ssh"  : defaults.bind_ssh,
            "bind-rfb"  : defaults.bind_rfb,
            })
    try:
        from xpra.net import vsock
    except ImportError:
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
                      help="Start a pulseaudio server for the session."
                      +" Default: %s." % enabled_or_auto(defaults.pulseaudio))
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
                      help="Allows the server to be controlled via its dbus interface."
                      + " Default: %s." % enabled_str(defaults.dbus_control))
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
                      help="Limit the bandwidth used. The value is specified in bits per second,"
                      +" use the value '0' to disable restrictions. Default: '%default'.")
    legacy_bool_parse("bandwidth-detection")
    group.add_option("--bandwidth-detection", action="store",
                      dest="bandwidth_detection", default=defaults.bandwidth_detection,
                      help="Automatically detect runtime bandwidth limits. Default: '%default'.")
    replace_option("--readwrite", "--readonly=no")
    replace_option("--readonly", "--readonly=yes")
    group.add_option("--readonly", action="store", metavar="yes|no",
                      dest="readonly", default=defaults.readonly,
                      help="Disable keyboard input and mouse events from the clients. "
                      +" Default: %s." % enabled_str(defaults.readonly))
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
                      help="Mouse wheel forwarding, can be used to disable the device ('no') or invert some axes "
                      "('invert-all', 'invert-x', invert-y', 'invert-z')."
                      +" Default: %s." % defaults.mousewheel)
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
        group.add_option("--xsettings", action="store", metavar="auto|yes|no",
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
                      help="Allow more than one client to connect to the same session. "
                      +" Default: %s." % enabled_or_auto(defaults.sharing))
    legacy_bool_parse("lock")
    group.add_option("--lock", action="store", metavar="yes|no",
                      dest="lock", default=defaults.lock,
                      help="Prevent sessions from being taken over by new clients. "
                      +" Default: %s." % enabled_or_auto(defaults.lock))
    legacy_bool_parse("remote-logging")
    group.add_option("--remote-logging", action="store", metavar="no|send|receive|both",
                      dest="remote_logging", default=defaults.remote_logging,
                      help="Forward all the client's log output to the server. "
                      +" Default: %s." % enabled_str(defaults.remote_logging))
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
                          help="Specifies which sound system to use to capture the sound stream "
                          +" (use 'help' for options)")
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
                      help="Specify which encodings are allowed. Default: %s." % dcsv(defaults.encodings))
    group.add_option("--encoding", action="store",
                      metavar="ENCODING", default=defaults.encoding,
                      dest="encoding", type="str",
                      help="Which image compression algorithm to use, specify 'help' to get a list of options."
                            " Default: %default."
                      )
    group.add_option("--video-encoders", action="append",
                      dest="video_encoders", default=[],
                      help="Specify which video encoders to enable, to get a list of all the options specify 'help'")
    group.add_option("--proxy-video-encoders", action="append",
                      dest="proxy_video_encoders", default=[],
                      help="Specify which video encoders to enable when running a proxy server,"
                      +" to get a list of all the options specify 'help'")
    group.add_option("--csc-modules", action="append",
                      dest="csc_modules", default=[],
                      help="Specify which colourspace conversion modules to enable,"
                      +" to get a list of all the options specify 'help'. Default: %s." % dcsv(defaults.csc_modules))
    group.add_option("--video-decoders", action="append",
                      dest="video_decoders", default=[],
                      help="Specify which video decoders to enable,"
                      +" to get a list of all the options specify 'help'")
    group.add_option("--video-scaling", action="store",
                      metavar="SCALING",
                      dest="video_scaling", type="str", default=defaults.video_scaling,
                      help="How much automatic video downscaling should be used,"
                      +" from 1 (rarely) to 100 (aggressively), 0 to disable."
                      +" Default: %default.")
    group.add_option("--min-quality", action="store",
                      metavar="MIN-LEVEL",
                      dest="min_quality", type="int", default=defaults.min_quality,
                      help="Sets the minimum encoding quality allowed in automatic quality setting,"
                      +" from 1 to 100, 0 to leave unset."
                      +" Default: %default.")
    group.add_option("--quality", action="store",
                      metavar="LEVEL",
                      dest="quality", type="int", default=defaults.quality,
                      help="Use a fixed image compression quality - only relevant for lossy encodings,"
                      +" from 1 to 100, 0 to use automatic setting."
                      +" Default: %default.")
    group.add_option("--min-speed", action="store",
                      metavar="SPEED",
                      dest="min_speed", type="int", default=defaults.min_speed,
                      help="Sets the minimum encoding speed allowed in automatic speed setting,"
                      "from 1 to 100, 0 to leave unset. Default: %default.")
    group.add_option("--speed", action="store",
                      metavar="SPEED",
                      dest="speed", type="int", default=defaults.speed,
                      help="Use image compression with the given encoding speed,"
                      +" from 1 to 100, 0 to use automatic setting."
                      +" Default: %default.")
    group.add_option("--auto-refresh-delay", action="store",
                      dest="auto_refresh_delay", type="float", default=defaults.auto_refresh_delay,
                      metavar="DELAY",
                      help="Idle delay in seconds before doing an automatic lossless refresh."
                      + " 0.0 to disable."
                      + " Default: %default.")
    group.add_option("--compressors", action="store",
                      dest="compressors", default=csv(defaults.compressors),
                      help="The packet compressors to enable. Default: %s." % dcsv(defaults.compressors))
    group.add_option("--packet-encoders", action="store",
                      dest="packet_encoders", default=csv(defaults.packet_encoders),
                      help="The packet encoders to enable. Default: %s." % dcsv(defaults.packet_encoders))
    replace_option("--compression-level", "--compression_level")
    replace_option("--compress", "--compression_level")
    group.add_option("-z", "--compression_level", action="store",
                      dest="compression_level", type="int", default=defaults.compression_level,
                      metavar="LEVEL",
                      help="How hard to work on compressing packet data."
                      + " You generally do not need to use this option,"
                      + " the default value should be adequate,"
                      + " picture data is compressed separately (see --encoding)."
                      + " 0 to disable compression,"
                      + " 9 for maximal (slowest) compression. Default: %default.")

    group = optparse.OptionGroup(parser, "Client Features Options",
                "These options control client features that affect the appearance or the keyboard.")
    parser.add_option_group(group)
    legacy_bool_parse("reconnect")
    group.add_option("--reconnect", action="store", metavar="yes|no",
                      dest="reconnect", default=defaults.reconnect,
                      help="Reconnect to the server. Default: %s." % enabled_or_auto(defaults.reconnect))
    legacy_bool_parse("opengl")
    group.add_option("--opengl", action="store", metavar="(yes|no|auto)[:backends]",
                      dest="opengl", default=defaults.opengl,
                      help="Use OpenGL accelerated rendering. Default: %s." % defaults.opengl)
    legacy_bool_parse("splash")
    group.add_option("--splash", action="store", metavar="yes|no|auto",
                      dest="splash", default=defaults.splash,
                      help="Show a splash screen whilst loading the client. Default: %s." % enabled_or_auto(defaults.splash))
    legacy_bool_parse("headerbar")
    group.add_option("--headerbar", action="store", metavar="auto|no|force",
                      dest="headerbar", default=defaults.headerbar,
                      help="Add a headerbar with menu to decorated windows. Default: %s." % defaults.headerbar)
    legacy_bool_parse("windows")
    group.add_option("--windows", action="store", metavar="yes|no",
                      dest="windows", default=defaults.windows,
                      help="Forward windows. Default: %s." % enabled_str(defaults.windows))
    group.add_option("--session-name", action="store",
                      dest="session_name", default=defaults.session_name,
                      help="The name of this session, which may be used in notifications, menus, etc. Default: 'Xpra'.")
    group.add_option("--min-size", action="store",
                      dest="min_size", default=defaults.min_size,
                      metavar="MIN_SIZE",
                      help="The minimum size for normal decorated windows, ie: 100x20. Default: '%default'.")
    group.add_option("--max-size", action="store",
                      dest="max_size", default=defaults.max_size,
                      metavar="MAX_SIZE",
                      help="The maximum size for normal windows, ie: 800x600. Default: '%default'.")
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
                      help="Make the window fullscreen if it is from a desktop or shadow server,"
                      +" scaling it to fit the screen."
                      +" Default: '%default'.")
    group.add_option("--border", action="store",
                      dest="border", default=defaults.border,
                      help="The border to draw inside xpra windows to distinguish them from local windows."
                        "Format: color[,size]. Default: '%default'")
    group.add_option("--title", action="store",
                      dest="title", default=defaults.title,
                      help="Text which is shown as window title, may use remote metadata variables."
                      +" Default: '%default'.")
    group.add_option("--window-close", action="store",
                          dest="window_close", default=defaults.window_close,
                          help="The action to take when a window is closed by the client."
                          +" Valid options are: 'forward', 'ignore', 'disconnect'."
                          +" Default: '%default'.")
    group.add_option("--window-icon", action="store",
                          dest="window_icon", default=defaults.window_icon,
                          help="Path to the default image which will be used for all windows"
                          +" (the application may override this)")
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
                          help="Enable Xpra's own system tray menu%s." % extra_text
                          +" Default: %s" % enabled_str(defaults.tray))
        do_legacy_bool_parse(cmdline, "delay-tray")
        parser.add_option("--delay-tray", action="store", metavar="yes|no",
                          dest="delay_tray", default=defaults.delay_tray,
                          help="Waits for the first events before showing the system tray%s." % extra_text
                          +" Default: %s" % enabled_str(defaults.delay_tray))
    group.add_option("--tray-icon", action="store",
                          dest="tray_icon", default=defaults.tray_icon,
                          help="Path to the image which will be used as icon for the system-tray or dock")
    group.add_option("--shortcut-modifiers", action="store",
                      dest="shortcut_modifiers", type="str", default=defaults.shortcut_modifiers,
                      help="Default set of modifiers required by the key shortcuts. Default %default.")
    group.add_option("--key-shortcut", action="append",
                      dest="key_shortcut", default=defaults.key_shortcut or [],
                      help="Define key shortcuts that will trigger specific actions."
                      + "If no shortcuts are defined, it defaults to: \n%s" % ("\n ".join(defaults.key_shortcut or ())))
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
                      help="Whether to enable SSL on TCP sockets and for what purpose (requires 'ssl-cert')."
                      +" Default: '%s'."  % enabled_str(defaults.ssl))
    group.add_option("--ssl-key", action="store",
                      dest="ssl_key", default=defaults.ssl_key,
                      help="Key file to use."
                      +" Default: '%default'.")
    group.add_option("--ssl-cert", action="store",
                      dest="ssl_cert", default=defaults.ssl_cert,
                      help="Certifcate file to use."
                      +" Default: '%default'.")
    group.add_option("--ssl-protocol", action="store",
                      dest="ssl_protocol", default=defaults.ssl_protocol,
                      help="Specifies which version of the SSL protocol to use."+
                      " Default: '%default'.")
    group.add_option("--ssl-ca-certs", action="store",
                      dest="ssl_ca_certs", default=defaults.ssl_ca_certs,
                      help="The ca_certs file contains a set of concatenated 'certification authority' certificates,"
                      +" or you can set this to a directory containing CAs files."+
                      " Default: '%default'.")
    group.add_option("--ssl-ca-data", action="store",
                      dest="ssl_ca_data", default=defaults.ssl_ca_data,
                      help="PEM or DER encoded certificate data, optionally converted to hex."
                      +" Default: '%default'.")
    group.add_option("--ssl-ciphers", action="store",
                      dest="ssl_ciphers", default=defaults.ssl_ciphers,
                      help="Sets the available ciphers, "
                      +" it should be a string in the OpenSSL cipher list format."
                      +" Default: '%default'.")
    group.add_option("--ssl-client-verify-mode", action="store",
                      dest="ssl_client_verify_mode", default=defaults.ssl_client_verify_mode,
                      help="Whether to try to verify the client's certificates"
                      +" and how to behave if verification fails."
                      +" Default: '%default'.")
    group.add_option("--ssl-server-verify-mode", action="store",
                      dest="ssl_server_verify_mode", default=defaults.ssl_server_verify_mode,
                      help="Whether to try to verify the server's certificates"
                      +" and how to behave if verification fails. "
                      +" Default: '%default'.")
    group.add_option("--ssl-verify-flags", action="store",
                      dest="ssl_verify_flags", default=defaults.ssl_verify_flags,
                      help="The flags for certificate verification operations."
                      +" Default: '%default'.")
    group.add_option("--ssl-check-hostname", action="store", metavar="yes|no",
                      dest="ssl_check_hostname", default=defaults.ssl_check_hostname,
                      help="Whether to match the peer cert's hostname or accept any host, dangerous."
                      +" Default: '%s'." % enabled_str(defaults.ssl_check_hostname))
    group.add_option("--ssl-server-hostname", action="store", metavar="hostname",
                      dest="ssl_server_hostname", default=defaults.ssl_server_hostname,
                      help="The server hostname to match."
                      +" Default: '%default'.")
    group.add_option("--ssl-options", action="store", metavar="options",
                      dest="ssl_options", default=defaults.ssl_options,
                      help="Set of SSL options enabled on this context."
                      +" Default: '%default'.")

    group = optparse.OptionGroup(parser, "Advanced Options",
                "These options apply to both client and server. Please refer to the man page for details.")
    parser.add_option_group(group)
    group.add_option("--env", action="append",
                      dest="env", default=list(defaults.env or []),
                      help="Define environment variables which will apply to this process and all subprocesses,"
                      +" can be specified multiple times."
                      +" Default: %s." % csv(
                          ("'%s'" % x) for x in (defaults.env or []) if not x.startswith("#")))
    group.add_option("--challenge-handlers", action="append",
                      dest="challenge_handlers", default=[],
                      help="Which handlers to use for processing server authentication challenges."
                      +" Default: %s." % csv(defaults.challenge_handlers))
    group.add_option("--password-file", action="append",
                      dest="password_file", default=defaults.password_file,
                      help="The file containing the password required to connect"
                      +" (useful to secure TCP mode)."
                      +" Default: %s." % csv(defaults.password_file))
    group.add_option("--forward-xdg-open", action="store",
                      dest="forward_xdg_open", default=defaults.forward_xdg_open,
                      help="Intercept calls to xdg-open and forward them to the client."
                      +" Default: '%default'.")
    group.add_option("--open-command", action="store",
                      dest="open_command", default=defaults.open_command,
                      help="Command to use to open files and URLs."
                      +" Default: '%default'.")
    legacy_bool_parse("modal-windows")
    group.add_option("--modal-windows", action="store",
                      dest="modal_windows", default=defaults.modal_windows,
                      help="Honour modal windows."
                      +" Default: '%default'.")
    group.add_option("--input-method", action="store",
                      dest="input_method", default=defaults.input_method,
                      help="Which X11 input method to configure for client applications started with start or"
                      + "start-child (Default: '%default', options: auto, none, keep, xim, IBus, SCIM, uim)")
    group.add_option("--dpi", action="store",
                      dest="dpi", default=defaults.dpi,
                      help="The 'dots per inch' value that client applications should try to honour,"
                      +" from 10 to 1000 or 0 for automatic setting."
                      +" Default: %s." % print_number(defaults.dpi))
    group.add_option("--pixel-depth", action="store",
                      dest="pixel_depth", default=defaults.pixel_depth,
                      help="The bits per pixel of the virtual framebuffer when starting a server"
                      +" (8, 16, 24 or 30), or for rendering when starting a client. "
                      +" Default: %s." % (defaults.pixel_depth or "0 (auto)"))
    group.add_option("--sync-xvfb", action="store",
                      dest="sync_xvfb", default=defaults.sync_xvfb,
                      help="How often to synchronize the virtual framebuffer used for X11 seamless servers "
                      +"(0 to disable)."
                      +" Default: %s." % defaults.sync_xvfb)
    group.add_option("--client-socket-dirs", action="store",
                      dest="client_socket_dirs", default=defaults.client_socket_dirs,
                      help="Directories where the clients create their control socket."
                      +" Default: %s." % os.path.pathsep.join("'%s'" % x for x in defaults.client_socket_dirs))
    group.add_option("--socket-dirs", action="store",
                      dest="socket_dirs", default=defaults.socket_dirs,
                      help="Directories to look for the socket files in."
                      +" Default: %s." % os.path.pathsep.join("'%s'" % x for x in defaults.socket_dirs))
    default_socket_dir_str = defaults.socket_dir or "$XPRA_SOCKET_DIR or the first valid directory in socket-dirs"
    group.add_option("--socket-dir", action="store",
                      dest="socket_dir", default=defaults.socket_dir,
                      help="Directory to place/look for the socket files in. Default: '%s'." % default_socket_dir_str)
    group.add_option("--system-proxy-socket", action="store",
                      dest="system_proxy_socket", default=defaults.system_proxy_socket,
                      help="The socket path to use to contact the system-wide proxy server. Default: '%default'.")
    group.add_option("--sessions-dir", action="store",
                      dest="sessions_dir", default=defaults.sessions_dir,
                      help="Directory to place/look for the sessions files in. Default: '%s'." % defaults.sessions_dir)
    group.add_option("--ssh-upgrade", action="store",
                      dest="ssh_upgrade", default=defaults.ssh_upgrade,
                      help="Upgrade TCP sockets to handle SSH connections. Default: '%default'.")
    group.add_option("--rfb-upgrade", action="store",
                      dest="rfb_upgrade", default=defaults.rfb_upgrade,
                      help="Upgrade TCP sockets to send a RFB handshake after this delay"
                      +" (in seconds). Default: '%default'.")
    group.add_option("-d", "--debug", action="store",
                      dest="debug", default=defaults.debug, metavar="FILTER1,FILTER2,...",
                      help="List of categories to enable debugging for"
                      +" (you can also use \"all\" or \"help\", default: '%default')")
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
                      help="The authentication module to use (default: %s)" % dcsv(defaults.auth))
    group.add_option("--tcp-auth", action="append",
                      dest="tcp_auth", default=list(defaults.tcp_auth or []),
                      help="The authentication module to use for TCP sockets (default: %s)" % dcsv(defaults.tcp_auth))
    group.add_option("--ws-auth", action="append",
                      dest="ws_auth", default=list(defaults.ws_auth or []),
                      help="The authentication module to use for Websockets (default: %s)" % dcsv(defaults.ws_auth))
    group.add_option("--wss-auth", action="append",
                      dest="wss_auth", default=list(defaults.wss_auth or []),
                      help="The authentication module to use for Secure Websockets (default: %s)" % dcsv(defaults.wss_auth))
    group.add_option("--ssl-auth", action="append",
                      dest="ssl_auth", default=list(defaults.ssl_auth or []),
                      help="The authentication module to use for SSL sockets (default: %s)" % dcsv(defaults.ssl_auth))
    group.add_option("--ssh-auth", action="append",
                      dest="ssh_auth", default=list(defaults.ssh_auth or []),
                      help="The authentication module to use for SSH sockets (default: %s)" % dcsv(defaults.ssh_auth))
    group.add_option("--rfb-auth", action="append",
                      dest="rfb_auth", default=list(defaults.rfb_auth or []),
                      help="The authentication module to use for RFB sockets (default: %s)" % dcsv(defaults.rfb_auth))
    if vsock:
        group.add_option("--vsock-auth", action="append",
                         dest="vsock_auth", default=list(defaults.vsock_auth or []),
                         help="The authentication module to use for vsock sockets (default: '%s')" % dcsv(defaults.vsock_auth))
    else:
        ignore({"vsock-auth" : defaults.vsock_auth})
    group.add_option("--min-port", action="store",
                      dest="min_port", default=defaults.min_port,
                      help="The minimum port number allowed when creating TCP sockets (default: '%default')")
    ignore({"password"           : defaults.password})
    if POSIX:
        group.add_option("--mmap-group", action="store",
                          dest="mmap_group", default=defaults.mmap_group,
                          help="When creating the mmap file with the client,"
                          +" set the group permission on the mmap file to this group,"
                          +" use the special value 'auto' to use the same value as the owner"
                          +" of the server socket file we connect to (default: '%default')")
        group.add_option("--socket-permissions", action="store",
                          dest="socket_permissions", default=defaults.socket_permissions,
                          help="When creating the server unix domain socket,"
                          +" what file access mode to use (default: '%default')")
    else:
        ignore({"mmap-group"            : defaults.mmap_group,
                "socket-permissions"    : defaults.socket_permissions,
                })

    replace_option("--enable-pings", "--pings=5")
    group.add_option("--pings", action="store", metavar="yes|no",
                      dest="pings", default=defaults.pings,
                      help="How often to send ping packets (in seconds, use zero to disable)."
                      +" Default: %s." % defaults.pings)
    group.add_option("--clipboard-filter-file", action="store",
                      dest="clipboard_filter_file", default=defaults.clipboard_filter_file,
                      help="Name of a file containing regular expressions of clipboard contents "
                      +" that must be filtered out")
    group.add_option("--local-clipboard", action="store",
                      dest="local_clipboard", default=defaults.local_clipboard,
                      metavar="SELECTION",
                      help="Name of the local clipboard selection to be synchronized"
                      +" when using the translated clipboard (default: %default)")
    group.add_option("--remote-clipboard", action="store",
                      dest="remote_clipboard", default=defaults.remote_clipboard,
                      metavar="SELECTION",
                      help="Name of the remote clipboard selection to be synchronized"
                      +" when using the translated clipboard (default: %default)")
    group.add_option("--remote-xpra", action="store",
                      dest="remote_xpra", default=defaults.remote_xpra,
                      metavar="CMD",
                      help="How to run xpra on the remote host."
                      +" (Default: %s)" % (" or ".join(defaults.remote_xpra)))
    group.add_option("--encryption", action="store",
                      dest="encryption", default=defaults.encryption,
                      metavar="ALGO",
                      help="Specifies the encryption cipher to use,"
                      +" specify 'help' to get a list of options. (default: None)")
    group.add_option("--encryption-keyfile", action="store",
                      dest="encryption_keyfile", default=defaults.encryption_keyfile,
                      metavar="FILE",
                      help="Specifies the file containing the encryption key."
                      +" (Default: '%default')")
    group.add_option("--tcp-encryption", action="store",
                      dest="tcp_encryption", default=defaults.tcp_encryption,
                      metavar="ALGO",
                      help="Specifies the encryption cipher to use for TCP sockets,"
                      +" specify 'help' to get a list of options. (default: None)")
    group.add_option("--tcp-encryption-keyfile", action="store",
                      dest="tcp_encryption_keyfile", default=defaults.tcp_encryption_keyfile,
                      metavar="FILE",
                      help="Specifies the file containing the encryption key to use for TCP sockets."
                      +" (default: '%default')")

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
    options.debug = fixup_debug_option(options.debug)
    if options.debug:
        categories = options.debug.split(",")
        for cat in categories:
            if cat=="help":
                h = []
                from xpra.log import STRUCT_KNOWN_FILTERS
                for category, d in STRUCT_KNOWN_FILTERS.items():
                    h.append("%s:" % category)
                    for k,v in d.items():
                        h.append(" * %-16s: %s" % (k,v))
                raise InitInfo("known logging filters: \n%s" % "\n".join(h))
    if options.sound_source=="help":
        from xpra.sound.gstreamer_util import NAME_TO_INFO_PLUGIN
        try:
            from xpra.sound.wrapper import query_sound
            source_plugins = query_sound().strtupleget("sources", ())
            source_default = query_sound().strget("source.default", "")
        except Exception as e:
            raise InitInfo(e) from None
        if source_plugins:
            raise InitInfo("The following audio capture plugins may be used (default: %s):\n" % source_default+
                           "\n".join([" * "+p.ljust(16)+NAME_TO_INFO_PLUGIN.get(p, "") for p in source_plugins]))
        raise InitInfo("No audio capture plugins found!")

    #only use the default bind option if the user hasn't specified one on the command line:
    if not options.bind:
        #use the default:
        options.bind = defaults_bind

    #only use the default challenge-handlers if the user hasn't specified any:
    if not options.challenge_handlers:
        options.challenge_handlers = defaults.challenge_handlers

    #only use the default key-shortcut list if the user hasn't specified one:
    if not options.key_shortcut:
        options.key_shortcut = defaults.key_shortcut

    #special handling for URL mode:
    #xpra attach xpra://[mode:]host:port/?param1=value1&param2=value2
    if len(args)==2 and args[0]=="attach":
        URL_MODES = {
            "xpra"      : "tcp",
            "xpras"     : "ssl",
            "xpra+tcp"  : "tcp",
            "xpratcp"   : "tcp",
            "xpra+tls"  : "ssl",
            "xpratls"   : "ssl",
            "xpra+ssl"  : "ssl",
            "xprassl"   : "ssl",
            "xpra+ssh"  : "ssh",
            "xprassh"   : "ssh",
            "xpra+ws"   : "ws",
            "xpraws"    : "ws",
            "xpra+wss"  : "wss",
            "xprawss"   : "wss",
            }
        for prefix, mode in URL_MODES.items():
            url = args[1]
            fullprefix = "%s://" % prefix
            if url.startswith(fullprefix):
                url = "%s://%s" % (mode, url[len(fullprefix):])
                address, params = parse_URL(url)
                for k,v in validate_config(params).items():
                    setattr(options, k.replace("-", "_"), v)
                #replace with our standard URL format,
                #ie: tcp://host:port
                args[1] = address
                break

    NEED_ENCODING_MODES = (
        "attach",
        "start", "seamless",
        "start-desktop", "desktop",
        "upgrade", "upgrade-seamless", "upgrade-desktop",
        "recover",
        "shadow", "proxy",
        "listen", "launcher",
        "bug-report", "encoding", "gui-info",
        )
    fixup_options(options, defaults, skip_encodings=len(args)==0 or
                  MODE_ALIAS.get(args[0], args[0]) not in NEED_ENCODING_MODES)

    for x in ("dpi", "sync_xvfb"):
        try:
            s = getattr(options, x, None)
            if x=="sync_xvfb" and (s or "").lower() in FALSE_OPTIONS:
                v = 0
            else:
                v = int(s)
            setattr(options, x, v)
        except Exception as e:
            raise InitException("invalid value for %s: '%s': %s" % (x, s, e)) from None

    def parse_window_size(v, attribute="max-size"):
        def pws_fail():
            raise InitException("invalid %s: %s" % (attribute, v))
        try:
            #split on "," or "x":
            pv = tuple(int(x.strip()) for x in v.replace(",", "x").split("x", 1))
        except ValueError:
            pws_fail()
        if len(pv)!=2:
            pws_fail()
        w, h = pv
        if w<0 or h<0 or w>=32768 or h>=32768:
            pws_fail()
        return w, h
    if options.min_size:
        options.min_size = "%sx%s" % parse_window_size(options.min_size, "min-size")
    if options.max_size:
        options.max_size = "%sx%s" % parse_window_size(options.max_size, "max-size")
    if options.encryption_keyfile and not options.encryption:
        from xpra.net.crypto import DEFAULT_MODE
        options.encryption = "AES-%s" % DEFAULT_MODE
    if options.tcp_encryption_keyfile and not options.tcp_encryption:
        from xpra.net.crypto import DEFAULT_MODE  # @Reimport
        options.tcp_encryption = "AES-%s" % DEFAULT_MODE
    return options, args

def validated_encodings(encodings):
    try:
        from xpra.codecs.codec_constants import PREFERRED_ENCODING_ORDER
    except ImportError:
        return []
    lower_encodings = [x.lower() for x in encodings]
    validated = [x for x in PREFERRED_ENCODING_ORDER if x.lower() in lower_encodings]
    if not validated:
        raise InitException("no valid encodings specified")
    return validated

def validate_encryption(opts):
    do_validate_encryption(opts.auth, opts.tcp_auth,
                           opts.encryption, opts.tcp_encryption, opts.encryption_keyfile, opts.tcp_encryption_keyfile)

def do_validate_encryption(auth, tcp_auth,
                           encryption, tcp_encryption, encryption_keyfile, tcp_encryption_keyfile):
    if not encryption and not tcp_encryption:
        #don't bother initializing anything
        return
    from xpra.net.crypto import crypto_backend_init
    crypto_backend_init()
    env_key = os.environ.get("XPRA_ENCRYPTION_KEY")
    pass_key = os.environ.get("XPRA_PASSWORD")
    from xpra.net.crypto import ENCRYPTION_CIPHERS, MODES, DEFAULT_MODE
    if not ENCRYPTION_CIPHERS:
        raise InitException("cannot use encryption: no ciphers available (the python-cryptography library must be installed)")
    if encryption=="help" or tcp_encryption=="help":
        raise InitInfo("the following encryption ciphers are available: %s" % csv(ENCRYPTION_CIPHERS))
    enc, mode = ((encryption or tcp_encryption)+"-").split("-")[:2]
    if not mode:
        mode = DEFAULT_MODE
    if enc:
        if enc not in ENCRYPTION_CIPHERS:
            raise InitException("encryption %s is not supported, try: %s" % (enc, csv(ENCRYPTION_CIPHERS)))
        if mode not in MODES:
            raise InitException("encryption mode %s is not supported, try: %s" % (mode, csv(MODES)))
        if encryption and not encryption_keyfile and not env_key and not auth:
            raise InitException("encryption %s cannot be used without an authentication module or keyfile"
                                +" (see --encryption-keyfile option)" % encryption)
        if tcp_encryption and not tcp_encryption_keyfile and not env_key and not tcp_auth:
            raise InitException("tcp-encryption %s cannot be used " % tcp_encryption+
                                "without a tcp authentication module or keyfile "
                                +" (see --tcp-encryption-keyfile option)")
    if pass_key and env_key and pass_key==env_key:
        raise InitException("encryption and authentication should not use the same value")
    #discouraged but not illegal:
    #if password_file and encryption_keyfile and password_file==encryption_keyfile:
    #    if encryption:
    #        raise InitException("encryption %s should not use the same file"
    #                            +" as the password authentication file" % encryption)
    #    elif tcp_encryption:
    #        raise InitException("tcp-encryption %s should not use the same file"
    #                            +" as the password authentication file" % tcp_encryption)

def show_sound_codec_help(is_server, speaker_codecs, microphone_codecs):
    from xpra.sound.wrapper import query_sound
    props = query_sound()
    if not props:
        return ["sound is not supported - gstreamer not present or not accessible"]
    codec_help = []
    all_speaker_codecs = props.strtupleget("encoders" if is_server else "decoders")
    invalid_sc = [x for x in speaker_codecs if x not in all_speaker_codecs]
    hs = "help" in speaker_codecs
    if hs:
        codec_help.append("speaker codecs available: %s" % csv(all_speaker_codecs))
    elif invalid_sc:
        codec_help.append("WARNING: some of the specified speaker codecs are not available: %s" % csv(invalid_sc))

    all_microphone_codecs = props.strtupleget("decoders" if is_server else "encoders")
    invalid_mc = [x for x in microphone_codecs if x not in all_microphone_codecs]
    hm = "help" in microphone_codecs
    if hm:
        codec_help.append("microphone codecs available: %s" % csv(all_microphone_codecs))
    elif invalid_mc:
        codec_help.append("WARNING: some of the specified microphone codecs are not available:"
                          +" %s" % csv(invalid_mc))
    return codec_help


def parse_vsock(vsock_str):
    from xpra.net.vsock import STR_TO_CID, CID_ANY, PORT_ANY    #@UnresolvedImport pylint: disable=import-outside-toplevel
    if not vsock_str.find(":")>=0:
        raise InitException("invalid vsocket format '%s'" % vsock_str)
    cid_str, port_str = vsock_str.split(":", 1)
    if cid_str.lower() in ("auto", "any"):
        cid = CID_ANY
    else:
        try:
            cid = int(cid_str)
        except ValueError:
            cid = STR_TO_CID.get(cid_str.upper())  # @UndefinedVariable
            if cid is None:
                raise InitException("invalid vsock cid '%s'" % cid_str) from None
    if port_str.lower() in ("auto", "any"):
        iport = PORT_ANY
    else:
        try:
            iport = int(port_str)
        except ValueError:
            raise InitException("invalid vsock port '%s'" % port_str) from None
    return cid, iport


def is_local(host) -> bool:
    return host.lower() in ("localhost", "127.0.0.1", "::1")
