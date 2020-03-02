# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys


_init_done = False
def init(prgname=None, appname=None):
    """ do whatever is needed to prepare an application for running,
        some platforms may initialize logging to file, etc
        If the names are supplied, we call set_name()
    """
    global _init_done
    if prgname is not None or appname is not None:
        set_default_name(prgname, appname)
        set_name()
    if not _init_done:
        _init_done = True
        do_init()

#platforms can override this
def do_init():  # pragma: no cover
    pass

def threaded_server_init():
    pass


class program_context:
    def __init__(self, prgname=None, appname=None):
        self.prgname = prgname
        self.appname = appname
    def __enter__(self):
        init(self.prgname, self.appname)
    def __exit__(self, *_args):
        clean()
    def __repr__(self):
        return "gui_context(%s, %s)" % (self.prgname, self.appname)


_prgname = None
_appname = None
def set_default_name(prgname=None, appname=None):
    #sets the default prg and app names
    global _prgname, _appname
    if prgname is not None:
        _prgname = prgname
    if appname is not None:
        _appname = appname


#platforms can override this
def command_error(message):
    from xpra.scripts.main import error
    error(message)

def command_info(message):
    from xpra.scripts.main import info
    info(message)


_clean_done = False
def clean():
    global _clean_done
    if not _clean_done:
        _clean_done = True
        do_clean()

#platforms can override this
def do_clean(): # pragma: no cover
    pass


_name_set = False
def set_name(prgname=None, appname=None):
    global _name_set
    if not _name_set:
        _name_set = True
        set_prgname(prgname or _prgname)
        set_application_name(appname or _appname)

#platforms can override this
def set_prgname(name):
    if not name:
        return
    from gi.repository import GLib
    GLib.set_prgname(name)

def get_prgname():
    global _prgname
    return _prgname


#platforms can override this
def set_application_name(name):
    if not name:
        return
    from gi.repository import GLib
    GLib.set_application_name(name)

def get_application_name():
    global _appname
    return _appname


def get_username():
    return do_get_username()

def do_get_username():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:   # pragma: no cover
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            pass
    return ""


def platform_import(where, pm, required, *imports):
    from xpra.os_util import OSX, POSIX
    if os.name == "nt": # pragma: no cover
        p = "win32"
    elif OSX:           # pragma: no cover
        p = "darwin"
    elif POSIX:         # pragma: no cover
        p = "xposix"
    else:               # pragma: no cover
        raise OSError("Unknown OS %s" % (os.name))

    module = "xpra.platform.%s" % p
    if pm:
        module += ".%s" % pm

    #cannot log this early! (win32 needs log to file redirection..)
    #log = Logger("platform", "import")
    #log("importing %s from %s (required=%s)" % (imports, module, required))
    try:
        platform_module = __import__(module, {}, {}, imports)
    except ImportError:
        if required:
            raise
        return
    assert platform_module
    for x in imports:
        found = hasattr(platform_module, x)
        if not found:
            if required:
                raise Exception("could not find %s in %s" % (x, module))
            continue
        v = getattr(platform_module, x)
        where[x] = v

platform_import(globals(), None, True, "do_init", "do_clean")
platform_import(globals(), None, False, "threaded_server_init",
                "set_prgname", "set_application_name", "program_context",
                "command_error", "command_info", "do_get_username")
