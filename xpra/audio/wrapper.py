# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any
from time import monotonic
from typing import NoReturn
from collections import namedtuple
from collections.abc import Iterable, Callable

from xpra.gstreamer.common import import_gst, format_element_options
from xpra.audio.gstreamer_util import (
    parse_audio_source, get_source_plugins, get_sink_plugins, get_default_sink_plugin, get_default_source,
    can_decode, can_encode, get_muxers, get_demuxers, get_all_plugin_names,
)
from xpra.net.subprocess_wrapper import SubprocessCaller, SubprocessCallee, exec_kwargs, exec_env
from xpra.platform.paths import get_audio_command
from xpra.common import FULL_INFO
from xpra.os_util import WIN32, OSX, POSIX, BITS, gi_import
from xpra.util.parsing import parse_simple_dict
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.scripts.config import InitExit, InitException
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio")

DEBUG_SOUND = envbool("XPRA_SOUND_DEBUG", False)
SUBPROCESS_DEBUG = tuple(x.strip() for x in os.environ.get("XPRA_SOUND_SUBPROCESS_DEBUG", "").split(",") if x.strip())
FAKE_START_FAILURE = envbool("XPRA_SOUND_FAKE_START_FAILURE", False)
FAKE_EXIT = envbool("XPRA_SOUND_FAKE_EXIT", False)
FAKE_CRASH = envbool("XPRA_SOUND_FAKE_CRASH", False)
SOUND_START_TIMEOUT = envint("XPRA_SOUND_START_TIMEOUT", 5000 * (1 + int(WIN32)))

DEFAULT_SOUND_COMMAND_ARGS = os.environ.get("XPRA_DEFAULT_SOUND_COMMAND_ARGS", "--windows=no").split(",")


def get_full_audio_command() -> list[str]:
    return get_audio_command() + DEFAULT_SOUND_COMMAND_ARGS


def get_audio_wrapper_env() -> dict[str, str]:
    env = {
        "XPRA_LOG_SOCKET_STATS": os.environ.get("XPRA_LOG_SOCKET_STATS", "0"),
    }
    if WIN32:
        # we don't want the output to go to a log file
        env["XPRA_REDIRECT_OUTPUT"] = "0"
    elif POSIX and not OSX:
        try:
            from xpra.audio.pulseaudio.util import add_audio_tagging_env
            add_audio_tagging_env(env)
        except ImportError as e:
            log.warn("Warning: failed to set pulseaudio tagging:")
            log.warn(" %s", e)
    return env


# this wrapper takes care of launching src.py or sink.py
#
# the command line should look something like:
# xpra MODE IN OUT PLUGIN PLUGIN_OPTIONS CODECS CODEC_OPTIONS VOLUME
# * MODE can be _audio_record or _audio_play
# * IN is where we read the encoded commands from, specify "-" for stdin
# * OUT is where we write the encoded output stream, specify "-" for stdout
# * PLUGIN is the audio source (for recording) or sink (for playing) to use, can be omitted (will be auto detected)
#   ie: pulsesrc, autoaudiosink
# * PLUGIN_OPTIONS is a string containing options specific to this plugin
#   ie: device=somedevice,otherparam=somevalue
# * CODECS:  the list of codecs that we are willing to support
#   ie: mp3,flac
# * CODECS_OPTIONS: a string containing options to apply to the codec
#   ie: blocksize=1024,otherparam=othervalue
# * VOLUME: optional, a number from 0.0 to 1.0
#   ie: 1.0
# FIXME: CODEC_OPTIONS should allow us to specify different options for each CODEC
# The output will be a regular xpra packet, containing serialized signals that we receive
# The input can be a regular xpra packet, those are converted into method calls

class AudioSubprocess(SubprocessCallee):
    """ Utility superclass for audio subprocess wrappers
        (see audio_record and audio_play below)
    """

    def __init__(self, wrapped_object, method_whitelist, exports_list):
        # add bits common to both record and play:
        methods = method_whitelist + ["set_volume", "cleanup"]
        exports = ["state-changed", "info", "error"] + exports_list
        super().__init__(wrapped_object=wrapped_object, method_whitelist=methods)
        for x in exports:
            self.connect_export(x)

    def start(self) -> None:
        if not FAKE_START_FAILURE:
            def wrap_start() -> bool:
                self.wrapped_object.start()
                return False
            GLib.idle_add(wrap_start)
        if FAKE_EXIT > 0:
            def process_exit() -> None:
                self.cleanup()
                GLib.timeout_add(250, self.stop)

            GLib.timeout_add(FAKE_EXIT * 1000, process_exit)
        if FAKE_CRASH > 0:
            def force_exit() -> NoReturn:
                sys.exit(1)

            GLib.timeout_add(FAKE_CRASH * 1000, force_exit)
        super().start()

    def cleanup(self) -> None:
        wo = self.wrapped_object
        log("cleanup() wrapped object=%s", wo)
        if wo:
            # this will stop the audio pipeline:
            self.wrapped_object = None
            try:
                wo.cleanup()
            except RuntimeError:
                log("cleanup() failed to clean %s", wo, exc_info=True)
        GLib.timeout_add(1000, self.do_stop)

    def export_info(self) -> bool:
        wo = self.wrapped_object
        if wo:
            self.send("info", wo.get_info())
        return wo is not None


class AudioRecord(AudioSubprocess):
    """ wraps SoundSource as a subprocess """

    def __init__(self, *pipeline_args):
        from xpra.audio.src import AudioSource
        audio_pipeline = AudioSource(*pipeline_args)
        super().__init__(audio_pipeline, [], ["new-stream", "new-buffer"])
        self.large_packets = ["new-buffer"]


class AudioPlay(AudioSubprocess):
    """ wraps AudioSink as a subprocess """

    def __init__(self, *pipeline_args):
        from xpra.audio.sink import AudioSink
        audio_pipeline = AudioSink(*pipeline_args)
        super().__init__(audio_pipeline, ["add_data"], [])


def run_audio(mode: str, error_cb: Callable, args: list[str]) -> int:
    """ this function just parses command line arguments to feed into the audio subprocess class,
        which in turn just feeds them into the audio pipeline class (sink.py or src.py)
    """
    gst = import_gst()
    if not gst:
        return 1
    info = mode.replace("_audio_", "")  # ie: "_audio_record" -> "record"
    from xpra.platform import program_context
    with program_context(f"Xpra-Audio-{info}", f"Xpra Audio {info}"):
        log("run_audio%s gst=%s", (mode, error_cb, args), gst)
        if info == "record":
            subproc = AudioRecord
        elif info == "play":
            subproc = AudioPlay
        elif info == "query":
            plugins = get_all_plugin_names()
            sources = [x for x in get_source_plugins() if x in plugins]
            sinks = [x for x in get_sink_plugins() if x in plugins]
            from xpra.audio.gstreamer_util import get_gst_version
            d: dict[str, Any] = {
                "encoders": can_encode(),
                "decoders": can_decode(),
                "sources": sources,
                "source.default": get_default_source() or "",
                "sinks": sinks,
                "sink.default": get_default_sink_plugin() or "",
                "muxers": get_muxers(),
                "demuxers": get_demuxers(),
            }
            if FULL_INFO >= 1:
                d["gst.version"] = tuple(int(x) for x in get_gst_version())
            if FULL_INFO >= 2:
                d |= {
                    "plugins": plugins,
                    "python.version": sys.version_info[:3],
                    "python.bits": BITS,
                }
            for k, v in d.items():
                if isinstance(v, (list, tuple)):
                    v = ",".join(str(x) for x in v)
                print(f"{k}={v}")
            return 0
        else:
            log.error(f"Error: unknown mode {mode!r}")
            return 1
        assert len(args) >= 6, "not enough arguments"

        # the plugin to use (ie: 'pulsesrc' for src.py or 'autoaudiosink' for sink.py)
        plugin = args[2]
        # plugin options (ie: "device=monitor_device,something=value")
        options = parse_simple_dict(args[3])
        # codecs:
        codecs = [x.strip() for x in args[4].split(",")]
        # codec options:
        codec_options = parse_simple_dict(args[5])
        # volume (optional):
        try:
            volume = int(args[6])
        except (ValueError, IndexError):
            volume = 1.0

        ss = None
        try:
            ss = subproc(plugin, options, codecs, codec_options, volume)
            ss.start()
            return 0
        except InitExit as e:
            log.error(f"{info}: {e}")
            return e.status
        except InitException as e:
            log.error(f"{info}: {e}")
            return 1
        except OSError:
            log.error("run_audio%s error", (mode, error_cb, args), exc_info=True)
            return 1
        finally:
            if ss:
                ss.stop()
    return 1


def _add_debug_args(command: list[str]) -> None:
    from xpra.log import debug_enabled_categories
    debug = list(SUBPROCESS_DEBUG)
    for f in ("audio", "gstreamer"):
        if (DEBUG_SOUND or f in debug_enabled_categories) and (f not in debug):
            debug.append(f)
    if debug:
        # forward debug flags:
        command.append("--debug")
        command.append(",".join(debug))


class AudioSubprocessWrapper(SubprocessCaller):
    """ This utility superclass deals with the caller side of the audio subprocess wrapper:
        * starting the wrapper subprocess
        * handling state-changed signal, so we have a local copy of the current value ready
        * handle "info" packets, so we have a cached copy
        * forward get/set volume calls (get_volume uses the value found in "info")
    """

    def __init__(self, description: str):
        super().__init__(description)
        self.state = "stopped"
        self.codec = "unknown"
        self.codec_description = ""
        self.info = {}
        # hook some default packet handlers:
        self.connect("state-changed", self.state_changed)
        self.connect("info", self.info_update)
        self.connect("signal", self.subprocess_signal)

    def get_env(self) -> dict[str, str]:
        env = super().get_env()
        env.update(get_audio_wrapper_env())
        env.pop("DISPLAY", None)
        # env.pop("WAYLAND_DISPLAY", None)
        return env

    def start(self) -> None:
        self.state = "starting"
        super().start()
        log("start() %s subprocess(%s)=%s", self.description, self.command, self.process.pid)
        GLib.timeout_add(SOUND_START_TIMEOUT, self.verify_started)

    def cleanup(self) -> None:
        log("cleanup() sending cleanup request to %s", self.description)
        self.send("cleanup")
        # cleanup should cause the process to exit
        GLib.timeout_add(500, self.send, "stop")
        GLib.timeout_add(1000, self.send, "exit")
        GLib.timeout_add(1500, self.stop)

    def verify_started(self) -> None:
        p = self.process
        log("verify_started() process=%s, info=%s, codec=%s", p, self.info, self.codec)
        if p is None:
            log("no process")
            return
        if p.poll() is not None:
            log("process has already terminated: exit code=%s", p.poll())
            return
        # if we don't get an "info" packet, then the pipeline must have failed to start
        if not self.info:
            log.warn("Warning: the %s process has failed to start", self.description)
            self.cleanup()

    def subprocess_signal(self, _wrapper, proc) -> None:
        log("subprocess_signal: %s", proc)
        # call via idle_add to prevent deadlocks on win32!
        GLib.idle_add(self.stop_protocol)

    def state_changed(self, _wrapper, new_state: str) -> None:
        self.state = new_state

    def get_state(self) -> str:
        return self.state

    def get_info(self) -> dict:
        return self.info

    def info_update(self, _wrapper, info: dict) -> None:
        log("info_update: %s", info)
        self.info.update(info)
        self.info["time"] = int(monotonic())
        p = self.process
        if p and not p.poll():
            self.info["pid"] = p.pid
        self.codec_description = info.get("codec_description")

    def set_volume(self, v: float) -> None:
        self.send("set_volume", int(v * 100))

    def get_volume(self) -> float:
        return self.info.get("volume", 100) / 100.0


class SourceSubprocessWrapper(AudioSubprocessWrapper):

    def __init__(self, plugin, _options, codecs, volume, element_options):
        super().__init__("audio capture")
        self.large_packets = ["new-buffer"]
        self.command = get_full_audio_command() + [
            "_audio_record", "-", "-",
            plugin or "", format_element_options(element_options),
            ",".join(codecs), "",
            str(volume),
        ]
        _add_debug_args(self.command)

    def __repr__(self):
        proc = self.process
        if proc:
            try:
                return "source_subprocess_wrapper(%s)" % proc.pid
            except AttributeError:
                pass
        return f"source_subprocess_wrapper({proc})"


class SinkSubprocessWrapper(AudioSubprocessWrapper):

    def __init__(self, plugin, codec, volume, element_options):
        super().__init__("audio playback")
        self.large_packets = ["add_data"]
        self.codec = codec
        self.command = get_full_audio_command() + [
            "_audio_play", "-", "-",
            plugin or "", format_element_options(element_options),
            codec, "",
            str(volume),
        ]
        _add_debug_args(self.command)

    def add_data(self, data: bytes, metadata: dict, packet_metadata=()) -> None:
        if DEBUG_SOUND:
            log("add_data(%s bytes, %s, %s) forwarding to %s", len(data), metadata, len(packet_metadata), self.protocol)
        self.send("add_data", data, metadata, packet_metadata)

    def __repr__(self):
        proc = self.process
        if proc:
            try:
                return "sink_subprocess_wrapper(%s)" % proc.pid
            except AttributeError:
                pass
        return "sink_subprocess_wrapper(%s)" % proc


def start_sending_audio(plugins, audio_source_plugin: str, device: str, codec: str, volume: float,
                        want_monitor_device: bool,
                        remote_decoders: Iterable[str],
                        remote_pulseaudio_server: str, remote_pulseaudio_id: str
                        ) -> SourceSubprocessWrapper | None:
    log("start_sending_audio%s",
        (plugins, audio_source_plugin, device, codec, volume, want_monitor_device,
         remote_decoders, remote_pulseaudio_server, remote_pulseaudio_id))
    with log.trap_error("Error setting up %r audio source" % (audio_source_plugin or "auto")):
        # info about the remote end:
        PAInfo = namedtuple("PAInfo", ("pulseaudio_server", "pulseaudio_id", "remote_decoders"))
        remote = PAInfo(pulseaudio_server=remote_pulseaudio_server,
                        pulseaudio_id=remote_pulseaudio_id,
                        remote_decoders=remote_decoders)
        plugin, options = parse_audio_source(plugins, audio_source_plugin, device, want_monitor_device, remote)
        if plugin:
            log("parsed '%s':", audio_source_plugin)
            log("plugin=%s", plugin)
            log("options=%s", options)
            return SourceSubprocessWrapper(plugin, options, remote_decoders, volume, options)
    return None


def start_receiving_audio(codec: str) -> SinkSubprocessWrapper:
    log("start_receiving_audio(%s)", codec)
    with log.trap_error("Error starting audio sink"):
        return SinkSubprocessWrapper(None, codec, 1.0, {})


def query_audio() -> typedict:
    import subprocess
    command = get_full_audio_command() + ["_audio_query"]
    _add_debug_args(command)
    kwargs = exec_kwargs()
    env = exec_env()
    env.update(get_audio_wrapper_env())
    env.pop("DISPLAY", None)
    log(f"query_audio() command={command!r}, env={env}, kwargs={kwargs}")
    proc = subprocess.Popen(command,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, universal_newlines=True,
                            **kwargs)
    with proc:
        out, err = proc.communicate(None)
    log(f"query_audio() process returned {proc.returncode}")
    log(f"query_audio() out={out!r}, err={err!r}")
    if proc.returncode != 0:
        return typedict()
    d = typedict()
    for x in out.splitlines():
        kv = x.split("=", 1)
        if len(kv) == 2:
            # ie: kv = ["decoders", "mp3,vorbis"]
            k, v = kv
            # fugly warning: all the other values are lists.. but this one is not:
            if k != "python.bits":
                v = v.split(",")
            # d["decoders"] = ["mp3", "vorbis"]
            d[k] = v
    log(f"query_audio()={d}")
    return d
