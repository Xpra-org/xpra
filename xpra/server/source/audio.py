# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from subprocess import Popen
from shutil import which
from typing import Any
from collections.abc import Sequence

from xpra.net.compression import Compressed
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.common import FULL_INFO, NotificationID, SizedBuffer
from xpra.os_util import get_machine_id, get_user_uuid, gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, bytestostr
from xpra.util.env import envint, envbool, first_time
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio")

NEW_STREAM_SOUND = envbool("XPRA_NEW_STREAM_SOUND", True)
NEW_STREAM_SOUND_STOP = envint("XPRA_NEW_STREAM_SOUND_STOP", 20)


class FakeSink:
    def __init__(self, codec: str):
        self.codec = codec

    @staticmethod
    def add_data(*args) -> None:
        log("FakeSink.add_data%s ignored", args)

    @staticmethod
    def cleanup(*args) -> None:
        log("FakeSink.cleanup%s ignored", args)


def stop_proc(proc) -> None:
    r = proc.poll()
    log("stop_proc(%s) exit code=%s", proc, r)
    if r is not None:
        # already ended
        return
    try:
        proc.terminate()
    except OSError:
        log("failed to stop subprocess %s", proc)


class AudioMixin(StubSourceMixin):

    PREFIX = "audio"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        audio = caps.get(AudioMixin.PREFIX)
        if isinstance(audio, dict):
            audio = typedict(audio)
            return audio.boolget("send") or audio.boolget("receive")
        return False

    def __init__(self):
        self.audio_properties: typedict = typedict()
        self.audio_source_plugin = ""
        self.supports_speaker = False
        self.speaker_codecs = []
        self.supports_microphone = False
        self.microphone_codecs = []
        self.restart_speaker_args = ()
        self.audio_suspended = False

    def init_from(self, _protocol, server) -> None:
        self.audio_properties = typedict(server.audio_properties)
        self.audio_source_plugin = server.audio_source_plugin
        self.supports_speaker = server.supports_speaker
        self.supports_microphone = server.supports_microphone
        self.speaker_codecs = server.speaker_codecs
        self.microphone_codecs = server.microphone_codecs

    def init_state(self) -> None:
        self.wants_audio = True
        self.audio_source_sequence = 0
        self.audio_source: Any = None
        self.audio_sink: Any = None
        self.pulseaudio_id = ""
        self.pulseaudio_cookie_hash = ""
        self.pulseaudio_server = ""
        self.audio_decoders: Sequence[str] = ()
        self.audio_encoders: Sequence[str] = ()
        self.audio_receive = False
        self.audio_send = False
        self.audio_fade_timer = 0
        self.new_stream_timers: dict[Popen, int] = {}

    def cleanup(self) -> None:
        log("%s.cleanup()", self)
        self.cancel_audio_fade_timer()
        self.stop_sending_audio()
        self.stop_receiving_audio()
        self.stop_new_stream_notifications()
        self.init_state()

    def stop_new_stream_notifications(self) -> None:
        timers = self.new_stream_timers.copy()
        self.new_stream_timers = {}
        for proc, timer in timers.items():
            timer = self.new_stream_timers.pop(proc, 0)
            if timer:
                GLib.source_remove(timer)
            stop_proc(proc)

    def parse_client_caps(self, c: typedict) -> None:
        audio = typedict(c.dictget(AudioMixin.PREFIX) or {})
        self.wants_audio = "audio" in c.strtupleget("wants") or audio.boolget("send") or audio.boolget("receive")
        if audio:
            self.pulseaudio_id = audio.strget("pulseaudio.id")
            self.pulseaudio_cookie_hash = audio.strget("pulseaudio.cookie-hash")
            self.pulseaudio_server = audio.strget("pulseaudio.server")
            self.audio_decoders = audio.strtupleget("decoders", ())
            self.audio_encoders = audio.strtupleget("encoders", ())
            self.audio_receive = audio.boolget("receive")
            self.audio_send = audio.boolget("send")
        log("pulseaudio id=%s, cookie-hash=%s, server=%s, audio decoders=%s, audio encoders=%s, receive=%s, send=%s",
            self.pulseaudio_id, self.pulseaudio_cookie_hash, self.pulseaudio_server,
            self.audio_decoders, self.audio_encoders, self.audio_receive, self.audio_send)

    def get_caps(self) -> dict[str, Any]:
        if not self.wants_audio or not self.audio_properties:
            return {}
        audio_props = dict(self.audio_properties)
        if FULL_INFO < 2:
            # only expose these specific keys:
            audio_props = {k: v for k, v in audio_props.items() if k in (
                "muxers", "demuxers",
            )}
        audio_props.update({
            "codec-full-names": True,
            "encoders": self.speaker_codecs,
            "decoders": self.microphone_codecs,
            "send": self.supports_speaker and len(self.speaker_codecs) > 0,
            "receive": self.supports_microphone and len(self.microphone_codecs) > 0,
        })
        return {"audio": audio_props}

    def audio_loop_check(self, mode: str = "speaker") -> bool:
        log("audio_loop_check(%s)", mode)
        # pylint: disable=import-outside-toplevel
        from xpra.audio.gstreamer_util import ALLOW_SOUND_LOOP, loop_warning_messages
        if ALLOW_SOUND_LOOP:
            return True
        machine_id = get_machine_id()
        uuid = get_user_uuid()
        # these attributes belong in a different mixin,
        # so we can't assume that they exist:
        client_machine_id = getattr(self, "machine_id", None)
        client_uuid = getattr(self, "uuid", None)
        log("audio_loop_check(%s) machine_id=%s client machine_id=%s, uuid=%s, client uuid=%s",
            mode, machine_id, client_machine_id, uuid, client_uuid)
        if client_machine_id:
            if client_machine_id != machine_id:
                # not the same machine, so OK
                return True
            if client_uuid != uuid:
                # different user, assume different pulseaudio server
                return True
        # check pulseaudio id if we have it
        padict = typedict(self.audio_properties.get("pulseaudio", {}))
        pulseaudio_id = padict.strget("id")
        pulseaudio_cookie_hash = padict.strget("cookie-hash")
        log("audio_loop_check(%s) pulseaudio id=%s, client pulseaudio id=%s",
            mode, pulseaudio_id, self.pulseaudio_id)
        log("audio_loop_check(%s) pulseaudio cookie hash=%s, client pulseaudio cookie hash=%s",
            mode, pulseaudio_cookie_hash, self.pulseaudio_cookie_hash)
        if pulseaudio_id and self.pulseaudio_id:
            if self.pulseaudio_id != pulseaudio_id:
                return True
        elif pulseaudio_cookie_hash and self.pulseaudio_cookie_hash:
            if self.pulseaudio_cookie_hash != pulseaudio_cookie_hash:
                return True
        else:
            # no cookie or id, so probably not a pulseaudio setup,
            # hope for the best:
            return True
        msgs = loop_warning_messages(mode)
        summary = msgs[0]
        body = "\n".join(msgs[1:])
        self.may_notify(NotificationID.AUDIO, summary, body, icon_name=mode)
        log.warn("Warning: %s", summary)
        for x in msgs[1:]:
            log.warn(" %s", x)
        return False

    def start_sending_audio(self, codec: str = "", volume: float = 1.0):
        log("start_sending_audio(%s)", codec)
        ss = None
        if getattr(self, "suspended", False):
            log.warn("Warning: not starting audio whilst in suspended state")
            return None
        if not self.supports_speaker:
            log.error("Error sending audio: support not enabled on the server")
            return None
        if self.audio_source:
            log.error("Error sending audio: forwarding already in progress")
            return None
        if not self.audio_receive:
            log.error("Error sending audio: support is not enabled on the client")
            return None
        if not codec:
            codecs = [x for x in self.audio_decoders if x in self.speaker_codecs]
            if not codecs:
                log.error("Error sending audio: no codecs in common")
                return None
            codec = codecs[0]
        elif codec not in self.speaker_codecs:
            log.warn("Warning: invalid codec specified: %s", codec)
            return None
        elif codec not in self.audio_decoders:
            log.warn("Error sending audio: invalid codec '%s'", codec)
            log.warn(" is not in the list of decoders supported by the client: %s", csv(self.audio_decoders))
            return None
        if not self.audio_loop_check("speaker"):
            return None
        try:
            from xpra.audio.wrapper import start_sending_audio  # pylint: disable=import-outside-toplevel
            plugins = self.audio_properties.strtupleget("sources")
            ss = start_sending_audio(plugins, self.audio_source_plugin,
                                     "", codec, volume, True, [codec],
                                     self.pulseaudio_server, self.pulseaudio_id)
            self.audio_source = ss
            log("start_sending_audio() audio source=%s", ss)
            if not ss:
                return None
            ss.sequence = self.audio_source_sequence
            ss.connect("new-buffer", self.new_audio_buffer)
            ss.connect("new-stream", self.new_stream)
            ss.connect("info", self.audio_source_info)
            ss.connect("exit", self.audio_source_exit)
            ss.connect("error", self.audio_source_error)
            ss.start()
            self.restart_speaker_args = (codec, volume)
            return ss
        except Exception as e:
            log.error("Error setting up audio: %s", e, exc_info=True)
            self.stop_sending_audio()
            ss = None
            return None
        finally:
            if ss is None:
                # tell the client we're not sending anything:
                self.send_eos(codec)

    def audio_source_error(self, source, message: str) -> None:
        # this should be printed to stderr by the audio process already
        if source == self.audio_source:
            log("audio capture error: %s", message)

    def audio_source_exit(self, source, *args) -> None:
        log("audio_source_exit(%s, %s)", source, args)
        if source == self.audio_source:
            self.stop_sending_audio()

    @staticmethod
    def audio_source_info(source, info: dict) -> None:
        log("audio_source_info(%s, %s)", source, info)

    def stop_sending_audio(self) -> None:
        ss = self.audio_source
        log("stop_sending_audio() audio_source=%s", ss)
        if ss:
            self.audio_source = None
            self.send_eos(ss.codec, ss.sequence)
            self.audio_source_sequence += 1
            ss.cleanup()
        self.call_update_av_sync_delay()

    def send_eos(self, codec: str, sequence: int = 0) -> None:
        log("send_eos(%s, %s)", codec, sequence)
        # tell the client this is the end:
        self.send_more("sound-data", codec, b"",
                       {
                           "end-of-stream": True,
                           "sequence": sequence,
                       })

    def new_stream_sound(self) -> None:
        if not NEW_STREAM_SOUND:
            return
        from xpra.platform.paths import get_resources_dir  # pylint: disable=import-outside-toplevel
        sample = os.path.abspath(os.path.normpath(os.path.join(get_resources_dir(), "bell.wav")))
        log(f"new_stream_sound() sample={sample}, exists={os.path.exists(sample)}")
        if not os.path.exists(sample):
            return
        gst_launch = os.path.abspath(os.path.normpath(which("gst-launch-1.0") or "gst-launch-1.0"))
        cmd = [
            gst_launch, "-q",
            "filesrc", f"location={sample}",
            "!", "decodebin",
            "!", "audioconvert",
            "!", "autoaudiosink",
        ]
        cmd_str = " ".join(cmd)
        try:
            proc = Popen(cmd)  # pylint: disable=consider-using-with
            log(f"Popen({cmd_str})={proc}")
            from xpra.util.child_reaper import getChildReaper  # pylint: disable=import-outside-toplevel
            getChildReaper().add_process(proc, "new-stream-sound", cmd, ignore=True, forget=True)

            def stop_new_stream_notification() -> None:
                if self.new_stream_timers.pop(proc, None):
                    stop_proc(proc)

            timer = GLib.timeout_add(NEW_STREAM_SOUND_STOP * 1000, stop_new_stream_notification)
            self.new_stream_timers[proc] = timer
        except Exception as e:
            log("new_stream_sound() error playing new stream sound", exc_info=True)
            log.error("Error playing new-stream sound")
            log.error(f" using: {cmd_str}:")
            log.estr(e)

    def new_stream(self, audio_source, codec: str) -> bool:
        log("new_stream(%s, %s)", audio_source, codec)
        self.new_stream_sound()
        if self.audio_source != audio_source:
            log("dropping new-stream signal (current source=%s, signal source=%s)", self.audio_source, audio_source)
            return False
        codec = codec or audio_source.codec
        audio_source.codec = codec
        # tell the client this is the start:
        self.send("sound-data", codec, b"", {
            "start-of-stream": True,
            "codec": codec,
            "sequence": audio_source.sequence,
        })
        self.call_update_av_sync_delay()
        # run it again after 10 seconds,
        # by that point the source info will actually be populated:
        GLib.timeout_add(10 * 1000, self.call_update_av_sync_delay)
        return False

    def call_update_av_sync_delay(self) -> None:
        # loose coupling with avsync mixin:
        update_av_sync = getattr(self, "update_av_sync_delay_total", None)
        log("call_update_av_sync_delay update_av_sync=%s", update_av_sync)
        if callable(update_av_sync):
            update_av_sync()  # pylint: disable=not-callable

    def new_audio_buffer(self, audio_source, data: bytes,
                         metadata: dict, packet_metadata: Sequence[SizedBuffer]) -> None:
        log("new_audio_buffer(%s, %s, %s, %s) info=%s",
            audio_source, len(data or []), metadata, [len(x) for x in packet_metadata], audio_source.info)
        if self.audio_source != audio_source or self.is_closed():
            log("audio buffer dropped: from old source or closed")
            return
        if audio_source.sequence < self.audio_source_sequence:
            log("audio buffer dropped: old sequence number: %s (current is %s)",
                audio_source.sequence, self.audio_source_sequence)
            return
        self.send_audio_data(audio_source, data, metadata, packet_metadata)

    def send_audio_data(self, audio_source, data: bytes, metadata: dict,
                        packet_metadata: Sequence[SizedBuffer]) -> None:
        # tag the packet metadata as already compressed:
        pmetadata = Compressed("packet metadata", packet_metadata)
        packet_data = [audio_source.codec, Compressed(audio_source.codec, data), metadata, pmetadata]
        sequence = audio_source.sequence
        if sequence >= 0:
            metadata["sequence"] = sequence
        self.send("sound-data", *packet_data, synchronous=False, will_have_more=True)

    def stop_receiving_audio(self) -> None:
        ss = self.audio_sink
        log("stop_receiving_audio() audio_sink=%s", ss)
        if ss:
            self.audio_sink = None
            ss.cleanup()

    ##########################################################################
    # audio control commands:
    def audio_control(self, action: str, *args):
        fn = "audio_control_" + action.replace("-", "_")
        method = getattr(self, fn, None)
        log(f"audio_control({action}, {args}) {self}.{fn}={method}")
        if not method:
            msg = f"unknown audio action {action!r}"
            if first_time(f"unknown-{method}"):
                log.error("Error: %s", msg)
            return msg
        return method(*args)  # pylint: disable=not-callable

    def audio_control_stop(self, sequence_str="") -> str:
        if sequence_str:
            try:
                sequence = int(sequence_str)
            except ValueError:
                msg = f"audio sequence number {sequence_str!r} is invalid"
                log.warn(msg)
                return msg
            if sequence != self.audio_source_sequence:
                log.warn("Warning: audio sequence mismatch: %i vs %i",
                         sequence, self.audio_source_sequence)
                return "not stopped"
            log("stop: sequence number matches")
        self.stop_sending_audio()
        return "stopped"

    def audio_control_fadein(self, codec: str = "", delay_str="") -> str:
        self.do_audio_control_start(0.0, codec)
        delay = 1000
        if delay_str:
            delay = max(1, min(10 * 1000, int(delay_str)))
        step = 1.0 / (delay / 100.0)
        log("audio_control fadein delay=%s, step=%1.f", delay, step)

        def fadein() -> bool:
            ss = self.audio_source
            if not ss:
                return False
            volume = ss.get_volume()
            log("fadein() volume=%.1f", volume)
            if volume < 1.0:
                volume = min(1.0, volume + step)
                ss.set_volume(volume)
            return volume < 1.0

        self.cancel_audio_fade_timer()
        self.audio_fade_timer = GLib.timeout_add(100, fadein)
        return "fadein started"

    def audio_control_start(self, codec: str = "") -> str:
        self.do_audio_control_start(1.0, codec)
        return f"requested {codec} audio"

    def do_audio_control_start(self, volume: float, codec: str) -> str:
        codec = bytestostr(codec)
        log("do_audio_control_start(%s, %s)", volume, codec)
        if not self.start_sending_audio(codec, volume):
            return "failed to start audio"
        msg = "audio started"
        if codec:
            msg += f" using codec {codec}"
        return msg

    def audio_control_fadeout(self, delay_str="") -> str:
        assert self.audio_source, "no active audio capture"
        delay = 1000
        if delay_str:
            delay = max(1, min(10 * 1000, int(delay_str)))
        step = 1.0 / (delay / 100.0)
        log("audio_control fadeout delay=%s, step=%1.f", delay, step)

        def fadeout() -> bool:
            ss = self.audio_source
            if not ss:
                return False
            volume = ss.get_volume()
            log("fadeout() volume=%.1f", volume)
            if volume > 0:
                ss.set_volume(max(0, volume - step))
                return True
            self.stop_sending_audio()
            return False

        self.cancel_audio_fade_timer()
        self.audio_fade_timer = GLib.timeout_add(100, fadeout)
        return "fadeout started"

    def audio_control_new_sequence(self, seq_str) -> str:
        self.audio_source_sequence = int(seq_str)
        return f"new sequence is {self.audio_source_sequence}"

    def cancel_audio_fade_timer(self) -> None:
        sft = self.audio_fade_timer
        if sft:
            self.audio_fade_timer = 0
            GLib.source_remove(sft)

    def audio_data(self, codec: str, data: bytes, metadata: dict, packet_metadata: Sequence[SizedBuffer] = ()) -> None:
        log("audio_data(%s, %s, %s, %s) audio sink=%s",
            codec, len(data or []), metadata, packet_metadata, self.audio_sink)
        if self.is_closed():
            return
        if self.audio_sink is not None and codec != self.audio_sink.codec:
            log.info("audio codec changed from %s to %s", self.audio_sink.codec, codec)
            self.audio_sink.cleanup()
            self.audio_sink = None
        if metadata.get("end-of-stream"):
            log("client sent end-of-stream, closing audio pipeline")
            self.stop_receiving_audio()
            return
        if not self.audio_sink:
            if not self.audio_loop_check("microphone"):
                # make a fake object,
                # so we don't fire the audio loop check warning repeatedly
                self.audio_sink = FakeSink(codec)
                return
            try:
                def audio_sink_error(*args) -> None:
                    log("audio_sink_error%s", args)
                    log.warn("Warning: stopping audio input because of an error")
                    self.stop_receiving_audio()

                from xpra.audio.wrapper import start_receiving_audio  # pylint: disable=import-outside-toplevel
                ss = start_receiving_audio(codec)
                if not ss:
                    return
                self.audio_sink = ss
                log("audio_data(..) created audio sink: %s", self.audio_sink)
                ss.connect("error", audio_sink_error)
                ss.start()
                log("audio_data(..) audio sink started")
            except Exception:
                log.error("Error: failed to start receiving %r", codec, exc_info=True)
                return
        self.audio_sink.add_data(data, metadata, packet_metadata)

    def get_audio_source_latency(self) -> int:
        encoder_latency = 0
        ss = self.audio_source
        cinfo = ""
        if ss:
            info = typedict(ss.info or {})
            try:
                qdict = info.dictget("queue")
                if qdict:
                    q = typedict(qdict).intget("cur", 0)
                    log("server side queue level: %s", q)
                # get the latency from the source info, if it has it:
                encoder_latency = info.intget("latency", -1)
                if encoder_latency < 0:
                    # fallback to hard-coded values:
                    # pylint: disable=import-outside-toplevel
                    from xpra.audio.gstreamer_util import ENCODER_LATENCY, RECORD_PIPELINE_LATENCY
                    encoder_latency = RECORD_PIPELINE_LATENCY + ENCODER_LATENCY.get(ss.codec, 0)
                    cinfo = f"{ss.codec} "
                # processing overhead
                encoder_latency += 100
            except Exception as e:
                encoder_latency = 0
                log("failed to get encoder latency for %s: %s", ss.codec, e)
        log("get_audio_source_latency() %s: %s", cinfo, encoder_latency)
        return encoder_latency

    def get_info(self) -> dict[str, Any]:
        return {"audio": self.get_audio_info()}

    def get_audio_info(self) -> dict[str, Any]:
        def audio_info(supported, subprocess_wrapper, codecs) -> dict[str, Any]:
            i = {"codecs": codecs}
            if not supported:
                i["state"] = "disabled"
                return i
            if subprocess_wrapper is None:
                i["state"] = "inactive"
                return i
            i.update(subprocess_wrapper.get_info())
            return i

        info = {
            "speaker": audio_info(self.supports_speaker, self.audio_source, self.audio_decoders),
            "microphone": audio_info(self.supports_microphone, self.audio_sink, self.audio_encoders),
        }
        for prop in ("pulseaudio_id", "pulseaudio_server"):
            v = getattr(self, prop)
            if v is not None:
                info[prop] = v
        return info

    def suspend(self) -> None:
        if self.audio_source:
            self.audio_suspended = True
            self.stop_sending_audio()

    def resume(self) -> None:
        suspended = self.audio_suspended
        rsa = self.restart_speaker_args
        if rsa and suspended:
            self.audio_suspended = False
            self.start_sending_audio(*rsa)
