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
from collections.abc import Callable, Sequence

from xpra.os_util import OSX, POSIX, gi_import
from xpra.util.io import pollwait
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envbool, osexpand, first_time
from xpra.net.common import PacketType
from xpra.util.thread import start_thread
from xpra.platform.info import get_username
from xpra.platform.paths import get_icon_filename
from xpra.scripts.parsing import audio_option
from xpra.scripts.session import save_session_file
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")
audiolog = Logger("audio")

PRIVATE_PULSEAUDIO = envbool("XPRA_PRIVATE_PULSEAUDIO", True)

PA_ENV_WHITELIST = (
    "DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SESSION_BUS_WINDOWID",
    "DISPLAY", "HOME", "HOSTNAME", "LANG", "PATH",
    "PWD", "SHELL", "XAUTHORITY",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
    "XPRA_PULSE_SOURCE_DEVICE_NAME", "XPRA_PULSE_SINK_DEVICE_NAME",
)


class AudioServer(StubServerMixin):
    """
    Mixin for servers that handle audio forwarding.
    """
    PREFIX = "audio"

    def __init__(self):
        self.audio_init_done = Event()
        self.audio_init_done.set()
        self.pulseaudio = False
        self.pulseaudio_command = ""
        self.pulseaudio_configure_commands = []
        self.pulseaudio_proc: Popen | None = None
        self.pulseaudio_private_dir = ""
        self.pulseaudio_private_socket = ""
        self.audio_source_plugin = ""
        self.supports_speaker = False
        self.supports_microphone = False
        self.speaker_allowed = False
        self.microphone_allowed = False
        self.speaker_codecs = ()
        self.microphone_codecs = ()
        self.audio_properties = typedict()
        self.av_sync = False

    def init(self, opts) -> None:
        self.audio_source_plugin = opts.audio_source
        self.supports_speaker = audio_option(opts.speaker) in ("on", "off")
        if self.supports_speaker:
            self.speaker_codecs = opts.speaker_codec
        self.supports_microphone = audio_option(opts.microphone) in ("on", "off")
        if self.supports_microphone:
            self.microphone_codecs = opts.microphone_codec
        self.pulseaudio = opts.pulseaudio
        self.pulseaudio_command = opts.pulseaudio_command
        self.pulseaudio_configure_commands = opts.pulseaudio_configure_commands
        log("AudioServer.init(..) supports speaker=%s, microphone=%s",
            self.supports_speaker, self.supports_microphone)
        self.av_sync = opts.av_sync
        log("AudioServer.init(..) av-sync=%s", self.av_sync)

    def setup(self) -> None:
        # the setup code will mostly be waiting for subprocesses to run,
        # so do it in a separate thread
        # and just wait for the results where needed:
        self.audio_init_done.clear()
        start_thread(self.do_audio_setup, "audio-setup", True)
        # we don't use threaded_setup() here because it would delay
        # all the other mixins that use it, for no good reason.

    def do_audio_setup(self) -> None:
        self.init_pulseaudio()
        self.init_audio_options()

    def cleanup(self) -> None:
        self.audio_init_done.wait(5)
        self.cleanup_pulseaudio()

    def get_info(self, _proto) -> dict[str, Any]:
        self.audio_init_done.wait(5)
        info = {}
        if self.pulseaudio is not False:
            info["pulseaudio"] = self.get_pulseaudio_info()
        if self.audio_properties:
            info["audio"] = self.audio_properties
        return {}

    def get_server_features(self, source) -> dict[str, Any]:
        d = {
            "av-sync": {
                "": self.av_sync,
                "enabled": self.av_sync,
            },
        }
        log("get_server_features(%s)=%s", source, d)
        return d

    def init_pulseaudio(self) -> None:
        audiolog("init_pulseaudio() pulseaudio=%s, pulseaudio_command=%s", self.pulseaudio, self.pulseaudio_command)
        if self.pulseaudio is False:
            return
        if not self.pulseaudio_command:
            audiolog.warn("Warning: pulseaudio command is not defined")
            return
        # environment initialization:
        # 1) make sure that the audio subprocess will use the devices
        #    we define in the pulseaudio command
        #    (it is too difficult to parse the pulseaudio_command,
        #    so we just hope that it matches this):
        #    Note: speaker is the source and microphone the sink,
        #    because things are reversed on the server.
        os.environ.update({
            "XPRA_PULSE_SOURCE_DEVICE_NAME": "Xpra-Speaker",
            "XPRA_PULSE_SINK_DEVICE_NAME": "Xpra-Microphone",
        })
        # 2) whitelist the env vars that pulseaudio may use:
        env = {k: v for k, v in self.get_child_env().items() if k in PA_ENV_WHITELIST}
        # 3) use a private pulseaudio server, so each xpra
        #    session can have its own server,
        #    create a directory for each display:
        if PRIVATE_PULSEAUDIO and POSIX and not OSX:
            # pylint: disable=import-outside-toplevel
            from xpra.platform.posix.paths import _get_xpra_runtime_dir, get_runtime_dir
            rd = osexpand(get_runtime_dir())
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
                    pulse_dirname = "pulse"
                else:
                    pulse_dirname = f"pulse-{display}"
                self.pulseaudio_private_dir = osexpand(os.path.join(xpra_rd, pulse_dirname))
                if not os.path.exists(self.pulseaudio_private_dir):
                    os.mkdir(self.pulseaudio_private_dir, 0o700)
                env["XDG_RUNTIME_DIR"] = self.pulseaudio_private_dir
                self.pulseaudio_private_socket = os.path.join(self.pulseaudio_private_dir, "pulse", "native")
                os.environ["XPRA_PULSE_SERVER"] = self.pulseaudio_private_socket
        cmd = shlex.split(self.pulseaudio_command)
        cmd = list(osexpand(x) for x in cmd)
        # find the absolute path to the command:
        pa_cmd = cmd[0]
        if not os.path.isabs(pa_cmd):
            pa_path = None
            for x in os.environ.get("PATH", "").split(os.path.pathsep):
                t = os.path.join(x, pa_cmd)
                if os.path.exists(t):
                    pa_path = t
                    break
            if not pa_path:
                msg = f"pulseaudio not started: {pa_cmd!r} command not found"
                if self.pulseaudio is None:
                    audiolog.info(msg)
                else:
                    audiolog.warn(msg)
                self.clean_pulseaudio_private_dir()
                return
            cmd[0] = pa_cmd
        started_at = monotonic()

        def pulseaudio_warning() -> None:
            audiolog.warn("Warning: pulseaudio has terminated shortly after startup.")
            audiolog.warn(" pulseaudio is limited to a single instance per user account,")
            audiolog.warn(" and one may be running already for user '%s'.", get_username())
            audiolog.warn(" To avoid this warning, either fix the pulseaudio command line")
            audiolog.warn(" or use the 'pulseaudio=no' option.")

        def pulseaudio_ended(proc) -> None:
            audiolog("pulseaudio_ended(%s) pulseaudio_proc=%s, returncode=%s, closing=%s",
                     proc, self.pulseaudio_proc, proc.returncode, self._closing)
            if self.pulseaudio_proc is None or self._closing:
                # cleared by cleanup already, ignore
                return
            elapsed = monotonic() - started_at
            if elapsed < 2:
                GLib.timeout_add(1000, pulseaudio_warning)
            else:
                audiolog.warn("Warning: the pulseaudio server process has terminated after %i seconds", int(elapsed))
            self.pulseaudio_proc = None

        try:
            audiolog("pulseaudio cmd=%s", " ".join(cmd))
            audiolog("pulseaudio env=%s", env)
            self.pulseaudio_proc = Popen(cmd, env=env)
        except Exception as e:
            audiolog("Popen(%s)", cmd, exc_info=True)
            audiolog.error("Error: failed to start pulseaudio:")
            audiolog.estr(e)
            self.clean_pulseaudio_private_dir()
            return
        self.add_process(self.pulseaudio_proc, "pulseaudio", cmd, ignore=True, callback=pulseaudio_ended)
        if self.pulseaudio_proc:
            save_session_file("pulseaudio.pid", "%s" % self.pulseaudio_proc.pid)
            audiolog.info("pulseaudio server started with pid %s", self.pulseaudio_proc.pid)
            if self.pulseaudio_private_socket:
                audiolog.info(" private server socket path:")
                audiolog.info(" '%s'", self.pulseaudio_private_socket)
                os.environ["PULSE_SERVER"] = "unix:%s" % self.pulseaudio_private_socket

            def configure_pulse() -> None:
                p = self.pulseaudio_proc
                if p is None or p.poll() is not None:
                    return
                for i, x in enumerate(self.pulseaudio_configure_commands):
                    proc = Popen(x, env=env, shell=True)
                    self.add_process(proc, "pulseaudio-configure-command-%i" % i, x, ignore=True)

            GLib.timeout_add(2 * 1000, configure_pulse)

    def cleanup_pulseaudio(self) -> None:
        self.audio_init_done.wait(5)
        proc = self.pulseaudio_proc
        if not proc:
            return
        audiolog("cleanup_pa() process.poll()=%s, pid=%s", proc.poll(), proc.pid)
        if self.is_child_alive(proc):
            self.pulseaudio_proc = None
            audiolog.info("stopping pulseaudio with pid %s", proc.pid)
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
                audiolog.warn("cleanup_pulseaudio() error stopping %s", proc, exc_info=True)
                # only log the full stacktrace if the process failed to terminate:
                if self.is_child_alive(proc):
                    audiolog.error("Error: stopping pulseaudio: %s", e, exc_info=True)
            if self.pulseaudio_private_socket and self.is_child_alive(proc):
                # wait for the pulseaudio process to exit,
                # it will delete the socket:
                audiolog("pollwait()=%s", pollwait(proc))
        if self.pulseaudio_private_socket and not self.is_child_alive(proc):
            # wait for the socket to get cleaned up
            # (it should be removed by the pulseaudio server as it exits)
            import time
            now = monotonic()
            while (monotonic() - now) < 1 and os.path.exists(self.pulseaudio_private_socket):
                time.sleep(0.1)
        self.clean_pulseaudio_private_dir()
        if not self.is_child_alive(proc):
            self.do_clean_session_files("pulseaudio.pid")

    def clean_pulseaudio_private_dir(self) -> None:
        if self.pulseaudio_private_dir:
            if os.path.exists(self.pulseaudio_private_socket):
                log.warn("Warning: the pulseaudio private socket file still exists:")
                log.warn(" '%s'", self.pulseaudio_private_socket)
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
                dirs += [native, pulse, self.pulseaudio_private_dir]
                path = None
                try:
                    for d in dirs:
                        path = os.path.abspath(d)
                        audiolog("removing private directory '%s'", path)
                        if os.path.exists(path) and os.path.isdir(path):
                            os.rmdir(path)
                    log.info("removing private directory '%s'", self.pulseaudio_private_dir)
                except OSError as e:
                    audiolog("cleanup_pulseaudio() error removing '%s'", path, exc_info=True)
                    audiolog.error("Error: failed to cleanup the pulseaudio private directory")
                    audiolog.error(" '%s'", self.pulseaudio_private_dir)
                    audiolog.estr(e)
                    try:
                        files = os.listdir(path)
                        if files:
                            audiolog.error(f" found %i files in {path!r}:", len(files))
                            for f in files:
                                audiolog.error(f" - {f!r}")
                    except OSError:
                        audiolog.error("cleanup_pulseaudio() error accessing '%s'", path, exc_info=True)

    def init_audio_options(self) -> None:
        def audio_missing(*_args) -> Sequence[str]:
            return ()

        def noaudio() -> None:
            self.supports_speaker = self.supports_microphone = False
            self.speaker_allowed = self.microphone_allowed = False

        parse_codecs: Callable = audio_missing
        if self.supports_speaker or self.supports_microphone:
            try:
                from xpra.audio.common import audio_option_or_all
                parse_codecs = audio_option_or_all
                from xpra.audio.wrapper import query_audio
                self.audio_properties = query_audio()
                if not self.audio_properties:
                    audiolog.info("Audio subsystem query failed, is GStreamer installed?")
                    noaudio()
                    return
                gstv = self.audio_properties.strtupleget("gst.version")
                if gstv:
                    log.info("GStreamer version %s", ".".join(gstv[:3]))
                else:
                    log.info("GStreamer loaded")
            except Exception as e:
                audiolog("failed to query audio", exc_info=True)
                audiolog.error("Error: failed to query audio subsystem:")
                audiolog.estr(e)
                noaudio()
                return
        encoders = self.audio_properties.strtupleget("encoders")
        decoders = self.audio_properties.strtupleget("decoders")
        self.speaker_codecs = parse_codecs("speaker-codec", self.speaker_codecs, encoders)
        self.microphone_codecs = parse_codecs("microphone-codec", self.microphone_codecs, decoders)
        if not self.speaker_codecs:
            self.supports_speaker = False
        if not self.microphone_codecs:
            self.supports_microphone = False
        # query_pulseaudio_properties may access X11,
        # do this from the main thread:
        if bool(self.audio_properties):
            GLib.idle_add(self.query_pulseaudio_properties)
        GLib.idle_add(self.log_audio_properties)
        self.audio_init_done.set()

    def query_pulseaudio_properties(self) -> None:
        try:
            from xpra.audio.pulseaudio.util import set_icon_path, get_info as get_pa_info
            pa_info = get_pa_info()
            audiolog("pulseaudio info=%s", pa_info)
            self.audio_properties.update(pa_info)
            set_icon_path(get_icon_filename("xpra.png"))
        except ImportError as e:
            if POSIX and not OSX:
                log.warn("Warning: failed to set pulseaudio tagging icon:")
                log.warn(" %s", e)

    def log_audio_properties(self) -> None:
        audiolog("init_audio_options speaker: supported=%s, encoders=%s",
                 self.supports_speaker, csv(self.speaker_codecs))
        audiolog("init_audio_options microphone: supported=%s, decoders=%s",
                 self.supports_microphone, csv(self.microphone_codecs))
        audiolog("init_audio_options audio properties=%s", self.audio_properties)

    def get_pulseaudio_info(self) -> dict[str, Any]:
        info = {
            "command": self.pulseaudio_command,
            "configure-commands": self.pulseaudio_configure_commands,
        }
        if self.pulseaudio_proc and self.pulseaudio_proc.poll() is None:
            info["pid"] = self.pulseaudio_proc.pid
        if self.pulseaudio_private_dir and self.pulseaudio_private_socket:
            info["private-directory"] = self.pulseaudio_private_dir
            info["private-socket"] = self.pulseaudio_private_socket
        return info

    def _process_sound_control(self, proto, packet: PacketType) -> None:
        self._process_audio_control(proto, packet)

    def _process_audio_control(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        audio_control = getattr(ss, "audio_control", None)
        if not audio_control:
            if first_time(f"no-audio-control-{ss}"):
                log.warn(f"Warning: ignoring audio control requests from {ss}")
                log.warn(" audio is not enabled for this connection")
            return
        audio_control(*packet[1:])

    def _process_sound_data(self, proto, packet: PacketType) -> None:
        self._process_sound_data(proto, packet)

    def _process_audio_data(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if ss:
            ss.audio_data(*packet[1:])

    def init_packet_handlers(self) -> None:
        if self.supports_speaker or self.supports_microphone:
            self.add_packets(f"{AudioServer.PREFIX}-control", main_thread=True)
            self.add_packets(f"{AudioServer.PREFIX}-data")
            self.add_legacy_alias("sound-control", f"{AudioServer.PREFIX}-control")
            self.add_legacy_alias("sound-data", f"{AudioServer.PREFIX}-data")
