# This file is part of Xpra.
# Copyright (C) 2015-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.sound.gstreamer_util import parse_sound_source, get_source_plugins, get_sink_plugins, get_default_sink, get_default_source, \
                            import_gst, format_element_options, \
                            can_decode, can_encode, get_muxers, get_demuxers, get_all_plugin_names
from xpra.net.subprocess_wrapper import subprocess_caller, subprocess_callee, exec_kwargs, exec_env
from xpra.platform.paths import get_sound_command
from xpra.os_util import WIN32, OSX, POSIX, monotonic_time
from xpra.util import AdHocStruct, typedict, parse_simple_dict, envint, envbool
from xpra.scripts.config import InitExit, InitException
from xpra.log import Logger
log = Logger("sound")

DEBUG_SOUND = envbool("XPRA_SOUND_DEBUG", False)
SUBPROCESS_DEBUG = [x.strip() for x in os.environ.get("XPRA_SOUND_SUBPROCESS_DEBUG", "").split(",") if x.strip()]
FAKE_START_FAILURE = envbool("XPRA_SOUND_FAKE_START_FAILURE", False)
FAKE_EXIT = envbool("XPRA_SOUND_FAKE_EXIT", False)
FAKE_CRASH = envbool("XPRA_SOUND_FAKE_CRASH", False)
SOUND_START_TIMEOUT = envint("XPRA_SOUND_START_TIMEOUT", 3000)
BUNDLE_METADATA = envbool("XPRA_SOUND_BUNDLE_METADATA", True)


def get_sound_wrapper_env():
    env = {}
    if WIN32:
        #disable bencoder to skip warnings with the py3k Sound subapp
        env["XPRA_USE_BENCODER"] = "0"
    elif POSIX and not OSX:
        try:
            from xpra.sound.pulseaudio.pulseaudio_util import add_audio_tagging_env
            add_audio_tagging_env(env)
        except ImportError as e:
            log.warn("Warning: failed to set pulseaudio tagging:")
            log.warn(" %s", e)
    return env


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
        methods = method_whitelist+["set_volume", "cleanup"]
        exports = ["state-changed", "info", "error"] + exports_list
        subprocess_callee.__init__(self, wrapped_object=wrapped_object, method_whitelist=methods)
        for x in exports:
            self.connect_export(x)

    def start(self):
        if not FAKE_START_FAILURE:
            self.idle_add(self.wrapped_object.start)
        if FAKE_EXIT>0:
            def process_exit():
                self.cleanup()
                self.timeout_add(250, self.stop)
            self.timeout_add(FAKE_EXIT*1000, process_exit)
        if FAKE_CRASH>0:
            def force_exit():
                sys.exit(1)
            self.timeout_add(FAKE_CRASH*1000, force_exit)
        subprocess_callee.start(self)

    def cleanup(self):
        wo = self.wrapped_object
        log("cleanup() wrapped object=%s", wo)
        if wo:
            #this will stop the sound pipeline:
            self.wrapped_object = None
            wo.cleanup()
        self.timeout_add(1000, self.do_stop)

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
        sound_subprocess.__init__(self, sound_pipeline, ["add_data"], [])


def run_sound(mode, error_cb, options, args):
    """ this function just parses command line arguments to feed into the sound subprocess class,
        which in turn just feeds them into the sound pipeline class (sink.py or src.py)
    """
    from xpra.gtk_common.gobject_compat import want_gtk3
    want_gtk3(True)
    gst = import_gst()
    if not gst:
        return 1
    info = mode.replace("_sound_", "")  #ie: "_sound_record" -> "record"
    from xpra.platform import program_context
    with program_context("Xpra-Audio-%s" % info, "Xpra Audio %s" % info):
        log("run_sound(%s, %s, %s, %s) gst=%s", mode, error_cb, options, args, gst)
        if mode=="_sound_record":
            subproc = sound_record
        elif mode=="_sound_play":
            subproc = sound_play
        elif mode=="_sound_query":
            plugins = get_all_plugin_names()
            sources = [x for x in get_source_plugins() if x in plugins]
            sinks = [x for x in get_sink_plugins() if x in plugins]
            from xpra.sound.gstreamer_util import gst_version, pygst_version
            import struct
            bits = struct.calcsize("P")*8
            d = {
                 "encoders"         : can_encode(),
                 "decoders"         : can_decode(),
                 "sources"          : sources,
                 "source.default"   : get_default_source() or "",
                 "sinks"            : sinks,
                 "sink.default"     : get_default_sink() or "",
                 "muxers"           : get_muxers(),
                 "demuxers"         : get_demuxers(),
                 "gst.version"      : [int(x) for x in gst_version],
                 "pygst.version"    : pygst_version,
                 "plugins"          : plugins,
                 "python.version"   : sys.version_info[:3],
                 "python.bits"      : bits,
                }
            if BUNDLE_METADATA:
                d["bundle-metadata"] = True
            for k,v in d.items():
                if type(v) in (list, tuple):
                    v = ",".join(str(x) for x in v)
                print("%s=%s" % (k, v))
            return 0
        else:
            log.error("unknown mode: %s" % mode)
            return 1
        assert len(args)>=6, "not enough arguments"

        #the plugin to use (ie: 'pulsesrc' for src.py or 'autoaudiosink' for sink.py)
        plugin = args[2]
        #plugin options (ie: "device=monitor_device,something=value")
        options = parse_simple_dict(args[3])
        #codecs:
        codecs = [x.strip() for x in args[4].split(",")]
        #codec options:
        codec_options = parse_simple_dict(args[5])
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
        except InitExit as e:
            log.error("%s: %s", info, e)
            return e.status
        except InitException as e:
            log.error("%s: %s", info, e)
            return 1
        except Exception:
            log.error("run_sound%s error", (mode, error_cb, options, args), exc_info=True)
            return 1
        finally:
            if ss:
                ss.stop()


def _add_debug_args(command):
    from xpra.log import debug_enabled_categories
    debug = SUBPROCESS_DEBUG[:]
    for f in ("sound", "gstreamer"):
        if (DEBUG_SOUND or f in debug_enabled_categories) and (f not in debug):
            debug.append(f)
    if debug:
        #forward debug flags:
        command += ["-d", ",".join(debug)]


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
        self.info = {}
        #hook some default packet handlers:
        self.connect("state-changed", self.state_changed)
        self.connect("info", self.info_update)
        self.connect("signal", self.subprocess_signal)

    def get_env(self):
        env = subprocess_caller.get_env(self)
        env.update(get_sound_wrapper_env())
        return env

    def start(self):
        self.state = "starting"
        subprocess_caller.start(self)
        log("start() %s subprocess(%s)=%s", self.description, self.command, self.process.pid)
        self.timeout_add(SOUND_START_TIMEOUT, self.verify_started)


    def cleanup(self):
        log("cleanup() sending cleanup request to %s", self.description)
        self.send("cleanup")
        #cleanup should cause the process to exit
        self.timeout_add(500, self.send, "stop")
        self.timeout_add(1000, self.send, "exit")
        self.timeout_add(1500, self.stop)


    def verify_started(self):
        p = self.process
        log("verify_started() process=%s, info=%s, codec=%s", p, self.info, self.codec)
        if p is None or p.poll() is not None:
            #process has terminated already
            return
        #if we don't get an "info" packet, then the pipeline must have failed to start
        if not self.info:
            log.warn("Warning: the %s process has failed to start", self.description)
            self.cleanup()


    def subprocess_signal(self, wrapper, proc):
        log("subprocess_signal: %s", proc)
        #call via idle_add to prevent deadlocks on win32!
        self.idle_add(self.stop_protocol)


    def state_changed(self, wrapper, new_state):
        self.state = new_state

    def get_state(self):
        return self.state


    def get_info(self):
        return self.info

    def info_update(self, wrapper, info):
        log("info_update: %s", info)
        self.info.update(info)
        self.info["time"] = int(monotonic_time())
        p = self.process
        if p and not p.poll():
            self.info["pid"] = p.pid
        self.codec_description = info.get("codec_description")


    def set_volume(self, v):
        self.send("set_volume", int(v*100))

    def get_volume(self):
        return self.info.get("volume", 100)/100.0


class source_subprocess_wrapper(sound_subprocess_wrapper):

    def __init__(self, plugin, options, codecs, volume, element_options):
        sound_subprocess_wrapper.__init__(self, "sound source")
        self.large_packets = ["new-buffer"]
        self.command = get_sound_command()+["_sound_record", "-", "-", plugin or "", format_element_options(element_options), ",".join(codecs), "", str(volume)]
        _add_debug_args(self.command)

    def __repr__(self):
        try:
            return "source_subprocess_wrapper(%s)" % self.process.pid
        except:
            return "source_subprocess_wrapper(%s)" % self.process


class sink_subprocess_wrapper(sound_subprocess_wrapper):

    def __init__(self, plugin, options, codec, volume, element_options):
        sound_subprocess_wrapper.__init__(self, "sound output")
        self.large_packets = ["add_data"]
        self.codec = codec
        self.command = get_sound_command()+["_sound_play", "-", "-", plugin or "", format_element_options(element_options), codec, "", str(volume)]
        _add_debug_args(self.command)

    def add_data(self, data, metadata={}, packet_metadata=()):
        if DEBUG_SOUND:
            log("add_data(%s bytes, %s, %s) forwarding to %s", len(data), metadata, len(packet_metadata), self.protocol)
        #theoretically, the sound process could be a different version,
        #so don't add the extra packet_metadata argument unless we know we actually want it:
        if packet_metadata:
            self.send("add_data", data, dict(metadata), packet_metadata)
        else:
            self.send("add_data", data, dict(metadata))

    def __repr__(self):
        try:
            return "sink_subprocess_wrapper(%s)" % self.process.pid
        except:
            return "sink_subprocess_wrapper(%s)" % self.process


def start_sending_sound(plugins, sound_source_plugin, device, codec, volume, want_monitor_device, remote_decoders, remote_pulseaudio_server, remote_pulseaudio_id):
    log("start_sending_sound%s", (plugins, sound_source_plugin, device, codec, volume, want_monitor_device, remote_decoders, remote_pulseaudio_server, remote_pulseaudio_id))
    try:
        #info about the remote end:
        remote = AdHocStruct()
        remote.pulseaudio_server = remote_pulseaudio_server
        remote.pulseaudio_id = remote_pulseaudio_id
        remote.remote_decoders = remote_decoders
        plugin, options = parse_sound_source(plugins, sound_source_plugin, device, want_monitor_device, remote)
        if not plugin:
            log.error("failed to setup '%s' sound stream source", (sound_source_plugin or "auto"))
            return  None
        log("parsed '%s':", sound_source_plugin)
        log("plugin=%s", plugin)
        log("options=%s", options)
        return source_subprocess_wrapper(plugin, options, remote_decoders, volume, options)
    except Exception as e:
        log.error("error setting up sound: %s", e, exc_info=True)
        return None


def start_receiving_sound(codec):
    log("start_receiving_sound(%s)", codec)
    try:
        return sink_subprocess_wrapper(None, {}, codec, 1.0, {})
    except:
        log.error("failed to start sound sink", exc_info=True)
        return None

def query_sound():
    import subprocess
    command = get_sound_command()+["_sound_query"]
    _add_debug_args(command)
    kwargs = exec_kwargs()
    env = exec_env()
    env.update(get_sound_wrapper_env())
    log("query_sound() command=%s, env=%s, kwargs=%s", command, env, kwargs)
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, **kwargs)
    out, err = proc.communicate(None)
    log("query_sound() process returned %s", proc.returncode)
    log("query_sound() out=%s, err=%s", out, err)
    if proc.returncode!=0:
        return typedict()
    d = typedict()
    for x in out.decode("utf8").splitlines():
        kv = x.split("=", 1)
        if len(kv)==2:
            #ie: kv = ["decoders", "mp3,vorbis"]
            k,v = kv
            #fugly warning: all the other values are lists.. but this one is not:
            if k!="python.bits":
                v = [x.encode() for x in v.split(",")]
            #d["decoders"] = ["mp3", "vorbis"]
            d[k.encode()] = v
    log("query_sound()=%s", d)
    return d
