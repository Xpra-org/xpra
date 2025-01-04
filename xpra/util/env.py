# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os
import sys
import warnings
import traceback
from contextlib import AbstractContextManager, nullcontext
from collections.abc import Sequence, Callable
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


def shellsub(s: str, subs: dict) -> str:
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

    def expanduser(var: str):
        if actual_username and var.startswith("~/"):
            # replace "~/" with "~$actual_username/"
            return os.path.expanduser("~%s/%s" % (actual_username, var[2:]))
        return os.path.expanduser(var)

    d = dict(subs or {})
    d |= {
        "PID": os.getpid(),
        "HOME": expanduser("~/"),
    }
    if os.name == "posix":
        d |= {
            "UID": uid or os.geteuid(),
            "GID": gid or os.getegid(),
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


def ignorewarnings(fn: Callable, *args) -> Any:
    import warnings
    try:
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        return fn(*args)
    finally:
        warnings.filterwarnings("default")


class nomodule_context:
    __slots__ = ("module_name", "saved_module")

    def __init__(self, module_name: str):
        self.module_name = module_name

    def __enter__(self):
        self.saved_module = sys.modules.get(self.module_name)
        # noinspection PyTypeChecker
        sys.modules[self.module_name] = None  # type: ignore[assignment]

    def __exit__(self, *_args):
        if sys.modules.get(self.module_name) is None:
            if self.saved_module is None:
                sys.modules.pop(self.module_name, None)
            else:
                sys.modules[self.module_name] = self.saved_module

    def __repr__(self):
        return f"nomodule_context({self.module_name})"


numpy_import_lock = RLock()


class NumpyImportContext(AbstractContextManager):

    def __init__(self, info: str, blocking=False):
        self.blocking = blocking
        self.info = info
        self.backtrace: list[str] = traceback.format_stack()

    def __enter__(self):
        if not numpy_import_lock.acquire(blocking=self.blocking):
            from xpra.log import Logger
            log = Logger("util")

            def log_backtrace(backtrace):
                for bt in backtrace:
                    for line in bt.split("\n"):
                        if line.strip():
                            log.warn(line)

            log.warn("numpy lock was already acquired from:")
            log_backtrace(self.backtrace)
            log.warn("failed to acquire it again from:")
            log_backtrace(traceback.format_stack())
            raise RuntimeError(f"the numpy import lock is already held by {self.info!r}!")
        os.environ["XPRA_NUMPY_IMPORT"] = "1"

    def __exit__(self, exc_type, exc_val, exc_tb):
        wait = envint("XPRA_NUMPY_LOCK_SLEEP", 0)
        import time
        time.sleep(wait)
        os.environ.pop("XPRA_NUMPY_IMPORT", None)
        numpy_import_lock.release()

    def __repr__(self):
        return f"numpy_import_context({self.info}, {self.blocking=})"


def numpy_import_context(subsystem: str, blocking=False) -> AbstractContextManager:
    # ie: subsystem = "OpenGL: glx context"
    key = subsystem.split(" ", 1)[0].split(":", 1)[0]
    # ie key = "OpenGL"
    env_name = "XPRA_"+(key.upper())+"_NUMPY"
    if env_name not in os.environ:
        env_name = "XPRA_NUMPY"
    allow_numpy = envbool(env_name, True)
    if allow_numpy:
        import threading
        thread = threading.current_thread()
        info = subsystem + f" in thread {thread.ident}: {thread.name!r}"
        return NumpyImportContext(info=info, blocking=blocking)
    return nomodule_context("numpy")


_saved_env = os.environ.copy()


def save_env() -> None:
    global _saved_env
    _saved_env = os.environ.copy()


def get_saved_env() -> dict[str, str]:
    return _saved_env.copy()


def get_saved_env_var(var, default="") -> str:
    return _saved_env.get(var, default)


def get_exec_env(remove: Sequence[str] = ("LS_COLORS", "LESSOPEN", "HISTCONTROL", "HISTSIZE", ),
                 keep: Sequence[str] = ()) -> dict[str, str]:
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        # anything matching `remove` is dropped:
        if any(re.match(pattern, k) for pattern in remove):
            continue
        # if `keep` is empty, then we ignore it, otherwise we require a match:
        if keep and not any(re.match(pattern, k) for pattern in keep):
            continue
        # let's make things more complicated than they should be:
        # on win32, the environment can end up containing unicode, and subprocess chokes on it:
        try:
            env[k] = v.encode("utf8").decode("latin1")
        except UnicodeError:
            env[k] = str(v)
    env["XPRA_SKIP_UI"] = "1"
    env["XPRA_FORCE_COLOR_LOG"] = "1"
    return env


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
