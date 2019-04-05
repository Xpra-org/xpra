# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
import re

from xpra.net.compression import Compressible
from xpra.os_util import POSIX, monotonic_time, strtobytes, bytestostr, hexstr, get_hex_uuid
from xpra.util import csv, envint, envbool, repr_ellipsized, typedict
from xpra.platform.features import CLIPBOARD_GREEDY, CLIPBOARDS as PLATFORM_CLIPBOARDS
from xpra.gtk_common.gobject_compat import import_glib
from xpra.log import Logger

log = Logger("clipboard")

glib = import_glib()

MIN_CLIPBOARD_COMPRESS_SIZE = envint("XPRA_MIN_CLIPBOARD_COMPRESS_SIZE", 512)
MAX_CLIPBOARD_PACKET_SIZE = 4*1024*1024
MAX_CLIPBOARD_RECEIVE_SIZE = envint("XPRA_MAX_CLIPBOARD_RECEIVE_SIZE", -1)
MAX_CLIPBOARD_SEND_SIZE = envint("XPRA_MAX_CLIPBOARD_SEND_SIZE", -1)

ALL_CLIPBOARDS = [strtobytes(x) for x in PLATFORM_CLIPBOARDS]
CLIPBOARDS = PLATFORM_CLIPBOARDS
CLIPBOARDS_ENV = os.environ.get("XPRA_CLIPBOARDS")
if CLIPBOARDS_ENV is not None:
    CLIPBOARDS = CLIPBOARDS_ENV.split(",")
    CLIPBOARDS = [strtobytes(x).upper().strip() for x in CLIPBOARDS]
del CLIPBOARDS_ENV

TEST_DROP_CLIPBOARD_REQUESTS = envint("XPRA_TEST_DROP_CLIPBOARD")
DELAY_SEND_TOKEN = envint("XPRA_DELAY_SEND_TOKEN", 100)

LOOP_DISABLE = envbool("XPRA_CLIPBOARD_LOOP_DISABLE", True)
LOOP_PREFIX = os.environ.get("XPRA_CLIPBOARD_LOOP_PREFIX", "Xpra-Clipboard-Loop-Detection:")

def get_discard_targets():
    _discard_target_strs_ = os.environ.get("XPRA_DISCARD_TARGETS")
    if _discard_target_strs_ is None:
        return  [
            r"^SAVE_TARGETS$",
            r"^COMPOUND_TEXT",
            r"^NeXT",
            r"^com\.apple\.",
            r"^CorePasteboardFlavorType",
            r"^dyn\.",
            r"^text/plain;charset=utf-8",
            ]
    return _discard_target_strs_.split(",")
DISCARD_TARGETS = tuple(re.compile(dt) for dt in get_discard_targets())
log("discard_targets=%s", csv(get_discard_targets()))

TEXT_TARGETS = ("UTF8_STRING", "TEXT", "STRING", "text/plain")

TRANSLATED_TARGETS = {
    "application/x-moz-nativehtml" : "UTF8_STRING"
    }

sizeof_long = struct.calcsize(b'@L')
assert sizeof_long in (4, 8), "struct.calcsize('@L')=%s" % sizeof_long
sizeof_short = struct.calcsize(b'=H')
assert sizeof_short == 2, "struct.calcsize('=H')=%s" % sizeof_short


def must_discard(target):
    return any(x for x in DISCARD_TARGETS if x.match(bytestostr(target)))

def _filter_targets(targets):
    f = [target for target in targets if not must_discard(target)]
    log("_filter_targets(%s)=%s", targets, f)
    return f

#CARD32 can actually be 64-bits...
CARD32_SIZE = sizeof_long*8
def get_format_size(dformat):
    return max(8, {32 : CARD32_SIZE}.get(dformat, dformat))


class ClipboardProtocolHelperCore(object):
    def __init__(self, send_packet_cb, progress_cb=None, **kwargs):
        d = typedict(kwargs)
        self.send = send_packet_cb
        self.progress_cb = progress_cb
        self.can_send = d.boolget("can-send", True)
        self.can_receive = d.boolget("can-receive", True)
        self.max_clipboard_packet_size = d.intget("max-packet-size", MAX_CLIPBOARD_PACKET_SIZE)
        self.max_clipboard_receive_size = d.intget("max-receive-size", MAX_CLIPBOARD_RECEIVE_SIZE)
        self.max_clipboard_send_size = d.intget("max-send-size", MAX_CLIPBOARD_SEND_SIZE)
        self.clipboard_contents_slice_fix = False
        self.disabled_by_loop = []
        self.filter_res = []
        filter_res = d.strlistget("filters")
        if filter_res:
            for x in filter_res:
                try:
                    self.filter_res.append(re.compile(x))
                except Exception as e:
                    log.error("Error: invalid clipboard filter regular expression")
                    log.error(" '%s': %s", x, e)
        self._clipboard_request_counter = 0
        self._clipboard_outstanding_requests = {}
        self._want_targets = False
        self.init_packet_handlers()
        self.init_proxies(d.strlistget("clipboards.local", CLIPBOARDS))
        remote_loop_uuids = d.dictget("remote-loop-uuids", {})
        self.verify_remote_loop_uuids(remote_loop_uuids)
        self.remote_clipboards = d.strlistget("clipboards.remote", CLIPBOARDS)

    def __repr__(self):
        return "ClipboardProtocolHelperCore"

    def get_info(self):
        info = {
                "type"      :       str(self).replace("ClipboardProtocolHelper", ""),
                "max_size"  :       self.max_clipboard_packet_size,
                "max_recv_size":    self.max_clipboard_receive_size,
                "max_send_size":    self.max_clipboard_send_size,
                "filters"   : [x.pattern for x in self.filter_res],
                "requests"  : self._clipboard_request_counter,
                "pending"   : tuple(self._clipboard_outstanding_requests.keys()),
                "can-send"      : self.can_send,
                "can-receive"   : self.can_receive,
                "want_targets"  : self._want_targets,
                }
        for clipboard, proxy in self._clipboard_proxies.items():
            info[clipboard] = proxy.get_info()
        return info

    def cleanup(self):
        def nosend(*_args):
            pass
        self.send = nosend
        for x in self._clipboard_proxies.values():
            x.cleanup()
        self._clipboard_proxies = {}

    def nesting_check(self):
        return True

    def client_reset(self):
        #if the client disconnects,
        #we can re-enable the clipboards it had problems with:
        l = self.disabled_by_loop
        self.disabled_by_loop = []
        for x in l:
            proxy = self._clipboard_proxies.get(x)
            proxy.set_enabled(True)


    def get_loop_uuids(self):
        uuids = {}
        for proxy in self._clipboard_proxies.values():
            uuids[proxy._selection] = proxy._loop_uuid
        log("get_loop_uuids()=%s", uuids)
        return uuids

    def verify_remote_loop_uuids(self, uuids):
        log("verify_remote_loop_uuids(%s)", uuids)

    def _verify_remote_loop_uuids(self, clipboard, value, user_data):
        pass

    def set_direction(self, can_send, can_receive, max_send_size=None, max_receive_size=None):
        self.can_send = can_send
        self.can_receive = can_receive
        self.set_limits(max_send_size, max_receive_size)
        for proxy in self._clipboard_proxies.values():
            proxy.set_direction(can_send, can_receive)

    def set_limits(self, max_send_size, max_receive_size):
        if max_send_size is not None:
            self.max_clipboard_send_size = max_send_size
        if max_receive_size is not None:
            self.max_clipboard_receive_size = max_receive_size

    def set_clipboard_contents_slice_fix(self, v):
        self.clipboard_contents_slice_fix = v

    def enable_selections(self, selections):
        #when clients first connect or later through the "clipboard-enable-selections" packet,
        #they can tell us which clipboard selections they want enabled
        #(ie: OSX and win32 only use "CLIPBOARD" by default, and not "PRIMARY" or "SECONDARY")
        log("enabling selections: %s", csv(selections))
        for selection, proxy in self._clipboard_proxies.items():
            proxy.set_enabled(strtobytes(selection) in selections)

    def set_greedy_client(self, greedy):
        for proxy in self._clipboard_proxies.values():
            proxy.set_greedy_client(greedy)

    def set_want_targets_client(self, want_targets):
        log("set_want_targets_client(%s)", want_targets)
        self._want_targets = want_targets

    def init_packet_handlers(self):
        self._packet_handlers = {
            "clipboard-token"               : self._process_clipboard_token,
            "clipboard-request"             : self._process_clipboard_request,
            "clipboard-contents"            : self._process_clipboard_contents,
            "clipboard-contents-none"       : self._process_clipboard_contents_none,
            "clipboard-pending-requests"    : self._process_clipboard_pending_requests,
            "clipboard-enable-selections"   : self._process_clipboard_enable_selections,
            "clipboard-loop-uuids"          : self._process_clipboard_loop_uuids,
            }

    def make_proxy(self, selection):
        raise NotImplementedError()

    def init_proxies(self, selections):
        self._clipboard_proxies = {}
        for selection in selections:
            proxy = self.make_proxy(selection)
            self._clipboard_proxies[selection] = proxy
        log("%s.init_proxies : %s", self, self._clipboard_proxies)

    def init_proxies_uuid(self):
        for proxy in self._clipboard_proxies.values():
            proxy.init_uuid()


    def local_to_remote(self, selection):
        #overriden in some subclasses (see: translated_clipboard)
        return  selection
    def remote_to_local(self, selection):
        #overriden in some subclasses (see: translated_clipboard)
        return  selection

    # Used by the client during startup:
    def send_tokens(self, selections=()):
        for selection in selections:
            proxy = self._clipboard_proxies.get(selection)
            if proxy:
                proxy._have_token = False
                self._send_clipboard_token_handler(proxy)

    def send_all_tokens(self):
        self.send_tokens(CLIPBOARDS)


    def _process_clipboard_token(self, packet):
        selection = bytestostr(packet[1])
        name = self.remote_to_local(selection)
        proxy = self._clipboard_proxies.get(name)
        if proxy is None:
            #this can happen if the server has fewer clipboards than the client,
            #ie: with win32 shadow servers
            l = log
            if name in ALL_CLIPBOARDS:
                l = log.warn
            l("ignoring token for clipboard '%s' (no proxy)", name)
            return
        if not proxy.is_enabled():
            l = log
            if name not in self.disabled_by_loop:
                l = log.warn
            l("ignoring token for disabled clipboard '%s'", name)
            return
        log("process clipboard token selection=%s, local clipboard name=%s, proxy=%s", selection, name, proxy)
        targets = None
        target_data = None
        if proxy._can_receive:
            if len(packet)>=3:
                targets = packet[2]
            if len(packet)>=8:
                target, dtype, dformat, wire_encoding, wire_data = packet[3:8]
                raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
                target_data = {target : (dtype, dformat, raw_data)}
        #older versions always claimed the selection when the token is received:
        claim = True
        if len(packet)>=10:
            claim = bool(packet[8])
            #clients can now also change the greedy flag on the fly,
            #this is needed for clipboard direction restrictions:
            #the client may want to be notified of clipboard changes, just like a greedy client
            proxy._greedy_client = bool(packet[9])
        synchronous_client = len(packet)>=11 and bool(packet[10])
        proxy.got_token(targets, target_data, claim, synchronous_client)

    def _send_clipboard_token_handler(self, proxy):
        selection = proxy._selection
        log("send clipboard token: %s", selection)
        rsel = self.local_to_remote(selection)
        def send_token(*args):
            self.send("clipboard-token", *args)
        if not proxy._can_send:
            #send the token without data,
            #and with claim flag set to False, greedy set to True
            send_token(rsel, [], "NOTARGET", "UTF8_STRING", 8, "bytes", "", False, True)
            return
        if self._want_targets:
            log("client wants targets with the token, querying TARGETS")
            #send the token with the target and data once we get them:
            #first get the targets, then get the contents for targets we want to send (if any)
            def got_targets(dtype, dformat, targets):
                log("got_targets for selection %s: %s, %s, %s", selection, dtype, dformat, targets)
                if targets is None:
                    send_token(rsel)
                    return
                #if there is a text target, send that too (just the first one that matches for now..)
                send_now = [x for x in targets if x in TEXT_TARGETS]
                def send_targets_only():
                    send_token(rsel, targets)
                if not send_now:
                    send_targets_only()
                    return
                target = send_now[0]
                def got_contents(dtype, dformat, data):
                    log("got_contents for selection %s: %s, %s, %s",
                        selection, dtype, dformat, repr_ellipsized(str(data)))
                    #code mostly duplicated from _process_clipboard_request
                    #see there for details
                    if dtype is None or data is None:
                        send_targets_only()
                        return
                    wire_encoding, wire_data = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
                    if wire_encoding is None:
                        send_targets_only()
                        return
                    wire_data = self._may_compress(dtype, dformat, wire_data)
                    if not wire_data:
                        send_targets_only()
                        return
                    target_data = (target, dtype, dformat, wire_encoding, wire_data, True, CLIPBOARD_GREEDY)
                    log("sending token with target data: %s", target_data)
                    send_token(rsel, targets, *target_data)
                proxy.get_contents(target, got_contents)
            proxy.get_contents("TARGETS", got_targets)
            return
        send_token(rsel)

    def _munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        log("_munge_raw_selection_to_wire%s", (target, dtype, dformat, data))
        # Some types just cannot be marshalled:
        if type in ("WINDOW", "PIXMAP", "BITMAP", "DRAWABLE",
                    "PIXEL", "COLORMAP"):
            log("skipping clipboard data of type: %s, format=%s, len(data)=%s", dtype, dformat, len(data or ""))
            return None, None
        if target==b"TARGETS" and dtype==b"ATOM":
            #targets is special cased here
            #because we get the values in wire format already (not atoms)
            #thanks to the request_targets() function (required on win32)
            return "atoms", _filter_targets(data)
        return self._do_munge_raw_selection_to_wire(target, dtype, dformat, data)

    def _do_munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        """ this method is overriden in xclipboard to parse X11 atoms """
        # Other types need special handling, and all types need to be
        # converting into an endian-neutral format:
        log("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s)", target, dtype, dformat, type(data), len(data or ""))
        if dformat == 32:
            #you should be using gdk_clipboard for atom support!
            if dtype in (b"ATOM", b"ATOM_PAIR") and POSIX:
                #we cannot handle gdk atoms here (but gdk_clipboard does)
                return None, None
            #important note: on 64 bits, format=32 means 8 bytes, not 4
            #that's just the way it is...
            binfmt = b"@" + b"L" * (len(data) // sizeof_long)
            ints = struct.unpack(binfmt, data)
            return b"integers", ints
        if dformat == 16:
            binfmt = b"=" + b"H" * (len(data) // sizeof_short)
            ints = struct.unpack(binfmt, data)
            return b"integers", ints
        if dformat == 8:
            for x in self.filter_res:
                if x.match(data):
                    log.warn("clipboard buffer contains blacklisted pattern '%s' and has been dropped!", x.pattern)
                    return None, None
            return b"bytes", data
        log.error("unhandled format %s for clipboard data type %s" % (dformat, dtype))
        return None, None

    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        log("wire selection to raw, encoding=%s, type=%s, format=%s, len(data)=%s",
            encoding, dtype, dformat, len(data or b""))
        if self.max_clipboard_receive_size > 0:
            max_recv_datalen = self.max_clipboard_receive_size * 8 // get_format_size(dformat)
            if len(data) > max_recv_datalen:
                olen = len(data)
                data = data[:max_recv_datalen]
                log.info("Data copied out truncated because of clipboard policy %d to %d", olen, max_recv_datalen)
        if encoding == b"bytes":
            return data
        if encoding == b"integers":
            if not data:
                return ""
            if dformat == 32:
                format_char = b"L"
            elif dformat == 16:
                format_char = b"H"
            elif dformat == 8:
                format_char = b"B"
            else:
                raise Exception("unknown encoding format: %s" % dformat)
            fstr = b"@" + format_char * len(data)
            log("struct.pack(%s, %s)", fstr, data)
            return struct.pack(fstr, *data)
        raise Exception("unhanled encoding: %s" % encoding)

    def _process_clipboard_request(self, packet):
        request_id, selection, target = packet[1:4]
        selection = bytestostr(selection)
        target = bytestostr(target)
        def no_contents():
            self.send("clipboard-contents-none", request_id, selection)
        if must_discard(target):
            log("invalid target '%s'", target)
            no_contents()
            return
        name = self.remote_to_local(selection)
        log("process clipboard request, request_id=%s, selection=%s, local name=%s, target=%s",
            request_id, selection, name, target)
        proxy = self._clipboard_proxies.get(name)
        if proxy is None:
            #err, we were asked about a clipboard we don't handle..
            log.error("Error: clipboard request for '%s' (no proxy, ignored)", name)
            no_contents()
            return
        if not proxy.is_enabled():
            l = log
            if selection not in self.disabled_by_loop:
                l = log.warn
            l("Warning: ignoring clipboard request for '%s' (disabled)", name)
            no_contents()
            return
        if not proxy._can_send:
            log("request for %s but sending is disabled, sending 'none' back", name)
            no_contents()
            return
        if TEST_DROP_CLIPBOARD_REQUESTS>0 and (request_id % TEST_DROP_CLIPBOARD_REQUESTS)==0:
            log.warn("clipboard request %s dropped for testing!", request_id)
            return
        def got_contents(dtype, dformat, data):
            log("got_contents(%s, %s, %s:%s) data=0x%s..",
                  dtype, dformat, type(data), len(data or ""), hexstr((data or "")[:200]))
            if dtype is None or data is None or (dformat==0 and data==b""):
                no_contents()
                return
            log("perform clipboard limit checking - datasize - %d, %d", len(data), self.max_clipboard_send_size)
            truncated = 0
            if self.max_clipboard_send_size > 0:
                max_send_datalen = self.max_clipboard_send_size * 8 // get_format_size(dformat)
                if len(data) > max_send_datalen:
                    truncated = len(data) - max_send_datalen
                    data = data[:max_send_datalen]
            munged = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
            wire_encoding, wire_data = munged
            log("clipboard raw -> wire: %r -> %r", (dtype, dformat, data), munged)
            if wire_encoding is None:
                no_contents()
                return
            wire_data = self._may_compress(dtype, dformat, wire_data)
            if wire_data is not None:
                packet = ["clipboard-contents", request_id, selection,
                        dtype, dformat, wire_encoding, wire_data]
                if self.clipboard_contents_slice_fix:
                    #sending the extra argument requires the fix
                    packet.append(truncated)
                self.send(*packet)
        proxy.get_contents(target, got_contents)

    def _may_compress(self, dtype, dformat, wire_data):
        if len(wire_data)>self.max_clipboard_packet_size:
            log.warn("Warning: clipboard contents are too big and have not been sent")
            log.warn(" %s compressed bytes dropped (maximum is %s)", len(wire_data), self.max_clipboard_packet_size)
            return  None
        if isinstance(wire_data, (str, bytes)) and len(wire_data)>=MIN_CLIPBOARD_COMPRESS_SIZE:
            return Compressible("clipboard: %s / %s" % (dtype, dformat), wire_data)
        return wire_data

    def _process_clipboard_contents(self, packet):
        request_id, selection, dtype, dformat, wire_encoding, wire_data = packet[1:7]
        log("process clipboard contents, selection=%s, type=%s, format=%s", selection, dtype, dformat)
        raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
        log("clipboard wire -> raw: %r -> %r", (dtype, dformat, wire_encoding, wire_data), raw_data)
        self._clipboard_got_contents(request_id, dtype, dformat, raw_data)

    def _process_clipboard_contents_none(self, packet):
        log("process clipboard contents none")
        request_id = packet[1]
        self._clipboard_got_contents(request_id, None, None, None)

    def _clipboard_got_contents(self, request_id, dtype, dformat, data):
        raise NotImplementedError()


    def progress(self):
        if self.progress_cb:
            self.progress_cb(len(self._clipboard_outstanding_requests), None)


    def _process_clipboard_pending_requests(self, packet):
        pending = packet[1]
        if self.progress_cb:
            self.progress_cb(None, pending)

    def _process_clipboard_enable_selections(self, packet):
        selections = packet[1]
        self.enable_selections(selections)

    def _process_clipboard_loop_uuids(self, packet):
        loop_uuids = packet[1]
        self.verify_remote_loop_uuids(loop_uuids)


    def process_clipboard_packet(self, packet):
        packet_type = bytestostr(packet[0])
        handler = self._packet_handlers.get(packet_type)
        if handler:
            #log("process clipboard handler(%s)=%s", packet_type, handler)
            handler(packet)
        else:
            log.warn("Warning: no clipboard packet handler for '%s'", packet_type)



class ClipboardProxyCore(object):
    def __init__(self, selection):
        self._selection = selection
        self._enabled = True
        self._have_token = False
        #enabled later during setup
        self._can_send = False
        self._can_receive = False
        #clients that need a new token for every owner-change: (ie: win32 and osx)
        #(forces the client to request new contents - prevents stale clipboard data)
        self._greedy_client = False
        #semaphore to block the sending of the token when we change the owner ourselves:
        self._block_owner_change = False
        self._last_emit_token = 0
        self._emit_token_timer = None
        #counters for info:
        self._selection_request_events = 0
        self._selection_get_events = 0
        self._selection_clear_events = 0
        self._sent_token_events = 0
        self._got_token_events = 0
        self._get_contents_events = 0
        self._request_contents_events = 0
        self._last_targets = ()

        self._loop_uuid = ""

    def init_uuid(self):
        self._loop_uuid = LOOP_PREFIX+get_hex_uuid()
        log("init_uuid() %s uuid=%s", self._selection, self._loop_uuid)

    def set_direction(self, can_send, can_receive):
        self._can_send = can_send
        self._can_receive = can_receive

    def get_info(self):
        info = {
                "have_token"            : self._have_token,
                "enabled"               : self._enabled,
                "greedy_client"         : self._greedy_client,
                "blocked_owner_change"  : self._block_owner_change,
                "last-targets"          : self._last_targets,
                "loop-uuid"             : self._loop_uuid,
                "event"         : {
                                   "selection_request"     : self._selection_request_events,
                                   "selection_get"         : self._selection_get_events,
                                   "selection_clear"       : self._selection_clear_events,
                                   "got_token"             : self._got_token_events,
                                   "sent_token"            : self._sent_token_events,
                                   "get_contents"          : self._get_contents_events,
                                   "request_contents"      : self._request_contents_events,
                                   },
                }
        return info

    def cleanup(self):
        self._enabled = False
        self.cancel_emit_token()

    def is_enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        log("%s.set_enabled(%s)", self, enabled)
        self._enabled = enabled

    def set_greedy_client(self, greedy):
        log("%s.set_greedy_client(%s)", self, greedy)
        self._greedy_client = greedy

    def __repr__(self):
        return  "ClipboardProxyCore(%s)" % self._selection

    def do_owner_changed(self, *_args):
        #an application on our side owns the clipboard selection
        #(they are ready to provide something via the clipboard)
        log("clipboard: %s owner_changed, enabled=%s, "+
            "can-send=%s, can-receive=%s, have_token=%s, greedy_client=%s, block_owner_change=%s",
            bytestostr(self._selection), self._enabled, self._can_send, self._can_receive,
            self._have_token, self._greedy_client, self._block_owner_change)
        if not self._enabled or self._block_owner_change:
            return
        if self._have_token or (self._greedy_client and self._can_send):
            if self._have_token or DELAY_SEND_TOKEN<0:
                #token ownership will change or told not to wait
                glib.idle_add(self.emit_token)
            elif not self._emit_token_timer:
                #we had it already, this can wait:
                #TODO: don't throttle clients without "want-targets" attribute
                # (sending the token is only expensive for those)
                self.schedule_emit_token()

    def schedule_emit_token(self):
        if self._have_token or DELAY_SEND_TOKEN<0:
            #token ownership will change or told not to wait
            glib.idle_add(self.emit_token)
        elif not self._emit_token_timer:
            #we had it already, this can wait:
            #TODO: don't throttle clients without "want-targets" attribute
            # (sending the token is only expensive for those)
            self.do_schedule_emit_token()

    def do_schedule_emit_token(self):
        now = monotonic_time()
        elapsed = int((now-self._last_emit_token)*1000)
        log("schedule_emit_token() elapsed=%i (max=%i)", elapsed, DELAY_SEND_TOKEN)
        if elapsed>=DELAY_SEND_TOKEN:
            #enough time has passed
            self.emit_token()
        else:
            self._emit_token_timer = glib.timeout_add(DELAY_SEND_TOKEN-elapsed, self.emit_token)

    def emit_token(self):
        self._emit_token_timer = None
        boc = self._block_owner_change
        self._block_owner_change = True
        self._have_token = False
        self._last_emit_token = monotonic_time()
        self.do_emit_token()
        self._sent_token_events += 1
        if boc is False:
            glib.idle_add(self.remove_block)

    def do_emit_token(self):
        #self.emit("send-clipboard-token")
        pass

    def cancel_emit_token(self):
        ett = self._emit_token_timer
        if ett:
            self._emit_token_timer = None
            glib.source_remove(ett)


    #def do_selection_request_event(self, event):
    #    pass

    #def do_selection_get(self, selection_data, info, time):
    #    pass

    #def do_selection_clear_event(self, event):
    #    pass

    def remove_block(self, *_args):
        log("remove_block: %s", self._selection)
        self._block_owner_change = False

    def claim(self):
        pass

    # This function is called by the xpra core when the peer has requested the
    # contents of this clipboard:
    def get_contents(self, target, cb):
        pass
