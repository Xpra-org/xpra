# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic, sleep
from threading import Event
from typing import Any
from collections.abc import Callable, Sequence

from xpra.audio.common import AUDIO_KEEPALIVE_PACKET, SILENCE_FLOOR_DB
from xpra.util.str_fn import csv
from xpra.util.objects import typedict
from xpra.util.env import first_time, envbool, envint
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.thread import start_thread
from xpra.scripts.parsing import audio_option
from xpra.server.source.audio import AudioConnection
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("audio")

QUERY_SLEEP = envint("XPRA_AUDIO_QUERY_SLEEP", 0)
AUDIO_METER = envbool("XPRA_AUDIO_METER", True)
AUDIO_LEVEL_DEVICE = "Xpra-Speaker.monitor"
AUDIO_LEVEL_INTERVAL = 250
AUDIO_SIGNAL_DELAY = max(0, envint("XPRA_AUDIO_SIGNAL_DELAY", 2000))
PULSE_INIT_TIMEOUT = 5


class AudioServer(StubSubsystem):
    """
    Mixin for servers that handle audio forwarding.
    """
    __slots__ = (
        "av_sync", "level", "meter", "meter_start_timer", "meter_state", "meter_stop",
        "microphone_allowed", "microphone_codecs", "properties", "signal_candidate",
        "signal_state", "signal_timer", "source_plugin", "speaker_allowed", "speaker_codecs",
        "supports_microphone", "supports_speaker",
    )
    PREFIX = "audio"
    # `audio-initialized` is emitted on this subsystem (via `SignalEmitter`)
    # once `query_audio()` completes. The audio source class subscribes
    # with `server.subsystems["audio"].connect(...)`.
    __signals__ = ["audio-initialized"]

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.source_plugin = ""
        self.supports_speaker = False
        self.supports_microphone = False
        self.speaker_allowed = False
        self.microphone_allowed = False
        self.speaker_codecs: Sequence[str] = ()
        self.microphone_codecs: Sequence[str] = ()
        self.properties = typedict()
        self.av_sync = False
        self.level: dict[str, Any] = {}
        self.meter: Any = None
        self.meter_start_timer = 0
        # `meter_state` only ever reports what the meter pipeline last said
        # (the subprocess pushes its own state strings, "stopped" included),
        # so it cannot also answer "may we still start a meter?":
        # `meter_stop` does, and it is set by `cleanup`.
        # It is an `Event` rather than a flag so that `cleanup` also interrupts
        # the pulseaudio wait below instead of leaving that thread parked.
        self.meter_state = "disabled"
        self.meter_stop = Event()
        self.signal_candidate: bool | None = None
        self.signal_state = False
        self.signal_timer = 0

    def init(self, opts) -> None:
        self.source_plugin = opts.audio_source
        self.supports_speaker = audio_option(opts.speaker) in ("on", "off")
        if self.supports_speaker:
            self.speaker_codecs = opts.speaker_codec
        self.supports_microphone = audio_option(opts.microphone) in ("on", "off")
        if self.supports_microphone:
            self.microphone_codecs = opts.microphone_codec
        log("AudioServer.init(..) supports speaker=%s, microphone=%s",
            self.supports_speaker, self.supports_microphone)
        self.av_sync = opts.av_sync
        pulse = self.get_subsystem("pulseaudio")
        can_meter = AUDIO_METER and self.supports_speaker and pulse is not None and pulse.enabled is not False
        self.meter_state = "pending" if can_meter else "disabled"
        log("AudioServer.init(..) av-sync=%s, meter=%s", self.av_sync, self.meter_state)

    def setup(self) -> None:
        # this is slow, use a separate thread:
        start_thread(self.init_audio_options, "audio-setup", True)
        if self.meter_state == "pending":
            start_thread(self.init_meter, "audio-meter-setup", True)
        self.add_audio_control_commands()

    def cleanup(self) -> None:
        self.cleanup_meter()

    def add_audio_control_commands(self) -> None:
        self.args_control("audio-output", "control audio forwarding", min_args=1, max_args=2)

    def get_info(self, _proto) -> dict[str, Any]:
        # always expose the configuration, even when the gstreamer query failed:
        # "initialized=False" tells the difference between "still querying" and "no audio"
        info: dict[str, Any] = dict(self.properties)
        info |= {
            "initialized": self.properties.boolget("initialized"),
            "source-plugin": self.source_plugin or "auto",
            "av-sync": self.av_sync,
            "speaker": {
                "supported": self.supports_speaker,
                "codecs": tuple(self.speaker_codecs),
            },
            "microphone": {
                "supported": self.supports_microphone,
                "codecs": tuple(self.microphone_codecs),
            },
        }
        if not self.properties:
            # audio is unsupported or not initialized yet, so the meter cannot run either
            return {AudioServer.PREFIX: info}
        meter_info: dict[str, Any] = {
            "state": self.meter_state,
            "interval": AUDIO_LEVEL_INTERVAL,
        }
        if meter := self.meter:
            proc = meter.process
            if proc and proc.poll() is None:
                meter_info["pid"] = proc.pid
            if command := meter.command:
                meter_info["command"] = command
        info["meter"] = meter_info
        if self.level:
            info["level"] = dict(self.level)
        return {AudioServer.PREFIX: info}

    def init_meter(self) -> None:
        if not AUDIO_METER or not self.supports_speaker:
            self.meter_state = "disabled"
            return
        pulse = self.get_subsystem("pulseaudio")
        if pulse is None or pulse.enabled is False:
            self.meter_state = "disabled"
            return
        # wait for pulseaudio, waking up early if the meter is stopped:
        deadline = monotonic() + PULSE_INIT_TIMEOUT
        while not pulse.init_done.is_set():
            remaining = deadline - monotonic()
            if remaining <= 0:
                self.meter_state = "unavailable"
                return
            if self.meter_stop.wait(min(remaining, 0.1)):
                return
        if self.meter_stopped():
            return
        if pulse.proc is not None or pulse.pid:
            self.meter_start_timer = self.timeout_add(2000, self.start_meter)
        else:
            self.meter_state = "unavailable"

    def meter_stopped(self) -> bool:
        return self.meter_stop.is_set() or bool(getattr(self.server, "_closing", False))

    @staticmethod
    def stop_meter_process(meter) -> None:
        try:
            meter.cleanup()
        except Exception as e:
            log.warn("Warning: failed to clean up the PulseAudio level meter: %s", e)
            try:
                meter.stop()
            except Exception:
                log("failed to stop the PulseAudio level meter", exc_info=True)

    def start_meter(self) -> None:
        self.meter_start_timer = 0
        if self.meter or self.meter_stopped():
            return
        meter = None
        try:
            from xpra.audio.wrapper import start_audio_meter
            meter = start_audio_meter(AUDIO_LEVEL_DEVICE, AUDIO_LEVEL_INTERVAL)
            self.meter = meter
            self.meter_state = "starting"
            meter.connect("level", self.meter_level)
            meter.connect("state-changed", self.meter_state_changed)
            meter.connect("error", self.meter_error)
            meter.connect("exit", self.meter_exit)
            meter.start()
        except Exception as e:
            self.meter = None
            if meter:
                self.stop_meter_process(meter)
            self.meter_state = "error"
            log.warn("Warning: failed to start the PulseAudio level meter:")
            log.warn(" %s", e)

    def meter_level(self, meter, sample: dict) -> None:
        if meter != self.meter:
            return
        self.meter_state = "active"
        # build the new sample before publishing it,
        # so that `get_info` never sees a partially updated dictionary:
        level = dict(sample)
        level["time"] = int(monotonic() * 1000)
        self.level = level
        self.send_audio_level(level)
        self.update_signal(level)

    def send_audio_level(self, level: dict) -> None:
        for source in self.get_sources_by_type(AudioConnection):
            source.send_audio_level(level)

    def send_audio_signal(self, signal: bool) -> None:
        for source in self.get_sources_by_type(AudioConnection):
            source.send_audio_signal(signal)

    def update_signal(self, level: dict) -> None:
        values = level.get("peak") or level.get("rms") or ()
        signal = any(float(value) > SILENCE_FLOOR_DB for value in values)
        if signal == self.signal_state:
            self.cancel_signal_timer()
            self.signal_candidate = None
            return
        if signal == self.signal_candidate and self.signal_timer:
            return
        self.cancel_signal_timer()
        self.signal_candidate = signal
        self.signal_timer = self.timeout_add(AUDIO_SIGNAL_DELAY, self.confirm_signal, signal)

    def confirm_signal(self, signal: bool) -> None:
        self.signal_timer = 0
        if self.signal_candidate != signal or self.meter_stopped():
            return
        self.signal_candidate = None
        if self.signal_state == signal:
            return
        self.signal_state = signal
        self.send_audio_signal(signal)

    def cancel_signal_timer(self) -> None:
        if timer := self.signal_timer:
            self.signal_timer = 0
            self.source_remove(timer)

    def meter_state_changed(self, meter, state: str) -> None:
        if meter == self.meter:
            self.meter_state = state
            if state in ("error", "stopped", "destroyed"):
                self.level = {}
                self.cancel_signal_timer()
                self.signal_candidate = None
                self.signal_state = False

    def meter_error(self, meter, message: str) -> None:
        if meter == self.meter:
            self.meter = None
            self.meter_state = "error"
            self.level = {}
            self.cancel_signal_timer()
            self.signal_candidate = None
            self.signal_state = False
            log.warn("Warning: PulseAudio level meter error: %s", message)
            self.stop_meter_process(meter)

    def meter_exit(self, meter, *_args) -> None:
        if meter != self.meter:
            return
        self.meter = None
        self.level = {}
        self.cancel_signal_timer()
        self.signal_candidate = None
        self.signal_state = False
        if not self.meter_stopped() and self.meter_state != "error":
            self.meter_state = "failed"

    def cleanup_meter(self) -> None:
        self.meter_stop.set()
        if timer := self.meter_start_timer:
            self.meter_start_timer = 0
            self.source_remove(timer)
        meter = self.meter
        self.meter = None
        if meter:
            self.stop_meter_process(meter)
        self.level = {}
        self.cancel_signal_timer()
        self.signal_candidate = None
        self.signal_state = False
        self.meter_state = "stopped"

    def get_server_features(self, source) -> dict[str, Any]:
        d = {
            "av-sync": {
                "": self.av_sync,
                "enabled": self.av_sync,
            },
        }
        log("get_server_features(%s)=%s", source, d)
        return d

    def init_audio_options(self) -> None:
        def audio_missing(*_args) -> Sequence[str]:
            return ()

        def noaudio() -> None:
            self.properties["initialized"] = True
            self.emit("audio-initialized")
            self.supports_speaker = self.supports_microphone = False
            self.speaker_allowed = self.microphone_allowed = False

        parse_codecs: Callable = audio_missing
        audio_properties = typedict()
        if self.supports_speaker or self.supports_microphone:
            try:
                from xpra.audio.common import audio_option_or_all
                parse_codecs = audio_option_or_all
                from xpra.audio.wrapper import query_audio
                sleep(QUERY_SLEEP)
                audio_properties = query_audio()
                if not audio_properties:
                    log.info("Audio subsystem query failed, is GStreamer installed?")
                    noaudio()
                    return
                gstv = audio_properties.strtupleget("gst.version")
                if gstv:
                    log.info("GStreamer version %s", ".".join(gstv[:3]))
                else:
                    log.info("GStreamer loaded")
            except Exception as e:
                log("failed to query audio", exc_info=True)
                log.error("Error: failed to query audio subsystem:")
                log.estr(e)
                noaudio()
                return
        encoders = audio_properties.strtupleget("encoders")
        decoders = audio_properties.strtupleget("decoders")
        self.speaker_codecs = parse_codecs("speaker-codec", self.speaker_codecs, encoders)
        self.microphone_codecs = parse_codecs("microphone-codec", self.microphone_codecs, decoders)
        if not self.speaker_codecs:
            self.supports_speaker = False
        if not self.microphone_codecs:
            self.supports_microphone = False
        # some calls must happen from the main thread:
        self.idle_add(self.init_ui_audio_options, audio_properties)

    def init_ui_audio_options(self, audio_properties: typedict):
        # query_pulseaudio_properties may access X11. PulseaudioServer is a
        # standalone subsystem, so reach into it via self.server.subsystems
        # rather than relying on inheritance.
        pulse = self.get_subsystem("pulseaudio")
        if bool(audio_properties) and pulse is not None:
            from xpra.server.subsystem.pulseaudio import query_pulseaudio_properties
            audio_properties |= query_pulseaudio_properties()
        audio_properties["initialized"] = True
        self.properties = audio_properties
        self.log_audio_properties()
        self.emit("audio-initialized")

    def log_audio_properties(self) -> None:
        from xpra.util.str_fn import csv
        log("init_audio_options:")
        log(" speaker: supported=%s, encoders=%s",self.supports_speaker, csv(self.speaker_codecs))
        log(" microphone: supported=%s, decoders=%s", self.supports_microphone, csv(self.microphone_codecs))
        log(" audio properties=%s", self.properties)

    def _process_sound_control(self, proto, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        self._process_control(proto, packet)

    def _process_control(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        audio_control = getattr(ss, "audio_control", None)
        if not callable(audio_control):
            if first_time(f"no-audio-control-{ss}"):
                log.warn(f"Warning: ignoring audio control requests from {ss}")
                log.warn(" audio is not enabled for this connection")
            return
        # noinspection calling-non-callable
        audio_control(*packet[1:])

    def _process_sound_data(self, proto, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        self._process_data(proto, packet)

    def _process_data(self, proto, packet: Packet) -> None:
        if ss := self.get_server_source(proto):
            ss.audio_data(*packet[1:])

    def _process_capabilities(self, proto, packet: Packet) -> None:
        if ss := self.get_server_source(proto):
            ss.client_audio_capabilities(packet.get_dict(1))

    def _process_keepalive(self, proto, packet: Packet) -> None:
        if ss := self.get_server_source(proto):
            ss.audio_keepalive(packet.get_u64(1))

    def init_packet_handlers(self) -> None:
        if self.supports_speaker or self.supports_microphone:
            self.add_packets(f"{AudioServer.PREFIX}-control", main_thread=True)
            self.add_packets(f"{AudioServer.PREFIX}-data")
            self.add_packets(f"{AudioServer.PREFIX}-capabilities", main_thread=True)
            self.add_packets(AUDIO_KEEPALIVE_PACKET)
            self.add_legacy_alias("sound-control", f"{AudioServer.PREFIX}-control")
            self.add_legacy_alias("sound-data", f"{AudioServer.PREFIX}-data")

    #########################################
    # Control Commands
    #########################################

    def control_command_audio_output(self, *args) -> str:
        msg = []
        from xpra.net.control.common import control_get_sources
        for csource in tuple(control_get_sources(self.server)):
            msg.append(f"{csource} : " + str(csource.audio_control(*args)))
        return csv(msg)
