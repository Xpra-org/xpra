# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
import re
from time import monotonic
from io import BytesIO
from typing import Tuple, List, Dict, Callable, Optional, Any, Iterable
from gi.repository import GLib  # @UnresolvedImport

from xpra.common import noop
from xpra.net.compression import Compressible
from xpra.net.common import PacketType
from xpra.os_util import POSIX, bytestostr, hexstr
from xpra.util import csv, envint, envbool, repr_ellipsized, ellipsizer, typedict
from xpra.platform.features import CLIPBOARDS as PLATFORM_CLIPBOARDS
from xpra.log import Logger, is_debug_enabled

log = Logger("clipboard")

MIN_CLIPBOARD_COMPRESS_SIZE : int = envint("XPRA_MIN_CLIPBOARD_COMPRESS_SIZE", 512)
MAX_CLIPBOARD_PACKET_SIZE : int = 16*1024*1024
MAX_CLIPBOARD_RECEIVE_SIZE : int = envint("XPRA_MAX_CLIPBOARD_RECEIVE_SIZE", -1)
MAX_CLIPBOARD_SEND_SIZE : int = envint("XPRA_MAX_CLIPBOARD_SEND_SIZE", -1)

ALL_CLIPBOARDS : Tuple[str, ...] = ("CLIPBOARD", "PRIMARY", "SECONDARY")
CLIPBOARDS : List[str] = list(PLATFORM_CLIPBOARDS)
CLIPBOARDS_ENV : Optional[str] = os.environ.get("XPRA_CLIPBOARDS")
if CLIPBOARDS_ENV is not None:
    CLIPBOARDS = [x.upper().strip() for x in CLIPBOARDS_ENV.split(",")]
del CLIPBOARDS_ENV

TEST_DROP_CLIPBOARD_REQUESTS = envint("XPRA_TEST_DROP_CLIPBOARD")
DELAY_SEND_TOKEN = envint("XPRA_DELAY_SEND_TOKEN", 100)


def get_discard_targets(envname:str="DISCARD", default_value:Tuple[str,...]=()):
    _discard_target_strs_ = os.environ.get("XPRA_%s_TARGETS" % envname)
    if _discard_target_strs_ is None:
        return default_value
    return _discard_target_strs_.split(",")
#targets we never wish to handle:
DISCARD_TARGETS = tuple(re.compile(dt) for dt in get_discard_targets("DISCARD", (
    r"^NeXT",
    r"^com\.apple\.",
    r"^CorePasteboardFlavorType",
    r"^dyn\.",
    r"^resource-transfer-format",           #eclipse
    r"^x-special/",                         #ie: gnome file copy
    )))
#targets some applications are known to request,
#even when the peer did not expose them as valid targets,
#rather than forwarding the request and then timing out,
#we will just drop them
DISCARD_EXTRA_TARGETS = tuple(re.compile(dt) for dt in get_discard_targets("DISCARD_EXTRA", (
    r"^SAVE_TARGETS$",
    r"^COMPOUND_TEXT",
    r"GTK_TEXT_BUFFER_CONTENTS",
    )))
log("DISCARD_TARGETS=%s", csv(DISCARD_TARGETS))
log("DISCARD_EXTRA_TARGETS=%s", csv(DISCARD_EXTRA_TARGETS))


TEXT_TARGETS: Tuple[str, ...] = tuple(
    os.environ.get("XPRA_CLIPBOARD_TEXT_TARGETS",
                   "UTF8_STRING,TEXT,STRING,text/plain,text/html").split(",")
)


TRANSLATED_TARGETS : Dict[str, str] = {
    "application/x-moz-nativehtml" : "UTF8_STRING"
    }

sizeof_long : int = struct.calcsize(b'@L')
assert sizeof_long in (4, 8), "struct.calcsize('@L')=%s" % sizeof_long
sizeof_short : int = struct.calcsize(b'=H')
assert sizeof_short == 2, "struct.calcsize('=H')=%s" % sizeof_short


def must_discard(target:str) -> bool:
    return any(x for x in DISCARD_TARGETS if x.match(target))

def must_discard_extra(target:str) -> bool:
    return any(x for x in DISCARD_EXTRA_TARGETS if x.match(target))


def _filter_targets(targets : Iterable[str]) -> Tuple[str, ...]:
    targets_strs = tuple(bytestostr(x) for x in targets)
    f = tuple(target for target in targets_strs if not must_discard(target))
    log("_filter_targets(%s)=%s", csv(targets_strs), f)
    return f

#CARD32 can actually be 64-bits...
CARD32_SIZE : int = sizeof_long*8
def get_format_size(dformat:int) -> int:
    return max(8, {32 : CARD32_SIZE}.get(dformat, dformat))


class ClipboardProxyCore:
    def __init__(self, selection):
        self._selection : str = selection
        self._enabled : bool = False
        self._have_token : bool = False
        #enabled later during setup
        self._can_send : bool = False
        self._can_receive : bool = False
        #clients that need a new token for every owner-change: (ie: win32 and osx)
        #(forces the client to request new contents - prevents stale clipboard data)
        self._greedy_client : bool = False
        self._want_targets : bool = False
        #semaphore to block the sending of the token when we change the owner ourselves:
        self._block_owner_change : int = 0
        self._last_emit_token : float = 0
        self._emit_token_timer : int = 0
        #counters for info:
        self._selection_request_events : int = 0
        self._selection_get_events : int = 0
        self._selection_clear_events : int = 0
        self._sent_token_events : int = 0
        self._got_token_events : int = 0
        self._get_contents_events : int = 0
        self._request_contents_events : int = 0
        self._last_targets = ()
        self.preferred_targets = []

    def set_direction(self, can_send : bool, can_receive : bool) -> None:
        self._can_send = can_send
        self._can_receive = can_receive

    def set_want_targets(self, want_targets) -> None:
        self._want_targets = want_targets


    def get_info(self) -> Dict[str,Any]:
        info : Dict[str,Any] = {
                "have_token"            : self._have_token,
                "enabled"               : self._enabled,
                "greedy_client"         : self._greedy_client,
                "preferred-targets"     : self.preferred_targets,
                "blocked_owner_change"  : self._block_owner_change,
                "last-targets"          : self._last_targets,
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

    def cleanup(self) -> None:
        self._enabled = False
        self.cancel_emit_token()
        self.cancel_unblock()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled : bool) -> None:
        log("%s.set_enabled(%s)", self, enabled)
        self._enabled = enabled

    def set_greedy_client(self, greedy : bool) -> None:
        log("%s.set_greedy_client(%s)", self, greedy)
        self._greedy_client = greedy

    def set_preferred_targets(self, preferred_targets) -> None:
        self.preferred_targets = preferred_targets


    def __repr__(self):
        return  "ClipboardProxyCore(%s)" % self._selection

    def do_owner_changed(self) -> None:
        #an application on our side owns the clipboard selection
        #(they are ready to provide something via the clipboard)
        log("clipboard: %s owner_changed, enabled=%s, "+
            "can-send=%s, can-receive=%s, have_token=%s, greedy_client=%s, block_owner_change=%s",
            bytestostr(self._selection), self._enabled, self._can_send, self._can_receive,
            self._have_token, self._greedy_client, self._block_owner_change)
        if not self._enabled or self._block_owner_change:
            return
        if self._have_token or ((self._greedy_client or self._want_targets) and self._can_send):
            self.schedule_emit_token()

    def schedule_emit_token(self, min_delay:int=0)  -> None:
        if min_delay==0 and (self._have_token or (not self._want_targets and not self._greedy_client) or DELAY_SEND_TOKEN<0):
            #token ownership will change or told not to wait
            GLib.idle_add(self.emit_token)
        elif not self._emit_token_timer:
            #we already had sent the token,
            #or sending it is expensive, so wait a bit:
            self.do_schedule_emit_token(min_delay)

    def do_schedule_emit_token(self, min_delay:int=0) -> None:
        now = monotonic()
        elapsed = int((now-self._last_emit_token)*1000)
        delay = max(min_delay, DELAY_SEND_TOKEN-elapsed)
        log("do_schedule_emit_token(%i) selection=%s, elapsed=%i (max=%i), delay=%i",
            min_delay, self._selection, elapsed, DELAY_SEND_TOKEN, delay)
        if delay<=0:
            #enough time has passed
            self.emit_token()
        else:
            self._emit_token_timer = GLib.timeout_add(delay, self.emit_token)

    def emit_token(self) -> None:
        self._emit_token_timer = 0
        boc = self._block_owner_change
        if not boc:
            self._block_owner_change = GLib.idle_add(self.remove_block)
        self._have_token = False
        self._last_emit_token = monotonic()
        self.do_emit_token()
        self._sent_token_events += 1

    def do_emit_token(self):
        #self.emit("send-clipboard-token")
        pass

    def cancel_emit_token(self) -> None:
        ett = self._emit_token_timer
        if ett:
            self._emit_token_timer = 0
            GLib.source_remove(ett)

    def cancel_unblock(self) -> None:
        boc = self._block_owner_change
        if boc:
            self._block_owner_change = 0
            GLib.source_remove(boc)

    #def do_selection_request_event(self, event):
    #    pass

    #def do_selection_get(self, selection_data, info, time):
    #    pass

    #def do_selection_clear_event(self, event):
    #    pass

    def remove_block(self, *_args) -> None:
        log("remove_block: %s", self._selection)
        self._block_owner_change = 0

    def claim(self) -> None:
        """
        Subclasses may want to take ownership of the clipboard selection.
        The X11 clipboard does.
        """

    # This function is called by the xpra core when the peer has requested the
    # contents of this clipboard:
    def get_contents(self, target:str, got_contents:Callable) -> None:
        pass

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        raise NotImplementedError()


    def filter_data(self, dtype:str="" , dformat:int=0, data=None, trusted:bool=False, output_dtype=None):
        log("filter_data(%s, %s, %i %s, %s, %s)",
            dtype, dformat, len(data), type(data), trusted, output_dtype)
        if not data:
            return data
        IMAGE_OVERLAY = os.environ.get("XPRA_CLIPBOARD_IMAGE_OVERLAY", None)
        if IMAGE_OVERLAY and not os.path.exists(IMAGE_OVERLAY):
            IMAGE_OVERLAY = None
        IMAGE_STAMP = envbool("XPRA_CLIPBOARD_IMAGE_STAMP", False)
        SANITIZE_IMAGES = envbool("XPRA_SANITIZE_IMAGES", True)
        if dtype in ("image/png", "image/jpeg", "image/tiff") and (
            (output_dtype is not None and dtype!=output_dtype) or
            IMAGE_STAMP or
            IMAGE_OVERLAY or
            (SANITIZE_IMAGES and not trusted)
            ):
            # pylint: disable=import-outside-toplevel
            from xpra.codecs.pillow.decoder import open_only
            img_type = dtype.split("/")[-1]
            img = open_only(data, (img_type, ))
            has_alpha = img.mode=="RGBA"
            if not has_alpha and IMAGE_OVERLAY:
                img = img.convert("RGBA")
            w, h = img.size
            if IMAGE_OVERLAY:
                from PIL import Image   #@UnresolvedImport
                try:
                    from PIL.Image.Resampling import LANCZOS
                except ImportError:
                    from PIL.Image import LANCZOS
                overlay = Image.open(IMAGE_OVERLAY)
                if overlay.mode!="RGBA":
                    log.warn("Warning: cannot use overlay image '%s'", IMAGE_OVERLAY)
                    log.warn(" invalid mode '%s'", overlay.mode)
                else:
                    log("adding clipboard image overlay to %s", dtype)
                    overlay_resized = overlay.resize((w, h), LANCZOS)
                    composite = Image.alpha_composite(img, overlay_resized)
                    if not has_alpha and img.mode=="RGBA":
                        composite = composite.convert("RGB")
                    img = composite
            if IMAGE_STAMP:
                log("adding clipboard image stamp to %s", dtype)
                from datetime import datetime
                from PIL import ImageDraw
                img_draw = ImageDraw.Draw(img)
                w, h = img.size
                img_draw.text((10, max(0, h//2-16)), 'via Xpra, %s' % datetime.now().isoformat(), fill='black')
            #now save it:
            img_type = (output_dtype or dtype).split("/")[-1]
            buf = BytesIO()
            img.save(buf, img_type.upper()) #ie: "PNG"
            data = buf.getvalue()
            buf.close()
        return data


class ClipboardProtocolHelperCore:
    def __init__(self, send_packet_cb, progress_cb:Callable=noop, **kwargs):
        d = typedict(kwargs)
        self.send : Callable = send_packet_cb
        self.progress_cb : Callable = progress_cb
        self.can_send : bool = d.boolget("can-send", True)
        self.can_receive : bool = d.boolget("can-receive", True)
        self.max_clipboard_packet_size : int = d.intget("max-packet-size", MAX_CLIPBOARD_PACKET_SIZE)
        self.max_clipboard_receive_size : int = d.intget("max-receive-size", MAX_CLIPBOARD_RECEIVE_SIZE)
        self.max_clipboard_send_size : int = d.intget("max-send-size", MAX_CLIPBOARD_SEND_SIZE)
        self.filter_res = []
        filter_res : Tuple[str,...] = d.strtupleget("filters")
        if filter_res:
            for x in filter_res:
                try:
                    self.filter_res.append(re.compile(x))
                except Exception as e:
                    log.error("Error: invalid clipboard filter regular expression")
                    log.error(" '%s': %s", x, e)
        self._clipboard_request_counter : int = 0
        self._clipboard_outstanding_requests : Dict[int,Tuple[int, str, str]] = {}
        self._local_to_remote : Dict[str,str] = {}
        self._remote_to_local : Dict[str,str] = {}
        self.init_translation(kwargs)
        self._want_targets : bool = False
        self.init_packet_handlers()
        self.init_proxies(d.strtupleget("clipboards.local", CLIPBOARDS))
        self.remote_clipboards = d.strtupleget("clipboards.remote", CLIPBOARDS)

    def init_proxies(self, selections : Iterable[str]) -> None:
        self._clipboard_proxies : Dict[str, ClipboardProxyCore] = {}
        for selection in selections:
            proxy = self.make_proxy(selection)
            self._clipboard_proxies[selection] = proxy
        log("%s.init_proxies : %s", self, self._clipboard_proxies)

    def init_translation(self, kwargs) -> None:
        def getselection(name) -> Optional[str]:
            v = kwargs.get(f"clipboard.{name}")           #ie: clipboard.remote
            env_value = os.environ.get(f"XPRA_TRANSLATEDCLIPBOARD_{name.upper()}_SELECTION")
            selections = kwargs.get(f"clipboards.{name}") #ie: clipboards.remote
            if not selections:
                return None
            for x in (env_value, v):
                if x and x in selections:
                    return x
            return selections[0]
        local = getselection("local")
        remote = getselection("remote")
        if local and remote:
            self._local_to_remote[local] = remote
            self._remote_to_local[remote] = local

    def local_to_remote(self, selection:str) -> str:
        return self._local_to_remote.get(selection, selection)

    def remote_to_local(self, selection:str) -> str:
        return self._remote_to_local.get(selection, selection)

    def get_remote_selections(self) -> List[str]:
        #figure out which remote selections we are interested in:
        selections = []
        for selection in self._clipboard_proxies.keys():
            selections.append(self.local_to_remote(selection))
        return selections

    def __repr__(self):
        return "ClipboardProtocolHelperCore"

    def get_info(self) -> Dict[str,Any]:
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

    def cleanup(self) -> None:
        def nosend(*_args):
            """ during cleanup, stop sending packets """
        self.send = nosend
        for x in self._clipboard_proxies.values():
            x.cleanup()
        self._clipboard_proxies = {}

    def client_reset(self) -> None:
        """ overriden in subclasses to try to reset the state """

    def set_direction(self, can_send:bool, can_receive:bool,
                      max_send_size:Optional[int]=None, max_receive_size:Optional[int]=None) -> None:
        self.can_send = can_send
        self.can_receive = can_receive
        self.set_limits(max_send_size, max_receive_size)
        for proxy in self._clipboard_proxies.values():
            proxy.set_direction(can_send, can_receive)

    def set_limits(self, max_send_size:Optional[int], max_receive_size:Optional[int]) -> None:
        if max_send_size is not None:
            self.max_clipboard_send_size = max_send_size
        if max_receive_size is not None:
            self.max_clipboard_receive_size = max_receive_size

    def enable_selections(self, selections=None) -> None:
        #when clients first connect or later through the "clipboard-enable-selections" packet,
        #they can tell us which clipboard selections they want enabled
        #(ie: OSX and win32 only use "CLIPBOARD" by default, and not "PRIMARY" or "SECONDARY")
        log("enabling selections: %s", csv(selections))
        for selection, proxy in self._clipboard_proxies.items():
            proxy.set_enabled(selections and bytestostr(selection) in selections)

    def set_greedy_client(self, greedy:bool) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.set_greedy_client(greedy)

    def set_want_targets_client(self, want_targets:bool) -> None:
        log("set_want_targets_client(%s)", want_targets)
        self._want_targets = want_targets

    def set_preferred_targets(self, preferred_targets) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.set_preferred_targets(preferred_targets)


    def init_packet_handlers(self):
        self._packet_handlers : Dict[str,Callable] = {
            "clipboard-token"               : self._process_clipboard_token,
            "clipboard-request"             : self._process_clipboard_request,
            "clipboard-contents"            : self._process_clipboard_contents,
            "clipboard-contents-none"       : self._process_clipboard_contents_none,
            "clipboard-pending-requests"    : self._process_clipboard_pending_requests,
            "clipboard-enable-selections"   : self._process_clipboard_enable_selections,
            }

    def make_proxy(self, selection:str) -> ClipboardProxyCore:
        raise NotImplementedError()

    def init_proxies_claim(self) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.claim()


    # Used by the client during startup:
    def send_tokens(self, selections:Iterable[str]=()) -> None:
        log("send_tokens(%s)", selections)
        for selection in selections:
            proxy = self._clipboard_proxies.get(selection)
            if proxy:
                proxy._have_token = False
                proxy.do_emit_token()

    def send_all_tokens(self) -> None:
        #only send the tokens that we're actually handling:
        self.send_tokens(tuple(self._clipboard_proxies.keys()))


    def _process_clipboard_token(self, packet : PacketType) -> None:
        selection = bytestostr(packet[1])
        name = self.remote_to_local(selection)
        proxy = self._clipboard_proxies.get(name)
        if proxy is None:
            #this can happen if the server has fewer clipboards than the client,
            #ie: with win32 shadow servers
            l : Callable = log.debug
            if name in ALL_CLIPBOARDS:
                l = log.warn
            l("ignoring token for clipboard '%s' (no proxy)", name)
            return
        if not proxy.is_enabled():
            log.warn("ignoring token for disabled clipboard '%s'", name)
            return
        log("process clipboard token selection=%s, local clipboard name=%s, proxy=%s", selection, name, proxy)
        targets = None
        target_data = None
        if proxy._can_receive:
            if len(packet)>=3:
                targets = self.local_targets(packet[2])
            if len(packet)>=8:
                target, dtype, dformat, wire_encoding, wire_data = packet[3:8]
                if target:
                    assert dformat in (8, 16, 32), "invalid format '%s' for datatype=%s and wire encoding=%s" % (
                        dformat, dtype, wire_encoding)
                    target = bytestostr(target)
                    if not must_discard(target):
                        wire_encoding = bytestostr(wire_encoding)
                        dtype = bytestostr(dtype)
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

    def local_targets(self, remote_targets:Iterable[str]):
        return _filter_targets(remote_targets)

    def remote_targets(self, local_targets:Iterable[str]):
        return _filter_targets(local_targets)

    def _munge_raw_selection_to_wire(self, target:str, dtype:str, dformat:int, data) -> Tuple[Any,Any]:
        log("_munge_raw_selection_to_wire, target=%s, type=%s, format=%s, len(data)=%s",
                 target, dtype, dformat, len(data or b""))
        if self.max_clipboard_send_size > 0:
            log("perform clipboard limit checking - datasize - %d, %d", len(data), self.max_clipboard_send_size)
            max_send_datalen = self.max_clipboard_send_size * 8 // get_format_size(dformat)
            if len(data) > max_send_datalen:
                olen = len(data)
                data = data[:max_send_datalen]
                log.info("clipboard data copied out truncated because of clipboard policy %d to %d",
                         olen, max_send_datalen)
        # Some types just cannot be marshalled:
        if dtype in ("WINDOW", "PIXMAP", "BITMAP", "DRAWABLE",
                    "PIXEL", "COLORMAP"):
            log("skipping clipboard data of type: %s, format=%s, len(data)=%s", dtype, dformat, len(data or b""))
            return None, None
        if target=="TARGETS" and dtype=="ATOM" and isinstance(data, (tuple, list)):
            #targets is special cased here
            #because we can get the values in wire format already (not atoms)
            #thanks to the request_targets() function (required on win32)
            return "atoms", self.remote_targets(data)
        try:
            return self._do_munge_raw_selection_to_wire(target, dtype, dformat, data)
        except Exception:
            log.error("Error: failed to convert selection data to wire format")
            log.error(" target was %s", target)
            log.error(" dtype=%s, dformat=%s, data=%s (%s)", dtype, dformat, repr_ellipsized(str(data)), type(data))
            raise

    def _do_munge_raw_selection_to_wire(self, target:str, dtype:str, dformat:int, data) -> Tuple[Any,Any]:
        """ this method is overridden in xclipboard to parse X11 atoms """
        # Other types need special handling, and all types need to be
        # converting into an endian-neutral format:
        log("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s)", target, dtype, dformat, type(data), len(data or ""))
        if dformat == 32:
            #you should be using gdk_clipboard for atom support!
            if dtype in ("ATOM", "ATOM_PAIR") and POSIX:
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
        log.error(f"Error: unhandled format {dformat} for clipboard data type {dtype}")
        return None, None

    def _munge_wire_selection_to_raw(self, encoding:str, dtype:str, dformat:int, data) -> bytes:
        log("wire selection to raw, encoding=%s, type=%s, format=%s, len(data)=%s",
            encoding, dtype, dformat, len(data or b""))
        if self.max_clipboard_receive_size > 0:
            log("perform clipboard limit checking - datasize - %d, %d", len(data), self.max_clipboard_send_size)
            max_recv_datalen = self.max_clipboard_receive_size * 8 // get_format_size(dformat)
            if len(data) > max_recv_datalen:
                olen = len(data)
                data = data[:max_recv_datalen]
                log.info("clipboard data copied in truncated because of clipboard policy %d to %d",
                         olen, max_recv_datalen)
        if data and isinstance(data, memoryview):
            data = bytes(data)
        if encoding == "bytes":
            return data
        if encoding == "integers":
            if not data:
                return b""
            if dformat == 32:
                format_char = b"L"
            elif dformat == 16:
                format_char = b"H"
            elif dformat == 8:
                format_char = b"B"
            else:
                raise ValueError(f"unknown encoding format: {dformat}")
            fstr = b"@" + format_char * len(data)
            log("struct.pack(%s, %s)", fstr, data)
            return struct.pack(fstr, *data)
        raise ValueError("unhanled encoding: %s" % ((encoding, dtype, dformat),))

    def _process_clipboard_request(self, packet : PacketType) -> None:
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
            #err, we were asked about a clipboard we don't handle...
            log.error("Error: clipboard request for '%s' (no proxy, ignored)", name)
            no_contents()
            return
        if not proxy.is_enabled():
            log.warn("Warning: ignoring clipboard request for '%s' (disabled)", name)
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
            self.proxy_got_contents(request_id, selection, target, dtype, dformat, data)
        proxy.get_contents(target, got_contents)

    def proxy_got_contents(self, request_id:int, selection:str, target:str, dtype:str, dformat:int, data) -> None:
        def no_contents():
            self.send("clipboard-contents-none", request_id, selection)
        dtype = bytestostr(dtype)
        if is_debug_enabled("clipboard"):
            log("proxy_got_contents(%s, %s, %s, %s, %s, %s:%s) data=0x%s..",
                  request_id, selection, target,
                  dtype, dformat, type(data), len(data or ""), hexstr((data or "")[:200]))
        if dtype is None or data is None or (dformat==0 and not data):
            no_contents()
            return
        truncated = 0
        if self.max_clipboard_send_size > 0:
            log("perform clipboard limit checking - datasize - %d, %d", len(data), self.max_clipboard_send_size)
            max_send_datalen = self.max_clipboard_send_size * 8 // get_format_size(dformat)
            if len(data) > max_send_datalen:
                truncated = len(data) - max_send_datalen
                data = data[:max_send_datalen]
        munged = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
        if is_debug_enabled("clipboard"):
            log("clipboard raw -> wire: %r -> %r",
                (dtype, dformat, ellipsizer(data)), ellipsizer(munged))
        wire_encoding, wire_data = munged
        if wire_encoding is None:
            no_contents()
            return
        wire_data = self._may_compress(dtype, dformat, wire_data)
        if wire_data is not None:
            packet = ["clipboard-contents", request_id, selection,
                    dtype, dformat, wire_encoding, wire_data, truncated]
            self.send(*packet)

    def _may_compress(self, dtype:str, dformat:int, wire_data):
        if len(wire_data)>self.max_clipboard_packet_size:
            log.warn("Warning: clipboard contents are too big and have not been sent")
            log.warn(" %s compressed bytes dropped (maximum is %s)", len(wire_data), self.max_clipboard_packet_size)
            return None
        l = len(wire_data)
        if isinstance(wire_data, (str, bytes)) and l>=MIN_CLIPBOARD_COMPRESS_SIZE:
            if isinstance(wire_data, str):
                #compression requires bytes:
                #but this would require the receiving end to use net_utf8()
                wire_data = wire_data.encode("utf8")
                log("encoded %i characters to %i utf8 bytes", l, len(wire_data))
            return Compressible(f"clipboard: {dtype} / {dformat}", wire_data)
        return wire_data

    def _process_clipboard_contents(self, packet : PacketType) -> None:
        request_id, selection, dtype, dformat, wire_encoding, wire_data = packet[1:7]
        selection = bytestostr(selection)
        wire_encoding = bytestostr(wire_encoding)
        dtype = bytestostr(dtype)
        log("process clipboard contents, selection=%s, type=%s, format=%s", selection, dtype, dformat)
        raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
        if log.is_debug_enabled():
            r = ellipsizer
            log("clipboard wire -> raw: %s -> %s", (dtype, dformat, wire_encoding, r(wire_data)), r(raw_data))
        assert isinstance(request_id, int) and isinstance(dformat, int)
        self._clipboard_got_contents(request_id, dtype, dformat, raw_data)

    def _process_clipboard_contents_none(self, packet : PacketType) -> None:
        log("process clipboard contents none")
        request_id = packet[1]
        assert isinstance(request_id, int)
        self._clipboard_got_contents(request_id, "", 0, None)

    def _clipboard_got_contents(self, request_id:int, dtype:str, dformat:int, data) -> None:
        raise NotImplementedError()


    def progress(self) -> None:
        self.progress_cb(len(self._clipboard_outstanding_requests), None)


    def _process_clipboard_pending_requests(self, packet : PacketType) -> None:
        pending = packet[1]
        self.progress_cb(None, pending)

    def _process_clipboard_enable_selections(self, packet : PacketType) -> None:
        selections = tuple(bytestostr(x) for x in packet[1])
        self.enable_selections(selections)


    def process_clipboard_packet(self, packet : PacketType) -> None:
        packet_type = bytestostr(packet[0])
        handler = self._packet_handlers.get(packet_type)
        if handler:
            #log("process clipboard handler(%s)=%s", packet_type, handler)
            handler(packet)
        else:
            log.warn(f"Warning: no clipboard packet handler for {packet_type!r}")
