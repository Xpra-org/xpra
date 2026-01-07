# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from typing import Any
from collections.abc import Callable
from time import monotonic
from subprocess import Popen

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.pid import load_pid, kill_pid
from xpra.util.env import envbool
from xpra.util.io import find_libexec_command, which
from xpra.util.objects import typedict
from xpra.server.subsystem.keyboard import KeyboardServer
from xpra.x11.error import xsync, xswallow, xlog
from xpra.log import Logger

log = Logger("x11", "server", "keyboard")
ibuslog = Logger("keyboard", "ibus")

GLib = gi_import("GLib")

IBUS_DAEMON_COMMAND = os.environ.get("XPRA_IBUS_DAEMON_COMMAND",
                                     "ibus-daemon --xim --verbose --replace --panel=disable --desktop=xpra")
EXPOSE_IBUS_LAYOUTS = envbool("XPRA_EXPOSE_IBUS_LAYOUTS", True)


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


def may_start_ibus(env: dict[str, str]):
    # maybe we are inheriting one from a dead session?
    daemonizer = find_libexec_command("daemonizer")
    pidfile = ibus_pid_file()
    ibus_daemon_pid = load_pid(pidfile)
    ibuslog(f"may_start_ibus({env}) {ibus_daemon_pid=}, {pidfile=!r}, {daemonizer=!r}")
    pidfile_exists = os.path.exists(pidfile)
    pid_exists = os.path.exists(f"/proc/{ibus_daemon_pid}")
    if ibus_daemon_pid and pid_exists:
        pid = load_pid(pidfile)
        if pid > 0:
            ibuslog(f"ibus-daemon is already running with pid {pid!r}")
            return
    if pidfile_exists and os.path.exists("/proc"):
        try:
            os.unlink(pidfile)
        except OSError as e:
            log.error(f"Warning: unable to delete old ibus pid file {pidfile!r}")
            log.estr(e)
            # don't trust the pidfile value from now on:
            pidfile = ""

    # start it late:
    def late_start():
        command = shlex.split(IBUS_DAEMON_COMMAND)
        ibuslog(f"starting ibus: {IBUS_DAEMON_COMMAND!r}")
        if daemonizer:
            from xpra.platform.paths import get_python_execfile_command
            command = get_python_execfile_command() + [daemonizer, pidfile, "--"] + command
            ibuslog(" using daemonizer: %r", command)
        proc = Popen(command, env=env)
        ibuslog("ibus-daemon proc=%s", proc)
        start = monotonic()
        from xpra.util.child_reaper import get_child_reaper

        def rec_new_pid() -> None:
            if pidfile and os.path.exists(pidfile):
                new_pid = load_pid(pidfile)
                ibuslog(f"{new_pid=}")
                if new_pid:
                    ibuslog.info(f"ibus-daemon is running with pid {new_pid!r}")
                    procinfo = get_child_reaper().add_pid(new_pid, "ibus-daemon", command=command,
                                                          ignore=True, forget=False)
                    procinfo.pidfile = pidfile

        def poll_daemonizer() -> bool:
            poll = proc.poll()
            ibuslog(f"poll_daemonizer() {poll=}")
            if poll is not None:
                rec_new_pid()
                return False
            elapsed = monotonic() - start
            if elapsed < 5:
                return True
            ibuslog.warn("Warning: the daemonizer has failed to exit")
            proc.terminate()
            return False

        if daemonizer:
            GLib.timeout_add(50, poll_daemonizer)
        else:
            get_child_reaper().add_process(proc, "ibus-daemon", command,
                                           ignore=True, forget=False)

    GLib.idle_add(late_start)


class X11KeyboardServer(KeyboardServer):

    def __init__(self):
        KeyboardServer.__init__(self)
        self.readonly = False
        self.xkb = False
        self.input_method = "keep"
        self.ibus_layouts: dict[str, Any] = {}
        self.current_keyboard_group = 0

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
            self.input_method = configure_imsettings_env(self.input_method)
            if self.input_method == "ibus":
                get_env: Callable[[], dict[str, str]] = getattr(self, "get_child_env", os.environ.copy)
                env = get_env()
                may_start_ibus(env)

        super().setup()

        ibuslog(f"input.setup() {EXPOSE_IBUS_LAYOUTS=}")
        if EXPOSE_IBUS_LAYOUTS:
            # wait for ibus to be ready to query the layouts:
            from xpra.keyboard.ibus import with_ibus_ready
            with_ibus_ready(self.query_ibus_layouts)

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

    def late_cleanup(self, stop=True) -> None:
        if not stop:
            return
        pidfile = ibus_pid_file()
        pid = load_pid(pidfile)
        if pid:
            kill_pid(pid, "ibus-daemon")

    def send_initial_data(self, ss, caps, send_ui: bool, share_count: int) -> None:
        if send_ui:
            self.send_ibus_layouts(ss)

    def send_ibus_layouts(self, ss):
        send_ibus_layouts = getattr(ss, "send_ibus_layouts", noop)
        ibuslog(f"{send_ibus_layouts=}")
        if send_ibus_layouts == noop:
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

    def set_backend(self, backend: str, name: str) -> None:
        if backend == "ibus" and name:
            from xpra.keyboard.ibus import set_engine, get_engine_layout_spec
            if set_engine(name):
                ibuslog(f"ibus set engine to {name!r}")
                layout, variant, options = get_engine_layout_spec()
                ibuslog(f"ibus layout: {layout} {variant=}, {options=}")

    def set_keyboard_layout_group(self, grp: int) -> None:
        kc = self.keyboard_config
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
        log(f"set_keyboard_layout_group({grp}) config={self.keyboard_config}, {self.current_keyboard_group=}")
        from xpra.x11.error import xsync, XError
        try:
            with xsync:
                self.current_keyboard_group = X11KeyboardBindings().set_layout_group(grp)
        except XError as e:
            log(f"set_keyboard_layout_group({grp})", exc_info=True)
            log.error(f"Error: failed to set keyboard layout group {grp}")
            log.estr(e)

    def set_keymap(self, server_source, force=False) -> None:
        if self.readonly:
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
            from xpra.os_util import gi_import
            GLib = gi_import("GLib")
            self.keymap_changing_timer = GLib.timeout_add(100, reenable_keymap_changes)
        # if sharing, don't set the keymap, translate the existing one:
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s != server_source and s.ui_client]
        translate_only = len(other_ui_clients) > 0
        log("set_keymap(%s, %s) translate_only=%s", server_source, force, translate_only)
        with xsync:
            # pylint: disable=access-member-before-definition
            server_source.set_keymap(self.keyboard_config, self.keys_pressed, force, translate_only)
            self.keyboard_config = server_source.keyboard_config
