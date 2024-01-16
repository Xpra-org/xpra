# This file is part of Xpra.
# Copyright (C) 2019-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import warnings
from contextlib import AbstractContextManager, nullcontext
from threading import RLock
from typing import Any


def unsetenv(*varnames) -> None:
    for x in varnames:
        os.environ.pop(x, None)


def hasenv(name: str) -> bool:
    return os.environ.get(name) is not None


def envint(name: str, d: int = 0) -> int:
    try:
        return int(os.environ.get(name, d))
    except ValueError:
        return d


def envbool(name: str, d: bool = False) -> bool:
    try:
        v = os.environ.get(name, "").lower()
        if v is None:
            return d
        if v in ("yes", "true", "on"):
            return True
        if v in ("no", "false", "off"):
            return False
        return bool(int(v))
    except ValueError:
        return d


def envfloat(name: str, d: float = 0) -> float:
    try:
        return float(os.environ.get(name, d))
    except ValueError:
        return d


def restore_script_env(env):
    # On OSX PythonExecWrapper sets various env vars to point into the bundle
    # and records the original variable contents. Here we revert them back
    # to their original state in case any of those changes cause problems
    # when running a command.
    if "_PYTHON_WRAPPER_VARS" in env:
        for v in env["_PYTHON_WRAPPER_VARS"].split():
            origv = "_" + v
            if env.get(origv):
                env[v] = env[origv]
            elif v in env:
                del env[v]
            del env[origv]
        del env["_PYTHON_WRAPPER_VARS"]
    return env


def shellsub(s: str, subs=None) -> str:
    """ shell style string substitution using the dictionary given """
    if subs:
        for var, value in subs.items():
            try:
                if isinstance(s, bytes):
                    vbin = str(value).encode()
                    s = s.replace(f"${var}".encode(), vbin)
                    s = s.replace(("${%s}" % var).encode(), vbin)
                else:
                    vstr = str(value)
                    s = s.replace(f"${var}", vstr)
                    s = s.replace("${%s}" % var, vstr)
            except (TypeError, ValueError):
                msg = f"failed to substitute {var!r} with value {value!r} ({type(value)}) in {s!r}"
                raise ValueError(msg) from None
    return s


def osexpand(s: str, actual_username="", uid=0, gid=0, subs=None) -> str:
    if not s:
        return s

    def expanduser(s: str):
        if actual_username and s.startswith("~/"):
            # replace "~/" with "~$actual_username/"
            return os.path.expanduser("~%s/%s" % (actual_username, s[2:]))
        return os.path.expanduser(s)
    d = dict(subs or {})
    d |= {
        "PID"   : os.getpid(),
        "HOME"  : expanduser("~/"),
    }
    if os.name == "posix":
        d |= {
            "UID"   : uid or os.geteuid(),
            "GID"   : gid or os.getegid(),
        }
        from xpra.os_util import OSX
        if not OSX:
            from xpra.platform.posix.paths import get_runtime_dir
            rd = get_runtime_dir()
            if rd and "XDG_RUNTIME_DIR" not in os.environ:
                d["XDG_RUNTIME_DIR"] = rd
    if actual_username:
        d["USERNAME"] = actual_username
        d["USER"] = actual_username
    # first, expand the substitutions themselves,
    # as they may contain references to other variables:
    ssub = {}
    for k, v in d.items():
        ssub[k] = expanduser(shellsub(str(v), d))
    return os.path.expandvars(expanduser(shellsub(expanduser(s), ssub)))


class OSEnvContext:
    __slots__ = ("env", "kwargs")

    def __init__(self, **kwargs):
        self.env = {}
        self.kwargs = kwargs

    def __enter__(self):
        self.env = os.environ.copy()
        os.environ.update(self.kwargs)

    def __exit__(self, *_args):
        os.environ.clear()
        os.environ.update(self.env)

    def __repr__(self):
        return "OSEnvContext"


# a global dictionary used for
# showing warning message just once
_once_only = set()


def first_time(key: str) -> bool:
    if key not in _once_only:
        _once_only.add(key)
        return True
    return False


class IgnoreWarningsContext(AbstractContextManager):

    def __enter__(self):
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    def __exit__(self, exc_type, exc_val, exc_tb):
        warnings.filterwarnings("default")

    def __repr__(self):
        return "IgnoreWarningsContext"


def ignorewarnings(fn, *args) -> Any:
    import warnings
    try:
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        return fn(*args)
    finally:
        warnings.filterwarnings("default")


numpy_import_lock = RLock()


class NumpyImportContext(AbstractContextManager):

    def __init__(self, blocking=False):
        self.blocking = blocking

    def __enter__(self):
        if not numpy_import_lock.acquire(blocking=self.blocking):
            raise RuntimeError("the numpy import lock is already held!")
        os.environ["XPRA_NUMPY_IMPORT"] = "1"

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.environ.pop("XPRA_NUMPY_IMPORT", None)
        numpy_import_lock.release()

    def __repr__(self):
        return f"numpy_import_context({self.blocking=})"


_saved_env = os.environ.copy()


def save_env() -> None:
    global _saved_env
    _saved_env = os.environ.copy()


def get_saved_env() -> dict[str,str]:
    return _saved_env.copy()


def get_saved_env_var(var, default=None):
    return _saved_env.get(var, default)


class SilenceWarningsContext(AbstractContextManager):

    def __init__(self, *categories):
        if sys.warnoptions:
            self.context = nullcontext()
            self.categories = ()
        else:
            self.categories = categories
            self.context = warnings.catch_warnings()

    def __enter__(self):
        self.context.__enter__()
        for category in self.categories:
            warnings.filterwarnings("ignore", category=category)

    def __exit__(self, exc_type, exc_val, exc_tb):
        warnings.filterwarnings("default")
        self.context.__exit__(exc_type, exc_val, exc_tb)

    def __repr__(self):
        return f"IgnoreWarningsContext({self.categories})"
