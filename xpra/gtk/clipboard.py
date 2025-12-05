# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.util.gobject import n_arg_signal, one_arg_signal
from xpra.clipboard.common import ClipboardCallback
from xpra.clipboard.targets import TEXT_TARGETS
from xpra.clipboard.proxy import ClipboardProxyCore
from xpra.clipboard.timeout import ClipboardTimeoutHelper
from xpra.os_util import gi_import
from xpra.util.str_fn import Ellipsizer
from xpra.util.env import envint
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GObject = gi_import("GObject")

log = Logger("clipboard")

BLOCK_DELAY = envint("XPRA_CLIPBOARD_BLOCK_DELAY", 5)


class GTK_Clipboard(ClipboardTimeoutHelper):

    def __repr__(self):
        return "GTK_Clipboard"

    def make_proxy(self, selection):
        proxy = GTKClipboardProxy(selection)
        proxy.set_want_targets(self._want_targets)
        proxy.set_direction(self.can_send, self.can_receive)
        proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
        proxy.connect("send-clipboard-request", self._send_clipboard_request_handler)
        return proxy


class GTKClipboardProxy(ClipboardProxyCore, GObject.GObject):
    __gsignals__ = {
        "send-clipboard-token": one_arg_signal,
        "send-clipboard-request": n_arg_signal(2),
    }

    def __init__(self, selection="CLIPBOARD"):
        ClipboardProxyCore.__init__(self, selection)
        GObject.GObject.__init__(self)
        self._owner_change_embargo = 0.0
        self._want_targets = False
        display = Gdk.Display.get_default()
        if not display:
            log.warn(f"Warning: no display, cannot access the {selection} clipboard")
            return
        self.clipboard = Gtk.Clipboard.get(Gdk.Atom.intern(selection, False))
        self.clipboard.connect("owner-change", self.owner_change)

    def __repr__(self):
        return "GTKClipboardProxy(%s)" % self._selection

    def got_token(self, targets, target_data=None, claim=True, synchronous_client=False) -> None:
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, synchronous_client=%s, can-receive=%s",
            self._selection, targets, Ellipsizer(target_data), claim, synchronous_client, self._can_receive)
        if claim:
            self._have_token = True
        if not self._can_receive:
            return
        if target_data and claim:
            targets = target_data.keys()
            text_targets = tuple(x for x in targets if x in TEXT_TARGETS)
            for text_target in text_targets:
                dtype, dformat, data = target_data.get(text_target)
                if dformat != 8:
                    continue
                text = str(data)
                if isinstance(data, bytes):
                    if text_target.lower().find("utf8") >= 0:
                        try:
                            text = data.decode("utf8")
                        except UnicodeDecodeError:
                            pass
                    else:
                        try:
                            text = data.decode("latin1")
                        except UnicodeDecodeError:
                            pass
                log("setting text data %s / %s of size %i: %s", dtype, dformat, len(text), Ellipsizer(text))
                self._owner_change_embargo = monotonic()
                self.clipboard.set_text(text, len(text))
                return
            # we should handle more datatypes here..

    ############################################################################
    # forward local requests to the remote clipboard:
    ############################################################################
    def schedule_emit_token(self, min_delay=0) -> None:
        def send_token(*token_data):
            self._have_token = False
            self.emit("send-clipboard-token", token_data)

        if not (self._want_targets or self._greedy_client):
            send_token()
            return
        # we need the targets:
        targets = self.clipboard.wait_for_targets()
        if not targets:
            send_token()
            return
        if not self._greedy_client:
            send_token(targets)
            return
        # for now, we only handle text targets:
        text_targets = tuple(x for x in targets if x in TEXT_TARGETS)
        if text_targets:
            text = self.clipboard.wait_for_text()
            if text:
                # should verify the target is actually utf8...
                text_target = text_targets[0]
                send_token(targets, (text_target, "UTF8_STRING", 8, text))
                return
        send_token(text_targets)

    def owner_change(self, clipboard, event) -> None:
        log("owner_change(%s, %s) window=%s, selection=%s",
            clipboard, event, event.window, event.selection)
        self.do_owner_changed()

    def do_owner_changed(self) -> None:
        elapsed = monotonic() - self._owner_change_embargo
        log("do_owner_changed() enabled=%s, elapsed=%s",
            self._enabled, elapsed)
        if not self._enabled or elapsed < BLOCK_DELAY:
            return
        self.schedule_emit_token()

    def get_contents(self, target: str, got_contents: ClipboardCallback, time=0) -> None:
        log("get_contents(%s, %s, %i) have-token=%s",
            target, got_contents, time, self._have_token)

        def get_targets():
            r = self.clipboard.wait_for_targets()
            if r and len(r) == 2 and r[0]:
                return r[1]
            return []

        if target == "TARGETS":
            atoms = tuple(x.name() for x in get_targets())
            got_contents("ATOM", 32, atoms)
            return
        if target in TEXT_TARGETS:
            text = self.clipboard.wait_for_text()
            got_contents(target, 8, text or "")
            return
        atom = next((x for x in get_targets() if x.name() == target), None)
        if atom:
            sel = self.clipboard.wait_for_contents(atom)
            if sel:
                data = sel.get_data()
                if target in ("image/png", "image/jpeg"):
                    data = self.filter_data(dtype=target, dformat=8, data=data)
                got_contents(target, 8, data)
                return
        log.warn("Warning: can't find request target atom {target}")
        got_contents(target, 0, b"")


GObject.type_register(GTKClipboardProxy)
