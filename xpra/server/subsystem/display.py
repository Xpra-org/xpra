# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import DISPLAY_CONFIGURE
from xpra.os_util import POSIX, OSX
from xpra.util.rectangle import rectangle

from xpra.server.source.display import DisplayConnection
from xpra.util.objects import typedict
from xpra.util.screen import log_screen_sizes
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.parsing import get_refresh_rate_for_value, parse_sharing_layout, DEFAULT_REFRESH_RATE
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("screen")
sharinglog = Logger("sharing")


def get_display_type() -> str:
    if POSIX and not OSX:
        from xpra.util.system import is_Wayland
        if is_Wayland():
            return "Wayland"
        return "X11"
    return "Main"


def is_display_connection(ss) -> bool:
    try:
        from xpra.server.source.display import DisplayConnection
    except ImportError:
        return False
    return isinstance(ss, DisplayConnection)


def get_desktop_size_capability(server_source, root_w: int, root_h: int) -> tuple[int, int]:
    if not server_source or not is_display_connection(server_source):
        return root_w, root_h
    client_size = server_source.desktop_size
    log("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
    if client_size == (0, 0):
        # client did not specify size, just return what we have
        return root_w, root_h
    client_w, client_h = client_size
    w = min(client_w, root_w)
    h = min(client_h, root_h)
    return w, h


def set_window_refresh_rate(ss, rrate: int):
    if hasattr(ss, "default_batch_config"):
        ss.default_batch_config.match_vrefresh(rrate)
    if hasattr(ss, "global_batch_config"):
        ss.global_batch_config.match_vrefresh(rrate)
    if hasattr(ss, "all_window_sources"):
        for window_source in ss.all_window_sources():
            bc = window_source.batch_config
            if bc:
                bc.match_vrefresh(rrate)


class DisplayManager(StubSubsystem):
    """
    Mixin for servers that handle displays.
    """
    __slots__ = (
        "antialias", "bit_depth", "default_dpi", "display", "display_options", "dpi",
        "original_desktop_display", "refresh_rate", "sharing_layout", "xdpi", "ydpi",
    )
    DEFAULT_REFRESH_RATE = DEFAULT_REFRESH_RATE
    PREFIX = "display"
    # can this server give each client its own area of the virtual display?
    # (`sharing=combine` - only the seamless X11 servers can, and only with RandR 1.6)
    SHARING_LAYOUT_SUPPORTED = False

    # `display-geometry-changed` is emitted on this subsystem (via
    # `SignalEmitter`) when the display geometry changes. Peer subsystems
    # subscribe with `self.get_subsystem("display").connect(...)`.
    __signals__ = ["display-geometry-changed"]

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.server.hello_request_handlers["screenshot"] = self._handle_hello_request_screenshot
        self.server.hello_request_handlers["icon"] = self._handle_hello_request_icon
        self.display = os.environ.get("DISPLAY", "")
        self.display_options = ""
        self.default_dpi = 96
        self.bit_depth = 24
        self.dpi = 0
        self.xdpi = 0
        self.ydpi = 0
        self.antialias: dict[str, Any] = {}
        self.refresh_rate = "auto"
        self.original_desktop_display = None
        # how the virtual display is shared between multiple clients:
        # `combine` gives each client its own area of it, anything else mirrors it
        self.sharing_layout = ""

    def init(self, opts) -> None:
        self.default_dpi = int(opts.dpi)
        self.refresh_rate = opts.refresh_rate
        self.sharing_layout = parse_sharing_layout(opts.sharing)
        sharinglog("sharing layout %r from sharing=%r", self.sharing_layout, opts.sharing)

    def setup(self) -> None:
        from xpra.platform.gui import init as gui_init
        log("gui_init()")
        gui_init()
        self.bit_depth = self.get_display_bit_depth()
        self.idle_add(self.print_screen_info)
        if self.sharing_layout and not self.SHARING_LAYOUT_SUPPORTED:
            session_type = getattr(self.server, "session_type", "")
            self.disable_sharing_layout(f"{session_type!r} sessions share a single display between their clients")

    def disable_sharing_layout(self, reason: str) -> None:
        """ fall back to sharing the display as `sharing=yes` would """
        sharinglog.warn("Warning: %r display sharing is not available", self.sharing_layout)
        sharinglog.warn(" %s", reason)
        sharinglog.warn(" the display will be shared as with `sharing=yes`")
        self.sharing_layout = ""

    def print_screen_info(self) -> None:
        for x in self.get_display_description().split("\n"):
            log.info(x)

    def get_display_description(self) -> str:
        dinfo = self.get_display_name()
        dtype = get_display_type()
        if dinfo == "Main":
            dinfo = f"{dtype} display"              #ie: "Main display" on macOS and win32
        else:
            dinfo = f"{dtype} display {dinfo}"      #ie: "X11 display :0"
        if size := self.get_display_size():
            w, h = size
            dinfo += f" size {w}x{h}"
        if bit_depth := self.get_display_bit_depth():
            dinfo += f"\n with {bit_depth} bit colors"
        return dinfo

    def get_display_name(self) -> str:
        return os.environ.get("DISPLAY", "")

    @staticmethod
    def publish_displayfd(display_name: str, fd: int) -> None:
        if OSX or not POSIX or fd <= 0:
            return
        try:
            from xpra.platform import displayfd
            display_no = display_name[1:]
            # ensure it is a string containing the number:
            display_no = str(int(display_no))
            log(f"writing display_no={display_no} to displayfd={fd}")
            assert displayfd.write_displayfd(fd, display_no), "timeout"
        except Exception as e:
            log.error("write_displayfd failed", exc_info=True)
            log.error(f"Error: failed to write {display_name} to fd={fd}")
            log.estr(e)

    def get_wm_name(self) -> str:
        return ""

    @staticmethod
    def get_display_bit_depth() -> int:
        return 0

    def get_refresh_rate_for_value(self, invalue) -> int:
        return get_refresh_rate_for_value(self.refresh_rate, invalue)

    def parse_hello(self, ss, caps: typedict) -> str | ConnectionMessage:
        if is_display_connection(ss):
            self.parse_screen_info(ss)
        return ""

    def add_new_client(self, ss, c: typedict) -> None:
        if not is_display_connection(ss):
            return
        from xpra.server.source.display import DisplayConnection
        display_clients = self.get_sources_by_type(DisplayConnection, ss)
        # a bit of explanation:
        # normally these things are synchronized using xsettings, which we handle already,
        # but non-posix clients have no such thing,
        # and we don't want to expose that as an interface
        # (it's not very nice, and it is very X11 specific)
        # also, clients may want to override what is in their xsettings..
        # so if the client specifies what it wants to use, we patch the xsettings with it
        # (the actual xsettings part is done in `update_all_server_settings` in the X11 specific subclasses)
        if display_clients:
            log.info("sharing with %s other client(s)", len(display_clients))
            self.dpi = 0
            self.xdpi = 0
            self.ydpi = 0
            self.antialias = {}
        else:
            dpi_caps = c.get("dpi")
            if isinstance(dpi_caps, int):
                # legacy mode, ie: html5 client
                self.dpi = self.xdpi = self.ydpi = int(dpi_caps)
            else:
                tdpi = typedict(c.dictget("dpi"))
                self.dpi = tdpi.intget("", 0)
                self.xdpi = tdpi.intget("x", self.xdpi)
                self.ydpi = tdpi.intget("y", self.ydpi)
            self.antialias = c.dictget("antialias")
        log("dpi=%s, dpi.x=%s, dpi.y=%s, antialias=%s",
            self.dpi, self.xdpi, self.ydpi, self.antialias)

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = self.get_display_caps(source)
        if BACKWARDS_COMPATIBLE:
            # legacy: use top level attributes:
            caps["display"] = caps.get("name", "")
            return caps
        return {"display": caps}

    def get_display_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        # with `sharing=combine`, each client only sees its own area of the virtual display:
        area_size = getattr(source, "get_display_area_size", lambda: ())()
        if area_size:
            sharinglog("get_display_caps(%s) using display area size %s", source, area_size)
        if root_size := (area_size or self.get_display_size()):
            caps |= {
                "actual_desktop_size": root_size,
                "root_window_size": root_size,
                "desktop_size": get_desktop_size_capability(source, *root_size),
            }
        if max_size := (area_size or self.get_max_screen_size()):
            caps["max_desktop_size"] = max_size
        if name := self.get_display_name():
            caps["name"] = name
        if self.display:
            caps["address"] = self.display
        return caps

    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        if max_size := self.get_max_screen_size():
            return {"server": {"max_desktop_size": max_size}}
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        i = {
            "dpi": {
                "default": self.default_dpi,
                "value": self.dpi,
                "x": self.xdpi,
                "y": self.ydpi,
            },
            "antialias": self.antialias,
            "depth": self.bit_depth,
            "refresh-rate": self.refresh_rate,
            "name": self.get_display_name(),
        }
        if self.sharing_layout:
            # only set if this server can actually honour it, see `disable_sharing_layout`
            i["sharing-layout"] = self.sharing_layout
        if self.display:
            i["address"] = self.display
        if self.original_desktop_display:
            i["original-desktop-display"] = self.original_desktop_display
        return {
            "display": i,
        }

    ######################################################################
    # display / screen / root window:
    def get_display_size(self) -> tuple[int, int]:
        return 0, 0

    def set_screen_geometry_attributes(self, w: int, h: int) -> None:
        # by default, use the screen as desktop area:
        self.set_desktop_geometry_attributes(w, h)

    def set_desktop_geometry_attributes(self, w: int, h: int) -> None:
        # `calculate_desktops` / `set_desktop_geometry` are variant-overridable
        # on the server (e.g. `SeamlessServer`), so we route through self.server:
        self.server.calculate_desktops()
        self.calculate_workarea(w, h)
        self.server.set_desktop_geometry(w, h)

    def parse_screen_info(self, ss) -> tuple[int, int]:
        return self.do_parse_screen_info(ss, ss.desktop_size)

    def do_parse_screen_info(self, ss, desktop_size) -> tuple[int, int]:
        log("do_parse_screen_info%s", (ss, desktop_size))
        dw, dh = None, None
        if desktop_size != (0, 0):
            try:
                dw, dh = desktop_size
                log.info(" client total display size is %sx%s", dw, dh)
                if ss.screen_sizes:
                    log_screen_sizes(dw, dh, ss.screen_sizes)
            except Exception:
                dw, dh = None, None
        best = self.configure_best_screen_size()
        if not best:
            return desktop_size
        sw, sh = best
        if self.sharing_layout:
            # the display is sized to hold every client, not just this one,
            # and this client is only told about the area it has been given:
            ss.desktop_size_server = ss.get_display_area_size() or (sw, sh)
            self.set_desktop_geometry_attributes(sw, sh)
            self.apply_refresh_rate(ss)
            sharinglog("do_parse_screen_info(%s, %s) combined display is %ix%i, this client gets %s",
                       ss, desktop_size, sw, sh, ss.desktop_size_server)
            return sw, sh
        # we will tell the client about the size chosen in the hello we send back,
        # so record this size as the current server desktop size to avoid change notifications:
        ss.desktop_size_server = sw, sh
        # prefer desktop size, fallback to screen size:
        w = dw or sw
        h = dh or sh
        # clamp to max supported:
        if max_size := self.get_max_screen_size():
            maxw, maxh = max_size
            w = min(w, maxw)
            h = min(h, maxh)
        self.set_desktop_geometry_attributes(w, h)
        self.apply_refresh_rate(ss)
        log("do_parse_screen_info(..)=%s", (w, h))
        return w, h

    def notify_screen_changed(self) -> None:
        log("notify_screen_changed()")
        self.emit("display-geometry-changed")
        self.idle_add(self.send_updated_screen_size)

    def send_updated_screen_size(self) -> None:
        root_size = self.get_display_size()
        if not root_size:
            return
        root_w, root_h = root_size
        max_size = self.get_max_screen_size()
        if not max_size:
            return
        max_w, max_h = max_size
        root_w = min(root_w, max_w)
        root_h = min(root_h, max_h)
        count = 0
        display_sources = self.get_sources_by_type(DisplayConnection)
        for ss in display_sources:
            if ss.updated_desktop_size(root_w, root_h, max_w, max_h):
                count += 1
        if count > 0:
            log.info("sent updated screen size to %s clients: %sx%s (max %sx%s)",
                     count, root_w, root_h, max_w, max_h)

    def get_max_screen_size(self) -> tuple[int, int]:
        return self.get_display_size()

    def configure_best_screen_size(self) -> tuple[int, int]:
        return self.get_display_size()

    def apply_refresh_rate(self, ss) -> int:
        rrate = self.get_client_refresh_rate(ss)
        log(f"apply_refresh_rate({ss}) rate={rrate}")
        if rrate > 0:
            set_window_refresh_rate(ss, rrate)
        return rrate

    def get_client_refresh_rate(self, ss) -> int:
        vrefresh = []
        # use the real refresh-rate value from the monitors
        # (value is pre-multiplied by 1000!) and apply our own `--refresh-rate`
        # policy below - the client only cooks the value it applies to its own display:
        if ss.monitors:
            for mdef in ss.monitors.values():
                v = mdef.get("refresh-rate", 0)
                if v:
                    vrefresh.append(v)
        if not vrefresh and getattr(ss, "vrefresh", 0) > 0:
            vrefresh.append(ss.vrefresh * 1000)
        if not vrefresh:
            vrefresh.append(self.DEFAULT_REFRESH_RATE)
        rrate = 0
        if vrefresh:
            rrate = min(vrefresh)
            if self.refresh_rate:
                rrate = get_refresh_rate_for_value(self.refresh_rate, rrate, multiplier=1000)
            rrate = round(rrate / 1000)
        log("get_client_refresh_rate(%s)=%s (from %s)", ss, rrate, vrefresh)
        return rrate

    def _process_desktop_size(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        log("new desktop size from %s: %s", proto, packet)
        assert BACKWARDS_COMPATIBLE
        root_w = packet.get_u16(1)
        root_h = packet.get_u16(2)
        screens = packet[3]
        ss.set_screen_sizes(screens)
        if len(packet) <= 4:
            return
        ndesktops = packet.get_u8(4)
        desktop_names = packet.get_strs(5)
        u_root_w = packet.get_u16(6)
        u_root_h = packet.get_u16(7)
        xdpi = packet.get_u16(8)
        ydpi = packet.get_u16(9)
        rrate = packet.get_u16(10)
        monitors = packet.get_dict(11)
        attrs: dict[str, Any] = {
            "desktop-size": (root_w, root_h),
            "desktop-size-unscaled": (u_root_w, u_root_h),
            "monitors": monitors,
            "dpi": {"x": xdpi, "y": ydpi},
        }
        if ndesktops:
            attrs["desktops"] = ndesktops
            attrs["desktop-names"] = desktop_names or ()
        if rrate:
            attrs["vrefresh"] = rrate
        packet = Packet(DISPLAY_CONFIGURE, attrs)
        self._process_configure(proto, packet)

    def set_screen_size(self, width: int, height: int):
        """ subclasses should override this method if they support resizing """

    def _apply_desktop_size(self, ss, width: int, height: int) -> None:
        log("client requesting new size: %sx%s", width, height)
        log.info("received updated display dimensions")
        log.info(f"client display size is {width}x{height}")
        log_screen_sizes(width, height, ss.screen_sizes)
        if self.sharing_layout:
            # this client is only one part of the display: re-do the whole layout
            # (which also re-assigns the areas, since this client's may have changed size)
            sharinglog("_apply_desktop_size(%s, %i, %i) re-combining the display", ss, width, height)
            width, height = self.configure_best_screen_size()
            if width <= 0 or height <= 0:
                return
        else:
            # variant servers wrap `set_screen_size` (see SeamlessServer); route
            # through self.server so the wrapper fires:
            self.server.set_screen_size(width, height)
        self.calculate_workarea(width, height)
        self.set_desktop_geometry_attributes(width, height)

    def _process_configure(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if ss is None:
            return
        attrs = typedict(packet.get_dict(1))
        desktop_size = attrs.intpair("desktop-size")
        if desktop_size != (0, 0):
            ss.desktop_size = desktop_size
        desktop_size_unscaled = attrs.intpair("desktop-size-unscaled")
        if desktop_size_unscaled != (0, 0):
            ss.desktop_size_unscaled = desktop_size_unscaled
        # vrefresh may be overridden in 'monitors' data:
        vrefresh = attrs.intget("vrefresh")
        if 0 < vrefresh < 240 and hasattr(ss, "vrefresh") and getattr(ss, "vrefresh") != vrefresh:
            ss.vrefresh = vrefresh
        if "monitors" in attrs:
            ss.set_monitors(attrs.dictget("monitors"))
        if desktop_size != (0, 0):
            self._apply_desktop_size(ss, *desktop_size)
        # DPI
        dpi = 0
        dpi_caps = attrs.get("dpi")
        # unprefixed legacy mode:
        if isinstance(dpi_caps, int):
            dpi = int(dpi_caps)
        dpix = attrs.intget("dpi.x", dpi)
        dpiy = attrs.intget("dpi.y", dpi)
        # namespaced caps:
        if isinstance(dpi_caps, dict):
            tdpi = typedict(dpi_caps)
            dpix = tdpi.intget("x", dpix)
            dpiy = tdpi.intget("y", dpiy)
        if dpix and dpiy and (dpix != self.xdpi or dpiy != self.ydpi):
            self.xdpi, self.ydpi = dpix, dpiy
            log("new dpi: %ix%i", dpix, dpiy)
            self.dpi = round((dpix + dpiy) / 2)
            self.dpi_changed()
        desktop_names = attrs.strtupleget("desktop-names")
        if desktop_names:
            ss.set_desktops(attrs.intget("desktops", len(desktop_names)), desktop_names)
            self.server.calculate_desktops()
        # soft dependency on ICC:
        iccdata = attrs.dictget("icc")
        if iccdata:
            if icc := self.get_subsystem("icc"):
                icc.process_icc(ss, iccdata)
        self.apply_refresh_rate(ss)
        # ensures that DPI and antialias information gets reset:
        if xsettings := self.get_subsystem("xsettings"):
            xsettings.update_all_server_settings()

    def dpi_changed(self) -> None:
        """
        The x11 servers override this method
        to also update the XSettings.
        """
        self.update_server_settings()

    def calculate_desktops(self):
        """ seamless servers can update the desktops """

    def calculate_workarea(self, maxw: int, maxh: int) -> None:
        log("calculate_workarea(%s, %s)", maxw, maxh)
        if not maxw or not maxh:
            raise ValueError("invalid dimensions: %ix%i" % (maxw, maxh))
        workarea = rectangle(0, 0, maxw, maxh)
        display_sources = self.get_sources_by_type(DisplayConnection)
        if self.sharing_layout:
            # the clients occupy distinct areas of the display, so intersecting
            # their workareas would leave nothing usable: the whole display is the workarea
            sharinglog("calculate_workarea(%s, %s) sharing layout %r: using the full display area",
                       maxw, maxh, self.sharing_layout)
            self.server.set_workarea(workarea)
            self.server.set_workareas(self.calculate_workareas(maxw, maxh, display_sources))
            return
        for ss in display_sources:
            # derived from the `monitors` dict (modern clients) or `screen_sizes` (legacy):
            client_workarea = ss.get_client_workarea()
            log("calculate_workarea() workarea(%s)=%s", ss, client_workarea)
            if not client_workarea:
                continue
            common_workarea = workarea.intersection_rect(client_workarea)
            if not common_workarea:
                log.warn("Warning: failed to calculate workarea")
                log.warn(" as intersection of %s and %s", (maxw, maxh), client_workarea)
                workarea = None
                break
            workarea = common_workarea
        # sanity checks:
        log("calculate_workarea(%s, %s) workarea=%s", maxw, maxh, workarea)
        max_dim = 32768 - 8192
        if not workarea or workarea.width == 0 or workarea.height == 0 or workarea.width >= max_dim or workarea.height >= max_dim:
            log.warn("Warning: failed to calculate a common workarea")
            log.warn(f" using the full display area: {maxw}x{maxh}")
            workarea = rectangle(0, 0, maxw, maxh)
        # variant-overridable on the server:
        self.server.set_workarea(workarea)
        self.server.set_workareas(self.calculate_workareas(maxw, maxh, display_sources))

    def calculate_workareas(self, maxw: int, maxh: int, display_sources) -> list[tuple[int, int, int, int]]:
        """ the per-monitor workareas, which can only be honoured for a single display client
            (with more than one, the monitor layouts don't match and there is nothing sensible to export)
            - unless we are combining the clients' displays, in which case they all line up """
        if len(display_sources) != 1 and not self.sharing_layout:
            return []
        screen = rectangle(0, 0, maxw, maxh)
        workareas = []
        for ss in display_sources:
            ox, oy = ss.get_display_origin()
            for client_workarea in ss.get_client_workareas():
                wx, wy, ww, wh = client_workarea
                common = screen.intersection_rect(rectangle(wx + ox, wy + oy, ww, wh))
                if common:
                    workareas.append((common.x, common.y, common.width, common.height))
        log("calculate_workareas(%s, %s) workareas=%s", maxw, maxh, workareas)
        return workareas

    ######################################################################
    # screenshots:
    def _handle_hello_request_screenshot(self, proto, _caps: typedict) -> bool:
        packet = self.make_screenshot_packet()
        proto.send_now(packet)
        return True

    def _handle_hello_request_icon(self, proto, _caps: typedict) -> bool:
        packet = self.make_icon_packet()
        proto.send_now(packet)
        return True

    def _process_request_screenshot(self, proto, _packet: Packet) -> None:
        packet = self.make_screenshot_packet()
        ss = self.get_server_source(proto)
        if packet and ss:
            ss.send(*packet)

    def _process_request_icon(self, proto, _packet: Packet) -> None:
        packet = self.make_icon_packet()
        ss = self.get_server_source(proto)
        if packet and ss:
            ss.send(*packet)

    def make_screenshot_packet(self) -> Packet:
        with log.trap_error("Error making screenshot packet"):
            return self.do_make_screenshot_packet()

    def do_make_screenshot_packet(self) -> Packet:
        raise NotImplementedError("no screenshot capability in %s" % type(self))

    def make_icon_packet(self) -> Packet:
        with log.trap_error("Error making icon packet"):
            return self.do_make_icon_packet()

    def do_make_icon_packet(self) -> Packet:
        raise NotImplementedError("no icon capability in %s" % type(self))

    def send_screenshot(self, proto) -> None:
        # this is a screenshot request, handle it and disconnect
        try:
            packet = self.make_screenshot_packet()
            if not packet:
                self.server.send_disconnect(proto, "screenshot failed")
                return
            proto.send_now(packet)
            self.timeout_add(5 * 1000, self.server.send_disconnect, proto, "screenshot sent")
        except Exception as e:
            log.error("failed to capture screenshot", exc_info=True)
            self.server.send_disconnect(proto, "screenshot failed: %s" % e)

    def init_packet_handlers(self) -> None:
        self.add_packets("display-configure", "display-request-screenshot", "display-request-icon", main_thread=True)
        if BACKWARDS_COMPATIBLE:
            self.add_legacy_alias("configure-display", "display-configure")
            self.add_legacy_alias("screenshot", "display-request-screenshot")
            self.add_packets("desktop_size", main_thread=True)
