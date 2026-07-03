# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

from typing import Any, Final
from collections.abc import Callable, Sequence

from xpra.platform.gui import get_window_min_size, get_window_max_size
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE, PacketElement
from xpra.net.packet_type import WINDOW_UNMAP, WINDOW_REFRESH
from xpra.client.subsystem.window.grab import should_force_grab
from xpra.client.subsystem.window.signalwatcher import kill_signalwatcher
from xpra.exit_codes import ExitCode, ExitValue
from xpra.util.system import is_Wayland
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.os_util import WIN32, OSX, gi_import
from xpra.client.base.stub import StubClientSubsystem
from xpra.util.signal_emitter import SignalEmitter
from xpra.common import noop
from xpra.log import Logger

log = Logger("window")
geomlog = Logger("geometry")
metalog = Logger("metadata")
execlog = Logger("client", "exec")

OPENGL_REINIT_WINDOWS = envbool("XPRA_OPENGL_REINIT_WINDOWS", True)
SHOW_DELAY: int = envint("XPRA_SHOW_DELAY", -1)
OSX_FOCUS_WORKAROUND = envint("XPRA_OSX_FOCUS_WORKAROUND", 2000)
OSX_EVENT_LISTENER = envbool("XPRA_OSX_EVENT_LISTENER", True)

DEFAULT_SERVER_WINDOW_STATES: Final[Sequence[str]] = (
    "iconified", "fullscreen", "above", "below",
    "sticky", "maximized",
)


def parse_window_size(v, attribute="max-size") -> tuple[int, int] | None:
    if v:
        try:
            pv = tuple(int(x.strip()) for x in v.split("x", 1))
            if len(pv) == 2:
                return pv
        except ValueError:
            # the main script does some checking, but we could be called from a config file launch
            log.warn("Warning: invalid window %s specified: %s", attribute, v)
    return None


def log_windows_info(windows: tuple) -> None:
    log("log_windows_info(%s)", windows)
    msg = "running"
    trays = sum(1 for w in windows if w.is_tray())
    wins = sum(1 for w in windows if not w.is_tray())
    if wins:
        msg += f", {wins} windows"
    if trays:
        msg += f", {trays} tray"
    log.info(msg)


class WindowManagerClient(StubClientSubsystem):

    def __init__(self):
        # the `window` subsystem owns these signals (via `SignalEmitter`); peers
        # subscribe with `get_subsystem("window").connect(name, handler)`:
        #  - "new-window"   (window)      fired once a new window is registered
        #  - "bell-toggled" ()            fired when the bell forwarding is toggled (see bell.py)
        SignalEmitter.__init__(self)
        self._window_to_id: dict[Any, int] = {}
        self._id_to_window: dict[int, Any] = {}

        self.auto_refresh_delay: int = -1
        self.min_window_size: tuple[int, int] = (0, 0)
        self.max_window_size: tuple[int, int] = (0, 0)

        self.windows_enabled: bool = True
        self.pixel_depth: int = 0
        self.modal_windows: bool = True

        self.server_window_frame_extents: bool = False
        self.server_window_states: Sequence[str] = ()
        # win32 WM/session event listener:
        self._win32_events = None

    def init(self, opts) -> None:
        self.auto_refresh_delay = opts.auto_refresh_delay
        self.min_window_size = parse_window_size(opts.min_size) or get_window_min_size()
        self.max_window_size = parse_window_size(opts.max_size) or get_window_max_size()
        self.pixel_depth = int(opts.pixel_depth)
        if self.pixel_depth not in (0, 16, 24, 30) and self.pixel_depth < 32:
            log.warn("Warning: invalid pixel depth %i", self.pixel_depth)
            self.pixel_depth = 0
        self.windows_enabled = opts.windows
        self.modal_windows = self.windows_enabled and opts.modal_windows

    def init_ui(self, opts) -> None:
        # opengl setup is owned by the `opengl` subsystem:
        if gl := self.get_subsystem("opengl"):
            gl.init_opengl(opts.opengl)

    def load(self) -> None:
        if power := self.get_subsystem("power"):
            power.connect("suspend", self.suspend_windows)
            power.connect("resume", self.resume_windows)

    def run(self) -> ExitValue:
        if WIN32:
            from xpra.platform.win32.window_events import Win32ClientEventsWatcher
            self._win32_events = Win32ClientEventsWatcher(self)
            self._win32_events.setup()
        elif OSX:
            self._setup_osx_events()
        return ExitCode.OK

    def _setup_osx_events(self) -> None:
        if OSX_FOCUS_WORKAROUND:
            from xpra.platform.darwin.gui import enable_focus_workaround, disable_focus_workaround
            GLib = gi_import("GLib")

            def first_ui_received(*_args):
                enable_focus_workaround()
                GLib.timeout_add(OSX_FOCUS_WORKAROUND, disable_focus_workaround)

            self.client.connect("first-ui-received", first_ui_received)
        if OSX_EVENT_LISTENER:
            with log.trap_error("Error setting up OSX event listener"):
                from xpra.platform.darwin.events import get_app_delegate
                delegate = get_app_delegate()
                log(f"_setup_osx_events() {delegate=}, deiconify_windows={self.deiconify_windows}")
                delegate.add_handler("deiconify", self.deiconify_windows)

    def cleanup(self) -> None:
        log("WindowClient.cleanup()")
        if we := self._win32_events:
            self._win32_events = None
            we.cleanup()
        # the protocol has been closed, it is now safe to close all the windows:
        # (cleaner and needed when we run embedded in the client launcher)
        self.destroy_all_windows()
        log("WindowClient.cleanup() done")

    def set_modal_windows(self, modal_windows) -> None:
        self.modal_windows = modal_windows
        # re-set flag on all the windows:
        for w in self._id_to_window.values():
            modal = w._metadata.boolget("modal", False)
            w.set_modal(modal)

    def get_info(self) -> dict[str, Any]:
        info: dict[Any, Any] = {
            "count": len(self._window_to_id),
            "min-size": self.min_window_size,
            "max-size": self.max_window_size,
            "read-only": self.client.readonly,
        }
        for wid, window in tuple(self._id_to_window.items()):
            info[wid] = window.get_info()
        winfo: dict[str, Any] = {"windows": info}
        return winfo

    ######################################################################
    # hello:
    def get_caps(self) -> dict[str, Any]:
        # FIXME: the messy bits without proper namespace:
        caps = {
            # features:
            "windows": self.windows_enabled,
            "window": self.get_window_caps(),
            "auto_refresh_delay": int(self.auto_refresh_delay * 1000),
        }
        return caps

    def get_window_caps(self) -> dict[str, Any]:
        if not self.windows_enabled:
            return {}
        return {
            # implemented in the gtk client:
            "min-size": self.min_window_size,
            "max-size": self.max_window_size,
            "restack": True,
            "pre-map": True,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_window_frame_extents = c.boolget("window.frame-extents")
        if not c.boolget("windows", True):
            log.warn("Warning: window forwarding is not enabled on this server")
        self.server_window_states = c.strtupleget("window.states", DEFAULT_SERVER_WINDOW_STATES)
        # `server_is_desktop` is owned by the `display` subsystem (it parses the fuller set of caps)
        self.client.connect("startup-complete", self.log_windows_info)
        return True

    def log_windows_info(self, *_args) -> None:
        try:
            windows = tuple(self._id_to_window.values())
            log_windows_info(windows)
        except AttributeError:
            pass

    @staticmethod
    def cook_metadata(_new_window, metadata: dict) -> typedict:
        # subclasses can apply tweaks here:
        return typedict(metadata)

    def get_window(self, wid: int):
        return self._id_to_window.get(wid)

    ######################################################################
    # regular windows:
    def _process_new_common(self, packet: Packet, override_redirect: bool):
        self.client._ui_event()
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        metadata = self.client.cook_metadata(True, packet.get_dict(6))
        # newer versions use metadata only:
        override_redirect |= metadata.boolget("override-redirect", False)
        if override_redirect and self.modal_windows:
            # find any modal windows and remove the flag
            # so that the OR window can get the focus
            # (it will be re-enabled when the OR window disappears)
            for wid, window in self._id_to_window.items():
                if window.is_OR() or window.is_tray():
                    continue
                if window.get_modal():
                    metalog("temporarily removing modal flag from %s", wid)
                    window.set_modal(False)
        metalog("process_new_common: %s, metadata=%s, OR=%s", packet[1:7], metadata, override_redirect)
        if wid in self._id_to_window:
            raise ValueError("we already have a window %#x: %s" % (wid, self.get_window(wid)))
        if w < 1 or w >= 32768 or h < 1 or h >= 32768:
            log.error("Error: window %#x dimensions %ix%i are invalid", wid, w, h)
            w, h = 1, 1
        rel_pos = metadata.inttupleget("relative-position")
        parent = metadata.intget("parent")
        geomlog("relative-position=%s (parent=%s)", rel_pos, parent)
        if parent and rel_pos:
            if pwin := self._id_to_window.get(parent):
                # apply scaling to relative position:
                p_pos = pwin.sp(*rel_pos)
                x = pwin._pos[0] + p_pos[0]
                y = pwin._pos[1] + p_pos[1]
                geomlog("relative position(%s)=%s", rel_pos, (x, y))
        # scaled dimensions of window (scaling helpers are owned by the `display` subsystem):
        display = self.get_subsystem("display")
        wx = display.sx(x)
        wy = display.sy(y)
        ww = max(1, display.sx(w))
        wh = max(1, display.sy(h))
        # backing size, same as original (server-side):
        bw, bh = w, h
        if len(packet) >= 8:
            client_properties = typedict(packet.get_dict(7))
        else:
            client_properties = typedict()
        geom = (wx, wy, ww, wh)
        backing_size = (bw, bh)
        geomlog("process_new_common: wid=%#x, OR=%s, geometry(%s)=%s / %s",
                wid, override_redirect, packet[2:6], geom, backing_size)
        return self.make_new_window(wid, geom, backing_size, metadata, override_redirect, client_properties)

    def _find_pid_focused_window(self, pid: int, OR=False) -> int:
        for twid, twin in self._id_to_window.items():
            if twin.is_tray():
                continue
            if twin.is_OR() != OR:
                continue
            if twin._metadata.intget("pid", -1) == pid:
                if OR or twid == self._focused:
                    return twid
        return 0

    def patch_OR_popup_transient_for(self, metadata: typedict) -> None:
        pid = metadata.intget("pid", 0)
        twid = metadata.intget("transient-for", 0)
        if is_Wayland():
            # if this is a sub-popup (ie: a submenu),
            # then GTK-Wayland refuses to show it unless we set transient-for
            # to point to the parent popup.
            # Even if under X11, `WM_TRANSIENT_FOR` points to the parent / top-level window...
            twid = self._find_pid_focused_window(pid, True)
        # try to ensure popup windows have a transient-for:
        if not twid:
            twid = self._find_pid_focused_window(pid)
        if twid:
            metadata["transient-for"] = twid

    def make_new_window(self, wid: int,
                        geom: tuple[int, int, int, int],
                        backing_size: tuple[int, int],
                        metadata: typedict, override_redirect: bool, client_properties):
        # window creation / group-leader / metadata cooking are concrete-client concerns:
        client_window_classes = self.client.get_client_window_classes(geom, metadata, override_redirect)
        group_leader_window = self.client.get_group_leader(wid, metadata, override_redirect)
        # workaround for "popup" OR windows without a transient-for (like: google chrome popups):
        # prevents them from being pushed under other windows on OSX
        # find a "transient-for" value using the pid to find a suitable window
        # if possible, choosing the currently focused window (if there is one..)
        pid = metadata.intget("pid", 0)
        if watcher_pid := self.assign_signal_watcher_pid(wid, pid, metadata.strget("title")):
            metadata["watcher-pid"] = watcher_pid
        if override_redirect and metadata.strget("role").lower() == "popup" and pid:
            self.patch_OR_popup_transient_for(metadata)
        border = self.get_border()
        window = None
        log("make_new_window(..) client_window_classes=%s, group_leader_window=%s",
            client_window_classes, group_leader_window)
        for cwc in client_window_classes:
            try:
                # the window's owning client must be the real client (not this
                # subsystem instance): it reaches siblings via `client.get_subsystem`
                window = cwc(self.client, group_leader_window, wid,
                             geom, backing_size,
                             metadata, override_redirect, client_properties,
                             border, self.max_window_size, self.pixel_depth,
                             self.client.headerbar)
                break
            except (RuntimeError, ValueError):
                log.warn(f"Warning: failed to instantiate {cwc!r}", exc_info=True)
        if window is None:
            log.warn("no more options.. this window will not be shown, sorry")
            return None
        self.register_window(wid, window)
        if SHOW_DELAY >= 0:
            self.timeout_add(SHOW_DELAY, self.show_window, wid, window, metadata, override_redirect)
        else:
            self.show_window(wid, window, metadata, override_redirect)
        return window

    def register_window(self, wid: int, window) -> None:
        log("register_window(..) window(%#x)=%s", wid, window)
        self._id_to_window[wid] = window
        self._window_to_id[window] = wid
        # let clients add their own behaviour for the new window (ie: gtk3 places
        # it fullscreen on a monitor in desktop mode, win32 connects its signals):
        self.emit("new-window", window)

    def show_window(self, wid: int, window, metadata, override_redirect: bool) -> None:
        window.show_all()
        # apply the current cursor — without this, newly-shown windows
        # show an arrow indefinitely (server doesn't resend cursor data):
        # the last cursor data is tracked by the `cursor` subsystem (which may be
        # disabled); its set_windows_cursor renders via the toolkit client:
        if cur := self.get_subsystem("cursor"):
            if last_cursor := cur.last_data:
                cur.set_windows_cursor([window], last_cursor)
        if override_redirect and should_force_grab(metadata):
            log.warn("forcing grab for OR window %#x", wid)
            self.client.window_grab(wid, window)

    def freeze(self) -> None:
        log("freeze()")
        for window in self._id_to_window.values():
            window.freeze()

    def unfreeze(self) -> None:
        log("unfreeze()")
        for window in self._id_to_window.values():
            window.unfreeze()

    def deiconify_windows(self) -> None:
        log("deiconify_windows()")
        for window in self._id_to_window.values():
            deiconify = getattr(window, "deiconify", None)
            if deiconify:
                deiconify()

    def resize_windows(self, new_size_fn: Callable) -> None:
        for window in self._id_to_window.values():
            if window:
                ww, wh = window._size
                nw, nh = new_size_fn(ww, wh)
                # this will apply the new scaling value to the size constraints:
                window.reset_size_constraints()
                window.resize(nw, nh)
        self.send_refresh_all()

    def reinit_windows(self, new_size_fn=None) -> None:
        # now replace all the windows with new ones:
        for wid in tuple(self._id_to_window.keys()):
            if window := self.get_window(wid):
                self.reinit_window(wid, window, new_size_fn)
        self.send_refresh_all()

    def reinit_window(self, wid: int, window, new_size_fn=None) -> None:
        geomlog("reinit_window%s", (wid, window, new_size_fn))

        def fake_send(*args):
            log("fake_send%s", args)

        if window.is_tray():
            # trays are never GL enabled, so don't bother re-creating them
            # might cause problems anyway if we did
            # just send a configure event in case they are moved / scaled
            window.send_configure()
            return
        # ignore packets from old window:
        window.send = fake_send
        # copy attributes:
        x, y = window._pos
        ww, wh = window._size
        if new_size_fn:
            ww, wh = new_size_fn(ww, wh)
        try:
            bw, bh = window._backing.size
        except (AttributeError, ValueError, TypeError):
            bw, bh = ww, wh
        client_properties = window._client_properties
        resize_counter = window._resize_counter
        metadata = window._metadata
        override_redirect = window._override_redirect
        backing = window._backing
        current_icon = window._current_icon
        video_decoder, csc_decoder, decoder_lock = None, None, None
        try:
            if backing:
                video_decoder = backing._video_decoder
                csc_decoder = backing._csc_decoder
                decoder_lock = backing._decoder_lock
                if decoder_lock:
                    decoder_lock.acquire()
                    log("reinit_windows() will preserve video=%s and csc=%s for %s", video_decoder, csc_decoder, wid)
                    backing._video_decoder = None
                    backing._csc_decoder = None
                    backing._decoder_lock = None
                    backing.close()

            # now we can unmap it:
            self.client.destroy_window(wid, window)
            # explicitly tell the server we have unmapped it:
            # (so it will reset the video encoders, etc)
            if not window.is_OR():
                self.send(WINDOW_UNMAP, wid)
            self._id_to_window.pop(wid, None)
            self._window_to_id.pop(window, None)
            # create the new window,
            # which should honour the new state of the opengl_enabled flag if that's what we changed,
            # or the new dimensions, etc
            geom = x, y, ww, wh
            backing_size = bw, bh
            # try to preserve the location:
            metadata["set-initial-position"] = True
            metadata["requested-position"] = x, y
            window = self.make_new_window(wid, geom, backing_size, metadata, override_redirect, client_properties)
            window._resize_counter = resize_counter
            # if we had a backing already,
            # restore the attributes we had saved from it
            if backing:
                backing = window._backing
                backing._video_decoder = video_decoder
                backing._csc_decoder = csc_decoder
                backing._decoder_lock = decoder_lock
            if current_icon:
                window.update_icon(current_icon)
        finally:
            if decoder_lock:
                decoder_lock.release()

    @staticmethod
    def get_group_leader(_wid: int, _metadata, _override_redirect) -> Any:
        # subclasses that wish to implement the feature may override this method
        return None

    def get_client_window_classes(self, _geom, _metadata, _override_redirect) -> Sequence[type]:
        raise NotImplementedError()

    def _process_window_create(self, packet: Packet) -> None:
        return self._process_new_common(packet, False)

    def _process_new_override_redirect(self, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        return self._process_new_common(packet, True)

    def _process_window_initiate_moveresize(self, packet: Packet) -> None:
        geomlog("%s", packet)
        wid = packet.get_wid()
        if window := self.get_window(wid):
            x_root = packet.get_i16(2)
            y_root = packet.get_i16(3)
            direction = packet.get_i8(4)
            button = packet.get_u8(5)
            source_indication = packet.get_i8(6)
            display = self.get_subsystem("display")
            window.initiate_moveresize(display.sx(x_root), display.sy(y_root), direction, button, source_indication)

    def _process_window_metadata(self, packet: Packet) -> None:
        wid = packet.get_wid()
        metadata = packet.get_dict(2)
        metalog("metadata update for window %i: %s", wid, metadata)
        if window := self.get_window(wid):
            metadata = self.client.cook_metadata(False, metadata)
            window.update_metadata(metadata)

    def _process_window_move_resize(self, packet: Packet) -> None:
        wid = packet.get_wid()
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        w = packet.get_u16(4)
        h = packet.get_u16(5)
        display = self.get_subsystem("display")
        ax = display.sx(x)
        ay = display.sy(y)
        aw = max(1, display.sx(w))
        ah = max(1, display.sy(h))
        resize_counter = -1
        if len(packet) > 6:
            resize_counter = packet.get_u64(6)
        window = self.get_window(wid)
        geomlog("_process_window_move_resize%s moving / resizing window %s (id=%s) to %s",
                packet[1:], window, wid, (ax, ay, aw, ah))
        if window:
            window.move_resize(ax, ay, aw, ah, resize_counter)

    def _process_window_resized(self, packet: Packet) -> None:
        wid = packet.get_wid()
        w = packet.get_u32(2)
        h = packet.get_u32(3)
        display = self.get_subsystem("display")
        aw = max(1, display.sx(w))
        ah = max(1, display.sy(h))
        resize_counter = -1
        if len(packet) > 4:
            resize_counter = packet.get_u64(4)
        window = self.get_window(wid)
        geomlog("_process_window_resized%s resizing window %s (wid=%#x) to %s", packet[1:], window, wid, (aw, ah))
        if window:
            window.resize(aw, ah, resize_counter)

    def _process_window_raise(self, packet: Packet) -> None:
        wid = packet.get_wid()
        window = self.get_window(wid)
        log(f"going to raise window {wid:#x} - {window}")
        if window:
            if window.has_toplevel_focus():
                log("window already has top level focus")
                return
            window.present()

    def _process_window_restack(self, packet: Packet) -> None:
        wid = packet.get_wid()
        detail = packet.get_i8(2)
        other_wid = packet.get_wid(3)
        above = int(detail == 0)
        window = self.get_window(wid)
        other_window = self.get_window(other_wid)
        log("restack window %s - %s %s %s",
            wid, window, ["above", "below"][above], other_window)
        if window:
            window.restack(other_window, above)

    def _process_configure_override_redirect(self, packet: Packet) -> None:
        self._process_window_move_resize(packet)

    def _process_window_destroy(self, packet: Packet) -> None:
        wid = packet.get_wid()
        if window := self.get_window(wid):
            assert window is not None
            if window.is_OR() and self.modal_windows:
                self.may_reenable_modal_windows(window)
            del self._id_to_window[wid]
            del self._window_to_id[window]
            self.client.destroy_window(wid, window)
        # weak dependency on Tray mixin:
        set_tray_icon = getattr(self, "set_tray_icon", noop)
        set_tray_icon()

    def may_reenable_modal_windows(self, window) -> None:
        orwids = tuple(wid for wid, w in self._id_to_window.items() if w.is_OR() and w != window)
        if orwids:
            # there are other OR windows left, don't do anything
            return
        for wid, w in self._id_to_window.items():
            if w.is_OR() or w.is_tray():
                # trays and OR windows cannot be made modal
                continue
            if w._metadata.boolget("modal") and not w.get_modal():
                metalog("re-enabling modal flag on %#x", wid)
                window.set_modal(True)

    def destroy_window(self, wid: int, window) -> None:
        log("destroy_window(%s#x, %s)", wid, window)
        window.destroy()
        if self._window_with_grab == wid:
            log("destroying window %s which has grab, ungrabbing!", wid)
            self.client.window_ungrab()
            self._window_with_grab = None
        if self.pointer_grabbed == wid:
            self.pointer_grabbed = None
        # deal with signal watchers:
        execlog("looking for window %#x in %s", wid, self._signalwatcher_to_wids)
        for signalwatcher, wids in tuple(self._signalwatcher_to_wids.items()):
            if wid in wids:
                execlog("removing %i from %s for signalwatcher %s", wid, wids, signalwatcher)
                wids.remove(wid)
                if not wids:
                    execlog("last window, removing watcher %s", signalwatcher)
                    self._signalwatcher_to_wids.pop(signalwatcher, None)
                    kill_signalwatcher(signalwatcher)
                    # now remove any pids that use this watcher:
                    for pid, w in tuple(self._pid_to_signalwatcher.items()):
                        if w == signalwatcher:
                            del self._pid_to_signalwatcher[pid]

    def destroy_all_windows(self) -> None:
        for wid, window in self._id_to_window.items():
            try:
                log("destroy_all_windows() destroying %#x / %s", wid, window)
                self.client.destroy_window(wid, window)
            except (RuntimeError, ValueError):
                log(f"destroy_all_windows() failed to destroy {window}", exc_info=True)
        self._id_to_window = {}
        self._window_to_id = {}

    ######################################################################
    # window refresh:
    def suspend_windows(self, *args) -> None:
        log("suspend_windows%s", args)
        self.refresh_slowly()

    def resume_windows(self, *args) -> None:
        log("resume_windows%s", args)
        # this will reset the refresh rate too:
        self.send_refresh_all()
        gl = self.get_subsystem("opengl")
        if gl and gl.enabled and OPENGL_REINIT_WINDOWS:
            # with opengl, the buffers sometimes contain garbage after resuming,
            # this should create new backing buffers:
            self.reinit_windows()
        self.reinit_window_icons()

    def pause(self) -> None:
        self.refresh_slowly()

    def refresh_slowly(self) -> None:
        # tell the server to slow down refresh for all the windows:
        self.control_refresh(-1, True, False)

    def unpause(self) -> None:
        self.send_refresh_all()

    def control_refresh(self, wid: int, suspend_resume, refresh, quality=100,
                        options: dict | None=None, client_properties: dict | None=None) -> None:
        packet: Sequence[PacketElement] = [WINDOW_REFRESH, wid, 0, quality]
        options = options or {}
        client_properties = client_properties or {}
        options["refresh-now"] = bool(refresh)
        if suspend_resume is True:
            options["batch"] = {
                "reset": True,
                "delay": 1000,
                "locked": True,
                "always": True,
            }
        elif suspend_resume is False:
            options["batch"] = {"reset": True}
        else:
            pass  # batch unchanged
        log("sending buffer refresh: options=%s, client_properties=%s", options, client_properties)
        packet.append(options)
        packet.append(client_properties)
        self.send(*packet)

    def send_refresh(self, wid: int) -> None:
        packet = [
            WINDOW_REFRESH, wid, 0, 100,
            {
                # explicit refresh (should be assumed True anyway),
                # also force a reset of batch configs:
                "refresh-now": True,
                "batch": {"reset": True},
            },
            {},  # no client_properties
        ]
        self.send(*packet)

    def send_refresh_all(self) -> None:
        log("Automatic refresh for all windows ")
        self.send_refresh(-1)

    ######################################################################
    # screen scaling:
    @staticmethod
    def fsx(v):
        """ convert X coordinate from server to client """
        return v

    @staticmethod
    def fsy(v):
        """ convert Y coordinate from server to client """
        return v

    @staticmethod
    def sx(v) -> int:
        """ convert X coordinate from server to client """
        return round(v)

    @staticmethod
    def sy(v) -> int:
        """ convert Y coordinate from server to client """
        return round(v)

    def srect(self, x, y, w, h) -> tuple[int, int, int, int]:
        """ convert rectangle coordinates from server to client """
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)

    def sp(self, x, y) -> tuple[int, int]:
        """ convert X,Y coordinates from server to client """
        return self.sx(x), self.sy(y)

    @staticmethod
    def cx(v) -> int:
        """ convert X coordinate from client to server """
        return round(v)

    @staticmethod
    def cy(v) -> int:
        """ convert Y coordinate from client to server """
        return round(v)

    def crect(self, x, y, w, h) -> tuple[int, int, int, int]:
        """ convert rectangle coordinates from client to server """
        return self.cx(x), self.cy(y), self.cx(w), self.cy(h)

    def cp(self, x, y) -> tuple[int, int]:
        """ convert X,Y coordinates from client to server """
        return self.cx(x), self.cy(y)

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.add_packets("new-override-redirect", main_thread=True)
            self.add_legacy_alias("raise-window", "window-raise")
            self.add_legacy_alias("new-window", "window-create")
            self.add_legacy_alias("restack-window", "window-restack")
            self.add_legacy_alias("initiate-moveresize", "window-initiate-moveresize")
            self.add_legacy_alias("lost-window", "window-destroy")
            self.add_legacy_alias("configure-override-redirect", "window-move-resize")
        self.add_packets(
            "window-create",
            "window-raise",
            "window-restack",
            "window-initiate-moveresize",
            "window-move-resize",
            "window-resized",
            "window-metadata",
            "window-destroy",
            main_thread=True)
