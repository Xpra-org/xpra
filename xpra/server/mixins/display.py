# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Tuple, Any

from xpra.util import engs, log_screen_sizes, typedict
from xpra.os_util import bytestostr, is_Wayland
from xpra.net.common import PacketType
from xpra.version_util import parse_version, dict_version_trim
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS
from xpra.common import get_refresh_rate_for_value, FULL_INFO
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("screen")
gllog = Logger("opengl")


class DisplayManager(StubServerMixin):
    """
    Mixin for servers that handle displays.
    """
    DEFAULT_REFRESH_RATE = 0

    def __init__(self):
        self.randr = False
        self.bell = False
        self.cursors = False
        self.default_dpi = 96
        self.bit_depth = 24
        self.dpi = 0
        self.xdpi = 0
        self.ydpi = 0
        self.antialias : Dict[str,Any] = {}
        self.cursor_size = 0
        self.double_click_time  = -1
        self.double_click_distance = -1, -1
        self.opengl = "no"
        self.opengl_props : Dict[str,Any] = {}
        self.refresh_rate = "auto"

    def init(self, opts) -> None:
        self.opengl = opts.opengl
        self.bell = opts.bell
        self.cursors = opts.cursors
        self.default_dpi = int(opts.dpi)
        self.bit_depth = self.get_display_bit_depth()
        self.refresh_rate = opts.refresh_rate

    def get_display_bit_depth(self) -> int:
        return 0


    def get_refresh_rate_for_value(self, invalue) -> int:
        return get_refresh_rate_for_value(self.refresh_rate, invalue)

    def parse_hello(self, ss, caps, send_ui:bool):
        if send_ui:
            self.parse_screen_info(ss)


    def last_client_exited(self) -> None:
        self.reset_icc_profile()


    def threaded_setup(self) -> None:
        self.opengl_props = self.query_opengl()


    def query_opengl(self) -> Dict[str,Any]:
        props : Dict[str,Any] = {}
        if self.opengl.lower()=="noprobe" or self.opengl.lower() in FALSE_OPTIONS:
            gllog("query_opengl() skipped because opengl=%s", self.opengl)
            return props
        if is_Wayland():
            gllog("query_opengl() skipped on wayland")
            return props
        try:
            # pylint: disable=import-outside-toplevel
            from subprocess import Popen, PIPE
            from xpra.platform.paths import get_xpra_command
            cmd = self.get_full_child_command(get_xpra_command()+["opengl", "--opengl=yes"])
            env = self.get_child_env()
            #we want the output so we can parse it:
            env["XPRA_REDIRECT_OUTPUT"] = "0"
            proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, env=env)
            out,err = proc.communicate()
            gllog("out(%s)=%s", cmd, out)
            gllog("err(%s)=%s", cmd, err)
            if proc.returncode==0:
                #parse output:
                for line in out.splitlines():
                    parts = bytestostr(line).split("=")
                    if len(parts)!=2:
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
                    if glprops.strget("success", "").lower() in TRUE_OPTIONS:
                        gllog.info(f"OpenGL is supported on display {self.display_name!r}")
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


    def get_caps(self, source)  -> Dict[str,Any]:
        caps : Dict[str,Any] = {
            "bell"          : self.bell,
            "cursors"       : self.cursors,
            }
        root_size = self.get_root_window_size()
        if root_size:
            caps["desktop_size"] = self._get_desktop_size_capability(source, *root_size)
        if FULL_INFO and self.opengl_props:
            caps["opengl"] = dict_version_trim(self.opengl_props)
        return caps

    def get_info(self, _proto) -> Dict[str,Any]:
        i = {
                "randr" : self.randr,
                "bell"  : self.bell,
                "cursors" : {
                    ""      : self.cursors,
                    "size"  : self.cursor_size,
                    },
                "double-click"  : {
                    "time"      : self.double_click_time,
                    "distance"  : self.double_click_distance,
                    },
                "dpi" : {
                    "default"   : self.default_dpi,
                    "value"     : self.dpi,
                    "x"         : self.xdpi,
                    "y"         : self.ydpi,
                    },
                "antialias" : self.antialias,
                "depth" : self.bit_depth,
                "refresh-rate"  : self.refresh_rate,
                }
        if self.opengl_props:
            i["opengl"] = self.opengl_props
        return {
            "display": i,
            }


    def _process_set_cursors(self, proto, packet : PacketType) -> None:
        assert self.cursors, "cannot toggle send_cursors: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_cursors = bool(packet[1])

    def _process_set_bell(self, proto, packet : PacketType) -> None:
        assert self.bell, "cannot toggle send_bell: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_bell = bool(packet[1])


    ######################################################################
    # display / screen / root window:
    def set_screen_geometry_attributes(self, w:int, h:int) -> None:
        #by default, use the screen as desktop area:
        self.set_desktop_geometry_attributes(w, h)

    def set_desktop_geometry_attributes(self, w:int, h:int) -> None:
        self.calculate_desktops()
        self.calculate_workarea(w, h)
        self.set_desktop_geometry(w, h)


    def parse_screen_info(self, ss) -> Tuple[int,int]:
        return self.do_parse_screen_info(ss, ss.desktop_size)

    def do_parse_screen_info(self, ss, desktop_size) -> Tuple[int,int]:
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
        #we will tell the client about the size chosen in the hello we send back,
        #so record this size as the current server desktop size to avoid change notifications:
        ss.desktop_size_server = sw, sh
        #prefer desktop size, fallback to screen size:
        w = dw or sw
        h = dh or sh
        #clamp to max supported:
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
        #randr has resized the screen, tell the client (if it supports it)
        w, h = screen.get_width(), screen.get_height()
        log("new screen dimensions: %ix%i", w, h)
        self.set_screen_geometry_attributes(w, h)
        self.idle_add(self.send_updated_screen_size)

    def get_root_window_size(self) -> Tuple[int,int]:
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
                count +=1
        if count>0:
            log.info("sent updated screen size to %s client%s: %sx%s (max %sx%s)",
                     count, engs(count), root_w, root_h, max_w, max_h)

    def get_max_screen_size(self) -> Tuple[int,int]:
        return self.get_root_window_size()

    def _get_desktop_size_capability(self, server_source, root_w:int, root_h:int) -> Tuple[int,int]:
        client_size = server_source.desktop_size
        log("client resolution is %s, current server resolution is %sx%s", client_size, root_w, root_h)
        if not client_size:
            #client did not specify size, just return what we have
            return root_w, root_h
        client_w, client_h = client_size
        w = min(client_w, root_w)
        h = min(client_h, root_h)
        return w, h

    def configure_best_screen_size(self) -> Tuple[int,int]:
        return self.get_root_window_size()


    def apply_refresh_rate(self, ss) -> int:
        rrate = self.get_client_refresh_rate(ss)
        if rrate>0:
            self.set_window_refresh_rate(ss, rrate)
        return rrate

    def set_window_refresh_rate(self, ss, rrate:int):
        if hasattr(ss, "all_window_sources"):
            for window_source in ss.all_window_sources():
                bc = window_source.batch_config
                if bc:
                    bc.match_vrefresh(rrate)

    def get_client_refresh_rate(self, ss) -> int:
        vrefresh = []
        #use the refresh-rate value from the monitors
        #(value is pre-multiplied by 1000!)
        if ss.monitors:
            for mdef in ss.monitors.values():
                v = mdef.get("refresh-rate", 0)
                if v:
                    vrefresh.append(v)
        if not vrefresh and getattr(ss, "vrefresh", 0)>0:
            vrefresh.append(ss.vrefresh*1000)
        if not vrefresh:
            vrefresh.append(self.DEFAULT_REFRESH_RATE)
        rrate = 0
        if vrefresh:
            rrate = min(vrefresh)
            if self.refresh_rate:
                rrate = get_refresh_rate_for_value(self.refresh_rate, rrate)
            rrate //= 1000
        log("get_client_refresh_rate(%s)=%s (from %s)", ss, rrate, vrefresh)
        return rrate

    def _process_desktop_size(self, proto, packet : PacketType) -> None:
        log("new desktop size from %s: %s", proto, packet)
        ss = self.get_server_source(proto)
        if ss is None:
            return
        width, height = packet[1:3]
        ss.desktop_size = (width, height)
        if len(packet)>=12:
            ss.set_monitors(packet[11])
        elif len(packet)>=11:
            #fallback to the older global attribute:
            v = packet[10]
            if 0<v<240 and hasattr(ss, "vrefresh") and getattr(ss, "vrefresh")!=v:
                ss.vrefresh = v
        if len(packet)>=10:
            #added in 0.16 for scaled client displays:
            xdpi, ydpi = packet[8:10]
            if xdpi!=self.xdpi or ydpi!=self.ydpi:
                self.xdpi, self.ydpi = xdpi, ydpi
                log("new dpi: %ix%i", self.xdpi, self.ydpi)
                self.dpi = round((self.xdpi + self.ydpi)/2)
                self.dpi_changed()
        if len(packet)>=8:
            #added in 0.16 for scaled client displays:
            ss.desktop_size_unscaled = packet[6:8]
        if len(packet)>=6:
            desktops, desktop_names = packet[4:6]
            ss.set_desktops(desktops, desktop_names)
            self.calculate_desktops()
        if len(packet)>=4:
            ss.set_screen_sizes(packet[3])
        bigger = ss.screen_resize_bigger
        log("client requesting new size: %sx%s (bigger=%s)", width, height, bigger)
        self.set_screen_size(width, height, bigger)
        if len(packet)>=4:
            log.info("received updated display dimensions")
            log.info("client display size is %sx%s",
                     width, height)
            log_screen_sizes(width, height, ss.screen_sizes)
            self.calculate_workarea(width, height)
        self.apply_refresh_rate(ss)
        #ensures that DPI and antialias information gets reset:
        self.update_all_server_settings()

    def _process_configure_display(self, proto, packet : PacketType) -> None:
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
        #vrefresh may be overridden in 'monitors' data:
        vrefresh = attrs.intget("vrefresh")
        if 0<vrefresh<240 and hasattr(ss, "vrefresh") and getattr(ss, "vrefresh")!=vrefresh:
            ss.vrefresh = vrefresh
        monitors = attrs.dictget("monitors")
        if monitors:
            ss.set_monitors(monitors)
        if desktop_size:
            bigger = ss.screen_resize_bigger
            width, height = desktop_size
            log("client requesting new size: %sx%s (bigger=%s)", width, height, bigger)
            self.set_screen_size(width, height, bigger)
            log.info("received updated display dimensions")
            log.info(f"client display size is {width}x{height}")
            log_screen_sizes(width, height, ss.screen_sizes)
            self.calculate_workarea(width, height)
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
        if dpix and dpiy and (dpix!=self.xdpi or dpiy!=self.ydpi):
            self.xdpi, self.ydpi = dpix, dpiy
            log("new dpi: %ix%i", dpix, dpiy)
            self.dpi = round((dpix + dpiy)/2)
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
        #ensures that DPI and antialias information gets reset:
        self.update_all_server_settings()


    def dpi_changed(self) -> None:
        """
        The x11 servers override this method
        to also update the XSettings.
        """

    def calculate_desktops(self):
        """ seamless servers can update the desktops """

    def calculate_workarea(self, w:int, h:int):
        raise NotImplementedError()

    def set_workarea(self, workarea) -> None:
        pass


    ######################################################################
    # screenshots:
    def _process_screenshot(self, proto, _packet : PacketType) -> None:
        packet = self.make_screenshot_packet()
        ss = self.get_server_source(proto)
        if packet and ss:
            ss.send(*packet)

    def make_screenshot_packet(self):
        try:
            return self.do_make_screenshot_packet()
        except Exception:
            log.error("make_screenshot_packet()", exc_info=True)
            return None

    def do_make_screenshot_packet(self):
        raise NotImplementedError("no screenshot capability in %s" % type(self))

    def send_screenshot(self, proto) -> None:
        #this is a screenshot request, handle it and disconnect
        try:
            packet = self.make_screenshot_packet()
            if not packet:
                self.send_disconnect(proto, "screenshot failed")
                return
            proto.send_now(packet)
            self.timeout_add(5*1000, self.send_disconnect, proto, "screenshot sent")
        except Exception as e:
            log.error("failed to capture screenshot", exc_info=True)
            self.send_disconnect(proto, "screenshot failed: %s" % e)


    def init_packet_handlers(self) -> None:
        self.add_packet_handlers({
            "set-cursors"           : self._process_set_cursors,
            "set-bell"              : self._process_set_bell,
            "desktop_size"          : self._process_desktop_size,
            "configure-display"     : self._process_configure_display,
            "screenshot"            : self._process_screenshot,
            })
