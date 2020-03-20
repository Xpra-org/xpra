# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_glib
from xpra.clipboard.clipboard_core import ClipboardProtocolHelperCore
from xpra.util import repr_ellipsized, envint, engs
from xpra.log import Logger
from xpra.platform.features import CLIPBOARD_GREEDY

glib = import_glib()

log = Logger("clipboard")

CONVERT_TIMEOUT = envint("XPRA_CLIPBOARD_CONVERT_TIMEOUT", 500)
REMOTE_TIMEOUT = envint("XPRA_CLIPBOARD_REMOTE_TIMEOUT", 1500)
assert 0<CONVERT_TIMEOUT<5000
assert 0<REMOTE_TIMEOUT<5000


class ClipboardTimeoutHelper(ClipboardProtocolHelperCore):

    #a clipboard superclass that handles timeouts
    def __init__(self, send_packet_cb, progress_cb=None, **kwargs):
        ClipboardProtocolHelperCore.__init__(self, send_packet_cb, progress_cb, **kwargs)
        self._clipboard_outstanding_requests = {}

    def cleanup(self):
        #reply to outstanding requests with "no data":
        for request_id in tuple(self._clipboard_outstanding_requests.keys()):
            self._clipboard_got_contents(request_id)
        self._clipboard_outstanding_requests = {}
        ClipboardProtocolHelperCore.cleanup(self)

    def make_proxy(self, selection):
        raise NotImplementedError()

    def _get_proxy(self, selection):
        proxy = self._clipboard_proxies.get(selection)
        if not proxy:
            log.warn("Warning: no clipboard proxy for '%s'", selection)
            return None
        return proxy

    def set_want_targets_client(self, want_targets):
        ClipboardProtocolHelperCore.set_want_targets_client(self, want_targets)
        #pass it on to the ClipboardProxy instances:
        for proxy in self._clipboard_proxies.values():
            proxy.set_want_targets(want_targets)


    ############################################################################
    # network methods for communicating with the remote clipboard:
    ############################################################################
    def _send_clipboard_token_handler(self, proxy, packet_data=()):
        if log.is_debug_enabled():
            log("_send_clipboard_token_handler(%s, %s)", proxy, repr_ellipsized(str(packet_data)))
        remote = self.local_to_remote(proxy._selection)
        packet = ["clipboard-token", remote]
        if packet_data:
            #append 'TARGETS' unchanged:
            packet.append(packet_data[0])
            #if present, the next element is the target data,
            #which we have to convert to wire format:
            if len(packet_data)>=2:
                target, dtype, dformat, data = packet_data[1]
                wire_encoding, wire_data = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
                if wire_encoding:
                    wire_data = self._may_compress(dtype, dformat, wire_data)
                    if wire_data:
                        packet += [target, dtype, dformat, wire_encoding, wire_data]
                        claim = proxy._can_send
                        packet += [claim, CLIPBOARD_GREEDY]
        self.send(*packet)

    def _send_clipboard_request_handler(self, proxy, selection, target):
        log("send_clipboard_request_handler%s", (proxy, selection, target))
        request_id = self._clipboard_request_counter
        self._clipboard_request_counter += 1
        log("send_clipboard_request id=%s", request_id)
        timer = glib.timeout_add(REMOTE_TIMEOUT, self.timeout_request, request_id, selection, target)
        self._clipboard_outstanding_requests[request_id] = (timer, selection, target)
        self.progress()
        self.send("clipboard-request", request_id, self.local_to_remote(selection), target)

    def timeout_request(self, request_id, selection, target):
        try:
            selection, target = self._clipboard_outstanding_requests.pop(request_id)[1:]
        except KeyError:
            log.warn("Warning: clipboard request id %i not found", request_id)
            log.warn(" selection=%s, target=%s", selection, target)
            return
        finally:
            self.progress()
        log.warn("Warning: remote clipboard request timed out")
        log.warn(" request id %i, selection=%s, target=%s", request_id, selection, target)
        proxy = self._get_proxy(selection)
        if proxy:
            proxy.got_contents(target)

    def _clipboard_got_contents(self, request_id, dtype=None, dformat=None, data=None):
        try:
            timer, selection, target = self._clipboard_outstanding_requests.pop(request_id)
        except KeyError:
            log.warn("Warning: request id %i not found", request_id)
            log.warn(" timed out already?")
            return
        finally:
            self.progress()
        glib.source_remove(timer)
        proxy = self._get_proxy(selection)
        log("clipboard got contents%s: proxy=%s for selection=%s",
            (request_id, dtype, dformat, repr_ellipsized(str(data))), proxy, selection)
        if proxy:
            proxy.got_contents(target, dtype, dformat, data)

    def client_reset(self):
        ClipboardProtocolHelperCore.client_reset(self)
        #timeout all pending requests
        cor = self._clipboard_outstanding_requests
        if cor:
            log.info("cancelling %i clipboard request%s", len(cor), engs(cor))
            self._clipboard_outstanding_requests = {}
            for request_id in cor:
                self._clipboard_got_contents(request_id)
