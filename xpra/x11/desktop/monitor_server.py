# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.scripts.config import InitException
from xpra.net.common import PacketType
from xpra.x11.desktop.base import DesktopServerBase
from xpra.x11.desktop.monitor_model import MonitorDesktopModel
from xpra.server.mixins.window import WindowsMixin
from xpra.x11.vfb_util import parse_resolution
from xpra.x11.bindings.randr import RandRBindings
from xpra.gtk.error import xsync, xlog
from xpra.log import Logger

GObject = gi_import("GObject")
GLib = gi_import("GLib")

RandR = RandRBindings()

log = Logger("server")
metadatalog = Logger("x11", "metadata")
screenlog = Logger("screen")
iconlog = Logger("icon")

MIN_SIZE = 640, 350
MAX_SIZE = 8192, 8192


def get_screen_size() -> tuple[int, int]:
    with xsync:
        return RandR.get_screen_size()


class XpraMonitorServer(DesktopServerBase):
    """
        Virtualizes monitors
    """
    __gsignals__ = DesktopServerBase.__common_gsignals__

    def __init__(self):
        with xsync:
            if not RandR.is_dummy16():
                display = os.environ.get("DISPLAY", "")
                raise InitException(f"the vfb display {display!r} cannot virtualize monitors - dummy RandR 1.6 missing")
        super().__init__()
        self.session_type: str = "monitor"
        self.reconfigure_timer: int = 0
        self.reconfigure_locked: bool = False

    def init_randr(self) -> None:
        super().init_randr()
        from xpra.x11.vfb_util import set_initial_resolution
        screenlog(f"init_randr() randr={self.randr}, initial-resolutions={self.initial_resolutions}")
        if not RandR.has_randr() or not self.initial_resolutions:
            return
        res = self.initial_resolutions
        with xlog:
            set_initial_resolution(res, self.dpi or self.default_dpi)

    def get_server_mode(self) -> str:
        return "X11 monitor"

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        if "features" in source.wants:
            capabilities |= {
                "monitor": True,
                "multi-monitors": True,
                "monitors": self.get_monitor_config(),
                "monitors.min-size": MIN_SIZE,
                "monitors.max-size": MAX_SIZE,
            }
        return capabilities

    def configure_best_screen_size(self):
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        log(f"configure_best_screen_size() sources={sss}")
        if len(sss) != 1:
            screenlog.info(f"screen used by {len(sss)} clients:")
            return get_screen_size()
        ss = sss[0]
        if not getattr(ss, "desktop_fullscreen", False):
            return get_screen_size()
        # try to match this client's layout:
        log("will try to mirror")
        # prevent this monitor layout change
        # from triggering a call to via reconfigure_monitors via reconfigure:
        try:
            self.reconfigure_locked = True
            mdef = self.mirror_client_monitor_layout()
            if mdef:
                self.setting_changed("monitors", mdef)
        except Exception:
            log("Warning: failed to mirror client monitor layout", exc_info=True)
            self.reconfigure_locked = False

        def unlock():
            self.reconfigure_locked = False

        GLib.timeout_add(1000, unlock)
        return get_screen_size()

    def load_existing_windows(self) -> None:
        with xlog:
            monitors = RandR.get_monitor_properties()
            for i, monitor in monitors.items():
                self.add_monitor_model(i + 1, monitor)
        # does not fire: (because of GTK?)
        # RandR.select_crtc_output_changes()
        # screen = gdk.Screen.get_default()
        # screen.connect("monitors-changed", self.monitors_changed)

    def do_x11_configure_event(self, event) -> None:
        # the root window changed,
        # check to see if a monitor has been modified
        # do this via a timer to avoid running multiple times
        # as we get multiple events for the same change
        log("do_x11_configure_event(%s)", event)
        if not self.reconfigure_timer:
            self.reconfigure_timer = GLib.timeout_add(50, self.reconfigure)

    def reconfigure(self) -> None:
        try:
            self.do_reconfigure()
        finally:
            self.reconfigure_timer = 0

    def do_reconfigure(self) -> None:
        # verify that our models are up-to-date,
        # we look for the `crtcs` because that's what tools like `xrandr` can modify easily
        #  ie: `xrandr --output DUMMY1 --mode 1024x768`
        mdefs = {}
        with xlog:
            info = RandR.get_all_screen_properties()
            crtcs = info.get("crtcs")
            outputs = info.get("outputs")
            monitors = info.get("monitors")

            def find_monitor(output_id):
                for minfo in monitors.values():
                    if output_id in minfo.get("outputs", ()):
                        return minfo
                return None

            screenlog("do_reconfigure() crtcs=%s", crtcs)
            screenlog("do_reconfigure() outputs=%s", outputs)
            screenlog("do_reconfigure() monitors=%s", monitors)
            if not crtcs or not outputs:
                return
            for i, crtc_info in crtcs.items():
                # find the monitor for this crtc:
                if crtc_info.get("noutput", 0) != 1:
                    screenlog(f"no outputs on crtc {i}")
                    continue
                output_id = crtc_info.get("outputs")[0]
                output_info = outputs.get(output_id)
                if not output_info:
                    screenlog(f"output {output_id} not found")
                    continue
                if output_info.get("connection") != "Connected":
                    screenlog(f"output {output_id} is not connected")
                    continue
                monitor_info = find_monitor(output_id)
                if not monitor_info:
                    screenlog(f"no monitor found for output id {output_id}")
                    return
                # get the geometry from the crtc:
                mdef = {k: v for k, v in crtc_info.items() if k in ("x", "y", "width", "height")}
                # add the millimeter dimensions from the output:
                mdef.update((k, v) for k, v in output_info.items() if k in ("mm-width", "mm-height"))
                # and some monitor attributes:
                mdef.update((k, v) for k, v in output_info.items() if k in ("primary", "automatic", "name"))
                mdefs[i] = mdef
                screenlog(f"do_reconfigure() {i}: {mdef}")
            if self.sync_monitors_to_models(mdefs) and not self.reconfigure_locked:
                self.reconfigure_monitors()
        self.refresh_all_windows()

    def sync_monitors_to_models(self, monitors) -> int:
        # now update the monitor models with this data:
        screenlog("sync_monitors_to_models(%s)", monitors)
        mods = 0
        for i, monitor in monitors.items():
            wid = i + 1
            model = self._id_to_window.get(wid)
            if not model:
                # found a new monitor!
                screenlog("found a new monitor: %s", monitor)
                self.add_monitor_model(wid, monitor)
                continue
            mdef = model.get_definition()
            diff = [k for k in ("x", "y", "width", "height") if monitor.get(k) != mdef.get(k)]
            screenlog("model %i geometry modified %s from %s to %s",
                      wid, diff, [mdef.get(k) for k in diff], [monitor.get(k) for k in diff])
            if diff:
                # re-initialize with new geometry:
                log("was %s, now %s", mdef, monitor)
                model.init(monitor)
                model.emit("resized")
                mods += 1
            if mdef.get("name", "") != monitor.get("name", ""):
                model.name = monitor.get("name")
                screenlog(f"monitor {i} name has changed to {model.name!r}")
                # name is used to generate the window "title":
                model.notify("title")
        return mods

    def add_monitor_model(self, wid: int, monitor) -> MonitorDesktopModel:
        model = MonitorDesktopModel(monitor)
        model.setup()
        screenlog("adding monitor model %s", model)
        super().do_add_new_window_common(wid, model)
        model.managed_connect("client-contents-changed", self._contents_changed)
        model.managed_connect("resized", self.monitor_resized)
        model.managed_connect("motion", self._motion_signaled)
        return model

    def monitor_resized(self, model) -> None:
        delta_x, delta_y = model.resize_delta
        wid = self._window_to_id[model]
        w, h = model.get_dimensions()
        screenlog("monitor_resized(%s) size=%s, delta=%s, wid=%i",
                  model, (w, h), (delta_x, delta_y), wid)
        for ss in self.window_sources():
            ss.resize_window(wid, model, w, h)
        if self.reconfigure_timer:
            # we're in the process of adjusting things
            return
        # we adjust the position of monitors after this one,
        # assuming that they are defined left to right!
        # first the models:
        self._adjust_monitors(wid, delta_x, delta_y)
        self.reconfigure_monitors()

    def reconfigure_monitors(self) -> None:
        # now we can do the virtual crtcs, outputs and monitors
        defs = self.get_monitor_config()
        screenlog("reconfigure_monitors() definitions=%s", defs)
        self.apply_monitor_config(defs)
        # and tell the client:
        self.setting_changed("monitors", defs)

    def validate_monitors(self) -> None:
        for model in self._id_to_window.values():
            x, y, width, height = model.get_geometry()
            if x + width >= MAX_SIZE[0] or y + height >= MAX_SIZE[1]:
                new_x, new_y = 0, 0
                mdef = model.get_definition()
                mdef |= {
                    "x": new_x,
                    "y": new_y,
                }
                model.init(mdef)

    def _adjust_monitors(self, after_wid: int, delta_x: int, delta_y: int) -> None:
        models = {wid: model for wid, model in self._id_to_window.items() if wid > after_wid}
        screenlog("adjust_monitors(%i, %i, %i) models=%s", after_wid, delta_x, delta_y, models)
        if (delta_x == 0 and delta_y == 0) or not models:
            return
        for wid, model in models.items():
            self._adjust_monitor(model, delta_x, delta_y)

    def _adjust_monitor(self, model, delta_x: int, delta_y: int) -> None:
        screenlog("adjust_monitors(%s, %i, %i)", model, delta_x, delta_y)
        if delta_x == 0 and delta_y == 0:
            return
        x, y = model.get_geometry()[:2]
        new_x = max(0, x + delta_x)
        new_y = max(0, y + delta_y)
        if new_x != x or new_y != y:
            screenlog(f"adjusting monitor {model} from {x},{y} to {new_x},{new_y}")
            mdef = model.get_definition()
            mdef |= {
                "x": new_x,
                "y": new_y,
            }
            model.init(mdef)

    def get_monitor_config(self) -> dict[int, dict]:
        monitor_defs = {}
        for wid, model in self._id_to_window.items():
            monitor = model.get_definition()
            i = wid - 1
            monitor["index"] = i
            monitor_defs[i] = monitor
        return monitor_defs

    def apply_monitor_config(self, monitor_defs: dict) -> None:
        with xsync:
            RandR.set_crtc_config(monitor_defs)

    def remove_monitor(self, wid: int) -> None:
        model = self._id_to_window.get(wid)
        screenlog("removing monitor for wid %i : %s", wid, model)
        if not model:
            raise ValueError(f"monitor {wid} not found")
        if len(self._id_to_window) <= 1:
            raise RuntimeError("cannot remove the last monitor")
        delta_x = -model.get_definition().get("width", 0)
        delta_y = 0  # model.monitor.get("width", 0)
        model.unmanage()
        wid = self._remove_window(model)
        # adjust the position of the other monitors:
        self._adjust_monitors(wid, delta_x, delta_y)
        self.reconfigure_monitors()

    def add_monitor(self, width: int, height: int) -> None:
        count = len(self._id_to_window)
        if count >= 16:
            raise RuntimeError(f"already too many monitors: {count}")
        if not (isinstance(width, int) and isinstance(height, int)):
            raise ValueError(f"invalid dimension types: {width} ({type(width)}) and {height} ({type(height)})")
        if (width, height) < MIN_SIZE:
            raise ValueError(f"monitor size {width}x{height} is too small, minimum is {MIN_SIZE}")
        if (width, height) > MAX_SIZE:
            raise ValueError(f"monitor size {width}x{height} is too large, maximum is {MIN_SIZE}")

        # find the wid to use:
        # prefer just incrementing the wid, but we cannot go higher than 16

        def rightof(wid: int):
            mdef = self._id_to_window[wid].get_definition()
            x = mdef.get("x", 0) + mdef.get("width", 0)
            y = mdef.get("y", 0)  # +monitor.get("height", 0)
            return x, y

        wid = self._max_window_id
        x = y = 0
        if wid < 16:
            # since we're just appending,
            # just place to the right of the last monitor:
            last = max(self._id_to_window)
            x, y = rightof(last)
        else:
            # find a gap we can use in the window ids before 16:
            prev = None
            for wid in range(16):
                if wid not in self._id_to_window:
                    break
                prev = wid
            assert wid <= 16
            if prev:
                x, y = rightof(prev)
            self._adjust_monitors(wid - 1, width, 0)
        # ensure no monitors end up too far to the right or bottom:
        # (better have them overlap - though we could do something smarter here)
        self.validate_monitors()
        # now we can add our new monitor:
        xdpi = self.xdpi or self.dpi or 96
        ydpi = self.ydpi or self.dpi or 96
        wmm = round(width * 25.4 / xdpi)
        hmm = round(height * 25.4 / ydpi)
        index = wid - 1
        monitor = {
            "index": index,
            "name": f"VFB-{index}",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "mm-width": wmm,
            "mm-height": hmm,
        }
        with xsync:
            model = self.add_monitor_model(wid, monitor)
        self.reconfigure_monitors()
        # send it to the clients:
        for ss in self._server_sources.values():
            if not isinstance(ss, WindowsMixin):
                continue
            self.send_new_desktop_model(model, ss)

    def _process_configure_monitor(self, _proto, packet: PacketType) -> None:
        action = str(packet[1])
        if action == "remove":
            identifier = str(packet[2])
            value = packet[3]
            if identifier == "wid":
                wid = int(value)
            elif identifier == "index":
                # index is zero-based
                wid = int(value) + 1
            else:
                raise ValueError(f"unsupported monitor identifier {identifier!r}")
            self.remove_monitor(wid)
        elif action == "add":
            resolution = packet[2]
            if isinstance(resolution, str):
                resolution = parse_resolution(resolution, self.refresh_rate)
            if not isinstance(resolution, (tuple, list)):
                raise ValueError(f"invalid resolution: {resolution!r} ({type(resolution)}")
            if len(resolution) not in (2, 3) or not all(isinstance(res, int) for res in resolution):
                raise ValueError(f"invalid resolution type: {resolution!r}")
            width, height = resolution[:2]
            self.add_monitor(width, height)
        else:
            raise ValueError(f"unsupported 'configure-monitor' action {action!r}")
        self.refresh_all_windows()

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("configure-monitor", main_thread=True)


GObject.type_register(XpraMonitorServer)
