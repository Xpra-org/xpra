# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from typing import Any, Final
from collections.abc import Callable, Iterable, Sequence

from xpra.common import noop
from xpra.net.compression import Compressible
from xpra.net.common import Packet, PacketElement
from xpra.os_util import POSIX
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, repr_ellipsized, bytestostr, hexstr
from xpra.util.env import envint
from xpra.platform.features import CLIPBOARDS as PLATFORM_CLIPBOARDS, CLIPBOARD_GREEDY
from xpra.clipboard.common import get_format_size, sizeof_long, sizeof_short, compile_filters
from xpra.clipboard.targets import _filter_targets, must_discard, DISCARD_EXTRA_TARGETS, DISCARD_TARGETS
from xpra.log import Logger, is_debug_enabled

log = Logger("clipboard")

MIN_CLIPBOARD_COMPRESS_SIZE: Final[int] = envint("XPRA_MIN_CLIPBOARD_COMPRESS_SIZE", 512)
MAX_CLIPBOARD_PACKET_SIZE: Final[int] = 16 * 1024 * 1024
MAX_CLIPBOARD_RECEIVE_SIZE: Final[int] = envint("XPRA_MAX_CLIPBOARD_RECEIVE_SIZE", -1)
MAX_CLIPBOARD_SEND_SIZE: Final[int] = envint("XPRA_MAX_CLIPBOARD_SEND_SIZE", -1)

CLIPBOARDS: list[str] = list(PLATFORM_CLIPBOARDS)
CLIPBOARDS_ENV: str | None = os.environ.get("XPRA_CLIPBOARDS")
if CLIPBOARDS_ENV is not None:
    CLIPBOARDS = [x.upper().strip() for x in CLIPBOARDS_ENV.split(",")]
del CLIPBOARDS_ENV

TEST_DROP_CLIPBOARD_REQUESTS = envint("XPRA_TEST_DROP_CLIPBOARD")

# targets we never wish to handle:
# targets some applications are known to request,
# even when the peer did not expose them as valid targets,
# rather than forwarding the request and then timing out,
# we will just drop them
log("DISCARD_TARGETS=%s", csv(DISCARD_TARGETS))
log("DISCARD_EXTRA_TARGETS=%s", csv(DISCARD_EXTRA_TARGETS))


class ClipboardProtocolHelperCore:
    def __init__(self, send_packet_cb: Callable, progress_cb: Callable = noop, **kwargs):
        d = typedict(kwargs)
        self.send: Callable = send_packet_cb
        self.progress_cb: Callable = progress_cb
        self.can_send: bool = d.boolget("can-send", True)
        self.can_receive: bool = d.boolget("can-receive", True)
        self.max_clipboard_packet_size: int = d.intget("max-packet-size", MAX_CLIPBOARD_PACKET_SIZE)
        self.max_clipboard_receive_size: int = d.intget("max-receive-size", MAX_CLIPBOARD_RECEIVE_SIZE)
        self.max_clipboard_send_size: int = d.intget("max-send-size", MAX_CLIPBOARD_SEND_SIZE)
        self.filter_res = compile_filters(d.strtupleget("filters"))
        self._clipboard_request_counter: int = 0
        self._clipboard_outstanding_requests: dict[int, tuple[int, str, str]] = {}
        self._local_to_remote: dict[str, str] = {}
        self._remote_to_local: dict[str, str] = {}
        self.init_translation(kwargs)
        self._want_targets: bool = False
        self.init_packet_handlers()
        self.init_proxies(d.strtupleget("clipboards.local", CLIPBOARDS))
        self.remote_clipboards = d.strtupleget("clipboards.remote", CLIPBOARDS)

    def init_proxies(self, selections: Iterable[str]) -> None:
        self._clipboard_proxies: dict[str, Any] = {}
        for selection in selections:
            proxy = self.make_proxy(selection)
            self._clipboard_proxies[selection] = proxy
        log("%s.init_proxies : %s", self, self._clipboard_proxies)

    def _get_proxy(self, selection: str):
        proxy = self._clipboard_proxies.get(selection)
        if not proxy:
            log.warn("Warning: no clipboard proxy for '%s'", selection)
        return proxy

    def set_want_targets_client(self, want_targets: bool) -> None:
        log("set_want_targets_client(%s)", want_targets)
        self._want_targets = want_targets
        # pass it on to the ClipboardProxy instances:
        for proxy in self._clipboard_proxies.values():
            proxy.set_want_targets(want_targets)

    def init_translation(self, kwargs: dict) -> None:
        def getselection(name: str) -> str:
            v = kwargs.get(f"clipboard.{name}")  # ie: clipboard.remote
            env_value = os.environ.get(f"XPRA_TRANSLATEDCLIPBOARD_{name.upper()}_SELECTION")
            selections = kwargs.get(f"clipboards.{name}", ())  # ie: clipboards.remote
            if not selections:
                return ""
            for x in (env_value, v):
                if x and x in selections:
                    return x
            return selections[0]

        local = getselection("local")
        remote = getselection("remote")
        log(f"init_translation({kwargs}) {local=!r} {remote=!r}")
        if local and remote:
            self._local_to_remote[local] = remote
            self._remote_to_local[remote] = local

    def local_to_remote(self, selection: str) -> str:
        return self._local_to_remote.get(selection, selection)

    def remote_to_local(self, selection: str) -> str:
        return self._remote_to_local.get(selection, selection)

    def get_remote_selections(self) -> list[str]:
        # figure out which remote selections we are interested in:
        selections = []
        for selection in self._clipboard_proxies.keys():
            selections.append(self.local_to_remote(selection))
        return selections

    def __repr__(self):
        return "ClipboardProtocolHelperCore"

    def get_info(self) -> dict[str, Any]:
        info: dict[str, str | int | Sequence[str] | bool | dict] = {
            "type": str(self).replace("ClipboardProtocolHelper", ""),
            "max_size": self.max_clipboard_packet_size,
            "max_recv_size": self.max_clipboard_receive_size,
            "max_send_size": self.max_clipboard_send_size,
            "filters": [x.pattern for x in self.filter_res],
            "requests": self._clipboard_request_counter,
            "pending": tuple(self._clipboard_outstanding_requests.keys()),
            "can-send": self.can_send,
            "can-receive": self.can_receive,
            "want_targets": self._want_targets,
        }
        for clipboard, proxy in self._clipboard_proxies.items():
            info[clipboard] = proxy.get_info()
        return info

    def cleanup(self) -> None:
        """ during cleanup, stop sending packets """
        self.send = noop
        for x in self._clipboard_proxies.values():
            x.cleanup()
        self._clipboard_proxies = {}

    def client_reset(self) -> None:
        """ overriden in subclasses to try to reset the state """

    def set_direction(self, can_send: bool, can_receive: bool,
                      max_send_size: int | None = None, max_receive_size: int | None = None) -> None:
        self.can_send = can_send
        self.can_receive = can_receive
        self.set_limits(max_send_size, max_receive_size)
        for proxy in self._clipboard_proxies.values():
            proxy.set_direction(can_send, can_receive)

    def set_limits(self, max_send_size: int | None, max_receive_size: int | None) -> None:
        if max_send_size is not None:
            self.max_clipboard_send_size = max_send_size
        if max_receive_size is not None:
            self.max_clipboard_receive_size = max_receive_size

    def enable_selections(self, selections: Iterable[str] = ()) -> None:
        # when clients first connect or later through the "clipboard-enable-selections" packet,
        # they can tell us which clipboard selections they want enabled
        # (ie: OSX and win32 only use "CLIPBOARD" by default, and not "PRIMARY" or "SECONDARY")
        log("enabling selections: %s", csv(selections))
        for selection, proxy in self._clipboard_proxies.items():
            proxy.set_enabled(selection in selections)

    def set_greedy_client(self, greedy: bool) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.set_greedy_client(greedy)

    def set_preferred_targets(self, preferred_targets) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.set_preferred_targets(preferred_targets)

    def init_packet_handlers(self) -> None:
        self._packet_handlers: dict[str, Callable] = {
            "clipboard-token": self._process_clipboard_token,
            "clipboard-request": self._process_clipboard_request,
            "clipboard-contents": self._process_clipboard_contents,
            "clipboard-contents-none": self._process_clipboard_contents_none,
            "clipboard-pending-requests": self._process_clipboard_pending_requests,
            "clipboard-enable-selections": self._process_clipboard_enable_selections,
        }

    def make_proxy(self, selection: str):
        raise NotImplementedError()

    def init_proxies_claim(self) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.claim()

    # Used by the client during startup:
    def send_tokens(self, selections: Iterable[str] = ()) -> None:
        log("send_tokens(%s)", selections)
        for selection in selections:
            proxy = self._clipboard_proxies.get(selection)
            if proxy:
                proxy._have_token = False
                proxy.do_emit_token()

    def send_all_tokens(self) -> None:
        # only send the tokens that we're actually handling:
        self.send_tokens(tuple(self._clipboard_proxies.keys()))

    def _send_clipboard_token_handler(self, proxy, packet_data: tuple[PacketElement] = ()):
        if log.is_debug_enabled():
            log("_send_clipboard_token_handler(%s, %s)", proxy, repr_ellipsized(packet_data))
        remote = self.local_to_remote(proxy._selection)
        packet: list[Any] = ["clipboard-token", remote]
        if packet_data:
            # append 'TARGETS' unchanged:
            packet.append(packet_data[0])
            # if present, the next element is the target data,
            # which we have to convert to wire format:
            if len(packet_data) >= 2:
                target, dtype, dformat, data = packet_data[1]
                wire_encoding, wire_data = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
                if wire_encoding:
                    wire_data = self._may_compress(dtype, dformat, wire_data)
                    if wire_data:
                        packet += [target, dtype, dformat, wire_encoding, wire_data]
                        claim = proxy._can_send
                        packet += [claim, CLIPBOARD_GREEDY]
        log("send_clipboard_token_handler %s to %s", proxy._selection, remote)
        self.send(*packet)

    def _process_clipboard_token(self, packet: Packet) -> None:
        selection = packet.get_str(1)
        name = self.remote_to_local(selection)
        proxy = self._clipboard_proxies.get(name)
        if proxy is None:
            # this can happen if the server has fewer clipboards than the client,
            # ie: with win32 shadow servers
            log_fn: Callable = log.debug
            if name in CLIPBOARDS:
                log_fn = log.warn
            log_fn("ignoring token for clipboard '%s' (no proxy)", name)
            return
        if not proxy.is_enabled():
            log.warn("ignoring token for disabled clipboard '%s'", name)
            return
        log("process clipboard token selection=%s, local clipboard name=%s, proxy=%s", selection, name, proxy)
        targets = None
        target_data = None
        if proxy._can_receive:
            if len(packet) >= 3:
                targets = self.local_targets(packet[2])
            if len(packet) >= 8:
                target = packet.get_str(3)
                dtype = packet.get_str(4)
                dformat = packet.get_u8(5)
                wire_encoding = packet.get_str(6)
                wire_data = packet.get_buffer(7)
                if target:
                    if dformat not in (8, 16, 32):
                        raise ValueError(f"invalid format '{dformat!r}' for type {dtype!r} and wire {wire_encoding=!r}")
                    if not must_discard(target):
                        raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
                        target_data = {target: (dtype, dformat, raw_data)}
        # older versions always claimed the selection when the token is received:
        claim = True
        if len(packet) >= 10:
            claim = bool(packet[8])
            # clients can now also change the greedy flag on the fly,
            # this is needed for clipboard direction restrictions:
            # the client may want to be notified of clipboard changes, just like a greedy client
            proxy._greedy_client = bool(packet[9])
        synchronous_client = len(packet) >= 11 and bool(packet[10])
        proxy.got_token(targets, target_data, claim, synchronous_client)

    def local_targets(self, remote_targets: Iterable[str]) -> Sequence[str]:
        """ filter remote targets to values that can be used locally """
        return _filter_targets(remote_targets)

    def remote_targets(self, local_targets: Iterable[str]) -> Sequence[str]:
        """ export local targets """
        return _filter_targets(local_targets)

    def _munge_raw_selection_to_wire(self, target: str, dtype: str, dformat: int, data) -> tuple[Any, Any]:
        log("_munge_raw_selection_to_wire%s", (target, dtype, dformat, repr_ellipsized(bytestostr(data))))
        if self.max_clipboard_send_size > 0:
            log("perform clipboard limit checking - datasize - %d, %d", len(data), self.max_clipboard_send_size)
            max_send_datalen = self.max_clipboard_send_size * 8 // get_format_size(dformat)
            if len(data) > max_send_datalen:
                olen = len(data)
                data = data[:max_send_datalen]
                log.info("clipboard data copied out truncated because of clipboard policy %d to %d",
                         olen, max_send_datalen)
        # Some types just cannot be marshalled:
        if dtype in (
                "WINDOW", "PIXMAP", "BITMAP", "DRAWABLE",
                "PIXEL", "COLORMAP"
        ):
            log("skipping clipboard data of type: %s, format=%s, len(data)=%s", dtype, dformat, len(data or b""))
            return None, None
        if target == "TARGETS" and dtype == "ATOM" and isinstance(data, (tuple, list)):
            # targets is special cased here
            # because we can get the values in wire format already (not atoms)
            # thanks to the request_targets() function (required on win32)
            return "atoms", self.remote_targets(data)
        try:
            return self._do_munge_raw_selection_to_wire(target, dtype, dformat, data)
        except Exception:
            log.error("Error: failed to convert selection data to wire format")
            log.error(" target was %s", target)
            log.error(" dtype=%s, dformat=%s, data=%s (%s)", dtype, dformat, repr_ellipsized(str(data)), type(data))
            raise

    def _do_munge_raw_selection_to_wire(self, target: str, dtype: str, dformat: int, data) -> tuple[Any, Any]:
        """ this method is overridden in xclipboard to parse X11 atoms """
        # Other types need special handling, and all types need to be
        # converting into an endian-neutral format:
        log("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s)", target, dtype, dformat, type(data), len(data or ""))
        if dformat == 32:
            # you should be using gdk_clipboard for atom support!
            if dtype in ("ATOM", "ATOM_PAIR") and POSIX:
                # we cannot handle gdk atoms here (but gdk_clipboard does)
                return None, None
            # important note: on 64 bits, format=32 means 8 bytes, not 4
            # that's just the way it is...
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
                    log.warn("clipboard buffer contains blocklisted pattern '%s' and has been dropped!", x.pattern)
                    return None, None
            return b"bytes", data
        log.error(f"Error: unhandled format {dformat} for clipboard data type {dtype}")
        return None, None

    def _munge_wire_selection_to_raw(self, encoding: str, dtype: str, dformat: int, data) -> bytes | str:
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

    def _process_clipboard_request(self, packet: Packet) -> None:
        request_id = packet.get_u64(1)
        selection = packet.get_str(2)
        target = packet.get_str(3)

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
            # err, we were asked about a clipboard we don't handle...
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
        if TEST_DROP_CLIPBOARD_REQUESTS > 0 and (request_id % TEST_DROP_CLIPBOARD_REQUESTS) == 0:
            log.warn("clipboard request %s dropped for testing!", request_id)
            return

        def got_contents(dtype="STRING", dformat=0, data=b"") -> None:
            self.proxy_got_contents(request_id, selection, target, dtype, dformat, data)

        proxy.get_contents(target, got_contents)

    def proxy_got_contents(self, request_id: int, selection: str, target: str, dtype: str, dformat: int, data) -> None:
        def no_contents():
            self.send("clipboard-contents-none", request_id, selection)

        dtype = bytestostr(dtype)
        if is_debug_enabled("clipboard"):
            log("proxy_got_contents(%s, %s, %s, %s, %s, %s:%s) data=0x%s..",
                request_id, selection, target,
                dtype, dformat, type(data), len(data or ""), hexstr((data or "")[:200]))
        if dtype is None or data is None or (dformat == 0 and not data):
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
                (dtype, dformat, Ellipsizer(data)), Ellipsizer(munged))
        wire_encoding, wire_data = munged
        if wire_encoding is None:
            no_contents()
            return
        wire_data = self._may_compress(dtype, dformat, wire_data)
        if wire_data is not None:
            packet = ["clipboard-contents", request_id, selection,
                      dtype, dformat, wire_encoding, wire_data, truncated]
            self.send(*packet)

    def _may_compress(self, dtype: str, dformat: int, wire_data):
        if len(wire_data) > self.max_clipboard_packet_size:
            log.warn("Warning: clipboard contents are too big and have not been sent")
            log.warn(" %s compressed bytes dropped (maximum is %s)", len(wire_data), self.max_clipboard_packet_size)
            return None
        size = len(wire_data)
        if isinstance(wire_data, (str, bytes)) and size >= MIN_CLIPBOARD_COMPRESS_SIZE:
            if isinstance(wire_data, str):
                # compression requires bytes:
                # but this would require the receiving end to know it needs to decode the bytes
                wire_data = wire_data.encode("utf8")
                log("encoded %i characters to %i utf8 bytes", size, len(wire_data))
            return Compressible(f"clipboard: {dtype} / {dformat}", wire_data)
        return wire_data

    def _process_clipboard_contents(self, packet: Packet) -> None:
        request_id = packet.get_u64(1)
        selection = packet.get_str(2)
        dtype = packet.get_str(3)
        dformat = packet.get_u8(4)
        wire_encoding = packet.get_str(5)
        wire_data = packet[6]
        log("process clipboard contents, selection=%s, type=%s, format=%s", selection, dtype, dformat)
        raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
        if log.is_debug_enabled():
            r = Ellipsizer
            log("clipboard wire -> raw: %s -> %s", (dtype, dformat, wire_encoding, r(wire_data)), r(raw_data))
        assert isinstance(request_id, int) and isinstance(dformat, int)
        self._clipboard_got_contents(request_id, dtype, dformat, raw_data)

    def _process_clipboard_contents_none(self, packet: Packet) -> None:
        log("process clipboard contents none")
        request_id = packet.get_u64(1)
        self._clipboard_got_contents(request_id, "", 8, b"")

    def _clipboard_got_contents(self, request_id: int, dtype: str, dformat: int, data) -> None:
        raise NotImplementedError()

    def progress(self) -> None:
        self.progress_cb(len(self._clipboard_outstanding_requests), -1)

    def _process_clipboard_pending_requests(self, packet: Packet) -> None:
        pending = packet.get_u8(1)
        self.progress_cb(-1, pending)

    def _process_clipboard_enable_selections(self, packet: Packet) -> None:
        selections = tuple(packet[1])
        self.enable_selections(selections)

    def process_clipboard_packet(self, packet: Packet) -> None:
        packet_type = packet.get_type()
        handler = self._packet_handlers.get(packet_type)
        if handler:
            handler(packet)
        else:
            log.warn(f"Warning: no clipboard packet handler for {packet_type!r}")
