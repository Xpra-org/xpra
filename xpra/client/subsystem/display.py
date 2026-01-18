# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any

from xpra.os_util import gi_import
from xpra.exit_codes import ExitCode
from xpra.platform.features import REINIT_WINDOWS
from xpra.platform.gui import (
    get_vrefresh,
    get_antialias_info, get_icc_info, get_display_icc_info, show_desktop,
    get_xdpi, get_ydpi, get_number_of_desktops, get_desktop_names, get_wm_name,
)
from xpra.scripts.main import check_display
from xpra.net.common import MAX_PACKET_SIZE, Packet
from xpra.common import (
    noop, adjust_monitor_refresh_rate, get_refresh_rate_for_value,
    FULL_INFO, SYNC_ICC, NotificationID, skipkeys, BACKWARDS_COMPATIBLE,
)
from xpra.util.parsing import (
    parse_scaling, scaleup_value, scaledown_value, fequ, r4cmp,
    MIN_SCALING, MAX_SCALING, SCALING_EMBARGO_TIME, FALSE_OPTIONS,
)
from xpra.util.objects import typedict
from xpra.util.screen import log_screen_sizes
from xpra.util.env import envint
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("screen")
workspacelog = Logger("client", "workspace")
scalinglog = Logger("scaling")

MONITOR_CHANGE_REINIT = envint("XPRA_MONITOR_CHANGE_REINIT")


class DisplayClient(StubClientMixin):
    """
    Utility mixin for clients that handle a desktop / display
    Adds client-side scaling handling
    """
    __signals__ = ["scaling-changed"]
    PREFIX = "display"

    def __init__(self):
        check_display()
        self.dpi = 0
        self.can_scale = False
        self.initial_scaling = 1, 1
        self.xscale, self.yscale = self.initial_scaling
        self.scale_change_embargo = float("inf")
        self.refresh_rate = ""
        self.desktop_fullscreen = False
        self.desktop_scaling = False
        self.screen_size_change_timer = 0
        self.opengl_enabled: bool = False
        self.opengl_props: dict[str, Any] = {}
        self.client_supports_opengl: bool = False

        self._last_screen_settings = ()
        self._current_screen_sizes = []

        self.server_desktop_size = None
        self.server_actual_desktop_size = None
        self.server_max_desktop_size = None
        self.server_display = None
        self.server_randr = False
        self.server_opengl = None
        self.server_multi_monitors = False
        self.server_monitors = {}
        self.log_screen_info = True

    def init(self, opts) -> None:
        self.desktop_fullscreen = opts.desktop_fullscreen
        self.desktop_scaling = opts.desktop_scaling
        self.refresh_rate = opts.refresh_rate
        self.dpi = int(opts.dpi)
        self.can_scale = opts.desktop_scaling not in FALSE_OPTIONS
        scalinglog("can_scale(%s)=%s", opts.desktop_scaling, self.can_scale)
        if self.can_scale:
            self.parse_scaling(opts.desktop_scaling)

    def parse_scaling(self, desktop_scaling: str) -> None:
        root_w, root_h = self.get_root_size()
        self.initial_scaling = parse_scaling(desktop_scaling, root_w, root_h, MIN_SCALING, MAX_SCALING)
        self.xscale, self.yscale = self.initial_scaling
        scalinglog("scaling(%s)=%s", self.initial_scaling, (self.xscale, self.yscale))

    def cleanup(self) -> None:
        ssct = self.screen_size_change_timer
        if ssct:
            self.screen_size_change_timer = 0
            GLib.source_remove(ssct)

    def get_screen_sizes(self, xscale=1, yscale=1) -> list[tuple[int, int]]:
        raise NotImplementedError()

    def get_root_size(self) -> tuple[int, int]:
        raise NotImplementedError()

    def get_info(self) -> dict[str, Any]:
        screen = self.get_screen_caps()
        screen["scaling"] = self.get_scaling_caps()
        screen["dpi"] = self.get_dpi_caps()
        return {
            "screen": screen,
        }

    ######################################################################
    # hello:
    def get_caps(self) -> dict[str, Any]:
        dc = self.get_display_caps()
        if not BACKWARDS_COMPATIBLE:
            return {DisplayClient.PREFIX: dc}
        dc["display"] = dict(dc)
        return dc

    def get_display_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "show-desktop": True,
            "refresh-rate": self.get_vrefresh(),
            "refresh-rate.raw": self.get_raw_vrefresh(),
        }
        if BACKWARDS_COMPATIBLE:
            caps["vrefresh"] = self.get_vrefresh()
        if FULL_INFO > 0:
            wm_name = get_wm_name()
            if wm_name:
                caps["wm_name"] = wm_name

            op = self.opengl_props
            if FULL_INFO < 2:
                op = skipkeys(op, "extensions", "GLU.extensions")
            caps["opengl"] = op

        self._last_screen_settings = self.get_screen_settings()
        root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h = self._last_screen_settings[:7]
        if u_root_w and u_root_h:
            caps["desktop_size"] = self.cp(u_root_w, u_root_h)
        if ndesktops:
            caps["desktops"] = ndesktops
            caps["desktop.names"] = tuple(desktop_names)

        ss = self.get_screen_sizes()
        self._current_screen_sizes = ss

        if self.log_screen_info:
            log.info(" desktop size is %sx%s:", u_root_w, u_root_h)
            log_screen_sizes(u_root_w, u_root_h, ss)
        if self.xscale != 1 or self.yscale != 1:
            caps["screen_sizes.unscaled"] = ss
            caps["desktop_size.unscaled"] = u_root_w, u_root_h
            if self.log_screen_info:
                root_w, root_h = self.cp(u_root_w, u_root_h)
                if fequ(self.xscale, self.yscale):
                    sinfo = "%i%%" % round(self.xscale * 100)
                else:
                    sinfo = "%i%% x %i%%" % (round(self.xscale * 100), round(self.yscale * 100))
                scaled_up = u_root_w > root_w or u_root_h > root_h
                log.info(" %sscaled to %s, virtual screen size: %ix%i",
                         "up" if scaled_up else "down", sinfo, root_w, root_h)
                log_screen_sizes(root_w, root_h, sss)
        else:
            sss = ss
        caps["screen_sizes"] = sss
        monitors = self.get_monitors_info()
        caps["monitors"] = adjust_monitor_refresh_rate(self.refresh_rate, monitors)
        caps.update(self.get_screen_caps())
        caps["dpi"] = self.get_dpi_caps()
        caps["screen-scaling"] = self.get_scaling_caps()
        if self.desktop_fullscreen:
            caps["desktop-fullscreen"] = True
        self.log_screen_info = False        # don't log it again
        return caps

    def get_dpi_caps(self) -> dict[str, Any]:
        # command line (or config file) override supplied:
        caps = {}
        dpi = 0
        if self.dpi > 0:
            # scale it:
            dpi = round((self.cx(self.dpi) + self.cy(self.dpi)) / 2.0)
        else:
            # not supplied, use platform detection code:
            # platforms may also provide per-axis dpi (later win32 versions do)
            xdpi = self.get_xdpi()
            ydpi = self.get_ydpi()
            log("xdpi=%i, ydpi=%i", xdpi, ydpi)
            if xdpi > 0 and ydpi > 0:
                xdpi = self.cx(xdpi)
                ydpi = self.cy(ydpi)
                dpi = round((xdpi + ydpi) / 2.0)
                caps = {
                    "x": xdpi,
                    "y": ydpi,
                }
        if dpi:
            caps[""] = dpi
        log("get_dpi_caps()=%s", caps)
        return caps

    def get_scaling_caps(self) -> dict[str, Any]:
        return {
            "": True,
            "enabled": self.xscale != 1 or self.yscale != 1,
            "values": (int(1000 * self.xscale), int(1000 * self.yscale)),
        }

    def get_vrefresh(self) -> int:
        raw = self.get_raw_vrefresh()
        rate = get_refresh_rate_for_value(self.refresh_rate, raw)
        log("get_vrefresh()=%s (from %s and %s)", rate, self.refresh_rate, raw)
        return rate

    def get_raw_vrefresh(self) -> int:
        return get_vrefresh()

    def get_screen_caps(self) -> dict[str, Any]:
        caps: dict[str, int | dict] = {
            "vrefresh": self.get_vrefresh(),
        }
        aa = get_antialias_info()
        if aa:
            caps["antialias"] = aa
        return caps

    def parse_server_capabilities(self, caps: typedict) -> bool:
        d = caps.get("display")
        if isinstance(d, dict):
            c = typedict(d)
            self.server_display = c.strget("name")
        elif BACKWARDS_COMPATIBLE:
            c = caps
            self.server_display = c.strget("display")
        else:
            raise ValueError("missing display capabilities")
        self.server_desktop_size = c.intpair("desktop_size")
        log("server desktop size=%s", self.server_desktop_size)
        self.server_max_desktop_size = c.intpair("max_desktop_size", (2 ** 15, 2 ** 15))
        self.server_actual_desktop_size = c.intpair("actual_desktop_size")
        log("server actual desktop size=%s", self.server_actual_desktop_size)
        self.server_randr = c.boolget("resize_screen")
        log("server has randr: %s", self.server_randr)
        self.server_opengl = c.dictget("opengl")
        Logger("screen", "opengl")("server opengl=%s", self.server_opengl)
        self.server_multi_monitors = c.boolget("multi-monitors", False)
        self.server_monitors = c.dictget("monitors")
        log("server multi-monitors=%s, monitors=%s", self.server_multi_monitors, self.server_monitors)
        self.print_desktop_size(c)
        return True

    def print_desktop_size(self, c: typedict) -> None:
        if c.boolget("desktop") or c.boolget("shadow"):
            v = c.intpair("actual_desktop_size")
            if v:
                w, h = v
                ss = c.tupleget("screen_sizes")
                log.info(f" remote desktop size is {w}x{h}")
                if ss:
                    log_screen_sizes(w, h, ss)

    def process_ui_capabilities(self, c: typedict) -> None:
        self.server_is_desktop = c.boolget("shadow") or c.boolget("desktop") or c.boolget("monitor")
        log("process_ui_capabilities(%s) desktop=%s, monitor=%s", c, c.boolget("desktop"), c.boolget("monitor"))
        if not c.boolget("monitor"):
            skip_vfb_size_check = False  # if we decide not to use scaling, skip warnings
            if not fequ(self.xscale, 1.0) or not fequ(self.yscale, 1.0):
                # scaling is used, make sure that we need it and that the server can support it
                # (without rounding support, size-hints can cause resize loops)
                if self.server_is_desktop and not self.desktop_fullscreen:
                    # don't honour auto mode in this case
                    if self.desktop_scaling == "auto":
                        log.info(" not scaling a %s server", c.strget("type", "shadow"))
                        skip_vfb_size_check = self.xscale > 1 or self.yscale > 1
                        self.scale_change_embargo = 0
                        self.scalingoff()
            if self.can_scale:
                self.may_adjust_scaling()
            if not self.server_is_desktop and not skip_vfb_size_check and self.server_max_desktop_size:
                avail_w, avail_h = self.server_max_desktop_size
                root_w, root_h = self.get_root_size()
                log("validating server_max_desktop_size=%s vs root size=%s",
                    self.server_max_desktop_size, (root_w, root_h))
                if self.cx(root_w) != root_w or self.cy(root_h) != root_h:
                    log(" root size scaled to %s", (self.cx(root_w), self.cy(root_h)))
                if self.cx(root_w) > (avail_w + 1) or self.cy(root_h) > (avail_h + 1):
                    log.warn("Server's virtual screen is too small")
                    log.warn(" server: %sx%s vs client: %sx%s", avail_w, avail_h, self.cx(root_w), self.cy(root_h))
                    log.warn(" you may see strange behavior,")
                    log.warn(" please see https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Xdummy.md")
        # now that we have the server's screen info, allow scale changes:
        self.scale_change_embargo = 0
        self.set_max_packet_size()
        self.send_icc_data()

    def send_icc_data(self) -> None:
        if SYNC_ICC and "configure-display" in self.server_packet_types:
            # it is now safe to send the colourspace data if we have any:
            icc = self.get_icc_info()
            dicc = self.get_display_icc_info()
            if icc or dicc:
                self.send("configure-display", {
                    "icc": {
                        "global": icc,
                        "display": dicc,
                    },
                })

    # noinspection PyUnreachableCode
    def set_max_packet_size(self) -> None:
        p = self._protocol
        if not p or p.TYPE != "xpra":
            return
        root_w, root_h = self.cp(*self.get_root_size())
        maxw, maxh = root_w, root_h
        try:
            server_w, server_h = self.server_actual_desktop_size
            maxw = max(root_w, server_w)
            maxh = max(root_h, server_h)
        except (TypeError, ValueError):
            pass
        if maxw <= 0 or maxh <= 0 or maxw >= 32768 or maxh >= 32768:
            message = "invalid maximum desktop size: %ix%i" % (maxw, maxh)
            log(message)
            self.quit(ExitCode.INTERNAL_ERROR)
            return
        if maxw >= 16384 or maxh >= 16384:
            log.warn("Warning: the desktop size is extremely large: %ix%i", maxw, maxh)
        # max packet size to accommodate
        # a full screen RGBX (32 bits) uncompressed image
        # also with enough headroom for some metadata (4k)
        # we can't assume to have a real ClientConnection object:
        p.max_packet_size = max(MAX_PACKET_SIZE, maxw * maxh * 4 + 4 * 1024)
        p.abs_max_packet_size = maxw * maxh * 4 * 4 + 4 * 1024
        log("maximum packet size set to %i", p.max_packet_size)

    def has_transparency(self) -> bool:
        return False

    def get_icc_info(self) -> dict[str, Any]:
        return get_icc_info()

    def get_display_icc_info(self) -> dict[str, Any]:
        return get_display_icc_info()

    def get_monitors_info(self) -> dict:
        return {}

    def _process_show_desktop(self, packet: Packet) -> None:
        show = packet.get_bool(1)
        log("calling %s(%s)", show_desktop, show)
        show_desktop(show)

    def _process_desktop_size(self, packet: Packet) -> None:
        root_w = packet.get_u16(1)
        root_h = packet.get_u16(2)
        max_w = packet.get_u16(3)
        max_h = packet.get_u16(4)
        log("server has resized the desktop to: %sx%s (max %sx%s)", root_w, root_h, max_w, max_h)
        self.server_max_desktop_size = max_w, max_h
        self.server_actual_desktop_size = root_w, root_h
        if self.can_scale:
            self.may_adjust_scaling()

    def may_adjust_scaling(self) -> None:
        log("may_adjust_scaling() server_is_desktop=%s, desktop_fullscreen=%s",
            self.server_is_desktop, self.desktop_fullscreen)
        if self.server_is_desktop and not self.desktop_fullscreen:
            # don't try to make it fit
            return
        assert self.can_scale
        max_w, max_h = self.server_max_desktop_size  # ie: server limited to 8192x4096?
        w, h = self.get_root_size()  # ie: 5760, 2160
        sw, sh = self.cp(w, h)  # ie: upscaled to: 11520x4320
        scalinglog("may_adjust_scaling() server max desktop size=%s, server actual desktop size=%s",
                   self.server_max_desktop_size, self.server_actual_desktop_size)
        scalinglog("may_adjust_scaling() client root size=%s", self.get_root_size())
        scalinglog(" scaled client root size using %sx%s: %s", self.xscale, self.yscale, (sw, sh))

        # server size is too small for the client screen size with the current scaling value,
        # calculate the minimum scaling to fit it:

        def clamp(v) -> int | float:
            return max(MIN_SCALING, min(MAX_SCALING, v))

        if self.desktop_fullscreen:
            sw, sh = self.server_actual_desktop_size
            x = clamp(w / sw)
            y = clamp(h / sh)
        else:
            if sw < (max_w + 1) and sh < (max_h + 1):
                # no change needed
                return
            x = clamp(w / max_w)
            y = clamp(h / max_h)
            # avoid wonky scaling:
            if not 0.75 < x / y < 1.25:
                x = y = min(x, y)

        def mint(v) -> int | float:
            # prefer `int` to `float`,
            # and even tolerate a 0.1% difference to get it:
            if round(v) * 1000 == round(v * 1000):
                return int(v)
            return v

        self.xscale = mint(x)
        self.yscale = mint(y)
        scalinglog(" xscale=%s, yscale=%s", self.xscale, self.yscale)
        # to use the same scale for both axes:
        # self.xscale = mint(max(x, y))
        # self.yscale = self.xscale
        summary = "Desktop scaling adjusted to accommodate the server"
        xstr = ("%.3f" % self.xscale).rstrip("0")
        ystr = ("%.3f" % self.yscale).rstrip("0")
        messages = [
            "server desktop size is %ix%i" % (max_w, max_h),
            "using scaling factor %s x %s" % (xstr, ystr),
        ]
        self.may_notify(NotificationID.SCALING, summary, "\n".join(messages), icon_name="scaling")
        scalinglog.warn("Warning: %s", summary)
        for m in messages:
            scalinglog.warn(" %s", m)
        self.emit("scaling-changed")

    ######################################################################
    # screen scaling:
    def fsx(self, v) -> float:
        """ convert X coordinate from server to client """
        return v * self.xscale

    def fsy(self, v) -> float:
        """ convert Y coordinate from server to client """
        return v * self.yscale

    def sx(self, v) -> int:
        """ convert X coordinate from server to client """
        return round(self.fsx(v))

    def sy(self, v) -> int:
        """ convert Y coordinate from server to client """
        return round(self.fsy(v))

    def srect(self, x, y, w, h) -> tuple[int, int, int, int]:
        """ convert rectangle coordinates from server to client """
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)

    def sp(self, x, y) -> tuple[int, int]:
        """ convert X,Y coordinates from server to client """
        return self.sx(x), self.sy(y)

    def cx(self, v) -> int:
        """ convert X coordinate from client to server """
        return round(v / self.xscale)

    def cy(self, v) -> int:
        """ convert Y coordinate from client to server """
        return round(v / self.yscale)

    def crect(self, x, y, w, h) -> tuple[int, int, int, int]:
        """ convert rectangle coordinates from client to server """
        return self.cx(x), self.cy(y), self.cx(w), self.cy(h)

    def cp(self, x, y) -> tuple[int, int]:
        """ convert X,Y coordinates from client to server """
        return self.cx(x), self.cy(y)

    ######################################################################
    # OpenGL:
    def init_opengl(self, _enable_opengl) -> None:
        self.opengl_enabled = False
        self.client_supports_opengl = False
        self.opengl_props = {"info": "not supported"}

    ######################################################################
    # desktop, screen and scaling:
    def desktops_changed(self, *args) -> None:
        workspacelog("desktops_changed%s", args)
        self.screen_size_changed(*args)

    def workspace_changed(self, *args) -> None:
        workspacelog("workspace_changed%s", args)
        for win in self._id_to_window.values():
            ws_changed = getattr(win, "workspace_changed", noop)
            ws_changed()

    def screen_size_changed(self, *args) -> None:
        log("screen_size_changed(%s) timer=%s", args, self.screen_size_change_timer)
        if self.screen_size_change_timer:
            return
        # update via timer so the data is more likely to be final (up to date) when we query it,
        # some properties (like _NET_WORKAREA for X11 clients via posix gui "PlatformClient") may
        # trigger multiple calls to screen_size_changed, delayed by some amount
        # (sometimes up to 1s..)
        delay = 1000
        # if we are suspending, wait longer:
        # (better chance that the suspend-resume cycle will have completed)
        if self._suspended_at > 0 and self._suspended_at - monotonic() < 5 * 1000:
            delay = 5 * 1000
        self.screen_size_change_timer = GLib.timeout_add(delay, self.do_process_screen_size_change)

    def do_process_screen_size_change(self) -> None:
        self.screen_size_change_timer = 0
        self.update_screen_size()
        log("do_process_screen_size_change() MONITOR_CHANGE_REINIT=%s, REINIT_WINDOWS=%s",
            MONITOR_CHANGE_REINIT, REINIT_WINDOWS)
        if (MONITOR_CHANGE_REINIT and REINIT_WINDOWS) or MONITOR_CHANGE_REINIT > 1:
            log.info("screen size change: will reinit the windows")
            self.reinit_windows()
            self.reinit_window_icons()

    def get_screen_settings(self) -> tuple:
        u_root_w, u_root_h = self.get_root_size()
        root_w, root_h = self.cp(u_root_w, u_root_h)
        self._current_screen_sizes = self.get_screen_sizes()
        sss = self.get_screen_sizes(self.xscale, self.yscale)
        ndesktops = get_number_of_desktops()
        desktop_names = get_desktop_names()
        log("get_screen_settings() sizes=%s, %s desktops: %s", sss, ndesktops, desktop_names)
        if self.dpi > 0:
            # use command line value supplied, but scale it:
            xdpi = ydpi = self.dpi
            log("get_screen_settings() dpi=%s", self.dpi)
        else:
            # not supplied, use platform detection code:
            xdpi = self.get_xdpi()
            ydpi = self.get_ydpi()
            log("get_screen_settings() xdpi=%s, ydpi=%s", get_xdpi(), get_ydpi())
        xdpi = self.cx(xdpi)
        ydpi = self.cy(ydpi)
        log("get_screen_settings() scaled: xdpi=%s, ydpi=%s", xdpi, ydpi)
        vrefresh = self.get_vrefresh()
        log("get_screen_settings() vrefresh=%s", vrefresh)
        monitors = self.get_monitors_info()
        return root_w, root_h, sss, ndesktops, desktop_names, u_root_w, u_root_h, xdpi, ydpi, vrefresh, monitors

    def update_screen_size(self) -> None:
        self.screen_size_change_timer = 0
        screen_settings = self.get_screen_settings()
        log("update_screen_size()     new settings=%s", screen_settings)
        log("update_screen_size() current settings=%s", self._last_screen_settings)
        if self._last_screen_settings == screen_settings:
            log("screen size unchanged")
            return
        root_w, root_h, sss = screen_settings[:3]
        log.info("sending updated screen size to server: %sx%s", root_w, root_h)
        log_screen_sizes(root_w, root_h, sss)
        if "configure-display" in self.server_packet_types:
            root_w, root_h = screen_settings[:2]
            ndesktops, desktop_names = screen_settings[3:5]
            u_root_w, u_root_h = screen_settings[5:7]
            xdpi, ydpi = screen_settings[7:9]
            rrate, monitors = screen_settings[9:11]
            attrs = {
                "desktop-size": (root_w, root_h),
                "desktop-size-unscaled": (u_root_w, u_root_h),
                "monitors": monitors,
                "dpi": {"x": xdpi, "y": ydpi},
            }
            icc = self.get_icc_info()
            dicc = self.get_display_icc_info()
            if icc or dicc:
                attrs["icc"] = {
                    "global": icc,
                    "display": dicc,
                }
            if ndesktops:
                attrs["desktops"] = ndesktops
                attrs["desktop-names"] = desktop_names or ()
            if rrate:
                attrs["vrefresh"] = rrate
            log(f"configure-display: {attrs}")
            self.send("configure-display", attrs)
        self._last_screen_settings = screen_settings
        # update the max packet size (may have gone up):
        self.set_max_packet_size()

    def get_xdpi(self) -> int:
        return get_xdpi()

    def get_ydpi(self) -> int:
        return get_ydpi()

    def scaleup(self) -> None:
        scaling = max(self.xscale, self.yscale)
        options = scaleup_value(scaling)
        scalinglog("scaleup() options=%s", options)
        if options:
            self._scaleto(min(options))

    def scaledown(self) -> None:
        scaling = min(self.xscale, self.yscale)
        options = scaledown_value(scaling)
        scalinglog("scaledown() options=%s", options)
        if options:
            self._scaleto(max(options))

    def _scaleto(self, new_scaling) -> None:
        scaling = max(self.xscale, self.yscale)
        scalinglog("_scaleto(%s) current value=%s", r4cmp(new_scaling, 1000) / 1000.0, r4cmp(scaling, 1000) / 1000.0)
        if new_scaling > 0:
            self.scale_change(new_scaling / scaling, new_scaling / scaling)

    def scalingoff(self) -> None:
        self.scaleset(1, 1)

    def scalereset(self) -> None:
        self.scaleset(*self.initial_scaling)

    def scaleset(self, xscale=1.0, yscale=1.0) -> None:
        scalinglog("scaleset(%s, %s) current scaling: %s, %s", xscale, yscale, self.xscale, self.yscale)
        self.scale_change(xscale / self.xscale, yscale / self.yscale)

    def scale_change(self, xchange=1.0, ychange=1.0) -> None:
        scalinglog("scale_change(%s, %s)", xchange, ychange)
        if self.server_is_desktop and self.desktop_fullscreen:
            scalinglog("scale_change(%s, %s) ignored, fullscreen shadow mode is active", xchange, ychange)
            return
        if not self.can_scale:
            scalinglog("scale_change(%s, %s) ignored, scaling is disabled", xchange, ychange)
            return
        if self.screen_size_change_timer:
            scalinglog("scale_change(%s, %s) screen size change is already pending", xchange, ychange)
            return
        if monotonic() < self.scale_change_embargo:
            scalinglog("scale_change(%s, %s) screen size change not permitted during embargo time - try again",
                       xchange, ychange)
            return

        def clamp(v) -> int | float:
            return max(MIN_SCALING, min(MAX_SCALING, v))

        xscale = clamp(self.xscale * xchange)
        yscale = clamp(self.yscale * ychange)
        scalinglog("scale_change xscale: clamp(%s*%s)=%s", self.xscale, xchange, xscale)
        scalinglog("scale_change yscale: clamp(%s*%s)=%s", self.yscale, ychange, yscale)
        if fequ(xscale, self.xscale) and fequ(yscale, self.yscale):
            scalinglog("scaling unchanged: %sx%s", self.xscale, self.yscale)
            return
        # re-calculate change values against clamped scale:
        xchange = xscale / self.xscale
        ychange = yscale / self.yscale
        # check against maximum server supported size:
        maxw, maxh = self.server_max_desktop_size
        root_w, root_h = self.get_root_size()
        sw = int(root_w / xscale)
        sh = int(root_h / yscale)
        scalinglog("scale_change root size=%s x %s, scaled to %s x %s", root_w, root_h, sw, sh)
        scalinglog("scale_change max server desktop size=%s x %s", maxw, maxh)
        if not self.server_is_desktop and (sw > (maxw + 1) or sh > (maxh + 1)):
            # would overflow..
            summary = "Invalid Scale Factor"
            messages = [
                "cannot scale by %i%% x %i%% or lower" % (round(100 * xscale), round(100 * yscale)),
                "the scaled client screen %i x %i -> %i x %i" % (root_w, root_h, sw, sh),
                " would overflow the server's screen: %i x %i" % (maxw, maxh),
            ]
            self.may_notify(NotificationID.SCALING, summary, "\n".join(messages), icon_name="scaling")
            scalinglog.warn("Warning: %s", summary)
            for m in messages:
                scalinglog.warn(" %s", m)
            return
        self.xscale = xscale
        self.yscale = yscale
        scalinglog("scale_change new scaling: %sx%s, change: %sx%s", self.xscale, self.yscale, xchange, ychange)
        self.scale_reinit(xchange, ychange)

    def scale_reinit(self, xchange=1.0, ychange=1.0) -> None:
        # wait at least one second before changing again:
        self.scale_change_embargo = monotonic() + SCALING_EMBARGO_TIME
        if fequ(self.xscale, self.yscale):
            scalinglog.info("setting scaling to %i%%:", round(100 * self.xscale))
        else:
            scalinglog.info("setting scaling to %i%% x %i%%:", round(100 * self.xscale), round(100 * self.yscale))
        self.update_screen_size()
        # re-initialize all the windows with their new size
        for win in self._id_to_window.values():
            if hasattr(win, "_xscale"):
                win._xscale *= xchange
            if hasattr(win, "_yscale"):
                win._yscale *= ychange

        def new_size_fn(w, h) -> tuple[int, int]:
            minx, miny = 16384, 16384
            if self.max_window_size != (0, 0):
                minx, miny = self.max_window_size
            return max(1, min(minx, round(w * xchange))), max(1, min(miny, round(h * ychange)))

        self.resize_windows(new_size_fn)
        self.reinit_window_icons()
        self.emit("scaling-changed")

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("show-desktop", "desktop_size", main_thread=True)
