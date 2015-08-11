# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os as os
import sys as sys


_init_done = False
def init(prgname=None, appname=None):
    """ do whatever is needed to prepare an application for running,
        some platforms may initialize logging to file, etc
    """
    global _init_done
    if not _init_done:
        _init_done = True
        if prgname:
            set_prgname(prgname)
        if appname:
            set_application_name(appname)
        do_init()

#platforms can override this
def do_init():
    pass


#platforms can override this
def command_error(message):
    print(message)

def command_info(message):
    print(message)


_clean_done = False
def clean():
    global _clean_done
    if not _clean_done:
        _clean_done = True
        do_clean()

#platforms can override this
def do_clean():
    pass


def _glib():
    from xpra.gtk_common.gobject_compat import import_glib
    return import_glib()

#platforms can override this
_prg_name = None
def set_prgname(name):
    global _prg_name
    if _prg_name is None:
        _prg_name = name
        do_set_prgname(name)

def do_set_prgname(name):
    try:
        _glib().set_prgname(name)
    except:
        pass

def get_prgname():
    global _prg_name
    return _prg_name


#platforms can override this
_application_name = None
def set_application_name(name):
    global _application_name
    if _application_name is None:
        _application_name = name
        do_set_application_name(name)

def do_set_application_name(name):
    try:
        _glib().set_application_name(name)
    except:
        pass

def get_application_name():
    global _application_name
    return _application_name


def get_main_fallback():
    #this is used on some platforms (win32),
    #when the user tries to run "xpra" without arguments
    #returns the function to run as fallback (or None)
    return None



def get_username():
    return do_get_username()

def do_get_username():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except:
        try:
            import getpass
            return getpass.getuser()
        except:
            pass
    return ""


def platform_import(where, pm, required, *imports):
    if os.name == "nt":
        p = "win32"
    elif sys.platform.startswith("darwin"):
        p = "darwin"
    elif os.name == "posix":
        p = "xposix"
    else:
        raise OSError("Unknown OS %s" % (os.name))

    module = "xpra.platform.%s" % p
    if pm:
        module += ".%s" % pm

    #cannot log this early! (win32 needs log to file redirection..)
    #log = Logger("platform", "import")
    #log("importing %s from %s (required=%s)" % (imports, module, required))
    platform_module = __import__(module, {}, {}, imports)
    assert platform_module
    for x in imports:
        found = hasattr(platform_module, x)
        if not found:
            if required:
                raise Exception("could not find %s in %s" % (x, module))
            else:
                continue
        v = getattr(platform_module, x)
        where[x] = v

platform_import(globals(), None, True, "do_init", "do_clean")
platform_import(globals(), None, False, "do_set_prgname", "do_set_application_name",
                "command_error", "command_info", "get_main_fallback", "do_get_username")
