# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("sound")

from xpra.net.compression import Compressed
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.os_util import get_machine_id, get_user_uuid, bytestostr, POSIX
from xpra.util import csv, envbool, flatten_dict, XPRA_AUDIO_NOTIFICATION_ID

NEW_STREAM_SOUND = envbool("XPRA_NEW_STREAM_SOUND", True)


class AudioMixin(StubSourceMixin):

    def __init__(self):
        self.sound_properties = {}
        self.sound_source_plugin = ""
        self.supports_speaker = False
        self.speaker_codecs = []
        self.supports_microphone = False
        self.microphone_codecs = []

    def init_from(self, _protocol, server):
        self.sound_properties       = server.sound_properties
        self.sound_source_plugin    = server.sound_source_plugin
        self.supports_speaker       = server.supports_speaker
        self.supports_microphone    = server.supports_microphone
        self.speaker_codecs         = server.speaker_codecs
        self.microphone_codecs      = server.microphone_codecs

    def init_state(self):
        self.wants_sound = True
        self.sound_source_sequence = 0
        self.sound_source = None
        self.sound_sink = None
        self.pulseaudio_id = None
        self.pulseaudio_cookie_hash = None
        self.pulseaudio_server = None
        self.sound_decoders = ()
        self.sound_encoders = ()
        self.sound_receive = False
        self.sound_send = False
        self.sound_bundle_metadata = False
        self.sound_fade_timer = None

    def cleanup(self):
        log("%s.cleanup()", self)
        self.cancel_sound_fade_timer()
        self.stop_sending_sound()
        self.stop_receiving_sound()
        self.init_state()


    def parse_client_caps(self, c):
        self.wants_sound = c.boolget("wants_sound", True)
        self.pulseaudio_id = c.strget("sound.pulseaudio.id")
        self.pulseaudio_cookie_hash = c.strget("sound.pulseaudio.cookie-hash")
        self.pulseaudio_server = c.strget("sound.pulseaudio.server")
        self.sound_decoders = c.strlistget("sound.decoders", [])
        self.sound_encoders = c.strlistget("sound.encoders", [])
        self.sound_receive = c.boolget("sound.receive")
        self.sound_send = c.boolget("sound.send")
        self.sound_bundle_metadata = c.boolget("sound.bundle-metadata")
        log("pulseaudio id=%s, cookie-hash=%s, server=%s, sound decoders=%s, sound encoders=%s, receive=%s, send=%s",
                 self.pulseaudio_id, self.pulseaudio_cookie_hash, self.pulseaudio_server, self.sound_decoders, self.sound_encoders, self.sound_receive, self.sound_send)

    def get_caps(self):
        if not self.wants_sound or not self.sound_properties:
            return {}
        sound_props = self.sound_properties.copy()
        sound_props.update({
            "codec-full-names"  : True,
            "encoders"          : self.speaker_codecs,
            "decoders"          : self.microphone_codecs,
            "send"              : self.supports_speaker and len(self.speaker_codecs)>0,
            "receive"           : self.supports_microphone and len(self.microphone_codecs)>0,
            })
        return flatten_dict({"sound" : sound_props})
        

    def audio_loop_check(self, mode="speaker"):
        log("audio_loop_check(%s)", mode)
        from xpra.sound.gstreamer_util import ALLOW_SOUND_LOOP, loop_warning_messages
        if ALLOW_SOUND_LOOP:
            return True
        machine_id = get_machine_id()
        uuid = get_user_uuid()
        log("audio_loop_check(%s) machine_id=%s client machine_id=%s, uuid=%s, client uuid=%s", mode, machine_id, self.machine_id, uuid, self.uuid)
        if self.machine_id:
            if self.machine_id!=machine_id:
                #not the same machine, so OK
                return True
            if self.uuid!=uuid:
                #different user, assume different pulseaudio server
                return True
        #check pulseaudio id if we have it
        pulseaudio_id = self.sound_properties.get("pulseaudio", {}).get("id")
        pulseaudio_cookie_hash = self.sound_properties.get("pulseaudio", {}).get("cookie-hash")
        log("audio_loop_check(%s) pulseaudio id=%s, client pulseaudio id=%s, pulseaudio cookie hash=%s, client pulseaudio cookie hash=%s",
                 mode, pulseaudio_id, self.pulseaudio_id, pulseaudio_cookie_hash, self.pulseaudio_cookie_hash)
        if pulseaudio_id and self.pulseaudio_id:
            if self.pulseaudio_id!=pulseaudio_id:
                return True
        elif pulseaudio_cookie_hash and self.pulseaudio_cookie_hash:
            if self.pulseaudio_cookie_hash!=pulseaudio_cookie_hash:
                return True
        else:
            #no cookie or id, so probably not a pulseaudio setup,
            #hope for the best:
            return True
        msgs = loop_warning_messages(mode)
        summary = msgs[0]
        body = "\n".join(msgs[1:])
        nid = XPRA_AUDIO_NOTIFICATION_ID
        self.may_notify(nid, summary, body, icon_name=mode)
        log.warn("Warning: %s", summary)
        for x in msgs[1:]:
            log.warn(" %s", x)
        return False

    def start_sending_sound(self, codec=None, volume=1.0, new_stream=None, new_buffer=None, skip_client_codec_check=False):
        assert self.hello_sent
        log("start_sending_sound(%s)", codec)
        ss = None
        try:
            if self.suspended:
                log.warn("Warning: not starting sound whilst in suspended state")
                return None
            if not self.supports_speaker:
                log.error("Error sending sound: support not enabled on the server")
                return None
            if self.sound_source:
                log.error("Error sending sound: forwarding already in progress")
                return None
            if not self.sound_receive:
                log.error("Error sending sound: support is not enabled on the client")
                return None
            if codec is None:
                codecs = [x for x in self.sound_decoders if x in self.speaker_codecs]
                if not codecs:
                    log.error("Error sending sound: no codecs in common")
                    return None
                codec = codecs[0]
            elif codec not in self.speaker_codecs:
                log.warn("Warning: invalid codec specified: %s", codec)
                return None
            elif (codec not in self.sound_decoders) and not skip_client_codec_check:
                log.warn("Error sending sound: invalid codec '%s'", codec)
                log.warn(" is not in the list of decoders supported by the client: %s", csv(self.sound_decoders))
                return None
            if not self.audio_loop_check("speaker"):
                return None
            from xpra.sound.wrapper import start_sending_sound
            plugins = self.sound_properties.strlistget("plugins", [])
            ss = start_sending_sound(plugins, self.sound_source_plugin, None, codec, volume, True, [codec], self.pulseaudio_server, self.pulseaudio_id)
            self.sound_source = ss
            log("start_sending_sound() sound source=%s", ss)
            if not ss:
                return None
            ss.sequence = self.sound_source_sequence
            ss.connect("new-buffer", new_buffer or self.new_sound_buffer)
            ss.connect("new-stream", new_stream or self.new_stream)
            ss.connect("info", self.sound_source_info)
            ss.connect("exit", self.sound_source_exit)
            ss.connect("error", self.sound_source_error)
            ss.start()
            return ss
        except Exception as e:
            log.error("error setting up sound: %s", e, exc_info=True)
            self.stop_sending_sound()
            ss = None
            return None
        finally:
            if ss is None:
                #tell the client we're not sending anything:
                self.send_eos(codec)

    def sound_source_error(self, source, message):
        #this should be printed to stderr by the sound process already
        if source==self.sound_source:
            log("sound source error: %s", message)

    def sound_source_exit(self, source, *args):
        log("sound_source_exit(%s, %s)", source, args)
        if source==self.sound_source:
            self.stop_sending_sound()

    def sound_source_info(self, source, info):
        log("sound_source_info(%s, %s)", source, info)

    def stop_sending_sound(self):
        ss = self.sound_source
        log("stop_sending_sound() sound_source=%s", ss)
        if ss:
            self.sound_source = None
            self.send_eos(ss.codec, ss.sequence)
            ss.cleanup()

    def send_eos(self, codec, sequence=0):
        #tell the client this is the end:
        self.send_more("sound-data", codec, "", 
                       {
                           "end-of-stream" : True,
                           "sequence"      : sequence,
                        })


    def new_stream(self, sound_source, codec):
        if NEW_STREAM_SOUND:
            try:
                from xpra.platform.paths import get_resources_dir
                sample = os.path.join(get_resources_dir(), "bell.wav")
                log("new_stream(%s, %s) sample=%s, exists=%s", sound_source, codec, sample, os.path.exists(sample))
                if os.path.exists(sample):
                    if POSIX:
                        sink = "alsasink"
                    else:
                        sink = "autoaudiosink"
                    cmd = ["gst-launch-1.0", "-q", "filesrc", "location=%s" % sample, "!", "decodebin", "!", "audioconvert", "!", sink]
                    import subprocess
                    proc = subprocess.Popen(cmd, close_fds=True)
                    log("Popen(%s)=%s", cmd, proc)
                    from xpra.child_reaper import getChildReaper
                    getChildReaper().add_process(proc, "new-stream-sound", cmd, ignore=True, forget=True)
            except:
                pass
        log("new_stream(%s, %s)", sound_source, codec)
        if self.sound_source!=sound_source:
            log("dropping new-stream signal (current source=%s, signal source=%s)", self.sound_source, sound_source)
            return
        codec = codec or sound_source.codec
        sound_source.codec = codec
        #tell the client this is the start:
        self.send("sound-data", codec, "",
                  {
                   "start-of-stream"    : True,
                   "codec"              : codec,
                   "sequence"           : sound_source.sequence,
                   })
        self.update_av_sync_delay_total()

    def new_sound_buffer(self, sound_source, data, metadata, packet_metadata=[]):
        log("new_sound_buffer(%s, %s, %s, %s) info=%s, suspended=%s",
                 sound_source, len(data or []), metadata, [len(x) for x in packet_metadata], sound_source.info, self.suspended)
        if self.sound_source!=sound_source or self.is_closed():
            log("sound buffer dropped: from old source or closed")
            return
        if sound_source.sequence<self.sound_source_sequence:
            log("sound buffer dropped: old sequence number: %s (current is %s)", sound_source.sequence, self.sound_source_sequence)
            return
        if packet_metadata:
            if not self.sound_bundle_metadata:
                #client does not support bundling, send packet metadata as individual packets before the main packet:
                for x in packet_metadata:
                    self.send_sound_data(sound_source, x)
                packet_metadata = ()
            else:
                #the packet metadata is compressed already:
                packet_metadata = Compressed("packet metadata", packet_metadata, can_inline=True)
        #don't drop the first 10 buffers
        can_drop_packet = (sound_source.info or {}).get("buffer_count", 0)>10
        self.send_sound_data(sound_source, data, metadata, packet_metadata, can_drop_packet)

    def send_sound_data(self, sound_source, data, metadata={}, packet_metadata=(), can_drop_packet=False):
        packet_data = [sound_source.codec, Compressed(sound_source.codec, data), metadata]
        if packet_metadata:
            assert self.sound_bundle_metadata
            packet_data.append(packet_metadata)
        sequence = sound_source.sequence
        if sequence>=0:
            metadata["sequence"] = sequence
        fail_cb = None
        if can_drop_packet:
            def sound_data_fail_cb():
                #ideally we would tell gstreamer to send an audio "key frame"
                #or synchronization point to ensure the stream recovers
                log("a sound data buffer was not received and will not be resent")
            fail_cb = sound_data_fail_cb
        self.send("sound-data", *packet_data, synchronous=False, fail_cb=fail_cb, will_have_more=True)

    def stop_receiving_sound(self):
        ss = self.sound_sink
        log("stop_receiving_sound() sound_sink=%s", ss)
        if ss:
            self.sound_sink = None
            ss.cleanup()

    def sound_control(self, action, *args):
        assert self.hello_sent
        action = bytestostr(action)
        log("sound_control(%s, %s)", action, args)
        if action=="stop":
            if len(args)>0:
                try:
                    sequence = int(args[0])
                except ValueError:
                    msg = "sound sequence number '%s' is invalid" % args[0]
                    log.warn(msg)
                    return msg
                if sequence!=self.sound_source_sequence:
                    log.warn("sound sequence mismatch: %i vs %i", sequence, self.sound_source_sequence)
                    return "not stopped"
                log("stop: sequence number matches")
            self.stop_sending_sound()
            return "stopped"
        elif action in ("start", "fadein"):
            codec = None
            if len(args)>0:
                codec = bytestostr(args[0])
            if action=="start":
                volume = 1.0
            else:
                volume = 0.0
            if not self.start_sending_sound(codec, volume):
                return "failed to start sound"
            if action=="fadein":
                delay = 1000
                if len(args)>1:
                    delay = max(1, min(10*1000, int(args[1])))
                step = 1.0/(delay/100.0)
                log("sound_control fadein delay=%s, step=%1.f", delay, step)
                def fadein():
                    ss = self.sound_source
                    if not ss:
                        return False
                    volume = ss.get_volume()
                    log("fadein() volume=%.1f", volume)
                    if volume<1.0:
                        volume = min(1.0, volume+step)
                        ss.set_volume(volume)
                    return volume<1.0
                self.cancel_sound_fade_timer()
                self.sound_fade_timer = self.timeout_add(100, fadein)
            msg = "sound started"
            if codec:
                msg += " using codec %s" % codec
            return msg
        elif action=="fadeout":
            assert self.sound_source, "no active sound source"
            delay = 1000
            if len(args)>0:
                delay = max(1, min(10*1000, int(args[0])))
            step = 1.0/(delay/100.0)
            log("sound_control fadeout delay=%s, step=%1.f", delay, step)
            def fadeout():
                ss = self.sound_source
                if not ss:
                    return False
                volume = ss.get_volume()
                log("fadeout() volume=%.1f", volume)
                if volume>0:
                    ss.set_volume(max(0, volume-step))
                    return True
                self.stop_sending_sound()
                return False
            self.cancel_sound_fade_timer()
            self.sound_fade_timer = self.timeout_add(100, fadeout)
        elif action=="new-sequence":
            self.sound_source_sequence = int(args[0])
            return "new sequence is %s" % self.sound_source_sequence
        elif action=="sync":
            assert self.av_sync, "av-sync is not enabled"
            self.set_av_sync_delay(int(args[0]))
            return "av-sync delay set to %ims" % self.av_sync_delay
        elif action=="av-sync-delta":
            assert self.av_sync, "av-sync is not enabled"
            self.set_av_sync_delta(int(args[0]))
            return "av-sync delta set to %ims" % self.av_sync_delta
        #elif action=="quality":
        #    assert self.sound_source
        #    quality = args[0]
        #    self.sound_source.set_quality(quality)
        #    self.start_sending_sound()
        else:
            msg = "unknown sound action: %s" % action
            log.error(msg)
            return msg

    def cancel_sound_fade_timer(self):
        sft = self.sound_fade_timer
        if sft:
            self.sound_fade_timer = None
            self.source_remove(sft)

    def sound_data(self, codec, data, metadata, packet_metadata=()):
        log("sound_data(%s, %s, %s, %s) sound sink=%s", codec, len(data or []), metadata, packet_metadata, self.sound_sink)
        if self.is_closed():
            return
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.info("sound codec changed from %s to %s", self.sound_sink.codec, codec)
            self.sound_sink.cleanup()
            self.sound_sink = None
        if metadata.get("end-of-stream"):
            log("client sent end-of-stream, closing sound pipeline")
            self.stop_receiving_sound()
            return
        if not self.sound_sink:
            if not self.audio_loop_check("microphone"):
                #make a fake object so we don't fire the audio loop check warning repeatedly
                from xpra.util import AdHocStruct
                self.sound_sink = AdHocStruct()
                self.sound_sink.codec = codec
                def noop(*args):
                    pass
                self.sound_sink.add_data = noop
                self.sound_sink.cleanup = noop
                return
            try:
                def sound_sink_error(*args):
                    log("sound_sink_error%s", args)
                    log.warn("stopping sound input because of error")
                    self.stop_receiving_sound()
                from xpra.sound.wrapper import start_receiving_sound
                ss = start_receiving_sound(codec)
                if not ss:
                    return
                self.sound_sink = ss
                log("sound_data(..) created sound sink: %s", self.sound_sink)
                ss.connect("error", sound_sink_error)
                ss.start()
                log("sound_data(..) sound sink started")
            except Exception:
                log.error("failed to setup sound", exc_info=True)
                return
        if packet_metadata:
            if not self.sound_properties.boolget("bundle-metadata"):
                for x in packet_metadata:
                    self.sound_sink.add_data(x)
                packet_metadata = ()
        self.sound_sink.add_data(data, metadata, packet_metadata)


    def get_sound_source_latency(self):
        encoder_latency = 0
        ss = self.sound_source
        cinfo = ""
        if ss:
            try:
                encoder_latency = ss.info.get("queue", {}).get("cur", 0)
                log("server side queue level: %s", encoder_latency)
                #get the latency from the source info, if it has it:
                encoder_latency = ss.info.get("latency", -1)
                if encoder_latency<0:
                    #fallback to hard-coded values:
                    from xpra.sound.gstreamer_util import ENCODER_LATENCY, RECORD_PIPELINE_LATENCY
                    encoder_latency = RECORD_PIPELINE_LATENCY + ENCODER_LATENCY.get(ss.codec, 0)
                    cinfo = "%s " % ss.codec
            except Exception as e:
                encoder_latency = 0
                log("failed to get encoder latency for %s: %s", ss.codec, e)
        log("get_sound_source_latency() %s: %s", cinfo, encoder_latency)
        return encoder_latency


    def get_info(self):
        return {"sound" : self.get_sound_info()}

    def get_sound_info(self):
        def sound_info(supported, prop, codecs):
            i = {"codecs" : codecs}
            if not supported:
                i["state"] = "disabled"
                return i
            if prop is None:
                i["state"] = "inactive"
                return i
            i.update(prop.get_info())
            return i
        info = {
                "speaker"       : sound_info(self.supports_speaker, self.sound_source, self.sound_decoders),
                "microphone"    : sound_info(self.supports_microphone, self.sound_sink, self.sound_encoders),
                }
        for prop in ("pulseaudio_id", "pulseaudio_server"):
            v = getattr(self, prop)
            if v is not None:
                info[prop] = v
        return info
