# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Todo:
#   xsync resize stuff
#   shape?
#   any other interesting metadata? _NET_WM_TYPE, WM_TRANSIENT_FOR, etc.?

import gtk.gdk
gtk.gdk.threads_init()

import gobject
import cairo
import sys
import hmac
import uuid
try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport
import os
import time
import ctypes
from threading import Thread, Lock
try:
    from queue import Queue, Empty  #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue, Empty  #@Reimport
from math import log as mathlog
def logp2(x):
    return mathlog(1+max(1, x), 2)
def logp10(x):
    return mathlog(9+max(1, x), 10)

from wimpiggy.wm import Wm
from wimpiggy.util import (AdHocStruct,
                           one_arg_signal,
                           gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from wimpiggy.lowlevel import (displayHasXComposite,       #@UnresolvedImport
                               get_rectangle_from_region,   #@UnresolvedImport
                               xtest_fake_key,              #@UnresolvedImport
                               xtest_fake_button,           #@UnresolvedImport
                               set_key_repeat_rate,         #@UnresolvedImport
                               ungrab_all_keys,             #@UnresolvedImport
                               unpress_all_keys,            #@UnresolvedImport
                               is_override_redirect,        #@UnresolvedImport
                               is_mapped,                   #@UnresolvedImport
                               add_event_receiver,          #@UnresolvedImport
                               get_cursor_image,            #@UnresolvedImport
                               get_children,                #@UnresolvedImport
                               has_randr, get_screen_sizes, #@UnresolvedImport
                               set_screen_size,             #@UnresolvedImport
                               get_screen_size,             #@UnresolvedImport
                               init_x11_filter,             #@UnresolvedImport
                               get_xatom                    #@UnresolvedImport
                               )
from wimpiggy.prop import prop_set
from wimpiggy.window import OverrideRedirectWindowModel, Unmanageable
from wimpiggy.keys import grok_modifier_map
from wimpiggy.error import XError, trap

from wimpiggy.log import Logger
log = Logger()

import xpra
from xpra.deque import maxdeque
from xpra.protocol import Protocol, SocketConnection, dump_packet, RGB24
from xpra.keys import mask_to_names, get_gtk_keymap, DEFAULT_MODIFIER_NUISANCE, ALL_X11_MODIFIERS
from xpra.xkbhelper import do_set_keymap, set_all_keycodes, set_modifiers_from_meanings, clear_modifiers, set_modifiers_from_keycodes
from xpra.xposix.xclipboard import ClipboardProtocolHelper
from xpra.xposix.xsettings import XSettingsManager
from xpra.scripts.main import ENCODINGS, DEFAULT_ENCODING
from xpra.version_util import is_compatible_with

MAX_CONCURRENT_CONNECTIONS = 20

def _get_rgb_rawdata(wid, pixmap, x, y, width, height, encoding, sequence, options):
    pixmap_w, pixmap_h = pixmap.get_size()
    # Just in case we somehow end up with damage larger than the pixmap,
    # we don't want to start requesting random chunks of memory (this
    # could happen if a window is resized but we don't throw away our
    # existing damage map):
    assert x >= 0
    assert y >= 0
    if x + width > pixmap_w:
        width = pixmap_w - x
    if y + height > pixmap_h:
        height = pixmap_h - y
    if width <= 0 or height <= 0:
        return None
    pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, width, height)
    pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(), x, y, 0, 0, width, height)
    raw_data = pixbuf.get_pixels()
    rowstride = pixbuf.get_rowstride()
    return (wid, x, y, width, height, encoding, raw_data, rowstride, sequence, options)


class DesktopManager(gtk.Widget):
    def __init__(self):
        gtk.Widget.__init__(self)
        self.set_property("can-focus", True)
        self.set_flags(gtk.NO_WINDOW)
        self._models = {}

    ## For communicating with the main WM:

    def add_window(self, model, x, y, w, h):
        assert self.flags() & gtk.REALIZED
        s = AdHocStruct()
        s.shown = False
        s.geom = (x, y, w, h)
        s.window = None
        self._models[model] = s
        model.connect("unmanaged", self._unmanaged)
        model.connect("ownership-election", self._elect_me)
        model.ownership_election()

    def window_geometry(self, model):
        return self._models[model].geom

    def show_window(self, model):
        self._models[model].shown = True
        model.ownership_election()
        if model.get_property("iconic"):
            model.set_property("iconic", False)

    def configure_window(self, model, x, y, w, h):
        if not self.visible(model):
            self._models[model].shown = True
            model.set_property("iconic", False)
            model.ownership_election()
        self._models[model].geom = (x, y, w, h)
        model.maybe_recalculate_geometry_for(self)

    def hide_window(self, model):
        if not model.get_property("iconic"):
            model.set_property("iconic", True)
        self._models[model].shown = False
        model.ownership_election()

    def visible(self, model):
        return self._models[model].shown

    def raise_window(self, model):
        if isinstance(model, OverrideRedirectWindowModel):
            model.get_property("client-window").raise_()
        else:
            window = self._models[model].window
            if window is not None:
                window.raise_()

    ## For communicating with WindowModels:

    def _unmanaged(self, model, wm_exiting):
        del self._models[model]

    def _elect_me(self, model):
        if self.visible(model):
            return (1, self)
        else:
            return (-1, self)

    def take_window(self, model, window):
        window.reparent(self.window, 0, 0)
        self._models[model].window = window

    def window_size(self, model):
        (_, _, w, h) = self._models[model].geom
        return (w, h)

    def window_position(self, model, w, h):
        (x, y, w0, h0) = self._models[model].geom
        if (w0, h0) != (w, h):
            log.warn("Uh-oh, our size doesn't fit window sizing constraints: "
                     "%sx%s vs %sx%s", w0, h0, w, h)
        return (x, y)

gobject.type_register(DesktopManager)


class DamageBatchConfig(object):
    """
    Encapsulate all the damage batching configuration into one object.
    """
    ENABLED = True
    ALWAYS = False
    MAX_EVENTS = 80                     #maximum number of damage events
    MAX_PIXELS = 1024*1024*MAX_EVENTS   #small screen at MAX_EVENTS frames
    TIME_UNIT = 1                       #per second
    MIN_DELAY = 5
    MAX_DELAY = 15000
    def __init__(self):
        self.enabled = self.ENABLED
        self.always = self.ALWAYS
        self.max_events = self.MAX_EVENTS
        self.max_pixels = self.MAX_PIXELS
        self.time_unit = self.TIME_UNIT
        self.min_delay = self.MIN_DELAY
        self.max_delay = self.MAX_DELAY
        self.delay = self.MIN_DELAY
        self.last_delays = maxdeque(100)
        self.last_updated = 0
        self.encoding = None

    def clone(self):
        c = DamageBatchConfig()
        for x in ["enabled", "always", "min_delay", "max_delay", "delay", "last_delays"]:
            setattr(c, x, getattr(self, x))
        return c

class ServerSource(object):
    """
    Strategy: if we have ordinary packets to send, send those.
    When we don't, then send window updates (expired ones first).
    The UI thread adds damage requests to a queue - see damage()
    """

    def __init__(self, protocol, batch_config, encoding, mmap, mmap_size):
        self._ordinary_packets = []
        self._protocol = protocol
        self._encoding = encoding
        self._damage_cancelled = {}
        self._damage_last_events = {}
        self._damage_delayed = {}
        self.client_decode_time = {}
        # for managing sequence numbers:
        self._sequence = 0                      #increase with every Region
        self._damage_packet_sequence = 0        #increase with every packet send
        self._damage_packet_sizes = maxdeque(100)
        self.last_client_packet_sequence = -1   #the last damage_packet_sequence the client echoed back to us
        self.last_client_delta = None           #last delta between our damage_packet_sequence and last_client_packet_sequence
        self.default_batch_config = batch_config
        self.batch_configs = {}
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size
        protocol.source = self
        self._damage_request_queue = Queue()
        self._damage_data_queue = Queue()
        self._damage_packet_queue = Queue()

        self._closed = False
        self._video_encoder_cleanup = {}
        self._video_encoder_lock = Lock()

        def start_daemon_thread(target, name):
            t = Thread(target=target)
            t.name = name
            t.daemon = True
            t.start()
            return t
        self._damagedata_thread = start_daemon_thread(self.damage_to_data, "damage_to_data")
        self._datapacket_thread = start_daemon_thread(self.data_to_packet, "data_to_packet")

    def close(self):
        self._closed = True
        self._damage_request_queue.put(None, block=False)
        self._damage_data_queue.put(None, block=False)
        self.video_encoder_cleanup()

    def video_encoder_cleanup(self):
        try:
            self._video_encoder_lock.acquire()
            for wid,cb in self._video_encoder_cleanup.items():
                try:
                    log("calling %s for wid=%s", cb, wid)
                    cb()
                except:
                    log.error("error on close callback %s", cb, exc_info=True)
            self._video_encoder_cleanup = {}
        finally:
            self._video_encoder_lock.release()

    def _have_more(self):
        return not self._closed and bool(self._ordinary_packets) or not self._damage_packet_queue.empty()

    def next_packet(self):
        if self._closed:
            return  None, False
        if self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        else:
            try:
                packet = self._damage_packet_queue.get(False)
            except Empty:
                packet = None
        return packet, packet is not None and self._have_more()

    def queue_ordinary_packet(self, packet):
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def set_new_encoding(self, encoding, window_ids):
        self.video_encoder_cleanup()
        if window_ids:
            for wid in window_ids:
                batch = self.get_batch_config(wid, False)
                if batch and batch.encoding==encoding:
                    continue
                self.clear_stats(wid)
                batch.encoding = encoding
        else:
            for wid, batch in self.batch_configs.items():
                if batch.encoding==encoding:
                    continue
                self.clear_stats(wid)
                batch.encoding = encoding
        if not window_ids or self._encoding is None:
            self._encoding = encoding

    def cancel_damage(self, wid):
        #if delayed, we can just drop it now
        if wid in self._damage_delayed:
            log("cancel_damage: %s, removed batched region", wid)
            del self._damage_delayed[wid]
        #for those being processed in separate threads, drop by sequence:
        log("cancel_damage: %s, dropping all damage up to and including sequence=%s", wid, self._sequence)
        self._damage_cancelled[wid] = self._sequence
        #clear it eventually - it should be used within mere seconds
        def clear_cancel(sequence):
            if self._damage_cancelled.get(wid, 0)==sequence:
                del self._damage_cancelled[wid]
        gobject.timeout_add(30*1000, clear_cancel, self._sequence)

    def clear_stats(self, wid):
        for d in [self._damage_last_events, self.client_decode_time, self.batch_configs]:
            if wid in d:
                del d[wid]

    def remove_window(self, wid):
        self.cancel_damage(wid)
        self.clear_stats(wid)
        try:
            self._video_encoder_lock.acquire()
            encoder_cleanup = self._video_encoder_cleanup.get(wid)
            if encoder_cleanup:
                encoder_cleanup()
                del self._video_encoder_cleanup[wid]
        finally:
            self._video_encoder_lock.release()

    def get_batch_config(self, wid, create=True):
        batch = self.batch_configs.get(wid)
        if not batch and create:
            batch = self.default_batch_config.clone()
            self.batch_configs[wid] = batch
        return batch

    def get_encoding(self, wid):
        batch = self.get_batch_config(wid, False)
        if batch:
            return batch.encoding or self._encoding
        return self._encoding

    def damage(self, wid, window, x, y, w, h, options=None):
        """ decide what to do with the damage area:
            * send it now (if not congested or batch.enabled is off)
            * add it to an existing delayed region
            * create a new delayed region if we find the client needs it
            Also takes care of adjusting the batch-delay in case
            of congestion.
            The options dict is currently used for carrying the
            "jpegquality" value, it could also be used for other purposes.
            Be aware though that when multiple
            damage requests are delayed and bundled together,
            the options may get quashed! So, specify a "batching"=False
            option to ensure no batching will occur for this request.
        """
        batch = self.get_batch_config(wid)
        def damage_now(reason):
            self._sequence += 1
            log("damage(%s, %s, %s, %s, %s) %s, sending now with sequence %s", wid, x, y, w, h, reason, self._sequence)
            region = gtk.gdk.Region()
            region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            item = wid, window, region, self._sequence, options
            self._damage_request_queue.put(item)
            batch.last_delays.append(0)
        #record this damage event in the damage_last_events queue:
        now = time.time()
        last_events = self._damage_last_events.setdefault(wid, maxdeque(100))
        last_events.append((now, w*h))

        if not batch.enabled:
            return damage_now("batching disabled")
        if options and options.get("batching", True) is False:
            return damage_now("batching option is off")

        delayed = self._damage_delayed.get(wid)
        if delayed:
            (_, _, region, _, _) = delayed
            region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            log("damage(%s, %s, %s, %s, %s) using existing delayed region: %s", wid, x, y, w, h, delayed)
            return

        self.calculate_batch_delay(wid, batch)
        event_min_time = now-batch.time_unit
        all_pixels = [pixels for event_time,pixels in last_events if event_time>event_min_time]
        beyond_limit = len(all_pixels)>batch.max_events or sum(all_pixels)>batch.max_pixels
        if not beyond_limit and not batch.always and batch.delay<=batch.min_delay:
            return damage_now("delay is at the minimum threshold")

        #create a new delayed region:
        region = gtk.gdk.Region()
        region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
        self._sequence += 1
        self._damage_delayed[wid] = (wid, window, region, self._sequence, options)
        def send_delayed():
            """ move the delayed rectangles to the expired list """
            log("send_delayed for %s", wid)
            delayed = self._damage_delayed.get(wid)
            if delayed:
                del self._damage_delayed[wid]
                self._damage_request_queue.put(delayed)
                log("moving region %s to expired list", delayed)
            else:
                log("window %s already removed from delayed list?", wid)
            return False
        log("damage(%s, %s, %s, %s, %s) scheduling batching expiry for sequence %s in %sms", wid, x, y, w, h, self._sequence, batch.delay)
        batch.last_delays.append(batch.delay)
        gobject.timeout_add(int(batch.delay), send_delayed)

    def calculate_batch_delay(self, wid, batch):
        now = time.time()
        if batch.last_updated+0.025>=now:
            return

        def update_batch_delay(reason, factor=1, delta=0):
            batch.delay = max(batch.min_delay, min(batch.max_delay, int(100.0*batch.delay*factor)/100.0)-delta)
            batch.last_updated = now
            log("update_batch_delay: %s, wid=%s, factor=%s, delta=%s, new batch delay=%s", reason, wid, factor, delta, batch.delay)

        last_delta = self.last_client_delta
        delta = self._damage_packet_sequence-self.last_client_packet_sequence
        self.last_client_delta = delta
        if True:
            if self._damage_packet_queue.qsize()>3:
                #packets ready for sending by network layer
                update_batch_delay("damage packet queue overflow: %s" % self._damage_packet_queue.qsize(), logp2(self._damage_packet_queue.qsize()-2))
            if self._damage_request_queue.qsize()>3:
                #processes damage requests and places them on the damage_data_queue
                update_batch_delay("damage request queue overflow: %s" % self._damage_request_queue.qsize(), logp10(self._damage_request_queue.qsize()-2))
            if self._damage_data_queue.qsize()>3:
                #contains pixmaps before they get converted to a packet that goes to the damage_packet_queue
                update_batch_delay("damage data queue overflow: %s" % self._damage_data_queue.qsize(), logp10(self._damage_data_queue.qsize()-2))
        if not last_delta:
            return
        #figure out how many pixels behind we are, rather than just the number of packets
        all_unprocessed = list(self._damage_packet_sizes)[-delta:]
        unprocessed = [pixels for (uwid,pixels) in all_unprocessed if uwid==wid]
        all_last_unprocessed = list(self._damage_packet_sizes)[-last_delta:]
        last_unprocessed = [pixels for (uwid,pixels) in all_last_unprocessed if uwid==wid]

        packets_due = len(unprocessed)
        last_packets_due = len(last_unprocessed)
        pixels_behind = sum(unprocessed)
        last_pixels_behind = sum(last_unprocessed)
        log("calculate_batch_delay: wid=%s, unprocessed=%s, last_unprocessed=%s, pixels_behind=%s, last_pixels_behind=%s", wid, unprocessed, last_unprocessed, pixels_behind, last_pixels_behind)
        if packets_due<=2 and last_packets_due<=2:
            return update_batch_delay("client is up to date: %s packets in queue" % packets_due, 0.9, 1)
        if packets_due<last_packets_due and pixels_behind<last_pixels_behind:
            return update_batch_delay("client is catching up: down from %s to %s packets in queue, %s to %s pixels due" % (last_packets_due, packets_due, last_pixels_behind, pixels_behind), 0.9, 1)
        low_limit, high_limit = 8*1024, 32*1024
        if self._mmap and self._mmap_size>0:
            low_limit, high_limit = 256*1024, 1*1024*1024
        #things are getting worse or unchanged:
        if pixels_behind<=low_limit:
            if packets_due<=5:
                return update_batch_delay("client is only %s pixels and only %s packets behind" % (pixels_behind, packets_due), 0.8, 1)
            if packets_due<10 and packets_due<last_packets_due:
                return update_batch_delay("client is only %s pixels and %s packets behind" % (pixels_behind, packets_due), 0.9, 0)
        if pixels_behind>=high_limit:
            return update_batch_delay("client is %s pixels behind!" % pixels_behind, min(2.0, logp2(1.0*pixels_behind/high_limit)))
        if pixels_behind<last_pixels_behind:
            #things are getting better:
            return update_batch_delay("client is only %s pixels behind, from %s last time around" % (pixels_behind, last_pixels_behind), 0.4+(10.0*pixels_behind/(1+last_pixels_behind)/2)/10.0)
        if packets_due>last_packets_due:
            return update_batch_delay("client is %s packets behind, up from %s" % (packets_due, last_packets_due), logp10(1.0*packets_due/(1+last_packets_due)))
        return update_batch_delay("client is %s pixels behind, from %s last time around" % (pixels_behind, last_pixels_behind), min(2.0, logp2(1.0*pixels_behind/last_pixels_behind)))

    def damage_to_data(self):
        """ pick items off the damage_request_queue
            and places the damage pixel data in the _damage_data_queue.
            this method runs in a thread but most of the actual processing
            is done in process_regions() which runs in the gtk main thread
            via idle_add.
        """
        while not self._closed:
            damage_request = self._damage_request_queue.get(True)
            if damage_request is None:
                return              #empty marker
            wid, window, damage, sequence, options = damage_request
            log("damage_to_data: processing sequence=%s", sequence)
            if self._damage_cancelled.get(wid, 0)>=sequence:
                log("damage_to_data: dropping request with sequence=%s", sequence)
                continue
            regions = []
            coding = self.get_encoding(wid)
            is_or = isinstance(window, OverrideRedirectWindowModel)
            try:
                if is_or:
                    (_, _, ww, wh) = window.get_property("geometry")
                else:
                    ww, wh = window.get_property("actual-size")
            except KeyError, e:
                ww, wh = 512, 512
            try:
                pixels_threshold = ww*wh*9/10
                packet_cost = 1024
                if self._mmap and self._mmap_size>0:
                    #with mmap, we can move lots of data around easily
                    #so favour large screen updates over many small packets
                    pixels_threshold = ww*wh/2
                    packet_cost = 4096
                pixel_count = 0
                while not damage.empty():
                    try:
                        (x, y, w, h) = get_rectangle_from_region(damage)
                        pixel_count += w*h
                        #favor full screen updates over many regions:
                        #x264 and vpx need full screen updates all the time
                        if pixel_count+packet_cost*len(regions)>=pixels_threshold or coding in ["x264", "vpx"]:
                            regions = [(0, 0, ww, wh, True)]
                            break
                        regions.append((x, y, w, h, False))
                        rect = gtk.gdk.Rectangle(x, y, w, h)
                        damage.subtract(gtk.gdk.region_rectangle(rect))
                    except ValueError:
                        log.error("damage_to_data: damage is empty: %s", damage)
                        break
                log("damage_to_data: to regions: %s items, %s pixels", len(regions), pixel_count)
            except Exception, e:
                log.error("damage_to_data: error processing region %s: %s", damage, e)
                continue
            gobject.idle_add(self._process_damage_regions, wid, window, ww, wh, regions, coding, sequence, options)

    def _process_damage_regions(self, wid, window, ww, wh, regions, coding, sequence, options):
        if self._damage_cancelled.get(wid, 0)>=sequence:
            log("process_damage_regions: dropping damage request with sequence=%s", sequence)
            return
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        log("process_damage_regions: regions=%s, sending damage ack", regions)
        window.acknowledge_changes()
        pixmap = window.get_property("client-contents")
        if pixmap is None:
            log.error("wtf, pixmap is None for window %s, wid=%s", window, wid)
            return
        log("process_damage_regions: pixmap size=%s, window size=%s", pixmap.get_size(), (ww, wh))
        for region in regions:
            (x, y, w, h, full_window) = region
            if full_window:
                log("process_damage_regions: sending full window: %s", pixmap.get_size())
                w, h = pixmap.get_size()
            data = _get_rgb_rawdata(wid, pixmap, x, y, w, h, coding, sequence, options)
            if data:
                log("process_damage_regions: adding pixel data %s to queue, queue size=%s", data[:6], self._damage_data_queue.qsize())
                self._damage_data_queue.put(data)

    def data_to_packet(self):
        while not self._closed:
            item = self._damage_data_queue.get(True)
            if item is None:
                return              #empty marker
            try:
                packet = self.make_data_packet(item)
                if packet:
                    log("data_to_packet: adding to packet queue, size=%s, full=%s", self._damage_packet_queue.qsize(), self._damage_packet_queue.full())
                    if self._damage_packet_queue.full():
                        self._protocol.source_has_more()
                    self._damage_packet_queue.put(packet)
                    self._protocol.source_has_more()
            except Exception, e:
                log.error("error processing damage data: %s", e, exc_info=True)

    def make_data_packet(self, item):
        wid, x, y, w, h, coding, data, rowstride, sequence, options = item
        if sequence>=0 and self._damage_cancelled.get(wid, 0)>=sequence:
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        log("make_data_packet: damage data: %s", (wid, x, y, w, h, coding))
        #send via mmap?
        if self._mmap and self._mmap_size>0 and len(data)>256:
            now = time.time()
            mmap_data = self._mmap_send(data)
            end = time.time()
            log("%s MBytes/s - %s bytes written to mmap in %sms", int(len(data)/(end-now)/1024/1024), len(data), int(1000*1000*(end-now))/1000.0)
            if mmap_data is not None:
                coding = "mmap"
                data = mmap_data
        #encode to jpeg/png:
        if coding in ["jpeg", "png"]:
            assert coding in ENCODINGS
            import Image
            im = Image.fromstring("RGB", (w, h), data, "raw", "RGB", rowstride)
            buf = StringIO()
            if coding=="jpeg":
                q = 50
                if options:
                    q = options.get("jpegquality", 50)
                q = min(99, max(1, q))
                log.debug("sending with jpeg quality %s", q)
                im.save(buf, "JPEG", quality=q)
            else:
                log.debug("sending as %s", coding)
                im.save(buf, coding.upper())
            data = buf.getvalue()
            buf.close()
        elif coding=="x264":
            assert coding in ENCODINGS
            assert x==0 and y==0
            #x264 needs sizes divisible by 2:
            w = w & 0xFFFE
            h = h & 0xFFFE
            from xpra.x264.codec import ENCODERS as x264_encoders, Encoder as x264Encoder   #@UnresolvedImport
            data = self.video_encode(x264_encoders, x264Encoder, wid, x, y, w, h, coding, data, rowstride)
        elif coding=="vpx":
            assert coding in ENCODINGS
            assert x==0 and y==0
            from xpra.vpx.codec import ENCODERS as vpx_encoders, Encoder as vpxEncoder      #@UnresolvedImport
            data = self.video_encode(vpx_encoders, vpxEncoder, wid, x, y, w, h, coding, data, rowstride)
        elif coding=="rgb24":
            data = RGB24(data)
        elif coding=="mmap":
            pass
        else:
            raise Exception("invalid encoding: %s" % coding)

        #check cancellation list again since the code above may take some time:
        #but always send mmap data so we can reclaim the space!
        if coding!="mmap" and sequence>=0 and self._damage_cancelled.get(wid, 0)>=sequence:
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        #actual network packet:
        packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride]
        self._damage_packet_sequence += 1
        self._damage_packet_sizes.append((wid, w*h))
        return packet

    def video_encode(self, encoders, factory, wid, x, y, w, h, coding, data, rowstride):
        assert coding in ENCODINGS
        assert x==0 and y==0
        #time_before = time.clock()
        try:
            self._video_encoder_lock.acquire()
            encoder = encoders.get(wid)
            if encoder and (encoder.get_width()!=w or encoder.get_height()!=h):
                log("%s: window dimensions have changed from %s to %s", (coding, encoder.get_width(), encoder.get_height()), (w, h))
                encoder.clean()
                encoder.init(w, h)
            if encoder is None:
                #we could have an old encoder if we were using a different encoding
                #if so, clean it up:
                old_encoder_cb = self._video_encoder_cleanup.get(wid)
                if old_encoder_cb:
                    old_encoder_cb()
                    del self._video_encoder_cleanup[wid]
                log("%s: new encoder", coding)
                encoder = factory()
                encoder.init(w, h)
                encoders[wid] = encoder
                def close_encoder():
                    log("close_encoder: %s for wid=%s" % (coding, wid))
                    encoder.clean()
                    del encoders[wid]
                self._video_encoder_cleanup[wid] = close_encoder
            log("%s: compress_image(%s bytes, %s)", coding, len(data), rowstride)
            err, size, data = encoder.compress_image(data, rowstride)
            if err!=0:
                log.error("%s: ouch, compression error %s", coding, err)
                return None
            return data
        finally:
            self._video_encoder_lock.release()

    def _mmap_send(self, data):
        #This is best explained using diagrams:
        #mmap_area=[&S&E-------------data-------------]
        #The first pair of 4 bytes are occupied by:
        #S=data_start index is only updated by the client and tells us where it has read up to
        #E=data_end index is only updated here and marks where we have written up to (matches current seek)
        # '-' denotes unused/available space
        # '+' is for data we have written
        # '*' is for data we have just written in this call
        # E and S show the location pointed to by data_start/data_end
        data_start = ctypes.c_uint.from_buffer(self._mmap, 0)
        data_end = ctypes.c_uint.from_buffer(self._mmap, 4)
        start = max(8, data_start.value)
        end = max(8, data_end.value)
        if end<start:
            #we have wrapped around but the client hasn't yet:
            #[++++++++E--------------------S+++++]
            #so there is one chunk available (from E to S):
            available = start-end
            chunk = available
        else:
            #we have not wrapped around yet, or the client has wrapped around too:
            #[------------S++++++++++++E---------]
            #so there are two chunks available (from E to the end, from the start to S):
            chunk = self._mmap_size-end
            available = chunk+(start-8)
        l = len(data)
        if l>=available:
            log.warn("mmap area full: we need more than %s but only %s left! ouch!", l, available)
            return None
        if l<chunk:
            """ data fits in the first chunk """
            #ie: initially:
            #[----------------------------------]
            #[*********E------------------------]
            #or if data already existed:
            #[+++++++++E------------------------]
            #[+++++++++**********E--------------]
            self._mmap.seek(end)
            self._mmap.write(data)
            data = [(end, l)]
            data_end.value = end+l
        else:
            """ data does not fit in first chunk alone """
            if available>=(self._mmap_size/2) and available>=(l*3) and l<(start-8):
                """ still plenty of free space, don't wrap around: just start again """
                #[------------------S+++++++++E------]
                #[*******E----------S+++++++++-------]
                self._mmap.seek(8)
                self._mmap.write(data)
                data = [(8, l)]
                data_end.value = 8+l
            else:
                """ split in 2 chunks: wrap around the end of the mmap buffer """
                #[------------------S+++++++++E------]
                #[******E-----------S+++++++++*******]
                self._mmap.seek(end)
                self._mmap.write(data[:chunk])
                self._mmap.seek(8)
                self._mmap.write(data[chunk:])
                l2 = l-chunk
                data = [(end, chunk), (8, l2)]
                data_end.value = 8+l2
        log("sending damage with mmap: %s", data)
        return data


def can_run_server():
    root = gtk.gdk.get_default_root_window()
    if not displayHasXComposite(root):
        log.error("Xpra is a compositing manager, it cannot use a display which lacks the XComposite extension!")
        return False
    return True


class XpraServer(gobject.GObject):
    __gsignals__ = {
        "wimpiggy-child-map-event": one_arg_signal,
        "wimpiggy-cursor-event": one_arg_signal,
        }

    def __init__(self, clobber, sockets, opts):
        gobject.GObject.__init__(self)
        init_x11_filter()
        self.init_x11_atoms()

        self.start_time = time.time()

        # Do this before creating the Wm object, to avoid clobbering its
        # selecting SubstructureRedirect.
        root = gtk.gdk.get_default_root_window()
        root.set_events(root.get_events() | gtk.gdk.SUBSTRUCTURE_MASK)
        root.property_change(gtk.gdk.atom_intern("XPRA_SERVER", False),
                            gtk.gdk.atom_intern("STRING", False),
                            8,
                            gtk.gdk.PROP_MODE_REPLACE,
                            xpra.__version__)
        add_event_receiver(root, self)

        # This must happen early, before loading in windows at least:
        self._protocol = None
        self._potential_protocols = []
        self._server_source = None
        self.default_damage_options = {}

        self.supports_mmap = opts.mmap
        self.encoding = opts.encoding or DEFAULT_ENCODING
        assert self.encoding in ENCODINGS
        self.png_window_icons = False
        self.session_name = opts.session_name
        try:
            import glib
            glib.set_application_name(self.session_name or "Xpra")
        except ImportError, e:
            log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)

        ### Create the WM object
        self._wm = Wm("Xpra", clobber)
        self._wm.connect("new-window", self._new_window_signaled)
        self._wm.connect("bell", self._bell_signaled)
        self._wm.connect("quit", lambda _: self.quit(True))

        ### Create our window managing data structures:
        self._desktop_manager = DesktopManager()
        self._wm.get_property("toplevel").add(self._desktop_manager)
        self._desktop_manager.show_all()

        self._window_to_id = {}
        self._id_to_window = {}
        # Window id 0 is reserved for "not a window"
        self._max_window_id = 1

        ### Load in existing windows:
        for window in self._wm.get_property("windows"):
            self._add_new_window(window)

        for window in get_children(root):
            if (is_override_redirect(window) and is_mapped(window)):
                self._add_new_or_window(window)

        ## These may get set by the client:
        self.xkbmap_layout = None
        self.xkbmap_variant = None
        self.xkbmap_print = None
        self.xkbmap_query = None
        self.xkbmap_mod_meanings = {}
        self.xkbmap_mod_managed = None
        self.keycode_translation = {}
        self.keymap_changing = False
        self.keyboard = True
        self.keyboard_sync = True
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.encodings = []
        self.mmap = None
        self.mmap_size = 0

        self.reset_statistics()

        self.send_notifications = False
        self.last_cursor_serial = None
        self.cursor_image = None
        #store list of currently pressed keys
        #(using a dict only so we can display their names in debug messages)
        self.keys_pressed = {}
        self.keys_timedout = {}
        #timers for cancelling key repeat when we get jitter
        self.keys_repeat_timers = {}
        ### Set up keymap:
        self.xkbmap_initial = get_gtk_keymap()
        self._keymap = gtk.gdk.keymap_get_default()
        self._keymap.connect("keys-changed", self._keys_changed)
        self._keys_changed()

        self._keynames_for_mod = None
        #clear all modifiers
        self.clean_keyboard_state()
        self._make_keymask_match([])

        ### Clipboard handling:
        self.clipboard_enabled = opts.clipboard
        if self.clipboard_enabled:
            def send_clipboard(packet):
                if self.clipboard_enabled:
                    self._send(packet)
                else:
                    log.debug("clipboard is disabled, dropping packet")
            self._clipboard_helper = ClipboardProtocolHelper(send_clipboard)
        else:
            self._clipboard_helper = None

        ### Misc. state:
        self._settings = {}
        self._xsettings_manager = None
        self._has_focus = 0
        self._upgrading = False

        self.password_file = opts.password_file
        self.salt = None

        self.randr = opts.randr and has_randr()
        if self.randr and len(get_screen_sizes())<=1:
            #disable randr when we are dealing with a Xvfb
            #with only one resolution available
            #since we don't support adding them on the fly yet
            self.randr = False
        log("randr enabled: %s", self.randr)

        self.pulseaudio = opts.pulseaudio

        try:
            from xpra.dbus_notifications_forwarder import register
            self.notifications_forwarder = register(self.notify_callback, self.notify_close_callback)
            if self.notifications_forwarder:
                log.info("using notification forwarder: %s", self.notifications_forwarder)
        except Exception, e:
            log.error("error loading or registering our dbus notifications forwarder: %s", e)
            self.notifications_forwarder = None

        ### All right, we're ready to accept customers:
        for sock in sockets:
            self.add_listen_socket(sock)

    def init_x11_atoms(self):
        #some applications (like openoffice), do not work properly
        #if some x11 atoms aren't defined, so we define them in advance:
        for atom_name in ["_NET_WM_WINDOW_TYPE",
                          "_NET_WM_WINDOW_TYPE_NORMAL",
                          "_NET_WM_WINDOW_TYPE_DESKTOP",
                          "_NET_WM_WINDOW_TYPE_DOCK",
                          "_NET_WM_WINDOW_TYPE_TOOLBAR",
                          "_NET_WM_WINDOW_TYPE_MENU",
                          "_NET_WM_WINDOW_TYPE_UTILITY",
                          "_NET_WM_WINDOW_TYPE_SPLASH",
                          "_NET_WM_WINDOW_TYPE_DIALOG",
                          "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
                          "_NET_WM_WINDOW_TYPE_POPUP_MENU",
                          "_NET_WM_WINDOW_TYPE_TOOLTIP",
                          "_NET_WM_WINDOW_TYPE_NOTIFICATION",
                          "_NET_WM_WINDOW_TYPE_COMBO",
                          "_NET_WM_WINDOW_TYPE_DND",
                          "_NET_WM_WINDOW_TYPE_NORMAL"
                          ]:
            get_xatom(atom_name)

    def reset_statistics(self):
        self.client_latency = maxdeque(maxlen=100)
        self.server_latency = maxdeque(maxlen=100)
        self.client_load = None

    def clean_keyboard_state(self):
        try:
            ungrab_all_keys(gtk.gdk.get_default_root_window())
        except:
            log.error("error ungrabbing keys", exc_info=True)
        try:
            unpress_all_keys(gtk.gdk.get_default_root_window())
        except:
            log.error("error unpressing keys", exc_info=True)

    def set_keymap(self):
        try:
            #prevent _keys_changed() from firing:
            #(using a flag instead of keymap.disconnect(handler) as this did not seem to work!)
            self.keymap_changing = True
            self.clean_keyboard_state()
            try:
                do_set_keymap(self.xkbmap_layout, self.xkbmap_variant,
                              self.xkbmap_print, self.xkbmap_query)
            except:
                log.error("error setting new keymap", exc_info=True)
            try:
                #first clear all existing modifiers:
                self.clean_keyboard_state()
                modifiers = ALL_X11_MODIFIERS.keys()  #just clear all of them (set or not)
                clear_modifiers(modifiers)

                #now set all the keycodes:
                self.clean_keyboard_state()
                self.keycode_translation = {}
                self._keynames_for_mod = None
                if self.keyboard:
                    assert self.xkbmap_keycodes and len(self.xkbmap_keycodes)>0, "client failed to provide xkbmap_keycodes!"
                    self.keycode_translation = set_all_keycodes(self.xkbmap_keycodes, self.xkbmap_initial)

                    #now set the new modifier mappings:
                    self.clean_keyboard_state()
                    log.debug("going to set modifiers, xkbmap_mod_meanings=%s, len(xkbmap_keycodes)=%s", self.xkbmap_mod_meanings, len(self.xkbmap_keycodes or []))
                    if self.xkbmap_mod_meanings:
                        #Unix-like OS provides modifier meanings:
                        self._keynames_for_mod = set_modifiers_from_meanings(self.xkbmap_mod_meanings)
                    elif self.xkbmap_keycodes:
                        #non-Unix-like OS provides just keycodes for now:
                        self._keynames_for_mod = set_modifiers_from_keycodes(self.xkbmap_keycodes)
                    else:
                        log.error("missing both xkbmap_mod_meanings and xkbmap_keycodes, modifiers will probably not work as expected!")
                    log.debug("keyname_for_mod=%s", self._keynames_for_mod)
            except:
                log.error("error setting xmodmap", exc_info=True)
        finally:
            # re-enable via idle_add to give all the pending
            # events a chance to run first (and get ignored)
            def reenable_keymap_changes(*args):
                self.keymap_changing = False
                self._keys_changed()
            gobject.idle_add(reenable_keymap_changes)


    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def quit(self, upgrading):
        self._upgrading = upgrading
        log.info("\nxpra is terminating.")
        sys.stdout.flush()
        gtk_main_quit_really()

    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        def print_ready():
            log.info("\nxpra is ready.")
            sys.stdout.flush()
        gobject.idle_add(print_ready)
        gtk.main()
        log.info("\nxpra end of gtk.main().")
        return self._upgrading

    def cleanup(self, *args):
        if self.notifications_forwarder:
            try:
                self.notifications_forwarder.release()
            except Exception, e:
                log.error("failed to release dbus notification forwarder: %s", e)
        self.disconnect("shutting down")

    def _new_connection(self, listener, *args):
        log.info("New connection received")
        if len(self._potential_protocols)>=MAX_CONCURRENT_CONNECTIONS:
            log.error("too many connections (%s), ignoring new one", len(self._potential_protocols))
            listener.close()
            return  True
        sock, address = listener.accept()
        protocol = Protocol(SocketConnection(sock, address), self.process_packet)
        self._potential_protocols.append(protocol)
        protocol.start()
        def verify_connection_accepted(protocol):
            if not protocol._closed and protocol in self._potential_protocols and protocol!=self._protocol:
                log.error("connection timedout: %s", protocol)
                self.send_disconnect(protocol, "login timeout")
        gobject.timeout_add(10*1000, verify_connection_accepted, protocol)
        return True

    def _keys_changed(self, *args):
        if not self.keymap_changing:
            self._modifier_map = grok_modifier_map(gtk.gdk.display_get_default(), self.xkbmap_mod_meanings)

    def _new_window_signaled(self, wm, window):
        self._add_new_window(window)

    def do_wimpiggy_cursor_event(self, event):
        if self.last_cursor_serial==event.cursor_serial:
            log("ignoring cursor event with the same serial number")
            return
        self.last_cursor_serial = event.cursor_serial
        self.cursor_image = get_cursor_image()
        if self.cursor_image:
            log("do_wimpiggy_cursor_event(%s) new_cursor=%s", event, self.cursor_image[:7])
        else:
            log("do_wimpiggy_cursor_event(%s) failed to get cursor image", event)
        self.send_cursor()

    def send_cursor(self):
        self._send(["cursor", self.cursor_image or ""])

    def _bell_signaled(self, wm, event):
        log("_bell_signaled(%s,%r)", wm, event)
        if not self.send_bell:
            return
        wid = 0
        if event.window!=gtk.gdk.get_default_root_window() and event.window_model is not None:
            try:
                wid = self._window_to_id[event.window_model]
            except:
                pass
        log("_bell_signaled(%s,%r) wid=%s", wm, event, wid)
        self._send(["bell", wid, event.device, event.percent, event.pitch, event.duration, event.bell_class, event.bell_id, event.bell_name or ""])

    def notify_callback(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        log("notify_callback(%s,%s,%s,%s,%s,%s,%s,%s) send_notifications=%s", dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, self.send_notifications)
        if self.send_notifications:
            self._send(["notify_show", dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout)])

    def notify_close_callback(self, nid):
        log("notify_close_callback(%s)", nid)
        if self.send_notifications:
            self._send(["notify_close", int(nid)])

    def do_wimpiggy_child_map_event(self, event):
        raw_window = event.window
        if event.override_redirect:
            self._add_new_or_window(raw_window)

    def _add_new_window_common(self, window):
        wid = self._max_window_id
        self._max_window_id += 1
        self._window_to_id[window] = wid
        self._id_to_window[wid] = window
        window.connect("client-contents-changed", self._contents_changed)
        window.connect("unmanaged", self._lost_window)

    _window_export_properties = ("title", "size-hints")
    def _add_new_window(self, window):
        log.debug("Discovered new ordinary window: %s", window)
        self._add_new_window_common(window)
        for prop in self._window_export_properties:
            window.connect("notify::%s" % prop, self._update_metadata)
        (x, y, w, h, _) = window.get_property("client-window").get_geometry()
        self._desktop_manager.add_window(window, x, y, w, h)
        self._send_new_window_packet(window)

    def _add_new_or_window(self, raw_window):
        log("Discovered new override-redirect window")
        try:
            window = OverrideRedirectWindowModel(raw_window)
        except Unmanageable:
            return
        self._add_new_window_common(window)
        window.connect("notify::geometry", self._or_window_geometry_changed)
        self._send_new_or_window_packet(window)

    def _or_window_geometry_changed(self, window, pspec):
        (x, y, w, h) = window.get_property("geometry")
        wid = self._window_to_id[window]
        self._send(["configure-override-redirect", wid, x, y, w, h])

    # These are the names of WindowModel properties that, when they change,
    # trigger updates in the xpra window metadata:
    _all_metadata = ("title", "size-hints", "class-instance", "icon", "client-machine", "transient-for", "window-type")

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property:
    def _make_metadata(self, window, propname):
        assert propname in self._all_metadata
        if propname == "title":
            if window.get_property("title") is not None:
                return {"title": window.get_property("title").encode("utf-8")}
            else:
                return {}
        elif propname == "size-hints":
            hints_metadata = {}
            hints = window.get_property("size-hints")
            if hints is not None:
                for attr, metakey in [
                    ("max_size", "maximum-size"),
                    ("min_size", "minimum-size"),
                    ("base_size", "base-size"),
                    ("resize_inc", "increment"),
                    ("min_aspect_ratio", "minimum-aspect"),
                    ("max_aspect_ratio", "maximum-aspect"),
                    ]:
                    v = getattr(hints, attr)
                    if v is not None and v>=0 and v<(2**32-1):
                        hints_metadata[metakey] = getattr(hints, attr)
            return {"size-constraints": hints_metadata}
        elif propname == "class-instance":
            c_i = window.get_property("class-instance")
            if c_i is not None:
                return {"class-instance": [x.encode("utf-8") for x in c_i]}
            else:
                return {}
        elif propname == "icon":
            surf = window.get_property("icon")
            if surf is not None:
                w = surf.get_width()
                h = surf.get_height()
                log("found new window icon: %sx%s, sending as png=%s", w,h,self.png_window_icons)
                if self.png_window_icons:
                    import Image
                    img = Image.frombuffer("RGBA", (w,h), surf.get_data(), "raw", "BGRA", 0, 1)
                    MAX_SIZE = 64
                    if w>MAX_SIZE or h>MAX_SIZE:
                        #scale icon down
                        if w>=h:
                            h = int(h*MAX_SIZE/w)
                            w = MAX_SIZE
                        else:
                            w = int(w*MAX_SIZE/h)
                            h = MAX_SIZE
                        log("scaling window icon down to %sx%s", w, h)
                        img = img.resize((w,h), Image.ANTIALIAS)
                    output = StringIO()
                    img.save(output, 'PNG')
                    raw_data = output.getvalue()
                    return {"icon": (w, h, "png", str(raw_data)) }
                else:
                    assert surf.get_format() == cairo.FORMAT_ARGB32
                    assert surf.get_stride() == 4 * surf.get_width()
                    return {"icon": (w, h, "premult_argb32", str(surf.get_data())) }
            else:
                return {}
        elif propname == "client-machine":
            client_machine = window.get_property("client-machine")
            if client_machine is not None:
                return {"client-machine": client_machine.encode("utf-8")}
            else:
                return {}
        elif propname == "transient-for":
            transient_for = window.get_property("transient-for")
            if transient_for:
                log.debug("found transient_for=%s, xid=%s", transient_for, transient_for.xid)
                #try to find the model for this window:
                for model in self._desktop_manager._models.keys():
                    log.debug("testing model %s: %s", model, model.client_window.xid)
                    if model.client_window.xid==transient_for.xid:
                        wid = self._window_to_id.get(model)
                        log.debug("found match, window id=%s", wid)
                        return {"transient-for" : wid}
                return {}
            return {}
        elif propname == "window-type":
            window_types = window.get_property("window-type")
            log.debug("window_types=%s", window_types)
            wts = []
            for window_type in window_types:
                wts.append(str(window_type))
            log.debug("window_types=%s", wts)
            return {"window-type" : wts}
        raise Exception("unhandled property name: %s" % propname)

    def _make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        """
            Given a list of modifiers that should be set, try to press the right keys
            to make the server's modifier list match it.
            Things to take into consideration:
            * xkbmap_mod_managed is a list of modifiers which are "server-managed":
                these never show up in the client's modifier list as it is not aware of them,
                so we just always leave them as they are and rely on some client key event to toggle them.
                ie: "num" on win32, which is toggled by the "Num_Lock" key presses.
            * when called from '_handle_key', we ignore the modifier key which may be pressed
                or released as it should be set by that key press event.
            * when called from mouse position/click events we ignore 'xkbmap_mod_pointermissing'
                which is set by the client to indicate modifiers which are missing from mouse events.
                ie: on win32, "lock" is missing.
            * if the modifier is a "nuisance" one ("lock", "num", "scroll") then we must
                simulate a full keypress (down then up).
            * some modifiers can be set by multiple keys ("shift" by both "Shift_L" and "Shift_R" for example)
                so we try to find the matching modifier in the currently pressed keys (keys_pressed)
                to make sure we unpress the right one.
        """
        if not self.keyboard:
            return
        if not self._keynames_for_mod:
            log.debug("make_keymask_match: ignored as keynames_for_mod not assigned yet")
            return

        def get_keycodes(keyname):
            keyval = gtk.gdk.keyval_from_name(keyname)
            if keyval==0:
                log.error("no keyval found for %s", keyname)
                return  []
            entries = self._keymap.get_entries_for_keyval(keyval)
            keycodes = []
            if entries:
                for _keycode,_group,_level in entries:
                    keycodes.append(_keycode)
            return  keycodes

        def get_current_mask():
            (_, _, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
            modifiers = mask_to_names(current_mask, self._modifier_map)
            log.debug("get_modifier_mask()=%s", modifiers)
            return modifiers
        current = set(get_current_mask())
        wanted = set(modifier_list)
        log.debug("make_keymask_match(%s) current mask: %s, wanted: %s, ignoring=%s/%s, keys_pressed=%s", modifier_list, current, wanted, ignored_modifier_keycode, ignored_modifier_keynames, self.keys_pressed)
        display = gtk.gdk.display_get_default()

        def change_mask(modifiers, press, info):
            for modifier in modifiers:
                if self.xkbmap_mod_managed and modifier in self.xkbmap_mod_managed:
                    log.debug("modifier is server managed: %s", modifier)
                    continue
                keynames = self._keynames_for_mod.get(modifier)
                if not keynames:
                    log.error("unknown modifier: %s", modifier)
                    continue
                if ignored_modifier_keynames:
                    for imk in ignored_modifier_keynames:
                        if imk in keynames:
                            log.debug("modifier %s ignored (ignored keyname=%s)", modifier, imk)
                            continue
                keycodes = []
                #log.info("keynames(%s)=%s", modifier, keynames)
                for keyname in keynames:
                    if keyname in self.keys_pressed.values():
                        #found the key which was pressed to set this modifier
                        for keycode, name in self.keys_pressed.items():
                            if name==keyname:
                                log.debug("found the key pressed for %s: %s", modifier, name)
                                keycodes.insert(0, keycode)
                    kcs = get_keycodes(keyname)
                    for kc in kcs:
                        if kc not in keycodes:
                            keycodes.append(kc)
                if ignored_modifier_keycode is not None and ignored_modifier_keycode in keycodes:
                    log.debug("modifier %s ignored (ignored keycode=%s)", modifier, ignored_modifier_keycode)
                    continue
                #nuisance keys (lock, num, scroll) are toggled by a
                #full key press + key release (so act accordingly in the loop below)
                nuisance = modifier in DEFAULT_MODIFIER_NUISANCE
                log.debug("keynames(%s)=%s, keycodes=%s, nuisance=%s", modifier, keynames, keycodes, nuisance)
                for keycode in keycodes:
                    if nuisance:
                        xtest_fake_key(display, keycode, True)
                        xtest_fake_key(display, keycode, False)
                    else:
                        xtest_fake_key(display, keycode, press)
                    new_mask = get_current_mask()
                    #log.debug("make_keymask_match(%s) %s modifier %s using %s: %s", info, modifier_list, modifier, keycode, (modifier not in new_mask))
                    if (modifier in new_mask)==press:
                        break
                    elif not nuisance:
                        log.debug("%s %s with keycode %s did not work - trying to undo it!", info, modifier, keycode)
                        xtest_fake_key(display, keycode, not press)
                        new_mask = get_current_mask()
                        #maybe doing the full keypress (down+up or u+down) worked:
                        if (modifier in new_mask)==press:
                            break

        change_mask(current.difference(wanted), False, "remove")
        change_mask(wanted.difference(current), True, "add")

    def _clear_keys_pressed(self):
        #make sure the timers don't fire and interfere:
        if len(self.keys_repeat_timers)>0:
            for timer in self.keys_repeat_timers.values():
                gobject.source_remove(timer)
            self.keys_repeat_timers = {}
        #clear all the keys we know about:
        if len(self.keys_pressed)>0:
            log.debug("clearing keys pressed: %s", self.keys_pressed)
            for keycode in self.keys_pressed.keys():
                xtest_fake_key(gtk.gdk.display_get_default(), keycode, False)
            self.keys_pressed = {}
        #this will take care of any remaining ones we are not aware of:
        #(there should not be any - but we want to be certain)
        unpress_all_keys(gtk.gdk.display_get_default())

    def _focus(self, wid, modifiers):
        log.debug("_focus(%s,%s) has_focus=%s", wid, modifiers, self._has_focus)
        if self._has_focus != wid:
            def reset_focus():
                self._clear_keys_pressed()
                # FIXME: kind of a hack:
                self._has_focus = 0
                self._wm.get_property("toplevel").reset_x_focus()

            if wid == 0:
                return reset_focus()
            window = self._id_to_window.get(wid)
            if not window:
                return reset_focus()
            #no idea why we can't call this straight away!
            #but with win32 clients, it would often fail!???
            def give_focus():
                window.give_client_focus()
                return False
            gobject.idle_add(give_focus)
            if modifiers is not None:
                self._make_keymask_match(modifiers, self.xkbmap_mod_pointermissing)
            self._has_focus = wid

    def _move_pointer(self, pos):
        (x, y) = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _send(self, packet):
        if self._protocol is not None:
            log("Queuing packet: %s", dump_packet(packet))
            self._protocol.source.queue_ordinary_packet(packet)

    def _damage(self, window, x, y, width, height, options=None):
        if self._protocol is not None and self._protocol.source is not None:
            wid = self._window_to_id[window]
            if options is None:
                options = self.default_damage_options
            self._protocol.source.damage(wid, window, x, y, width, height, options)

    def _cancel_damage(self, wid):
        if self._protocol is not None and self._protocol.source is not None:
            self._protocol.source.cancel_damage(wid)

    def _send_new_window_packet(self, window):
        geometry = self._desktop_manager.window_geometry(window)
        self._do_send_new_window_packet("new-window", window, geometry, self._all_metadata)

    def _send_new_or_window_packet(self, window):
        geometry = window.get_property("geometry")
        properties = ["transient-for", "window-type"]
        self._do_send_new_window_packet("new-override-redirect", window, geometry, properties)
        (_, _, w, h) = geometry
        self._damage(window, 0, 0, w, h)

    def _do_send_new_window_packet(self, ptype, window, geometry, properties):
        wid = self._window_to_id[window]
        (x, y, w, h) = geometry
        metadata = {}
        for propname in properties:
            metadata.update(self._make_metadata(window, propname))
        self._send([ptype, wid, x, y, w, h, metadata])

    def _update_metadata(self, window, pspec):
        wid = self._window_to_id[window]
        metadata = self._make_metadata(window, pspec.name)
        self._send(["window-metadata", wid, metadata])

    def _lost_window(self, window, wm_exiting):
        wid = self._window_to_id[window]
        self._send(["lost-window", wid])
        self._cancel_damage(wid)
        del self._window_to_id[window]
        del self._id_to_window[wid]
        if self._server_source:
            self._server_source.remove_window(wid)

    def _contents_changed(self, window, event):
        if (isinstance(window, OverrideRedirectWindowModel)
            or self._desktop_manager.visible(window)):
            self._damage(window, event.x, event.y, event.width, event.height)

    def _get_desktop_size_capability(self, client_capabilities):
        (root_w, root_h) = gtk.gdk.get_default_root_window().get_size()
        client_size = client_capabilities.get("desktop_size")
        log.info("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
        if not client_size:
            """ client did not specify size, just return what we have """
            return    root_w, root_h
        client_w, client_h = client_size
        if not self.randr:
            """ server does not support randr - return minimum of the client/server dimensions """
            w = min(client_w, root_w)
            h = min(client_h, root_h)
            return    w,h
        log.debug("client resolution is %sx%s, current server resolution is %sx%s", client_w, client_h, root_w, root_h)
        return self.set_screen_size(client_w, client_h)

    def set_screen_size(self, client_w, client_h):
        (root_w, root_h) = gtk.gdk.get_default_root_window().get_size()
        if client_w==root_w and client_h==root_h:
            return    root_w,root_h    #unlikely: perfect match already!
        #try to find the best screen size to resize to:
        new_size = None
        for w,h in get_screen_sizes():
            if w<client_w or h<client_h:
                continue            #size is too small for client
            if new_size:
                ew,eh = new_size
                if ew*eh<w*h:
                    continue        #we found a better (smaller) candidate already
            new_size = w,h
        log.debug("best resolution for client(%sx%s) is: %s", client_w, client_h, new_size)
        if new_size:
            w, h = new_size
            if w==root_w and h==root_h:
                log.info("best resolution for client %sx%s is unchanged: %sx%s", client_w, client_h, w, h)
            else:
                try:
                    set_screen_size(w, h)
                    (root_w, root_h) = get_screen_size()
                    if root_w!=w or root_h!=h:
                        log.error("odd, failed to set the new resolution, "
                                  "tried to set it to %sx%s and ended up with %sx%s", w, h, root_w, root_h)
                    else:
                        log.info("new resolution set for client %sx%s : screen now set to %sx%s", client_w, client_h, root_w, root_h)
                except Exception, e:
                    log.error("ouch, failed to set new resolution: %s", e, exc_info=True)
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return w,h

    def _process_desktop_size(self, proto, packet):
        (width, height) = packet[1:3]
        log.debug("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)

    def _set_encoding(self, encoding, wids):
        if encoding:
            assert encoding in self.encodings, "encoding %s is not supported, client supplied list: %s" % (encoding, self.encodings)
            if encoding not in ENCODINGS:
                log.error("encoding %s is not supported by this server! " \
                         "Will use the first commonly supported encoding instead", encoding)
                encoding = None
        else:
            log.debug("encoding not specified, will use the first match")
        if not encoding:
            #not specified or not supported, find intersection of supported encodings:
            common = [e for e in self.encodings if e in ENCODINGS]
            log.debug("encodings supported by both ends: %s", common)
            if not common:
                raise Exception("cannot find compatible encoding between "
                                "client (%s) and server (%s)" % (self.encodings, ENCODINGS))
            encoding = common[0]
        self.encoding = encoding
        if self._server_source is not None:
            self._server_source.set_new_encoding(encoding, wids)
        log.info("encoding set to %s, client supports %s, server supports %s", encoding, self.encodings, ENCODINGS)

    def _process_encoding(self, proto, packet):
        encoding = packet[1]
        if len(packet)>=3:
            wids = packet[2]
            wids = [wid for wid in wids if wid in self._id_to_window.keys()]
        else:
            wids = None
        self._set_encoding(encoding, wids)

    def _send_password_challenge(self, proto):
        self.salt = "%s" % uuid.uuid4()
        log.info("Password required, sending challenge")
        packet = ("challenge", self.salt)
        proto._add_packet_to_queue(packet)

    def send_disconnect(self, proto, reason):
        def force_disconnect(*args):
            proto.close()
        proto._add_packet_to_queue(["disconnect", reason])
        gobject.timeout_add(1000, force_disconnect)

    def _verify_password(self, proto, client_hash):
        try:
            passwordFile = open(self.password_file, "rU")
        except IOError, e:
            log.error("cannot open password file %s: %s", self.password_file, e)
            self.send_disconnect(proto, "invalid password file specified on server")
            return
        password  = passwordFile.read()
        password_hash = hmac.HMAC(password, self.salt)
        if client_hash != password_hash.hexdigest():
            def login_failed(*args):
                log.error("Password supplied does not match! dropping the connection.")
                self.send_disconnect(proto, "invalid password")
            gobject.timeout_add(1000, login_failed)
            return False
        self.salt = None            #prevent replay attacks
        log.info("Password matches!")
        sys.stdout.flush()
        return True

    def get_info(self):
        info = {"version" : xpra.__version__}
        info["start_time"] = int(self.start_time)
        info["platform"] = sys.platform
        info["windows"] = len(self._id_to_window)
        if self._protocol is None or self._protocol.source is None or self._protocol.source._closed:
            return  info
        self.send_ping()
        source = self._protocol.source
        info["encoding"] = source._encoding
        info["damage_packet_queue_size"] = source._damage_packet_queue.qsize()
        info["damage_request_queue_size"] = source._damage_request_queue.qsize()
        info["damage_data_queue_size"] = source._damage_data_queue.qsize()
        info["input_bytecount"] = self._protocol.input_bytecount
        info["input_packetcount"] = self._protocol.input_packetcount
        info["input_raw_packetcount"] = self._protocol.input_raw_packetcount
        info["output_bytecount"] = self._protocol.output_bytecount
        info["output_packetcount"] = self._protocol.output_packetcount
        info["output_raw_packetcount"] = self._protocol.output_raw_packetcount
        if len(self.server_latency)>0:
            info["min_server_latency"] = min(self.server_latency)
            info["max_server_latency"] = max(self.server_latency)
            info["avg_server_latency"] = sum(self.server_latency)/len(self.server_latency)
        if len(self.client_latency)>0:
            info["min_client_latency"] = min(self.client_latency)
            info["max_client_latency"] = max(self.client_latency)
            info["avg_client_latency"] = sum(self.client_latency)/len(self.client_latency)

        #client pixels per second:
        now = time.time()
        time_limit = now-30             #ignore old records (30s)
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        latest_start_time = 0           #the highest time any of the queues starts from
        for wid in self._id_to_window.keys():
            decode_time_list = source.client_decode_time.get(wid)
            if not decode_time_list:
                continue
            window_pixels = 0           #pixel count
            window_time = 0             #decoding time
            window_start_time = 0
            for when, pixels, decode_time in decode_time_list:
                if when<time_limit or decode_time<=0:
                    continue
                if window_start_time==0:
                    window_start_time = when
                    latest_start_time = max(latest_start_time, when)
                log("wid=%s, pixels=%s in %s", wid, pixels, decode_time)
                window_pixels += pixels
                window_time += decode_time
            log("wid=%s, window_time=%s, window_pixels=%s", wid, window_time, window_pixels)
            log("wid=%s, pixels/s=%s", wid, int(window_pixels *1000*1000 / window_time))
            total_time += window_time
            total_pixels += window_pixels
        log("total_time=%s, total_pixels=%s", total_time, total_pixels)
        if total_time>0:
            pixels_decoded_per_second = int(total_pixels *1000*1000 / total_time)
            info["pixels_decoded_per_second"] = pixels_decoded_per_second
            log("pixels_decoded_per_second=%s", pixels_decoded_per_second)

        if latest_start_time:
            elapsed = now-latest_start_time
            #count all pixels newer than this time
            total_pixels = 0
            for wid in self._id_to_window.keys():
                decode_time_list = source.client_decode_time.get(wid)
                if not decode_time_list:
                    continue
                for when, pixels, decode_time in decode_time_list:
                    if decode_time<=0:
                        continue
                    if when>=latest_start_time:
                        total_pixels += pixels
            pixels_per_second = int(total_pixels/elapsed)
            info["pixels_per_second"] = pixels_per_second
            log("pixels_per_second=%s", pixels_per_second)

        #damage regions per second:
        total_pixels = 0            #pixels processed
        regions_count = 0           #weighted value: sum of (regions count * number of pixels / elapsed time)
        for wid in self._id_to_window.keys():
            last_events = source._damage_last_events.get(wid)
            if not last_events:
                continue
            start_when = 0
            window_regions = 0      #regions for this window
            window_pixels = 0       #pixel count
            for when, pixels in last_events:
                if when<time_limit:
                    continue
                window_regions += 1
                if start_when==0:
                    start_when = when
                log("wid=%s, pixels=%s", wid, pixels)
                window_pixels += pixels
                total_pixels += pixels
            log("wid=%s, window_pixels=%s", wid, window_pixels)
            if start_when>0:
                log("wid=%s, window_pixels=%s, regions=%s, elapsed=%s", wid, window_pixels, window_regions, now-start_when)
                log("wid=%s, regions_per_second=%s", wid, (window_regions/(now-start_when)))
                regions_count += window_pixels*window_regions/(now-start_when)
        log("regions_count=%s, total_pixels=%s", regions_count, total_pixels)
        if regions_count:
            regions_per_second = int(regions_count/total_pixels)
            info["regions_per_second"] = regions_per_second
            log("regions_per_second=%s", regions_per_second)
        return info

    def _process_hello(self, proto, packet):
        capabilities = packet[1]
        log.debug("process_hello: capabilities=%s", capabilities)
        log.info("Handshake complete; enabling connection")
        if capabilities.get("version_request", False):
            response = {"version" : xpra.__version__}
            packet = ["hello", response]
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "version sent")
            return

        remote_version = capabilities.get("__prerelease_version") or capabilities.get("version")
        if not is_compatible_with(remote_version):
            proto.close()
            return
        if self.password_file:
            log.debug("password auth required")
            client_hash = capabilities.get("challenge_response")
            if not client_hash or not self.salt:
                self._send_password_challenge(proto)
                return
            del capabilities["challenge_response"]
            if not self._verify_password(proto, client_hash):
                return

        if capabilities.get("screenshot_request", False):
            #this is a screenshot request, handle it and disconnect
            packet = self.make_screenshot_packet()
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "screenshot sent")
            return
        if capabilities.get("info_request", False):
            packet = ["hello", self.get_info()]
            proto._add_packet_to_queue(packet)
            gobject.timeout_add(5*1000, self.send_disconnect, proto, "info sent")
            return

        # Okay, things are okay, so let's boot out any existing connection and
        # set this as our new one:
        if self._protocol is not None:
            self.disconnect("new valid connection received")
        self.reset_statistics()
        self.encodings = capabilities.get("encodings", [])
        self._set_encoding(capabilities.get("encoding", None), None)
        #mmap:
        self.close_mmap()
        mmap_file = capabilities.get("mmap_file")
        log("client supplied mmap_file=%s, mmap supported=%s", mmap_file, self.supports_mmap)
        if self.supports_mmap and mmap_file and os.path.exists(mmap_file):
            import mmap
            try:
                f = open(mmap_file, "r+b")
                self.mmap_size = os.path.getsize(mmap_file)
                self.mmap = mmap.mmap(f.fileno(), self.mmap_size)
                mmap_token = capabilities.get("mmap_token")
                if mmap_token:
                    #verify the token:
                    v = 0
                    for i in range(0,16):
                        v = v<<8
                        peek = ctypes.c_ubyte.from_buffer(self.mmap, 512+15-i)
                        v += peek.value
                    log.debug("mmap_token=%s, verification=%s", mmap_token, v)
                    if v!=mmap_token:
                        log.error("WARNING: mmap token verification failed, not using mmap area!")
                        self.close_mmap()
                if self.mmap:
                    log.info("using client supplied mmap file=%s, size=%s", mmap_file, self.mmap_size)
            except Exception, e:
                log.error("cannot use mmap file '%s': %s", mmap_file, e)
                self.close_mmap()
        self._protocol = proto
        self._protocol.raw_packets = bool(capabilities.get("raw_packets", False))
        batch_config = DamageBatchConfig()
        batch_config.enabled = bool(capabilities.get("batch.enabled", DamageBatchConfig.ENABLED))
        batch_config.always = bool(capabilities.get("batch.always", False))
        batch_config.min_delay = min(1000, max(1, capabilities.get("batch.min_delay", DamageBatchConfig.MIN_DELAY)))
        batch_config.max_delay = min(15000, max(1, capabilities.get("batch.max_delay", DamageBatchConfig.MAX_DELAY)))
        batch_config.delay = min(1000, max(1, capabilities.get("batch.delay", batch_config.min_delay)))
        batch_config.encoding = self.encoding
        self._server_source = ServerSource(self._protocol, batch_config, self.encoding, self.mmap, self.mmap_size)
        self.send_hello(capabilities)
        if "jpeg" in capabilities:
            self.default_damage_options["jpegquality"] = capabilities["jpeg"]
        self.keyboard = bool(capabilities.get("keyboard", True))
        self.keyboard_sync = bool(capabilities.get("keyboard_sync", True))
        key_repeat = capabilities.get("key_repeat", None)
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat
            if self.key_repeat_delay>0 and self.key_repeat_interval>0:
                set_key_repeat_rate(self.key_repeat_delay, self.key_repeat_interval)
                log.info("setting key repeat rate from client: %s / %s", self.key_repeat_delay, self.key_repeat_interval)
        else:
            #dont do any jitter compensation:
            self.key_repeat_delay = -1
            self.key_repeat_interval = -1
            #but do set a default repeat rate:
            set_key_repeat_rate(500, 30)
        #parse keyboard related options:
        self.xkbmap_layout = capabilities.get("xkbmap_layout")
        self.xkbmap_variant = capabilities.get("xkbmap_variant")
        self.assign_keymap_options(capabilities)

        #always clear modifiers before setting a new keymap
        self._make_keymask_match([])
        self.set_keymap()
        self.send_cursors = capabilities.get("cursors", False)
        self.send_bell = capabilities.get("bell", False)
        self.send_notifications = self.notifications_forwarder is not None and capabilities.get("notifications", False)
        self.clipboard_enabled = capabilities.get("clipboard", True) and self._clipboard_helper is not None
        log.debug("cursors=%s, bell=%s, notifications=%s, clipboard=%s", self.send_cursors, self.send_bell, self.send_notifications, self.clipboard_enabled)
        self._wm.enableCursors(self.send_cursors)
        self.png_window_icons = "png" in self.encodings and "png" in ENCODINGS
        # now we can set the modifiers to match the client
        modifiers = capabilities.get("modifiers", [])
        log.debug("setting modifiers to %s", modifiers)
        self._make_keymask_match(modifiers)
        # We send the new-window packets sorted by id because this sorts them
        # from oldest to newest -- and preserving window creation order means
        # that the earliest override-redirect windows will be on the bottom,
        # which is usually how things work.  (I don't know that anyone cares
        # about this kind of correctness at all, but hey, doesn't hurt.)
        for wid in sorted(self._id_to_window.keys()):
            window = self._id_to_window[wid]
            if isinstance(window, OverrideRedirectWindowModel):
                self._send_new_or_window_packet(window)
            else:
                self._desktop_manager.hide_window(window)
                self._send_new_window_packet(window)
        if self.send_cursors:
            self.send_cursor()

    def send_hello(self, client_capabilities):
        capabilities = {}
        capabilities["version"] = xpra.__version__
        capabilities["desktop_size"] = self._get_desktop_size_capability(client_capabilities)
        capabilities["actual_desktop_size"] = gtk.gdk.get_default_root_window().get_size()
        capabilities["platform"] = sys.platform
        capabilities["clipboard"] = self.clipboard_enabled
        capabilities["encodings"] = ENCODINGS
        capabilities["encoding"] = self.encoding
        capabilities["resize_screen"] = self.randr
        if "key_repeat" in client_capabilities:
            capabilities["key_repeat"] = client_capabilities.get("key_repeat")
        if self.session_name:
            capabilities["session_name"] = self.session_name
        if self.mmap_size>0:
            capabilities["mmap_enabled"] = True
        capabilities["start_time"] = int(self.start_time)
        capabilities["toggle_cursors_bell_notify"] = True
        capabilities["notifications"] = self.notifications_forwarder is not None
        capabilities["png_window_icons"] = "png" in ENCODINGS
        if "key_repeat" in client_capabilities:
            capabilities["key_repeat_modifiers"] = True
        capabilities["raw_packets"] = True
        self._send(["hello", capabilities])

    def send_ping(self):
        self._send(["ping", int(1000*time.time())])

    def _process_ping_echo(self, proto, packet):
        (echoedtime, l1, l2, l3, sl) = packet[1:6]
        diff = int(1000*time.time()-echoedtime)
        self.client_latency.append(diff)
        self.client_load = (l1, l2, l3)
        self.server_latency.append(sl)
        log("ping echo client load=%s, measured server latency=%s", self.client_load, sl)

    def _process_ping(self, proto, packet):
        echotime = packet[1]
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        cl = -1
        if len(self.client_latency)>0:
            cl = self.client_latency[-1]
        self._send(["ping_echo", echotime, l1, l2, l3, cl])
        #if the client is pinging us, ping it too:
        gobject.timeout_add(500, self.send_ping)

    def _process_screenshot(self, proto, packet):
        self.send_screenshot()

    def send_screenshot(self):
        packet = self.make_screenshot_packet()
        self._send(packet)

    def make_screenshot_packet(self):
        log.debug("grabbing screenshot")
        regions = []
        for wid in reversed(sorted(self._id_to_window.keys())):
            window = self._id_to_window[wid]
            pixmap = window.get_property("client-contents")
            if pixmap is None:
                continue
            (x, y, _, _) = self._desktop_manager.window_geometry(window)
            w, h = pixmap.get_size()
            item = (wid, x, y, w, h, pixmap)
            if self._has_focus==wid:
                #window with focus first (drawn last)
                regions.insert(0, item)
            else:
                regions.append(item)
        log.debug("screenshot: found regions=%s", regions)
        if len(regions)==0:
            packet = ["screenshot", 0, 0, "png", -1, ""]
        else:
            minx = min([x for (_,x,_,_,_,_) in regions])
            miny = min([y for (_,_,y,_,_,_) in regions])
            maxx = max([(x+w) for (_,x,_,w,_,_) in regions])
            maxy = max([(y+h) for (_,_,y,_,h,_) in regions])
            width = maxx-minx
            height = maxy-miny
            log.debug("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
            import Image
            image = Image.new("RGBA", (width, height))
            for wid, x, y, w, h, pixmap in reversed(regions):
                (wid, _, _, w, h, _, raw_data, rowstride, _, _) = _get_rgb_rawdata(wid, pixmap, 0, 0, w, h, "rgb24", -1, None)
                window_image = Image.fromstring("RGB", (w, h), raw_data, "raw", "RGB", rowstride)
                tx = x-minx
                ty = y-miny
                image.paste(window_image, (tx, ty))
            buf = StringIO()
            image.save(buf, "png")
            data = buf.getvalue()
            buf.close()
            packet = ["screenshot", width, height, "png", rowstride, data]
        return packet

    def _process_set_notify(self, proto, packet):
        self.send_notifications = bool(packet[1])

    def _process_set_cursors(self, proto, packet):
        self.send_cursors = bool(packet[1])
        self._wm.enableCursors(self.send_cursors)

    def _process_set_bell(self, proto, packet):
        self.send_bell = bool(packet[1])

    def _process_set_deflate(self, proto, packet):
        level = packet[1]
        log.debug("client has requested compression level=%s", level)
        #at this point the client is sending compressed, we have enabled the decompressor
        #we echo it back to set the server's compressor and the client will set its decompressor
        self._send(["set_deflate", level])

    def disconnect(self, reason):
        if self._protocol:
            log.info("Disconnecting existing client, reason is: %s", reason)
            # send message asking client to disconnect (politely):
            self._protocol.flush_then_close(["disconnect", reason])
            #this ensures that from now on we ignore any incoming packets coming
            #from this connection as these could potentially set some keys pressed, etc
            if self._server_source and (self._server_source is self._protocol.source):
                self._server_source.close()
                self._server_source = None
        #so it is now safe to clear them:
        #(this may fail during shutdown - which is ok)
        try:
            self._clear_keys_pressed()
        except:
            pass
        self._focus(0, [])
        log.info("Connection lost")
        self.close_mmap()

    def close_mmap(self):
        if self.mmap:
            self.mmap.close()
            self.mmap = None
        self.mmap_size = 0

    def _process_disconnect(self, proto, packet):
        self.disconnect("on client request")

    def _process_clipboard_enabled_status(self, proto, packet):
        clipboard_enabled = packet[1]
        if self._clipboard_helper:
            self.clipboard_enabled = clipboard_enabled
            log.debug("toggled clipboard to %s", self.clipboard_enabled)
        else:
            log.warn("client toggled clipboard-enabled but we do not support clipboard at all! ignoring it")

    def _process_server_settings(self, proto, packet):
        settings = packet[1]
        old_settings = dict(self._settings)
        self._settings.update(settings)
        for k, v in settings.items():
            if k not in old_settings or v != old_settings[k]:
                def root_set(p):
                    prop_set(gtk.gdk.get_default_root_window(),
                             p, "latin1", v.decode("utf-8"))
                if k == "xsettings-blob":
                    self._xsettings_manager = XSettingsManager(v)
                elif k == "resource-manager":
                    root_set("RESOURCE_MANAGER")
                elif self.pulseaudio:
                    if k == "pulse-cookie":
                        root_set("PULSE_COOKIE")
                    elif k == "pulse-id":
                        root_set("PULSE_ID")
                    elif k == "pulse-server":
                        root_set("PULSE_SERVER")

    def _process_map_window(self, proto, packet):
        (wid, x, y, width, height) = packet[1:6]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._desktop_manager.configure_window(window, x, y, width, height)
        self._desktop_manager.show_window(window)
        self._damage(window, 0, 0, width, height)

    def _process_unmap_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot map window %s: already removed!", wid)
            return
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._cancel_damage(wid)
        self._desktop_manager.hide_window(window)

    def _process_move_window(self, proto, packet):
        (wid, x, y) = packet[1:4]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot move window %s: already removed!", wid)
            return
        assert not isinstance(window, OverrideRedirectWindowModel)
        (_, _, w, h) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)

    def _process_resize_window(self, proto, packet):
        (wid, w, h) = packet[1:4]
        window = self._id_to_window.get(wid)
        if not window:
            log("cannot resize window %s: already removed!", wid)
            return
        assert not isinstance(window, OverrideRedirectWindowModel)
        self._cancel_damage(wid)
        (x, y, _, _) = self._desktop_manager.window_geometry(window)
        self._desktop_manager.configure_window(window, x, y, w, h)
        (_, _, ww, wh) = self._desktop_manager.window_geometry(window)
        visible = self._desktop_manager.visible(window)
        log("resize_window to %sx%s, desktop manager set it to %sx%s, visible=%s", w, h, ww, wh, visible)
        if visible:
            self._damage(window, 0, 0, w, h)

    def _process_focus(self, proto, packet):
        wid = packet[1]
        if len(packet)>=3:
            modifiers = packet[2]
        else:
            modifiers = None
        self._focus(wid, modifiers)

    def _process_layout(self, proto, packet):
        (layout, variant) = packet[1:3]
        if layout!=self.xkbmap_layout or variant!=self.xkbmap_variant:
            self.xkbmap_layout = layout
            self.xkbmap_variant = variant
            self.set_keymap()

    def assign_keymap_options(self, props):
        """ used by both process_hello and process_keymap
            to set the keyboard attributes """
        for x in ["xkbmap_print", "xkbmap_query", "xkbmap_mod_meanings",
                  "xkbmap_mod_managed", "xkbmap_mod_pointermissing", "xkbmap_keycodes"]:
            setattr(self, x, props.get(x))

    def _process_keymap(self, proto, packet):
        props = packet[1]
        self.assign_keymap_options(props)
        modifiers = props.get("modifiers")
        self._make_keymask_match([])
        self.set_keymap()
        self._make_keymask_match(modifiers)


    def _process_key_action(self, proto, packet):
        if not self.keyboard:
            log.info("ignoring key action packet since keyboard is turned off")
            return
        (wid, keyname, pressed, modifiers, keyval, _, client_keycode) = packet[1:8]
        keycode = self.keycode_translation.get(client_keycode, client_keycode)
        #currently unused: (group, is_modifier) = packet[8:10]
        self._focus(wid, None)
        self._make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        #negative keycodes are used for key events without a real keypress/unpress
        #for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode>0:
            self._handle_key(wid, pressed, keyname, keyval, keycode, modifiers)

    def _handle_key(self, wid, pressed, name, keyval, keycode, modifiers):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        log.debug("handle_key(%s,%s,%s,%s,%s,%s)", wid, pressed, name, keyval, keycode, modifiers)
        if pressed and (wid is not None) and (wid not in self._id_to_window):
            log("window %s is gone, ignoring key press", wid)
            return
        if keycode in self.keys_timedout:
            del self.keys_timedout[keycode]
        def press():
            log.debug("handle keycode pressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                self.keys_pressed[keycode] = name
            xtest_fake_key(gtk.gdk.display_get_default(), keycode, True)
        def unpress():
            log.debug("handle keycode unpressing %s: key %s", keycode, name)
            if self.keyboard_sync:
                del self.keys_pressed[keycode]
            xtest_fake_key(gtk.gdk.display_get_default(), keycode, False)
        if pressed:
            if keycode not in self.keys_pressed:
                press()
                if not self.keyboard_sync:
                    #keyboard is not synced: client manages repeat so unpress
                    #it immediately
                    unpress()
            else:
                log.debug("handle keycode %s: key %s was already pressed, ignoring", keycode, name)
        else:
            if keycode in self.keys_pressed:
                unpress()
            else:
                log.debug("handle keycode %s: key %s was already unpressed, ignoring", keycode, name)
        if self.keyboard_sync and keycode>0 and self.key_repeat_delay>0 and self.key_repeat_interval>0:
            self._key_repeat(wid, pressed, name, keyval, keycode, modifiers, self.key_repeat_delay)

    def _key_repeat(self, wid, pressed, keyname, keyval, keycode, modifiers, delay_ms=0):
        """ Schedules/cancels the key repeat timeouts """
        timer = self.keys_repeat_timers.get(keycode, None)
        if timer:
            log.debug("cancelling key repeat timer: %s for %s / %s", timer, keyname, keycode)
            gobject.source_remove(timer)
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            log.debug("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            def _key_repeat_timeout(when):
                now = time.time()
                log.debug("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s", keyname, keycode, now, when, delay_ms)
                self._handle_key(wid, False, keyname, keyval, keycode, modifiers)
                self.keys_timedout[keycode] = now
            now = time.time()
            self.keys_repeat_timers[keycode] = gobject.timeout_add(delay_ms, _key_repeat_timeout, now)

    def _process_key_repeat(self, proto, packet):
        if not self.keyboard:
            log.info("ignoring key repeat packet since keyboard is turned off")
            return
        if len(packet)<6:
            #don't bother trying to make it work with old clients
            if self.keyboard_sync:
                log.info("key repeat data is too small (client is too old), disabling keyboard sync")
                self.keyboard_sync = False
            return
        (wid, keyname, keyval, client_keycode, modifiers) = packet[1:6]
        keycode = self.keycode_translation.get(client_keycode, client_keycode)
        #key repeat uses modifiers from a pointer event, so ignore mod_pointermissing:
        self._make_keymask_match(modifiers, ignored_modifier_keynames=self.xkbmap_mod_pointermissing)
        if not self.keyboard_sync:
            #this check should be redundant: clients should not send key-repeat without
            #having keyboard_sync enabled
            return
        if keycode not in self.keys_pressed:
            #the key is no longer pressed, has it timed out?
            when_timedout = self.keys_timedout.get(keycode, None)
            if when_timedout:
                del self.keys_timedout[keycode]
            now = time.time()
            if when_timedout and (now-when_timedout)<30:
                #not so long ago, just re-press it now:
                log.debug("key %s/%s, had timed out, re-pressing it", keycode, keyname)
                self.keys_pressed[keycode] = keyname
                xtest_fake_key(gtk.gdk.display_get_default(), keycode, True)
        self._key_repeat(wid, True, keyname, keyval, keycode, modifiers, self.key_repeat_interval)

    def _process_button_action(self, proto, packet):
        (wid, button, pressed, pointer, modifiers) = packet[1:6]
        self._make_keymask_match(modifiers, ignored_modifier_keynames=self.xkbmap_mod_pointermissing)
        self._desktop_manager.raise_window(self._id_to_window[wid])
        self._move_pointer(pointer)
        try:
            trap.call_unsynced(xtest_fake_button,
                               gtk.gdk.display_get_default(),
                               button, pressed)
        except XError:
            log.warn("Failed to pass on (un)press of mouse button %s"
                     + " (perhaps your Xvfb does not support mousewheels?)",
                     button)

    def _process_pointer_position(self, proto, packet):
        (wid, pointer, modifiers) = packet[1:4]
        self._make_keymask_match(modifiers, ignored_modifier_keynames=self.xkbmap_mod_pointermissing)
        if wid in self._id_to_window:
            self._desktop_manager.raise_window(self._id_to_window[wid])
            self._move_pointer(pointer)
        else:
            log("_process_pointer_position() invalid window id: %s", wid)

    def _process_close_window(self, proto, packet):
        wid = packet[1]
        window = self._id_to_window.get(wid, None)
        if window:
            window.request_close()
        else:
            log("cannot close window %s: it is already gone!", wid)

    def _process_shutdown_server(self, proto, packet):
        log.info("Shutting down in response to request")
        try:
            proto.close()
        except:
            pass
        self.quit(False)

    def _process_damage_sequence(self, proto, packet):
        packet_sequence = packet[1]
        log("received sequence: %s", packet_sequence)
        if len(packet)>=6:
            wid, width, height, decode_time = packet[2:6]
            log("packet decoding for window %s %sx%s took %s µs", wid, width, height, decode_time)
            client_decode_list = self._server_source.client_decode_time.setdefault(wid, maxdeque(maxlen=20))
            client_decode_list.append((time.time(), width*height, decode_time))
        self._server_source.last_client_packet_sequence = packet_sequence

    def _process_buffer_refresh(self, proto, packet):
        [wid, _, jpeg_qual] = packet[1:4]
        opts = self.default_damage_options.copy()
        if self.encoding=="jpeg":
            opts["jpegquality"] = jpeg_qual
        if wid==-1:
            windows = self._id_to_window.values()
        elif wid in self._id_to_window:
            windows = [self._id_to_window[wid]]
        else:
            return
        log.debug("Requested refresh for windows: %s", windows)
        opts["batching"] = False
        for window in windows:
            if (isinstance(window, OverrideRedirectWindowModel)):
                (_, _, w, h) = window.get_property("geometry")
            else:
                if not self._desktop_manager._models[window].shown:
                    log("window is no longer shown, ignoring buffer refresh which would fail")
                    return
                w, h = window.get_property("actual-size")
            self._damage(window, 0, 0, w, h, opts)

    def _process_jpeg_quality(self, proto, packet):
        quality = packet[1]
        log.debug("Setting JPEG quality to ", quality)
        self.default_damage_options["jpegquality"] = quality

    def _process_connection_lost(self, proto, packet):
        log.info("Connection lost")
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        if proto.source and (proto.source is self._server_source):
            self._server_source.close()
            self._server_source = None
        if proto is self._protocol:
            log.info("xpra client disconnected.")
            self._clear_keys_pressed()
            self._protocol = None
            self._focus(0, [])
        sys.stdout.flush()

    def _process_gibberish(self, proto, packet):
        data = packet[1]
        log.info("Received uninterpretable nonsense: %s", repr(data))

    _default_packet_handlers = {
        "hello": _process_hello,
        Protocol.CONNECTION_LOST: _process_connection_lost,
        Protocol.GIBBERISH: _process_gibberish,
        }
    _authenticated_packet_handlers = {
        "hello": _process_hello,
        "server-settings": _process_server_settings,
        "map-window": _process_map_window,
        "unmap-window": _process_unmap_window,
        "move-window": _process_move_window,
        "resize-window": _process_resize_window,
        "focus": _process_focus,
        "key-action": _process_key_action,
        "key-repeat": _process_key_repeat,
        "layout-changed": _process_layout,
        "keymap-changed": _process_keymap,
        "set-clipboard-enabled": _process_clipboard_enabled_status,
        "button-action": _process_button_action,
        "pointer-position": _process_pointer_position,
        "close-window": _process_close_window,
        "shutdown-server": _process_shutdown_server,
        "jpeg-quality": _process_jpeg_quality,
        "damage-sequence": _process_damage_sequence,
        "buffer-refresh": _process_buffer_refresh,
        "screenshot": _process_screenshot,
        "desktop_size": _process_desktop_size,
        "encoding": _process_encoding,
        "ping": _process_ping,
        "ping_echo": _process_ping_echo,
        "set_deflate": _process_set_deflate,
        "set-cursors": _process_set_cursors,
        "set-notify": _process_set_notify,
        "set-bell": _process_set_bell,
        "disconnect": _process_disconnect,
        # "clipboard-*" packets are handled below:
        Protocol.CONNECTION_LOST: _process_connection_lost,
        Protocol.GIBBERISH: _process_gibberish,
        }

    def process_packet(self, proto, packet):
        packet_type = packet[0]
        assert isinstance(packet_type, str)
        if packet_type.startswith("clipboard-"):
            if self.clipboard_enabled:
                self._clipboard_helper.process_clipboard_packet(packet)
            return
        if proto is self._protocol:
            handlers = self._authenticated_packet_handlers
        else:
            handlers = self._default_packet_handlers
        handler = handlers.get(packet_type)
        if not handler:
            log.error("unknown or invalid packet type: %s", packet_type)
            if proto is not self._protocol:
                proto.close()
            return
        handler(self, proto, packet)

gobject.type_register(XpraServer)
