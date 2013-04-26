# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

### NOTE: this must be kept in sync with the version in
###    xpra/platform/gui.py
#@PydevCodeAnalysisIgnore

import os as _os
import sys as _sys
import inspect


_init_done = False
def init():
    global _init_done
    if not _init_done:
        _init_done = True
        do_init()

def do_init():
    pass

def valid_dir(path):
    try:
        return path and os.path.exists(path) and os.path.isdir(path)
    except:
        return False


def get_default_conf_dir():
    return os.environ.get("XPRA_CONF_DIR", "~/.xpra")

def get_default_socket_dir():
    return os.environ.get("XPRA_SOCKET_DIR", "~/.xpra")

#overriden in platform code:
def get_app_dir():
    return default_get_app_dir()

def default_get_app_dir():
    if os.name=="posix":
        for prefix in [sys.exec_prefix, "/usr", "/usr/local"]:
            adir = os.path.join(prefix, "share", "xpra")
            if valid_dir(adir):
                return adir
    adir = os.path.dirname(inspect.getfile(sys._getframe(1)))
    if valid_dir(adir):
        return adir
    adir = os.path.dirname(sys.argv[0])
    if valid_dir(adir):
        return adir
    adir = os.getcwd()
    return adir       #tried our best, hope this works!

#may be overriden in platform code:
def get_resources_dir():
    return get_app_dir()

#may be overriden in platform code:
def get_icon_dir():
    adir = get_app_dir()
    idir = os.path.join(adir, "icons")
    if valid_dir(idir):
        return idir
    for prefix in [sys.exec_prefix, "/usr", "/usr/local"]:
        idir = os.path.join(prefix, "icons")
        if os.path.exists(idir):
            return idir
    return adir     #better than nothing :(

def get_icon_filename(name):
    def err(*msg):
        """ log an error message and return None """
        from wimpiggy.log import Logger
        log = Logger()
        log.error(*msg)
        return None
    idir = get_icon_dir()
    if not idir:
        return err("cannot find icons directory!")
    filename = os.path.join(idir, name)
    if not os.path.exists(filename):
        return err("icon file %s does not exist", filename)
    if not os.path.isfile(filename):
        return err("%s is not a file!", filename)
    return filename

def get_icon(name):
    filename = get_icon_filename(name)
    if not filename:
        return    None
    from xpra.gtk_common.gtk_util import get_icon_from_file
    return get_icon_from_file(filename)



if _os.name == "nt":
    from xpra.win32 import *
elif _sys.platform.startswith("darwin"):
    from xpra.darwin import *
elif _os.name == "posix":
    from xpra.xposix import *
else:
    raise OSError("Unknown OS %s" % (_os.name))

def add_notray_option(parser, extra_text=""):
    parser.add_option("--no-tray", action="store_true",
                          dest="no_tray", default=False,
                          help="Disables the system tray%s" % extra_text)

def add_delaytray_option(parser, extra_text=""):
    parser.add_option("--delay-tray", action="store_true",
                          dest="delay_tray", default=False,
                          help="Waits for the first events before showing the system tray")


def main():
    print("application directory: %s" % get_app_dir())
    print("icon directory: %s" % get_icon_dir())
    #print("share directory: %s", get_share_dir())


if __name__ == "__main__":
    main()
