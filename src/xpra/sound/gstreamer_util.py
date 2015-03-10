#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os

from xpra.util import AdHocStruct
from xpra.log import Logger
log = Logger("sound")

GST_QUEUE_NO_LEAK             = 0
GST_QUEUE_LEAK_UPSTREAM       = 1
GST_QUEUE_LEAK_DOWNSTREAM     = 2
GST_QUEUE_LEAK_DEFAULT = GST_QUEUE_LEAK_DOWNSTREAM
MS_TO_NS = 1000000

QUEUE_LEAK = int(os.environ.get("XPRA_SOUND_QUEUE_LEAK", GST_QUEUE_LEAK_DEFAULT))
if QUEUE_LEAK not in (GST_QUEUE_NO_LEAK, GST_QUEUE_LEAK_UPSTREAM, GST_QUEUE_LEAK_DOWNSTREAM):
    log.error("invalid leak option %s", QUEUE_LEAK)
    QUEUE_LEAK = GST_QUEUE_LEAK_DEFAULT

def get_queue_time(default_value=450):
    queue_time = int(os.environ.get("XPRA_SOUND_QUEUE_TIME", default_value))*MS_TO_NS
    queue_time = max(0, queue_time)
    return queue_time


ALLOW_SOUND_LOOP = os.environ.get("XPRA_ALLOW_SOUND_LOOP", "0")=="1"


NAME_TO_SRC_PLUGIN = {
    "auto"          : "autoaudiosrc",
    "alsa"          : "alsasrc",
    "oss"           : "osssrc",
    "oss4"          : "oss4src",
    "jack"          : "jackaudiosrc",
    "osx"           : "osxaudiosrc",
    "test"          : "audiotestsrc",
    "pulse"         : "pulsesrc",
    "direct"        : "directsoundsrc",
    }
SRC_TO_NAME_PLUGIN = {}
for k,v in NAME_TO_SRC_PLUGIN.items():
    SRC_TO_NAME_PLUGIN[v] = k
PLUGIN_TO_DESCRIPTION = {
    "pulsesrc"      : "Pulseaudio",
    "jacksrc"       : "JACK Audio Connection Kit",
    }
NAME_TO_INFO_PLUGIN = {
    "auto"          : "Wrapper audio source for automatically detected audio source",
    "alsa"          : "Read from a sound card via ALSA",
    "oss"           : "Capture from a sound card via OSS",
    "oss4"          : "Capture from a sound card via OSS version 4",
    "jack"          : "Captures audio from a JACK server",
    "osx"           : "Input from a sound card in OS X",
    "test"          : "Creates audio test signals of given frequency and volume",
    "pulse"         : "Captures audio from a PulseAudio server",
    "direct"        : "directsoundsrc",
    }


VORBIS = "vorbis"
AAC = "aac"
FLAC = "flac"
MP3 = "mp3"
WAV = "wav"
OPUS = "opus"
SPEEX = "speex"
WAVPACK = "wavpack"

#format: encoder, formatter, decoder, parser
#we keep multiple options here for the same encoding
#and will populate the ones that are actually available into the "CODECS" dict
CODEC_OPTIONS = [
            #VORBIS : ("vorbisenc", "oggmux", "vorbisdec", "oggdemux"),
            #AAC     : ("faac",          "oggmux",   "faad",         "aacparse"),
            (FLAC        , "flacenc",       "oggmux",   "flacdec",      "oggdemux"),
            (MP3         , "lamemp3enc",    None,       "mad",          "mp3parse"),
            (MP3         , "lamemp3enc",    None,       "mad",          "mpegaudioparse"),
            (WAV         , "wavenc",        None,       None,           "wavparse"),
            (OPUS        , "opusenc",       "oggmux",   "opusdec",      "oggdemux"),
            (SPEEX       , "speexenc",      "oggmux",   "speexdec",     "oggdemux"),
            (WAVPACK     , "wavpackenc",    None,       "wavpackdec",   "wavpackparse"),
            ]
CODECS = {}

CODEC_ORDER = [MP3, WAVPACK, WAV, FLAC, SPEEX]


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


gst = None
has_gst = False

all_plugin_names = []
pygst_version = ""
gst_version = ""
#ugly win32 hack to make it find the gstreamer plugins:
if sys.platform.startswith("win") and hasattr(sys, "frozen") and sys.frozen in ("windows_exe", "console_exe", True):
    from xpra.platform.paths import get_app_dir
    if sys.version_info[0]<3:
        #gstreamer-0.10
        v = (0, 10)
    else:
        #gstreamer-1.0
        v = (1, 0)
    os.environ["GST_PLUGIN_PATH"] = os.path.join(get_app_dir(), "gstreamer-%s" % (".".join([str(x) for x in v])))


def import_gst1():
    import gi
    from gi.repository import Gst           #@UnresolvedImport
    #gi.require_version('Gst', '0.10')
    gi.require_version('Gst', '1.0')
    Gst.init(None)
    #make it look like pygst (gstreamer-0.10):
    Gst.registry_get_default = Gst.Registry.get
    Gst.get_pygst_version = lambda: gi.version_info
    Gst.get_gst_version = lambda: Gst.version()
    def new_buffer(data):
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)
        return buf
    Gst.new_buffer = new_buffer
    Gst.element_state_get_name = Gst.Element.state_get_name
    #note: we only copy the constants we actually need..
    for x in ('NULL', 'PAUSED', 'PLAYING', 'READY', 'VOID_PENDING'):
        setattr(Gst, "STATE_%s" % x, getattr(Gst.State, x))
    for x in ('EOS', 'ERROR', 'TAG', 'STREAM_STATUS', 'STATE_CHANGED',
              'LATENCY', 'WARNING', 'ASYNC_DONE', 'NEW_CLOCK', 'STREAM_STATUS',
              'BUFFERING', 'INFO', 'STREAM_START'
              ):
        setattr(Gst, "MESSAGE_%s" % x, getattr(Gst.MessageType, x))
    Gst.MESSAGE_DURATION = Gst.MessageType.DURATION_CHANGED
    Gst.FLOW_OK = Gst.FlowReturn.OK
    global gst_version, pygst_version
    gst_version = Gst.get_gst_version()
    pygst_version = Gst.get_pygst_version()
    return Gst

def import_gst0_10():
    global gst_version, pygst_version
    import pygst
    pygst.require("0.10")
    try:
        #initializing gstreamer parses sys.argv
        #which interferes with our own command line arguments
        #so we temporarily replace them:
        saved_args = sys.argv
        sys.argv = sys.argv[:1]
        #now do the import with stderr redirection
        #to avoid gobject warnings:
        oldfd = redirect_stderr()
        import gst
        gst_version = gst.gst_version
        pygst_version = gst.pygst_version
        gst.new_buffer = gst.Buffer
        if not hasattr(gst, 'MESSAGE_STREAM_START'):
            #a None value is better than nothing:
            #(our code can assume it exists - just never matches)
            gst.MESSAGE_STREAM_START = None
        return gst
    finally:
        unredirect_stderr(oldfd)
        sys.argv = saved_args

_gst_major_version = None
try:
    from xpra.gtk_common.gobject_compat import is_gtk3
    if is_gtk3():
        gst = import_gst1()
        _gst_major_version = 1
    else:
        gst = import_gst0_10()
        _gst_major_version = 0
    has_gst = True
except:
    log("failed to import GStreamer", exc_info=True)


def normv(v):
    if v==2**64-1:
        return -1
    return v


def get_all_plugin_names():
    global all_plugin_names, has_gst
    if len(all_plugin_names)==0 and has_gst:
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


if has_gst:
    #populate CODECS:
    for elements in CODEC_OPTIONS:
        encoding = elements[0]
        if encoding in CODECS:
            #we already have one for this encoding
            continue
        elif sys.platform.startswith("win") and _gst_major_version==0 and encoding==FLAC:
            #the gstreamer 0.10 builds on win32 use the outdated oss build,
            #which includes outdated flac libraries with known CVEs,
            #so avoid using those:
            log("avoiding outdated flac module (likely buggy on win32 with gstreamer 0.10)")
            continue
        #verify we have all the elements needed:
        if has_plugins(*elements[1:]):
            #ie: FLAC, "flacenc", "oggmux", "flacdec", "oggdemux" = elements
            encoding, encoder, muxer, decoder, demuxer = elements
            CODECS[encoding] = (encoder, muxer, decoder, demuxer)
    log("initialized CODECS:")
    for k in [x for x in CODEC_ORDER if x in CODECS]:
        log("* %s : %s", k, CODECS[k])

def get_sound_codecs(is_speaker, is_server):
    global has_gst
    if not has_gst:
        return []
    try:
        if (is_server and is_speaker) or (not is_server and not is_speaker):
            return can_encode()
        else:
            return can_decode()
    except Exception as e:
        log.warn("failed to get list of codecs: %s" % e)
        return []

def show_sound_codec_help(is_server, speaker_codecs, microphone_codecs):
    if not has_gst:
        return "sound is not supported - gstreamer not present or not accessible"
    info = []
    all_speaker_codecs = get_sound_codecs(True, is_server)
    invalid_sc = [x for x in speaker_codecs if x not in all_speaker_codecs]
    hs = "help" in speaker_codecs
    if hs:
        info.append("speaker codecs available: %s" % (", ".join(all_speaker_codecs)))
    elif len(invalid_sc):
        info.append("WARNING: some of the specified speaker codecs are not available: %s" % (", ".join(invalid_sc)))
        for x in invalid_sc:
            speaker_codecs.remove(x)
    elif len(speaker_codecs)==0:
        speaker_codecs += all_speaker_codecs

    all_microphone_codecs = get_sound_codecs(True, is_server)
    invalid_mc = [x for x in microphone_codecs if x not in all_microphone_codecs]
    hm = "help" in microphone_codecs
    if hm:
        info.append("microphone codecs available: %s" % (", ".join(all_microphone_codecs)))
    elif len(invalid_mc):
        info.append("WARNING: some of the specified microphone codecs are not available: %s" % (", ".join(invalid_mc)))
        for x in invalid_mc:
            microphone_codecs.remove(x)
    elif len(microphone_codecs)==0:
        microphone_codecs += all_microphone_codecs
    return info


def get_encoder_formatter(name):
    assert name in CODECS, "invalid codec: %s (should be one of: %s)" % (name, CODECS.keys())
    encoder, formatter, _, _ = CODECS.get(name)
    assert encoder is None or has_plugins(encoder), "encoder %s not found" % encoder
    assert formatter is None or has_plugins(formatter), "formatter %s not found" % formatter
    return encoder, formatter

def get_decoder_parser(name):
    assert name in CODECS, "invalid codec: %s (should be one of: %s)" % (name, CODECS.keys())
    _, _, decoder, parser = CODECS.get(name)
    assert decoder is None or has_plugins(decoder), "decoder %s not found" % decoder
    assert parser is None or has_plugins(parser), "parser %s not found" % parser
    return decoder, parser

def has_encoder(name):
    if name not in CODECS:
        return False
    encoder, fmt, _, _ = CODECS.get(name)
    return has_plugins(encoder, fmt)

def has_decoder(name):
    if name not in CODECS:
        return False
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


def get_source_plugins():
    sources = []
    from xpra.sound.pulseaudio_util import has_pa
    #we have to put pulsesrc first if pulseaudio is installed
    #because using autoaudiosource does not work properly for us:
    #it may still choose pulse, but without choosing the right device.
    if has_pa():
        sources.append("pulsesrc")
    sources.append("autoaudiosrc")
    if sys.platform.startswith("darwin"):
        sources.append("osxaudiosrc")
    elif sys.platform.startswith("win"):
        sources.append("directsoundsrc")
    if os.name=="posix":
        sources += ["alsasrc", "jackaudiosrc",
                    "osssrc", "oss4src",
                    "osxaudiosrc", "jackaudiosrc"]
    sources.append("audiotestsrc")
    return sources

def get_available_source_plugins():
    return [x for x in get_source_plugins() if has_plugins(x)]

def get_test_defaults(remote):
    return  {"wave" : 2, "freq" : 110, "volume" : 0.4}

WARNED_MULTIPLE_DEVICES = False
def get_pulse_defaults(remote):
    """
        choose the device to use
    """
    from xpra.sound.pulseaudio_util import has_pa, get_pa_device_options, get_default_sink
    from xpra.sound.pulseaudio_util import get_pulse_server, get_pulse_id, set_source_mute
    if not has_pa():
        log.warn("pulseaudio is not available!")
        return    None
    pa_server = get_pulse_server()
    log("start sound, remote pulseaudio server=%s, local pulseaudio server=%s", remote.pulseaudio_server, pa_server)
    #only worth comparing if we have a real server string
    #one that starts with {UUID}unix:/..
    if pa_server and pa_server.startswith("{") and \
        remote.pulseaudio_server and remote.pulseaudio_server==pa_server:
        log.error("identical Pulseaudio server, refusing to create a sound loop - sound disabled")
        return    None
    pa_id = get_pulse_id()
    log("start sound, client id=%s, server id=%s", remote.pulseaudio_id, pa_id)
    if remote.pulseaudio_id and remote.pulseaudio_id==pa_id:
        log.error("identical Pulseaudio ID, refusing to create a sound loop - sound disabled")
        return    None
    monitor_devices = get_pa_device_options(True, False)
    log("found pulseaudio monitor devices: %s", monitor_devices)
    if len(monitor_devices)==0:
        log.error("could not detect any Pulseaudio monitor devices - sound forwarding is disabled")
        return    None
    #default to first one:
    monitor_device, monitor_device_name = monitor_devices.items()[0]
    if len(monitor_devices)>1:
        default_sink = get_default_sink()
        default_monitor = default_sink+".monitor"
        global WARNED_MULTIPLE_DEVICES
        if not WARNED_MULTIPLE_DEVICES:
            WARNED_MULTIPLE_DEVICES = True
            log.warn("found more than one audio monitor device:")
            for k,v in monitor_devices.items():
                log.warn(" * %s (\"%s\")", v, k)
        if default_monitor in monitor_devices:
            monitor_device = default_monitor
            monitor_device_name = monitor_devices.get(default_monitor)
            if not WARNED_MULTIPLE_DEVICES:
                log.warn("using monitor of default sink: %s", monitor_device_name)
        else:
            if not WARNED_MULTIPLE_DEVICES:
                log.warn("using the first device")
    log.info("using Pulseaudio device '%s'", monitor_device_name)
    #make sure it is not muted:
    set_source_mute(monitor_device, mute=False)
    return {"device" : monitor_device}

#a list of functions to call to get the plugin options
#at runtime (so we can perform runtime checks on remote data,
# to avoid sound loops for example)
DEFAULT_SRC_PLUGIN_OPTIONS = {
    "test"                  : get_test_defaults,
    "pulse"                 : get_pulse_defaults,
    }


def parse_element_options(options_str):
    #parse the options string and add the pairs:
    options = {}
    for s in options_str.split(","):
        if not s:
            continue
        try:
            k,v = s.split("=", 1)
            options[k] = v
        except Exception as e:
            log.warn("failed to parse plugin option '%s': %s", s, e)
    return options

def get_sound_source_options(plugin, options_str, remote):
    """
        Given a plugin (short name), options string and remote info,
        return the options for the plugin given,
        using the dynamic defaults (which may use remote info)
        and applying the options string on top.
    """
    #ie: get_sound_source_options("audiotestsrc", "wave=4,freq=220", {remote_pulseaudio_server=XYZ}):
    #use the defaults as starting point:
    defaults_fn = DEFAULT_SRC_PLUGIN_OPTIONS.get(plugin)
    if defaults_fn:
        options = defaults_fn(remote)
        if options is None:
            #means failure
            return None
    else:
        options = {}
    options.update(parse_element_options(options_str))
    return options

def parse_sound_source(sound_source_plugin, remote):
    #format: PLUGINNAME:options
    #ie: test:wave=2,freq=110,volume=0.4
    #ie: pulse:device=device.alsa_input.pci-0000_00_14.2.analog-stereo
    plugin = sound_source_plugin.split(":")[0]
    options_str = (sound_source_plugin+":").split(":",1)[1]
    simple_str = (plugin).lower().strip()
    if not simple_str:
        #choose the first one from
        options = get_available_source_plugins()
        if not options:
            log.error("no source plugins available")
            return None
        log("parse_sound_source: no plugin specified, using default: %s", options[0])
        simple_str = options[0]
    for s in ("src", "sound", "audio"):
        if simple_str.endswith(s):
            simple_str = simple_str[:-len(s)]
    gst_sound_source_plugin = NAME_TO_SRC_PLUGIN.get(simple_str)
    if not gst_sound_source_plugin:
        log.error("unknown source plugin: '%s' / '%s'", simple_str, sound_source_plugin)
        return  None, {}
    log("parse_sound_source(%s, %s) plugin=%s", sound_source_plugin, remote, gst_sound_source_plugin)
    options = get_sound_source_options(simple_str, options_str, remote)
    log("get_sound_source_options%s=%s", (simple_str, options_str, remote), options)
    if options is None:
        #means error
        return None, {}
    return gst_sound_source_plugin, options


def start_sending_sound(sound_source_plugin, codec, volume, remote_decoders, local_decoders, remote_pulseaudio_server, remote_pulseaudio_id):
    assert has_gst
    try:
        #info about the remote end:
        remote = AdHocStruct()
        remote.pulseaudio_server = remote_pulseaudio_server
        remote.pulseaudio_id = remote_pulseaudio_id
        remote.remote_decoders = remote_decoders
        plugin, options = parse_sound_source(sound_source_plugin, remote)
        if not plugin:
            log.error("failed to setup '%s' sound stream source", (sound_source_plugin or "auto"))
            return  None
        log("parsed '%s':", sound_source_plugin)
        log("plugin=%s", plugin)
        log("options=%s", options)
        matching_codecs = [x for x in remote_decoders if x in local_decoders]
        ordered_codecs = [x for x in CODEC_ORDER if x in matching_codecs]
        if len(ordered_codecs)==0:
            log.error("no matching codecs between remote (%s) and local (%s) - sound disabled", remote_decoders, local_decoders)
            return    None
        if codec is not None and codec not in matching_codecs:
            log.warn("invalid codec specified: %s", codec)
            codec = None
        if codec is None:
            codec = ordered_codecs[0]
        log("using sound codec %s", codec)
        from xpra.sound.src import SoundSource
        log.info("starting sound stream capture using %s source", PLUGIN_TO_DESCRIPTION.get(plugin, plugin))
        return SoundSource(plugin, options, codec, volume, {})
    except Exception as e:
        log.error("error setting up sound: %s", e, exc_info=True)
        return    None


def get_info(receive=True, send=True, receive_codecs=[], send_codecs=[]):
    if not has_gst:
        return  {}
    return {"gst.version"   : gst_version,
            "pygst.version" : pygst_version,
            "decoders"      : receive_codecs,
            "encoders"      : send_codecs,
            "receive"       : receive and len(receive_codecs)>0,
            "send"          : send and len(send_codecs)>0,
            "plugins"       : get_all_plugin_names(),
            }


def main():
    from xpra.platform import init, clean
    try:
        init("GStreamer-Info", "GStreamer Information")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()
        print("GStreamer plugins found: %s" % ", ".join(get_all_plugin_names()))
        print("")
        print("GStreamer version: %s" % ".".join([str(x) for x in gst_version]))
        print("PyGStreamer version: %s" % ".".join([str(x) for x in pygst_version]))
        print("")
        encs = [x for x in CODEC_ORDER if has_encoder(x)]
        decs = [x for x in CODEC_ORDER if has_decoder(x)]
        print("encoders supported: %s" % ", ".join(encs))
        print("decoders supported: %s" % ", ".join(decs))
    finally:
        clean()


if __name__ == "__main__":
    main()
