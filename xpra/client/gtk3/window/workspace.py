# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import, WIN32, OSX, POSIX
from xpra.util.system import is_Wayland, is_X11
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.common import WORKSPACE_UNSET, WORKSPACE_ALL, WORKSPACE_NAMES, noop
from xpra.gtk.util import get_default_root_window
from xpra.log import Logger

GLib = gi_import("GLib")
Gdk = gi_import("Gdk")

log = Logger("window", "workspace")

CAN_SET_WORKSPACE = False
HAS_X11_BINDINGS = False

root_xid: int = 0

WIN32_WORKSPACE = WIN32 and envbool("XPRA_WIN32_WORKSPACE", False)


def wn(w) -> str:
    return WORKSPACE_NAMES.get(w, str(w))


def use_x11_bindings() -> bool:
    if not POSIX or OSX:
        return False
    if not is_X11() or is_Wayland():
        return False
    if envbool("XPRA_USE_X11_BINDINGS", False):
        return True
    try:
        from xpra.x11.bindings.xwayland_info import isxwayland
    except ImportError:
        log("no xwayland bindings", exc_info=True)
        return False
    return not isxwayland()


if use_x11_bindings():
    try:
        from xpra.x11.error import xlog
        from xpra.x11.prop import prop_get
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.send_wm import send_wm_workspace
    except ImportError as x11e:
        log("x11 bindings", exc_info=True)
        # gtk util should have already logged a detailed warning
        log("cannot import the X11 bindings:")
        log(" %s", x11e)
    except RuntimeError as e:
        log("x11", exc_info=True)
        log.error(f"Error loading X11 bindings: {e}")
    else:
        HAS_X11_BINDINGS = True
        root_xid = get_root_xid()

        def can_set_workspace() -> bool:
            SET_WORKSPACE = envbool("XPRA_SET_WORKSPACE", True)
            if not SET_WORKSPACE:
                return False
            try:
                # in theory this is not a proper check, meh - that will do
                supported = prop_get(root_xid, "_NET_SUPPORTED", ["atom"], ignore_errors=True) or ()
                return "_NET_WM_DESKTOP" in supported
            except Exception as we:
                log("x11 workspace bindings error", exc_info=True)
                log.error("Error: failed to setup workspace hooks:")
                log.estr(we)
                return False

        CAN_SET_WORKSPACE = can_set_workspace()
elif WIN32 and WIN32_WORKSPACE:
    from _ctypes import COMError
    try:
        from pyvda.pyvda import get_virtual_desktops
    except (OSError, ImportError, COMError, NotImplementedError) as e:
        log(f"no workspace support: {e}")
        WIN32_WORKSPACE = 0
    else:
        CAN_SET_WORKSPACE = len(get_virtual_desktops()) > 0

POLL_WORKSPACE = envbool("XPRA_POLL_WORKSPACE", WIN32_WORKSPACE)


class WorkspaceWindow(GtkStubWindow):

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self._can_set_workspace = CAN_SET_WORKSPACE
        self._window_workspace = WORKSPACE_UNSET
        self._desktop_workspace = WORKSPACE_UNSET
        self.workspace_timer = 0
        if self._can_set_workspace:
            self.init_workspace(metadata, client_props)

    def cleanup(self) -> None:  # pylint: disable=method-hidden
        self.cancel_workspace_timer()

    def get_info(self) -> dict[str, Any]:
        return {
            "workspace": wn(self._window_workspace),
            "desktop": wn(self._desktop_workspace),
        }

    def get_window_event_mask(self) -> Gdk.EventMask:
        return Gdk.EventMask.PROPERTY_CHANGE_MASK

    def init_workspace(self, metadata: typedict, client_props: typedict) -> None:
        workspace = typedict(client_props).intget("workspace", WORKSPACE_UNSET)
        log("init_window(..) workspace from client properties %s: %s", client_props, wn(workspace))
        if workspace >= 0:
            # client properties override application specified workspace value on init only:
            metadata["workspace"] = workspace
        self._window_workspace = WORKSPACE_UNSET  # will get set in set_metadata if present
        self._desktop_workspace = self.get_desktop_workspace()
        log("init_window(..) workspace=%s, current workspace=%s",
            wn(self._window_workspace), wn(self._desktop_workspace))

        def prop_changed(_widget, event) -> None:
            atom = str(event.atom)
            if atom == "_NET_WM_DESKTOP":
                if self._been_mapped and not self._override_redirect and self._can_set_workspace:
                    self.do_workspace_changed(str(event))
        self.connect("property-notify-event", prop_changed)

        if POLL_WORKSPACE:
            self.when_realized("workspace", self.init_workspace_timer)

    def init_workspace_timer(self) -> None:
        value = [-1]

        def poll_workspace() -> bool:
            ws = self.get_window_workspace()
            log(f"poll_workspace() {ws=}")
            if value[0] != ws:
                value[0] = ws
                self.workspace_changed()
            return True

        self.workspace_timer = GLib.timeout_add(1000, poll_workspace)

    def cancel_workspace_timer(self) -> None:
        wt = self.workspace_timer
        if wt:
            self.workspace_timer = 0
            GLib.source_remove(wt)

    def workspace_changed(self) -> None:
        # on X11 clients, this fires from the root window property watcher
        if self._can_set_workspace:
            self.do_workspace_changed("desktop workspace changed")

    def do_workspace_changed(self, info: str) -> None:
        # call this method whenever something workspace related may have changed
        window_workspace = self.get_window_workspace()
        desktop_workspace = self.get_desktop_workspace()
        log("do_workspace_changed(%s) for window %i (window, desktop): from %s to %s",
            info, self.wid,
            (wn(self._window_workspace), wn(self._desktop_workspace)),
            (wn(window_workspace), wn(desktop_workspace)))
        if self._window_workspace == window_workspace and self._desktop_workspace == desktop_workspace:
            # no change
            return
        suspend_resume = None
        if desktop_workspace < 0:
            # maybe the property has been cleared? maybe the window is being scrubbed?
            log("not sure if the window is shown or not: %s vs %s, resuming to be safe",
                wn(desktop_workspace), wn(window_workspace))
            suspend_resume = False
        elif window_workspace == WORKSPACE_UNSET:
            log("workspace unset: assume current")
            suspend_resume = False
        elif window_workspace == WORKSPACE_ALL:
            log("window is on all workspaces")
            suspend_resume = False
        elif desktop_workspace != window_workspace:
            log("window is on a different workspace, increasing its batch delay")
            log(" desktop: %s, window: %s", wn(desktop_workspace), wn(window_workspace))
            suspend_resume = True
        elif self._window_workspace != self._desktop_workspace:
            assert desktop_workspace == window_workspace
            log("window was on a different workspace, resetting its batch delay")
            log(" (was desktop: %s, window: %s, now both on %s)",
                wn(self._window_workspace), wn(self._desktop_workspace), wn(desktop_workspace))
            suspend_resume = False
        self._window_workspace = window_workspace
        self._desktop_workspace = desktop_workspace
        client_properties = {}
        if window_workspace is not None:
            client_properties["workspace"] = window_workspace
        # weak dependency on `send_control_refresh`:
        send_control_refresh = getattr(self, "send_control_refresh", noop)
        send_control_refresh(suspend_resume, client_properties)

    def get_workspace_count(self) -> int:
        if not self._can_set_workspace:
            return 0
        if WIN32:
            if not WIN32_WORKSPACE:
                return 0
            from pyvda.pyvda import get_virtual_desktops
            return len(get_virtual_desktops())
        root = get_default_root_window()
        return self.xget_u32_property(root, "_NET_NUMBER_OF_DESKTOPS")

    def set_workspace(self, workspace) -> None:
        log("set_workspace(%s)", workspace)
        if not self._can_set_workspace:
            return
        if not self._been_mapped:
            # will be dealt with in the map event handler
            # which will look at the window metadata again
            log("workspace=%s will be set when the window is mapped", wn(workspace))
            return
        if workspace is not None:
            workspace = workspace & 0xffffffff
        desktop = self.get_desktop_workspace()
        ndesktops = self.get_workspace_count()
        current = self.get_window_workspace()
        log("set_workspace(%s) realized=%s", wn(workspace), self.get_realized())
        log(" current workspace=%s, detected=%s, desktop workspace=%s, ndesktops=%s",
            wn(self._window_workspace), wn(current), wn(desktop), ndesktops)
        if not self._can_set_workspace or not ndesktops:
            return
        if workspace == desktop or workspace == WORKSPACE_ALL or desktop is None:
            # window is back in view
            self._client.control_refresh(self.wid, False, False)
        if (workspace < 0 or workspace >= ndesktops) and workspace not in (WORKSPACE_UNSET, WORKSPACE_ALL):
            # this should not happen, workspace is unsigned (CARDINAL)
            # and the server should have the same list of desktops that we have here
            log.warn("Warning: invalid workspace number: %s", wn(workspace))
            workspace = WORKSPACE_UNSET
        if workspace == WORKSPACE_UNSET:
            # we cannot unset via send_wm_workspace, so we have to choose one:
            workspace = self.get_desktop_workspace()
        if workspace in (None, WORKSPACE_UNSET):
            log.warn("workspace=%s (doing nothing)", wn(workspace))
            return
        # we will need the gdk window:
        if current == workspace:
            log("window workspace unchanged: %s", wn(workspace))
            return
        if WIN32:
            if not WIN32_WORKSPACE:
                return
            from xpra.platform.win32.gui import get_window_handle
            from pyvda.pyvda import AppView, VirtualDesktop
            hwnd = get_window_handle(self)
            if not hwnd:
                return
            vd = VirtualDesktop(number=workspace + 1)
            app_view = AppView(hwnd=hwnd)
            log(f"moving {app_view} to {vd}")
            app_view.move(vd)
            return
        if not HAS_X11_BINDINGS:
            return
        gdkwin = self.get_window()
        log("do_set_workspace: gdkwindow: %#x, mapped=%s, visible=%s",
            gdkwin.get_xid(), self.get_mapped(), gdkwin.is_visible())
        with xlog:
            send_wm_workspace(root_xid, gdkwin.get_xid(), workspace)

    def get_desktop_workspace(self) -> int:
        if WIN32:
            if not WIN32_WORKSPACE:
                return 0
            from pyvda.pyvda import VirtualDesktop
            return VirtualDesktop.current().number - 1

        window = self.get_window()
        if window:
            root = window.get_screen().get_root_window()
        else:
            # if we are called during init...
            # we don't have a window
            root = get_default_root_window()
        return self.do_get_workspace(root, "_NET_CURRENT_DESKTOP")

    def get_window_workspace(self) -> int:
        if WIN32:
            if not WIN32_WORKSPACE:
                return WORKSPACE_UNSET
            try:
                from xpra.platform.win32.gui import get_window_handle
                from pyvda.pyvda import AppView
            except ImportError as e:
                log(f"unable to query workspace: {e}")
                return 0
            hwnd = get_window_handle(self)
            if not hwnd:
                return WORKSPACE_UNSET
            try:
                return AppView(hwnd).desktop.number - 1
            except Exception:
                log("failed to query pyvda appview", exc_info=True)
                return 0
        return self.do_get_workspace(self.get_window(), "_NET_WM_DESKTOP", WORKSPACE_UNSET)

    def do_get_workspace(self, target, prop: str, default_value=0) -> int:
        if not self._can_set_workspace:
            log("do_get_workspace: not supported, returning %s", wn(default_value))
            return default_value  # OSX does not have workspaces
        if target is None:
            log("do_get_workspace: target is None, returning %s", wn(default_value))
            return default_value  # window is not realized yet
        value = self.xget_u32_property(target, prop, default_value)
        log("do_get_workspace %s=%s on window %i: %#x",
            prop, wn(value), self.wid, target.get_xid())
        return value & 0xffffffff

    def get_map_client_properties(self) -> dict[str, Any]:
        workspace = self.get_window_workspace()
        if self._been_mapped:
            if workspace is None:
                # not set, so assume it is on the current workspace:
                workspace = self.get_desktop_workspace()
        else:
            workspace = self._metadata.intget("workspace", WORKSPACE_UNSET)
            if workspace != WORKSPACE_UNSET:
                log("map event set workspace %s", wn(workspace))
                self.set_workspace(workspace)
        if self._window_workspace != workspace and workspace is not None:
            log("map event: been_mapped=%s, changed workspace from %s to %s",
                self._been_mapped, wn(self._window_workspace), wn(workspace))
            self._window_workspace = workspace
        if workspace is not None:
            return {"workspace": workspace}
        return {}

    def get_configure_client_properties(self) -> dict[str, Any]:
        if not self._been_mapped:
            return {}
        # if the window has been mapped already, the workspace should be set:
        workspace = self.get_window_workspace()
        if self._window_workspace != workspace and workspace is not None:
            log("send_configure_event: changed workspace from %s to %s",
                wn(self._window_workspace), wn(workspace))
            self._window_workspace = workspace
            return {"workspace": workspace}
        return {}
