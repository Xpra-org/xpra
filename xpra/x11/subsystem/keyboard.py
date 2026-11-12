# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from typing import Any
from collections.abc import Sequence
from time import monotonic
from subprocess import Popen

from xpra.common import noop
from xpra.os_util import POSIX
from xpra.server.source.keyboard import KeyboardConnection
from xpra.util.pid import load_pid, write_pid
from xpra.util.child_reaper import KILL_CHILD_PROCESS_GROUP, ProcInfo, get_child_reaper, pid_exists, stop_child_process
from xpra.util.env import envbool, get_xdg_home
from xpra.util.io import find_libexec_command, which
from xpra.util.objects import typedict, Scheduler
from xpra.server.subsystem.keyboard import KeyboardManager
from xpra.util.system import stop_proc
from xpra.x11.error import xsync, xswallow, xlog
from xpra.log import Logger

log = Logger("x11", "server", "keyboard")
ibuslog = Logger("keyboard", "ibus")

IBUS = envbool("XPRA_IBUS", True)
IBUS_DAEMON_COMMAND = os.environ.get("XPRA_IBUS_DAEMON_COMMAND",
                                     "ibus-daemon --xim --verbose --replace --panel=disable --desktop=xpra")
EXPOSE_IBUS_LAYOUTS = envbool("XPRA_EXPOSE_IBUS_LAYOUTS", IBUS)


def configure_imsettings_env(input_method: str) -> str:
    im = input_method.lower()
    if im in ("none", "no"):
        # the default: set DISABLE_IMSETTINGS=1, fallback to xim
        # that's because the 'ibus' 'immodule' breaks keyboard handling
        # unless its daemon is also running - and we don't know if it is..
        imsettings_env(True, "xim", "xim", "xim", "none", "@im=none")
    elif im == "keep":
        # do nothing and keep whatever is already set, hoping for the best
        pass
    elif im in ("xim", "ibus", "scim", "uim"):
        # ie: (False, "ibus", "ibus", "IBus", "@im=ibus")
        imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=" + im.lower())
    else:
        v = imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=" + im.lower())
        ibuslog.warn(f"using input method settings: {v}")
        ibuslog.warn(f"unknown input method specified: {input_method}")
        ibuslog.warn(" if it is correct, you may want to file a bug to get it recognized")
    return im


def imsettings_env(disabled, gtk_im_module, qt_im_module, clutter_im_module,
                   imsettings_module, xmodifiers) -> dict[str, str]:
    # for more information, see imsettings:
    # https://code.google.com/p/imsettings/source/browse/trunk/README
    if disabled is True:
        os.environ["DISABLE_IMSETTINGS"] = "1"  # this should override any XSETTINGS too
    elif disabled is False and ("DISABLE_IMSETTINGS" in os.environ):
        del os.environ["DISABLE_IMSETTINGS"]
    v = {
        "GTK_IM_MODULE": gtk_im_module,  # or "gtk-im-context-simple"?
        "QT_IM_MODULE": qt_im_module,  # or "simple"?
        "QT4_IM_MODULE": qt_im_module,
        "CLUTTER_IM_MODULE": clutter_im_module,
        "IMSETTINGS_MODULE": imsettings_module,  # or "xim"?
        "XMODIFIERS": xmodifiers,
        # not really sure what to do with those:
        # "IMSETTINGS_DISABLE_DESKTOP_CHECK"    : "true",
        # "IMSETTINGS_INTEGRATE_DESKTOP"        : "no"           #we're not a real desktop
    }
    os.environ.update(v)
    return v


def ibus_pid_file() -> str:
    session_dir = os.environ["XPRA_SESSION_DIR"]
    return os.path.join(session_dir, "ibus-daemon.pid")


def get_ibus_dirs() -> tuple[str, str]:
    """
    Returns the directory containing the ibus address files,
    and the one containing its socket - creating them if needed.
    """
    config_dir = os.path.expanduser(get_xdg_home("XDG_CONFIG_HOME"))
    cache_dir = os.path.expanduser(get_xdg_home("XDG_CACHE_HOME"))
    dirs = os.path.join(config_dir, "ibus", "bus"), os.path.join(cache_dir, "ibus")
    for path in dirs:
        os.makedirs(path, mode=0o700, exist_ok=True)
    return dirs


def ibus_has_process_group(pid: int) -> bool:
    if not POSIX or not KILL_CHILD_PROCESS_GROUP or pid <= 1:
        return False
    if pid == os.getpgrp():
        return False
    try:
        # OpenBSD rejects getpgid() for processes in another session.
        # Probe the group itself without sending a signal.
        os.killpg(pid, 0)
    except OSError:
        return False
    return True


def may_start_ibus(env: dict[str, str], scheduler: Scheduler) -> ProcInfo | None:
    # maybe we are inheriting one from a dead session?
    daemonizer = find_libexec_command("daemonizer")
    pidfile = ibus_pid_file()
    ibus_daemon_pid = load_pid(pidfile)
    ibuslog(f"may_start_ibus({env}) {ibus_daemon_pid=}, {pidfile=!r}, {daemonizer=!r}")

    def register_pid(pid: int, command) -> ProcInfo:
        reaper = get_child_reaper()
        procinfo = reaper.add_pid(pid, "ibus-daemon", command=command, ignore=True, forget=False,
                                  kill_process_group=ibus_has_process_group(pid))
        procinfo.pidfile = pidfile

        def poll_ibus() -> bool:
            # A detached daemon does not deliver SIGCHLD to this server.
            reaper.poll()
            return not procinfo.dead

        if not procinfo.dead:
            scheduler.timeout_add(1000, poll_ibus)
        return procinfo

    pidfile_exists = os.path.exists(pidfile)
    if POSIX and ibus_daemon_pid > 1 and pid_exists(ibus_daemon_pid):
        ibuslog(f"ibus-daemon is already running with pid {ibus_daemon_pid!r}")
        return register_pid(ibus_daemon_pid, shlex.split(IBUS_DAEMON_COMMAND))
    if pidfile_exists:
        try:
            os.unlink(pidfile)
        except OSError as e:
            log.error(f"Warning: unable to delete old ibus pid file {pidfile!r}")
            log.estr(e)
            # don't trust the pidfile value from now on:
            pidfile = ""

    def start() -> ProcInfo | None:
        command = shlex.split(IBUS_DAEMON_COMMAND)
        child_env = env
        ibuslog(f"starting ibus: {IBUS_DAEMON_COMMAND!r}")
        if daemonizer:
            from xpra.platform.paths import get_python_execfile_command
            command = get_python_execfile_command() + [daemonizer, pidfile, "--"] + command
            ibuslog(" using daemonizer: %r", command)
            # Keep the daemonizer's isolation policy consistent with its registration.
            child_env = dict(env)
            child_env["XPRA_KILL_CHILD_PROCESS_GROUP"] = "1" if KILL_CHILD_PROCESS_GROUP else "0"
        proc = Popen(command, env=child_env, start_new_session=POSIX and KILL_CHILD_PROCESS_GROUP and not daemonizer)
        ibuslog("ibus-daemon proc=%s", proc)
        start = monotonic()

        def rec_new_pid() -> bool:
            if pidfile and os.path.exists(pidfile):
                new_pid = load_pid(pidfile)
                ibuslog(f"{new_pid=}")
                if new_pid:
                    ibuslog.info(f"ibus-daemon is running with pid {new_pid!r}")
                    register_pid(new_pid, command)
                    return True
            return False

        def poll_daemonizer() -> bool:
            poll = proc.poll()
            ibuslog(f"poll_daemonizer() {poll=}")
            if poll is not None and rec_new_pid():
                return False
            elapsed = monotonic() - start
            if elapsed < 5:
                return True
            if poll is None:
                ibuslog.warn("Warning: the daemonizer has failed to exit")
                stop_proc(proc, "daemonizer")
            else:
                ibuslog.warn("Warning: the ibus daemon PID file was not written")
            return False

        if daemonizer:
            scheduler.timeout_add(50, poll_daemonizer)
            return None
        else:
            procinfo = get_child_reaper().add_process(proc, "ibus-daemon", command, ignore=True, forget=False,
                                                      kill_process_group=POSIX and KILL_CHILD_PROCESS_GROUP)
            with procinfo.lock:
                if pidfile and not procinfo.dead:
                    procinfo.pidfile = pidfile
                    procinfo.pidinode = write_pid(pidfile, proc.pid)
            return procinfo

    return start()


class X11KeyboardManager(KeyboardManager):
    __slots__ = ("current_keyboard_group", "ibus_layouts", "ibus_procinfo", "input_method", "xkb")
    BACKEND = "x11"

    def __init__(self, server=None):
        KeyboardManager.__init__(self, server)
        self.xkb = False
        self.input_method = "keep"
        self.ibus_layouts: dict[str, Any] = {}
        self.ibus_procinfo: ProcInfo | None = None
        # the layout group we last set, or -1 when unknown:
        self.current_keyboard_group = -1

    def init(self, opts) -> None:
        super().init(opts)
        im = opts.input_method.lower()
        if im == "auto":
            ibus_daemon = which(IBUS_DAEMON_COMMAND.split(" ")[0])      # ie: "ibus-daemon"
            if ibus_daemon:
                im = "ibus"
            else:
                im = "none"
        self.input_method = im

    def setup(self):
        try:
            from xpra.x11.bindings.xkb import init_xkb_events
            xkb = init_xkb_events()
        except ImportError:
            log("init_xkb_events()", exc_info=True)
            xkb = False
        if not xkb:
            log.warn("Warning: XKB bindings not available, some keyboard features may not work")

        try:
            from xpra.x11.bindings.test import XTestBindings
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            from xpra.x11.xkbhelper import clean_keyboard_state
            with xlog:
                clean_keyboard_state()
            self.xkb = True
        except ImportError as e:
            log("setup()", exc_info=True)
            log.error("Error: unable to use keyboard")
            log.estr(e)
            self.input_method = ""
            self.xkb = False
        else:
            assert self.xkb
            with xlog:
                XTest = XTestBindings()
                X11Keyboard = X11KeyboardBindings()
                if not XTest.hasXTest():
                    log.error("Error: keyboard and mouse disabled without XTest support")
                elif not X11Keyboard.hasXkb():
                    log.error("Error: limited keyboard support without XKB")

        super().setup()

        ibuslog(f"input.setup() {EXPOSE_IBUS_LAYOUTS=}")
        if EXPOSE_IBUS_LAYOUTS:
            # wait for ibus to be ready to query the layouts:
            from xpra.keyboard.ibus import with_ibus_ready
            with_ibus_ready(self.query_ibus_layouts)

    def early_setup(self) -> None:
        # start the input method daemon before the server is confined,
        # since it needs to write to the home directory:
        self.input_method = configure_imsettings_env(self.input_method)
        if self.input_method == "ibus":
            if IBUS:
                env = self.server.get_child_env()
                self.ibus_procinfo = may_start_ibus(env, self)
            else:
                log.warn("Warning: ibus is disabled, but input-method uses it")
                log.warn(" either use another input method or start the daemon manually")

    def get_landlock_paths(self) -> dict[str, Sequence[str]]:
        if self.input_method != "ibus":
            return {}
        # so that we can read its address and connect to its socket:
        bus_dir, socket_dir = get_ibus_dirs()
        return {"read": (bus_dir, ), "socket": (socket_dir, )}

    def make_keyboard_device(self):
        if self.xkb:
            from xpra.x11.server.xtest_keyboard import XTestKeyboardDevice
            return XTestKeyboardDevice()
        return super().make_keyboard_device()

    def query_ibus_layouts(self) -> None:
        try:
            from xpra.keyboard.ibus import query_ibus
        except ImportError as e:
            ibuslog(f"no ibus module: {e}")
        else:
            self.ibus_layouts = dict((k, v) for k, v in query_ibus().items() if k.startswith("engine"))
            import threading
            from xpra.util.str_fn import Ellipsizer
            ibuslog("loaded ibus layouts from %s: %s", threading.current_thread(),
                    Ellipsizer(self.ibus_layouts))

    def cleanup(self) -> None:
        super().cleanup()
        if self.xkb:
            from xpra.x11.xkbhelper import clean_keyboard_state
            with xswallow:
                clean_keyboard_state()
        self.current_keyboard_group = -1

    def clear_keys_pressed(self, *args) -> None:
        super().clear_keys_pressed(*args)
        # `clean_keyboard_state` has reset the layout group behind our back:
        self.current_keyboard_group = -1

    def late_cleanup(self, stop=True) -> None:
        if not stop or not IBUS:
            return
        procinfo = self.ibus_procinfo
        if procinfo is None and (pid := load_pid(ibus_pid_file())):
            reaper = get_child_reaper()
            procinfo = reaper.get_proc_info(pid)
            if procinfo is None:
                # Startup registration may still be pending, or this is an older daemon.
                procinfo = reaper.add_pid(pid, "ibus-daemon", shlex.split(IBUS_DAEMON_COMMAND), ignore=True,
                                          kill_process_group=ibus_has_process_group(pid))
        if procinfo:
            stop_child_process(procinfo.process, "ibus-daemon")

    def send_initial_data(self, ss) -> None:
        self.send_ibus_layouts(ss)

    def send_ibus_layouts(self, ss):
        send_ibus_layouts = getattr(ss, "send_ibus_layouts", noop)
        ibuslog(f"{send_ibus_layouts=}")
        if not send_ibus_layouts:
            return

        # wait for ibus, so we will have the layouts if they exist
        def ibus_is_ready() -> None:
            send_ibus_layouts(self.ibus_layouts)
        from xpra.keyboard.ibus import with_ibus_ready
        with_ibus_ready(ibus_is_ready)

    def get_keyboard_info(self) -> dict[str, Any]:
        info = super().get_keyboard_info()
        if EXPOSE_IBUS_LAYOUTS and self.ibus_layouts:
            info["ibus"] = self.ibus_layouts
        return info

    def get_keyboard_config(self, props=None):
        if not self.xkb:
            return None
        p = typedict(props or {})
        from xpra.x11.server.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        keyboard_config.enabled = p.boolget("keyboard", True)
        keyboard_config.parse_options(p)
        keyboard_config.parse_layout(p)
        log("get_keyboard_config(..)=%s", keyboard_config)
        return keyboard_config

    def set_keyboard_layout_group(self, grp: int) -> None:
        kc = self.config
        if not kc:
            log(f"set_keyboard_layout_group({grp}) ignored, no config")
            return
        if not kc.layout_groups:
            log(f"set_keyboard_layout_group({grp}) ignored, no layout groups support")
            # not supported by the client that owns the current keyboard config,
            # so make sure we stick to the default group:
            grp = 0
        from xpra.x11.bindings.keyboard import X11KeyboardBindings
        if not X11KeyboardBindings().hasXkb():
            log(f"set_keyboard_layout_group({grp}) ignored, no Xkb support")
            return
        if grp < 0:
            grp = 0
        if self.current_keyboard_group == grp:
            log(f"set_keyboard_layout_group({grp}) ignored, value unchanged")
            return
        log(f"set_keyboard_layout_group({grp}) config={self.config}, {self.current_keyboard_group=}")
        from xpra.x11.error import xsync, XError
        try:
            with xsync:
                self.current_keyboard_group = X11KeyboardBindings().set_layout_group(grp)
        except XError as e:
            log(f"set_keyboard_layout_group({grp})", exc_info=True)
            log.error(f"Error: failed to set keyboard layout group {grp}")
            log.estr(e)

    def set_keymap(self, server_source, force=False) -> None:
        if server_source and getattr(server_source, "effective_readonly", lambda: self.server.readonly)():
            return

        def reenable_keymap_changes(*args) -> bool:
            log("reenable_keymap_changes(%s)", args)
            self.keymap_changing_timer = 0
            self._keys_changed()
            return False

        # prevent _keys_changed() from firing:
        # (using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
        if not self.keymap_changing_timer:
            # use idle_add to give all the pending
            # events a chance to run first (and get ignored)
            self.keymap_changing_timer = self.timeout_add(100, reenable_keymap_changes)
        # if sharing, don't set the keymap, translate the existing one:
        other_kb_clients = self.get_sources_by_type(KeyboardConnection, server_source)
        translate_only = any(ss.keyboard_input for ss in other_kb_clients)
        log("set_keymap(%s, %s) translate_only=%s", server_source, force, translate_only)
        with xsync:
            # pylint: disable=access-member-before-definition
            server_source.set_keymap(self.config, self.config_hash, self.keys_pressed, force, translate_only)
            self.set_current_config(server_source.keyboard_config)
        # the keymap may have been replaced and the layout group reset:
        self.current_keyboard_group = -1
        # setxkbmap resets X11 autorepeat to defaults, so re-apply:
        if self.key_repeat_delay > 0 and self.key_repeat_interval > 0:
            self.set_keyboard_repeat(self.key_repeat_delay, self.key_repeat_interval)

    def set_default_keymap(self, server_source) -> None:
        super().set_default_keymap(server_source)
        # `clean_keyboard_state` has reset the layout group:
        self.current_keyboard_group = -1
