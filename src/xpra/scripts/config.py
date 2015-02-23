#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os

#this is here so we can expose the "platform" module
#before we import xpra.platform
import platform as python_platform
assert python_platform
from xpra.util import AdHocStruct

def warn(msg):
    sys.stderr.write(msg+"\n")

def debug(*args):
    #can be overriden
    pass

DEFAULT_XPRA_CONF_FILENAME = os.environ.get("XPRA_CONF_FILENAME", 'xpra.conf')
DEFAULT_NET_WM_NAME = os.environ.get("XPRA_NET_WM_NAME", "Xpra")


ENCRYPTION_CIPHERS = []
try:
    from Crypto.Cipher import AES
    assert AES
    ENCRYPTION_CIPHERS.append("AES")
except:
    pass

try:
    import xpra.sound
    has_sound_support = bool(xpra.sound)
except:
    has_sound_support = False


def OpenGL_safety_check():
    #Ubuntu 12.04 will just crash on you if you try:
    distro = ""
    if hasattr(python_platform, "linux_distribution"):
        distro = python_platform.linux_distribution()
    if distro and len(distro)==3 and distro[0]=="Ubuntu":
        ur = distro[1]  #ie: "12.04"
        try:
            rnum = [int(x) for x in ur.split(".")]  #ie: [12, 4]
            if rnum<=[12, 4]:
                return "Ubuntu %s is too buggy" % ur
        except:
            pass
    #try to detect VirtualBox:
    #based on the code found here:
    #http://spth.virii.lu/eof2/articles/WarGame/vboxdetect.html
    #because it used to cause hard VM crashes when we probe the GL driver!
    try:
        from ctypes import cdll
        if cdll.LoadLibrary("VBoxHook.dll"):
            return "VirtualBox is present (VBoxHook.dll)"
    except:
        pass
    try:
        try:
            f = None
            f = open("\\\\.\\VBoxMiniRdrDN", "r")
        finally:
            if f:
                f.close()
                return True, "VirtualBox is present (VBoxMiniRdrDN)"
    except Exception as e:
        import errno
        if e.args[0]==errno.EACCES:
            return "VirtualBox is present (VBoxMiniRdrDN)"
    return None
OPENGL_DEFAULT = None       #will auto-detect by probing
if OpenGL_safety_check() is not None:
    OPENGL_DEFAULT = False


def get_build_info():
    info = []
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS             #@UnresolvedImport
        try:
            mods = int(LOCAL_MODIFICATIONS)
        except:
            mods = 0
        if mods==0:
            info.append("revision %s" % REVISION)
        else:
            info.append("revision %s with %s local changes" % (REVISION, LOCAL_MODIFICATIONS))
    except Exception as e:
        warn("Error: could not find the source information: %s" % e)
    try:
        from xpra.build_info import BUILT_BY, BUILT_ON, BUILD_DATE, CYTHON_VERSION, COMPILER_VERSION    #@UnresolvedImport
        info.append("Built on %s by %s" % (BUILT_ON, BUILT_BY))
        if BUILD_DATE:
            info.append(BUILD_DATE)
        if CYTHON_VERSION!="unknown" or COMPILER_VERSION!="unknown":
            info.append("")
        if CYTHON_VERSION!="unknown":
            info.append("built with Cython %s" % CYTHON_VERSION)
        if COMPILER_VERSION!="unknown":
            info.append(COMPILER_VERSION)
    except Exception as e:
        warn("Error: could not find the build information: %s" % e)
    return info


def name_to_field(name):
    return name.replace("-", "_")

def save_config(conf_file, config, keys, extras_types={}):
    with open(conf_file, "w") as f:
        option_types = OPTION_TYPES.copy()
        option_types.update(extras_types)
        saved = {}
        for key in keys:
            assert key in option_types, "invalid configuration key: %s" % key
            v = getattr(config, name_to_field(key))
            saved[key] = v
            f.write("%s=%s%s" % (key, v, os.linesep))
        debug("save_config: saved %s to %s", saved, conf_file)

def read_config(conf_file):
    """
        Parses a config file into a dict of strings.
        If the same key is specified more than once,
        the value for this key will be an array of strings.
    """
    d = {}
    if not os.path.isfile(conf_file):
        debug("read_config(%s) is not a file!", conf_file)
        return d
    with open(conf_file, "rU") as f:
        lines = []
        no = 0
        for line in f:
            sline = line.strip().rstrip('\r\n').strip()
            no += 1
            if len(sline) == 0:
                debug("%4s empty line", no)
                continue
            if sline[0] in ( '!', '#' ):
                debug("%4s skipping comments   : %s", no, sline[:16]+"..")
                continue
            debug("%4s loaded              : %s", no, sline)
            lines.append(sline)
    debug("loaded %s lines", len(lines))
    #aggregate any lines with trailing backslash
    agg_lines = []
    l = ""
    for line in lines:
        if line.endswith("\\"):
            l += line[:-1]
        else:
            l += line
            agg_lines.append(l)
            l = ""
    if len(l)>0:
        #last line had a trailing backslash... meh
        agg_lines.append(l)
    debug("loaded %s aggregated lines", len(agg_lines))
    #parse name=value pairs:
    for sline in agg_lines:
        if sline.find("=")<=0:
            debug("skipping line which is missing an equal sign: %s", sline)
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
            debug("added to: %s='%s'", name, d[name])
        else:
            debug("assigned (new): %s='%s'", name, value)
            d[name] = value
    return  d

def read_xpra_conf(conf_dir, xpra_conf_filename=DEFAULT_XPRA_CONF_FILENAME):
    """
        Reads an <xpra_conf_filename> file from the given directory,
        returns a dict with values as strings and arrays of strings.
    """
    debug("read_xpra_conf(%s, %s)", conf_dir, xpra_conf_filename)
    cdir = os.path.expanduser(conf_dir)
    d = {}
    if not os.path.exists(cdir) or not os.path.isdir(cdir):
        debug("invalid config directory: %s", cdir)
        return  d
    conf_file = os.path.join(cdir, xpra_conf_filename)
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        debug("config file does not exist: %s", conf_file)
        return  d
    return read_config(conf_file)

def read_xpra_defaults():
    """
        Reads the global <xpra_conf_filename> from the <conf_dir>
        and then the user-specific one.
        (the latter overrides values from the former)
        returns a dict with values as strings and arrays of strings.
        If the <conf_dir> is not specified, we figure out its location.
    """
    from xpra.platform.paths import get_default_conf_dir, get_system_conf_dir, get_user_conf_dir
    # load config files in this order (the later ones override earlier ones):
    # * application defaults   (ie: "/Volumes/Xpra/Xpra.app/Contents/Resources/" on OSX)
    #                          (ie: "C:\Program Files\Xpra\" on win32)
    #                          (ie: None on others)
    # * system defaults        (ie: "/etc/xpra" on Posix - not on OSX)
    #                          (ie: "/Library/Application Support/Xpra" on OSX)
    #                          (ie: "C:\Documents and Settings\All Users\Application Data\Xpra" with XP)
    #                          (ie: "C:\ProgramData\Xpra" with Vista onwards)
    # * user config            (ie: "~/.xpra/" on all Posix, including OSX)
    #                          (ie: "C:\Documents and Settings\Username\Application Data\Xpra" with XP)
    #                          (ie: "C:\Users\<user name>\AppData\Roaming" with Visa onwards)
    dirs = [get_default_conf_dir(), get_system_conf_dir(), get_user_conf_dir()]
    defaults = {}
    for d in dirs:
        if not d:
            continue
        ad = os.path.expanduser(d)
        if not os.path.exists(ad):
            debug("read_xpra_defaults: skipping %s", ad)
            continue
        defaults.update(read_xpra_conf(ad))
        debug("read_xpra_defaults: updated defaults with %s", ad)
    return defaults


OPTIONS_VALIDATION = {}

OPTION_TYPES = {
                    #string options:
                    "encoding"          : str,
                    "title"             : str,
                    "username"          : str,
                    "auth"              : str,
                    "tcp-auth"          : str,
                    "wm-name"           : str,
                    "remote-xpra"       : str,
                    "session-name"      : str,
                    "dock-icon"         : str,
                    "tray-icon"         : str,
                    "window-icon"       : str,
                    "password-file"     : str,
                    "clipboard-filter-file" : str,
                    "pulseaudio-command": str,
                    "encryption"        : str,
                    "encryption_keyfile": str,
                    "mode"              : str,
                    "ssh"               : str,
                    "xvfb"              : str,
                    "socket-dir"        : str,
                    "log-file"          : str,
                    "border"            : str,
                    "max-size"          : str,
                    "window-layout"     : str,
                    "display"           : str,
                    "tcp-proxy"         : str,
                    "download-path"     : str,
                    "open-command"      : str,
                    "lpadmin"           : str,
                    "debug"             : str,
                    "input-method"      : str,
                    "microphone"        : str,
                    "speaker"           : str,
                    "sound-source"      : str,
                    "socket-permissions": str,
                    #int options:
                    "quality"           : int,
                    "min-quality"       : int,
                    "speed"             : int,
                    "min-speed"         : int,
                    "compression_level" : int,
                    "dpi"               : int,
                    "scaling"           : int,
                    "file-size-limit"   : int,
                    "idle-timeout"      : int,
                    #float options:
                    "auto-refresh-delay": float,
                    #boolean options:
                    "daemon"            : bool,
                    "use-display"       : bool,
                    "displayfd"         : bool,
                    "fake-xinerama"     : bool,
                    "tray"              : bool,
                    "clipboard"         : bool,
                    "pulseaudio"        : bool,
                    "dbus-proxy"        : bool,
                    "mmap"              : bool,
                    "mmap-group"        : bool,
                    "readonly"          : bool,
                    "keyboard-sync"     : bool,
                    "pings"             : bool,
                    "cursors"           : bool,
                    "bell"              : bool,
                    "notifications"     : bool,
                    "xsettings"         : bool,
                    "system-tray"       : bool,
                    "sharing"           : bool,
                    "delay-tray"        : bool,
                    "windows"           : bool,
                    "exit-with-children": bool,
                    "exit-with-client"  : bool,
                    "exit-ssh"          : bool,
                    "opengl"            : bool,
                    "mdns"              : bool,
                    "file-transfer"     : bool,
                    "printing"          : bool,
                    "open-files"        : bool,
                    "swap-keys"         : bool,
                    "start-new-commands": bool,
                    "remote-logging"    : bool,
                    #arrays of strings:
                    "encodings"         : list,
                    "video-encoders"    : list,
                    "csc-modules"       : list,
                    "video-decoders"    : list,
                    "speaker-codec"     : list,
                    "microphone-codec"  : list,
                    "compressors"       : list,
                    "packet-encoders"   : list,
                    "key-shortcut"      : list,
                    "start"             : list,
                    "start-child"       : list,
                    "bind-tcp"          : list,
                    "env"               : list,
               }

GLOBAL_DEFAULTS = None
#lowest common denominator here
#(the xpra.conf file shipped is generally better tuned than this - especially for 'xvfb')
def get_defaults():
    global GLOBAL_DEFAULTS
    if GLOBAL_DEFAULTS is not None:
        return GLOBAL_DEFAULTS
    from xpra.platform.features import DEFAULT_SSH_CMD, DOWNLOAD_PATH, OPEN_COMMAND, DEFAULT_PULSEAUDIO_COMMAND, DEFAULT_XVFB_COMMAND
    try:
        from xpra.platform.info import get_username
        username = get_username()
    except:
        username = ""
    GLOBAL_DEFAULTS = {
                    "encoding"          : "",
                    "title"             : "@title@ on @client-machine@",
                    "username"          : username,
                    "auth"              : "",
                    "tcp-auth"          : "",
                    "wm-name"           : DEFAULT_NET_WM_NAME,
                    "remote-xpra"       : "~/.xpra/run-xpra",
                    "session-name"      : "",
                    "dock-icon"         : "",
                    "tray-icon"         : "",
                    "window-icon"       : "",
                    "password-file"     : "",
                    "clipboard-filter-file" : "",
                    "pulseaudio-command": DEFAULT_PULSEAUDIO_COMMAND,
                    "encryption"        : "",
                    "encryption_keyfile": "",
                    "ssh"               : DEFAULT_SSH_CMD,
                    "xvfb"              : DEFAULT_XVFB_COMMAND,
                    "socket-dir"        : "",
                    "log-file"          : "$DISPLAY.log",
                    "border"            : "auto,0",
                    "max-size"          : "",
                    "window-layout"     : "",
                    "display"           : "",
                    "tcp-proxy"         : "",
                    "download-path"     : DOWNLOAD_PATH,
                    "open-command"      : OPEN_COMMAND,
                    "lpadmin"           : "lpadmin",
                    "debug"             : "",
                    "input-method"      : "none",
                    "sound-source"      : "",
                    "html"              : "",
                    "socket-permissions": "660",
                    "quality"           : 0,
                    "min-quality"       : 30,
                    "speed"             : 0,
                    "min-speed"         : 0,
                    "compression_level" : 1,
                    "dpi"               : 0,
                    "scaling"           : 1,
                    "file-size-limit"   : 10,
                    "idle-timeout"      : 0,
                    "auto-refresh-delay": 0.25,
                    "daemon"            : True,
                    "use-display"       : False,
                    "displayfd"         : False,
                    "fake-xinerama"     : True,
                    "tray"              : True,
                    "clipboard"         : True,
                    "pulseaudio"        : True,
                    "dbus-proxy"        : os.name=="posix" and not sys.platform.startswith("darwin"),
                    "mmap"              : True,
                    "mmap-group"        : False,
                    "speaker"           : ["disabled", "on"][has_sound_support],
                    "microphone"        : ["disabled", "off"][has_sound_support],
                    "readonly"          : False,
                    "keyboard-sync"     : True,
                    "pings"             : False,
                    "cursors"           : True,
                    "bell"              : True,
                    "notifications"     : True,
                    "xsettings"         : os.name=="posix",
                    "system-tray"       : True,
                    "sharing"           : False,
                    "delay-tray"        : False,
                    "windows"           : True,
                    "exit-with-children": False,
                    "exit-with-client"  : False,
                    "start-new-commands": False,
                    "remote-logging"    : sys.platform.startswith("win") or sys.platform.startswith("darwin"),
                    "exit-ssh"          : True,
                    "opengl"            : OPENGL_DEFAULT,
                    "mdns"              : False,
                    "file-transfer"     : True,
                    "printing"          : True,
                    "open-files"        : False,
                    "swap-keys"         : sys.platform.startswith("darwin"),    #only used on osx
                    "encodings"         : ["all"],
                    "video-encoders"    : ["all"],
                    "csc-modules"       : ["all"],
                    "video-decoders"    : ["all"],
                    "speaker-codec"     : [],
                    "microphone-codec"  : [],
                    "compressors"       : ["all"],
                    "packet-encoders"   : ["all"],
                    "key-shortcut"      : [
                                           "Meta+Shift+F2:show_start_new_command",
                                           "Meta+Shift+F4:quit",
                                           "Meta+Shift+F8:magic_key",
                                           "Meta+Shift+F11:show_session_info"
                                           ],
                    "bind-tcp"          : None,
                    "start"             : None,
                    "start-child"       : None,
                    "env"               : None,
                    }
    return GLOBAL_DEFAULTS
#fields that got renamed:
CLONES = {}

#these options should not be specified in config files:
NO_FILE_OPTIONS = ["daemon"]


TRUE_OPTIONS = ("yes", "true", "1", "on", True)
FALSE_OPTIONS = ("no", "false", "0", "off", False)
def parse_bool(k, v):
    if type(v)==str:
        v = v.lower()
    if v in TRUE_OPTIONS:
        return True
    elif v in FALSE_OPTIONS:
        return False
    elif v in ["auto", None]:
        #keep default - which may be None!
        return None
    else:
        warn("Warning: cannot parse value '%s' for '%s' as a boolean" % (v, k))
        return None

def print_bool(k, v, true_str='yes', false_str='no'):
    if type(v)==type(None):
        return 'auto'
    if type(v)==bool:
        if v:
            return true_str
        return false_str
    warn("Warning: cannot print value '%s' for '%s' as a boolean" % (v, k))

def parse_bool_or_int(k, v):
    return parse_bool_or_number(int, k, v)

def parse_bool_or_number(numtype, k, v, auto=0):
    if type(v)==str:
        v = v.lower()
    if v in TRUE_OPTIONS:
        return 1
    elif v in FALSE_OPTIONS:
        return 0
    else:
        return parse_number(numtype, k, v, auto)

def parse_number(numtype, k, v, auto=0):
    if type(v)==str:
        v = v.lower()
    if v=="auto":
        return auto
    try:
        return numtype(v)
    except Exception as e:
        warn("Warning: cannot parse value '%s' for '%s' as a type %s: %s" % (v, k, numtype, e))
        return None

def print_number(i, auto_value=0):
    if i==auto_value:
        return "auto"
    return str(i)

def validate_config(d={}, discard=NO_FILE_OPTIONS, extras_types={}, extras_validation={}):
    """
        Validates all the options given in a dict with fields as keys and
        strings or arrays of strings as values.
        Each option is strongly typed and invalid value are discarded.
        We get the required datatype from OPTION_TYPES
    """
    validations = OPTIONS_VALIDATION.copy()
    validations.update(extras_validation)
    option_types = OPTION_TYPES.copy()
    option_types.update(extras_types)
    nd = {}
    for k, v in d.items():
        if k in discard:
            warn("Warning: option '%s' is not allowed in configuration files" % k)
            continue
        vt = option_types.get(k)
        if vt is None:
            warn("Warning: invalid option: '%s'" % k)
            continue
        if vt==str:
            if type(v)!=str:
                warn("invalid value for '%s': %s (string required)" % (k, type(v)))
                continue
        elif vt==int:
            v = parse_bool_or_number(int, k, v)
            if v==None:
                continue
        elif vt==float:
            v = parse_number(float, k, v)
            if v==None:
                continue
        elif vt==bool:
            v = parse_bool(k, v)
            if v is None:
                continue
        elif vt==list:
            if type(v)==str:
                #could just be that we specified it only once..
                v = [v]
            elif type(v)==list or v==None:
                #ok so far..
                pass
            else:
                warn("Warning: invalid value for '%s': %s (a string or list of strings is required)" % (k, type(v)))
                continue
        else:
            warn("Error: unknown option type for '%s': %s" % (k, vt))
        validation = validations.get(k)
        if validation and v is not None:
            msg = validation(v)
            if msg:
                warn("Warning: invalid value for '%s': %s, %s" % (k, v, msg))
                continue
        nd[k] = v
    return nd


def make_defaults_struct(extras_defaults={}, extras_types={}, extras_validation={}):
    #populate config with default values:
    defaults = read_xpra_defaults()
    return dict_to_validated_config(defaults, extras_defaults, extras_types, extras_validation)

def dict_to_validated_config(d, extras_defaults={}, extras_types={}, extras_validation={}):
    options = get_defaults().copy()
    options.update(extras_defaults)
    #parse config:
    validated = validate_config(d, extras_types=extras_types, extras_validation=extras_validation)
    options.update(validated)
    for k,v in CLONES.items():
        if k in options:
            options[v] = options[k]
    config = AdHocStruct()
    for k,v in options.items():
        setattr(config, name_to_field(k), v)
    return config


def main():
    from xpra.util import nonl
    def print_options(o):
        for k,ot in sorted(OPTION_TYPES.items()):
            v = getattr(o, name_to_field(k), "")
            if ot==bool and v is None:
                v = "Auto"
            if type(v)==list:
                v = ", ".join(str(x) for x in v)
            print("* %-32s : %s" % (k, nonl(v)))
    from xpra.platform import init, clean
    try:
        init("Config-Info", "Config Info")
        args = list(sys.argv[1:])
        if "-v" in args:
            global debug
            def debug(*args):
                print(args[0] % args[1:])
            args.remove("-v")

        print("Default Configuration:")
        print_options(make_defaults_struct())
        if len(args)>0:
            for filename in args:
                print("")
                print("Configuration file '%s':" % filename)
                if not os.path.exists(filename):
                    print(" Error: file not found")
                    continue
                d = read_config(filename)
                config = dict_to_validated_config(d)
                print_options(config)
    finally:
        clean()


if __name__ == "__main__":
    main()
