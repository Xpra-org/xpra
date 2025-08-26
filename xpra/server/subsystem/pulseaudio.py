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

from xpra.os_util import OSX, WIN32, POSIX, gi_import, is_container, getuid, getgid
from xpra.platform.paths import get_system_conf_dirs
from xpra.util.io import pollwait, is_writable, which
from xpra.util.env import envbool, osexpand
from xpra.util.pid import load_pid, kill_pid
from xpra.util.str_fn import csv
from xpra.util.system import is_X11
from xpra.util.thread import start_thread
from xpra.scripts.parsing import enabled_or_auto
from xpra.scripts.session import clean_session_files, session_file_path, pidexists
from xpra.server import features
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio", "pulseaudio")

PRIVATE_PULSEAUDIO = envbool("XPRA_PRIVATE_PULSEAUDIO", not is_container())

PULSE_SOURCE = "Xpra-Speaker"
PULSE_SINK = "Xpra-Microphone"

PULSE_DEVICE_DEFAULTS: dict[str, str] = {
    "XPRA_PULSE_SOURCE_DEVICE_NAME": PULSE_SOURCE,
    "XPRA_PULSE_SINK_DEVICE_NAME": PULSE_SINK,
}

PA_ENV_WHITELIST = (
    "DISPLAY", "HOME", "HOSTNAME", "LANG", "PATH",
    "PWD", "SHELL", "XAUTHORITY",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
    "XPRA_PULSE_SOURCE_DEVICE_NAME", "XPRA_PULSE_SINK_DEVICE_NAME",
    "PULSE_CONFIG_PATH", "PULSE_STATE_PATH", "PULSE_RUNTIME_PATH", "PULSE_COOKIE",
    "PULSE_SOURCE", "PULSE_SINK", "PULSE_SERVER",
)


def pulseaudio_warning() -> None:
    from xpra.platform.info import get_username
    log.warn("Warning: pulseaudio has terminated shortly after startup.")
    log.warn(" pulseaudio is limited to a single instance per user account,")
    log.warn(" and one may be running already for user '%s'.", get_username())
    log.warn(" To avoid this warning, either fix the pulseaudio command line")
    log.warn(" or use the 'pulseaudio=no' option.")


def get_default_pulseaudio_command(pulseaudio_server_socket="$XPRA_PULSE_SERVER") -> list[str]:
    if WIN32 or OSX:
        return []

    cmd = [
        "pulseaudio", "--start", "-n", "--daemonize=false", "--system=false",
        "--exit-idle-time=-1",
        "--load=module-suspend-on-idle",
        "--log-level=%i" % (2 + 2 * int(log.is_debug_enabled())),
        "--log-target=stderr",
    ]

    def description(desc: str) -> str:
        return f"device.description={desc}"

    def load(name: str, options: dict[str, str]) -> None:
        args = " ".join([f"--load={name}"] + [f"{n}={v}" for n, v in options.items()])
        cmd.append(args)

    load("module-null-sink",
         {
             "sink_name": "Xpra-Speaker",
             "sink_properties": description("Xpra-Speaker"),
         })
    load("module-null-sink",
         {
             "sink_name": "Xpra-Microphone",
             "sink_properties": description("Xpra-Microphone"),
         })
    load("module-remap-source",
         {
             "source_name": "Xpra-Mic-Source",
             "source_properties": description("Xpra-Mic-Source"),
             "master": "Xpra-Microphone.monitor",
             "channels": "1"
         })
    load("module-native-protocol-unix",
         {
             "socket": pulseaudio_server_socket,
             "auth-cookie": "$PULSE_COOKIE",
             "auth-cookie-enabled": int(not is_container()),
         })
    if is_X11():
        load("module-x11-publish", {
            "display": "$DISPLAY",
            "cookie": "$PULSE_COOKIE",
        })
    if features.dbus:
        load("module-dbus-protocol", {})
    from xpra.util.env import envbool
    if not envbool("XPRA_PULSEAUDIO_SHM", not is_container()):
        cmd.append("--disable-shm=yes")
    if not envbool("XPRA_PULSEAUDIO_MEMFD", True):
        cmd.append("--enable-memfd=no")
    if not envbool("XPRA_PULSEAUDIO_REALTIME", True):
        cmd.append("--realtime=no")
    if not envbool("XPRA_PULSEAUDIO_HIGH_PRIORITY", True):
        cmd.append("--high-priority=no")

    # run our configure script:
    xpra_pa = get_xpra_pulse_script()
    log("get_xpra_pulse_script()=%s", xpra_pa)
    if xpra_pa:
        cmd.append(f"--file={xpra_pa}")
    return cmd


def get_xpra_pulse_script() -> str:
    for d in get_system_conf_dirs():
        pulse_dir = os.path.join(d, "pulse")
        if not os.path.exists(pulse_dir):
            continue
        script = os.path.join(pulse_dir, "xpra.pa")
        if os.path.exists(script):
            return script
    return ""


class PulseaudioServer(StubServerMixin):
    """
    Handles starting and configuring pulseaudio
    """
    PREFIX = "pulseaudio"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.pulseaudio_init_done = Event()
        self.pulseaudio_init_done.set()
        self.pulseaudio = False
        self.pulseaudio_command = ""
        self.pulseaudio_configure_commands = ()
        self.pulseaudio_pid = 0
        self.pulseaudio_proc: Popen | None = None
        self.pulseaudio_private_dir = ""
        self.pulseaudio_server_dir = ""
        self.pulseaudio_server_socket = ""
        self.pulseaudio_started_at = 0.0

    def init(self, opts) -> None:
        self.pulseaudio = opts.pulseaudio
        self.pulseaudio_command = opts.pulseaudio_command
        pcc = csv(opts.pulseaudio_configure_commands)
        if pcc == "auto":
            from xpra.platform.features import DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS
            self.pulseaudio_configure_commands = DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS
        elif pcc == "none":
            self.pulseaudio_configure_commands = ()
        else:
            self.pulseaudio_configure_commands = tuple(x.strip() for x in opts.pulseaudio_configure_commands if x.strip())

    def threaded_setup(self) -> None:
        # the setup code will mostly be waiting for subprocesses to run,
        # so do it in a separate thread
        # and just wait for the results where needed:
        start_thread(self.init_pulseaudio, "init-pulseaudio", True)
        # we spawn another thread here to avoid blocking threaded init

    def late_cleanup(self, stop=True) -> None:
        if stop:
            self.pulseaudio_init_done.wait(5)
            self.cleanup_pulseaudio()

    def get_info(self, _proto) -> dict[str, Any]:
        # noinspection PySimplifyBooleanCheck
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
                display_no = os.environ.get("DISPLAY", "").lstrip(":")
                if xpra_rd.find(f"/{display_no}/"):
                    # this is already a per-display directory,
                    # no need to include the display name again:
                    # ie: /run/user/1000/xpra/10/
                    base_dir = osexpand(xpra_rd, subs=os.environ)
                else:
                    pulse_dirname = f"pulse-{display_no}"
                    base_dir = osexpand(os.path.join(xpra_rd, pulse_dirname), subs=os.environ)
                    self.pulseaudio_private_dir = base_dir
                if not os.path.exists(base_dir):
                    os.mkdir(base_dir, 0o700)
                pulse_dir = os.path.join(base_dir, "pulse")
        if not os.path.exists(pulse_dir):
            os.mkdir(pulse_dir, mode=0o700)
        self.pulseaudio_server_dir = pulse_dir
        # ie: /run/user/1000/xpra/10/pulse/native
        # or /run/user/1000/pulse/native
        self.pulseaudio_server_socket = os.path.join(pulse_dir, "native")
        log("configure_pulse_dirs() pulse_dir=%s, socket=%s", self.pulseaudio_server_dir, self.pulseaudio_server_socket)

    def init_pulseaudio(self) -> None:
        log("init_pulseaudio() pulseaudio=%s, pulseaudio_command=%r",
            enabled_or_auto(self.pulseaudio), self.pulseaudio_command)
        # noinspection PySimplifyBooleanCheck
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

    def get_pulse_env(self) -> dict[str, str]:
        # ensure that we use our own pulse source and sink:
        env: dict[str, str] = {
            "PULSE_SOURCE": PULSE_SOURCE,
            "PULSE_SINK": PULSE_SINK,
        }
        # pulseaudio will not start if it cannot write to the home directory, see:
        # https://serverfault.com/a/631549/63324
        # https://github.com/gavv/gavv.github.io/blob/main/content/articles/009-pulseaudio-under-the-hood.md#user-directories
        # Under "What environment variables does PulseAudio care about?":
        # https://www.freedesktop.org/wiki/Software/PulseAudio/FAQ/
        # (fails to list any of the environment variables we use here)
        home_dir = os.environ.get("HOME", "")
        home_rw = is_writable(home_dir, getuid(), getgid())
        log(f"rw({home_dir})={home_rw}")
        if not home_rw:
            server_dir = self.pulseaudio_server_dir
            if "PULSE_CONFIG_PATH" not in os.environ:
                env["PULSE_CONFIG_PATH"] = server_dir
            if "PULSE_STATE_PATH" not in os.environ:
                env["PULSE_STATE_PATH"] = server_dir
            if "PULSE_RUNTIME_PATH" not in os.environ:
                env["PULSE_RUNTIME_PATH"] = self.pulseaudio_private_dir or server_dir
            if "PULSE_COOKIE" not in os.environ:
                env["PULSE_COOKIE"] = os.path.join(server_dir, "cookie")
        log("get_pulse_env()=%s", env)
        return env

    def get_pulseaudio_server_env(self) -> dict[str, str]:
        whitelist = list(PA_ENV_WHITELIST)
        if features.dbus:
            whitelist += ["DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SESSION_BUS_WINDOWID"]
        env = {k: v for k, v in os.environ.items() if k in whitelist}
        env.update(self.get_pulse_env())
        if self.pulseaudio_private_dir:
            env["XDG_RUNTIME_DIR"] = self.pulseaudio_private_dir
        return env

    def get_child_env(self) -> dict[str, str]:
        """
        Returns the environment variables that should be passed to child processes.
        """
        env = super().get_child_env()
        env.update(self.get_pulse_env())
        return env

    def do_init_pulseaudio(self) -> None:
        pidfile = session_file_path("pulseaudio.pid")
        pid = load_pid(pidfile)
        if pidexists(pid):
            log.info("found existing pulseaudio server process with pid %i", pid)
            self.pulseaudio_pid = pid
            return
        # environment initialization:
        # 1) make sure that the audio subprocess will use the devices
        #    we define in the pulseaudio command
        #    (it is too difficult to parse the pulseaudio_command,
        #    so we just hope that it matches this):
        #    Note: speaker is the source and microphone the sink,
        #    because things are reversed on the server.
        os.environ.update(PULSE_DEVICE_DEFAULTS)
        self.configure_pulse_dirs()

        if self.pulseaudio_command == "auto":
            cmd = get_default_pulseaudio_command(self.pulseaudio_server_socket)
        else:
            cmd = shlex.split(self.pulseaudio_command)

        env = self.get_pulseaudio_server_env()
        cmd = list(osexpand(x, subs=env) for x in cmd)
        # find the absolute path to the command:
        pa_cmd = cmd[0]
        if not os.path.isabs(pa_cmd):
            pa_path = which(pa_cmd)
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
            log("pulseaudio cmd=%s", shlex.join(cmd))
            log("pulseaudio env=%s", env)
            self.pulseaudio_proc = Popen(cmd, env=env)
        except OSError as e:
            log("Popen(%s)", cmd, exc_info=True)
            log.error("Error: failed to start pulseaudio:")
            log.estr(e)
            self.clean_pulseaudio_private_dir()
            return
        self.add_process(self.pulseaudio_proc, "pulseaudio", cmd, ignore=True, callback=self.pulseaudio_ended)
        if self.pulseaudio_proc:
            from xpra.scripts.session import save_session_file
            save_session_file("pulseaudio.pid", "%s" % self.pulseaudio_proc.pid)
            self.session_files.append("pulseaudio.pid")
            log.info("pulseaudio server started with pid %s", self.pulseaudio_proc.pid)
            if self.pulseaudio_server_socket:
                log.info(" %r", self.pulseaudio_server_socket)
                os.environ["PULSE_SERVER"] = "unix:%s" % self.pulseaudio_server_socket
            GLib.timeout_add(2 * 1000, self.configure_pulse, env)

    def configure_pulse(self, env: dict[str, str]) -> None:
        p = self.pulseaudio_proc
        if p is None or p.poll() is not None:
            return
        for i, x in enumerate(self.pulseaudio_configure_commands):
            proc = Popen(x, env=env, shell=True)
            self.add_process(proc, "pulseaudio-configure-command-%i" % i, x, ignore=True)

    def pulseaudio_ended(self, proc: Popen) -> None:
        log("pulseaudio_ended(%s) pulseaudio_proc=%s, returncode=%s, closing=%s",
            proc, self.pulseaudio_proc, proc.returncode, self._closing)
        self.pulseaudio_pid = 0
        if self.pulseaudio_proc is None or self._closing:
            # cleared by cleanup already, ignore
            return
        elapsed = monotonic() - self.pulseaudio_started_at
        if elapsed < 2:
            GLib.timeout_add(1000, pulseaudio_warning)
        else:
            log.warn("Warning: the pulseaudio server process has terminated after %i seconds", int(elapsed))
        self.pulseaudio_proc = None
        clean_session_files("pulseaudio.pid")

    def cleanup_pulseaudio(self) -> None:
        log("cleanup_pulseaudio()")
        self.pulseaudio_init_done.wait(5)
        proc = self.pulseaudio_proc
        pid = self.pulseaudio_pid
        if proc:
            self.exit_pulseaudio()
        elif pid:
            kill_pid(pid, "pulseaudio")
        else:
            return
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

    def exit_pulseaudio(self) -> None:
        proc = self.pulseaudio_proc
        if not proc:
            return
        log("exit_pulseaudio() process.poll()=%s, pid=%s", proc.poll(), proc.pid)
        if not self.is_child_alive(proc):
            return
        self.pulseaudio_proc = None
        log.info("stopping pulseaudio with pid %s", proc.pid)
        try:
            # first we try pactl (required on Ubuntu):
            cmd = ["pactl", "exit"]
            pactl_proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
            self.add_process(pactl_proc, "pactl exit", cmd, True)
            r = pollwait(pactl_proc)
            # warning: pactl will return 0 whether it succeeds or not...
            # but we can't kill the process because Ubuntu starts a new one
            if r != 0 and self.is_child_alive(proc):
                # fallback to using SIGINT:
                proc.terminate()
        except Exception as e:
            log("exit_pulseaudio() error stopping %s", proc, exc_info=True)
            # only log the full stacktrace if the process failed to terminate:
            if self.is_child_alive(proc):
                log.error("Error: stopping pulseaudio: %s", e, exc_info=True)

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
            "server-directory": self.pulseaudio_server_dir,
        }
        proc = self.pulseaudio_proc
        if proc and proc.poll() is None:
            info["pid"] = proc.pid
        if self.pulseaudio_private_dir and self.pulseaudio_server_socket:
            info["private-directory"] = self.pulseaudio_private_dir
            info["private-socket"] = self.pulseaudio_server_socket
        return info
