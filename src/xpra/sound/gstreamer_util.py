#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os

from xpra.sound.common import FLAC_OGG, OPUS_OGG, OPUS_MKA, SPEEX_OGG, VORBIS_OGG, VORBIS_MKA, \
                                AAC_MPEG4, WAV_LZ4, WAV_LZO, \
                                VORBIS, FLAC, MP3, MP3_MPEG4, OPUS, SPEEX, WAV, WAVPACK, \
                                MPEG4, MKA, OGG

from xpra.util import csv, engs, parse_simple_dict, envint, envbool
from xpra.log import Logger
log = Logger("sound", "gstreamer")

if sys.version > '3':
    unicode = str           #@ReservedAssignment


#used on the server (reversed):
XPRA_PULSE_SOURCE_DEVICE_NAME = "Speaker"
XPRA_PULSE_SINK_DEVICE_NAME = "Microphone"

GST_QUEUE_NO_LEAK             = 0
GST_QUEUE_LEAK_UPSTREAM       = 1
GST_QUEUE_LEAK_DOWNSTREAM     = 2
GST_QUEUE_LEAK_DEFAULT = GST_QUEUE_LEAK_DOWNSTREAM
MS_TO_NS = 1000000

QUEUE_LEAK = envint("XPRA_SOUND_QUEUE_LEAK", GST_QUEUE_LEAK_DEFAULT)
if QUEUE_LEAK not in (GST_QUEUE_NO_LEAK, GST_QUEUE_LEAK_UPSTREAM, GST_QUEUE_LEAK_DOWNSTREAM):
    log.error("invalid leak option %s", QUEUE_LEAK)
    QUEUE_LEAK = GST_QUEUE_LEAK_DEFAULT

def get_queue_time(default_value=450, prefix=""):
    queue_time = int(os.environ.get("XPRA_SOUND_QUEUE_%sTIME" % prefix, default_value))*MS_TO_NS
    queue_time = max(0, queue_time)
    return queue_time


WIN32 = sys.platform.startswith("win")
OSX = sys.platform.startswith("darwin")

ALLOW_SOUND_LOOP = envbool("XPRA_ALLOW_SOUND_LOOP", False)
GSTREAMER1 = envbool("XPRA_GSTREAMER1", True)
PULSEAUDIO_DEVICE_NAME = os.environ.get("XPRA_PULSEAUDIO_DEVICE_NAME", "")
USE_DEFAULT_DEVICE = envbool("XPRA_USE_DEFAULT_DEVICE", True)
def force_enabled(codec_name):
    return os.environ.get("XPRA_SOUND_CODEC_ENABLE_%s" % codec_name.upper(), "0")=="1"


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
SRC_HAS_DEVICE_NAME = ["alsasrc", "osssrc", "oss4src", "jackaudiosrc", "pulsesrc", "directsoundsrc", "osxaudiosrc"]
SRC_TO_NAME_PLUGIN = {}
for k,v in NAME_TO_SRC_PLUGIN.items():
    SRC_TO_NAME_PLUGIN[v] = k
PLUGIN_TO_DESCRIPTION = {
    "pulsesrc"      : "Pulseaudio",
    "jacksrc"       : "JACK Audio Connection Kit",
    }

NAME_TO_INFO_PLUGIN = {
    "auto"          : "Automatic audio source selection",
    "alsa"          : "ALSA Linux Sound",
    "oss"           : "OSS sound cards",
    "oss4"          : "OSS version 4 sound cards",
    "jack"          : "JACK audio sound server",
    "osx"           : "Mac OS X sound cards",
    "test"          : "Test signal",
    "pulse"         : "PulseAudio",
    "direct"        : "Microsoft Windows Direct Sound",
    }


#format: encoder, container-formatter, decoder, container-parser, stream-compressor
#we keep multiple options here for the same encoding
#and will populate the ones that are actually available into the "CODECS" dict
CODEC_OPTIONS = [
        (VORBIS_MKA , "vorbisenc",      "webmmux",      "vorbisdec",                    "matroskademux"),
        #those two fail silently - no idea why:
        #(VORBIS_OGG , "vorbisenc",      "oggmux",       "vorbisparse ! vorbisdec",      "oggdemux"),
        #(VORBIS     , "vorbisenc",      None,           "vorbisparse ! vorbisdec",      None),
        (FLAC       , "flacenc",        None,           "flacparse ! flacdec",          None),
        #this only works in gstreamer 0.10 and is filtered out during initialization:
        (FLAC_OGG   , "flacenc",        "oggmux",       "flacparse ! flacdec",          "oggdemux"),
        (MP3        , "lamemp3enc",     None,           "mp3parse ! mad",               None),
        (MP3        , "lamemp3enc",     None,           "mpegaudioparse ! mad",         None),
        (MP3_MPEG4  , "lamemp3enc",     "mp4mux",       "mp3parse ! mad",               "qtdemux"),
        (MP3_MPEG4  , "lamemp3enc",     "mp4mux",       "mpegaudioparse ! mad",         "qtdemux"),
        (WAV        , "wavenc",         None,           "wavparse",                     None),
        (WAV_LZ4    , "wavenc",         None,           "wavparse",                     None,                       "lz4"),
        (WAV_LZO    , "wavenc",         None,           "wavparse",                     None,                       "lzo"),
        (OPUS_OGG   , "opusenc",        "oggmux",       "opusdec",                      "oggdemux"),
        (OPUS       , "opusenc",        None,           "opusparse ! opusdec",          None),
        #this can cause "could not link opusenc0 to webmmux0"
        (OPUS_MKA   , "opusenc",        "webmmux",      "opusdec",                      "matroskademux"),
        (SPEEX_OGG  , "speexenc",       "oggmux",       "speexdec",                     "oggdemux"),
        (WAVPACK    , "wavpackenc",      None,          "wavpackparse ! wavpackdec",    None),
        (AAC_MPEG4  , "faac",           "mp4mux",       "faad",                         "qtdemux"),
        (AAC_MPEG4  , "avenc_aac",      "mp4mux",       "avdec_aac",                    "qtdemux"),
            ]

MUX_OPTIONS = [
               (OGG,    "oggmux",   "oggdemux"),
               (MKA,    "webmmux",  "matroskademux"),
               (MPEG4,  "mp4mux",   "qtdemux"),
              ]
emux = [x for x in os.environ.get("XPRA_MUXER_OPTIONS", "").split(",") if len(x.strip())>0]
if emux:
    mo = [v for v in MUX_OPTIONS if v[0] in emux]
    if mo:
        MUX_OPTIONS = mo
    else:
        log.warn("Warning: invalid muxer options %s", emux)
    del mo
del emux


#these encoders require an "audioconvert" element:
ENCODER_NEEDS_AUDIOCONVERT = ("flacenc", "wavpackenc")
#if this is lightweight enough, maybe we should include it unconditionally?
SOURCE_NEEDS_AUDIOCONVERT = ("directsoundsrc", "osxaudiosrc", "autoaudiosrc")

#options we use to tune for low latency:
OGG_DELAY = 20*MS_TO_NS
ENCODER_DEFAULT_OPTIONS_COMMON = {
            "lamemp3enc"    : {
                               "encoding-engine-quality" : 0,
                               },   #"fast"
            "wavpackenc"    : {
                               "mode"       : 1,        #"fast" (0 aka "very fast" is not supported)
                               "bitrate"    : 256000,
                               },
            "flacenc"       : {
                               "quality"    : 0,        #"fast"
                               },
            "avenc_aac"     : {
                               "compliance" : 1,       #allows experimental
                               "perfect-timestamp"  : 1,
                               },
            "faac"          : {
                               "perfect-timestamp"  : 1,
                               },
            #"vorbisenc"     : {"perfect-timestamp" : 1},
                           }
ENCODER_DEFAULT_OPTIONS = {
                            0       : {
                                       "opusenc"       : {
                                                          "cbr"            : 0,
                                                          "complexity"     : 0
                                                          },
                                       },
                            1      :   {
                                        #FIXME: figure out when it is safe to apply the "bitrate-type" setting:
                                        "opusenc"       : {
                                                           #only available with 1.6 onwards?
                                                           #"bitrate-type"   : 2,      #constrained vbr
                                                           "complexity"     : 0
                                                           },
                                        },
                           }
#we may want to review this if/when we implement UDP transport:
MUXER_DEFAULT_OPTIONS = {
            "oggmux"        : {
                               "max-delay"          : OGG_DELAY,
                               "max-page-delay"     : OGG_DELAY,
                               },
            "webmmux"       : {
                               "writing-app"        : "Xpra",
                               "streamable"         : 1,
                               #"min-index-interval" : 0,
                               },
            "mp4mux"        : {
                               "faststart"          : 1,
                               "streamable"         : 1,
                               "fragment-duration"  : 20,
                               "presentation-time"  : 0,
                               }
           }

#based on the encoder options above:
ENCODER_LATENCY = {
        VORBIS      : 0,
        VORBIS_OGG  : 0,
        VORBIS_MKA  : 0,
        MP3         : 250,
        FLAC        : 50,
        WAV         : 0,
        WAVPACK     : 600,
        OPUS        : 0,
        SPEEX       : 0,
       }

CODEC_ORDER = [OPUS_OGG, VORBIS_MKA, FLAC_OGG, MP3, AAC_MPEG4, WAV_LZ4, WAV_LZO, WAV, WAVPACK, SPEEX_OGG, OPUS, VORBIS, FLAC_OGG, OPUS_MKA, FLAC, MP3_MPEG4]


gst = None
has_gst = None
gst_major_version = None
gst_vinfo = None

pygst_version = ""
gst_version = ""

def get_pygst_version():
    return pygst_version

def get_gst_version():
    return gst_version


def import_gst1():
    log("import_gst1()")
    import gi
    log("import_gst1() gi=%s", gi)
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst           #@UnresolvedImport
    log("import_gst1() Gst=%s", Gst)
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
    log("import_gst0_10()")
    global gst_version, pygst_version
    import pygst
    log("import_gst0_10() pygst=%s", pygst)
    pygst.require("0.10")
    #initializing gstreamer parses sys.argv
    #which interferes with our own command line arguments
    #so we temporarily hide it,
    #also import with stderr redirection in place
    #to avoid gobject warnings:
    from xpra.os_util import HideStdErr, HideSysArgv
    with HideStdErr():
        with HideSysArgv():
            import gst
    gst_version = gst.gst_version
    pygst_version = gst.pygst_version
    gst.new_buffer = gst.Buffer
    if not hasattr(gst, 'MESSAGE_STREAM_START'):
        #a None value is better than nothing:
        #(our code can assume it exists - just never matches)
        gst.MESSAGE_STREAM_START = None
    return gst


def get_version_str(version):
    if version==1:
        return "1.0"
    else:
        return "0.10"

def import_gst():
    global gst, has_gst, gst_vinfo, gst_major_version
    if has_gst is not None:
        return gst

    PYTHON3 = sys.version_info[0]>=3
    if PYTHON3:
        imports = [ (import_gst1,       1) ]
    elif GSTREAMER1:
        imports = [
                    (import_gst1,       1),
                    (import_gst0_10,    0),
                  ]
    else:
        imports = [
                    (import_gst0_10,    0),
                    (import_gst1,       1),
                  ]
    errs = {}
    saved_sys_path = sys.path[:]
    saved_os_environ = os.environ.copy()
    for import_function, MV in imports:
        #restore os.environ and sys.path
        sys.path = saved_sys_path[:]
        os.environ.clear()
        os.environ.update(saved_os_environ)
        vstr = get_version_str(MV)
        #hacks to locate gstreamer plugins on win32 and osx:
        if WIN32:
            frozen = hasattr(sys, "frozen") and sys.frozen in ("windows_exe", "console_exe", True)
            log("gstreamer_util: frozen=%s", frozen)
            if frozen:
                #on win32, we keep separate trees
                #because GStreamer 0.10 and 1.x were built using different and / or incompatible version of the same libraries:
                from xpra.platform.paths import get_app_dir
                gst_dir = os.path.join(get_app_dir(), "gstreamer-%s" % vstr)     #ie: C:\Program Files\Xpra\gstreamer-0.10
                os.environ["GST_PLUGIN_PATH"] = gst_dir
                if MV==1:
                    gst_bin_dir = os.path.join(gst_dir, "bin")                       #ie: C:\Program Files\Xpra\gstreamer-0.10\bin
                    os.environ["PATH"] = os.pathsep.join(x for x in (gst_bin_dir, os.environ.get("PATH", "")) if x)
                    sys.path.insert(0, gst_bin_dir)
                    scanner = os.path.join(gst_bin_dir, "gst-plugin-scanner.exe")
                    if os.path.exists(scanner):
                        os.environ["GST_PLUGIN_SCANNER"]    = scanner
                    gi_dir = os.path.join(get_app_dir(), "girepository-%s" % vstr)
                    os.environ["GI_TYPELIB_PATH"]       = gi_dir
        elif OSX:
            bundle_contents = os.environ.get("GST_BUNDLE_CONTENTS")
            log("OSX: GST_BUNDLE_CONTENTS=%s", bundle_contents)
            if bundle_contents:
                os.environ["GST_PLUGIN_PATH"]       = os.path.join(bundle_contents, "Resources", "lib", "gstreamer-%s" % vstr)
                os.environ["GST_PLUGIN_SCANNER"]    = os.path.join(bundle_contents, "Resources", "bin", "gst-plugin-scanner-%s" % vstr)
                if MV==1:
                    gi_dir = os.path.join(bundle_contents, "Resources", "lib", "girepository-%s" % vstr)
                    os.environ["GI_TYPELIB_PATH"]       = gi_dir
        if MV<1:
            #we should not be loading the gi bindings
            try:
                del os.environ["GI_TYPELIB_PATH"]
            except:
                pass
        log("GStreamer %s environment: %s", vstr, dict((k,v) for k,v in os.environ.items() if (k.startswith("GST") or k.startswith("GI") or k=="PATH")))
        log("GStreamer %s sys.path=%s", vstr, csv(sys.path))

        try:
            log("trying to import GStreamer %s using %s", get_version_str(MV), import_function)
            _gst = import_function()
            v = _gst.version()
            if v[-1]==0:
                v = v[:-1]
            gst_vinfo = ".".join((str(x) for x in v))
            gst_major_version = MV
            gst = _gst
            break
        except Exception as e:
            log("Warning failed to import GStreamer %s", vstr, exc_info=True)
            errs[vstr] = e
    if gst:
        log("Python GStreamer version %s for Python %s.%s", gst_vinfo, sys.version_info[0], sys.version_info[1])
    else:
        log.warn("Warning: failed to import GStreamer:")
        for vstr,e in errs.items():
            log.warn(" GStreamer %s: %s", vstr, e)
    has_gst = gst is not None
    return gst

def prevent_import():
    global has_gst, gst, import_gst
    if has_gst or gst or "gst" in sys.modules or "gi.repository.Gst" in sys.modules:
        raise Exception("cannot prevent the import of the GStreamer bindings, already loaded: %s" % gst)
    def fail_import():
        raise Exception("importing of the GStreamer bindings is not allowed!")
    import_gst = fail_import
    sys.modules["gst"] = None
    sys.modules["gi.repository.Gst"]= None


def normv(v):
    if v==2**64-1:
        return -1
    return v


all_plugin_names = []
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
    #support names that contain a gstreamer chain, ie: "flacparse ! flacdec"
    snames = []
    for x in names:
        if not x:
            continue
        snames += [v.strip() for v in x.split("!")]
    missing = [name for name in snames if (name is not None and name not in allp)]
    if len(missing)>0:
        log("missing %s from %s", missing, names)
    return len(missing)==0

def get_encoder_default_options(encoder):
    global gst_major_version, ENCODER_DEFAULT_OPTIONS_COMMON, ENCODER_DEFAULT_OPTIONS
    #strip the muxer:
    enc = encoder.split("+")[0]
    options = ENCODER_DEFAULT_OPTIONS_COMMON.get(enc, {}).copy()
    options.update(ENCODER_DEFAULT_OPTIONS.get(gst_major_version).get(enc, {}))
    return options


CODECS = None
ENCODERS = {}       #(encoder, payloader, stream-compressor)
DECODERS = {}       #(decoder, depayloader, stream-compressor)

def get_encoders():
    init_codecs()
    global ENCODERS
    return ENCODERS

def get_decoders():
    init_codecs()
    global DECODERS
    return DECODERS

def init_codecs():
    global CODECS, ENCODERS, DECODERS, gst_major_version
    if CODECS is not None or not has_gst:
        return CODECS or {}
    #populate CODECS:
    CODECS = {}
    for elements in CODEC_OPTIONS:
        if not validate_encoding(elements):
            continue
        try:
            encoding, encoder, payloader, decoder, depayloader, stream_compressor = (list(elements)+[None])[:6]
        except ValueError as e:
            log.error("Error: invalid codec entry: %s", e)
            log.error(" %s", elements)
            continue
        add_encoder(encoding, encoder, payloader, stream_compressor)
        add_decoder(encoding, decoder, depayloader, stream_compressor)
    log("initialized sound codecs:")
    def ci(v):
        return "%-22s" % (v or "")
    log("  - %s", "".join([ci(v) for v in ("encoder/decoder", "(de)payloader", "stream-compressor")]))
    for k in [x for x in CODEC_ORDER]:
        if k in ENCODERS or k in DECODERS:
            CODECS[k] = True
            log("* %s :", k)
            if k in ENCODERS:
                log("  - %s", "".join([ci(v) for v in ENCODERS[k]]))
            if k in DECODERS:
                log("  - %s", "".join([ci(v) for v in DECODERS[k]]))
    return CODECS

def add_encoder(encoding, encoder, payloader, stream_compressor):
    global ENCODERS
    if encoding in ENCODERS:
        return
    if OSX and encoding in (OPUS_OGG, ):
        log("avoiding %s on Mac OS X", encoding)
        return
    if has_plugins(encoder, payloader):
        ENCODERS[encoding] = (encoder, payloader, stream_compressor)

def add_decoder(encoding, decoder, depayloader, stream_compressor):
    global DECODERS
    if encoding in DECODERS:
        return
    if has_plugins(decoder, depayloader):
        DECODERS[encoding] = (decoder, depayloader, stream_compressor)

def validate_encoding(elements):
    #generic platform validation of encodings and plugins
    #full of quirks
    encoding = elements[0]
    if force_enabled(encoding):
        log.info("sound codec %s force enabled", encoding)
        return True
    elif len([x for x in elements if x and (x.find("matroska")>=0)])>0 and get_gst_version()<(1, ):
        #outdated versions of gstreamer cause problems with the gdp and matroskademux muxers,
        #the receiver may not be able to process the data
        #and we have no way of knowing what version they have at this point, so just disable those:
        log("avoiding %s with gdp muxer - gstreamer version %s is too old", encoding, get_gst_version())
        return False
    elif encoding.startswith(FLAC):
        #flac problems:
        if WIN32 and gst_major_version==0:
            #the gstreamer 0.10 builds on win32 use the outdated oss build,
            #which includes outdated flac libraries with known CVEs,
            #so avoid using those:
            log("avoiding outdated flac module (likely buggy on win32 with gstreamer 0.10)")
            return False
    elif WIN32 and encoding in (SPEEX_OGG, ):
        log("skipping %s on win32", encoding)
        return False
    elif encoding.startswith(OPUS):
        if gst_major_version<1:
            log("skipping %s with GStreamer 0.10", encoding)
            return False
        if encoding==OPUS_MKA and get_gst_version()<(1, 8):
            #this causes "could not link opusenc0 to webmmux0"
            #(not sure which versions are affected, but 1.8.x is not)
            log("skipping %s with GStreamer %s", encoding, get_gst_version())
            return False
    try:
        stream_compressor = elements[5]
    except:
        stream_compressor = None
    if stream_compressor and not has_stream_compressor(stream_compressor):
        log("skipping %s: missing %s", encoding, stream_compressor)
        return False
    return True

def has_stream_compressor(stream_compressor):
    if stream_compressor not in ("lz4", "lzo"):
        log.warn("Warning: invalid stream compressor '%s'", stream_compressor)
        return False
    from xpra.net.compression import use_lz4, use_lzo
    if stream_compressor=="lz4" and not use_lz4:
        return False
    if stream_compressor=="lzo" and not use_lzo:
        return False
    return True

def get_muxers():
    muxers = []
    for name,muxer,_ in MUX_OPTIONS:
        if has_plugins(muxer):
            muxers.append(name)
    return muxers

def get_demuxers():
    demuxers = []
    for name,_,demuxer in MUX_OPTIONS:
        if has_plugins(demuxer):
            demuxers.append(name)
    return demuxers

def get_stream_compressors():
    return [x for x in ["lz4", "lzo"] if has_stream_compressor(x)]

def get_encoder_elements(name):
    encoders = get_encoders()
    assert name in encoders, "invalid codec: %s (should be one of: %s)" % (name, encoders.keys())
    encoder, formatter, stream_compressor = encoders.get(name)
    assert stream_compressor is None or has_stream_compressor(stream_compressor), "stream-compressor %s not found" % stream_compressor
    assert encoder is None or has_plugins(encoder), "encoder %s not found" % encoder
    assert formatter is None or has_plugins(formatter), "formatter %s not found" % formatter
    return encoder, formatter, stream_compressor

def get_decoder_elements(name):
    decoders = get_decoders()
    assert name in decoders, "invalid codec: %s (should be one of: %s)" % (name, decoders.keys())
    decoder, parser, stream_compressor = decoders.get(name)
    assert stream_compressor is None or has_stream_compressor(stream_compressor), "stream-compressor %s not found" % stream_compressor
    assert decoder is None or has_plugins(decoder), "decoder %s not found" % decoder
    assert parser is None or has_plugins(parser), "parser %s not found" % parser
    return decoder, parser, stream_compressor

def has_encoder(name):
    encoders = get_encoders()
    if name not in encoders:
        return False
    encoder, fmt, _ = encoders.get(name)
    return has_plugins(encoder, fmt)

def has_decoder(name):
    decoders = get_decoders()
    if name not in decoders:
        return False
    decoder, parser, _ = decoders.get(name)
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
    def qstr(v):
        #only quote strings
        if type(v) in (str, unicode):
            return "\"%s\"" % v
        return v
    if options:
        s += " "
        s += " ".join([("%s=%s" % (k,qstr(v))) for k,v in options.items()])
    return s


def get_source_plugins():
    sources = []
    try:
        from xpra.sound.pulseaudio.pulseaudio_util import has_pa
        #we have to put pulsesrc first if pulseaudio is installed
        #because using autoaudiosource does not work properly for us:
        #it may still choose pulse, but without choosing the right device.
        if has_pa():
            sources.append("pulsesrc")
    except ImportError as e:
        log("get_source_plugins() no pulsesrc: %s", e)
    if OSX:
        sources.append("osxaudiosrc")
    elif WIN32:
        sources.append("directsoundsrc")
    sources.append("autoaudiosrc")
    if os.name=="posix":
        sources += ["alsasrc",
                    "osssrc", "oss4src",
                    "jackaudiosrc"]
    sources.append("audiotestsrc")
    return sources

def get_sink_plugins():
    SINKS = []
    if sys.platform.startswith("darwin"):
        SINKS.append("osxaudiosink")
    elif sys.platform.startswith("win"):
        SINKS.append("directsoundsink")
    SINKS.append("autoaudiosink")
    try:
        from xpra.sound.pulseaudio.pulseaudio_util import has_pa
        if has_pa():
            SINKS.append("pulsesink")
    except ImportError as e:
        log("get_sink_plugins() no pulsesink: %s", e)
    if os.name=="posix":
        SINKS += ["alsasink", "osssink", "oss4sink", "jackaudiosink"]
    return SINKS

def get_default_sink():
    sink = os.environ.get("XPRA_SOUND_SINK")
    sinks = get_sink_plugins()
    if sink:
        if sink not in sinks:
            log.error("invalid default sound sink: '%s' is not in %s", sink, csv(sinks))
        else:
            return sink
    try:
        from xpra.sound.pulseaudio.pulseaudio_util import has_pa, get_pactl_server
        if has_pa():
            s = get_pactl_server()
            if not s:
                log("cannot connect to pulseaudio server?")
            else:
                return "pulsesink"
    except ImportError as e:
        log("get_default_sink() no pulsesink: %s", e)
    return sinks[0]


def get_test_defaults(*args):
    return  {"wave" : 2, "freq" : 110, "volume" : 0.4}

WARNED_MULTIPLE_DEVICES = False
def get_pulse_defaults(device_name_match=None, want_monitor_device=True, input_or_output=None, remote=None, xpra_device_name=None):
    device = get_pulse_device(device_name_match, want_monitor_device, input_or_output, remote, xpra_device_name)
    if not device:
        return {}
    #make sure it is not muted:
    try:
        from xpra.sound.pulseaudio.pulseaudio_util import has_pa, set_source_mute, set_sink_mute
        if has_pa():
            if input_or_output is True or want_monitor_device:
                set_source_mute(device, mute=False)
            elif input_or_output is False:
                set_sink_mute(device, mute=False)
    except Exception as e:
        log("device %s may still be muted: %s", device, e)
    return {"device" : device}

def get_pulse_device(device_name_match=None, want_monitor_device=True, input_or_output=None, remote=None, xpra_device_name=None):
    """
        choose the device to use
    """
    try:
        from xpra.sound.pulseaudio.pulseaudio_util import has_pa, get_pa_device_options, get_default_sink, get_pulse_server, get_pulse_id
        if not has_pa():
            log.warn("Warning: pulseaudio is not available!")
            return None
    except ImportError as e:
        log.warn("Warning: pulseaudio is not available!")
        log.warn(" %s", e)
        return None
    pa_server = get_pulse_server()
    if remote:
        log("start sound, remote pulseaudio server=%s, local pulseaudio server=%s", remote.pulseaudio_server, pa_server)
        #only worth comparing if we have a real server string
        #one that starts with {UUID}unix:/..
        if pa_server and pa_server.startswith("{") and \
            remote.pulseaudio_server and remote.pulseaudio_server==pa_server:
            log.error("Error: sound is disabled to prevent a sound loop")
            log.error(" identical Pulseaudio server '%s'", pa_server)
            return None
        pa_id = get_pulse_id()
        log("start sound, client id=%s, server id=%s", remote.pulseaudio_id, pa_id)
        if remote.pulseaudio_id and remote.pulseaudio_id==pa_id:
            log.error("Error: sound is disabled to prevent a sound loop")
            log.error(" identical Pulseaudio ID '%s'", pa_id)
            return None

    device_type_str = ""
    if input_or_output is not None:
        device_type_str = ["output", "input"][input_or_output]
    if want_monitor_device:
        device_type_str += " monitor"
    #def get_pa_device_options(monitors=False, input_or_output=None, ignored_devices=["bell-window-system"], log_errors=True)
    devices = get_pa_device_options(want_monitor_device, input_or_output)
    log("found %i pulseaudio %s device%s: %s", len(devices), device_type_str, engs(devices), devices)
    if len(devices)==0:
        log.error("Error: sound forwarding is disabled")
        log.error(" could not detect any Pulseaudio %s devices", device_type_str)
        return None

    #try to match one of the devices using the device name filters:
    if len(devices)>1:
        filters = []
        matches = []
        for match in (device_name_match, PULSEAUDIO_DEVICE_NAME, xpra_device_name):
            if not match:
                continue
            if match!=xpra_device_name:
                filters.append(match)
            match = match.lower()
            matches = dict((k,v) for k,v in devices.items() if k.lower().find(match)>=0 or v.lower().find(match)>=0)
            #log("matches(%s, %s)=%s", devices, match, matches)
            if len(matches)==1:
                log("found name match for '%s': %s", match, matches.items()[0])
                break
            elif len(matches)>1:
                log.warn("Warning: Pulseaudio %s device name filter '%s'", device_type_str, match)
                log.warn(" matched %i devices", len(matches))
        if filters or len(matches)>0:
            if len(matches)==0:
                log.warn("Warning: Pulseaudio %s device name filter%s:", device_type_str, engs(filters))
                log.warn(" %s", csv("'%s'" % x for x in filters))
                log.warn(" did not match any of the devices found:")
                for k,v in devices.items():
                    log.warn(" * '%s'", k)
                    log.warn("   '%s'", v)
                return None
            devices = matches

    #still have too many devices to choose from?
    if len(devices)>1:
        if want_monitor_device:
            #use the monitor of the default sink if we find it:
            default_sink = get_default_sink()
            default_monitor = default_sink+".monitor"
            if default_monitor in devices:
                device_name = devices.get(default_monitor)
                log.info("using monitor of default sink: %s", device_name)
                return default_monitor

        global WARNED_MULTIPLE_DEVICES
        if not WARNED_MULTIPLE_DEVICES:
            WARNED_MULTIPLE_DEVICES = True
            if not PULSEAUDIO_DEVICE_NAME: #warned already
                dtype = "audio"
                if want_monitor_device:
                    dtype = "output monitor"
                elif input_or_output is False:
                    dtype = "audio input"
                elif input_or_output is True:
                    dtype = "audio output"
                log.warn("Warning: found %i %s devices:", len(devices), dtype)
            for k,v in devices.items():
                log.warn(" * %s", v)
                log.warn("   %s", k)
            if not PULSEAUDIO_DEVICE_NAME: #used already!
                log.warn(" to select a specific one,")
                log.warn(" use the environment variable XPRA_PULSEAUDIO_DEVICE_NAME")
        #default to first one:
        if USE_DEFAULT_DEVICE:
            log.info("using default pulseaudio device")
            return None
    #default to first one:
    device, device_name = devices.items()[0]
    log.info("using pulseaudio device:")
    log.info(" '%s'", device_name)
    return device

def get_pulse_source_defaults(device_name_match=None, want_monitor_device=True, remote=None):
    return get_pulse_defaults(device_name_match, want_monitor_device, input_or_output=not want_monitor_device, remote=remote, xpra_device_name=XPRA_PULSE_SOURCE_DEVICE_NAME)

def get_pulse_sink_defaults():
    return get_pulse_defaults(want_monitor_device=False, input_or_output=False, xpra_device_name=XPRA_PULSE_SINK_DEVICE_NAME)

def get_directsound_source_defaults(device_name_match=None, want_monitor_device=True, remote=None):
    try:
        from win32com.directsound import directsound
    except ImportError as e:
        log.warn("Warning: failed to import directsound")
        log.warn(" %s", e)
        return {}
    try:
        if not want_monitor_device:
            devices = directsound.DirectSoundEnumerate()
            log("DirectSoundEnumerate found %i device%s", len(devices), engs(devices))
        else:
            devices = directsound.DirectSoundCaptureEnumerate()
            log("DirectSoundCaptureEnumerate found %i device%s", len(devices), engs(devices))
        names = []
        if devices:
            for guid, name, mod in devices:
                if mod or guid:
                    log("* %-32s %s : %s", name, mod, guid)
                else:
                    log("* %s", name)
                names.append(name)
            device_name = None
            if device_name_match:
                for name in names:
                    if name.lower().find(device_name_match)>=0:
                        device_name = name
                        break
            if device_name is None:
                for name in names:
                    if name.lower().find("primary")>=0:
                        device_name = name
                        break
            log("best matching %sdevice: %s", ["","capture "][want_monitor_device], device_name)
            if device_name is None and want_monitor_device:
                #we have to choose one because the default device
                #may not be a capture device?
                device_name = names[0]
            if device_name:
                log.info("using directsound %sdevice:", ["","capture "][want_monitor_device])
                log.info(" '%s'", device_name)
                return {
                        "device-name"   : device_name,
                        }
    except Exception as e:
        log.error("Error quering sound devices using %s:", directsound)
        log.error(" %s", e)
    return {}


#a list of functions to call to get the plugin options
#at runtime (so we can perform runtime checks on remote data,
# to avoid sound loops for example)
DEFAULT_SRC_PLUGIN_OPTIONS = {
    "test"                  : get_test_defaults,
    "pulse"                 : get_pulse_source_defaults,
    "direct"                : get_directsound_source_defaults,
    }

DEFAULT_SINK_PLUGIN_OPTIONS = {
    "pulse"                 : get_pulse_sink_defaults,
    }


def format_element_options(options):
    return csv("%s=%s" % (k,v) for k,v in options.items())


def get_sound_source_options(plugin, options_str, device, want_monitor_device, remote):
    """
        Given a plugin (short name), options string and remote info,
        return the options for the plugin given,
        using the dynamic defaults (which may use remote info)
        and applying the options string on top.
    """
    #ie: get_sound_source_options("audiotestsrc", "wave=4,freq=220", {remote_pulseaudio_server=XYZ}):
    #use the defaults as starting point:
    defaults_fn = DEFAULT_SRC_PLUGIN_OPTIONS.get(plugin)
    log("DEFAULT_SRC_PLUGIN_OPTIONS(%s)=%s", plugin, defaults_fn)
    if defaults_fn:
        options = defaults_fn(device, want_monitor_device, remote)
        log("%s%s=%s", defaults_fn, (device, want_monitor_device, remote), options)
        if options is None:
            #means failure
            return None
    else:
        options = {}
        #if we add support for choosing devices in the GUI,
        #this code will then get used:
        if device and plugin in SRC_HAS_DEVICE_NAME:
            #assume the user knows the "device-name"...
            #(since I have no idea where to get the "device" string)
            options["device-name"] = device
    options.update(parse_simple_dict(options_str))
    return options


def parse_sound_source(all_plugins, sound_source_plugin, device, want_monitor_device, remote):
    #format: PLUGINNAME:options
    #ie: test:wave=2,freq=110,volume=0.4
    #ie: pulse:device=device.alsa_input.pci-0000_00_14.2.analog-stereo
    plugin = sound_source_plugin.split(":")[0]
    options_str = (sound_source_plugin+":").split(":",1)[1].rstrip(":")
    simple_str = (plugin).lower().strip()
    if not simple_str:
        #choose the first one from
        options = [x for x in get_source_plugins() if x in all_plugins]
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
    log("parse_sound_source(%s, %s, %s) plugin=%s", all_plugins, sound_source_plugin, remote, gst_sound_source_plugin)
    options = get_sound_source_options(simple_str, options_str, device, want_monitor_device, remote)
    log("get_sound_source_options%s=%s", (simple_str, options_str, remote), options)
    if options is None:
        #means error
        return None, {}
    return gst_sound_source_plugin, options


def loop_warning(mode="speaker", machine_id=""):
    log.warn("Warning: cannot start %s forwarding:", mode)
    log.warn(" user and server environment are identical,")
    log.warn(" this would create a sound loop")
    log.warn(" use XPRA_ALLOW_SOUND_LOOP=1 to force enable it")
    if machine_id:
        log(" '%s'", machine_id)


def main():
    global pygst_version, gst_version, gst_vinfo
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GStreamer-Info", "GStreamer Information"):
        enable_color()
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()
        import_gst()
        print("Loaded Python GStreamer version %s for Python %s.%s" % (gst_vinfo, sys.version_info[0], sys.version_info[1]))
        apn = get_all_plugin_names()
        print("GStreamer plugins found: %s" % csv(apn))
        print("")
        print("GStreamer version: %s" % ".".join([str(x) for x in gst_version]))
        print("PyGStreamer version: %s" % ".".join([str(x) for x in pygst_version]))
        print("")
        encs = [x for x in CODEC_ORDER if has_encoder(x)]
        decs = [x for x in CODEC_ORDER if has_decoder(x)]
        print("encoders:           %s" % csv(encs))
        print("decoders:           %s" % csv(decs))
        print("muxers:             %s" % csv(get_muxers()))
        print("demuxers:           %s" % csv(get_demuxers()))
        print("stream compressors: %s" % csv(get_stream_compressors()))
        print("source plugins:     %s" % csv([x for x in get_source_plugins() if x in apn]))
        print("sink plugins:       %s" % csv([x for x in get_sink_plugins() if x in apn]))
        print("default sink:       %s" % get_default_sink())


if __name__ == "__main__":
    main()
