# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence, Iterable
from typing import Any

from xpra.common import noop
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool, ignorewarnings
from xpra.os_util import gi_import, WIN32, POSIX
from xpra.util.system import is_Wayland
from xpra.net.common import Packet, FULL_INFO
from xpra.common import is_covered_by_opaque_region
from xpra.client.gui.window.backing import VIDEO_MAX_SIZE
from xpra.constants import DEFAULT_METADATA_SUPPORTED
from xpra.util.parsing import FALSE_OPTIONS
from xpra.gtk.util import get_default_root_window, init_display_source
from xpra.gtk.window import GDKWindow
from xpra.gtk.versions import get_gtk_version_info
from xpra.exit_codes import ExitValue
from xpra.util.gobject import no_arg_signal
from xpra.gtk.css_overrides import inject_css_overrides
from xpra.client.gui.ui_client_base import UIXpraClient
from xpra.client.base.gobject import GObjectClientAdapter
from xpra.client.gtk3.dialogs import GTKDialogClient
from xpra.client.gtk3.keyboard_helper import GTKKeyboardHelper
from xpra.client.gtk3.subsystem.display import Gtk3DisplayClient
from xpra.client.gtk3.frame_extents import setup_frame_request_window, get_window_frame_sizes
from xpra.platform.gui import system_bell
from xpra.net.packet_type import STARTUP_COMPLETE
from xpra.log import Logger

log = Logger("gtk", "client")
opengllog = Logger("gtk", "opengl")
cursorlog = Logger("gtk", "client", "cursor")
focuslog = Logger("client", "focus")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")

METADATA_SUPPORTED = os.environ.get("XPRA_METADATA_SUPPORTED", "")
OPENGL_MIN_SIZE = envint("XPRA_OPENGL_MIN_SIZE", 32)
NO_OPENGL_WINDOW_TYPES = os.environ.get(
    "XPRA_NO_OPENGL_WINDOW_TYPES",
    "DOCK,TOOLBAR,MENU,UTILITY,SPLASH,DROPDOWN_MENU,POPUP_MENU,TOOLTIP,NOTIFICATION,COMBO,DND"
).split(",")
WINDOW_GROUPING = os.environ.get("XPRA_WINDOW_GROUPING", "group-leader-xid,class-instance,pid,command").split(",")

VREFRESH = envint("XPRA_VREFRESH", 0)

inject_css_overrides()
init_display_source(False)
# must come after init_display_source()
from xpra.client.gtk3.window.base import HAS_X11_BINDINGS, make_window_cursor  # noqa: E402


def get_group_ref(metadata: dict) -> str:
    # ie: refs="group-leader-xid" or "pid+class-instance"
    for ref_str in WINDOW_GROUPING:
        refs = ref_str.split(".")
        # ie: ["pid", "class-instance"]
        if not all(ref in metadata for ref in refs):
            continue
        group_refs = []
        for ref in refs:
            value = metadata[ref]
            if isinstance(value, Iterable):
                group_refs.append(f"{ref}:{csv(value)}")
            group_refs.append(f"{ref}:{value}")
        # ie: "pid=10,class-instance=foo"
        return ",".join(group_refs)
    return ""


def _add_statusicon_tray(tray_classes: list[type]) -> list[type]:
    if not is_Wayland():
        try:
            from xpra.gtk.statusicon_tray import GTKStatusIconTray
            # unlikely to work with gnome:
            if envbool("XPRA_PREFER_STATUSICON", False):
                tray_classes.insert(0, GTKStatusIconTray)
            else:
                tray_classes.append(GTKStatusIconTray)
        except Exception as e:
            log.warn("Warning: failed to load StatusIcon tray")
            log.warn(" %s", e)
    return tray_classes


# noinspection PyMethodMayBeStatic
class GTKXpraClient(GObjectClientAdapter, UIXpraClient):
    __gsignals__ = {}
    # add signals from super classes (all no-arg signals)
    for signal_name in UIXpraClient.__signals__:
        __gsignals__[signal_name] = no_arg_signal

    ClientWindowClass: type | None = None

    @staticmethod
    def get_subsystem_classes() -> dict[str, type]:
        classes = dict(UIXpraClient.get_subsystem_classes())
        classes["display"] = Gtk3DisplayClient
        classes["dialogs"] = GTKDialogClient
        return classes

    def __init__(self):
        GObjectClientAdapter.__init__(self)
        UIXpraClient.__init__(self)
        self.client_type = "Python/GTK3"
        self.menu_helper = None
        # only used when the main menu cannot be popped up, see `get_popup_menu_helper`:
        self.popup_menu_helper = None
        # the keyboard subsystem holds `helper_class`; inject the GTK
        # implementation into it (it is created by UIXpraClient.__init__ above):
        if kb := self.get_subsystem("keyboard"):
            kb.helper_class = GTKKeyboardHelper
        # add our GTK-specific behaviour to the subsystem signals (the subsystems
        # own these signals; we just subscribe and react):
        if window := self.get_subsystem("window"):
            window.connect("new-window", self._new_window)
        if gl := self.get_subsystem("opengl"):
            gl.connect("toggled", self._opengl_toggled)
        # opengl state is owned by the `opengl` subsystem; cursor tracking state
        # (`_cursors`, `last_data`) by the `cursor` subsystem; the methods
        # below reach them via `get_subsystem(...)`.
        # group leader bits:
        self._ref_to_group_leader = {}
        self._group_leader_wids = {}
        self.video_max_size = VIDEO_MAX_SIZE

    def get_menu_helper(self):
        """
        menu helper used by our tray (make_tray / setup_xpra_tray)
        and for showing the menu on windows via a shortcut,
        """
        if not self.menu_helper:
            from xpra.platform.systray import get_menu_helper_class
            from xpra.client.gtk3.tray_menu import GTKTrayMenu
            from xpra.util.objects import make_instance
            mhc = (get_menu_helper_class(), GTKTrayMenu)
            log("get_menu_helper() tray menu helper classes: %s", mhc)
            self.menu_helper = make_instance(mhc, self)
        return self.menu_helper

    def get_popup_menu_helper(self):
        if mh := super().get_popup_menu_helper():
            return mh
        # ie: macOS, where the main menu is the menu bar
        if not self.popup_menu_helper:
            from xpra.client.gtk3.tray_menu import GTKTrayMenu
            from xpra.util.objects import make_instance
            self.popup_menu_helper = make_instance((GTKTrayMenu, ), self)
            log("get_popup_menu_helper()=%s", self.popup_menu_helper)
        return self.popup_menu_helper

    def run(self) -> ExitValue:
        log(f"run() HAS_X11_BINDINGS={HAS_X11_BINDINGS}")
        from xpra.client.base import features
        if features.display:
            Gdk.Screen.get_default().connect("size-changed", self.get_subsystem("display").screen_size_changed)
        if features.window:
            # call this once early:
            ignorewarnings(self.get_mouse_position)
            if HAS_X11_BINDINGS:
                setup_frame_request_window()
        UIXpraClient.run(self)
        return GObjectClientAdapter.run(self)

    def cleanup(self) -> None:
        log("GTKXpraClient.cleanup()")
        if dialogs := self.get_subsystem("dialogs"):
            dialogs.cleanup()
        for attr in ("menu_helper", "popup_menu_helper"):
            if mh := getattr(self, attr):
                setattr(self, attr, None)
                mh.cleanup()
        UIXpraClient.cleanup(self)

    def _process_startup_complete(self, packet: Packet) -> None:
        super()._process_startup_complete(packet)
        Gdk.notify_startup_complete()
        self.remove_packet_handlers(STARTUP_COMPLETE)

    # every other dialog delegation lives on `UIXpraClient`, which any backend
    # composing a `dialogs` subsystem inherits; only this one is Gtk-only,
    # because the `challenge` subsystem has a working non-GUI fallback:
    def do_process_challenge_prompt(self, *args, **kwargs):
        return self._call_dialogs("do_process_challenge_prompt", *args, **kwargs)

    def get_tray_classes(self) -> list[type]:
        return _add_statusicon_tray(super().get_tray_classes())

    def get_system_tray_classes(self) -> list[type]:
        window = self.get_subsystem("window")
        native = window.get_system_tray_classes() if window else []
        return _add_statusicon_tray(native)

    def supports_system_tray(self) -> bool:
        #  always True: we can always use Gtk.StatusIcon as fallback
        return True

    def get_root_window(self):
        return get_default_root_window()

    def get_raw_mouse_position(self) -> tuple[int, int]:
        root = self.get_root_window()
        if not root:
            return -1, -1
        return root.get_pointer()[-3:-1]

    def get_mouse_position(self) -> tuple[int, int]:
        p = self.get_raw_mouse_position()
        display = self.get_subsystem("display")
        return display.cp(p[0], p[1]) if display else (p[0], p[1])

    def get_current_modifiers(self) -> Sequence[str]:
        root = self.get_root_window()
        if root is None:
            return ()
        modifiers_mask = root.get_pointer()[-1]
        # `mask_to_names` is owned by the `keyboard` subsystem (which may be absent):
        keyboard = self.get_subsystem("keyboard")
        return keyboard.mask_to_names(modifiers_mask) if keyboard else ()

    def make_hello(self) -> dict[str, Any]:
        capabilities = UIXpraClient.make_hello(self)
        from xpra.client.base import features
        display = self.get_subsystem("display")
        if features.encoding:
            capabilities["encoding.transparency"] = display.has_transparency() if display else False
        if FULL_INFO > 1:
            capabilities.setdefault("versions", {}).update(get_gtk_version_info())
        if envbool("XPRA_EXPORT_ICON_DATA", FULL_INFO > 1):
            # tell the server which icons GTK can use
            # so it knows when it should supply one as fallback
            if it := Gtk.IconTheme.get_default():
                # this would add our bundled icon directory
                # to the search path, but I don't think we have
                # any extra icons that matter in there:
                # from xpra.platform.paths import get_icon_dir
                # d = get_icon_dir()
                # if d not in it.get_search_path():
                #    it.append_search_path(d)
                #    it.rescan_if_needed()
                log(f"default icon theme: {it}")
                log(f"icon search path: {it.get_search_path()}")
                log(f"contexts: {it.list_contexts()}")
                icons = []
                for context in it.list_contexts():
                    icons += it.list_icons(context)
                log(f"icons: {icons}")
                capabilities["theme.default.icons"] = tuple(set(icons))
        if features.window:
            if METADATA_SUPPORTED:
                ms = [x.strip() for x in METADATA_SUPPORTED.split(",")]
            else:
                # this is currently unused, and slightly redundant because of metadata.supported below:
                capabilities["window.states"] = [
                    "fullscreen", "maximized",
                    "sticky", "above", "below",
                    "shaded", "iconified",
                    "skip-taskbar", "skip-pager",
                ]
                ms = list(DEFAULT_METADATA_SUPPORTED)
                # 4.4:
                ms += ["parent", "relative-position", "override-redirect"]
            if POSIX:
                # this is only really supported on X11, but posix is easier to check for..
                # "strut" and maybe even "fullscreen-monitors" could also be supported on other platforms I guess
                ms += ["shaded", "bypass-compositor", "strut", "fullscreen-monitors", "locale"]
            if HAS_X11_BINDINGS:
                ms += ["x11-property", "focused"]
                if envbool("XPRA_XSHAPE", True):
                    ms += ["shape"]
            log("metadata.supported: %s", ms)
            capabilities["metadata.supported"] = ms
            capabilities.setdefault("window", {})["frame_sizes"] = get_window_frame_sizes()
        if features.encoding:
            capabilities.setdefault("encoding", {})["icons"] = {
                "greedy": True,  # we don't set a default window icon anymore
                "size": (64, 64),  # size we want
                "max_size": (128, 128),  # limit
            }
        return capabilities

    def set_windows_cursor(self, windows, cursor_data: Sequence) -> None:
        cursorlog(f"set_windows_cursor({windows}, args[{len(cursor_data)}])")
        cursor = make_window_cursor(cursor_data, self.get_subsystem("display"))
        # the `cursor` subsystem records the last cursor (in its set_windows_cursor);
        # here we only track which windows got a cursor, for reset_windows_cursors:
        cur = self.get_subsystem("cursor")
        for w in windows:
            # weak dependency on PointerWindow:
            set_cursor_data = getattr(w, "set_cursor_data", noop)
            set_cursor_data(cursor_data)
            # trays don't have a gdk window:
            set_gdk_cursor = getattr(w, "set_gdk_cursor", None)
            if set_gdk_cursor and set_gdk_cursor(cursor) and cur:
                cur._cursors[w] = cursor_data

    def window_bell(self, window, device: int, percent: int, pitch: int, duration: int, bell_class,
                    bell_id: int, bell_name: str) -> None:
        gdkwindow = None
        if window:
            gdkwindow = window.get_window()
        if gdkwindow is None:
            gdkwindow = self.get_root_window()
        xid = 0
        if hasattr(gdkwindow, "get_xid"):
            xid = gdkwindow.get_xid()
        log(f"window_bell(..) {gdkwindow=}, {xid=}")
        if not system_bell(xid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
            # fallback to simple beep:
            Gdk.beep()

    def get_gl_client_window_module(self, enable_opengl: str) -> tuple[dict, Any]:
        # the (toolkit-specific) OpenGL window backend for this client;
        # the `display` subsystem calls this from its `init_opengl` and stays
        # backend-agnostic. Other toolkits provide their own implementation.
        from xpra.opengl.window import get_gl_client_window_module
        return get_gl_client_window_module(enable_opengl)

    def get_client_window_classes(self, geom: tuple[int, int, int, int], metadata: typedict,
                                  override_redirect: bool) -> Sequence[type]:
        log("get_client_window_class%s", (geom, metadata, override_redirect))
        enc = self.get_subsystem("encoding")
        gl = self.get_subsystem("opengl")
        gl_window_class = gl.GLClientWindowClass if gl else None
        log(" ClientWindowClass=%s, GLClientWindowClass=%s, opengl_enabled=%s, encoding=%s",
            self.ClientWindowClass, gl_window_class, bool(gl and gl.enabled),
            enc.encoding if enc else None)
        window_classes: list[type] = []
        if gl_window_class:
            ww, wh = geom[2], geom[3]
            if self.can_use_opengl(ww, wh, metadata, override_redirect):
                window_classes.append(gl_window_class)
            else:
                opengllog(f"OpenGL not available for {ww}x{wh} {override_redirect=} window {metadata}")
        if self.ClientWindowClass:
            window_classes.append(self.ClientWindowClass)
        return tuple(window_classes)

    def can_use_opengl(self, w: int, h: int, metadata: typedict, override_redirect: bool) -> bool:
        # opengl state lives on the `opengl` subsystem; scaling (sx/sy) on `display`:
        gl = self.get_subsystem("opengl")
        display = self.get_subsystem("display")
        gl_window_class = gl.GLClientWindowClass if gl else None
        opengllog("can_use_opengl GLClientWindowClass=%s, opengl_enabled=%s, opengl_force=%s",
                  gl_window_class, gl and gl.enabled, gl and gl.force)
        if gl_window_class is None or not gl.enabled:
            return False
        if not gl.force:
            # verify texture limits:
            ms = min(display.sx(gl.texture_size_limit), *gl.max_viewport_dims)
            if w > ms or h > ms:
                return False
            # avoid opengl for small windows:
            if w <= OPENGL_MIN_SIZE or h <= OPENGL_MIN_SIZE:
                log("not using opengl for small window: %ix%i", w, h)
                return False
            # avoid opengl for tooltips:
            window_types = metadata.strtupleget("window-type")
            if any(x in NO_OPENGL_WINDOW_TYPES for x in window_types):
                log("not using opengl for %s window-type", csv(window_types))
                return False
            if metadata.intget("transient-for", 0) > 0:
                log("not using opengl for transient-for window")
                return False
            if "content-types" in metadata:
                content_types = metadata.strtupleget("content-types")
            else:
                content_types = ()
            if "text" in content_types:
                return False
        if WIN32:
            # these checks can't be forced ('opengl_force')
            # win32 opengl just doesn't do alpha or undecorated windows properly:
            if override_redirect:
                return False
            if metadata.boolget("has-alpha", False):
                # windows that declare themselves fully opaque via
                # _NET_WM_OPAQUE_REGION can safely use OpenGL despite has-alpha.
                # opaque-region is in server coordinates, w/h are client-scaled,
                # so scale opaque-region up rather than scaling w/h back down
                # to avoid rounding errors from the round-trip conversion
                opr = tuple(
                    (display.sx(ox), display.sy(oy), display.sx(ow), display.sy(oh))
                    for ox, oy, ow, oh in metadata.tupleget("opaque-region")
                )
                if not is_covered_by_opaque_region(opr, w, h):
                    return False
            if not metadata.boolget("decorations", True):
                return False
            hbl = (self.headerbar or "").lower().strip()
            if hbl not in FALSE_OPTIONS:
                # any risk that we may end up using headerbar,
                # means we can't enable opengl
                return False
        return True

    def _new_window(self, _emitter, window) -> None:
        # in desktop / monitor / shadow mode, place each new window fullscreen on its own monitor:
        remote_server_mode = self.get_subsystem("remote-info").server_mode
        screen_mode = any(remote_server_mode.find(x) >= 0 for x in ("desktop", "monitor", "shadow"))
        display = self.get_subsystem("display")
        if display and display.desktop_fullscreen and screen_mode:
            screen = Gdk.Screen.get_default()
            n = screen.get_n_monitors()
            monitor = (len(self.get_windows()) - 1) % n
            window.fullscreen_on_monitor(screen, monitor)
            log("fullscreen_on_monitor: %i", monitor)

    def _opengl_toggled(self, emitter) -> None:
        # the `opengl` subsystem toggled rendering on/off: replace all the windows with new ones:
        if window := self.get_subsystem("window"):
            window.reinit_windows()
            window.reinit_window_icons()

    def find_window(self, metadata: typedict, metadata_key: str = "transient-for"):
        fwid = metadata.intget(metadata_key, -1)
        log("find_window(%s, %s) wid=%#x", metadata, metadata_key, fwid)
        if fwid > 0 and (window := self.get_subsystem("window")):
            return window.get_window(fwid)
        return None

    def find_gdk_window(self, metadata: typedict, metadata_key="transient-for"):
        if client_window := self.find_window(metadata, metadata_key):
            if gdk_window := client_window.get_window():
                return gdk_window
        return None

    def get_group_leader(self, wid: int, metadata: typedict, _override_redirect: bool):
        def find_gdk_window(metadata_key="transient-for"):
            return self.find_gdk_window(metadata, metadata_key)

        win = find_gdk_window("group-leader-wid") or find_gdk_window("transient-for") or find_gdk_window("parent")
        log(f"get_group_leader(..)={win}")
        if win:
            return win

        ref_metadata = dict(metadata)
        ref_metadata["wid"] = wid
        refkey = get_group_ref(ref_metadata)
        log(f"get_group_leader: refkey={refkey}, metadata={metadata}, refs={self._ref_to_group_leader}")
        if group_leader_window := self._ref_to_group_leader.get(refkey):
            log("found existing group leader window %s using ref=%s", group_leader_window, refkey)
            wids = self._group_leader_wids.setdefault(group_leader_window, [])
            if wid not in wids:
                wids.append(wid)
            return group_leader_window
        # we need to create one:
        title = "%s group leader for window %s" % (self.session_name or "Xpra", wid)
        # group_leader_window = Gdk.Window(None, 1, 1, Gtk.WindowType.TOPLEVEL, 0, Gdk.INPUT_ONLY, title)
        # static new(parent, attributes, attributes_mask)
        group_leader_window = GDKWindow(wclass=Gdk.WindowWindowClass.INPUT_ONLY, title=title)
        self._ref_to_group_leader[refkey] = group_leader_window
        # avoid warning on win32...
        if not WIN32:
            # X11 spec says window should point to itself:
            group_leader_window.set_group(group_leader_window)
        log("new hidden group leader window %s for ref=%s", group_leader_window, refkey)
        self._group_leader_wids.setdefault(group_leader_window, []).append(wid)
        return group_leader_window

    def destroy_window(self, wid: int, window, reinit=False) -> None:
        # augment the window subsystem's own destroy with group-leader cleanup:
        if w := self.get_subsystem("window"):
            w.destroy_window(wid, window)
        group_leader = window.group_leader
        if group_leader is None or not self._group_leader_wids:
            return
        if reinit:
            # the window is about to be re-created with the same wid and group ref,
            # so keep the group leader (and our record of this wid) for it to re-use:
            log("keeping group leader %s for re-initialized window %#x", group_leader, wid)
            return
        wids = self._group_leader_wids.get(group_leader)
        if wids is None:
            # not recorded any window ids on this group leader
            # means it is another managed window, leave it alone
            return
        if wid in wids:
            wids.remove(wid)
        if wids:
            # still has another window pointing to it
            return
        # the last window has gone, we can remove the group leader,
        # find all the references to this group leader:
        del self._group_leader_wids[group_leader]
        refs = []
        for ref, gl in self._ref_to_group_leader.items():
            if gl == group_leader:
                refs.append(ref)
        for ref in refs:
            del self._ref_to_group_leader[ref]
        log("last window for refs %s is gone, destroying the group leader %s", refs, group_leader)
        group_leader.close()

    # the xpra clipboard tray notification (blink/reset) is owned by the
    # `clipboard` and `tray` subsystems.
