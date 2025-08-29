# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from importlib import import_module


_init_done = False


def init(prgname="", appname="") -> None:
    """ do whatever is needed to prepare an application for running,
        some platforms may initialize logging to file, etc.
        If the names are supplied, we call set_name()
    """
    global _init_done
    if prgname or appname:
        set_default_name(prgname, appname)
        set_name()
    init_env()
    if not _init_done:
        _init_done = True
        do_init()


def do_init() -> None:  # pragma: no cover
    """ some platforms override this """


def init_env() -> None:
    do_init_env()


def do_init_env() -> None:
    init_env_common()


def init_env_common() -> None:
    # turn off gdk scaling to make sure we get the actual window geometry:
    os.environ["GDK_SCALE"] = os.environ.get("GDK_SCALE", "1")
    os.environ["GDK_DPI_SCALE"] = os.environ.get("GDK_DPI_SCALE", "1")
    # client side decorations break window geometry,
    # disable this "feature" unless explicitly enabled:
    os.environ["GTK_CSD"] = os.environ.get("GTK_CSD", "0")
    init_hashlib()


def init_hashlib() -> None:
    from xpra.util.env import envbool
    if envbool("XPRA_NOMD5", False):
        import hashlib
        try:
            hashlib.algorithms_available.remove("md5")  # type: ignore[attr-defined] #@UndefinedVariable
        except KeyError:
            pass
        else:
            def nomd5(*_anyargs):
                raise ValueError("md5 support is disabled")
            hashlib.md5 = nomd5                         # type: ignore
    if envbool("XPRA_NOSHA1", False):
        import hashlib  # @Reimport
        try:
            hashlib.algorithms_available.remove("sha1")  # type: ignore[attr-defined] #@UndefinedVariable
        except KeyError:
            pass
        else:
            def nosha1(*_anyargs):
                raise ValueError("sha1 support is disabled")
            hashlib.sha1 = nosha1                       # type: ignore


def threaded_server_init() -> None:
    """ platform implementations may override this function """


class program_context:
    def __init__(self, prgname="", appname=""):
        self.prgname = prgname
        self.appname = appname

    def __enter__(self):
        init(self.prgname, self.appname)
        return self

    def __exit__(self, *_args):
        clean()

    def __repr__(self):
        return f"gui_context({self.prgname}, {self.appname})"


_prgname = ""
_appname = ""


def set_default_name(prgname="", appname="") -> None:
    # sets the default prg and app names
    global _prgname, _appname
    if prgname:
        _prgname = prgname
    if appname:
        _appname = appname


# platforms can override this
def command_error(message) -> None:
    from xpra.scripts.main import error
    error(message)


def command_info(message) -> None:
    from xpra.scripts.main import info
    info(message)


_clean_done = False


def clean() -> None:
    global _clean_done
    if not _clean_done:
        _clean_done = True
        do_clean()


def do_clean() -> None:  # pragma: no cover
    """ some platforms override this """


_name_set = False


def set_name(prgname="", appname="") -> None:
    global _name_set
    if not _name_set:
        _name_set = True
        set_prgname(prgname or _prgname)
        set_application_name(appname or _appname)


# platforms can override this
def set_prgname(name="") -> None:
    if not name:
        return
    try:
        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
        GLib.set_prgname(name)
    except ImportError:
        pass


def get_prgname() -> str:
    global _prgname
    return _prgname


# platforms can override this
def set_application_name(name="") -> None:
    if not name:
        return
    try:
        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
    except ImportError:
        pass
    else:
        GLib.set_application_name(name)


def get_application_name() -> str:
    global _appname
    return _appname


def is_terminal() -> bool:
    return bool(os.environ.get("TERM", ""))


def platform_import(where: dict, pm="", required=False, *imports) -> None:
    from xpra.os_util import OSX, POSIX
    if os.name == "nt":     # pragma: no cover
        p = "win32"
    elif OSX:               # pragma: no cover
        p = "darwin"
    elif POSIX:             # pragma: no cover
        p = "posix"
    else:                   # pragma: no cover
        raise OSError(f"Unknown OS {os.name!r}")

    module = "xpra.platform.%s" % p
    if pm:
        module += ".%s" % pm

    # cannot log this early! (win32 needs log to file redirection…)
    # log = Logger("platform", "import")
    # log("importing %s from %s (required=%s)" % (imports, module, required))
    try:
        platform_module = import_module(module)
    except ImportError as e:
        if required:
            raise
        from xpra.util.env import envbool
        if envbool("XPRA_IMPORT_DEBUG", False):
            from xpra.log import Logger
            log = Logger("util")
            log.info(f"Unable to import optional {module}: {e}")
        return
    for x in imports:
        found = hasattr(platform_module, x)
        if not found:
            if required:
                raise ImportError(f"could not find {x} in {module}")
        else:
            where[x] = getattr(platform_module, x)


platform_import(globals(), "", False,
                "do_init", "do_clean", "do_init_env",
                "threaded_server_init",
                "set_prgname", "set_application_name", "program_context",
                "command_error", "command_info",
                "is_terminal",
                )
