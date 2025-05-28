# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import shlex
import os.path
from time import monotonic
from subprocess import Popen, PIPE
from threading import Event
from typing import Any
from collections.abc import Sequence

from xpra.os_util import OSX, POSIX, gi_import, is_container
from xpra.util.io import pollwait
from xpra.util.env import envbool, osexpand
from xpra.util.thread import start_thread
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio", "pulseaudio")

PRIVATE_PULSEAUDIO = envbool("XPRA_PRIVATE_PULSEAUDIO", not is_container())

PULSE_DEVICE_DEFAULTS: dict[str, str] = {
    "XPRA_PULSE_SOURCE_DEVICE_NAME": "Xpra-Speaker",
    "XPRA_PULSE_SINK_DEVICE_NAME": "Xpra-Microphone",
}

PA_ENV_WHITELIST = (
    "DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SESSION_BUS_WINDOWID",
    "DISPLAY", "HOME", "HOSTNAME", "LANG", "PATH",
    "PWD", "SHELL", "XAUTHORITY",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
    "XPRA_PULSE_SOURCE_DEVICE_NAME", "XPRA_PULSE_SINK_DEVICE_NAME",
)


def pulseaudio_warning() -> None:
    from xpra.platform.info import get_username
    log.warn("Warning: pulseaudio has terminated shortly after startup.")
    log.warn(" pulseaudio is limited to a single instance per user account,")
    log.warn(" and one may be running already for user '%s'.", get_username())
    log.warn(" To avoid this warning, either fix the pulseaudio command line")
    log.warn(" or use the 'pulseaudio=no' option.")


class PulseaudioServer(StubServerMixin):
    """
    Handles starting and configuring pulseaudio
    """
    PREFIX = "pulseaudio"

    def __init__(self):
        self.pulseaudio_init_done = Event()
        self.pulseaudio_init_done.set()
        self.pulseaudio = False
        self.pulseaudio_command = ""
        self.pulseaudio_configure_commands = []
        self.pulseaudio_proc: Popen | None = None
        self.pulseaudio_private_dir = ""
        self.pulseaudio_server_socket = ""
        self.pulseaudio_started_at = 0.0

    def init(self, opts) -> None:
        self.pulseaudio = opts.pulseaudio
        self.pulseaudio_command = opts.pulseaudio_command
        self.pulseaudio_configure_commands = opts.pulseaudio_configure_commands

    def threaded_setup(self) -> None:
        # the setup code will mostly be waiting for subprocesses to run,
        # so do it in a separate thread
        # and just wait for the results where needed:
        start_thread(self.init_pulseaudio, "init-pulseaudio", True)
        # we spawn another thread here to avoid blocking threaded init

    def cleanup(self) -> None:
        self.pulseaudio_init_done.wait(5)
        self.cleanup_pulseaudio()

    def get_info(self, _proto) -> dict[str, Any]:
        if self.pulseaudio is False:
            return {}
        self.pulseaudio_init_done.wait(5)
        return {PulseaudioServer.PREFIX: self.get_pulseaudio_info()}

    def configure_pulse_dirs(self):
        if not POSIX or OSX:
            return
        from xpra.platform.posix.paths import _get_xpra_runtime_dir, get_runtime_dir
        rd = osexpand(get_runtime_dir())
        if not rd or not os.path.exists(rd) or not os.path.isdir(rd):
            log.warn("Warning: the runtime directory '%s' does not exist,", rd)
            log.warn(" cannot start a pulseaudio server")
            return
        # this default location is shared by all sessions for the same user:
        pulse_dir = os.path.join(rd, "pulse")
        # 3) with a private pulseaudio server, each xpra session can have its own server,
        #    since we create a pulseaudio directory for each display:
        if PRIVATE_PULSEAUDIO:
            # pylint: disable=import-outside-toplevel
            if not rd or not os.path.exists(rd) or not os.path.isdir(rd):
                log.warn("Warning: the runtime directory '%s' does not exist,", rd)
                log.warn(" cannot start a private pulseaudio server")
            else:
                xpra_rd = os.environ.get("XPRA_SESSION_DIR", _get_xpra_runtime_dir())
                assert xpra_rd, "bug: no xpra runtime dir"
                display = os.environ.get("DISPLAY", "").lstrip(":")
                if xpra_rd.find(f"/{display}/"):
                    # this is already a per-display directory,
                    # no need to include the display name again:
                    # ie: /run/user/1000/xpra/10/
                    self.pulseaudio_private_dir = osexpand(xpra_rd, subs=os.environ)
                else:
                    pulse_dirname = f"pulse-{display}"
                    self.pulseaudio_private_dir = osexpand(os.path.join(xpra_rd, pulse_dirname), subs=os.environ)
                if not os.path.exists(self.pulseaudio_private_dir):
                    os.mkdir(self.pulseaudio_private_dir, 0o700)
                pulse_dir = os.path.join(self.pulseaudio_private_dir, "pulse")
        if not os.path.exists(pulse_dir):
            os.mkdir(pulse_dir, mode=0o700)
        # ie: /run/user/1000/xpra/10/pulse/native
        # or /run/user/1000/pulse/native
        self.pulseaudio_server_socket = os.path.join(pulse_dir, "native")

    def init_pulseaudio(self) -> None:
        log("init_pulseaudio() pulseaudio=%s, pulseaudio_command=%s", self.pulseaudio, self.pulseaudio_command)
        if self.pulseaudio is False:
            return
        if not self.pulseaudio_command:
            log.warn("Warning: pulseaudio command is not defined")
            return
        try:
            self.pulseaudio_init_done.clear()
            self.do_init_pulseaudio()
        finally:
            self.pulseaudio_init_done.set()

    def do_init_pulseaudio(self) -> None:
        # environment initialization:
        # 1) make sure that the audio subprocess will use the devices
        #    we define in the pulseaudio command
        #    (it is too difficult to parse the pulseaudio_command,
        #    so we just hope that it matches this):
        #    Note: speaker is the source and microphone the sink,
        #    because things are reversed on the server.
        os.environ.update(PULSE_DEVICE_DEFAULTS)
        # 2) whitelist the env vars that pulseaudio may use:
        env = {k: v for k, v in self.get_child_env().items() if k in PA_ENV_WHITELIST}
        self.configure_pulse_dirs()
        if self.pulseaudio_private_dir:
            env["XDG_RUNTIME_DIR"] = self.pulseaudio_private_dir
        env["XPRA_PULSE_SERVER"] = self.pulseaudio_server_socket
        cmd = shlex.split(self.pulseaudio_command)
        cmd = list(osexpand(x, subs=env) for x in cmd)
        # find the absolute path to the command:
        pa_cmd = cmd[0]
        if not os.path.isabs(pa_cmd):
            pa_path = ""
            for x in os.environ.get("PATH", "").split(os.path.pathsep):
                t = os.path.join(x, pa_cmd)
                if os.path.exists(t):
                    pa_path = t
                    break
            if not pa_path:
                msg = f"pulseaudio not started: {pa_cmd!r} command not found"
                if self.pulseaudio is None:
                    log.info(msg)
                else:
                    log.warn(msg)
                self.clean_pulseaudio_private_dir()
                return
            cmd[0] = pa_cmd
        self.pulseaudio_started_at = monotonic()

        try:
            log("pulseaudio cmd=%s", " ".join(cmd))
            log("pulseaudio env=%s", env)
            self.pulseaudio_proc = Popen(cmd, env=env)
        except Exception as e:
            log("Popen(%s)", cmd, exc_info=True)
            log.error("Error: failed to start pulseaudio:")
            log.estr(e)
            self.clean_pulseaudio_private_dir()
            return
        self.add_process(self.pulseaudio_proc, "pulseaudio", cmd, ignore=True, callback=self.pulseaudio_ended)
        if self.pulseaudio_proc:
            from xpra.scripts.session import save_session_file
            save_session_file("pulseaudio.pid", "%s" % self.pulseaudio_proc.pid)
            log.info("pulseaudio server started with pid %s", self.pulseaudio_proc.pid)
            if self.pulseaudio_server_socket:
                log.info(" %r", self.pulseaudio_server_socket)
                os.environ["PULSE_SERVER"] = "unix:%s" % self.pulseaudio_server_socket
            GLib.timeout_add(2 * 1000, self.configure_pulse, env)

    def configure_pulse(self, env: dict) -> None:
        p = self.pulseaudio_proc
        if p is None or p.poll() is not None:
            return
        for i, x in enumerate(self.pulseaudio_configure_commands):
            proc = Popen(x, env=env, shell=True)
            self.add_process(proc, "pulseaudio-configure-command-%i" % i, x, ignore=True)

    def pulseaudio_ended(self, proc) -> None:
        log("pulseaudio_ended(%s) pulseaudio_proc=%s, returncode=%s, closing=%s",
            proc, self.pulseaudio_proc, proc.returncode, self._closing)
        if self.pulseaudio_proc is None or self._closing:
            # cleared by cleanup already, ignore
            return
        elapsed = monotonic() - self.pulseaudio_started_at
        if elapsed < 2:
            GLib.timeout_add(1000, pulseaudio_warning)
        else:
            log.warn("Warning: the pulseaudio server process has terminated after %i seconds", int(elapsed))
        self.pulseaudio_proc = None

    def cleanup_pulseaudio(self) -> None:
        self.pulseaudio_init_done.wait(5)
        proc = self.pulseaudio_proc
        if not proc:
            return
        log("cleanup_pa() process.poll()=%s, pid=%s", proc.poll(), proc.pid)
        if self.is_child_alive(proc):
            self.pulseaudio_proc = None
            log.info("stopping pulseaudio with pid %s", proc.pid)
            try:
                # first we try pactl (required on Ubuntu):
                cmd = ["pactl", "exit"]
                proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
                self.add_process(proc, "pactl exit", cmd, True)
                r = pollwait(proc)
                # warning: pactl will return 0 whether it succeeds or not...
                # but we can't kill the process because Ubuntu starts a new one
                if r != 0 and self.is_child_alive(proc):
                    # fallback to using SIGINT:
                    proc.terminate()
            except Exception as e:
                log.warn("cleanup_pulseaudio() error stopping %s", proc, exc_info=True)
                # only log the full stacktrace if the process failed to terminate:
                if self.is_child_alive(proc):
                    log.error("Error: stopping pulseaudio: %s", e, exc_info=True)
            if self.pulseaudio_server_socket and self.is_child_alive(proc):
                # wait for the pulseaudio process to exit,
                # it will delete the socket:
                log("pollwait()=%s", pollwait(proc))
        if self.pulseaudio_server_socket and not self.is_child_alive(proc):
            # wait for the socket to get cleaned up
            # (it should be removed by the pulseaudio server as it exits)
            import time
            now = monotonic()
            while (monotonic() - now) < 1 and os.path.exists(self.pulseaudio_server_socket):
                time.sleep(0.1)
        self.clean_pulseaudio_private_dir()
        if not self.is_child_alive(proc):
            self.do_clean_session_files("pulseaudio.pid")

    def clean_pulseaudio_private_dir(self) -> None:
        if self.pulseaudio_private_dir:
            if os.path.exists(self.pulseaudio_server_socket):
                log.warn("Warning: the pulseaudio private socket file still exists:")
                log.warn(" '%s'", self.pulseaudio_server_socket)
                log.warn(" the private pulseaudio directory containing it will not be removed")
            else:
                import glob
                pulse = os.path.join(self.pulseaudio_private_dir, "pulse")
                native = os.path.join(pulse, "native")
                dirs = []
                dbus_dirs = glob.glob("%s/dbus-*" % self.pulseaudio_private_dir)
                if len(dbus_dirs) == 1:
                    dbus_dir = dbus_dirs[0]
                    if os.path.isdir(dbus_dir):
                        services_dir = os.path.join(dbus_dir, "services")
                        dirs.append(services_dir)
                        dirs.append(dbus_dir)
                dirs += [native, pulse]
                path = None
                try:
                    for d in dirs:
                        path = os.path.abspath(d)
                        log("removing private directory '%s'", path)
                        if os.path.exists(path) and os.path.isdir(path):
                            os.rmdir(path)
                    log.info("removing private directory '%s'", self.pulseaudio_private_dir)
                except OSError as e:
                    log("cleanup_pulseaudio() error removing '%s'", path, exc_info=True)
                    log.error("Error: failed to cleanup the pulseaudio private directory")
                    log.error(" '%s'", self.pulseaudio_private_dir)
                    log.estr(e)
                    try:
                        files = os.listdir(path)
                        if files:
                            log.error(f" found %i files in {path!r}:", len(files))
                            for f in files:
                                log.error(f" - {f!r}")
                    except OSError:
                        log.error("cleanup_pulseaudio() error accessing '%s'", path, exc_info=True)

    def query_pulseaudio_properties(self) -> None:
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.audio.pulseaudio.util import set_icon_path, get_info as get_pa_info
            pa_info = get_pa_info()
            log("pulseaudio info=%s", pa_info)
            self.audio_properties.update(pa_info)
            set_icon_path(get_icon_filename("xpra.png"))
        except ImportError as e:
            if POSIX and not OSX:
                log.warn("Warning: failed to set pulseaudio tagging icon:")
                log.warn(" %s", e)

    def get_pulseaudio_info(self) -> dict[str, Any]:
        info: dict[str, str | Sequence[str] | int] = {
            "command": self.pulseaudio_command,
            "configure-commands": self.pulseaudio_configure_commands,
        }
        if self.pulseaudio_proc and self.pulseaudio_proc.poll() is None:
            info["pid"] = self.pulseaudio_proc.pid
        if self.pulseaudio_private_dir and self.pulseaudio_server_socket:
            info["private-directory"] = self.pulseaudio_private_dir
            info["private-socket"] = self.pulseaudio_server_socket
        return info
