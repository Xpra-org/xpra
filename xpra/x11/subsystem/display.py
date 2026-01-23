# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from subprocess import Popen
from collections.abc import Sequence

from xpra.os_util import gi_import, POSIX
from xpra.util.env import envint, envbool, first_time
from xpra.util.version import XPRA_VERSION
from xpra.x11.error import xlog, xsync, xswallow, XError
from xpra.exit_codes import ExitCode
from xpra.util.system import is_X11
from xpra.scripts.config import FALSE_OPTIONS, InitExit
from xpra.net.common import Packet
from xpra.common import (
    get_refresh_rate_for_value, parse_env_resolutions, parse_resolutions,
    MAX_WINDOW_SIZE, NotificationID, BACKWARDS_COMPATIBLE,
)
from xpra.x11.xroot_props import root_set, root_get, root_del
from xpra.server.subsystem.display import DisplayManager
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("screen")
grablog = Logger("server", "grab")

DUMMY_WIDTH_HEIGHT_MM = envbool("XPRA_DUMMY_WIDTH_HEIGHT_MM", True)


def x11_ungrab() -> None:
    grablog("X11_ungrab")
    with xsync:
        from xpra.x11.bindings.core import X11CoreBindings
        core = X11CoreBindings()
        core.UngrabKeyboard()
        core.UngrabPointer()


def check_xvfb(xvfb: Popen | None, timeout=0) -> bool:
    if xvfb is None:
        return True
    assert POSIX
    from xpra.x11.vfb_util import check_xvfb_process
    if not check_xvfb_process(xvfb, timeout=timeout):
        return False
    return True


def _get_root_int(prop: str) -> int:
    from xpra.x11.xroot_props import root_get
    with xsync:
        return root_get(prop, "u32") or 0


def _set_root_int(prop: str = "_XPRA_RANDR_EXACT_SIZE", i: int = 0) -> None:
    from xpra.x11.xroot_props import root_set
    with xsync:
        root_set(prop, "u32", i)


def get_root_size() -> tuple[int, int]:
    with xsync:
        from xpra.x11.bindings.window import X11WindowBindings
        X11Window = X11WindowBindings()
        return X11Window.get_root_size()


def get_display_pid() -> int:
    # perhaps this is an upgrade from an older version?
    # try harder to find the pid:
    try:
        return _get_root_int("XPRA_XVFB_PID") or _get_root_int("_XPRA_SERVER_PID") or 0
    except RuntimeError:
        return 0


def save_server_pid() -> None:
    root_set("XPRA_SERVER_PID", "u32", os.getpid())


def save_server_mode(session_type: str) -> None:
    root_set("XPRA_SERVER_MODE", "latin1", session_type)


def save_server_uuid(uuid: str) -> None:
    root_set("XPRA_SERVER_UUID", "latin1", uuid)


def get_server_uuid() -> str:
    return root_get("XPRA_SERVER_UUID", "latin1") or ""


def save_server_version():
    if BACKWARDS_COMPATIBLE:
        root_set("XPRA_SERVER", "latin1", XPRA_VERSION)
    root_set("XPRA_SERVER_VERSION", "latin1", XPRA_VERSION)


def log_randr_warning(msg="no randr bindings", error="") -> None:
    log.warn("Warning: %s", msg)
    if error:
        log.warn(error)
    log.warn(" the virtual display cannot be configured properly")


class X11DisplayManager(DisplayManager):
    """
    Mixin for servers that handle displays.
    """

    def __init__(self):
        DisplayManager.__init__(self)
        self.xvfb: Popen | None = None
        self.display_pid: int = 0
        self.randr_sizes_added: list[tuple[int, int]] = []
        self.initial_resolutions: Sequence[tuple[int, int, int]] = ()
        self.randr = False
        self.randr_exact_size = False
        self.antialias: dict[str, Any] = {}
        self.original_desktop_display = None
        # the actual values are defined in subclasses:
        self.session_type = ""
        self.uuid = ""

    def init(self, opts) -> None:
        self.init_display_pid()
        DisplayManager.init(self, opts)
        onoff = sizes = opts.resize_display
        if opts.resize_display.find(":") > 0:
            # ie: "off:1080p"
            onoff, sizes = opts.resize_display.split(":", 1)
        try:
            res = parse_resolutions(sizes, opts.refresh_rate)
            self.initial_resolutions = res if res is not None else self.get_default_initial_res()
        except ValueError:
            self.initial_resolutions = self.get_default_initial_res()
        log("initial_resolutions(%s, %s)=%s", sizes, opts.refresh_rate, self.initial_resolutions)
        self.randr = onoff.lower() not in FALSE_OPTIONS
        self.randr_exact_size = False
        self.check_xvfb()

    def get_default_initial_res(self) -> Sequence[tuple[int, int, int]]:
        # desktop servers override this to use 1080p
        # seamless servers should start with the larger default (8K)
        return parse_env_resolutions(default_refresh_rate=self.refresh_rate)

    def get_caps(self, source) -> dict[str, Any]:
        caps = DisplayManager.get_caps(self, source)
        if "features" in source.wants:
            caps |= {
                "resize_screen": self.randr,
                "resize_exact": self.randr_exact_size,
                "force_ungrab": True,
            }
            if self.randr:
                sizes = self.get_all_screen_sizes()
                if len(sizes) > 1:
                    caps["screen-sizes"] = sizes
        return caps

    def check_xvfb(self) -> None:
        if not check_xvfb(self.xvfb):
            raise InitExit(ExitCode.NO_DISPLAY, "xvfb process has terminated")

    def setup(self) -> None:
        self.check_xvfb()
        from xpra.scripts.server import verify_display
        if not verify_display(xvfb=self.xvfb, display_name=self.display):
            raise InitExit(ExitCode.NO_DISPLAY, f"unable to access display {self.display!r}")
        self.session_files += [
            "xvfb.pid",
            "xauthority",
            "Xorg.log",
            "Xorg.log.old",
            "xorg.conf.d/*",
            "xorg.conf.d",
        ]
        DisplayManager.setup(self)
        if not self.display_pid:
            self.display_pid = get_display_pid()
        if self.randr and self.init_randr():
            self.set_initial_resolution()
        with xsync:
            save_server_pid()
            save_server_mode(self.session_type)
            save_server_uuid(self.uuid)
            save_server_version()

    def init_randr(self) -> bool:
        from xpra.x11.error import xlog
        try:
            from xpra.x11.bindings.randr import RandRBindings
        except ImportError as e:
            self.randr = False
            log_randr_warning("no randr bindings", str(e))
            return False
        with xlog:
            RandR = RandRBindings()
            if not RandR.has_randr():
                log_randr_warning("randr extension is not available")
                self.randr = False
                return False
            # check the property first,
            # because we may be inheriting this display,
            # in which case the screen sizes list may be longer than 1
            eprop = _get_root_int("_XPRA_RANDR_EXACT_SIZE")
            log("_XPRA_RANDR_EXACT_SIZE=%s", eprop)
            self.randr_exact_size = eprop == 1 or RandR.get_version() >= (1, 6)
            if not self.randr_exact_size:
                # ugly hackish way of detecting Xvfb with randr,
                # assume that it has only one resolution pre-defined:
                sizes = RandR.get_xrr_screen_sizes()
                if len(sizes) == 1:
                    self.randr_exact_size = True
                    _set_root_int("_XPRA_RANDR_EXACT_SIZE",1)
                elif not sizes:
                    # xwayland?
                    self.randr = False
                    self.randr_exact_size = False
            log(f"randr enabled: {self.randr}, exact size={self.randr_exact_size}")
            if not self.randr:
                log.warn("Warning: no X11 RandR support on %r", os.environ.get("DISPLAY", ""))
        return self.randr

    def set_initial_resolution(self) -> None:
        log(f"set_initial_resolution() randr={self.randr}, initial_resolutions={self.initial_resolutions}")
        if self.randr and self.initial_resolutions and is_X11():
            from xpra.x11.error import xlog
            from xpra.x11.vfb_util import set_initial_resolution
            dpi = self.dpi or self.default_dpi
            resolutions = self.initial_resolutions
            with xlog:
                set_initial_resolution(resolutions, dpi)

    def init_display_pid(self) -> None:
        pid = envint("XVFB_PID", 0)
        if not pid:
            log.info("xvfb pid not found")
        else:
            log.info(f"xvfb pid {pid}")
        self.display_pid = pid

    def late_cleanup(self, stop=True) -> None:
        with xswallow:
            root_del("XPRA_SERVER_PID")
            root_del("XPRA_SERVER_VERSION")
            if BACKWARDS_COMPATIBLE:
                root_del("XPRA_SERVER")
            if stop:
                root_del("XPRA_SERVER_MODE")
                root_del("_XPRA_RANDR_EXACT_SIZE")
        if stop and POSIX:
            self.kill_display()
        elif self.display_pid:
            log.info("not cleaning up Xvfb %i", self.display_pid)

    def kill_display(self) -> None:
        if not self.display_pid:
            log("unable to kill display: no display pid")
            return
        from xpra.x11.vfb_util import kill_xvfb
        kill_xvfb(self.display_pid)

    def get_display_bit_depth(self) -> int:
        with xlog:
            from xpra.x11.bindings.window import X11WindowBindings
            X11Window = X11WindowBindings()
            rxid = X11Window.get_root_xid()
            return X11Window.get_depth(rxid)
        return 0

    def get_refresh_rate_for_value(self, invalue) -> int:
        return get_refresh_rate_for_value(self.refresh_rate, invalue)

    def get_info(self, proto) -> dict[str, Any]:
        info = DisplayManager.get_info(self, proto)
        dinfo = info["display"]
        dinfo["randr"] = self.randr
        try:
            from xpra.x11.composite import CompositeHelper
            dinfo["xshm"] = CompositeHelper.XShmEnabled
        except (ImportError, ValueError) as e:
            log("no composite: %s", e)
        if self.display_pid:
            dinfo["pid"] = self.display_pid
        return info

    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        info = DisplayManager.get_ui_info(self, proto, **kwargs)
        # randr:
        if self.randr:
            with xlog:
                sizes = self.get_all_screen_sizes()
                if sizes:
                    info["randr"] = {
                        "": True,
                        "options": tuple(reversed(sorted(sizes))),
                        "exact": self.randr_exact_size,
                    }
        return info

    ######################################################################
    # display / screen / root window:
    def get_display_size(self) -> tuple[int, int]:
        if self.randr:
            with xsync:
                from xpra.x11.bindings.randr import RandRBindings
                return RandRBindings().get_screen_size()
        return get_root_size()

    def get_all_screen_sizes(self) -> Sequence[tuple[int, int]]:
        # workaround for #2910: the resolutions we add are not seen by XRRSizes!
        # so we keep track of the ones we have added ourselves:
        try:
            from xpra.x11.bindings.randr import RandRBindings
        except ImportError:
            return (get_root_size(), )
        sizes = list(RandRBindings().get_xrr_screen_sizes())
        for w, h in self.randr_sizes_added:
            if (w, h) not in sizes:
                sizes.append((w, h))
        return tuple(sizes)

    def get_max_screen_size(self) -> tuple[int, int]:
        max_w, max_h = get_root_size()
        if self.randr:
            sizes = self.get_all_screen_sizes()
            if len(sizes) >= 1:
                for w, h in sizes:
                    max_w = max(max_w, w)
                    max_h = max(max_h, h)
            if max_w > MAX_WINDOW_SIZE or max_h > MAX_WINDOW_SIZE:
                log.warn("Warning: maximum screen size is very large: %sx%s", max_w, max_h)
                log.warn(" you may encounter window sizing problems")
            log("get_max_screen_size()=%s", (max_w, max_h))
        return max_w, max_h

    def configure_best_screen_size(self) -> tuple[int, int]:
        # return ServerBase.set_best_screen_size(self)
        """ sets the screen size to use the largest width and height used by any of the clients """
        root_w, root_h = get_root_size()
        if not self.randr:
            return root_w, root_h
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        max_w, max_h = 0, 0
        min_w, min_h = 16384, 16384
        client_sizes = {}
        for ss in sss:
            client_size = ss.desktop_size
            if client_size:
                w, h = client_size
                size = "%ix%i" % (w, h)
                max_w = max(max_w, w)
                max_h = max(max_h, h)
                if w > 0:
                    min_w = min(min_w, w)
                if h > 0:
                    min_h = min(min_h, h)
                client_sizes[ss.uuid] = size
        if len(client_sizes) > 1:
            log.info("screen used by %i clients:", len(client_sizes))
            for uuid, size in client_sizes.items():
                log.info("* %s: %s", uuid, size)
        log("current server resolution is %ix%i", root_w, root_h)
        log("maximum client resolution is %ix%i", max_w, max_h)
        log("minimum client resolution is %ix%i", min_w, min_h)
        w, h = max_w, max_h
        log("using %ix%i", w, h)
        if w <= 0 or h <= 0:
            # invalid - use fallback
            return root_w, root_h
        return self.set_screen_size(w, h)

    def get_best_screen_size(self, desired_w: int, desired_h: int):
        r = self.do_get_best_screen_size(desired_w, desired_h)
        log("get_best_screen_size%s=%s", (desired_w, desired_h), r)
        return r

    def do_get_best_screen_size(self, desired_w: int, desired_h: int):
        if not self.randr:
            return desired_w, desired_h
        screen_sizes = self.get_all_screen_sizes()
        if (desired_w, desired_h) in screen_sizes:
            return desired_w, desired_h
        if self.randr_exact_size:
            try:
                with xsync:
                    from xpra.x11.bindings.randr import RandRBindings
                    if RandRBindings().add_screen_size(desired_w, desired_h):
                        # we have to wait a little bit
                        # to make sure that everything sees the new resolution
                        # (ideally this method would be split in two and this would be a callback)
                        self.randr_sizes_added.append((desired_w, desired_h))
                        import time
                        time.sleep(0.5)
                        return desired_w, desired_h
            except XError as e:
                log("add_screen_size(%s, %s)", desired_w, desired_h, exc_info=True)
                log.warn("Warning: failed to add resolution %ix%i:", desired_w, desired_h)
                log.warn(" %s", e)
            # re-query:
            screen_sizes = self.get_all_screen_sizes()
        # try to find the best screen size to resize to:
        closest = {}
        for w, h in screen_sizes:
            distance = abs(desired_w * desired_h - w * h)
            closest[distance] = (w, h)
        if not closest:
            log.warn("Warning: no matching resolution found for %sx%s", desired_w, desired_h)
            root_w, root_h = get_root_size()
            return root_w, root_h
        min_dist = sorted(closest.keys())[0]
        new_size = closest[min_dist]
        log("best %s resolution for client(%sx%s) is: %s", desired_w, desired_h, new_size)
        w, h = new_size
        return w, h

    def set_screen_size(self, desired_w: int, desired_h: int):
        log("set_screen_size%s", (desired_w, desired_h))
        root_w, root_h = get_root_size()
        if not self.randr:
            return root_w, root_h
        if desired_w == root_w and desired_h == root_h:
            return root_w, root_h  # unlikely: perfect match already!
        # clients may supply "xdpi" and "ydpi" (v0.15 onwards), or just "dpi", or nothing...
        xdpi = self.xdpi or self.dpi
        ydpi = self.ydpi or self.dpi
        log("set_screen_size(%s, %s) xdpi=%s, ydpi=%s",
            desired_w, desired_h, xdpi, ydpi)
        wmm, hmm = 0, 0
        if xdpi <= 0 or ydpi <= 0:
            # use some sane defaults: either the command line option, or fallback to 96
            # (96 is better than nothing, because we do want to set the dpi
            # to avoid Xdummy setting a crazy dpi from the virtual screen dimensions)
            xdpi = self.default_dpi or 96
            ydpi = self.default_dpi or 96
            # find the "physical" screen dimensions, so we can calculate the required dpi
            # (and do this before changing the resolution)
            client_w, client_h = 0, 0
            sss = self._server_sources.values()
            for ss in sss:
                screen_sizes = getattr(ss, "screen_sizes", ())
                for s in screen_sizes:
                    if len(s) >= 10:
                        # (display_name, width, height, width_mm, height_mm, monitors,
                        # work_x, work_y, work_width, work_height)
                        client_w = max(client_w, s[1])
                        client_h = max(client_h, s[2])
                        wmm = max(wmm, s[3])
                        hmm = max(hmm, s[4])
            if wmm > 0 and hmm > 0 and client_w > 0 and client_h > 0:
                # calculate "real" dpi:
                xdpi = round(client_w * 25.4 / wmm)
                ydpi = round(client_h * 25.4 / hmm)
                log("calculated DPI: %s x %s (from w: %s / %s, h: %s / %s)",
                    xdpi, ydpi, client_w, wmm, client_h, hmm)
        if wmm == 0 or hmm == 0:
            wmm = round(desired_w * 25.4 / xdpi)
            hmm = round(desired_h * 25.4 / ydpi)
            log(f"display dimensions for dpi {xdpi}x{ydpi} and resolution {desired_w}x{desired_h} is {wmm}x{hmm}")
        from xpra.x11.bindings.randr import RandRBindings
        if DUMMY_WIDTH_HEIGHT_MM:
            # FIXME: we assume there is only one output:
            output = 0
            with xsync:
                RandRBindings().set_output_int_property(output, "WIDTH_MM", wmm)
                RandRBindings().set_output_int_property(output, "HEIGHT_MM", hmm)
        log("set_dpi(%i, %i)", xdpi, ydpi)
        self.set_dpi(xdpi, ydpi)

        # try to find the best screen size to resize to:
        w, h = self.get_best_screen_size(desired_w, desired_h)

        if w == root_w and h == root_h:
            log.info("best resolution matching %sx%s is unchanged: %sx%s", desired_w, desired_h, w, h)
            return root_w, root_h
        with log.trap_error("Error: failed to set new resolution"):
            with xsync:
                RandRBindings().get_screen_size()
            # Xdummy with randr 1.2:
            log("using XRRSetScreenConfigAndRate with %ix%i", w, h)
            with xsync:
                RandRBindings().set_screen_size(w, h)
            if self.randr_exact_size:
                # Xvfb with randr > 1.2: the resolution has been added
                # we can use XRRSetScreenSize:
                try:
                    with xsync:
                        RandRBindings().xrr_set_screen_size(w, h, wmm, hmm)
                except XError:
                    log("XRRSetScreenSize failed", exc_info=True)
            log("calling RandR.get_screen_size()")
            with xsync:
                root_w, root_h = RandRBindings().get_screen_size()
            log("RandR.get_screen_size()=%s,%s", root_w, root_h)
            log("RandR.get_vrefresh()=%s", RandRBindings().get_vrefresh())
            if root_w != w or root_h != h:
                log.warn("Warning: tried to set resolution to %ix%i", w, h)
                log.warn(" and ended up with %ix%i", root_w, root_h)
            else:
                msg = f"server virtual display now set to {root_w}x{root_h}"
                if desired_w != root_w or desired_h != root_h:
                    msg += f" (best match for {desired_w}x{desired_h})"
                log.info(msg)

            # show dpi via idle_add so server has time to change the screen size (mm)
            GLib.idle_add(self.show_dpi, xdpi, ydpi)
        return root_w, root_h

    def show_dpi(self, xdpi: int, ydpi: int):
        root_w, root_h = get_root_size()
        from xpra.x11.bindings.randr import RandRBindings
        wmm, hmm = RandRBindings().get_screen_size_mm()  # ie: (1280, 1024)
        log("RandR.get_screen_size_mm=%s,%s", wmm, hmm)
        actual_xdpi = round(root_w * 25.4 / wmm)
        actual_ydpi = round(root_h * 25.4 / hmm)
        log("actual DPI calculated from display dimensions %ix%i and resolution %ix%i: %ix%i",
            wmm, hmm, root_w, root_h, actual_xdpi, actual_ydpi)
        if abs(actual_xdpi - xdpi) <= 1 and abs(actual_ydpi - ydpi) <= 1:
            log.info("DPI set to %s x %s", actual_xdpi, actual_ydpi)
            log("wanted: %s x %s", xdpi, ydpi)
        else:
            # should this be a warning:
            log_fn = log.info
            maxdelta = max(abs(actual_xdpi - xdpi), abs(actual_ydpi - ydpi))
            if maxdelta >= 10:
                log_fn = log.warn
            messages = [
                f"DPI set to {actual_xdpi} x {actual_ydpi} (wanted {xdpi} x {ydpi})",
            ]
            if maxdelta >= 10:
                messages.append("you may experience scaling problems, such as huge or small fonts, etc")
                messages.append("to fix this issue, try the dpi switch, or use a patched Xorg dummy driver")
                self.notify_dpi_warning("\n".join(messages))
            for i, message in enumerate(messages):
                log_fn("%s%s", ["", " "][i > 0], message)

    def mirror_client_monitor_layout(self) -> dict[int, Any]:
        if not self.randr:
            return {}
        from xpra.x11.bindings.randr import RandRBindings
        with xsync:
            if not RandRBindings().is_dummy16():
                raise RuntimeError("cannot match monitor layout without RandR 1.6")
        # if we have a single UI client,
        # see if we can emulate its monitor geometry exactly
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        log("%i sources=%s", len(sss), sss)
        if len(sss) != 1:
            return {}
        ss = sss[0]
        mdef = ss.get_monitor_definitions()
        if not mdef:
            return {}
        log(f"monitor definition from client {ss}: {mdef}")
        from xpra.common import adjust_monitor_refresh_rate
        mdef = adjust_monitor_refresh_rate(self.refresh_rate, mdef)
        log("refresh-rate adjusted using %s: %s", self.refresh_rate, mdef)
        with xlog:
            RandRBindings().set_crtc_config(mdef)
        return mdef

    def notify_dpi_warning(self, body: str) -> None:
        sources = tuple(self._server_sources.values())
        if len(sources) == 1:
            ss = sources[0]
            if first_time("DPI-warning-%s" % ss.uuid):
                sources[0].may_notify(NotificationID.DPI, "DPI Issue", body, icon_name="font")

    def set_dpi(self, xdpi: int, ydpi: int) -> None:
        """ overridden in the seamless server """

    ################################################################
    # force-ungrab:

    def _process_force_ungrab(self, proto, _packet: Packet) -> None:
        # ignore the window id: wid = packet[1]
        grablog("force ungrab from %s", proto)
        x11_ungrab()

    @staticmethod
    def x11_ungrab():
        x11_ungrab()

    # noinspection PyMethodMayBeStatic
    def init_packet_handlers(self) -> None:
        DisplayManager.init_packet_handlers(self)
        self.add_packets("force-ungrab", main_thread=True)
