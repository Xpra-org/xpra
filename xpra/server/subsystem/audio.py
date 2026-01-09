# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from threading import Event
from collections.abc import Callable, Sequence

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.env import first_time
from xpra.net.common import Packet
from xpra.util.thread import start_thread
from xpra.scripts.parsing import audio_option
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio")


class AudioServer(StubServerMixin):
    """
    Mixin for servers that handle audio forwarding.
    """
    PREFIX = "audio"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.audio_initialized = Event()
        self.audio_source_plugin = ""
        self.supports_speaker = False
        self.supports_microphone = False
        self.speaker_allowed = False
        self.microphone_allowed = False
        self.speaker_codecs: Sequence[str] = ()
        self.microphone_codecs: Sequence[str] = ()
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
        log("AudioServer.init(..) supports speaker=%s, microphone=%s",
            self.supports_speaker, self.supports_microphone)
        self.av_sync = opts.av_sync
        log("AudioServer.init(..) av-sync=%s", self.av_sync)

    def threaded_setup(self) -> None:
        # this is slow, use a separate thread:
        start_thread(self.init_audio_options, "audio-setup", True)

    def get_info(self, _proto) -> dict[str, Any]:
        if self.audio_properties:
            return {AudioServer.PREFIX: dict(self.audio_properties)}
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
                    log.info("Audio subsystem query failed, is GStreamer installed?")
                    noaudio()
                    return
                gstv = self.audio_properties.strtupleget("gst.version")
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
        encoders = self.audio_properties.strtupleget("encoders")
        decoders = self.audio_properties.strtupleget("decoders")
        self.speaker_codecs = parse_codecs("speaker-codec", self.speaker_codecs, encoders)
        self.microphone_codecs = parse_codecs("microphone-codec", self.microphone_codecs, decoders)
        if not self.speaker_codecs:
            self.supports_speaker = False
        if not self.microphone_codecs:
            self.supports_microphone = False
        self.audio_initialized.set()

        # query_pulseaudio_properties may access X11,
        # so call it from the main thread:
        query_pulseaudio = getattr(self, "query_pulseaudio_properties", noop)
        if bool(self.audio_properties) and query_pulseaudio != noop:
            GLib.idle_add(query_pulseaudio)
        GLib.idle_add(self.log_audio_properties)

    def log_audio_properties(self) -> None:
        from xpra.util.str_fn import csv
        log("init_audio_options:")
        log(" speaker: supported=%s, encoders=%s",self.supports_speaker, csv(self.speaker_codecs))
        log(" microphone: supported=%s, decoders=%s", self.supports_microphone, csv(self.microphone_codecs))
        log(" audio properties=%s", self.audio_properties)

    def _process_sound_control(self, proto, packet: Packet) -> None:
        self._process_audio_control(proto, packet)

    def _process_audio_control(self, proto, packet: Packet) -> None:
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

    def _process_sound_data(self, proto, packet: Packet) -> None:
        self._process_audio_data(proto, packet)

    def _process_audio_data(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if ss:
            ss.audio_data(*packet[1:])

    def init_packet_handlers(self) -> None:
        if self.supports_speaker or self.supports_microphone:
            self.add_packets(f"{AudioServer.PREFIX}-control", main_thread=True)
            self.add_packets(f"{AudioServer.PREFIX}-data")
            self.add_legacy_alias("sound-control", f"{AudioServer.PREFIX}-control")
            self.add_legacy_alias("sound-data", f"{AudioServer.PREFIX}-data")
