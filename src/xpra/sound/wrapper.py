# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.net.subprocess_wrapper import subprocess_caller, subprocess_callee, gobject
from xpra.platform.paths import get_sound_executable
from xpra.util import AdHocStruct
from xpra.log import Logger
log = Logger("sound")

DEBUG_SOUND = os.environ.get("XPRA_SOUND_DEBUG", "0")=="1"
SUBPROCESS_DEBUG = os.environ.get("XPRA_SOUND_SUBPROCESS_DEBUG", "").split(",")
FAKE_OVERRUN = int(os.environ.get("XPRA_FAKE_OVERRUN", "0"))


#this wrapper takes care of launching src.py or sink.py
#
#the command line should look something like:
# xpra MODE IN OUT PLUGIN PLUGIN_OPTIONS CODECS CODEC_OPTIONS VOLUME
# * MODE can be _sound_record or _sound_play
# * IN is where we read the encoded commands from, specify "-" for stdin
# * OUT is where we write the encoded output stream, specify "-" for stdout
# * PLUGIN is the sound source (for recording) or sink (for playing) to use, can be omitted (will be auto detected)
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

class sound_subprocess(subprocess_callee):
    """ Utility superclass for sound subprocess wrappers
        (see sound_record and sound_play below)
    """
    def __init__(self, wrapped_object, method_whitelist, exports_list):
        #add bits common to both record and play:
        methods = method_whitelist+["set_volume", "stop", "cleanup"]
        exports = ["state-changed", "info", "error"] + exports_list
        subprocess_callee.__init__(self, wrapped_object=wrapped_object, method_whitelist=methods)
        for x in exports:
            self.connect_export(x)

    def start(self):
        gobject.idle_add(self.wrapped_object.start)
        subprocess_callee.start(self)

    def stop(self):
        wo = self.wrapped_object
        log("stop() wrapped object=%s", wo)
        if wo:
            #this will stop the sound pipeline:
            self.wrapped_object = None
            wo.cleanup()
        #this will stop the protocol and main loop
        #so call it with a delay so the sound pipeline can shutdown cleanly
        gobject.timeout_add(250, subprocess_callee.stop, self)

    def export_info(self):
        wo = self.wrapped_object
        if wo:
            self.send("info", wo.get_info())
        return wo is not None


class sound_record(sound_subprocess):
    """ wraps SoundSource as a subprocess """
    def __init__(self, *pipeline_args):
        from xpra.sound.src import SoundSource
        sound_pipeline = SoundSource(*pipeline_args)
        sound_subprocess.__init__(self, sound_pipeline, [], ["new-stream", "new-buffer"])
        self.large_packets = ["new-buffer"]

class sound_play(sound_subprocess):
    """ wraps SoundSink as a subprocess """
    def __init__(self, *pipeline_args):
        from xpra.sound.sink import SoundSink
        sound_pipeline = SoundSink(*pipeline_args)
        sound_subprocess.__init__(self, sound_pipeline, ["add_data"], ["underrun", "overrun"])
        if FAKE_OVERRUN>0:
            def fake_overrun(*args):
                wo = self.wrapped_object
                if wo:
                    wo.emit("overrun", 500)
            gobject.timeout_add(FAKE_OVERRUN*1000, fake_overrun)


def run_sound(mode, error_cb, options, args):
    """ this function just parses command line arguments to feed into the sound subprocess class,
        which in turn just feeds them into the sound pipeline class (sink.py or src.py)
    """
    assert len(args)>=6, "not enough arguments"
    if mode=="_sound_record":
        subproc = sound_record
    elif mode=="_sound_play":
        subproc = sound_play
    else:
        raise Exception("unknown mode: %s" % mode)

    #the plugin to use (ie: 'pulsesrc' for src.py or 'autoaudiosink' for sink.py)
    plugin = args[2]
    #plugin options (ie: "device=monitor_device,something=value")
    from xpra.sound.gstreamer_util import parse_element_options
    options = parse_element_options(args[3])
    #codecs:
    codecs = [x.strip() for x in args[4].split(",")]
    #codec options:
    codec_options = parse_element_options(args[5])
    #volume (optional):
    try:
        volume = int(args[6])
    except:
        volume = 1.0

    ss = None
    try:
        ss = subproc(plugin, options, codecs, codec_options, volume)
        ss.start()
        return 0
    except Exception:
        log.error("run_sound%s error", (mode, error_cb, options, args), exc_info=True)
        return 1
    finally:
        if ss:
            ss.stop()


class sound_subprocess_wrapper(subprocess_caller):
    """ This utility superclass deals with the caller side of the sound subprocess wrapper:
        * starting the wrapper subprocess
        * handling state-changed signal so we have a local copy of the current value ready
        * handle "info" packets so we have a cached copy
        * forward get/set volume calls (get_volume uses the value found in "info")
    """
    def __init__(self, description):
        subprocess_caller.__init__(self, description)
        self.state = "stopped"
        self.codec = "unknown"
        self.codec_description = ""
        self.last_info = {}
        #hook some default packet handlers:
        self.connect("state-changed", self.state_changed)
        self.connect("info", self.info_update)
        self.connect("signal", self.subprocess_signal)


    def cleanup(self):
        log("cleanup() sending cleanup request to %s", self.description)
        self.send("cleanup")
        #cleanup should cause the process to exit
        gobject.timeout_add(500, self.stop)


    def subprocess_signal(self, wrapper, proc):
        log("subprocess_signal: %s", proc)
        self.stop_protocol()


    def state_changed(self, wrapper, new_state):
        self.state = new_state

    def get_state(self):
        return self.state


    def get_info(self):
        return self.last_info

    def info_update(self, wrapper, info):
        log("info_update: %s", info)
        self.last_info = info
        self.last_info["time"] = int(time.time())
        self.codec_description = info.get("codec_description")


    def set_volume(self, v):
        self.send("set_volume", int(v*100))

    def get_volume(self):
        return self.last_info.get("volume", 100)/100.0


    def _add_debug_args(self):
        from xpra.log import debug_enabled_categories
        debug = SUBPROCESS_DEBUG[:]
        if (DEBUG_SOUND or "sound" in debug_enabled_categories) and ("sound" not in debug):
            debug.append("sound")
        if debug:
            #forward debug flags:
            self.command += ["-d", ",".join(debug)]

class source_subprocess_wrapper(sound_subprocess_wrapper):

    def __init__(self, plugin, options, codecs, volume, element_options):
        sound_subprocess_wrapper.__init__(self, "sound-source")
        self.large_packets = ["new-buffer"]
        self.command = [get_sound_executable(), "_sound_record", "-", "-", plugin or "", "", ",".join(codecs), "", str(volume)]
        self._add_debug_args()

    def __repr__(self):
        return "source_subprocess_wrapper(%s)" % self.process


class sink_subprocess_wrapper(sound_subprocess_wrapper):

    def __init__(self, plugin, options, codec, volume, element_options):
        sound_subprocess_wrapper.__init__(self, "sound-sink")
        self.large_packets = ["add_data"]
        self.codec = codec
        self.command = [get_sound_executable(), "_sound_play", "-", "-", plugin or "", "", codec, "", str(volume)]
        self._add_debug_args()

    def add_data(self, data, metadata):
        if DEBUG_SOUND:
            log("add_data(%s bytes, %s) forwarding to %s", len(data), metadata, self.protocol)
        self.send("add_data", data, dict(metadata))

    def __repr__(self):
        return "sink_subprocess_wrapper(%s)" % self.process


def start_sending_sound(sound_source_plugin, codec, volume, remote_decoders, remote_pulseaudio_server, remote_pulseaudio_id):
    log("start_sending_sound%s", (sound_source_plugin, codec, volume, remote_decoders, remote_pulseaudio_server, remote_pulseaudio_id))
    from xpra.sound.gstreamer_util import has_gst, parse_sound_source
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
        return source_subprocess_wrapper(plugin, options, remote_decoders, volume, {})
    except Exception as e:
        log.error("error setting up sound: %s", e, exc_info=True)
        return None


def start_receiving_sound(codec):
    log("start_receiving_sound(%s)", codec)
    try:
        return sink_subprocess_wrapper(None, {}, codec, {}, 1.0)
    except:
        log.error("failed to start sound sink", exc_info=True)
        return None
