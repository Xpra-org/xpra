# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
import time
import subprocess

import gobject
gobject.threads_init()

from xpra.platform.paths import get_sound_executable
from xpra.os_util import Queue, setbinarymode
from xpra.util import AdHocStruct
from xpra.log import Logger
log = Logger("sound")
DEBUG_SOUND = os.environ.get("XPRA_SOUND_DEBUG", "0")=="1"
SUBPROCESS_DEBUG = os.environ.get("XPRA_SOUND_SUBPROCESS_DEBUG", "").split(",")
EXPORT_INFO_TIME = int(os.environ.get("XPRA_SOUND_INFO_TIME", "1000"))


#this wrapper takes care of launching src.py or sink.py
#wrapped so that we can interact with them using a standard xpra protocol layer
#it is generic enough to be used with other processes
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

#to make it possible to inspect files (more human readable):
HEXLIFY_PACKETS = os.environ.get("XPRA_HEXLIFY_PACKETS", "0")=="1"
#use a packet encoder on the data:
ENCODE_PACKETS = os.environ.get("XPRA_ENCODE_PACKETS", "1")=="1"


#by default we just print the exported signals:
def printit(*args):
    log.info("export %s", [str(x)[:128] for x in args])

export_callback = printit
    
def export(*args):
    global export_callback
    signame = args[-1]
    data = args[1:-1]
    export_callback(*([signame] + list(data)))


def run_sound(mode, error_cb, options, args):
    assert len(args)>=6, "not enough arguments"
    mainloop = gobject.MainLoop()

    #common to both sink and src:
    signal_handlers = {
        "state-changed"     : export,
        "bitrate-changed"   : export,
        "error"             : export,
        "new-stream"        : export,
       }
    #these definitions should probably be introspected somehow:
    #(to make it more generic / abstracted)
    functions = ["set_volume", "stop"]
    if mode=="_sound_record":
        from xpra.sound.src import SoundSource
        gst_wrapper = SoundSource
        signal_handlers["new-buffer"] = export
    elif mode=="_sound_play":
        from xpra.sound.sink import SoundSink
        gst_wrapper = SoundSink
        def eos(*args):
            gobject.idle_add(mainloop.quit)
        signal_handlers["eos"] = eos
        signal_handlers["underrun"] = export
        signal_handlers["overrun"] = export
        functions += ["add_data"]
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

    #figure out where we read from and write to:
    input_filename = args[0]
    if input_filename=="-":
        #disable stdin buffering:
        _input = os.fdopen(sys.stdin.fileno(), 'r', 0)
        setbinarymode(_input.fileno())
    else:
        _input = open(input_filename, 'rb')
    output_filename = args[1]
    if output_filename=="-":
        #disable stdout buffering:
        _output = os.fdopen(sys.stdout.fileno(), 'w', 0)
        setbinarymode(_output.fileno())
    else:
        _output = open(output_filename, 'wb')

    try:
        pipeline = gst_wrapper(plugin, options, codecs, codec_options, volume)

        def stop():
            pipeline.cleanup()
            mainloop.quit()

        def handle_signal(*args):
            gobject.idle_add(stop)

        if ENCODE_PACKETS:
            from xpra.net.bytestreams import TwoFileConnection
            conn = TwoFileConnection(_output, _input, abort_test=None, target=mode, info=mode, close_cb=stop)
            conn.timeout = 0
            from xpra.net.protocol import Protocol
            def process_packet(proto, packet):
                #log("process_packet(%s, %s)", proto, str(packet)[:128])
                command = packet[0]
                if command==Protocol.CONNECTION_LOST:
                    log("connection-lost: %s, terminating", packet[1:])
                    stop()
                    return
                method = getattr(pipeline, command, None)
                if not method:
                    log.warn("unknown command: %s", command)
                    return
                if DEBUG_SOUND:
                    log("calling %s.%s%s", pipeline, command, str(tuple(packet[1:]))[:128])
                gobject.idle_add(method, *packet[1:])

            queue = Queue()
            def get_packet_cb():
                try:
                    item = queue.get(False)
                except:
                    item = None
                return (item, None, None, queue.qsize()>0)
            protocol = Protocol(gobject, conn, process_packet, get_packet_cb=get_packet_cb)
            protocol.large_packets = ["new-buffer"]
            try:
                protocol.enable_encoder("rencode")
            except Exception as e:
                log.warn("failed to enable rencode: %s", e)
            protocol.enable_compressor("none")
            protocol.start()
            global export_callback
            def send_via_protocol(*args):
                if HEXLIFY_PACKETS:
                    import binascii
                    args = args[:1]+[binascii.hexlify(str(x)[:32]) for x in args[1:]]
                log("send_via_protocol: adding '%s' message (%s items already in queue)", args[0], queue.qsize())
                queue.put(args)
                protocol.source_has_more()
            export_callback = send_via_protocol
            #export signal before shutting down:
            from xpra.os_util import SIGNAMES
            def handle_signal(sig, frame):
                signame = SIGNAMES.get(sig, sig)
                log("handle_signal(%s, %s)", signame, frame)
                send_via_protocol("signal", signame)
                #give time for the network layer to send the signal
                time.sleep(0.1)
                stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        for x,handler in signal_handlers.items():
            log("registering signal %s", x)
            pipeline.connect(x, handler, x)

        if EXPORT_INFO_TIME>0:
            def export_info():
                send_via_protocol("info", pipeline.get_info())
            gobject.timeout_add(EXPORT_INFO_TIME, export_info)

        gobject.idle_add(pipeline.start)
        mainloop.run()
        return 0
    except Exception as e:
        log.error("run_sound%s error", (mode, error_cb, options, args), exc_info=True)
        return 1
    finally:
        if _input!=sys.stdin:
            try:
                _input.close()
            except:
                pass
        if _output!=sys.stdout:
            try:
                _output.close()
            except:
                pass


class sound_subprocess_wrapper(object):

    def __init__(self):
        self.state = "stopped"
        self.codec = "unknown"
        self.codec_description = ""
        self.process = None
        self.protocol = None
        self.command = None
        self.send_queue = Queue()
        self.signal_callbacks = {}
        self.last_info = {}
        #hook some default packet handlers:
        from xpra.net.protocol import Protocol
        self.connect("state-changed", self.state_changed)
        self.connect("info", self.info_update)
        self.connect(Protocol.CONNECTION_LOST, self.connection_lost)
        

    def state_changed(self, sink, new_state):
        self.state = new_state

    def get_state(self):
        return self.state

    def get_info(self):
        return self.last_info

    def info_update(self, sink, info):
        self.last_info = info
        self.last_info["time"] = int(time.time())
        self.codec_description = info.get("codec_description")

    def set_volume(self, v):
        self.send("set_volume", int(v*100))

    def get_volume(self):
        return self.last_info.get("volume", 100)/100.0



    def start(self):
        log("starting sound source using %s", self.command)
        kwargs = {}
        if os.name=="posix":
            kwargs["close_fds"] = True
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr.fileno(), **kwargs)
        #make a connection using the process stdin / stdout
        from xpra.net.bytestreams import TwoFileConnection
        def sound_process_exit():
            log("sound_process_exit()")
        conn = TwoFileConnection(self.process.stdin, self.process.stdout, abort_test=None, target="sound", info="sound", close_cb=sound_process_exit)
        conn.timeout = 0
        from xpra.net.protocol import Protocol
        self.protocol = Protocol(gobject, conn, self.process_packet, get_packet_cb=self.get_packet)
        self.protocol.large_packets = ["new-buffer", "add_data"]
        self.protocol.enable_encoder("rencode")
        self.protocol.enable_compressor("none")
        self.protocol.start()


    def cleanup(self):
        #TODO: rename in callers?
        self.stop()

    def stop(self):
        log("%s.stop()", self)
        if self.process:
            try:
                self.process.terminate()
                self.protocol.close()
            except Exception as e:
                log.warn("failed to stop sound process %s: %s", self.process, e)

    def connection_lost(self, *args):
        log("connection_lost%s", args)
        self.stop()

    def get_packet(self):
        try:
            item = self.send_queue.get(False)
        except:
            item = None
        return (item, None, None, self.send_queue.qsize()>0)

    def send(self, *packet_data):
        assert self.protocol
        self.send_queue.put(packet_data)
        self.protocol.source_has_more()

    def process_packet(self, proto, packet):
        if DEBUG_SOUND:
            log("process_packet(%s, %s)", proto, [str(x)[:32] for x in packet])
        command = packet[0]
        callbacks = self.signal_callbacks.get(command)
        log("process_packet callbacks(%s)=%s", command, callbacks)
        if callbacks:
            for cb, args in callbacks:
                try:
                    all_args = list(packet[1:]) + args
                    cb(self, *all_args)
                except Exception as e:
                    log.error("error processing callback %s for %s packet: %s", cb, command, e, exc_info=True)

    def connect(self, signal, cb, *args):
        self.signal_callbacks.setdefault(signal, []).append((cb, list(args)))

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
        sound_subprocess_wrapper.__init__(self)
        self.command = [get_sound_executable(), "_sound_record", "-", "-", plugin or "", "", ",".join(codecs), "", str(volume)]
        self._add_debug_args()

    def __repr__(self):
        return "source_subprocess_wrapper(%s)" % self.process


class sink_subprocess_wrapper(sound_subprocess_wrapper):

    def __init__(self, plugin, options, codec, volume, element_options):
        sound_subprocess_wrapper.__init__(self)
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
