# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.screen import log_screen_sizes
from xpra.util.str_fn import bytestostr
from xpra.util.env import OSEnvContext
from xpra.net.common import PacketType
from xpra.util.version import parse_version, dict_version_trim
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS
from xpra.common import get_refresh_rate_for_value, FULL_INFO
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("screen")
gllog = Logger("opengl")


def run_opengl_probe(cmd: list[str], env: dict[str, str], display_name: str):
    props: dict[str, Any] = {}
    try:
        # pylint: disable=import-outside-toplevel
        from subprocess import Popen, PIPE
        # we want the output so we can parse it:
        env["XPRA_REDIRECT_OUTPUT"] = "0"
        gllog(f"query_opengl() using {cmd=}, {env=}")
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, env=env)
        out, err = proc.communicate()
        gllog("out(%s)=%s", cmd, out)
        gllog("err(%s)=%s", cmd, err)
        if proc.returncode == 0:
            # parse output:
            for line in out.splitlines():
                parts = bytestostr(line).split("=")
                if len(parts) != 2:
                    continue
                k = parts[0].strip()
                v = parts[1].strip()
                if k in ("GLX", "GLU.version", "opengl", "pyopengl", "accelerate", "shading-language-version"):
                    props[k] = parse_version(v)
                else:
                    props[k] = v
            gllog("opengl props=%s", props)
            if props:
                glprops = typedict(props)
                if glprops.strget("success").lower() in TRUE_OPTIONS:
                    gllog.info(f"OpenGL is supported on display {display_name!r}")
                    renderer = glprops.strget("renderer").split(";")[0]
                    if renderer:
                        gllog.info(f" using {renderer!r} renderer")
                else:
                    gllog.info("OpenGL is not supported on this display")
                    probe_err = glprops.strget("error")
                    if probe_err:
                        gllog.info(f" {probe_err}")
            else:
                gllog.info("No OpenGL information available")
        else:
            props["error-details"] = bytestostr(err).strip("\n\r")
            error = "unknown error"
            for x in str(err).splitlines():
                if x.startswith("RuntimeError: "):
                    error = x[len("RuntimeError: "):]
                    break
                if x.startswith("ImportError: "):
                    error = x[len("ImportError: "):]
                    break
            props["error"] = error
            log.warn("Warning: OpenGL support check failed:")
            log.warn(f" {error}")
    except Exception as e:
        gllog("query_opengl()", exc_info=True)
        gllog.error("Error: OpenGL support check failed")
        gllog.error(f" {e!r}")
        props["error"] = str(e)
    gllog("OpenGL: %s", props)
    return props


class DisplayManager(StubServerMixin):
    """
    Mixin for servers that handle displays.
    """
    DEFAULT_REFRESH_RATE = 0
    PREFIX = "display"

    def __init__(self):
        self.randr = False
        self.bell = False
        self.default_dpi = 96
        self.bit_depth = 24
        self.dpi = 0
        self.xdpi = 0
        self.ydpi = 0
        self.antialias: dict[str, Any] = {}
        self.double_click_time = -1
        self.double_click_distance = -1, -1
        self.opengl = "no"
        self.opengl_props: dict[str, Any] = {}
        self.refresh_rate = "auto"
        self.original_desktop_display = None

    def init(self, opts) -> None:
        self.opengl = opts.opengl
        self.bell = opts.bell
        self.default_dpi = int(opts.dpi)
        self.bit_depth = self.get_display_bit_depth()
        self.refresh_rate = opts.refresh_rate

    def print_screen_info(self) -> None:
        display = os.environ.get("DISPLAY")
        if display and display.startswith(":"):
            extra = ""
            bit_depth = self.get_display_bit_depth()
            if bit_depth:
                extra = f" with {bit_depth} bit colors"
            log.info(f" connected to X11 display {display}{extra}")

    def get_display_bit_depth(self) -> int:
        return 0

    def get_refresh_rate_for_value(self, invalue) -> int:
        return get_refresh_rate_for_value(self.refresh_rate, invalue)

    def parse_hello(self, ss, caps, send_ui: bool):
        if send_ui:
            self.parse_screen_info(ss)

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        if not send_ui:
            return
        # a bit of explanation:
        # normally these things are synchronized using xsettings, which we handle already,
        # but non-posix clients have no such thing,
        # and we don't want to expose that as an interface
        # (it's not very nice, and it is very X11 specific)
        # also, clients may want to override what is in their xsettings..
        # so if the client specifies what it wants to use, we patch the xsettings with it
        # (the actual xsettings part is done in `update_all_server_settings` in the X11 specific subclasses)
        if share_count > 0:
            log.info("sharing with %s other client(s)", share_count)
            self.dpi = 0
            self.xdpi = 0
            self.ydpi = 0
            self.double_click_time = -1
            self.double_click_distance = -1, -1
            self.antialias = {}
        else:
            dpi_caps = c.get("dpi")
            if isinstance(dpi_caps, int):
                # legacy mode, ie: html5 client
                self.dpi = self.xpdi = self.ydpi = int(dpi_caps)
            else:
                tdpi = typedict(c.dictget("dpi") or {})
                self.dpi = tdpi.intget("", 0)
                self.xdpi = tdpi.intget("x", self.xdpi)
                self.ydpi = tdpi.intget("y", self.ydpi)
            self.double_click_time = c.intget("double_click.time", -1)
            self.double_click_distance = c.intpair("double_click.distance", (-1, -1))
            self.antialias = c.dictget("antialias", {})
        log("dpi=%s, dpi.x=%s, dpi.y=%s, antialias=%s",
            self.dpi, self.xdpi, self.ydpi, self.antialias)
        log("double-click time=%s, distance=%s", self.double_click_time, self.double_click_distance)
        # if we're not sharing, reset all the settings:
        reset = share_count == 0
        self.update_all_server_settings(reset)

    def last_client_exited(self) -> None:
        self.reset_icc_profile()

    def threaded_setup(self) -> None:
        self.opengl_props = self.query_opengl()

    def query_opengl(self) -> dict[str, Any]:
        props: dict[str, Any] = {}
        if self.opengl.lower() == "noprobe" or self.opengl.lower() in FALSE_OPTIONS:
            gllog("query_opengl() skipped because opengl=%s", self.opengl)
            return props
        with OSEnvContext(XPRA_VERIFY_MAIN_THREAD="0"):
            try:
                # import OpenGL directly
                import OpenGL
                assert OpenGL
                gllog("found pyopengl version %s", OpenGL.__version__)
                # this may trigger an `AttributeError` if libGLX / libOpenGL are not installed:
                from OpenGL import GL
                assert GL
                gllog("loaded `GL` bindings")
            except (ImportError, AttributeError) as e:
                return {
                    'error': f'OpenGL is not available: {e}',
                    'success': False,
                }
            try:
                from xpra.opengl import backing
                assert backing
            except ImportError:
                return {
                    'error': '`xpra.opengl` is not available',
                    'success': False,
                }
        from xpra.platform.paths import get_xpra_command
        cmd = self.get_full_child_command(get_xpra_command() + ["opengl", "--opengl=force"])
        return run_opengl_probe(cmd, self.get_child_env(), self.display_name)

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "bell": self.bell,
        }
        if "display" in source.wants:
            root_size = self.get_root_window_size()
            if root_size:
                caps |= {
                    "actual_desktop_size": root_size,
                    "root_window_size": root_size,
                    "desktop_size": self._get_desktop_size_capability(source, *root_size),
                }
        if FULL_INFO and self.opengl_props:
            caps["opengl"] = dict_version_trim(self.opengl_props)
        return caps

    def get_server_features(self, source) -> dict[str, Any]:
        features: dict[str, Any] = {}
        if source and "display" in source.wants:
            max_size = self.get_max_screen_size()
            if max_size:
                features["max_desktop_size"] = max_size
            display = os.environ.get("DISPLAY")
            if display:
                features["display"] = display
        return features

    def get_ui_info(self, proto, client_uuids=None, *args) -> dict[str, Any]:
        max_size = self.get_max_screen_size()
        if max_size:
            return {"server": {"max_desktop_size": max_size}}
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        i = {
            "randr": self.randr,
            "bell": self.bell,
            "double-click": {
                "time": self.double_click_time,
                "distance": self.double_click_distance,
            },
            "dpi": {
                "default": self.default_dpi,
                "value": self.dpi,
                "x": self.xdpi,
                "y": self.ydpi,
            },
            "antialias": self.antialias,
            "depth": self.bit_depth,
            "refresh-rate": self.refresh_rate,
        }
        if self.original_desktop_display:
            i["original-desktop-display"] = self.original_desktop_display
        if self.opengl_props:
            i["opengl"] = self.opengl_props
        return {
            "display": i,
        }

    def _process_set_bell(self, proto, packet: PacketType) -> None:
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_bell = bool(packet[1])

    ######################################################################
    # display / screen / root window:
    def set_screen_geometry_attributes(self, w: int, h: int) -> None:
        # by default, use the screen as desktop area:
        self.set_desktop_geometry_attributes(w, h)

    def set_desktop_geometry_attributes(self, w: int, h: int) -> None:
        self.calculate_desktops()
        self.calculate_workarea(w, h)
        self.set_desktop_geometry(w, h)

    def parse_screen_info(self, ss) -> tuple[int, int]:
        return self.do_parse_screen_info(ss, ss.desktop_size)

    def do_parse_screen_info(self, ss, desktop_size) -> tuple[int, int]:
        log("do_parse_screen_info%s", (ss, desktop_size))
        dw, dh = None, None
        if desktop_size:
            try:
                dw, dh = desktop_size
                log.info(" client root window size is %sx%s", dw, dh)
                if ss.screen_sizes:
                    log_screen_sizes(dw, dh, ss.screen_sizes)
            except Exception:
                dw, dh = None, None
        best = self.configure_best_screen_size()
        if not best:
            return desktop_size
        sw, sh = best
        # we will tell the client about the size chosen in the hello we send back,
        # so record this size as the current server desktop size to avoid change notifications:
        ss.desktop_size_server = sw, sh
        # prefer desktop size, fallback to screen size:
        w = dw or sw
        h = dh or sh
        # clamp to max supported:
        max_size = self.get_max_screen_size()
        if max_size:
            maxw, maxh = max_size
            w = min(w, maxw)
            h = min(h, maxh)
        self.set_desktop_geometry_attributes(w, h)
        self.set_icc_profile()
        self.apply_refresh_rate(ss)
        log("configure_best_screen_size()=%s", (w, h))
        return w, h

    def set_icc_profile(self) -> None:
        log("set_icc_profile() not implemented")

    def reset_icc_profile(self) -> None:
        log("reset_icc_profile() not implemented")

    def _monitors_changed(self, screen) -> None:
        self.do_screen_changed(screen)

    def _screen_size_changed(self, screen) -> None:
        self.do_screen_changed(screen)

    def do_screen_changed(self, screen) -> None:
        log("do_screen_changed(%s)", screen)
        # randr has resized the screen, tell the client (if it supports it)
        w, h = screen.get_width(), screen.get_height()
        log("new screen dimensions: %ix%i", w, h)
        self.set_screen_geometry_attributes(w, h)
        self.notify_screen_changed(screen)

    def notify_screen_changed(self, screen) -> None:
        GLib.idle_add(self.send_updated_screen_size)

    def get_root_window_size(self) -> tuple[int, int]:
        raise NotImplementedError()

    def send_updated_screen_size(self) -> None:
        root_size = self.get_root_window_size()
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
        for ss in self._server_sources.values():
            if ss.updated_desktop_size(root_w, root_h, max_w, max_h):
                count += 1
        if count > 0:
            log.info("sent updated screen size to %s clients: %sx%s (max %sx%s)",
                     count, root_w, root_h, max_w, max_h)

    def get_max_screen_size(self) -> tuple[int, int]:
        return self.get_root_window_size()

    def _get_desktop_size_capability(self, server_source, root_w: int, root_h: int) -> tuple[int, int]:
        client_size = server_source.desktop_size
        log("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
        if not client_size:
            # client did not specify size, just return what we have
            return root_w, root_h
        client_w, client_h = client_size
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return w, h

    def configure_best_screen_size(self) -> tuple[int, int]:
        return self.get_root_window_size()

    def apply_refresh_rate(self, ss) -> int:
        rrate = self.get_client_refresh_rate(ss)
        log(f"apply_refresh_rate({ss}) rate={rrate}")
        if rrate > 0:
            self.set_window_refresh_rate(ss, rrate)
        return rrate

    def set_window_refresh_rate(self, ss, rrate: int):
        if hasattr(ss, "default_batch_config"):
            ss.default_batch_config.match_vrefresh(rrate)
        if hasattr(ss, "global_batch_config"):
            ss.global_batch_config.match_vrefresh(rrate)
        if hasattr(ss, "all_window_sources"):
            for window_source in ss.all_window_sources():
                bc = window_source.batch_config
                if bc:
                    bc.match_vrefresh(rrate)

    def get_client_refresh_rate(self, ss) -> int:
        vrefresh = []
        # use the refresh-rate value from the monitors
        # (value is pre-multiplied by 1000!)
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
            rrate //= 1000
        log("get_client_refresh_rate(%s)=%s (from %s)", ss, rrate, vrefresh)
        return rrate

    def _process_desktop_size(self, proto, packet: PacketType) -> None:
        log("new desktop size from %s: %s", proto, packet)
        ss = self.get_server_source(proto)
        if ss is None:
            return
        width, height = packet[1:3]
        ss.desktop_size = (width, height)
        if len(packet) >= 12:
            ss.set_monitors(packet[11])
        elif len(packet) >= 11:
            # fallback to the older global attribute:
            v = packet[10]
            if 0 < v < 240 and hasattr(ss, "vrefresh") and getattr(ss, "vrefresh") != v:
                ss.vrefresh = v
        if len(packet) >= 10:
            # added in 0.16 for scaled client displays:
            xdpi, ydpi = packet[8:10]
            if xdpi != self.xdpi or ydpi != self.ydpi:
                self.xdpi, self.ydpi = xdpi, ydpi
                log("new dpi: %ix%i", self.xdpi, self.ydpi)
                self.dpi = round((self.xdpi + self.ydpi) / 2)
                self.dpi_changed()
        if len(packet) >= 8:
            # added in 0.16 for scaled client displays:
            ss.desktop_size_unscaled = packet[6:8]
        if len(packet) >= 6:
            desktops, desktop_names = packet[4:6]
            ss.set_desktops(desktops, desktop_names)
            self.calculate_desktops()
        if len(packet) >= 4:
            ss.set_screen_sizes(packet[3])
        log("client requesting new size: %sx%s", width, height)
        self.set_screen_size(width, height)
        self.set_desktop_geometry_attributes(width, height)
        if len(packet) >= 4:
            log.info("received updated display dimensions")
            log.info("client display size is %sx%s", width, height)
            log_screen_sizes(width, height, ss.screen_sizes)
            self.calculate_workarea(width, height)
        self.apply_refresh_rate(ss)
        # ensures that DPI and antialias information gets reset:
        self.update_all_server_settings()

    def _process_configure_display(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if ss is None:
            return
        attrs = typedict(packet[1])
        desktop_size = attrs.intpair("desktop-size")
        if desktop_size:
            ss.desktop_size = desktop_size
        desktop_size_unscaled = attrs.intpair("desktop-size-unscaled")
        if desktop_size_unscaled:
            ss.desktop_size_unscaled = desktop_size_unscaled
        # vrefresh may be overridden in 'monitors' data:
        vrefresh = attrs.intget("vrefresh")
        if 0 < vrefresh < 240 and hasattr(ss, "vrefresh") and getattr(ss, "vrefresh") != vrefresh:
            ss.vrefresh = vrefresh
        monitors = attrs.dictget("monitors")
        if monitors:
            ss.set_monitors(monitors)
        if desktop_size:
            width, height = desktop_size
            log("client requesting new size: %sx%s", width, height)
            self.set_screen_size(width, height)
            log.info("received updated display dimensions")
            log.info(f"client display size is {width}x{height}")
            log_screen_sizes(width, height, ss.screen_sizes)
            self.calculate_workarea(width, height)
            self.set_desktop_geometry_attributes(width, height)
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
            self.calculate_desktops()
        iccd = attrs.dictget("icc")
        if iccd:
            iccd = typedict(iccd)
            ss.icc = iccd.get("global", ss.icc)
            ss.display_icc = iccd.get("display", ss.display_icc)
            self.set_icc_profile()
        self.apply_refresh_rate(ss)
        # ensures that DPI and antialias information gets reset:
        self.update_all_server_settings()

    def dpi_changed(self) -> None:
        """
        The x11 servers override this method
        to also update the XSettings.
        """

    def calculate_desktops(self):
        """ seamless servers can update the desktops """

    def calculate_workarea(self, w: int, h: int):
        raise NotImplementedError()

    def set_workarea(self, workarea) -> None:
        pass

    ######################################################################
    # screenshots:
    def _process_screenshot(self, proto, _packet: PacketType) -> None:
        packet = self.make_screenshot_packet()
        ss = self.get_server_source(proto)
        if packet and ss:
            ss.send(*packet)

    def make_screenshot_packet(self):
        with log.trap_error("Error making screenshot packet"):
            return self.do_make_screenshot_packet()

    def do_make_screenshot_packet(self):
        raise NotImplementedError("no screenshot capability in %s" % type(self))

    def send_screenshot(self, proto) -> None:
        # this is a screenshot request, handle it and disconnect
        try:
            packet = self.make_screenshot_packet()
            if not packet:
                self.send_disconnect(proto, "screenshot failed")
                return
            proto.send_now(packet)
            GLib.timeout_add(5 * 1000, self.send_disconnect, proto, "screenshot sent")
        except Exception as e:
            log.error("failed to capture screenshot", exc_info=True)
            self.send_disconnect(proto, "screenshot failed: %s" % e)

    def init_packet_handlers(self) -> None:
        self.add_packets("set-bell", "desktop_size", "configure-display", "screenshot", main_thread=True)
