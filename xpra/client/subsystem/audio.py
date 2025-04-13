# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable, Sequence, Iterable

from xpra.platform.paths import get_icon_filename
from xpra.scripts.parsing import audio_option
from xpra.net.common import PacketType
from xpra.net.compression import Compressed
from xpra.net.protocol.constants import CONNECTION_LOST
from xpra.common import FULL_INFO, noop, SizedBuffer
from xpra.os_util import get_machine_id, get_user_uuid, gi_import, OSX, POSIX
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, bytestostr, memoryview_to_bytes
from xpra.util.env import envint
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger

avsynclog = Logger("av-sync")
log = Logger("client", "audio")

GLib = gi_import("GLib")

AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA")
DELTA_THRESHOLD = envint("XPRA_AV_SYNC_DELTA_THRESHOLD", 40)
DEFAULT_AV_SYNC_DELAY = envint("XPRA_DEFAULT_AV_SYNC_DELAY", 150)


def init_audio_tagging(tray_icon) -> None:
    if not POSIX:
        return
    try:
        from xpra import audio
        assert audio
    except ImportError:
        log("no audio module, skipping pulseaudio tagging setup")
        return
    try:
        from xpra.audio.pulseaudio.util import set_icon_path
        tray_icon_filename = get_icon_filename(tray_icon or "xpra")
        set_icon_path(tray_icon_filename)
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


class AudioClient(StubClientMixin):
    """
    Utility mixin for clients that handle audio
    """
    __signals__ = ["speaker-changed", "microphone-changed"]
    PREFIX = "audio"

    def __init__(self):
        self.audio_source_plugin = ""
        self.speaker_allowed: bool = False
        self.speaker_enabled: bool = False
        self.speaker_codecs = []
        self.microphone_allowed: bool = False
        self.microphone_enabled: bool = False
        self.microphone_codecs = []
        self.microphone_device = ""
        self.av_sync: bool = False
        self.av_sync_delta: int = AV_SYNC_DELTA
        self.audio_properties: typedict = typedict()
        # audio state:
        self.on_sink_ready: Callable[[], None] = noop
        self.audio_sink = None
        self.audio_sink_sequence: int = 0
        self.server_audio_eos_sequence: bool = False
        self.audio_source = None
        self.audio_source_sequence: int = 0
        self.audio_in_bytecount: int = 0
        self.audio_out_bytecount: int = 0
        self.audio_resume_restart = False
        self.server_av_sync: bool = False
        self.server_pulseaudio_id = ""
        self.server_pulseaudio_server = ""
        self.server_audio_decoders: Sequence[str] = ()
        self.server_audio_encoders: Sequence[str] = ()
        self.server_audio_receive: bool = False
        self.server_audio_send: bool = False
        self.queue_used_sent: int = 0
        # duplicated from ServerInfo mixin:
        self._remote_machine_id = ""

    def init(self, opts) -> None:
        self.av_sync = opts.av_sync
        self.speaker_allowed = audio_option(opts.speaker) in ("on", "off")
        # ie: "on", "off", "on:Some Device", "off:Some Device"
        mic = [x.strip() for x in opts.microphone.split(":", 1)]
        self.microphone_allowed = audio_option(mic[0]) in ("on", "off")
        self.microphone_device = ""
        if self.microphone_allowed and len(mic) == 2:
            self.microphone_device = mic[1]
        self.audio_source_plugin = opts.audio_source

        audio_option_fn: Callable = nooptions
        if self.speaker_allowed or self.microphone_allowed:
            def noaudio(title: str, message: str) -> None:
                self.may_notify_audio(title, message)
                self.speaker_allowed = False
                self.microphone_allowed = False
            try:
                from xpra.audio import common
                assert common
            except ImportError:
                noaudio("No Audio",
                        "`xpra-audio` subsystem is not installed\n"
                        " speaker and microphone forwarding are disabled")
                return
            try:
                from xpra.audio.common import audio_option_or_all
                audio_option_fn = audio_option_or_all
                from xpra.audio.wrapper import query_audio
                self.audio_properties = query_audio()
                if not self.audio_properties:
                    noaudio("No Audio",
                            "Audio subsystem query failed, is GStreamer installed?")
                    return
                gstv = self.audio_properties.strtupleget("gst.version")
                if gstv:
                    log.info("GStreamer version %s", ".".join(gstv[:3]))
                else:
                    log.info("GStreamer loaded")
            except Exception as e:
                log("failed to query audio", exc_info=True)
                noaudio("No Audio",
                        "Error querying the audio subsystem:\n"
                        f"{e}")
                return
        encoders = self.audio_properties.strtupleget("encoders")
        decoders = self.audio_properties.strtupleget("decoders")
        self.speaker_codecs = audio_option_fn("speaker-codec", opts.speaker_codec, decoders)
        self.microphone_codecs = audio_option_fn("microphone-codec", opts.microphone_codec, encoders)
        if not self.speaker_codecs:
            self.speaker_allowed = False
        if not self.microphone_codecs:
            self.microphone_allowed = False
        self.speaker_enabled = self.speaker_allowed and audio_option(opts.speaker) == "on"
        self.microphone_enabled = self.microphone_allowed and audio_option(mic[0]) == "on"
        log("speaker: codecs=%s, allowed=%s, enabled=%s", encoders, self.speaker_allowed, csv(self.speaker_codecs))
        log("microphone: codecs=%s, allowed=%s, enabled=%s, default device=%s",
            decoders, self.microphone_allowed, csv(self.microphone_codecs), self.microphone_device)
        log("av-sync=%s", self.av_sync)
        if POSIX and not OSX:
            try:
                from xpra.audio.pulseaudio.util import get_info as get_pa_info
                pa_info = get_pa_info()
                log("pulseaudio info=%s", pa_info)
                self.audio_properties.update(pa_info)
            except ImportError as e:
                log.warn("Warning: no pulseaudio information available")
                log.warn(" %s", e)
            except Exception:
                log.error("Error: failed to add pulseaudio info", exc_info=True)
        # audio tagging:
        init_audio_tagging(opts.tray_icon)

    def cleanup(self) -> None:
        self.stop_all_audio()

    def stop_all_audio(self) -> None:
        if self.audio_source:
            self.stop_sending_audio()
        if self.audio_sink:
            self.stop_receiving_audio()

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "speaker": self.speaker_enabled,
            "microphone": self.microphone_enabled,
            "properties": dict(self.audio_properties),
        }
        ss = self.audio_source
        if ss:
            info["src"] = ss.get_info()
        ss = self.audio_sink
        if ss:
            info["sink"] = ss.get_info()
        return {AudioClient.PREFIX: info}

    def get_caps(self) -> dict[str, Any]:
        return {
            "av-sync": self.get_avsync_capabilities(),
            AudioClient.PREFIX: self.get_audio_capabilities(),
        }

    def get_audio_capabilities(self) -> dict[str, Any]:
        if not self.audio_properties:
            return {}
        caps: dict[str, Any] = {
            "decoders": self.speaker_codecs,
            "encoders": self.microphone_codecs,
            "send": self.microphone_allowed,
            "receive": self.speaker_allowed,
        }
        # make mypy happy about the type: convert typedict to dict with string keys
        sp: dict[str, Any] = {str(k): v for k, v in self.audio_properties.items()}
        if FULL_INFO < 2:
            # only expose these specific keys:
            sp = {k: v for k, v in sp.items() if k in (
                "encoders", "decoders", "muxers", "demuxers",
            )}
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
        audio = typedict(c.dictget("audio") or {})
        self.server_pulseaudio_id = audio.strget("pulseaudio.id")
        self.server_pulseaudio_server = audio.strget("pulseaudio.server")
        self.server_audio_decoders = audio.strtupleget("decoders")
        self.server_audio_encoders = audio.strtupleget("encoders")
        self.server_audio_receive = audio.boolget("receive")
        self.server_audio_send = audio.boolget("send")
        log("pulseaudio id=%s, server=%s, audio decoders=%s, audio encoders=%s, receive=%s, send=%s",
            self.server_pulseaudio_id, self.server_pulseaudio_server,
            csv(self.server_audio_decoders), csv(self.server_audio_encoders),
            self.server_audio_receive, self.server_audio_send)
        if self.server_audio_send and self.speaker_enabled:
            self.show_progress(90, "starting speaker forwarding")
            self.start_receiving_audio()
        if self.server_audio_receive and self.microphone_enabled:
            # call via idle_add because we may query X11 properties
            # to find the pulseaudio server:
            GLib.idle_add(self.start_sending_audio)
        return True

    def suspend(self) -> None:
        self.audio_resume_restart = bool(self.audio_sink)
        self.stop_receiving_audio()
        self.stop_sending_audio()

    def resume(self) -> None:
        ars = self.audio_resume_restart
        if ars:
            self.audio_resume_restart = False
            self.start_receiving_audio()

    ######################################################################
    # audio:

    def may_notify_audio(self, summary: str, body: str) -> None:
        # overridden in UI client subclass
        pass

    def audio_loop_check(self, mode="speaker") -> bool:
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
        pulseaudio_id = self.audio_properties.get("pulseaudio", {}).get("id")
        if not pulseaudio_id or not self.server_pulseaudio_id:
            # not available, assume no pulseaudio so no loop?
            return True
        if self.server_pulseaudio_id != pulseaudio_id:
            # different pulseaudio server
            return True
        msgs = loop_warning_messages(mode)
        summary = msgs[0]
        body = "\n".join(msgs[1:])
        self.may_notify_audio(summary, body)
        log.warn("Warning: %s", summary)
        for x in msgs[1:]:
            log.warn(" %s", x)
        return False

    def no_matching_codec_error(self, forwarding="speaker",
                                server_codecs: Iterable[str] = (), client_codecs: Iterable[str] = ()) -> None:
        summary = "Failed to start %s forwarding" % forwarding
        body = "No matching codecs between client and server"
        self.may_notify_audio(summary, body)
        log.error("Error: %s", summary)
        log.error(" server supports: %s", csv(server_codecs))
        log.error(" client supports: %s", csv(client_codecs))

    def start_sending_audio(self, device="") -> None:
        """ (re)start an audio source and emit client signal """
        log("start_sending_audio(%s)", device)
        enabled = False
        try:
            assert self.microphone_allowed, "microphone forwarding is disabled"
            assert self.server_audio_receive, "client support for receiving audio is disabled"
            if not self.audio_loop_check("microphone"):
                return
            ss = self.audio_source
            if ss:
                enabled = True
                if ss.get_state() == "active":
                    log.error("Error: microphone forwarding is already active")
                else:
                    ss.start()
            else:
                enabled = self.start_audio_source(device)
        finally:
            if enabled != self.microphone_enabled:
                self.microphone_enabled = enabled
                self.emit("microphone-changed")
            log("start_sending_audio(%s) done, microphone_enabled=%s", device, enabled)

    def start_audio_source(self, device="") -> bool:
        log("start_audio_source(%s)", device)
        assert self.audio_source is None

        def audio_source_state_changed(*_args) -> None:
            self.emit("microphone-changed")

        # find the matching codecs:
        matching_codecs = get_matching_codecs(self.microphone_codecs, self.server_audio_decoders)
        log("start_audio_source(%s) matching codecs: %s", device, csv(matching_codecs))
        if not matching_codecs:
            self.no_matching_codec_error("microphone", self.server_audio_decoders, self.microphone_codecs)
            return False
        try:
            from xpra.audio.wrapper import start_sending_audio
            plugins = self.audio_properties.get("sources")
            ss = start_sending_audio(plugins, self.audio_source_plugin, device or self.microphone_device,
                                     "", 1.0, False, matching_codecs,
                                     self.server_pulseaudio_server, self.server_pulseaudio_id)
            if not ss:
                return False
            self.audio_source = ss
            ss.sequence = self.audio_source_sequence
            ss.connect("new-buffer", self.new_audio_buffer)
            ss.connect("state-changed", audio_source_state_changed)
            ss.connect("new-stream", self.new_stream)
            ss.start()
            log("start_audio_source(%s) audio source %s started", device, ss)
            return True
        except Exception as e:
            self.may_notify_audio("Failed to start microphone forwarding", "%s" % e)
            log.error("Error setting up microphone forwarding:")
            log.estr(e)
            return False

    def new_stream(self, audio_source, codec: str) -> None:
        log("new_stream(%s)", codec)
        if self.audio_source != audio_source:
            log("dropping new-stream signal (current source=%s, signal source=%s)", self.audio_source, audio_source)
            return
        codec = codec or audio_source.codec
        audio_source.codec = codec
        # tell the server this is the start:
        self.send("sound-data", codec, b"",
                  {
                      "start-of-stream": True,
                      "codec": codec,
                  })

    def stop_sending_audio(self) -> None:
        """ stop the audio source and emit client signal """
        ss = self.audio_source
        log("stop_sending_audio() audio source=%s", ss)
        if self.microphone_enabled:
            self.microphone_enabled = False
            self.emit("microphone-changed")
        self.audio_source = None
        if ss is None:
            log.warn("Warning: cannot stop audio capture which has not been started")
            return
        # tell the server to stop:
        self.send("sound-data", ss.codec or "", b"", {
            "end-of-stream": True,
            "sequence": ss.sequence,
        })
        self.audio_source_sequence += 1
        ss.cleanup()

    def start_receiving_audio(self) -> None:
        """ ask the server to start sending audio and emit the client signal """
        log("start_receiving_audio() audio sink=%s", self.audio_sink)
        enabled = False
        try:
            if self.audio_sink is not None:
                log("start_receiving_audio: we already have an audio sink")
                enabled = True
                return
            if not self.server_audio_send:
                log.error("Error receiving audio: support not enabled on the server")
                return
            if not self.audio_loop_check("speaker"):
                return
            # choose a codec:
            matching_codecs = get_matching_codecs(self.speaker_codecs, self.server_audio_encoders)
            log("start_receiving_audio() matching codecs: %s", csv(matching_codecs))
            if not matching_codecs:
                self.no_matching_codec_error("speaker", self.server_audio_encoders, self.speaker_codecs)
                return
            codec = matching_codecs[0]

            def sink_ready(*args) -> bool:
                scodec = codec
                log("sink_ready(%s) codec=%s (server codec name=%s)", args, codec, scodec)
                self.send("sound-control", "start", scodec)
                return False

            self.on_sink_ready = sink_ready
            enabled = self.start_audio_sink(codec)
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
        ss = self.audio_sink
        log("stop_receiving_audio(%s) audio sink=%s", tell_server, ss)
        if self.speaker_enabled:
            self.speaker_enabled = False
            self.emit("speaker-changed")
        if not ss:
            return
        if tell_server and ss.sequence == self.audio_sink_sequence:
            self.send("sound-control", "stop", self.audio_sink_sequence)
        self.audio_sink_sequence += 1
        self.send("sound-control", "new-sequence", self.audio_sink_sequence)
        self.audio_sink = None
        log("stop_receiving_audio(%s) calling %s", tell_server, ss.cleanup)
        ss.cleanup()
        log("stop_receiving_audio(%s) done", tell_server)

    def audio_sink_state_changed(self, audio_sink, state: str) -> None:
        if audio_sink != self.audio_sink:
            log("audio_sink_state_changed(%s, %s) not the current sink, ignoring it", audio_sink, state)
            return
        log("audio_sink_state_changed(%s, %s) on_sink_ready=%s", audio_sink, state, self.on_sink_ready)
        if state == "ready":
            self.on_sink_ready()
            self.on_sink_ready = noop
        self.emit("speaker-changed")

    def audio_sink_bitrate_changed(self, audio_sink, bitrate: int) -> None:
        if audio_sink != self.audio_sink:
            log("audio_sink_bitrate_changed(%s, %s) not the current sink, ignoring it", audio_sink, bitrate)
            return
        log("audio_sink_bitrate_changed(%s, %s)", audio_sink, bitrate)
        # not shown in the UI, so don't bother with emitting a signal:
        # self.emit("speaker-changed")

    def audio_sink_error(self, audio_sink, error) -> None:
        log("audio_sink_error(%s, %s) exit_code=%s, current sink=%s",
            audio_sink, error, self.exit_code, self.audio_sink)
        if self.exit_code is not None:
            # exiting
            return
        if audio_sink != self.audio_sink:
            log("audio_sink_error(%s, %s) not the current sink, ignoring it", audio_sink, error)
            return
        estr = bytestostr(error).replace("gst-resource-error-quark: ", "")
        self.may_notify_audio("Speaker forwarding error", estr)
        log.warn("Error: stopping speaker:")
        log.warn(" %s", estr)
        self.stop_receiving_audio()

    def audio_process_stopped(self, audio_sink, *args) -> None:
        if self.exit_code is not None:
            # exiting
            return
        if audio_sink != self.audio_sink:
            log("audio_process_stopped(%s, %s) not the current sink, ignoring it", audio_sink, args)
            return
        log.warn("Warning: the audio process has stopped")
        self.stop_receiving_audio()

    def audio_sink_exit(self, audio_sink, *args) -> None:
        log("audio_sink_exit(%s, %s) audio_sink=%s", audio_sink, args, self.audio_sink)
        if self.exit_code is not None:
            # exiting
            return
        ss = self.audio_sink
        if audio_sink != ss:
            log("audio_sink_exit() not the current sink, ignoring it")
            return
        if ss and ss.codec:
            # the mandatory "I've been naughty warning":
            # we use the "codec" field as guard to ensure we only print this warning once…
            log.warn("Warning: the %s audio sink has stopped", ss.codec)
            ss.codec = ""
        self.stop_receiving_audio()

    def start_audio_sink(self, codec: str) -> bool:
        log("start_audio_sink(%s)", codec)
        assert self.audio_sink is None, "audio sink already exists!"
        try:
            log("starting %s audio sink", codec)
            from xpra.audio.wrapper import start_receiving_audio
            ss = start_receiving_audio(codec)
            if not ss:
                return False
            ss.sequence = self.audio_sink_sequence
            self.audio_sink = ss
            ss.connect("state-changed", self.audio_sink_state_changed)
            ss.connect("error", self.audio_sink_error)
            ss.connect("exit", self.audio_sink_exit)
            ss.connect(CONNECTION_LOST, self.audio_process_stopped)
            ss.start()
            log("%s audio sink started", codec)
            return True
        except Exception as e:
            log.error("Error: failed to start audio sink", exc_info=True)
            self.audio_sink_error(self.audio_sink, e)
            return False

    def new_audio_buffer(self, audio_source, data: bytes,
                         metadata: dict, packet_metadata: Sequence[SizedBuffer] = ()) -> None:
        log("new_audio_buffer(%s, %s, %s, %s)", audio_source, len(data or ()), metadata, packet_metadata)
        if audio_source.sequence < self.audio_source_sequence:
            log("audio buffer dropped: old sequence number: %s (current is %s)",
                audio_source.sequence, self.audio_source_sequence)
            return
        self.audio_out_bytecount += len(data)
        for x in packet_metadata:
            self.audio_out_bytecount += len(x)
        metadata["sequence"] = audio_source.sequence
        self.send_audio_data(audio_source, data, metadata, packet_metadata)

    def send_audio_data(self, audio_source, data: bytes,
                        metadata: dict, packet_metadata: Sequence[SizedBuffer]) -> None:
        codec = audio_source.codec
        # tag the packet metadata as already compressed:
        pmetadata = Compressed("packet metadata", packet_metadata)
        packet_data = [codec, Compressed(codec, data), metadata, pmetadata]
        self.send("sound-data", *packet_data)

    def send_audio_sync(self, v: int) -> None:
        self.send("sound-control", "sync", v)

    ######################################################################
    # packet handlers

    def _process_audio_data(self, packet: PacketType) -> None:
        codec = str(packet[1])
        data = memoryview_to_bytes(packet[2])
        metadata = typedict(packet[3])
        # the server may send packet_metadata, which is pushed before the actual audio data:
        packet_metadata = ()
        if len(packet) > 4:
            packet_metadata = packet[4]
        if data:
            self.audio_in_bytecount += len(data)
        # verify sequence number if present:
        seq = metadata.intget("sequence", -1)
        if self.audio_sink_sequence > 0 and 0 <= seq < self.audio_sink_sequence:
            log("ignoring audio data with old sequence number %s (now on %s)", seq, self.audio_sink_sequence)
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
                self.start_audio_sink(codec)
            else:
                log("speaker is now disabled - dropping packet")
                return
        ss = self.audio_sink
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
        self.add_legacy_alias("sound-data", f"{AudioClient.PREFIX}-data")
