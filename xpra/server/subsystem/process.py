# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any

from xpra.common import noerr
from xpra.os_util import POSIX, OSX, getuid, get_shell_for_uid, get_username_for_uid, get_home_for_uid, find_group
from xpra.scripts.display import X11_SOCKET_DIR
from xpra.scripts.main import configure_env, parse_env
from xpra.util.env import envbool, osexpand, source_env, unsetenv
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("server")


def sanitize_env() -> None:
    # we don't want client apps to think these mean anything:
    # (if set, they belong to the desktop the server was started from)
    # TODO: simply whitelisting the env would be safer/better
    unsetenv("DESKTOP_SESSION",
             "GDMSESSION",
             "GNOME_DESKTOP_SESSION_ID",
             "SESSION_MANAGER",
             "XDG_VTNR",
             "XDG_MENU_PREFIX",
             "XDG_CURRENT_DESKTOP",
             "XDG_SESSION_DESKTOP",
             "XDG_SESSION_TYPE",
             "XDG_SESSION_ID",
             "XDG_SEAT",
             "XDG_VTNR",
             "QT_GRAPHICSSYSTEM_CHECKED",
             "CKCON_TTY",
             "CKCON_X11_DISPLAY",
             "CKCON_X11_DISPLAY_DEVICE",
             "WINDOWPATH",
             "VTE_VERSION",
             "LS_COLORS",
             )


def create_runtime_dir(xrd: str, uid: int, gid: int) -> str:
    if not POSIX or OSX or getuid() != 0:
        return ""
    # workarounds:
    # * some distros don't set a correct value,
    # * or they don't create the directory for us,
    # * or pam_open is going to create the directory but needs time to do so..
    if xrd and xrd.endswith("/user/0") and uid > 0:
        # don't keep root's directory, as this would not work:
        xrd = ""
    if not xrd:
        # find the "/run/user" directory:
        run_user = "/run/user"
        if not os.path.exists(run_user):
            run_user = "/var/run/user"
        if os.path.exists(run_user):
            xrd = os.path.join(run_user, str(uid))
    if not xrd:
        return ""
    if not os.path.exists(xrd):
        os.mkdir(xrd, 0o700)
        if POSIX:
            os.lchown(xrd, uid, gid)
    xpra_dir = os.path.join(xrd, "xpra")
    if not os.path.exists(xpra_dir):
        os.mkdir(xpra_dir, 0o700)
        if POSIX:
            os.lchown(xpra_dir, uid, gid)
    return xrd


def setup_pam_session(display_name: str, xauth_data: str, uid: int) -> tuple[Any, dict]:
    # if pam is present, try to create a new session:
    pam = None
    root = POSIX and getuid() == 0
    pam_open = POSIX and envbool("XPRA_PAM_OPEN", root and uid != 0)
    if pam_open:
        try:
            from xpra.platform.pam import pam_session
        except ImportError as e:
            noerr(sys.stderr.write, "Error: failed to import pam module\n")
            noerr(sys.stderr.write, f" {e}\n")
            del e
        else:
            username = get_username_for_uid(uid)
            pam = pam_session(username)
    if pam:
        env = {
            # "XDG_SEAT"               : "seat1",
            # "XDG_VTNR"               : "0",
            "XDG_SESSION_TYPE": "x11",
            # "XDG_SESSION_CLASS"      : "user",
            "XDG_SESSION_DESKTOP": "xpra",
        }
        # maybe we should just bail out instead?
        if pam.start():
            pam.set_env(env)
            items = {}
            if display_name.startswith(":"):
                items["XDISPLAY"] = display_name
            if xauth_data:
                items["XAUTHDATA"] = xauth_data
            pam.set_items(items)
            if pam.open():
                # we can't close it, because we're not going to be root anymore,
                # but since we're the process leader for the session,
                # terminating will also close the session
                # atexit.register(pam.close)
                protected_env = pam.get_envlist()
                os.environ.update(protected_env)
                return pam, protected_env
    return pam, {}


def setup_runtime_dir(opts_env: tuple[str, ...], uid: int, gid: int, protected_env: dict) -> tuple[str, dict]:
    # get XDG_RUNTIME_DIR from env options,
    # which may not have updated os.environ yet when running as root with "--uid="
    root = POSIX and getuid() == 0
    xrd = parse_env(opts_env).get("XDG_RUNTIME_DIR", "")
    if OSX and not xrd:
        xrd = osexpand("~/.xpra", uid=uid, gid=gid)
        os.environ["XDG_RUNTIME_DIR"] = xrd
    xrd = os.path.abspath(xrd) if xrd else ""
    if root and (uid > 0 or gid > 0):
        # we're going to chown the directory if we create it,
        # ensure this cannot be abused, only use "safe" paths:
        if xrd == f"/run/user/{uid}":
            pass  # OK!
        elif not any(True for x in ("/tmp", "/var/tmp") if xrd.startswith(x)):
            xrd = ""
        # these paths could cause problems if we were to create and chown them:
        elif xrd.startswith(X11_SOCKET_DIR) or xrd.startswith("/tmp/.XIM-unix"):
            xrd = ""
    if not xrd:
        xrd = os.environ.get("XDG_RUNTIME_DIR", "")
    xrd = create_runtime_dir(xrd, uid, gid)
    if xrd:
        # this may override the value we get from pam
        # with the value supplied by the user:
        protected_env["XDG_RUNTIME_DIR"] = xrd
    return xrd, protected_env


class ProcessServer(StubSubsystem):
    __slots__ = (
        "applied", "chdir", "env", "gid", "pam", "protected_env", "source", "uid",
        "wm_name", "xrd", "xvfb",
    )
    PREFIX = "process"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.uid = 0
        self.gid = 0
        self.protected_env: dict[str, str] = {}
        self.env = ()
        self.source = ()
        self.wm_name = ""
        self.xvfb = ""
        self.chdir = ""
        self.pam = None
        self.xrd = ""
        self.applied = False

    def init(self, opts) -> None:
        self.uid = int(opts.uid)
        self.gid = int(opts.gid)
        if POSIX and self.uid and not self.gid:
            self.gid = find_group(self.uid)
            opts.gid = self.gid
        self.env = tuple(opts.env)
        self.source = tuple(opts.source)
        self.wm_name = str(opts.wm_name or "")
        self.xvfb = str(opts.xvfb or "")
        self.chdir = str(opts.chdir or "")

    def prepare_environment(self, display_name: str, xauth_data: str, start_vfb: bool,
                            shadowing: bool, starting: str, protected_env: dict) -> None:
        self.protected_env = dict(protected_env)
        self.pam, pam_protected_env = setup_pam_session(display_name, xauth_data, self.uid)
        if pam_protected_env:
            self.protected_env = pam_protected_env

        self.xrd, self.protected_env = setup_runtime_dir(self.env, self.uid, self.gid, self.protected_env)

        sanitize_env()
        if not shadowing:
            os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.update(source_env(self.source))
        if POSIX:
            if self.xrd:
                os.environ["XDG_RUNTIME_DIR"] = self.xrd
            if not OSX:
                os.environ["XDG_SESSION_TYPE"] = "x11"
            if starting != "desktop":
                os.environ["XDG_CURRENT_DESKTOP"] = self.wm_name
        if display_name[0] != "S":
            os.environ["DISPLAY"] = display_name
            if POSIX:
                os.environ["CKCON_X11_DISPLAY"] = display_name
        elif not start_vfb or "Xephyr" not in self.xvfb:
            os.environ.pop("DISPLAY", None)
        os.environ.update(self.protected_env)

    def setup(self) -> None:
        if self.applied:
            return
        self.applied = True
        root = POSIX and getuid() == 0
        if root and (self.uid != 0 or self.gid != 0):
            username = get_username_for_uid(self.uid)
            home = get_home_for_uid(self.uid)
            log("root: switching to uid=%i, gid=%i", self.uid, self.gid)
            from xpra.util.daemon import setuidgid
            setuidgid(self.uid, self.gid)
            os.environ.update({
                "HOME": home,
                "USER": username,
                "LOGNAME": username,
            })
            shell = get_shell_for_uid(self.uid)
            if shell:
                os.environ["SHELL"] = shell
            # now we've changed uid, it is safe to honour all the env updates:
            configure_env(self.env)
            os.environ.update(self.protected_env)
            if not self.chdir:
                self.chdir = home
        else:
            configure_env(self.env)
        if self.chdir:
            log(f"chdir({self.chdir})")
            os.chdir(osexpand(self.chdir))

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            ProcessServer.PREFIX: {
                "uid": self.uid,
                "gid": self.gid,
                "root": POSIX and getuid() == 0,
                "chdir": self.chdir,
                "applied": self.applied,
            },
        }
