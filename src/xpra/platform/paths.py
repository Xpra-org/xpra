# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import inspect
import os as _os
import sys as _sys


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
        from xpra.log import Logger
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


LICENSE_TEXT = None
def get_license_text(self):
    global LICENSE_TEXT
    if LICENSE_TEXT:
        return  LICENSE_TEXT
    filename = os.path.join(get_resources_dir(), 'COPYING')
    if os.path.exists(filename):
        try:
            if sys.version < '3':
                license_file = open(filename, mode='rb')
            else:
                license_file = open(filename, mode='r', encoding='ascii')
            LICENSE_TEXT = license_file.read()
        finally:
            license_file.close()
    if not LICENSE_TEXT:
        LICENSE_TEXT = "GPL version 2"
    return LICENSE_TEXT


if _os.name == "nt":
    from win32.paths import *               #@UnusedWildImport
elif _sys.platform.startswith("darwin"):
    from darwin.paths import *              #@UnusedWildImport
elif _os.name == "posix":
    from xposix.paths import *              #@UnusedWildImport
else:
    raise OSError("Unknown OS %s" % (_os.name))
