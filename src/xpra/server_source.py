# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
gtk.gdk.threads_init()

import hashlib
import time
import gobject
import ctypes
try:
    from queue import Queue         #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue         #@Reimport
from collections import deque

from wimpiggy.log import Logger
log = Logger()

try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport

from xpra.deque import maxdeque
from xpra.window_source import WindowSource, DamageBatchConfig
from xpra.maths import add_list_stats, dec1, std_unit
from xpra.scripts.main import ENCODINGS
from xpra.protocol import zlib_compress, Compressed

from wimpiggy.keys import grok_modifier_map
from xpra.keys import mask_to_names, DEFAULT_MODIFIER_NUISANCE, ALL_X11_MODIFIERS
from xpra.xkbhelper import do_set_keymap, set_all_keycodes, \
                           get_modifiers_from_meanings, get_modifiers_from_keycodes, \
                           clear_modifiers, set_modifiers, \
                           clean_keyboard_state
from wimpiggy.lowlevel import xtest_fake_key, get_modifier_mappings     #@UnresolvedImport


def start_daemon_thread(target, name):
    from threading import Thread
    t = Thread(target=target)
    t.name = name
    t.daemon = True
    t.start()
    return t

import os
NOYIELD = os.environ.get("XPRA_YIELD") is None

NRECS = 500


debug = log.debug

class KeyboardConfig(object):
    def __init__(self):
        self.xkbmap_print = None
        self.xkbmap_query = None
        self.xkbmap_mod_meanings = {}
        self.xkbmap_mod_managed = []
        self.xkbmap_mod_pointermissing = []
        self.xkbmap_keycodes = []
        self.xkbmap_x11_keycodes = []
        self.xkbmap_layout = None
        self.xkbmap_variant = None

        self.enabled = True
        #this is shared between clients!
        self.keys_pressed = {}
        #these are derived by calling set_keymap:
        self.keynames_for_mod = None
        self.keycode_translation = {}
        self.keycodes_for_modifier_keynames = {}
        self.modifier_client_keycodes = {}
        self.compute_modifier_map()
        self.make_modifiers_match = True
        self.is_native_keymap = True

    def get_hash(self):
        m = hashlib.md5()
        for x in (self.xkbmap_print, self.xkbmap_query, \
                  self.xkbmap_mod_meanings, self.xkbmap_mod_pointermissing, \
                  self.xkbmap_keycodes, self.xkbmap_x11_keycodes):
            m.update("/%s" % str(x))
        return "%s/%s/%s" % (self.xkbmap_layout, self.xkbmap_variant, m.hexdigest())

    def compute_modifier_keynames(self):
        self.keycodes_for_modifier_keynames = {}
        keymap = gtk.gdk.keymap_get_default()
        if self.keynames_for_mod:
            for modifier, keynames in self.keynames_for_mod.items():
                for keyname in keynames:
                    keyval = gtk.gdk.keyval_from_name(keyname)
                    if keyval==0:
                        log.error("no keyval found for keyname %s (modifier %s)", keyname, modifier)
                        return  []
                    entries = keymap.get_entries_for_keyval(keyval)
                    if entries:
                        for keycode, _, _ in entries:
                            self.keycodes_for_modifier_keynames.setdefault(keyname, set()).add(keycode)
        debug("compute_modifier_keynames: keycodes_for_modifier_keynames=%s", self.keycodes_for_modifier_keynames)

    def compute_client_modifier_keycodes(self):
        """ The keycodes for all modifiers (those are *client* keycodes!) """
        try:
            server_mappings = get_modifier_mappings()
            log("get_modifier_mappings=%s", server_mappings)
            #update the mappings to use the keycodes the client knows about:
            reverse_trans = {}
            for k,v in self.keycode_translation.items():
                reverse_trans[v] = k
            self.modifier_client_keycodes = {}
            for modifier, keys in server_mappings.items():
                client_keycodes = []
                for keycode,keyname in keys:
                    client_keycode = reverse_trans.get(keycode, keycode)
                    if client_keycode:
                        client_keycodes.append((client_keycode, keyname))
                self.modifier_client_keycodes[modifier] = client_keycodes
            log("compute_client_modifier_keycodes() mappings=%s", self.modifier_client_keycodes)
        except Exception, e:
            log.error("do_set_keymap: %s" % e, exc_info=True)

    def compute_modifier_map(self):
        self.modifier_map = grok_modifier_map(gtk.gdk.display_get_default(), self.xkbmap_mod_meanings)
        debug("modifier_map(%s)=%s", self.xkbmap_mod_meanings, self.modifier_map)


    def set_keymap(self, client_platform):
        if not self.enabled:
            return
        clean_keyboard_state()
        try:
            do_set_keymap(self.xkbmap_layout, self.xkbmap_variant,
                          self.xkbmap_print, self.xkbmap_query)
        except:
            log.error("error setting new keymap", exc_info=True)
        self.is_native_keymap = self.xkbmap_print!="" or self.xkbmap_query!=""
        self.make_modifiers_match = (client_platform and not client_platform.startswith("win")) or self.is_native_keymap
        try:
            #first clear all existing modifiers:
            clean_keyboard_state()
            clear_modifiers(ALL_X11_MODIFIERS.keys())       #just clear all of them (set or not)

            #now set all the keycodes:
            clean_keyboard_state()
            self.keycode_translation = {}

            has_keycodes = (self.xkbmap_x11_keycodes and len(self.xkbmap_x11_keycodes)>0) or \
                            (self.xkbmap_keycodes and len(self.xkbmap_keycodes)>0)
            assert has_keycodes, "client failed to provide any keycodes!"
            #first compute the modifier maps as this may have an influence
            #on the keycode mappings (at least for the from_keycodes case):
            if self.xkbmap_mod_meanings:
                #Unix-like OS provides modifier meanings:
                self.keynames_for_mod = get_modifiers_from_meanings(self.xkbmap_mod_meanings)
            elif self.xkbmap_keycodes:
                #non-Unix-like OS provides just keycodes for now:
                self.keynames_for_mod = get_modifiers_from_keycodes(self.xkbmap_keycodes)
            else:
                log.error("missing both xkbmap_mod_meanings and xkbmap_keycodes, modifiers will probably not work as expected!")
                self.keynames_for_mod = {}
            #if the client does not provide a full keymap,
            #try to preserve the initial server keycodes
            #(used by non X11 clients like osx,win32 or Android)
            preserve_server_keycodes = not self.xkbmap_print and not self.xkbmap_query
            self.keycode_translation = set_all_keycodes(self.xkbmap_x11_keycodes, self.xkbmap_keycodes, preserve_server_keycodes, self.keynames_for_mod)

            #now set the new modifier mappings:
            clean_keyboard_state()
            log("going to set modifiers, xkbmap_mod_meanings=%s, len(xkbmap_keycodes)=%s", self.xkbmap_mod_meanings, len(self.xkbmap_keycodes or []))
            if self.keynames_for_mod:
                set_modifiers(self.keynames_for_mod)
            self.compute_modifier_keynames()
            self.compute_client_modifier_keycodes()
            log("keyname_for_mod=%s", self.keynames_for_mod)
        except:
            log.error("error setting xmodmap", exc_info=True)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
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
        def get_current_mask():
            _, _, current_mask = gtk.gdk.get_default_root_window().get_pointer()
            modifiers = mask_to_names(current_mask, self.modifier_map)
            debug("get_modifier_mask()=%s", modifiers)
            return modifiers

        if not self.keynames_for_mod:
            debug("make_keymask_match: ignored as keynames_for_mod not assigned yet")
            return
        if not self.make_modifiers_match:
            debug("make_keymask_match: ignored - current mask=%s", get_current_mask())
            return
        if ignored_modifier_keynames is None:
            ignored_modifier_keynames = self.xkbmap_mod_pointermissing

        def is_ignored(modifier_keynames):
            if not ignored_modifier_keynames:
                return False
            for imk in ignored_modifier_keynames:
                if imk in modifier_keynames:
                    debug("modifier ignored (ignored keyname=%s)", imk)
                    return True
            return False


        current = set(get_current_mask())
        wanted = set(modifier_list)
        if current==wanted:
            return
        debug("make_keymask_match(%s) current mask: %s, wanted: %s, ignoring=%s/%s, keys_pressed=%s", modifier_list, current, wanted, ignored_modifier_keycode, ignored_modifier_keynames, self.keys_pressed)
        display = gtk.gdk.display_get_default()

        def change_mask(modifiers, press, info):
            for modifier in modifiers:
                if self.xkbmap_mod_managed and modifier in self.xkbmap_mod_managed:
                    debug("modifier is server managed: %s", modifier)
                    continue
                keynames = self.keynames_for_mod.get(modifier)
                if not keynames:
                    log.error("unknown modifier: %s", modifier)
                    continue
                if is_ignored(keynames):
                    debug("modifier %s ignored (in ignored keynames=%s)", modifier, keynames)
                    continue
                #find the keycodes that match the keynames for this modifier
                keycodes = []
                #log.info("keynames(%s)=%s", modifier, keynames)
                for keyname in keynames:
                    if keyname in self.keys_pressed.values():
                        #found the key which was pressed to set this modifier
                        for keycode, name in self.keys_pressed.items():
                            if name==keyname:
                                debug("found the key pressed for %s: %s", modifier, name)
                                keycodes.insert(0, keycode)
                    keycodes_for_keyname = self.keycodes_for_modifier_keynames.get(keyname)
                    if keycodes_for_keyname:
                        for keycode in keycodes_for_keyname:
                            if keycode not in keycodes:
                                keycodes.append(keycode)
                if ignored_modifier_keycode is not None and ignored_modifier_keycode in keycodes:
                    debug("modifier %s ignored (ignored keycode=%s)", modifier, ignored_modifier_keycode)
                    continue
                #nuisance keys (lock, num, scroll) are toggled by a
                #full key press + key release (so act accordingly in the loop below)
                nuisance = modifier in DEFAULT_MODIFIER_NUISANCE
                debug("keynames(%s)=%s, keycodes=%s, nuisance=%s", modifier, keynames, keycodes, nuisance)
                for keycode in keycodes:
                    if nuisance:
                        xtest_fake_key(display, keycode, True)
                        xtest_fake_key(display, keycode, False)
                    else:
                        xtest_fake_key(display, keycode, press)
                    new_mask = get_current_mask()
                    success = (modifier in new_mask)==press
                    debug("make_keymask_match(%s) %s modifier %s using %s, success: %s", info, modifier_list, modifier, keycode, success)
                    if success:
                        break
                    elif not nuisance:
                        debug("%s %s with keycode %s did not work - trying to undo it!", info, modifier, keycode)
                        xtest_fake_key(display, keycode, not press)
                        new_mask = get_current_mask()
                        #maybe doing the full keypress (down+up or u+down) worked:
                        if (modifier in new_mask)==press:
                            break

        change_mask(current.difference(wanted), False, "remove")
        change_mask(wanted.difference(current), True, "add")



class GlobalPerformanceStatistics(object):
    """
    Statistics which are shared by all WindowSources
    """
    def __init__(self):
        self.reset()

    def reset(self):
        # mmap state:
        self.mmap_size = 0
        self.mmap_bytes_sent = 0
        self.mmap_free_size = 0                        #how much of the mmap space is left (may be negative if we failed to write the last chunk)
        # queue statistics:
        self.damage_data_qsizes = maxdeque(NRECS)       #size of the damage_data_queue before we add a new record to it
                                                        #(event_time, size)
        self.damage_packet_qsizes = maxdeque(NRECS)     #size of the damage_packet_queue before we add a new packet to it
                                                        #(event_time, size)
        self.damage_packet_qpixels = maxdeque(NRECS)    #number of pixels waiting in the damage_packet_queue for a specific window,
                                                        #before we add a new packet to it
                                                        #(event_time, wid, size)
        self.damage_last_events = maxdeque(NRECS)       #records the x11 damage requests as they are received:
                                                        #(wid, event time, no of pixels)
        self.client_decode_time = maxdeque(NRECS)       #records how long it took the client to decode frames:
                                                        #(wid, event_time, no of pixels, decoding_time*1000*1000)
        self.min_client_latency = None                  #The lowest client latency ever recorded: the time it took
                                                        #from the moment the damage packet got sent until we got the ack packet
                                                        #(but not including time spent decoding on the client)
        self.client_latency = maxdeque(NRECS)           #how long it took for a packet to get to the client and get the echo back.
                                                        #(wid, event_time, no of pixels, client_latency)
        self.avg_client_latency = None
        self.client_ping_latency = maxdeque(NRECS)      #time it took to get a ping_echo back from the client:
                                                        #(event_time, elapsed_time_in_seconds)
        self.server_ping_latency = maxdeque(NRECS)      #time it took for the client to get a ping_echo back from us:
                                                        #(event_time, elapsed_time_in_seconds)
        self.client_load = None

    def record_latency(self, wid, decode_time, start_send_at, end_send_at, pixels, bytecount):
        now = time.time()
        send_diff = now-start_send_at
        echo_diff = now-end_send_at
        send_latency = max(0, send_diff-decode_time/1000.0/1000.0)
        echo_latency = max(0, echo_diff-decode_time/1000.0/1000.0)
        log("record_latency: took %s ms round trip (%s just for echo), %s for decoding of %s pixels, %s bytes sent over the network in %s ms (%s ms for echo)",
                dec1(send_diff*1000), dec1(echo_diff*1000), dec1(decode_time/1000.0), pixels, bytecount, dec1(send_latency*1000), dec1(echo_latency*1000))
        if self.min_client_latency is None or self.min_client_latency>send_latency:
            self.min_client_latency = send_latency
        self.client_latency.append((wid, time.time(), pixels, send_latency))

    def add_stats(self, info, suffix=""):
        info["output_mmap_bytecount%s" % suffix] = self.mmap_bytes_sent
        if self.min_client_latency is not None:
            info["client_latency%s.absmin" % suffix] = int(self.min_client_latency*1000)
        qsizes = [x for _,x in list(self.damage_data_qsizes)]
        add_list_stats(info, "damage_data_queue_size%s" % suffix,  qsizes)
        qsizes = [x for _,x in list(self.damage_packet_qsizes)]
        add_list_stats(info, "damage_packet_queue_size%s" % suffix,  qsizes)
        latencies = [x*1000 for (_, _, _, x) in list(self.client_latency)]
        add_list_stats(info, "client_latency%s" % suffix,  latencies)

        add_list_stats(info, "server_ping_latency%s" % suffix, [1000.0*x for _, x in list(self.server_ping_latency)])
        add_list_stats(info, "client_ping_latency%s" % suffix, [1000.0*x for _, x in list(self.client_ping_latency)])

        #client pixels per second:
        now = time.time()
        time_limit = now-30             #ignore old records (30s)
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        start_time = None               #when we start counting from (oldest record)
        region_sizes = []
        for _, event_time, pixels, decode_time in list(self.client_decode_time):
            #time filter and ignore failed decoding (decode_time==0)
            if event_time<time_limit or decode_time<=0:
                continue
            if start_time is None or start_time>event_time:
                start_time = event_time
            total_pixels += pixels
            total_time += decode_time
            region_sizes.append(pixels)
        log("total_time=%s, total_pixels=%s", total_time, total_pixels)
        if total_time>0:
            pixels_decoded_per_second = int(total_pixels *1000*1000 / total_time)
            info["pixels_decoded_per_second%s" % suffix] = pixels_decoded_per_second
        if start_time:
            elapsed = now-start_time
            pixels_per_second = int(total_pixels/elapsed)
            info["pixels_per_second%s" % suffix] = pixels_per_second
            info["regions_per_second%s" % suffix] = int(len(region_sizes)/elapsed)
            info["average_region_size%s" % suffix] = int(total_pixels/len(region_sizes))


class ServerSource(object):
    """
    A ServerSource mediates between the server (which only knows about windows)
    and the WindowSource (which only knows about window ids) instances
    which manage damage data processing.
    It sends damage pixels to the client via its 'protocol' instance (network connection).

    Strategy: if we have 'ordinary_packets' to send, send those.
    When we don't, then send window updates from the 'damage_packet_queue'.
    See 'next_packet'.

    The UI thread calls damage(), which goes into WindowSource and eventually (batching may be involved)
    adds the damage pixels ready for processing to the damage_data_queue,
    items are picked off by the separate 'data_to_packet' thread and added to the
    damage_packet_queue.
    """

    def __init__(self, protocol, get_transient_for,
                 supports_mmap,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality):
        self.closed = False
        self.ordinary_packets = []
        self.protocol = protocol
        self.get_transient_for = get_transient_for
        # mmap:
        self.supports_mmap = supports_mmap
        self.mmap = None
        self.mmap_size = 0
        # sound:
        self.supports_speaker = supports_speaker
        self.speaker_codecs = speaker_codecs
        self.supports_microphone = supports_microphone
        self.microphone_codecs = microphone_codecs
        self.sound_source = None
        self.sound_sink = None

        self.default_quality = default_quality      #default encoding quality for lossless encodings
        self.encoding = None                        #the default encoding for all windows
        self.encodings = []                         #all the encodings supported by the client
        self.encoding_options = {}
        self.default_batch_config = DamageBatchConfig()
        self.default_damage_options = {}

        self.window_sources = {}                    #WindowSource for each Window ID

        self.uuid = ""
        self.hostname = ""
        self.fqdn = ""
        # client capabilities/options:
        self.client_type = None
        self.client_version = None
        self.client_platform = None
        self.png_window_icons = False
        self.auto_refresh_delay = 0
        self.server_window_resize = False
        self.send_cursors = False
        self.send_bell = False
        self.send_notifications = False
        self.send_windows = True
        self.randr_notify = False
        self.named_cursors = False
        self.clipboard_enabled = False
        self.share = False
        self.desktop_size = None
        self.screen_sizes = []
        self.raw_window_icons = False
        self.system_tray = False
        #sound props:
        self.pulseaudio_id = None
        self.pulseaudio_server = None
        self.sound_decoders = []
        self.sound_encoders = []

        self.keyboard_config = None

        # the queues of damage requests we work through:
        self.damage_data_queue = Queue()           #holds functions to call to process damage data
                                                    #items placed in this queue are picked off by the "data_to_packet" thread,
                                                    #the functions should add the packets they generate to the 'damage_packet_queue'
        self.damage_packet_queue = deque()         #holds actual packets ready for sending (already encoded)
                                                    #these packets are picked off by the "protocol" via 'next_packet()'
                                                    #format: packet, wid, pixels, start_send_cb, end_send_cb
        #these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()
        # ready for processing:
        protocol.source = self
        self.datapacket_thread = start_daemon_thread(self.data_to_packet, "data_to_packet")

    def close(self):
        self.closed = True
        self.damage_data_queue.put(None, block=False)
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}
        self.close_mmap()
        self.protocol = None
        self.stop_sending_sound()

    def parse_hello(self, capabilities):
        #batch options:
        self.default_batch_config = DamageBatchConfig()
        self.default_batch_config.always = bool(capabilities.get("batch.always", False))
        self.default_batch_config.min_delay = min(1000, max(1, capabilities.get("batch.min_delay", DamageBatchConfig.MIN_DELAY)))
        self.default_batch_config.max_delay = min(15000, max(1, capabilities.get("batch.max_delay", DamageBatchConfig.MAX_DELAY)))
        self.default_batch_config.delay = min(1000, max(1, capabilities.get("batch.delay", DamageBatchConfig.START_DELAY)))
        #client uuid:
        self.uuid = capabilities.get("uuid", "")
        self.hostname = capabilities.get("hostname", "")
        self.fqdn = capabilities.get("fqdn", "")
        self.client_type = capabilities.get("client_type", "PyGTK")
        self.client_platform = capabilities.get("platform", "")
        self.client_version = capabilities.get("version", None)
        #general features:
        self.send_windows = capabilities.get("windows", True)
        self.server_window_resize = capabilities.get("server-window-resize", False)
        self.send_cursors = self.send_windows and capabilities.get("cursors", False)
        self.send_bell = capabilities.get("bell", False)
        self.send_notifications = capabilities.get("notifications", False)
        self.randr_notify = capabilities.get("randr_notify", False)
        self.clipboard_enabled = capabilities.get("clipboard", True)
        self.share = capabilities.get("share", False)
        self.desktop_size = capabilities.get("desktop_size")
        self.set_screen_sizes(capabilities.get("screen_sizes"))
        self.named_cursors = capabilities.get("named_cursors", False)
        self.raw_window_icons = capabilities.get("raw_window_icons", False)
        self.system_tray = capabilities.get("system_tray", False)
        #encoding options (filter):
        for k, v in capabilities.items():
            #these properties are special cased here because we
            #defined their name before the "encoding." prefix convention:
            if k in ("initial_quality", "rgb24zlib", "uses_swscale", "encoding_client_options"):
                self.encoding_options[k] = v
            elif k.startswith("encoding."):
                k = k[len("encoding."):]
                self.encoding_options[k] = v
        #encodings:
        self.encodings = capabilities.get("encodings", [])
        self.set_encoding(capabilities.get("encoding", None), None)
        q = self.default_quality
        if "jpeg" in capabilities:      #pre 0.7 versions
            q = capabilities["jpeg"]
        if "quality" in capabilities:   #0.7 onwards:
            q = capabilities["quality"]
        if q>=0:
            self.default_damage_options["quality"] = q
        self.png_window_icons = "png" in self.encodings and "png" in ENCODINGS
        self.auto_refresh_delay = int(capabilities.get("auto_refresh_delay", 0)/1000.0)
        #keyboard:
        self.keyboard_config = KeyboardConfig()
        self.keyboard_config.enabled = self.send_windows and bool(capabilities.get("keyboard", True))
        self.assign_keymap_options(capabilities)
        self.keyboard_config.xkbmap_layout = capabilities.get("xkbmap_layout")
        self.keyboard_config.xkbmap_variant = capabilities.get("xkbmap_variant")
        #mmap:
        if self.send_windows:
            #we don't need mmap if not sending pixels
            mmap_file = capabilities.get("mmap_file")
            mmap_token = capabilities.get("mmap_token")
            log("client supplied mmap_file=%s, mmap supported=%s", mmap_file, self.supports_mmap)
            if self.supports_mmap and mmap_file and os.path.exists(mmap_file):
                self.init_mmap(mmap_file, mmap_token)
        log("cursors=%s, bell=%s, notifications=%s", self.send_cursors, self.send_bell, self.send_notifications)
        log("client uuid %s", self.uuid)
        msg = "%s %s client version %s" % (self.client_type, self.client_platform, self.client_version)
        if self.fqdn:
            msg += " connected from '%s'" % self.fqdn
        log.info(msg)
        if self.send_windows:
            if self.mmap_size>0:
                log.info("mmap is enabled using %sBytes area in %s", std_unit(self.mmap_size), mmap_file)
            else:
                log.info("using %s as primary encoding", self.encoding)
        else:
            log.info("windows forwarding is disabled")
        #sound stuff:
        self.pulseaudio_id = capabilities.get("sound.pulseaudio.id")
        self.pulseaudio_server = capabilities.get("sound.pulseaudio.server")
        self.sound_decoders = capabilities.get("sound.decoders", [])
        self.sound_encoders = capabilities.get("sound.encoders", [])
        self.sound_receive = capabilities.get("sound.receive", False)
        self.sound_send = capabilities.get("sound.send", False)

    def start_sending_sound(self):
        assert self.supports_speaker
        assert self.sound_source is None
        assert self.sound_receive
        try:
            from xpra.sound.gstreamer_util import start_sending_sound
            self.sound_source = start_sending_sound(self.sound_decoders, self.microphone_codecs, self.pulseaudio_server, self.pulseaudio_id)
            if self.sound_source:
                self.sound_source.connect("new-buffer", self.new_sound_buffer)
                self.sound_source.start()
        except Exception, e:
            log.error("error setting up sound: %s", e)

    def stop_sending_sound(self):
        if self.sound_source:
            self.sound_source.stop()
            self.sound_source.cleanup()
            self.sound_source = None

    def new_sound_buffer(self, sound_source, data):
        assert self.sound_source
        self.idle_send("sound-data", self.sound_source.codec, Compressed(self.sound_source.codec, data))

    def sound_control(self, action, *args):
        if action=="stop":
            self.stop_sending_sound()
        elif action=="start":
            self.start_sending_sound()
        #elif action=="quality":
        #    assert self.sound_source
        #    quality = args[0]
        #    self.sound_source.set_quality(quality)
        #    self.start_sending_sound()
        else:
            log.error("unkown sound action: %s", action)

    def sound_data(self, codec, data, *args):
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.info("sound codec changed from %s to %s", self.sound_sink.codec, codec)
            self.sound_sink.stop()
            self.sound_sink.cleanup()
            self.sound_sink = None
        if not self.sound_sink:
            try:
                from xpra.sound.sink import SoundSink
                self.sound_sink = SoundSink(codec=codec)
                self.sound_sink.start()
            except Exception, e:
                log.error("failed to setup sound: %s", e)
                return
        self.sound_sink.add_data(data)

    def set_screen_sizes(self, screen_sizes):
        self.screen_sizes = screen_sizes or []
        log("client screen sizes: %s", screen_sizes)

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property:
    def _make_metadata(self, window, propname):
        if propname == "title":
            title = window.get_property("title")
            if title is None:
                return {}
            return {"title": title.encode("utf-8")}
        elif propname == "modal":
            return {"modal" : window.get_property("modal")}
        elif propname == "size-hints":
            hints_metadata = {}
            hints = window.get_property("size-hints")
            if hints is not None:
                for attr, metakey in [
                    ("max_size", "maximum-size"),
                    ("min_size", "minimum-size"),
                    ("base_size", "base-size"),
                    ("resize_inc", "increment"),
                    ("min_aspect", "minimum-aspect"),
                    ("max_aspect", "maximum-aspect"),
                    ("min_aspect_ratio", "minimum-aspect-ratio"),
                    ("max_aspect_ratio", "maximum-aspect-ratio"),
                    ]:
                    v = getattr(hints, attr)
                    if v is not None:
                        hints_metadata[metakey] = v
            return {"size-constraints": hints_metadata}
        elif propname == "class-instance":
            c_i = window.get_property("class-instance")
            if c_i is None:
                return {}
            return {"class-instance": [x.encode("utf-8") for x in c_i]}
        elif propname == "icon":
            surf = window.get_property("icon")
            if surf is None:
                return {}
            return {"icon": self.make_window_icon(surf.get_data(), surf.get_format(), surf.get_stride(), surf.get_width(), surf.get_height())}
        elif propname == "client-machine":
            client_machine = window.get_property("client-machine")
            if client_machine is None:
                return {}
            return {"client-machine": client_machine.encode("utf-8")}
        elif propname == "transient-for":
            wid = self.get_transient_for(window)
            if wid:
                return {"transient-for" : wid}
            return {}
        elif propname == "window-type":
            window_types = window.get_property("window-type")
            assert window_types is not None, "window-type is not defined for %s" % window
            log("window_types=%s", window_types)
            wts = []
            for window_type in window_types:
                wts.append(str(window_type))
            log("window_types=%s", wts)
            return {"window-type" : wts}
        raise Exception("unhandled property name: %s" % propname)


    def make_window_icon(self, pixel_data, pixel_format, stride, w, h):
        log("found new window icon: %sx%s, sending as png=%s", w, h, self.png_window_icons)
        if self.png_window_icons:
            import Image
            img = Image.frombuffer("RGBA", (w,h), pixel_data, "raw", "BGRA", 0, 1)
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
            output.close()
            return w, h, "png", str(raw_data)
        import cairo
        assert pixel_format == cairo.FORMAT_ARGB32
        assert stride == 4 * w
        return w, h, "premult_argb32", str(pixel_data)

#
# Keyboard magic
#
    def set_layout(self, layout, variant):
        if layout!=self.keyboard_config.xkbmap_layout or variant!=self.keyboard_config.xkbmap_variant:
            self.keyboard_config.xkbmap_layout = layout
            self.keyboard_config.xkbmap_variant = variant
            return True
        return False

    def assign_keymap_options(self, props):
        """ used by both process_hello and process_keymap
            to set the keyboard attributes """
        modded = False
        for x in ["xkbmap_print", "xkbmap_query", "xkbmap_mod_meanings",
                  "xkbmap_mod_managed", "xkbmap_mod_pointermissing",
                  "xkbmap_keycodes", "xkbmap_x11_keycodes"]:
            cv = getattr(self.keyboard_config, x)
            nv = props.get(x)
            if cv!=nv:
                setattr(self.keyboard_config, x, nv)
                modded = True
        return modded

    def keys_changed(self):
        self.keyboard_config.compute_modifier_map()
        self.keyboard_config.compute_modifier_keynames()

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        if self.keyboard_config.enabled:
            self.keyboard_config.make_keymask_match(modifier_list, ignored_modifier_keycode, ignored_modifier_keynames)

    def set_keymap(self, current_keyboard_config, keys_pressed, force):
        if self.keyboard_config.enabled:
            current_id = None
            if current_keyboard_config and current_keyboard_config.enabled:
                current_id = current_keyboard_config.get_hash()
            keymap_id = self.keyboard_config.get_hash()
            log("current keyboard id=%s, new keyboard id=%s", current_id, keymap_id)
            if force or current_id is None or keymap_id!=current_id:
                self.keyboard_config.keys_pressed = keys_pressed
                self.keyboard_config.set_keymap(self.client_platform)
                current_keyboard_config = self.keyboard_config
            else:
                log.info("keyboard mapping already configured (skipped)")
                self.keyboard_config = current_keyboard_config
        return current_keyboard_config

    def get_keycode(self, client_keycode, keyname, modifiers):
        if not self.keyboard_config.enabled:
            log.info("ignoring keycode since keyboard is turned off")
            return -1
        server_keycode = self.keyboard_config.keycode_translation.get((client_keycode, keyname))
        if server_keycode is None:
            if self.keyboard_config.is_native_keymap:
                #native: assume no translation for this key
                server_keycode = client_keycode
            else:
                #non-native: try harder to find matching keysym
                server_keycode = self.keyboard_config.keycode_translation.get(keyname, client_keycode)
        return server_keycode


#
# Functions for interacting with the network layer:
#
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, have_more = None, None, None, False
        if not self.closed:
            if len(self.ordinary_packets)>0:
                packet = self.ordinary_packets.pop(0)
            elif len(self.damage_packet_queue)>0:
                packet, _, _, start_send_cb, end_send_cb = self.damage_packet_queue.popleft()
            have_more = packet is not None and (len(self.ordinary_packets)>0 or len(self.damage_packet_queue)>0)
        return packet, start_send_cb, end_send_cb, have_more

    def idle_send(self, *parts):
        gobject.idle_add(self.send, *parts)

    def send(self, *parts):
        """ This method queues non-damage packets (higher priority) """
        self.ordinary_packets.append(parts)
        if self.protocol:
            self.protocol.source_has_more()

#
# Functions used by the server to request something
# (window events, stats, user requests, etc)
#
    def set_encoding(self, encoding, window_ids):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        if encoding:
            assert encoding in self.encodings, "encoding %s is not supported, client supplied list: %s" % (encoding, self.encodings)
            if encoding not in ENCODINGS:
                log.error("encoding %s is not supported by this server! " \
                         "Will use the first commonly supported encoding instead", encoding)
                encoding = None
        else:
            log("encoding not specified, will use the first match")
        if not encoding:
            #not specified or not supported, find intersection of supported encodings:
            common = [e for e in self.encodings if e in ENCODINGS]
            log("encodings supported by both ends: %s", common)
            if not common:
                raise Exception("cannot find compatible encoding between "
                                "client (%s) and server (%s)" % (self.encodings, ENCODINGS))
            encoding = common[0]
        if window_ids is not None:
            wss = [self.window_sources.get(wid) for wid in window_ids]
        else:
            wss = self.window_sources.values()
        for ws in wss:
            if ws is not None:
                ws.set_new_encoding(encoding)
        if not window_ids or self.encoding is None:
            self.encoding = encoding

    def hello(self, server_capabilities):
        capabilities = server_capabilities.copy()
        try:
            import xpra.sound
            try:
                assert xpra.sound
                from xpra.sound.pulseaudio_util import add_pulseaudio_capabilities
                add_pulseaudio_capabilities(capabilities)
                from xpra.sound.gstreamer_util import add_gst_capabilities
                add_gst_capabilities(capabilities,
                                     receive=self.supports_microphone, send=self.supports_speaker,
                                     receive_codecs=self.speaker_codecs, send_codecs=self.microphone_codecs)
                log("sound capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("sound.")])
            except Exception, e:
                log.error("failed to setup sound: %s", e)
        except ImportError, e:
            log("sound modules were not included in this installation")
        capabilities["encoding"] = self.encoding
        capabilities["mmap_enabled"] = self.mmap_size>0
        capabilities["modifier_keycodes"] = self.keyboard_config.modifier_client_keycodes
        capabilities["auto_refresh_delay"] = int(self.auto_refresh_delay*1000.0)
        self.send("hello", capabilities)

    def add_info(self, info, suffix=""):
        info["clipboard%s" % suffix] = self.clipboard_enabled
        info["cursors%" % suffix] = self.send_cursors
        info["bell%" % suffix] = self.send_bell
        info["notifications%" % suffix] = self.send_notifications

    def send_clipboard(self, packet):
        if self.clipboard_enabled:
            self.send(*packet)

    def send_cursor(self, cursor_data, cursor_name=None):
        if self.send_cursors:
            if cursor_data:
                #only newer versions support cursor names:
                if not self.named_cursors:
                    cursor_data = cursor_data[:8]
                self.send("cursor", *cursor_data)
            else:
                self.send("cursor", "")

    def bell(self, wid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if self.send_bell:
            self.send("bell", wid, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if self.send_notifications:
            self.send("notify_show", dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout))

    def notify_close(self, nid):
        if self.send_notifications:
            self.send("notify_close", nid)

    def set_deflate(self, level):
        self.send("set_deflate", level)

    def ping(self):
        #NOTE: all ping time/echo time/load avg values are in milliseconds
        self.send("ping", int(1000*time.time()))

    def process_ping(self, time_to_echo):
        #send back the load average:
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        #and the last client ping latency we measured (if any):
        if len(self.statistics.client_ping_latency)>0:
            _, cl = self.statistics.client_ping_latency[-1]
            cl = int(1000.0*cl)
        else:
            cl = -1
        self.idle_send("ping_echo", time_to_echo, l1, l2, l3, cl)
        #if the client is pinging us, ping it too:
        gobject.timeout_add(500, self.ping)

    def process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, server_ping_latency = packet[1:6]
        client_ping_latency = time.time()-echoedtime/1000.0
        self.statistics.client_ping_latency.append((time.time(), client_ping_latency))
        self.client_load = l1, l2, l3
        if server_ping_latency>=0:
            self.statistics.server_ping_latency.append((time.time(), server_ping_latency/1000.0))
        log("ping echo client load=%s, measured server latency=%s", self.client_load, server_ping_latency)

    def updated_desktop_size(self, root_w, root_h, max_w, max_h):
        if self.randr_notify:
            self.send("desktop_size", root_w, root_h, max_w, max_h)

    def or_window_geometry(self, wid, window, x, y, w, h):
        if not self.can_send_window(window):
            return
        self.send("configure-override-redirect", wid, x, y, w, h)

    def window_metadata(self, wid, window, prop):
        if not self.can_send_window(window):
            return
        if prop=="icon" and self.raw_window_icons:
            self.send_window_icon(window, wid)
        else:
            metadata = self._make_metadata(window, prop)
            if len(metadata)>0:
                self.send("window-metadata", wid, metadata)

    def can_send_window(self, window):
        if not self.send_windows and not window.is_tray():
            return  False
        if window.is_tray() and not self.system_tray:
            return  False
        return True

    def new_tray(self, wid, window, w, h):
        assert window.is_tray()
        if not self.can_send_window(window):
            return
        self.send("new-tray", wid, w, h)

    def new_window(self, ptype, wid, window, x, y, w, h, properties, client_properties):
        if not self.can_send_window(window):
            return
        send_props = list(properties)
        if self.raw_window_icons and "icon" in properties:
            send_props.remove("icon")
        metadata = {}
        for propname in send_props:
            metadata.update(self._make_metadata(window, propname))
        log("new_window(%s, %s, %s, %s, %s, %s, %s, %s, %s) metadata=%s", ptype, window, wid, x, y, w, h, properties, client_properties, metadata)
        self.send(ptype, wid, x, y, w, h, metadata, client_properties or {})
        if self.raw_window_icons and "icon" in properties:
            self.send_window_icon(wid, window)

    def send_window_icon(self, wid, window):
        surf = window.get_property("icon")
        log("send_window_icon(%s,%s) icon=%s", window, wid, surf)
        if surf is not None:
            w, h, pixel_format, pixel_data = self.make_window_icon(surf.get_data(), surf.get_format(), surf.get_stride(), surf.get_width(), surf.get_height())
            assert pixel_format in ("premult_argb32", "png")
            if pixel_format=="premult_argb32":
                data = zlib_compress("rgb24", pixel_data)
            else:
                data = Compressed("png", pixel_data)
            self.send("window-icon", wid, w, h, pixel_format, data)

    def lost_window(self, wid, window):
        if not self.can_send_window(window):
            return
        self.send("lost-window", wid)

    def resize_window(self, wid, window, ww, wh):
        """
        The server detected that the application window has been resized,
        we forward it if the client supports this type of event.
        """
        if not self.can_send_window(window):
            return
        if self.server_window_resize:
            self.send("window-resized", wid, ww, wh)

    def cancel_damage(self, wid, window):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        """
        if not self.can_send_window(window):
            return
        ws = self.window_sources.get(wid)
        if ws:
            ws.cancel_damage()

    def remove_window(self, wid, window):
        """ The given window is gone, ensure we free all the related resources """
        if not self.can_send_window(window):
            return
        ws = self.window_sources.get(wid)
        if ws:
            del self.window_sources[wid]
            ws.cleanup()

    def add_stats(self, info, window_ids=[], suffix=""):
        """
            Adds most of the statistics available to the 'info' dict passed in.
            This is used by server.py to provide those statistics to clients
            via the 'xpra info' command.
        """
        info["client_type%s" % suffix] = self.client_type
        info["client_version%s" % suffix] = self.client_version or "unknown"
        info["client_uuid%s" % suffix] = self.uuid
        info["keyboard%s" % suffix] = self.keyboard_config.enabled
        try:
            info["client_connection%s" % suffix] = str(self.protocol._conn.target or self.protocol._conn.filename)
        except:
            pass
        info["client_encodings%s" % suffix] = ",".join(self.encodings)
        info["damage_data_queue_size%s.current" % suffix] = self.damage_data_queue.qsize()
        info["damage_packet_queue_size%s.current" % suffix] = len(self.damage_packet_queue)
        qpixels = [x[2] for x in list(self.damage_packet_queue)]
        add_list_stats(info, "damage_packet_queue_pixels%s" % suffix,  qpixels)
        if len(qpixels)>0:
            info["damage_packet_queue_pixels%s.current" % suffix] = qpixels[-1]
        self.ping()

        self.protocol.add_stats(info, suffix=suffix)
        self.statistics.add_stats(info, suffix=suffix)
        batch_delays = []
        if window_ids:
            total_pixels = 0
            total_time = 0.0
            for wid in window_ids:
                ws = self.window_sources.get(wid)
                if ws:
                    #per-window stats:
                    ws.add_stats(info, suffix=suffix)
                    #collect stats for global averages:
                    for _, pixels, _, encoding_time in list(ws.statistics.encoding_stats):
                        total_pixels += pixels
                        total_time += encoding_time
                    info["pixels_encoded_per_second%s" % suffix] = int(total_pixels / total_time)
                    batch = ws.batch_config
                    for _,d in list(batch.last_delays):
                        batch_delays.append(d)
        if len(batch_delays)>0:
            add_list_stats(info, "batch_delay%s" % suffix, batch_delays)

    def set_quality(self, quality):
        if quality==-1:
            del self.default_damage_options["quality"]
        else:
            self.default_damage_options["quality"] = quality

    def refresh(self, wid, window, opts):
        if not self.can_send_window(window):
            return
        self.cancel_damage(wid, window)
        w, h = window.get_dimensions()
        self.damage(wid, window, 0, 0, w, h, opts)

    def damage(self, wid, window, x, y, w, h, options=None):
        """
            Main entry point from the window manager,
            we dispatch to the WindowSource for this window id
            (creating a new one if needed)
        """
        if not self.can_send_window(window):
            return
        assert window is not None
        if options is None:
            damage_options = self.default_damage_options
        else:
            damage_options = self.default_damage_options.copy()
            damage_options.update(options)
        self.statistics.damage_last_events.append((wid, time.time(), w*h))
        ws = self.window_sources.get(wid)
        if ws is None:
            batch_config = self.default_batch_config.clone()
            batch_config.wid = wid
            ws = WindowSource(self.queue_damage, self.queue_packet, self.statistics,
                              wid, batch_config, self.auto_refresh_delay,
                              self.encoding, self.encodings, self.encoding_options,
                              self.default_damage_options,
                              self.mmap, self.mmap_size)
            self.window_sources[wid] = ws
        ws.damage(window, x, y, w, h, damage_options)

    def client_ack_damage(self, damage_packet_sequence, wid, width, height, decode_time):
        """
            The client is acknowledging a damage packet,
            we record the 'client decode time' (which is provided by the client)
            and WindowSource will calculate and record the "client latency".
            (since it knows when the "draw" packet was sent)
        """
        if not self.send_windows:
            log.error("client_ack_damage when we don't send any window data!?")
            return
        log("packet decoding for window %s %sx%s took %s µs", wid, width, height, decode_time)
        if decode_time>0:
            self.statistics.client_decode_time.append((wid, time.time(), width*height, decode_time))
        ws = self.window_sources.get(wid)
        if ws:
            ws.damage_packet_acked(damage_packet_sequence, width, height, decode_time)

#
# Methods used by WindowSource:
#
    def queue_damage(self, encode_and_send_cb):
        """
            This is used by WindowSource to queue damage processing to be done in the 'data_to_packet' thread.
            The 'encode_and_send_cb' will then add the resulting packet to the 'damage_packet_queue' via 'queue_packet'.
        """
        self.statistics.damage_data_qsizes.append((time.time(), self.damage_data_queue.qsize()))
        self.damage_data_queue.put(encode_and_send_cb)

    def queue_packet(self, packet, wid, pixels, start_send_cb, end_send_cb):
        """
            Add a new 'draw' packet to the 'damage_packet_queue'.
            Note: this code runs in the non-ui thread so we have to use idle_add to call into protocol.
        """
        now = time.time()
        self.statistics.damage_packet_qsizes.append((now, len(self.damage_packet_queue)))
        self.statistics.damage_packet_qpixels.append((now, wid, sum([x[1] for x in list(self.damage_packet_queue) if x[2]==wid])))
        self.damage_packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb))
        #if self.protocol._write_queue.empty():
        gobject.idle_add(self.protocol.source_has_more)

#
# The damage packet thread loop:
#
    def data_to_packet(self):
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'damage_data_queue'.
        """
        while not self.closed:
            encode_and_queue = self.damage_data_queue.get(True)
            if encode_and_queue is None:
                return              #empty marker
            try:
                encode_and_queue()
            except Exception, e:
                log.error("error processing damage data: %s", e, exc_info=True)
            NOYIELD or time.sleep(0)

#
# Management of mmap area:
#
    def init_mmap(self, mmap_file, mmap_token):
        import mmap
        try:
            f = open(mmap_file, "r+b")
            self.mmap_size = os.path.getsize(mmap_file)
            self.mmap = mmap.mmap(f.fileno(), self.mmap_size)
            if mmap_token:
                #verify the token:
                v = 0
                for i in range(0,16):
                    v = v<<8
                    peek = ctypes.c_ubyte.from_buffer(self.mmap, 512+15-i)
                    v += peek.value
                log("mmap_token=%s, verification=%s", mmap_token, v)
                if v!=mmap_token:
                    log.error("WARNING: mmap token verification failed, not using mmap area!")
                    self.close_mmap()
            if self.mmap:
                log("using client supplied mmap file=%s, size=%s", mmap_file, self.mmap_size)
                self.statistics.mmap_size = self.mmap_size
        except Exception, e:
            log.error("cannot use mmap file '%s': %s", mmap_file, e)
            self.close_mmap()

    def close_mmap(self):
        if self.mmap:
            self.mmap.close()
            self.mmap = None
        self.mmap_size = 0
