# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import sleep
from typing import Any
from collections.abc import Callable, Sequence, Iterable

from xpra.audio.common import (
    AUDIO_DATA_PACKET, AUDIO_CONTROL_PACKET, AUDIO_KEEPALIVE_PACKET,
)
from xpra.audio.keepalive import AudioKeepaliveMixin
from xpra.platform.paths import get_icon_filename
from xpra.scripts.parsing import audio_option
from xpra.net.common import Packet, FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.net.compression import Compressed
from xpra.net.packet_type import CONNECTION_LOST
from xpra.common import noop, SizedBuffer, may_notify_client
from xpra.constants import NotificationID
from xpra.os_util import get_machine_id, get_user_uuid, WIN32, OSX, POSIX
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, bytestostr
from xpra.util.env import envint
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger
from xpra.util.thread import start_thread

avsynclog = Logger("av-sync")
log = Logger("client", "audio")

QUERY_SLEEP = envint("XPRA_AUDIO_QUERY_SLEEP", 0)


def _is_recoverable_audio_error(error_str: str) -> bool:
    if not WIN32:
        return False
    upper = error_str.upper()
    return "DEVICE_INVALIDATED" in upper or "88890004" in upper


AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA")
DELTA_THRESHOLD = envint("XPRA_AV_SYNC_DELTA_THRESHOLD", 40)
DEFAULT_AV_SYNC_DELAY = envint("XPRA_DEFAULT_AV_SYNC_DELAY", 150)


def init_audio_tagging(icon: str) -> None:
    if not POSIX:
        return
    try:
        from xpra import audio
        if not audio:
            # cythonized code can bind None for missing imports
            raise ImportError("xpra.audio")
    except ImportError:
        log("no audio module, skipping pulseaudio tagging setup")
        return
    try:
        from xpra.audio.pulseaudio.util import set_icon_path
        icon_filename = get_icon_filename(icon or "xpra")
        set_icon_path(icon_filename)
    except ImportError as e:
        if not OSX:
            log.warn("Warning: failed to set pulseaudio tagging icon:")
            log.warn(" %s", e)


def get_matching_codecs(local_codecs, server_codecs) -> Sequence[str]:
    matching_codecs = tuple(x for x in local_codecs if x in server_codecs)
    log("get_matching_codecs(%s, %s)=%s", local_codecs, server_codecs, matching_codecs)
    return matching_codecs


def nooptions(*_args) -> Sequence[str]:
    return ()


def get_pa_info() -> dict:
    if OSX or not POSIX:
        return {}
    try:
        from xpra.audio.pulseaudio.util import get_info as get_pa_info
        pa_info = get_pa_info()
        log("pulseaudio info=%s", pa_info)
        return pa_info
    except ImportError as e:
        log.warn("Warning: no pulseaudio information available")
        log.warn(" %s", e)
    except Exception:
        log.error("Error: failed to add pulseaudio info", exc_info=True)
    return {}


class AudioClient(AudioKeepaliveMixin, StubClientMixin):
    """
    Utility mixin for clients that handle audio
    """
    __signals__ = ["speaker-changed", "microphone-changed", "audio-initialized"]
    PREFIX = "audio"

    def __init__(self, client=None):
        StubClientMixin.__init__(self, client)
        self.source_plugin = ""
        self.speaker_allowed: bool = False
        self.speaker_enabled: bool = False
        self.speaker_codecs = []
        self.microphone_allowed: bool = False
        self.microphone_enabled: bool = False
        self.microphone_codecs = []
        self.microphone_device = ""
        self.av_sync: bool = False
        self.av_sync_delta: int = AV_SYNC_DELTA
        self.properties: typedict = typedict()
        # audio state:
        self.on_sink_ready: Callable[[], None] = noop
        self.sink = None
        self.sink_sequence: int = 0
        self.source = None
        self.source_sequence: int = 0
        self.server_eos_sequence: bool = False
        self.in_bytecount: int = 0
        self.out_bytecount: int = 0
        self.resume_restart = False
        self.server_av_sync: bool = False
        self.server_pulseaudio_id = ""
        self.server_pulseaudio_server = ""
        self.server_decoders: Sequence[str] = ()
        self.server_encoders: Sequence[str] = ()
        self.server_receive: bool = False
        self.server_send: bool = False
        self.init_audio_keepalive_state()
        self.queue_used_sent: int = 0
        self.wants_capabilities = False            # flag indicating that the server wants 'audio-capabilities'
        # duplicated from ServerInfo mixin:
        self._remote_machine_id = ""

    def init(self, opts) -> None:
        self.av_sync = opts.av_sync
        self.speaker_allowed = audio_option(opts.speaker) in ("on", "off")
        # ie: "on", "off", "on:Some Device", "off:Some Device"
        mic = [x.strip() for x in opts.microphone.split(":", 1)]
        self.microphone_allowed = audio_option(mic[0]) in ("on", "off")
        self.speaker_enabled = self.speaker_allowed and audio_option(opts.speaker) == "on"
        self.microphone_enabled = self.microphone_allowed and audio_option(mic[0]) == "on"
        self.microphone_device = ""
        if self.microphone_allowed and len(mic) == 2:
            self.microphone_device = mic[1]
        self.source_plugin = opts.audio_source
        # these are not validated yet:
        self.speaker_codecs = opts.speaker_codec
        self.microphone_codecs = opts.microphone_codec
        # audio tagging:
        init_audio_tagging(opts.tray_icon)

    def load(self):
        if power := self.get_subsystem("power"):
            power.connect("suspend", self.suspend_audio)
            power.connect("resume", self.resume_audio)
        if BACKWARDS_COMPATIBLE:
            self.properties = self.query_audio()
            self.properties.update(get_pa_info())
            return

        def do_load() -> None:
            # set `self.properties` last when loading is complete:
            sleep(1.5)
            properties = self.query_audio()
            # get_pa_info() must be called from the main thread
            # because it may access the $DISPLAY

            def add_ui_info() -> None:
                properties.update(get_pa_info())
                self.properties = properties
                if self.wants_capabilities:
                    self.send_audio_capabilities()
            self.idle_add(add_ui_info)
        start_thread(do_load, "audio-query-thread", daemon=True)

    def query_audio(self) -> typedict:
        audio_option_fn: Callable = nooptions
        properties = typedict()
        if self.speaker_allowed or self.microphone_allowed:
            def noaudio(title: str, message: str) -> typedict:
                self.may_notify(title, message)
                self.speaker_allowed = False
                self.microphone_allowed = False
                return properties
            try:
                from xpra.audio import common
                assert common
            except ImportError:
                return noaudio("No Audio",
                               "`xpra-audio` subsystem is not installed\n"
                               " speaker and microphone forwarding are disabled")
            try:
                from xpra.audio.common import audio_option_or_all
                audio_option_fn = audio_option_or_all
                from xpra.audio.wrapper import query_audio
                sleep(QUERY_SLEEP)
                properties = query_audio()
                if not properties:
                    return noaudio("No Audio",
                                   "Audio subsystem query failed, is GStreamer installed?")
                gstv = properties.strtupleget("gst.version")
                if gstv:
                    log.info("GStreamer version %s", ".".join(gstv[:3]))
                else:
                    log.info("GStreamer loaded")
            except Exception as e:
                log("failed to query audio", exc_info=True)
                return noaudio("No Audio",
                               f"Error querying the audio subsystem:\n{e}")
        encoders = properties.strtupleget("encoders")
        decoders = properties.strtupleget("decoders")
        # validate the options against the list of codecs available:
        self.speaker_codecs = audio_option_fn("speaker-codec", self.speaker_codecs, decoders)
        self.microphone_codecs = audio_option_fn("microphone-codec", self.microphone_codecs, encoders)
        if not self.speaker_codecs:
            self.speaker_allowed = False
        if not self.microphone_codecs:
            self.microphone_allowed = False
        self.speaker_enabled &= self.speaker_allowed
        self.microphone_enabled &= self.microphone_allowed
        log("speaker: codecs=%s, allowed=%s, enabled=%s", encoders, self.speaker_allowed, csv(self.speaker_codecs))
        log("microphone: codecs=%s, allowed=%s, enabled=%s, default device=%s",
            decoders, self.microphone_allowed, csv(self.microphone_codecs), self.microphone_device)
        log("av-sync=%s", self.av_sync)
        return properties

    def cleanup(self) -> None:
        self.cancel_audio_keepalive_timers()
        self.stop_all_audio()

    def stop_all_audio(self) -> None:
        if self.source:
            self.stop_sending_audio()
        if self.sink:
            self.stop_receiving_audio()

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "speaker": self.speaker_enabled,
            "microphone": self.microphone_enabled,
            "properties": dict(self.properties),
        }
        if ss := self.source:
            info["src"] = ss.get_info()
        if ss := self.sink:
            info["sink"] = ss.get_info()
        return {AudioClient.PREFIX: info}

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "av-sync": self.get_avsync_capabilities(),
        }
        if BACKWARDS_COMPATIBLE:
            caps[AudioClient.PREFIX] = self.get_audio_capabilities()
        else:
            caps[AudioClient.PREFIX] = {"async": True}
        return caps

    def get_audio_capabilities(self) -> dict[str, Any]:
        if not self.properties:
            return {}
        caps: dict[str, Any] = {
            "decoders": self.speaker_codecs,
            "encoders": self.microphone_codecs,
            "send": self.microphone_allowed,
            "receive": self.speaker_allowed,
        }
        caps.update(self.get_audio_keepalive_caps())
        # make mypy happy about the type: convert typedict to dict with string keys
        sp: dict[str, Any] = {str(k): v for k, v in self.properties.items()}
        if FULL_INFO < 2:
            # only expose these specific keys:
            expose = ("encoders", "decoders", "muxers", "demuxers")
            sp = {k: v for k, v in sp.items() if k in expose}
        caps.update(sp)
        log("audio capabilities: %s", caps)
        return caps

    def get_avsync_capabilities(self) -> dict[str, Any]:
        if not self.av_sync:
            return {}
        delay = max(0, DEFAULT_AV_SYNC_DELAY + AV_SYNC_DELTA)
        return {
            "": True,
            "enabled": True,
            "delay.default": delay,
            "delay": delay,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_av_sync = c.boolget("av-sync.enabled")
        avsynclog("av-sync: server=%s, client=%s", self.server_av_sync, self.av_sync)
        audio = typedict(c.dictget("audio"))
        log("audio capabilities: %s", audio)
        if audio.boolget("async"):
            if self.properties:
                self.send_audio_capabilities()
            else:
                self.wants_capabilities = True
        else:
            self.parse_audio_capabilities(audio)
            self.auto_start()
            self.emit("audio-initialized")
        return True

    def send_audio_capabilities(self) -> None:
        caps = self.get_audio_capabilities()
        log("send_audio_capabilities: %s", caps)
        self.send("audio-capabilities", caps)

    def parse_audio_capabilities(self, audio: typedict) -> None:
        log("parse_audio_capabilities(%s)", audio)
        self.server_pulseaudio_id = audio.strget("pulseaudio.id")
        self.server_pulseaudio_server = audio.strget("pulseaudio.server")
        self.server_decoders = audio.strtupleget("decoders")
        self.server_encoders = audio.strtupleget("encoders")
        self.server_receive = audio.boolget("receive")
        self.server_send = audio.boolget("send")
        self.parse_audio_keepalive_caps(audio)
        log("pulseaudio id=%s, server=%s", self.server_pulseaudio_id, self.server_pulseaudio_server)
        log("audio decoders=%s, audio encoders=%s, receive=%s, send=%s",
            csv(self.server_decoders), csv(self.server_encoders),
            self.server_receive, self.server_send)

    def auto_start(self) -> None:
        if self.server_send and self.speaker_enabled:
            self.start_receiving_audio()
        if self.server_receive and self.microphone_enabled:
            # call via idle_add because we may query X11 properties
            # to find the pulseaudio server:
            self.idle_add(self.start_sending_audio)
        if self.audio_keepalive_enabled():
            self.schedule_audio_keepalive()

    def suspend_audio(self, _client) -> None:
        self.resume_restart = bool(self.sink)
        if self.sink:
            self.stop_receiving_audio()
        if self.source:
            self.stop_sending_audio()

    def resume_audio(self, _client) -> None:
        if self.resume_restart:
            self.resume_restart = False
            self.start_receiving_audio()

    ######################################################################
    # audio:

    def may_notify(self, summary: str, body: str) -> None:
        may_notify_client(self.client, NotificationID.AUDIO, summary, body, icon_name="audio")

    def loop_check(self, mode="speaker") -> bool:
        from xpra.audio.gstreamer_util import ALLOW_SOUND_LOOP, loop_warning_messages
        if ALLOW_SOUND_LOOP:
            return True
        if self._remote_machine_id:
            if self._remote_machine_id != get_machine_id():
                # not the same machine, so OK
                return True
            if self._remote_uuid != get_user_uuid():
                # different user, assume different pulseaudio server
                return True
        # check pulseaudio id if we have it
        pulseaudio_id = self.properties.get("pulseaudio", {}).get("id")
        if not pulseaudio_id or not self.server_pulseaudio_id:
            # not available, assume no pulseaudio so no loop?
            return True
        if self.server_pulseaudio_id != pulseaudio_id:
            # different pulseaudio server
            return True
        msgs = loop_warning_messages(mode)
        summary = msgs[0]
        body = "\n".join(msgs[1:])
        self.may_notify(summary, body)
        log.warn("Warning: %s", summary)
        for x in msgs[1:]:
            log.warn(" %s", x)
        return False

    def no_matching_codec_error(self, forwarding="speaker",
                                server_codecs: Iterable[str] = (), client_codecs: Iterable[str] = ()) -> None:
        summary = "Failed to start %s forwarding" % forwarding
        body = "No matching codecs between client and server"
        self.may_notify(summary, body)
        log.error("Error: %s", summary)
        log.error(" server supports: %s", csv(server_codecs))
        log.error(" client supports: %s", csv(client_codecs))

    def start_sending_audio(self, device="") -> None:
        """ (re)start an audio source and emit client signal """
        log("start_sending_audio(%s)", device)
        enabled = False
        try:
            assert self.microphone_allowed, "microphone forwarding is disabled"
            assert self.server_receive, "client support for receiving audio is disabled"
            if not self.loop_check("microphone"):
                return
            if ss := self.source:
                enabled = True
                if ss.get_state() == "active":
                    log.error("Error: microphone forwarding is already active")
                else:
                    ss.start()
            else:
                enabled = self.start_source(device)
        finally:
            if enabled != self.microphone_enabled:
                self.microphone_enabled = enabled
                self.emit("microphone-changed")
            log("start_sending_audio(%s) done, microphone_enabled=%s", device, enabled)

    def start_source(self, device="") -> bool:
        log("start_source(%s)", device)
        assert self.source is None

        def audio_source_state_changed(*_args) -> None:
            self.emit("microphone-changed")

        # find the matching codecs:
        matching_codecs = get_matching_codecs(self.microphone_codecs, self.server_decoders)
        log("start_source(%s) matching codecs: %s", device, csv(matching_codecs))
        if not matching_codecs:
            self.no_matching_codec_error("microphone", self.server_decoders, self.microphone_codecs)
            return False
        try:
            from xpra.audio.wrapper import start_sending_audio
            plugins = self.properties.get("sources")
            ss = start_sending_audio(plugins, self.source_plugin, device or self.microphone_device,
                                     "", 1.0, False, matching_codecs,
                                     self.server_pulseaudio_server, self.server_pulseaudio_id)
            if not ss:
                return False
            self.source = ss
            ss.sequence = self.source_sequence
            ss.connect("new-buffer", self.new_buffer)
            ss.connect("state-changed", audio_source_state_changed)
            ss.connect("new-stream", self.new_stream)
            ss.start()
            log("start_source(%s) audio source %s started", device, ss)
            return True
        except Exception as e:
            self.may_notify("Failed to start microphone forwarding", "%s" % e)
            log.error("Error setting up microphone forwarding:")
            log.estr(e)
            return False

    def new_stream(self, source, codec: str) -> None:
        log("new_stream(%s)", codec)
        if self.source != source:
            log("dropping new-stream signal (current source=%s, signal source=%s)", self.source, source)
            return
        codec = codec or source.codec
        source.codec = codec
        # tell the server this is the start:
        self.send(AUDIO_DATA_PACKET, codec, (), {
            "start-of-stream": True,
            "codec": codec,
        })

    def stop_sending_audio(self) -> None:
        """ stop the audio source and emit client signal """
        ss = self.source
        log("stop_sending_audio() audio source=%s", ss)
        if self.microphone_enabled:
            self.microphone_enabled = False
            self.emit("microphone-changed")
        self.source = None
        if ss is None:
            log.warn("Warning: cannot stop audio capture which has not been started")
            return
        # tell the server to stop:
        self.send(AUDIO_DATA_PACKET, ss.codec or "", (), {
            "end-of-stream": True,
            "sequence": ss.sequence,
        })
        self.source_sequence += 1
        ss.cleanup()
        if not self.sink:
            self.cancel_audio_keepalive_timers()

    def start_receiving_audio(self) -> None:
        """ ask the server to start sending audio and emit the client signal """
        log("start_receiving_audio() audio sink=%s", self.sink)
        enabled = False
        try:
            if self.sink is not None:
                log("start_receiving_audio: we already have an audio sink")
                enabled = True
                return
            if not self.server_send:
                log.error("Error receiving audio: support not enabled on the server")
                return
            if not self.loop_check("speaker"):
                return
            # choose a codec:
            matching_codecs = get_matching_codecs(self.speaker_codecs, self.server_encoders)
            log("start_receiving_audio() matching codecs: %s", csv(matching_codecs))
            if not matching_codecs:
                self.no_matching_codec_error("speaker", self.server_encoders, self.speaker_codecs)
                return
            codec = matching_codecs[0]

            def sink_ready(*args) -> None:
                scodec = codec
                log("sink_ready(%s) codec=%s (server codec name=%s)", args, codec, scodec)
                self.send(AUDIO_CONTROL_PACKET, "start", scodec)

            self.on_sink_ready = sink_ready
            enabled = self.start_sink(codec)
        finally:
            if self.speaker_enabled != enabled:
                self.speaker_enabled = enabled
                self.emit("speaker-changed")
            log("start_receiving_audio() done, speaker_enabled=%s", enabled)

    def stop_receiving_audio(self, tell_server: bool = True) -> None:
        """
            ask the server to stop sending audio
            and toggle the flag so that we ignore further packets
            and emit the `new-sequence` client signal
        """
        ss = self.sink
        log("stop_receiving_audio(%s) audio sink=%s", tell_server, ss)
        if self.speaker_enabled:
            self.speaker_enabled = False
            self.emit("speaker-changed")
        if not ss:
            return
        if tell_server and ss.sequence == self.sink_sequence:
            self.send(AUDIO_CONTROL_PACKET, "stop", self.sink_sequence)
        self.sink_sequence += 1
        self.send(AUDIO_CONTROL_PACKET, "new-sequence", self.sink_sequence)
        self.sink = None
        log("stop_receiving_audio(%s) calling %s", tell_server, ss.cleanup)
        ss.cleanup()
        log("stop_receiving_audio(%s) done", tell_server)
        if not self.source:
            self.cancel_audio_keepalive_timers()

    def sink_state_changed(self, sink, state: str) -> None:
        if sink != self.sink:
            log("sink_state_changed(%s, %s) not the current sink, ignoring it", sink, state)
            return
        log("sink_state_changed(%s, %s) on_sink_ready=%s", sink, state, self.on_sink_ready)
        if state == "ready":
            self.on_sink_ready()
            self.on_sink_ready = noop
        self.emit("speaker-changed")

    def sink_bitrate_changed(self, sink, bitrate: int) -> None:
        if sink != self.sink:
            log("sink_bitrate_changed(%s, %s) not the current sink, ignoring it", sink, bitrate)
            return
        log("sink_bitrate_changed(%s, %s)", sink, bitrate)
        # not shown in the UI, so don't bother with emitting a signal:
        # self.emit("speaker-changed")

    def sink_error(self, sink, error) -> None:
        log("sink_error(%s, %s) exit_code=%s, current sink=%s",
            sink, error, self.client.exit_code, self.sink)
        if self.client.exit_code is not None:
            # exiting
            return
        if sink != self.sink:
            log("sink_error(%s, %s) not the current sink, ignoring it", sink, error)
            return
        estr = bytestostr(error).replace("gst-resource-error-quark: ", "")
        if "AUDIO_DEVICE_CHANGED" in estr:
            # audio subprocess detected a device change — restart quickly:
            log.info("audio output device changed, restarting speaker")
            self.stop_receiving_audio()
            self.idle_add(self._restart_audio_after_device_change)
            return
        if _is_recoverable_audio_error(estr):
            # recoverable device error (e.g. WASAPI invalidation before monitor detected it):
            log.info("audio device removed, waiting for new device")
            self.resume_restart = True
        else:
            self.may_notify("Speaker forwarding error", estr)
            log.warn("Error: stopping speaker:")
            log.warn(" %s", estr)
        self.stop_receiving_audio()

    DEVICE_RESTART_INITIAL_MS = 1000
    DEVICE_RESTART_MAX_MS = 60000

    def _restart_audio_after_device_change(self, delay: int = 200) -> None:
        """Restart audio after a device change with exponential backoff on failure."""
        def do_restart():
            if not self.start_receiving_audio():
                next_delay = min(delay * 2, self.DEVICE_RESTART_MAX_MS)
                log.info("audio restart failed, retrying in %dms", next_delay)
                self.timeout_add(next_delay, lambda: self._restart_audio_after_device_change(next_delay))
        self.timeout_add(delay, do_restart)

    def process_stopped(self, sink, *args) -> None:
        if self.client.exit_code is not None:
            # exiting
            return
        if sink != self.sink:
            log("process_stopped(%s, %s) not the current sink, ignoring it", sink, args)
            return
        log.warn("Warning: the audio process has stopped")
        self.stop_receiving_audio()

    def sink_exit(self, sink, *args) -> None:
        log("sink_exit(%s, %s) sink=%s", sink, args, self.sink)
        if self.client.exit_code is not None:
            # exiting
            return
        ss = self.sink
        if sink != ss:
            log("sink_exit() not the current sink, ignoring it")
            return
        if ss and ss.codec:
            # the mandatory "I've been naughty warning":
            # we use the "codec" field as guard to ensure we only print this warning once…
            log.warn("Warning: the %s audio sink has stopped", ss.codec)
            ss.codec = ""
        self.stop_receiving_audio()

    def start_sink(self, codec: str) -> bool:
        log("start_sink(%s)", codec)
        assert self.sink is None, "audio sink already exists!"
        try:
            log("starting %s audio sink", codec)
            from xpra.audio.wrapper import start_receiving_audio
            ss = start_receiving_audio(codec)
            if not ss:
                return False
            ss.sequence = self.sink_sequence
            self.sink = ss
            ss.connect("state-changed", self.sink_state_changed)
            ss.connect("error", self.sink_error)
            ss.connect("exit", self.sink_exit)
            ss.connect(CONNECTION_LOST, self.process_stopped)
            ss.start()
            log("%s audio sink started", codec)
            return True
        except Exception as e:
            log.error("Error: failed to start audio sink", exc_info=True)
            self.sink_error(self.sink, e)
            return False

    def new_buffer(self, source, data: bytes,
                   metadata: dict, packet_metadata: Sequence[SizedBuffer] = ()) -> None:
        log("new_buffer(%s, %s, %s, %s)", source, len(data or ()), metadata, packet_metadata)
        if source.sequence < self.source_sequence:
            log("audio buffer dropped: old sequence number: %s (current is %s)",
                source.sequence, self.source_sequence)
            return
        self.out_bytecount += len(data)
        for x in packet_metadata:
            self.out_bytecount += len(x)
        metadata["sequence"] = source.sequence
        if not self.audio_keepalive_may_send(source.codec, metadata):
            return
        self.send_data(source, data, metadata, packet_metadata)
        self.schedule_audio_keepalive_check()

    def send_data(self, source, data: bytes,
                  metadata: dict, packet_metadata: Sequence[SizedBuffer]) -> None:
        codec = source.codec
        # tag the packet metadata as already compressed:
        pmetadata = Compressed("packet metadata", packet_metadata)
        packet_data = [codec, Compressed(codec, data), metadata, pmetadata]
        self.send(AUDIO_DATA_PACKET, *packet_data)

    def send_audio_keepalive_packet(self, timestamp: int) -> None:
        self.send(AUDIO_KEEPALIVE_PACKET, timestamp)

    def audio_keepalive_active(self) -> bool:
        """ override the keepalive superclass implementation because our attributes have been renamed / shortened """
        return bool(self.source or self.sink)

    def get_audio_keepalive_codec(self) -> str:
        """ override the keepalive superclass implementation because our attributes have been renamed / shortened """
        return self.source.codec if self.source else ""

    def audio_keepalive_timer_add(self, delay: int, fn) -> int:
        return self.timeout_add(delay, fn)

    def audio_keepalive_timer_remove(self, timer: int) -> None:
        self.source_remove(timer)

    def _process_audio_keepalive(self, packet: Packet) -> None:
        self.audio_keepalive(packet.get_u64(1))

    def send_audio_sync(self, v: int) -> None:
        if self.server_av_sync:
            self.send(AUDIO_CONTROL_PACKET, "sync", v)

    ######################################################################
    # packet handlers
    def _process_audio_capabilities(self, packet: Packet) -> None:
        audio = typedict(packet.get_dict(1))
        self.parse_audio_capabilities(audio)
        self.auto_start()
        self.emit("audio-initialized")

    def _process_audio_data(self, packet: Packet) -> None:
        codec = packet.get_str(1)
        data = packet.get_buffer(2)
        metadata = typedict(packet.get_dict(3))
        self.update_latest_received_audio_timestamp(metadata)
        # the server may send packet_metadata, which is pushed before the actual audio data:
        packet_metadata = ()
        if len(packet) > 4:
            packet_metadata = packet.get_bytes_seq(4)
        if data:
            self.in_bytecount += len(data)
        # verify sequence number if present:
        seq = metadata.intget("sequence", -1)
        if self.sink_sequence > 0 and 0 <= seq < self.sink_sequence:
            log("ignoring audio data with old sequence number %s (now on %s)", seq, self.sink_sequence)
            return

        if not self.speaker_enabled:
            if metadata.boolget("start-of-stream"):
                # server is asking us to start playing audio
                if not self.speaker_allowed:
                    # no can do!
                    log.warn("Warning: cannot honour the request to start the speaker")
                    log.warn(" speaker forwarding is disabled")
                    self.stop_receiving_audio(True)
                    return
                self.speaker_enabled = True
                self.emit("speaker-changed")
                self.on_sink_ready = noop
                codec = metadata.strget("codec")
                log("starting speaker on server request using codec %s", codec)
                self.start_sink(codec)
            else:
                log("speaker is now disabled - dropping packet")
                return
        ss = self.sink
        if ss is None:
            log("no audio sink to process audio data, dropping it")
            return
        if metadata.boolget("end-of-stream"):
            log("server sent end-of-stream for sequence %s, closing audio pipeline", seq)
            self.stop_receiving_audio(False)
            return
        if codec != ss.codec:
            log.error("Error: audio codec change is not supported!")
            log.error(" stream tried to switch from %s to %s", ss.codec, codec)
            self.stop_receiving_audio()
            return
        if ss.get_state() == "stopped":
            log("audio data received, audio sink is stopped - telling server to stop")
            self.stop_receiving_audio()
            return
        # (some packets (ie: sos, eos) only contain metadata)
        if data or packet_metadata:
            ss.add_data(data, dict(metadata), packet_metadata)
        if self.av_sync and self.server_av_sync:
            qinfo = typedict(ss.get_info()).dictget("queue")
            queue_used = typedict(qinfo or {}).intget("cur", -1)
            if queue_used < 0:
                return
            delta = (self.queue_used_sent or 0) - queue_used
            # avsynclog("server audio sync: queue info=%s, last sent=%s, delta=%s",
            #    dict((k,v) for (k,v) in info.items() if k.startswith("queue")), self.queue_used_sent, delta)
            if self.queue_used_sent is None or abs(delta) >= DELTA_THRESHOLD:
                avsynclog("server audio sync: sending updated queue.used=%i (was %s)",
                          queue_used, (self.queue_used_sent or "unset"))
                self.queue_used_sent = queue_used
                v = queue_used + self.av_sync_delta
                if self.av_sync_delta:
                    avsynclog(" adjusted value=%i with sync delta=%i", v, self.av_sync_delta)
                self.send_audio_sync(v)

    def init_authenticated_packet_handlers(self) -> None:
        log("init_authenticated_packet_handlers()")
        # this handler can run directly from the network thread:
        self.add_packets(f"{AudioClient.PREFIX}-data")
        self.add_packets(f"{AudioClient.PREFIX}-capabilities", main_thread=True)
        self.add_packets(AUDIO_KEEPALIVE_PACKET)
        self.add_legacy_alias("sound-data", f"{AudioClient.PREFIX}-data")
