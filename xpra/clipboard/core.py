# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from time import monotonic
from typing import Any, Final
from collections import deque
from collections.abc import Callable, Iterable, Sequence

from xpra.common import noop
from xpra.net.compression import Compressible
from xpra.net.common import Packet, PacketElement, packet_handler
from xpra.net.clipboard_packet import (
    MAX_CLIPBOARD_TARGETS, MAX_CLIPBOARD_ORIGIN_SIZE, MAX_CLIPBOARD_OPTIONS, MAX_SELECTIONS, MAX_SELECTION_NAME,
    MAX_WIRE_ENCODING,
    get_name, get_names, get_selection, parse_wire_data, parse_clipboard_data_items,
)
from xpra.net.packet_values import check_key
from xpra.net.dispatch import SubsystemPacketHandlers
from xpra.os_util import POSIX, get_hex_uuid
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, repr_ellipsized, bytestostr, hexstr
from xpra.util.env import envint, envbool, first_time
from xpra.clipboard.common import (
    get_format_size, sizeof_long, sizeof_short, compile_filters, get_local_selections,
    ALL_CLIPBOARDS,
)
from xpra.clipboard.targets import (
    HTML_TARGETS,
    PLAIN_TEXT_TARGETS,
    RTF_TARGETS,
    URI_TARGETS,
    _filter_targets,
    must_discard,
    DISCARD_EXTRA_TARGETS,
    DISCARD_TARGETS,
)
from xpra.net.packet_type import (
    CLIPBOARD_CONTENTS, CLIPBOARD_CONTENTS_NONE, CLIPBOARD_DATA, CLIPBOARD_ENABLE_SELECTIONS, CLIPBOARD_PENDING_REQUESTS, CLIPBOARD_REQUEST,
)
from xpra.log import Logger, is_debug_enabled

log = Logger("clipboard")

MIN_CLIPBOARD_COMPRESS_SIZE: Final[int] = envint("XPRA_MIN_CLIPBOARD_COMPRESS_SIZE", 512)
MAX_CLIPBOARD_PACKET_SIZE: Final[int] = 16 * 1024 * 1024
MAX_CLIPBOARD_RECEIVE_SIZE: Final[int] = envint("XPRA_MAX_CLIPBOARD_RECEIVE_SIZE", -1)
MAX_CLIPBOARD_SEND_SIZE: Final[int] = envint("XPRA_MAX_CLIPBOARD_SEND_SIZE", -1)
MAX_CLIPBOARD_ORIGINS: Final[int] = 16
# the requests from the peer we are still serving, each one may be waiting for a local application:
MAX_CLIPBOARD_PEER_REQUESTS: Final[int] = envint("XPRA_MAX_CLIPBOARD_PEER_REQUESTS", 32)
# a request which has not been answered by then is forgotten:
PEER_REQUEST_EXPIRY: Final[float] = 10

DEFAULT_PREFERRED_TARGETS = ",".join(
    PLAIN_TEXT_TARGETS + HTML_TARGETS + URI_TARGETS + RTF_TARGETS
)
if POSIX:
    DEFAULT_PREFERRED_TARGETS += ",image/png"
PREFERRED_TARGETS = tuple(os.environ.get("XPRA_CLIPBOARD_PREFERRED_TARGETS", DEFAULT_PREFERRED_TARGETS).split(","))

TEST_DROP_CLIPBOARD_REQUESTS = envint("XPRA_TEST_DROP_CLIPBOARD")

# targets we never wish to handle:
# targets some applications are known to request,
# even when the peer did not expose them as valid targets,
# rather than forwarding the request and then timing out,
# we will just drop them
log("DISCARD_TARGETS=%s", csv(DISCARD_TARGETS))
log("DISCARD_EXTRA_TARGETS=%s", csv(DISCARD_EXTRA_TARGETS))


class ClipboardProtocolHelperCore(SubsystemPacketHandlers):
    """
    The clipboard helper owns the whole `clipboard` packet namespace, but it is not a
    subsystem: it has no `PacketDispatcher` to be routed from, and it can be driven
    standalone (see `unit/clipboard_core_test.py`).
    The `clipboard` subsystem on either side registers every `clipboard-*` packet type
    against a single handler which validates the packet - readonly mode, which client
    owns the clipboard, whether clipboard sharing is still enabled - and then hands it
    to `process_clipboard_packet` below, which is the second dispatch stage.
    Deriving from `SubsystemPacketHandlers` means that stage uses the same registry,
    naming convention and `PREFIX` stripping as every subsystem: `clipboard-data` is
    handled by `_process_data`.
    """
    PREFIX = "clipboard"

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
        self._clipboard_outstanding_requests: dict[int, tuple[int, str, str, str]] = {}
        self._peer_requests: dict[int, float] = {}
        self._clipboard_origins: dict[str, deque[str]] = {}
        self._local_to_remote: dict[str, str] = {}
        self._remote_to_local: dict[str, str] = {}
        selections = get_local_selections(d.boolget("all-selections"))
        self.init_translation(kwargs, selections)
        self._want_targets: tuple[str, ...] = ()
        self._greedy: tuple[str, ...] = ()
        self.init_packet_handlers()
        self.init_proxies(d.strtupleget("clipboards.local", selections))
        self.remote_clipboards = d.strtupleget("clipboards.remote", selections)
        self.local_want_targets = tuple(selections) if envbool("XPRA_CLIPBOARD_WANT_TARGETS") else ()
        self.local_greedy = tuple(selections) if envbool("XPRA_CLIPBOARD_GREEDY") else ()
        self.local_preferred_targets = PREFERRED_TARGETS
        self.local_selections = selections

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "preferred-targets": self.local_preferred_targets,
            "selections": self.local_selections,
        }
        # some implementations must set the targets when claiming the clipboard:
        if self.local_want_targets:
            caps["want_targets"] = self.local_want_targets
        # some implementation must set a value to claim the clipboard (ie: win32 and osx)
        if self.local_greedy:
            # Older peers read this using boolget(), so a non-empty tuple is
            # backwards compatible with the old boolean capability.
            caps["greedy"] = self.local_greedy
        return caps

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

    def proxy_want_targets(self, selection: str) -> bool:
        return self.local_to_remote(selection) in self._want_targets

    def proxy_greedy(self, selection: str) -> bool:
        return self.local_to_remote(selection) in self._greedy

    def local_greedy_selection(self, selection: str) -> bool:
        return selection in self.local_greedy

    def set_want_targets_client(self, want_targets: Sequence[str]) -> None:
        log("set_want_targets_client(%s)", want_targets)
        self._want_targets = tuple(want_targets)
        # pass it on to the ClipboardProxy instances:
        for selection, proxy in self._clipboard_proxies.items():
            proxy.set_want_targets(self.proxy_want_targets(selection))

    def init_translation(self, kwargs: dict, local_selections: Sequence[str]) -> None:
        # the selections we can translate from and to, unless specified:
        defaults = {
            "local": local_selections,
            "remote": ALL_CLIPBOARDS,
        }

        def getselection(name: str) -> str:
            v = kwargs.get(f"clipboard.{name}")  # ie: clipboard.remote
            env_value = os.environ.get(f"XPRA_TRANSLATEDCLIPBOARD_{name.upper()}_SELECTION")
            selections = kwargs.get(f"clipboards.{name}", defaults[name])  # ie: clipboards.remote
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
        info: dict[str, str | int | Sequence[str] | Sequence[int] | bool | dict] = {
            "type": str(self).replace("ClipboardProtocolHelper", ""),
            "max_size": self.max_clipboard_packet_size,
            "max_recv_size": self.max_clipboard_receive_size,
            "max_send_size": self.max_clipboard_send_size,
            "filters": [x.pattern for x in self.filter_res],
            "requests": self._clipboard_request_counter,
            "pending": tuple(self._clipboard_outstanding_requests.keys()),
            "peer-requests": len(self._peer_requests),
            "can-send": self.can_send,
            "can-receive": self.can_receive,
            "remote": {
                "want_targets": self._want_targets,
                "greedy": self._greedy,
                "remote-clipboards": self.remote_clipboards,
            },
            "local": {
                "want-targets": self.local_want_targets,
                "greedy": self.local_greedy,
            },
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
        self._clipboard_origins = {}
        self._peer_requests = {}

    def client_reset(self) -> None:
        """Reset state associated with the disconnected clipboard peer."""
        self._clipboard_origins.clear()
        self._peer_requests.clear()
        for proxy in self._clipboard_proxies.values():
            # a token we have scheduled but not sent belongs to the peer which is gone:
            proxy.cancel_emit_token()
            proxy._clipboard_origin = ""

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

    def set_greedy_client(self, greedy: Sequence[str]) -> None:
        log("set_greedy_client(%s)", greedy)
        self._greedy = tuple(greedy)
        for selection, proxy in self._clipboard_proxies.items():
            proxy.set_greedy_client(self.proxy_greedy(selection))

    def set_preferred_targets(self, preferred_targets) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.set_preferred_targets(preferred_targets)

    def init_packet_handlers(self) -> None:
        # this is also the only place the registry is created: the helper can be driven
        # standalone, without `__init__` having run (see `unit/clipboard_core_test.py`)
        self._packet_handlers = {}
        self.register_packet_handlers()

    def make_proxy(self, selection: str):
        raise NotImplementedError()

    def init_proxies_claim(self) -> None:
        for proxy in self._clipboard_proxies.values():
            proxy.claim()

    def remember_clipboard_origin(self, selection: str, origin: str) -> None:
        origins = self._clipboard_origins.setdefault(selection, deque(maxlen=MAX_CLIPBOARD_ORIGINS))
        try:
            origins.remove(origin)
        except ValueError:
            pass
        origins.append(origin)

    def is_clipboard_loop(self, selection: str, origin: str) -> bool:
        return origin in self._clipboard_origins.get(selection, ())

    # Used by the client during startup:
    def send_tokens(self, selections: Iterable[str] = ()) -> None:
        log("send_tokens(%s)", selections)
        for selection in selections:
            if proxy := self._clipboard_proxies.get(selection):
                # this token replaces any we had scheduled,
                # and is counted and timed like any other:
                proxy.cancel_emit_token()
                proxy.emit_token()

    def send_all_tokens(self) -> None:
        # only send the tokens that we're actually handling:
        self.send_tokens(tuple(self._clipboard_proxies.keys()))

    def _send_clipboard_token_handler(self, proxy, token_data: dict[str, Any]) -> None:
        if log.is_debug_enabled():
            log("_send_clipboard_token_handler(%s, %s)", proxy, repr_ellipsized(token_data))
        remote = self.local_to_remote(proxy._selection)
        targets = token_data.get("targets", ())
        raw_items = token_data.get("data", {})
        options: dict[str, PacketElement] = {
            "claim": proxy._can_send,
            "greedy": self.local_greedy_selection(proxy._selection),
        }
        origin = getattr(proxy, "_clipboard_origin", "")
        if not origin:
            origin = get_hex_uuid()
            proxy._clipboard_origin = origin
        self.remember_clipboard_origin(proxy._selection, origin)
        options["origin"] = origin
        if targets:
            options["targets"] = targets
        wire_items = {}
        for target, item in raw_items.items():
            dtype, dformat, data = item[:3]
            wire_encoding, wire_data = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
            if not wire_encoding:
                continue
            wire_data = self._may_compress(dtype, dformat, wire_data)
            if wire_data is None:
                continue
            # Nested values cannot use the top-level Compressible marker.
            if isinstance(wire_data, Compressible):
                wire_data = wire_data.data
            wire_items[target] = (dtype, dformat, wire_encoding, wire_data)
        if wire_items:
            options["data"] = wire_items
        packet = [CLIPBOARD_DATA, remote, options]
        log("send_clipboard_token_handler %s to %s", proxy._selection, remote)
        self.send(*packet)

    def _get_clipboard_token_proxy(self, selection: str):
        name = self.remote_to_local(selection)
        proxy = self._clipboard_proxies.get(name)
        if proxy is None:
            # this can happen if the server has fewer clipboards than the client,
            # ie: with win32 shadow servers
            log_fn: Callable = log.debug
            if name in self.local_selections:
                log_fn = log.warn
            log_fn("ignoring token for clipboard %r (no proxy)", name)
            return None
        if not proxy.is_enabled():
            log.warn("ignoring token for disabled clipboard %r", name)
            return None
        log("process clipboard token selection=%s, local clipboard name=%s, proxy=%s", selection, name, proxy)
        return proxy

    @packet_handler(CLIPBOARD_DATA)
    def _process_data(self, packet: Packet) -> None:
        packet.check_len(3, 3)
        selection = get_selection(packet[1])
        options = packet.get_dict(2, MAX_CLIPBOARD_OPTIONS)
        for key in options:
            check_key(key, "clipboard option")
        origin = options.get("origin", "")
        if isinstance(origin, bytes):
            origin = origin.decode("latin1")
        if not isinstance(origin, str) or len(origin) > MAX_CLIPBOARD_ORIGIN_SIZE:
            raise ValueError(f"invalid clipboard origin {repr_ellipsized(origin)}")
        remote_targets = get_names(options["targets"]) if "targets" in options else None
        data = parse_clipboard_data_items(options["data"], self.max_clipboard_packet_size) if "data" in options else {}
        proxy = self._get_clipboard_token_proxy(selection)
        if proxy is None:
            return
        if origin and self.is_clipboard_loop(proxy._selection, origin):
            log.warn("Warning: clipboard loop detected for %r", proxy._selection)
            return
        proxy._clipboard_origin = origin
        targets = None
        target_data = None
        if proxy._can_receive:
            if remote_targets is not None:
                targets = self.local_targets(remote_targets)
            if data:
                target_data = {}
                for target, (dtype, dformat, wire_encoding, wire_data) in data.items():
                    if must_discard(target) or not self.may_intern(target, dtype):
                        continue
                    raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
                    target_data[target] = (dtype, dformat, raw_data)
        if "greedy" in options:
            proxy._greedy_client = bool(options["greedy"])
        if options.get("token", True):
            proxy.got_token(targets, target_data, bool(options.get("claim", True)), bool(options.get("synchronous", False)))

    def local_targets(self, remote_targets: Iterable[str]) -> Sequence[str]:
        """ filter remote targets to values that can be used locally """
        targets = _filter_targets(remote_targets)
        if len(targets) > MAX_CLIPBOARD_TARGETS:
            log.warn("Warning: too many clipboard targets, only using the first %i out of %i",
                     MAX_CLIPBOARD_TARGETS, len(targets))
            targets = targets[:MAX_CLIPBOARD_TARGETS]
        accepted = self.accept_names(targets)
        return tuple(target for target in targets if target in accepted)

    def accept_names(self, names: Sequence[str]) -> set[str]:
        """
        the target and type names received from the peer which we are willing to use,
        subclasses that store them in a resource which is never freed (ie: X11 atoms) must limit them
        """
        return set(names)

    def may_intern(self, *names: str) -> bool:
        return set(names) <= self.accept_names(names)

    def may_request(self, selection: str, target: str) -> bool:
        """ can we request this target from the local `selection` on behalf of the peer """
        return self.may_intern(target)

    def remote_targets(self, local_targets: Iterable[str]) -> Sequence[str]:
        """ export local targets """
        return _filter_targets(local_targets)

    def _munge_raw_selection_to_wire(self, target: str, dtype: str, dformat: int, data) -> tuple[str, Any]:
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
            return "", ()
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

    def _do_munge_raw_selection_to_wire(self, target: str, dtype: str, dformat: int, data) -> tuple[str, Any]:
        """ this method is overridden in xclipboard to parse X11 atoms """
        # Other types need special handling, and all types need to be
        # converting into an endian-neutral format:
        log("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s)", target, dtype, dformat, type(data), len(data or ""))
        if dformat == 32:
            # you should be using gdk_clipboard for atom support!
            if dtype in ("ATOM", "ATOM_PAIR") and POSIX:
                # we cannot handle gdk atoms here (but gdk_clipboard does)
                return "", ()
            # important note: on 64 bits, format=32 means 8 bytes, not 4
            # that's just the way it is...
            binfmt = b"@" + b"L" * (len(data) // sizeof_long)
            ints = struct.unpack(binfmt, data)
            return "integers", ints
        if dformat == 16:
            binfmt = b"=" + b"H" * (len(data) // sizeof_short)
            ints = struct.unpack(binfmt, data)
            return "integers", ints
        if dformat == 8:
            for x in self.filter_res:
                if x.match(data):
                    log.warn("clipboard buffer contains blocklisted pattern '%s' and has been dropped!", x.pattern)
                    return "", ()
            return "bytes", data
        log.error(f"Error: unhandled format {dformat} for clipboard data type {dtype}")
        return "", ()

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

    def expire_peer_requests(self) -> None:
        now = monotonic()
        for request_id, start in tuple(self._peer_requests.items()):
            if now - start > PEER_REQUEST_EXPIRY:
                log("clipboard request %i has expired", request_id)
                del self._peer_requests[request_id]

    @packet_handler(CLIPBOARD_REQUEST)
    def _process_request(self, packet: Packet) -> None:
        packet.check_len(4, 4)
        request_id = packet.get_u64(1)
        selection = get_selection(packet[2])
        target = get_name(packet[3])

        def no_contents():
            self._peer_requests.pop(request_id, None)
            self.send(CLIPBOARD_CONTENTS_NONE, request_id, selection)

        if request_id in self._peer_requests:
            log.warn("Warning: duplicate clipboard request id %i, ignored", request_id)
            return
        self.expire_peer_requests()
        if len(self._peer_requests) >= MAX_CLIPBOARD_PEER_REQUESTS:
            if first_time("clipboard-peer-requests"):
                log.warn("Warning: too many pending clipboard requests, the limit is %i", MAX_CLIPBOARD_PEER_REQUESTS)
            self.send(CLIPBOARD_CONTENTS_NONE, request_id, selection)
            return
        self._peer_requests[request_id] = monotonic()
        if must_discard(target):
            log("invalid target %r", target)
            no_contents()
            return
        name = self.remote_to_local(selection)
        log("process clipboard request, request_id=%s, selection=%s, local name=%s, target=%s",
            request_id, selection, name, target)
        proxy = self._clipboard_proxies.get(name)
        if proxy is None:
            # err, we were asked about a clipboard we don't handle...
            log.error("Error: clipboard request for %r (no proxy, ignored)", name)
            no_contents()
            return
        if not proxy.is_enabled():
            log.warn("Warning: ignoring clipboard request for %r", name)
            no_contents()
            return
        if not proxy._can_send:
            log("request for %s but sending is disabled, sending 'none' back", name)
            no_contents()
            return
        if not self.may_request(name, target):
            log("request for %s target %r refused", name, target)
            no_contents()
            return
        if TEST_DROP_CLIPBOARD_REQUESTS > 0 and (request_id % TEST_DROP_CLIPBOARD_REQUESTS) == 0:
            log.warn("clipboard request %s dropped for testing!", request_id)
            return

        def got_contents(dtype="STRING", dformat=0, data=b"") -> None:
            self.proxy_got_contents(request_id, selection, target, dtype, dformat, data)

        proxy.get_contents(target, got_contents)

    def proxy_got_contents(self, request_id: int, selection: str, target: str, dtype: str, dformat: int, data) -> None:
        self._peer_requests.pop(request_id, None)

        def no_contents():
            self.send(CLIPBOARD_CONTENTS_NONE, request_id, selection)

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
        if not wire_encoding:
            no_contents()
            return
        wire_data = self._may_compress(dtype, dformat, wire_data)
        if wire_data is None:
            no_contents()
            return
        packet = [CLIPBOARD_CONTENTS, request_id, selection,
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

    @packet_handler(CLIPBOARD_CONTENTS)
    def _process_contents(self, packet: Packet) -> None:
        # the html5 client does not send the `truncated` field:
        packet.check_len(7, 8)
        request_id = packet.get_u64(1)
        selection = get_selection(packet[2])
        dtype = get_name(packet[3], what="type")
        dformat = packet.get_u8(4)
        wire_encoding = packet.get_str(5, MAX_WIRE_ENCODING)
        wire_data, _size = parse_wire_data(wire_encoding, dformat, packet[6], self.max_clipboard_packet_size)
        if len(packet) > 7:
            packet.get_u64(7)
        log("process clipboard contents, selection=%s, type=%s, format=%s", selection, dtype, dformat)
        if not self.may_intern(dtype):
            log("clipboard contents type %r refused", dtype)
            self._clipboard_got_contents(request_id, selection=selection)
            return
        raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
        if log.is_debug_enabled():
            r = Ellipsizer
            log("clipboard wire -> raw: %s -> %s", (dtype, dformat, wire_encoding, r(wire_data)), r(raw_data))
        self._clipboard_got_contents(request_id, dtype, dformat, raw_data, selection=selection, encoding=wire_encoding)

    @packet_handler(CLIPBOARD_CONTENTS_NONE)
    def _process_contents_none(self, packet: Packet) -> None:
        log("process clipboard contents none")
        packet.check_len(3, 3)
        request_id = packet.get_u64(1)
        selection = get_selection(packet[2])
        self._clipboard_got_contents(request_id, selection=selection)

    def _clipboard_got_contents(self, request_id: int, dtype: str = "", dformat: int = 0, data=None,
                                selection: str = "", encoding: str = "") -> None:
        """
        `selection` and `encoding` are only specified for replies received from the peer,
        they must match the request
        """
        raise NotImplementedError()

    def progress(self) -> None:
        self.progress_cb(len(self._clipboard_outstanding_requests), -1)

    @packet_handler(CLIPBOARD_PENDING_REQUESTS)
    def _process_pending_requests(self, packet: Packet) -> None:
        packet.check_len(2, 2)
        pending = packet.get_u8(1)
        self.progress_cb(-1, pending)

    @packet_handler(CLIPBOARD_ENABLE_SELECTIONS)
    def _process_enable_selections(self, packet: Packet) -> None:
        packet.check_len(2, 2)
        selections = tuple(get_selection(x) for x in packet.get_strs(1, MAX_SELECTIONS, MAX_SELECTION_NAME))
        self.enable_selections(selections)

    def process_clipboard_packet(self, packet: Packet) -> None:
        # second dispatch stage: the `clipboard` subsystem has already validated this packet
        packet_type = packet.get_type()
        handler_def = None
        if self.owns_packet(packet_type):
            handler_def = self.get_packet_handler(self.packet_subtype(packet_type))
        if not handler_def:
            log.warn(f"Warning: no clipboard packet handler for {packet_type!r}")
            return
        # our handlers take just the packet, and the caller has already scheduled us
        # on the main thread where needed, so the `main_thread` flag is unused here:
        handler_def[0](packet)
