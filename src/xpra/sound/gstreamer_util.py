#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os

from xpra.log import Logger
log = Logger()

SOUND_TEST_MODE = os.environ.get("XPRA_SOUND_TEST", "0")!="0"


VORBIS = "vorbis"
AAC = "aac"
FLAC = "flac"
MP3 = "mp3"
WAV = "wav"
OPUS = "opus"
SPEEX = "speex"
WAVPACK = "wavpack"
#TODO: ac3, amr, dca?

#format: encoder, formatter, decoder, parser
CODECS = {
            #VORBIS : ("vorbisenc", "oggmux", "vorbisdec", "oggdemux"),
            #AAC : ("faac", "mp4mux", "faad", "aacparse"),
            FLAC    : ("flacenc",       "oggmux",   "flacdec",      "oggdemux"),
            MP3     : ("lamemp3enc",    None,       "mad",          "mp3parse"),
            WAV     : ("wavenc",        None,       None,           "wavparse"),
            OPUS    : ("opusenc",       "oggmux",   "opusdec",      "oggdemux"),
            SPEEX   : ("speexenc",      "oggmux",   "speexdec",     "oggdemux"),
            WAVPACK : ("wavpackenc",    None,       "wavpackdec",   "wavpackparse"),
            }
CODEC_ORDER = [MP3, OPUS, WAVPACK, WAV, FLAC, SPEEX]


#code to temporarily redirect stderr and restore it afterwards, adapted from:
#http://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python
#so we can get rid of the stupid gst warning below:
#"** Message: pygobject_register_sinkfunc is deprecated (GstObject)"
#ideally we would redirect to a buffer so we could still capture and show these messages in debug out
#we only do this on win32 because on Linux this interferes with server daemonizing
def redirect_stderr():
    if not sys.platform.startswith("win"):
        return None
    sys.stderr.flush() # <--- important when redirecting to files
    newstderr = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    sys.stderr = os.fdopen(newstderr, 'w')
    return newstderr

def unredirect_stderr(oldfd):
    if oldfd is not None:
        os.dup2(oldfd, 2)


has_gst = False
all_plugin_names = []
pygst_version = ""
gst_version = ""
#ugly win32 hack to make it find the gstreamer plugins:
if sys.platform.startswith("win"):
    if hasattr(sys, "frozen"):
        if sys.frozen in ("windows_exe", "console_exe"):
            main_dir = os.path.dirname(unicode(sys.executable, sys.getfilesystemencoding()))
            os.environ["GST_PLUGIN_PATH"] = os.path.join(main_dir, "gstreamer-0.10")
#now do the import with stderr redirection:
import pygst
pygst.require("0.10")
try:
    oldfd = redirect_stderr()
    import gst
finally:
    unredirect_stderr(oldfd)
has_gst = True
gst_version = gst.gst_version
pygst_version = gst.pygst_version


def get_all_plugin_names():
    global all_plugin_names
    if len(all_plugin_names)==0:
        registry = gst.registry_get_default()
        all_plugin_names = [el.get_name() for el in registry.get_feature_list(gst.ElementFactory)]
        all_plugin_names.sort()
        log("found the following plugins: %s", all_plugin_names)
    return all_plugin_names

def has_plugins(*names):
    allp = get_all_plugin_names()
    missing = [name for name in names if (name is not None and name not in allp)]
    if len(missing)>0:
        log("missing %s from %s (all=%s)", missing, names, allp)
    return len(missing)==0

def get_encoder_formatter(name):
    assert name in CODECS, "invalid codec: %s" % name
    encoder, formatter, _, _ = CODECS.get(name)
    assert encoder is None or has_plugins(encoder), "encoder %s not found" % encoder
    assert formatter is None or has_plugins(formatter), "formatter %s not found" % formatter
    return encoder, formatter

def get_decoder_parser(name):
    assert name in CODECS, "invalid codec: %s" % name
    _, _, decoder, parser = CODECS.get(name)
    assert decoder is None or has_plugins(decoder), "decoder %s not found" % decoder
    assert parser is None or has_plugins(parser), "parser %s not found" % parser
    return decoder, parser

def has_encoder(name):
    assert name in CODECS, "invalid codec: %s" % name
    encoder, fmt, _, _ = CODECS.get(name)
    return has_plugins(encoder, fmt)

def has_decoder(name):
    assert name in CODECS, "invalid codec: %s" % name
    _, _, decoder, parser = CODECS.get(name)
    return has_plugins(decoder, parser)

def has_codec(name):
    return has_encoder(name) and has_decoder(name)

def can_encode():
    return [x for x in CODEC_ORDER if has_encoder(x)]

def can_decode():
    return [x for x in CODEC_ORDER if has_decoder(x)]


def plugin_str(plugin, options):
    if plugin is None:
        return None
    s = "%s" % plugin
    if options:
        s += " "
        s += " ".join([("%s=%s" % (k,v)) for k,v in options.items()])
    return s

def add_gst_capabilities(capabilities, receive=True, send=True,
                        receive_codecs=[], send_codecs=[]):
    capabilities["gst_version"] = gst_version
    capabilities["pygst_version"] = pygst_version
    capabilities["sound.decoders"] = receive_codecs
    capabilities["sound.encoders"] = send_codecs
    capabilities["sound.receive"] = receive and len(receive_codecs)>0
    capabilities["sound.send"] = send and len(send_codecs)>0


def start_sending_sound(remote_decoders, local_decoders, remote_pulseaudio_server, remote_pulseaudio_id):
    try:
        matching_codecs = [x for x in remote_decoders if x in local_decoders]
        ordered_codecs = [x for x in CODEC_ORDER if x in matching_codecs]
        if len(ordered_codecs)==0:
            log.error("no matching codecs between remote (%s) and local (%s) - sound disabled", remote_decoders, local_decoders)
            return    None
        codec = ordered_codecs[0]
        log.info("using sound codec %s", codec)
        from xpra.sound.src import SoundSource
        if SOUND_TEST_MODE:
            sound_source = SoundSource("audiotestsrc", {"wave":2, "freq":110, "volume":0.4}, codec, {})
            log.info("using test sound source")
        else:
            from xpra.sound.pulseaudio_util import has_pa, get_pa_device_options
            from xpra.sound.pulseaudio_util import get_pulse_server, get_pulse_id
            if not has_pa():
                log.error("pulseaudio not supported - sound disabled")
                return    None
            pa_server = get_pulse_server()
            log("start sound, remote pulseaudio server=%s, local pulseaudio server=%s", remote_pulseaudio_server, pa_server)
            if remote_pulseaudio_server and (remote_pulseaudio_server==pa_server or len(pa_server)>16 and remote_pulseaudio_server.endswith(pa_server)):
                log.error("identical pulseaudio server, refusing to create a sound loop - sound disabled")
                return    None
            pa_id = get_pulse_id()
            log("start sound, client id=%s, server id=%s", remote_pulseaudio_id, pa_id)
            if remote_pulseaudio_id and remote_pulseaudio_id==pa_id:
                log.error("identical pulseaudio ID, refusing to create a sound loop - sound disabled")
                return    None
            monitor_devices = get_pa_device_options(True, False)
            log("found pulseaudio monitor devices: %s", monitor_devices)
            if len(monitor_devices)==0:
                log.error("could not detect any pulseaudio monitor devices - sound forwarding is disabled")
                return    None
            if len(monitor_devices)>1:
                log.warn("found more than one monitor device: %s", monitor_devices)
                log.warn("using: %s", monitor_devices.items()[0][1])
            monitor_device = monitor_devices.items()[0][0]
            sound_source = SoundSource("pulsesrc", {"device" : monitor_device}, codec, {})
            log.info("starting sound using pulseaudio device %s", monitor_device)
        return sound_source
    except Exception, e:
        log.error("error setting up sound: %s", e, exc_info=True)
        return    None

def main():
    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.INFO)

    log.info("GStreamer plugins found: %s", ", ".join(get_all_plugin_names()))
    if sys.platform.startswith("win"):
        print("\nPress Enter to close")
        sys.stdin.readline()
    log.info("")
    log.info("encoders supported: %s", [x for x in CODEC_ORDER if has_encoder(x)])
    log.info("decoders supported: %s", [x for x in CODEC_ORDER if has_decoder(x)])


if __name__ == "__main__":
    main()
