# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any

from xpra.util.gobject import n_arg_signal, one_arg_signal
from xpra.clipboard.common import ClipboardCallback, ClipboardData, env_timeout
from xpra.clipboard.targets import TEXT_TARGETS, is_utf8_target
from xpra.clipboard.proxy import ClipboardProxyCore, filter_data
from xpra.clipboard.timeout import ClipboardTimeoutHelper
from xpra.os_util import gi_import
from xpra.util.str_fn import Ellipsizer
from xpra.util.env import envint
from xpra.log import Logger
from xpra.util.system import is_Wayland

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")
GObject = gi_import("GObject")

log = Logger("clipboard")

BLOCK_DELAY = envint("XPRA_CLIPBOARD_BLOCK_DELAY", 5)
# how long the application which owns the selection is given to answer:
# the blocking `wait_for_*` calls this backend used to make relied on GTK's own
# backstop, which only gives up after 30 seconds - twelve times longer than the
# peer waits for us. A Wayland selection is read from a pipe rather than in a
# single round trip, so this is not as tight as the X11 backend's `CONVERT_TIMEOUT`:
REQUEST_TIMEOUT = env_timeout("GTK_REQUEST", 500)


def atom_names(atoms) -> tuple[str, ...]:
    """
    Normalize what the `request_targets` callback is handed.

    That is `None` when the request found no owner, and pygobject can unpack an
    array holding a single atom as the atom itself rather than as a sequence.
    """
    if atoms is None:
        return ()
    if hasattr(atoms, "name"):
        # a bare atom, not a sequence of them
        atoms = (atoms, )
    return tuple(atom.name() for atom in atoms)


def empty_reply(target: str) -> tuple[str, int, Any]:
    # `TARGETS` is answered with the list of atom names, so an empty list says
    # 'no targets'; every other target uses a zero format to say 'no data',
    # which is what `collect_contents` skips on
    if target == "TARGETS":
        return "ATOM", 32, ()
    return target, 0, b""


class GTK_Clipboard(ClipboardTimeoutHelper):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if is_Wayland():
            self.local_greedy = tuple(self.local_selections)

    def __repr__(self):
        return "GTK_Clipboard"

    def make_proxy(self, selection):
        proxy = GTKClipboardProxy(selection)
        proxy.set_want_targets(self.proxy_want_targets(selection))
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
        # bumped whenever the selection changes hands, so that the answers to the
        # requests made for the previous owner can be told apart and dropped:
        self._selection_generation = 0
        # the requests still waiting for an answer: request id -> timer
        self._local_requests: dict[int, int] = {}
        self._local_request_counter = 0
        self.clipboard = None
        display = Gdk.Display.get_default()
        if not display:
            log.warn(f"Warning: no display, cannot access the {selection} clipboard")
            return
        self.clipboard = Gtk.Clipboard.get(Gdk.Atom.intern(selection, False))
        self.clipboard.connect("owner-change", self.owner_change)

    def __repr__(self):
        return "GTKClipboardProxy(%s)" % self._selection

    def cleanup(self) -> None:
        self.cancel_local_requests()
        super().cleanup()

    def cancel_local_requests(self) -> None:
        requests = self._local_requests
        self._local_requests = {}
        for timer in requests.values():
            GLib.source_remove(timer)

    def is_stale(self, generation: int) -> bool:
        # `cleanup` disables the proxy, so this also covers the callbacks
        # which arrive after the proxy is gone:
        return not self._enabled or generation != self._selection_generation

    def answer_once(self, target: str, got_contents: ClipboardCallback) -> ClipboardCallback:
        """
        Arm the watchdog for a request and return the function which answers it.

        Whichever of the reply and the timeout comes first takes the request out,
        so the caller is always given exactly one answer: `collect_contents` chains
        on it, and a request which never answers would stall the whole token.

        The timer is armed before the request is made because GTK can answer
        `request_targets` from its own cache, and `request_contents` for a selection
        this process owns, without ever returning to the main loop.
        """
        request_id = self._local_request_counter
        self._local_request_counter += 1

        def answer(dtype: str = "", dformat: int = 0, data=b"") -> None:
            timer = self._local_requests.pop(request_id, 0)
            if not timer:
                # the watchdog got there first
                return
            GLib.source_remove(timer)
            got_contents(dtype, dformat, data)

        def timeout() -> None:
            if not self._local_requests.pop(request_id, 0):
                return
            log.warn("Warning: %s clipboard request for %r timed out", self._selection, target)
            got_contents(*empty_reply(target))

        self._local_requests[request_id] = GLib.timeout_add(REQUEST_TIMEOUT, timeout)
        return answer

    def got_token(self, targets, target_data=None, claim=True, synchronous_client=False) -> None:
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        # whatever we were fetching was for the owner this token replaces:
        self._selection_generation += 1
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, synchronous_client=%s, can-receive=%s",
            self._selection, targets, Ellipsizer(target_data), claim, synchronous_client, self._can_receive)
        if claim:
            self._have_token = True
        if not self._can_receive or not self.clipboard:
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
                    if is_utf8_target(text_target):
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
                self.clipboard.set_text(text, -1)
                return
            # we should handle more datatypes here..

    ############################################################################
    # forward local requests to the remote clipboard:
    ############################################################################
    def do_emit_token(self) -> bool:
        # the targets, and the contents for a greedy client, are collected here -
        # *after* the back-off delay - so that we advertise the latest clipboard state.
        # Collecting them finishes asynchronously: what is returned is the decision
        # to advertise, not the packet.
        generation = self._selection_generation

        def send_token(targets=(), target_data=None) -> None:
            self.emit("send-clipboard-token", {
                "targets": tuple(targets),
                "data": target_data or {},
            })

        if not (self._want_targets or self._greedy_client) or not self.clipboard:
            send_token()
            return True

        # we need the targets, and the target data for greedy clients:
        def got_targets(_clipboard, atoms, *_args) -> None:
            if self.is_stale(generation):
                return
            targets = atom_names(atoms)
            if not targets or not self._greedy_client:
                send_token(targets)
                return
            eager = self.get_eager_targets(targets)
            log("get_eager_targets(%s)=%s", targets, eager)
            if not eager:
                send_token(targets)
                return

            def got_target_data(target_data: ClipboardData) -> None:
                if self.is_stale(generation):
                    return
                send_token(targets, target_data)

            self.collect_contents(eager, got_target_data)

        self.clipboard.request_targets(got_targets, None)
        return True

    def owner_change(self, clipboard, event) -> None:
        log("owner_change(%s, %s) window=%s, selection=%s",
            clipboard, event, event.window, event.selection)
        self.do_owner_changed()

    def do_owner_changed(self) -> None:
        elapsed = monotonic() - self._owner_change_embargo
        log("do_owner_changed() enabled=%s, can-send=%s, elapsed=%s", self._enabled, self._can_send, elapsed)
        # the selection has changed hands, so anything we are still fetching
        # belongs to the owner it replaces:
        self._selection_generation += 1
        if not self._enabled or not self._can_send or elapsed < BLOCK_DELAY:
            return
        self._clipboard_origin = ""
        self.schedule_emit_token()

    def get_contents(self, target: str, got_contents: ClipboardCallback) -> None:
        log("get_contents(%s, %s) have-token=%s", target, got_contents, self._have_token)
        if not self.clipboard:
            got_contents(*empty_reply(target))
            return
        answer = self.answer_once(target, got_contents)

        if target == "TARGETS":
            def got_targets(_clipboard, atoms, *_args) -> None:
                answer("ATOM", 32, atom_names(atoms))

            self.clipboard.request_targets(got_targets, None)
            return

        def got_text(_clipboard, text, *_args) -> None:
            if not text:
                log("no text found for clipboard target %r", target)
                answer(*empty_reply(target))
                return
            answer(target, 8, text)

        def got_selection(_clipboard, selection_data, *_args) -> None:
            # an owner which did not answer, or does not have the target we asked for,
            # gives us a negative length - which reaches us as `None` or as no data at all.
            # An empty selection is not worth forwarding either, and `collect_contents`
            # skips both the same way:
            data = selection_data.get_data()
            if not data:
                if target in TEXT_TARGETS:
                    # ask for whatever text the owner does have instead:
                    self.clipboard.request_text(got_text, None)
                    return
                log("no data found for clipboard target %r", target)
                answer(*empty_reply(target))
                return
            atom = selection_data.get_data_type()
            dtype = (atom.name() if atom else "") or target
            dformat = selection_data.get_format() or 8
            answer(dtype, dformat, filter_data(dtype=dtype, dformat=dformat, data=data))

        # the owner answers with no data for a target it does not have,
        # so this does not need the targets looked up first:
        self.clipboard.request_contents(Gdk.Atom.intern(target, False), got_selection, None)


GObject.type_register(GTKClipboardProxy)
