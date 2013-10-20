# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
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


ENCRYPTION_CIPHERS = []
try:
    from Crypto.Cipher import AES
    assert AES
    ENCRYPTION_CIPHERS.append("AES")
except:
    pass


def OpenGL_safety_check():
    #Ubuntu 12.04 will just crash on you if you try:
    distro = python_platform.linux_distribution()
    if distro and len(distro)==3 and distro[0]=="Ubuntu":
        ur = distro[1]  #ie: "12.04"
        try:
            rnum = [int(x) for x in ur.split(".")]  #ie: [12, 4]
            if rnum<=[12, 04]:
                return "Ubuntu %s is too buggy" % ur
        except:
            pass
    #try to detect VirtualBox:
    #based on the code found here:
    #http://spth.virii.lu/eof2/articles/WarGame/vboxdetect.html
    #because it causes hard VM crashes when we probe the GL driver!
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
                return "VirtualBox is present (VBoxMiniRdrDN)"
    except Exception, e:
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
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS
        from xpra.build_info import BUILT_BY, BUILT_ON, BUILD_DATE, CYTHON_VERSION, COMPILER_INFO
        info.append("Built on %s by %s" % (BUILT_ON, BUILT_BY))
        if BUILD_DATE:
            info.append(BUILD_DATE)
        try:
            mods = int(LOCAL_MODIFICATIONS)
        except:
            mods = 0
        if mods==0:
            info.append("revision %s" % REVISION)
        else:
            info.append("revision %s with %s local changes" % (REVISION, LOCAL_MODIFICATIONS))
        if CYTHON_VERSION!="unknown" or COMPILER_INFO!="unknown":
            info.append("")
        if CYTHON_VERSION!="unknown":
            info.append("built with Cython %s" % CYTHON_VERSION)
        if COMPILER_INFO!="unknown":
            info.append(COMPILER_INFO)
    except Exception, e:
        warn("Error: could not find the source or build information: %s" % e)
    return info


def save_config(conf_file, config, keys):
    f = open(conf_file, "w")
    for key in keys:
        assert key in OPTION_TYPES, "invalid configuration key: %s" % key
        fn = key.replace("-", "_")
        v = getattr(config, fn)
        f.write("%s=%s%s" % (key, v, os.linesep))
    f.close()

def read_config(conf_file):
    """
        Parses a config file into a dict of strings.
        If the same key is specified more than once,
        the value for this key will be an array of strings.
    """
    d = {}
    if not os.path.isfile(conf_file):
        return d
    f = open(conf_file, "rU")
    lines = []
    for line in f:
        sline = line.strip().rstrip('\r\n').strip()
        if len(sline) == 0:
            continue
        if sline[0] in ( '!', '#' ):
            continue
        lines.append(sline)
    f.close()
    #aggregate any lines with trailing bacakslash
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
    #parse name=value pairs:
    for sline in agg_lines:
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
    return  d

def read_xpra_conf(conf_dir):
    """
        Reads an "xpra.conf" file from the given directory,
        returns a dict with values as strings and arrays of strings.
    """
    cdir = os.path.expanduser(conf_dir)
    d = {}
    if not os.path.exists(cdir) or not os.path.isdir(cdir):
        return  d
    conf_file = os.path.join(cdir, 'xpra.conf')
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        return  d
    return read_config(conf_file)

def read_xpra_defaults():
    """
        Reads the global "xpra.conf" and then the user-specific one.
        (the latter overrides values from the former)
        returns a dict with values as strings and arrays of strings.
    """
    #first, read the global defaults:
    if sys.platform.startswith("win"):
        conf_dir = os.path.dirname(os.path.abspath(sys.executable))
    elif sys.prefix == '/usr':
        conf_dir = '/etc/xpra'
    else:
        conf_dir = sys.prefix + '/etc/xpra/'
    defaults = read_xpra_conf(conf_dir)
    #now load the per-user config over it:
    from xpra.platform.paths import get_default_conf_dir
    user_defaults = read_xpra_conf(get_default_conf_dir())
    for k,v in user_defaults.items():
        defaults[k] = v
    return defaults


OPTION_TYPES = {
                    #string options:
                    "encoding"          : str,
                    "title"             : str,
                    "host"              : str,
                    "username"          : str,
                    "auth"              : str,
                    "remote-xpra"       : str,
                    "session-name"      : str,
                    "client-toolkit"    : str,
                    "dock-icon"         : str,
                    "tray-icon"         : str,
                    "window-icon"       : str,
                    "password"          : str,
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
                    "mode"              : str,
                    "window-layout"     : str,
                    "display"           : str,
                    #int options:
                    "quality"           : int,
                    "min-quality"       : int,
                    "speed"             : int,
                    "min-speed"         : int,
                    "port"              : int,
                    "compression_level" : int,
                    "dpi"               : int,
                    #float options:
                    "max-bandwidth"     : float,
                    "auto-refresh-delay": float,
                    #boolean options:
                    "debug"             : bool,
                    "daemon"            : bool,
                    "use-display"       : bool,
                    "no-tray"           : bool,
                    "clipboard"         : bool,
                    "pulseaudio"        : bool,
                    "mmap"              : bool,
                    "mmap-group"        : bool,
                    "speaker"           : bool,
                    "microphone"        : bool,
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
                    "autoconnect"       : bool,
                    "exit-with-children": bool,
                    "opengl"            : bool,
                    #arrays of strings (default value, allowed options):
                    "speaker-codec"     : list,
                    "microphone-codec"  : list,
                    "key-shortcut"      : list,
                    "start-child"       : list,
                    "bind-tcp"          : list,
               }

GLOBAL_DEFAULTS = None
#lowest common denominator here
#(the xpra.conf file shipped is generally better tuned than this - especially for 'xvfb')
def get_defaults():
    global GLOBAL_DEFAULTS
    if GLOBAL_DEFAULTS is not None:
        return GLOBAL_DEFAULTS
    from xpra.platform.features import DEFAULT_SSH_CMD
    try:
        from xpra.platform.info import get_username
        username = get_username()
    except:
        username = ""
    GLOBAL_DEFAULTS = {
                    "encoding"          : "",
                    "title"             : "@title@ on @client-machine@",
                    "host"              : "",
                    "username"          : username,
                    "auth"              : "",
                    "remote-xpra"       : ".xpra/run-xpra",
                    "session-name"      : "",
                    "client-toolkit"    : "",
                    "dock-icon"         : "",
                    "tray-icon"         : "",
                    "window-icon"       : "",
                    "password"          : "",
                    "password-file"     : "",
                    "clipboard-filter-file" : "",
                    "pulseaudio-command": "pulseaudio --start --daemonize=false --system=false "
                                            +" --exit-idle-time=-1 -n --load=module-suspend-on-idle "
                                            +" --load=module-null-sink --load=module-native-protocol-unix "
                                            +" --log-level=2 --log-target=stderr",
                    "encryption"        : "",
                    "encryption_keyfile": "",
                    "mode"              : "tcp",
                    "ssh"               : DEFAULT_SSH_CMD,
                    "xvfb"              : "Xvfb +extension Composite -screen 0 3840x2560x24+32 -nolisten tcp -noreset -auth $XAUTHORITY",
                    "socket-dir"        : "",
                    "log-file"          : "$DISPLAY.log",
                    "window-layout"     : "",
                    "display"           : "",
                    "quality"           : -1,
                    "min-quality"       : 50,
                    "speed"             : -1,
                    "min-speed"         : -1,
                    "port"              : -1,
                    "compression_level" : 1,
                    "dpi"               : 96,
                    "max-bandwidth"     : 0.0,
                    "auto-refresh-delay": 0.25,
                    "debug"             : False,
                    "daemon"            : True,
                    "use-display"       : False,
                    "no-tray"           : False,
                    "clipboard"         : True,
                    "pulseaudio"        : True,
                    "mmap"              : True,
                    "mmap-group"        : False,
                    "speaker"           : True,
                    "microphone"        : True,
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
                    "autoconnect"       : False,
                    "exit-with-children": False,
                    "opengl"            : OPENGL_DEFAULT,
                    "speaker-codec"     : [],
                    "microphone-codec"  : [],
                    "key-shortcut"      : ["Meta+Shift+F4:quit", "Meta+Shift+F8:magic_key"],
                    "bind-tcp"          : None,
                    "start-child"       : None,
                    }
    return GLOBAL_DEFAULTS
MODES = ["tcp", "tcp + aes", "ssh"]
def validate_in_list(x, options):
    if x in options:
        return None
    return "must be in %s" % (", ".join(options))
OPTIONS_VALIDATION = {
                    "mode"              : lambda x : validate_in_list(x, MODES),
                    }
#fields that got renamed:
CLONES = {
            "quality"       : "jpeg-quality",
          }

#these options should not be specified in config files:
NO_FILE_OPTIONS = ["daemon"]



def parse_bool(k, v):
    if type(v)==str:
        v = v.lower()
    if v in ["yes", "true", "1", "on", True]:
        return True
    elif v in ["no", "false", "0", "off", False]:
        return False
    elif v in ["auto", None]:
        #keep default - which may be None!
        return None
    else:
        warn("Warning: cannot parse value '%s' for '%s' as a boolean" % (v, k))

def print_bool(k, v):
    if type(v)==type(None):
        return 'auto'
    if type(v)==bool:
        return v and 'yes' or 'no'
    warn("Warning: cannot print value '%s' for '%s' as a boolean" % (v, k))

def parse_number(numtype, k, v, auto=-1):
    if type(v)==str:
        v = v.lower()
    if v=="auto":
        return auto
    try:
        return numtype(v)
    except Exception, e:
        warn("Warning: cannot parse value '%s' for '%s' as a type %s: %s" % (v, k, numtype, e))
        return None

def validate_config(d={}, discard=NO_FILE_OPTIONS):
    """
        Validates all the options given in a dict with fields as keys and
        strings or arrays of strings as values.
        Each option is strongly typed and invalid value are discarded.
        We get the required datatype from OPTION_TYPES
    """
    nd = {}
    for k, v in d.items():
        if k in discard:
            warn("Warning: option '%s' is not allowed in configuration files" % k)
            continue
        vt = OPTION_TYPES.get(k)
        if vt is None:
            warn("Warning: invalid option: '%s'" % k)
            continue
        if vt==str:
            if type(v)!=str:
                warn("invalid value for '%s': %s (string required)" % (k, type(v)))
                continue
        elif vt==int:
            v = parse_number(int, k, v)
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
        validation = OPTIONS_VALIDATION.get(k)
        if validation and v is not None:
            msg = validation(v)
            if msg:
                warn("Warning: invalid value for '%s': %s, %s" % (k, v, msg))
                continue
        nd[k] = v
    return nd


def make_defaults_struct():
    #populate config with default values:
    defaults = read_xpra_defaults()
    validated = validate_config(defaults)
    options = get_defaults().copy()
    options.update(validated)
    for k,v in CLONES.items():
        if k in options:
            options[v] = options[k]
    config = AdHocStruct()
    for k,v in options.items():
        attr_name = k.replace("-", "_")
        setattr(config, attr_name, v)
    return config


def main():
    print("default configuration: %s" % make_defaults_struct())


if __name__ == "__main__":
    main()
