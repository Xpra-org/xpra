#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os, time
from collections import deque
from threading import Lock

from xpra.sound.sound_pipeline import SoundPipeline, gobject, one_arg_signal
from xpra.sound.gstreamer_util import plugin_str, get_decoder_parser, get_queue_time, normv, get_codecs, get_default_sink, get_sink_plugins, \
                                        MP3, CODEC_ORDER, gst, QUEUE_LEAK, MS_TO_NS

from xpra.scripts.config import InitExit
from xpra.util import updict, csv
from xpra.os_util import thread
from xpra.log import Logger
log = Logger("sound")


SINKS = get_sink_plugins()
DEFAULT_SINK = get_default_sink()

SINK_SHARED_DEFAULT_ATTRIBUTES = {"sync"    : False,
                                  "async"   : True,
                                  "qos"     : True
                                  }

SINK_DEFAULT_ATTRIBUTES = {0 : {
                                "pulsesink"  : {"client" : "Xpra"}
                               },
                           1 : {
                                "pulsesink"  : {"client-name" : "Xpra"}
                               },
                          }

QUEUE_SILENT = 0
QUEUE_TIME = get_queue_time(450)

GRACE_PERIOD = int(os.environ.get("XPRA_SOUND_GRACE_PERIOD", "2000"))
#percentage: from 0 for no margin, to 200% which triples the buffer target
MARGIN = max(0, min(200, int(os.environ.get("XPRA_SOUND_MARGIN", "50"))))

GST_FORMAT_BUFFERS = 4


class SoundSink(SoundPipeline):

    __gsignals__ = SoundPipeline.__generic_signals__.copy()
    __gsignals__.update({
        "eos"       : one_arg_signal,
        })

    def __init__(self, sink_type=None, sink_options={}, codecs=get_codecs(), codec_options={}, volume=1.0):
        if not sink_type:
            sink_type = DEFAULT_SINK
        if sink_type not in SINKS:
            raise InitExit(1, "invalid sink: %s" % sink_type)
        matching = [x for x in CODEC_ORDER if (x in codecs and x in get_codecs())]
        log("SoundSink(..) found matching codecs %s", matching)
        if not matching:
            raise InitExit(1, "no matching codecs between arguments '%s' and supported list '%s'" % (csv(codecs), csv(get_codecs().keys())))
        codec = matching[0]
        decoder, parser = get_decoder_parser(codec)
        SoundPipeline.__init__(self, codec)
        self.sink_type = sink_type
        self.levels = deque(maxlen=100)
        decoder_str = plugin_str(decoder, codec_options)
        pipeline_els = []
        appsrc_el = ["appsrc",
                     "do-timestamp=1",
                     "name=src",
                     "emit-signals=0",
                     "block=0",
                     "is-live=0",
                     "stream-type=stream",
                     "format=%s" % GST_FORMAT_BUFFERS]
        pipeline_els.append(" ".join(appsrc_el))
        pipeline_els.append(parser)
        pipeline_els.append(decoder_str)
        pipeline_els.append("audioconvert")
        pipeline_els.append("audioresample")
        pipeline_els.append("volume name=volume volume=%s" % volume)
        queue_el = ["queue",
                    "name=queue",
                    "min-threshold-time=0",
                    "max-size-buffers=0",
                    "max-size-bytes=0",
                    "max-size-time=%s" % QUEUE_TIME,
                    "leaky=%s" % QUEUE_LEAK]
        if QUEUE_SILENT:
            queue_el.append("silent=%s" % QUEUE_SILENT)
        pipeline_els.append(" ".join(queue_el))
        sink_attributes = SINK_SHARED_DEFAULT_ATTRIBUTES.copy()
        from xpra.sound.gstreamer_util import gst_major_version
        sink_attributes.update(SINK_DEFAULT_ATTRIBUTES.get(gst_major_version, {}).get(sink_type, {}))
        sink_attributes.update(sink_options)
        sink_str = plugin_str(sink_type, sink_attributes)
        pipeline_els.append(sink_str)
        self.setup_pipeline_and_bus(pipeline_els)
        self.volume = self.pipeline.get_by_name("volume")
        self.src    = self.pipeline.get_by_name("src")
        self.queue  = self.pipeline.get_by_name("queue")
        self.overruns = 0
        self.underruns = 0
        self.overrun_events = deque(maxlen=100)
        self.underrun_events = deque(maxlen=100)
        self.queue_state = "starting"
        self.last_underrun = 0
        self.last_overrun = 0
        self.last_max_update = time.time()
        self.level_lock = Lock()
        if QUEUE_SILENT==0:
            self.queue.connect("overrun", self.queue_overrun)
            self.queue.connect("underrun", self.queue_underrun)
            self.queue.connect("running", self.queue_running)
            self.queue.connect("pushing", self.queue_pushing)

    def __repr__(self):
        return "SoundSink('%s' - %s)" % (self.pipeline_str, self.state)

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.sink_type = ""
        self.src = None


    def queue_pushing(self, *args):
        self.queue_state = "pushing"
        self.emit_info()
        return True

    def queue_running(self, *args):
        self.queue_state = "running"
        self.set_min_level()
        self.set_max_level()
        self.emit_info()
        return True

    def queue_underrun(self, *args):
        now = time.time()
        if self.queue_state=="starting" or 1000*(now-self.start_time)<GRACE_PERIOD:
            log("ignoring underrun during startup")
            return
        self.queue_state = "underrun"
        if now-self.last_underrun>2:
            self.last_underrun = now
            self.set_min_level()
            self.underrun_events.append(now)
        self.emit_info()
        return 1

    def get_level_range(self, mintime=2, maxtime=10):
        now = time.time()
        filtered = [v for t,v in list(self.levels) if (now-t)>=mintime and (now-t)<=maxtime]
        if len(filtered)>=10:
            maxl = max(filtered)
            minl = min(filtered)
            #range of the levels recorded:
            return maxl-minl
        return 0

    def set_min_level(self):
        if not self.level_lock.acquire(False):
            return
        try:
            lrange = self.get_level_range()
            if lrange>0:
                cmtt = self.queue.get_property("min-threshold-time")//MS_TO_NS
                #from 100% down to 0% in 2 seconds after underrun:
                now = time.time()
                pct = max(0, int((self.last_underrun+2-now)*50))
                mtt = min(50, pct*max(50, lrange)//200)
                log("set_min_level pct=%2i, cmtt=%3i, mtt=%3i", pct, cmtt, mtt)
                if cmtt!=mtt:
                    self.queue.set_property("min-threshold-time", mtt*MS_TO_NS)
                    log("set_min_level min-threshold-time=%s", mtt)
        finally:
            self.level_lock.release()

    def set_max_level(self, force=False):
        if not self.level_lock.acquire(False):
            return
        try:
            lrange = self.get_level_range(mintime=0)
            now = time.time()
            log("set_max_level lrange=%3i, last_max_update=%is", lrange, int(now-self.last_max_update))
            #more than one second since last update and we have a range:
            if now-self.last_max_update>1 and lrange>0:
                cmst = self.queue.get_property("max-size-time")//MS_TO_NS
                #overruns in the last minute:
                olm = len([x for x in list(self.overrun_events) if now-x<60])
                #increase target if we have more than 5 overruns in the last minute:
                target_mst = lrange*(100 + MARGIN + min(100, olm*20))//100
                #from 100% down to 0% in 2 seconds after underrun:
                pct = max(0, int((self.last_overrun+2-now)*50))
                #use this last_overrun percentage value to temporarily decrease the target
                #(causes overruns that drop packets and lower the buffer level)
                target_mst = max(50, int(target_mst - pct*lrange//100))
                mst = (cmst + target_mst)//2
                #cap it at 1 second:
                mst = min(mst, 1000)
                log("set_max_level overrun count=%-2i, margin=%3i, pct=%2i, cmst=%3i, mst=%3i", olm, MARGIN, pct, cmst, mst)
                if force or abs(cmst-mst)>=max(50, lrange//2):
                    self.queue.set_property("max-size-time", mst*MS_TO_NS)
                    self.last_max_update = now
        finally:
            self.level_lock.release()

    def queue_overrun(self, *args):
        now = time.time()
        if self.queue_state=="starting" or 1000*(now-self.start_time)<GRACE_PERIOD:
            log("ignoring overrun during startup")
            return
        clt = self.queue.get_property("current-level-time")//MS_TO_NS
        log("overrun level=%ims", clt)
        now = time.time()
        #grace period of recording overruns:
        #(because when we record an overrun, we lower the max-time,
        # which causes more overruns!)
        if self.last_overrun is None or now-self.last_overrun>2:
            self.last_overrun = now
            self.set_max_level()
            self.overrun_events.append(now)
        self.overruns += 1
        return 1

    def eos(self):
        log("eos()")
        if self.src:
            self.src.emit('end-of-stream')
        self.cleanup()
        return 0

    def get_info(self):
        info = SoundPipeline.get_info(self)
        if QUEUE_TIME>0:
            clt = self.queue.get_property("current-level-time")
            qmax = self.queue.get_property("max-size-time")
            qmin = self.queue.get_property("min-threshold-time")
            updict(info, "queue", {
                "min"           : qmin//MS_TO_NS,
                "max"           : qmax//MS_TO_NS,
                "cur"           : clt//MS_TO_NS,
                "pct"           : min(QUEUE_TIME, clt)*100//qmax,
                "overruns"      : self.overruns,
                "underruns"     : self.underruns,
                "state"         : self.queue_state})
        return info

    def add_data(self, data, metadata=None):
        if not self.src:
            log("add_data(..) dropped")
            return
        #having a timestamp causes problems with the queue and overruns:
        log("add_data(%s bytes, %s) queue_state=%s", len(data), metadata, self.queue_state)
        buf = gst.new_buffer(data)
        if metadata:
            #having a timestamp causes problems with the queue and overruns:
            #ts = metadata.get("timestamp")
            #if ts is not None:
            #    buf.timestamp = normv(ts)
            d = metadata.get("duration")
            if d is not None:
                d = normv(d)
                if d>0:
                    buf.duration = normv(d)
        if self.push_buffer(buf):
            self.buffer_count += 1
            self.byte_count += len(data)
            clt = self.queue.get_property("current-level-time")//MS_TO_NS
            log("pushed %5i bytes, new buffer level: %3ims, queue state=%s", len(data), clt, self.queue_state)
            self.levels.append((time.time(), clt))
            if self.queue_state=="pushing":
                self.set_min_level()
                self.set_max_level()
        self.emit_info()

    def push_buffer(self, buf):
        #buf.size = size
        #buf.timestamp = timestamp
        #buf.duration = duration
        #buf.offset = offset
        #buf.offset_end = offset_end
        #buf.set_caps(gst.caps_from_string(caps))
        r = self.src.emit("push-buffer", buf)
        if r!=gst.FLOW_OK:
            log.error("push-buffer error: %s", r)
            self.emit('error', "push-buffer error: %s" % r)
            return 0
        return 1

gobject.type_register(SoundSink)


def main():
    from xpra.platform import init, clean
    init("Sound-Record")
    try:
        from xpra.gtk_common.gobject_compat import import_glib
        glib = import_glib()
        args = sys.argv
        log.enable_debug()
        import os.path
        if len(args) not in (2, 3):
            print("usage: %s [-v|--verbose] filename [codec]" % sys.argv[0])
            return 1
        filename = args[1]
        if not os.path.exists(filename):
            print("file %s does not exist" % filename)
            return 2
        codecs = get_codecs()
        if len(args)==3:
            codec = args[2]
            if codec not in codecs:
                print("invalid codec: %s" % codec)
                return 2
        else:
            codec = None
            parts = filename.split(".")
            if len(parts)>1:
                extension = parts[-1]
                if extension.lower() in codecs:
                    codec = extension.lower()
                    print("guessed codec %s from file extension %s" % (codec, extension))
            if codec is None:
                print("assuming this is an mp3 file...")
                codec = MP3

        log.enable_debug()
        with open(filename, "rb") as f:
            data = f.read()
        print("loaded %s bytes from %s" % (len(data), filename))
        #force no leak since we push all the data at once
        global QUEUE_LEAK, GST_QUEUE_NO_LEAK, QUEUE_SILENT
        QUEUE_LEAK = GST_QUEUE_NO_LEAK
        QUEUE_SILENT = 1
        ss = SoundSink(codec=codec)
        ss.add_data(data)
        def eos(*args):
            print("eos")
            glib.idle_add(glib_mainloop.quit)
        ss.connect("eos", eos)
        ss.start()

        glib_mainloop = glib.MainLoop()

        import signal
        def deadly_signal(*args):
            glib.idle_add(glib_mainloop.quit)
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)

        def check_for_end(*args):
            qtime = ss.queue.get_property("current-level-time")//MS_TO_NS
            if qtime<=0:
                log.info("underrun (end of stream)")
                thread.start_new_thread(ss.stop, ())
                glib.timeout_add(500, glib_mainloop.quit)
                return False
            return True
        glib.timeout_add(1000, check_for_end)

        glib_mainloop.run()
        return 0
    finally:
        clean()


if __name__ == "__main__":
    sys.exit(main())
