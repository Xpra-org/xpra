# This file is part of Xpra.
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.platform.features import CLIPBOARD_WANT_TARGETS, CLIPBOARD_GREEDY, CLIPBOARD_PREFERRED_TARGETS, CLIPBOARDS
from xpra.platform.gui import get_clipboard_native_class
from xpra.net import compression
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS
from xpra.util import flatten_dict, typedict
from xpra.os_util import bytestostr, is_Wayland
from xpra.log import Logger

log = Logger("clipboard")


class ClipboardClient(StubClientMixin):
    """
    Utility mixin for clients that handle clipboard synchronization
    """
    __signals__ = ["clipboard-toggled"]

    def __init__(self):
        super().__init__()
        self.client_clipboard_type = ""
        self.client_clipboard_direction = "both"
        self.client_supports_clipboard = False
        self.clipboard_enabled = False
        self.server_clipboard_direction = "both"
        self.server_clipboard = False
        self.server_clipboard_direction = ""
        self.server_clipboard_preferred_targets = ()
        self.server_clipboards = ()
        self.server_clipboard_greedy = False
        self.server_clipboard_want_targets = False
        self.server_clipboard_selections = ()
        self.clipboard_helper = None
        self.local_clipboard_requests = 0
        self.remote_clipboard_requests = 0
        #only used with the translated clipboard class:
        self.local_clipboard = ""
        self.remote_clipboard = ""

    def init(self, opts):
        self.client_clipboard_type = opts.clipboard
        self.client_clipboard_direction = opts.clipboard_direction
        self.client_supports_clipboard = (opts.clipboard or "").lower() not in FALSE_OPTIONS
        self.remote_clipboard = opts.remote_clipboard
        self.local_clipboard = opts.local_clipboard


    def cleanup(self):
        ch = self.clipboard_helper
        log("ClipboardClient.cleanup() clipboard_helper=%s", ch)
        if ch:
            self.clipboard_helper = None
            try:
                ch.cleanup()
            except Exception:
                log.error("error on clipboard helper '%s' cleanup", ch, exc_info=True)


    def get_info(self) -> dict:
        return {
            "clipboard": {
                "client" : {
                    "enabled"   : self.clipboard_enabled,
                    "type"      : self.client_clipboard_type,
                    "direction" : self.client_clipboard_direction,
                },
                "server" : {
                    "enabled"   : self.server_clipboard,
                    "direction" : self.server_clipboard_direction,
                    "selections": self.server_clipboards,
                },
                "requests" : {
                    "local"     : self.local_clipboard_requests,
                    "remote"    : self.remote_clipboard_requests,
                    },
                },
            }

    def get_caps(self) -> dict:
        if not self.client_supports_clipboard:
            return {}
        caps = flatten_dict({
            "clipboard" : {
                ""                          : True,
                "notifications"             : True,
                "selections"                : CLIPBOARDS,
                #buggy osx clipboards:
                "want_targets"              : CLIPBOARD_WANT_TARGETS,
                #buggy osx and win32 clipboards:
                "greedy"                    : CLIPBOARD_GREEDY,
                "preferred-targets"         : CLIPBOARD_PREFERRED_TARGETS,
                "set_enabled"               : True,     #v4 servers no longer use or show this flag
                "contents-slice-fix"        : True,     #fixed in v2.4, removed check in v4.3
                },
             })
        return caps

    def parse_server_capabilities(self, c : typedict) -> bool:
        try:
            from xpra import clipboard
            assert clipboard
        except ImportError:
            log.warn("Warning: clipboard module is missing")
            self.clipboard_enabled = False
            return True
        self.server_clipboard = c.boolget("clipboard")
        self.server_clipboard_direction = c.strget("clipboard-direction", "both")
        if self.server_clipboard_direction!=self.client_clipboard_direction and self.server_clipboard_direction!="both":
            if self.client_clipboard_direction=="disabled":
                pass
            elif self.server_clipboard_direction=="disabled":
                log.warn("Warning: server clipboard synchronization is currently disabled")
                self.client_clipboard_direction = "disabled"
            elif self.client_clipboard_direction=="both":
                log.warn("Warning: server only supports '%s' clipboard transfers", self.server_clipboard_direction)
                self.client_clipboard_direction = self.server_clipboard_direction
            else:
                log.warn("Warning: incompatible clipboard direction settings")
                log.warn(" server setting: %s, client setting: %s",
                         self.server_clipboard_direction, self.client_clipboard_direction)
        try:
            from xpra.clipboard.clipboard_core import ALL_CLIPBOARDS
        except ImportError:
            ALL_CLIPBOARDS = []
        self.server_clipboards = c.strtupleget("clipboards", ALL_CLIPBOARDS)
        log("server clipboard: supported=%s, direction=%s",
                     self.server_clipboard, self.server_clipboard_direction)
        log("client clipboard: supported=%s, direction=%s",
                     self.client_supports_clipboard, self.client_clipboard_direction)
        self.clipboard_enabled = self.client_supports_clipboard and self.server_clipboard
        self.server_clipboard_greedy = c.boolget("clipboard.greedy")
        self.server_clipboard_want_targets = c.boolget("clipboard.want_targets")
        self.server_clipboard_selections = c.strtupleget("clipboard.selections", CLIPBOARDS)
        self.server_clipboard_preferred_targets = c.strtupleget("clipboard.preferred-targets", ())
        log("server clipboard: greedy=%s, want_targets=%s, selections=%s",
            self.server_clipboard_greedy, self.server_clipboard_want_targets, self.server_clipboard_selections)
        log("parse_clipboard_caps() clipboard enabled=%s", self.clipboard_enabled)
        self.server_clipboard_preferred_targets = c.strtupleget("clipboard.preferred-targets", ())
        return True

    def process_ui_capabilities(self, caps : typedict):
        log("process_ui_capabilities() clipboard_enabled=%s", self.clipboard_enabled)
        if self.clipboard_enabled:
            ch = self.make_clipboard_helper()
            if not ch:
                log.warn("Warning: no clipboard support")
                if is_Wayland():
                    log.warn(" (wayland display)")
            self.clipboard_helper = ch
            self.clipboard_enabled = ch is not None
            log("clipboard helper=%s", ch)
            if self.clipboard_enabled:
                #tell the server about which selections we really want to sync with
                #(could have been translated, or limited if the client only has one, etc)
                self.send_clipboard_selections(ch.get_remote_selections())
                ch.send_all_tokens()
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")


    def init_authenticated_packet_handlers(self):
        self.add_packet_handler("set-clipboard-enabled", self._process_clipboard_enabled_status)
        for x in (
            "token", "request",
            "contents", "contents-none",
            "pending-requests", "enable-selections",
            ):
            self.add_packet_handler("clipboard-%s" % x, self._process_clipboard_packet)

    def get_clipboard_helper_classes(self):
        ct = self.client_clipboard_type
        if ct and ct.lower() in FALSE_OPTIONS:
            return []
        from xpra.scripts.main import CLIPBOARD_CLASS
        #first add the platform specific one, (may be None):
        clipboard_options = [
            CLIPBOARD_CLASS,
            get_clipboard_native_class(),
            ]
        log("get_clipboard_helper_classes() unfiltered list=%s", clipboard_options)
        if ct and ct.lower()!="auto" and ct.lower() not in TRUE_OPTIONS:
            #try to match the string specified:
            filtered = [x for x in clipboard_options if x and x.lower().find(self.client_clipboard_type)>=0]
            if not filtered:
                log.warn("Warning: no clipboard types matching '%s'", self.client_clipboard_type)
                log.warn(" clipboard synchronization is disabled")
                return []
            log(" found %i clipboard types matching '%s'", len(filtered), self.client_clipboard_type)
            clipboard_options = filtered
        #now try to load them:
        log("get_clipboard_helper_classes() options=%s", clipboard_options)
        loadable = []
        for co in clipboard_options:
            if not co:
                continue
            try:
                parts = co.split(".")
                mod = ".".join(parts[:-1])
                module = __import__(mod, {}, {}, [parts[-1]])
                helperclass = getattr(module, parts[-1])
                loadable.append(helperclass)
            except ImportError:
                log("cannot load %s", co, exc_info=True)
                continue
        log("get_clipboard_helper_classes()=%s", loadable)
        return loadable

    def make_clipboard_helper(self):
        """
            Try the various clipboard classes until we find one
            that loads ok. (some platforms have more options than others)
        """
        clipboard_options = self.get_clipboard_helper_classes()
        log("make_clipboard_helper() options=%s", clipboard_options)
        for helperclass in clipboard_options:
            try:
                return self.setup_clipboard_helper(helperclass)
            except ImportError as e:
                log.error("Error: cannot instantiate %s:", helperclass)
                log.error(" %s", e)
                del e
            except Exception:
                log.error("Error: cannot instantiate %s", helperclass, exc_info=True)
        return None


    def _process_clipboard_packet(self, packet):
        ch = self.clipboard_helper
        log("process_clipboard_packet: %s, helper=%s", bytestostr(packet[0]), ch)
        if ch:
            ch.process_clipboard_packet(packet)

    def _process_clipboard_enabled_status(self, packet):
        clipboard_enabled, reason = packet[1:3]
        if self.clipboard_enabled!=clipboard_enabled:
            log.info("clipboard toggled to %s by the server, reason given:", ["off", "on"][int(clipboard_enabled)])
            log.info(" %s", bytestostr(reason))
            self.clipboard_enabled = bool(clipboard_enabled)
            self.emit("clipboard-toggled")

    def clipboard_toggled(self, *args):
        log("clipboard_toggled%s clipboard_enabled=%s, server_clipboard=%s",
            args, self.clipboard_enabled, self.server_clipboard)
        if self.server_clipboard:
            self.send_now("set-clipboard-enabled", self.clipboard_enabled)
            if self.clipboard_enabled:
                ch = self.clipboard_helper
                assert ch is not None
                self.send_clipboard_selections(ch.get_remote_selections())
                ch.send_all_tokens()

    def send_clipboard_selections(self, selections):
        log("send_clipboard_selections(%s)", selections)
        self.send_now("clipboard-enable-selections", selections)

    def setup_clipboard_helper(self, helperClass):
        log("setup_clipboard_helper(%s)", helperClass)
        #first add the platform specific one, (may be None):
        kwargs= {
                #all the local clipboards supported:
                 "clipboards.local"     : CLIPBOARDS,
                 #all the remote clipboards supported:
                 "clipboards.remote"    : self.server_clipboards,
                 "can-send"             : self.client_clipboard_direction in ("to-server", "both"),
                 "can-receive"          : self.client_clipboard_direction in ("to-client", "both"),
                 #the local clipboard we want to sync to (with the translated clipboard only):
                 "clipboard.local"      : self.local_clipboard,
                 #the remote clipboard we want to we sync to (with the translated clipboard only):
                 "clipboard.remote"     : self.remote_clipboard
                 }
        log("setup_clipboard_helper() kwargs=%s", kwargs)
        def clipboard_send(*parts):
            log("clipboard_send: %s", parts[0])
            if not self.clipboard_enabled:
                log("clipboard is disabled, not sending clipboard packet")
                return
            #replaces 'Compressible' items in a packet
            #with a subclass that calls self.compressed_wrapper
            #and which can therefore enable the brotli compressor:
            packet = list(parts)
            for i, v in enumerate(packet):
                if isinstance(v, compression.Compressible):
                    packet[i] = self.compressible_item(v)
            self.send_now(*packet)
        def clipboard_progress(local_requests, remote_requests):
            log("clipboard_progress(%s, %s)", local_requests, remote_requests)
            if local_requests is not None:
                self.local_clipboard_requests = local_requests
            if remote_requests is not None:
                self.remote_clipboard_requests = remote_requests
            n = self.local_clipboard_requests+self.remote_clipboard_requests
            self.clipboard_notify(n)
        hc = helperClass(clipboard_send, clipboard_progress, **kwargs)
        hc.set_preferred_targets(self.server_clipboard_preferred_targets)
        hc.set_greedy_client(self.server_clipboard_greedy)
        hc.set_want_targets_client(self.server_clipboard_want_targets)
        hc.enable_selections(self.server_clipboard_selections)
        return hc

    def compressible_item(self, compressible):
        """
            converts a 'Compressible' item into something that will
            call `self.compressed_wrapper` when compression is requested
            by the network encode thread.
        """
        client = self
        class ProtocolCompressible(compression.Compressible):
            __slots__ = ()
            def compress(self):
                return client.compressed_wrapper(self.datatype, self.data,
                                                 level=9, can_inline=False, brotli=True)
        return ProtocolCompressible(compressible.datatype, compressible.data)

    def clipboard_notify(self, n):
        log("clipboard_notify(%i)", n)
