# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.constants import NotificationID
from xpra.common import may_notify_client
from xpra.os_util import OSX
from xpra.util.str_fn import csv, pver
from xpra.util.env import osexpand
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

log = Logger("opengl")


class OpenGLClient(StubClientSubsystem):
    """
    Client-side OpenGL setup and state.

    Stays backend-agnostic: it asks the concrete client for its toolkit OpenGL
    window backend via `get_gl_client_window_module` and treats the returned
    window class as an opaque type to validate and instantiate. The opengl
    capabilities are reported by the `display` subsystem (which reads this
    subsystem's `properties`).

    Owns the "toggled" signal (via `SignalEmitter`): peers subscribe with
    `get_subsystem("opengl").connect("toggled", handler)` to react to opengl
    rendering being turned on/off (ie: the gtk3 client re-creates its windows).
    """
    __slots__ = (
        "GLClientWindowClass", "client_supports", "enabled", "force", "max_viewport_dims", "properties",
        "texture_size_limit",
    )
    PREFIX = "opengl"
    __signals__ = ["toggled"]

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.enabled: bool = False
        self.properties: dict[str, Any] = {}
        self.client_supports: bool = False
        self.force: bool = False
        self.texture_size_limit: int = 0
        self.max_viewport_dims: tuple[int, int] = (0, 0)
        # the (backend-specific) OpenGL window class, obtained from the client
        # via `get_gl_client_window_module` and held here as an opaque type:
        self.GLClientWindowClass: type | None = None

    def get_info(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "supported": self.client_supports,
            "props": self.properties,
        }

    def toggle_opengl(self, *_args) -> None:
        self.enabled = not self.enabled
        log("toggle_opengl() enabled=%s", self.enabled)
        # let the client re-create its windows for the new rendering mode:
        self.emit("toggled")

    def init_opengl(self, enable_opengl: str) -> None:
        log(f"init_opengl({enable_opengl})")
        # enable_opengl can be True, False, force, probe-failed, probe-success, or None (auto-detect)
        # ie: "on:native,gtk", "auto", "no"
        # ie: "probe-failed:SIGSEGV"
        # ie: "probe-success"
        parts = enable_opengl.split(":", 1)
        enable_option = parts[0].lower()  # ie: "on"
        log(f"init_opengl: enable_option={enable_option}")
        if enable_option in ("probe-failed", "probe-error", "probe-crash", "probe-warning", "probe-disabled"):
            msg = enable_option.replace("-", " ")
            if len(parts) > 1 and any(len(x) for x in parts[1:]):
                msg += ": %s" % csv(parts[1:])
            self.properties["info"] = "disabled, %s" % msg
            if enable_option != "probe-disabled":
                self.opengl_setup_failure(body=msg)
            return
        if enable_option in FALSE_OPTIONS:
            self.properties["info"] = "disabled by configuration"
            return
        warnings = []
        self.properties["info"] = ""
        if enable_option == "force":
            self.force = True
        elif enable_option != "probe-success":
            from xpra.platform.gui import gl_check as platform_gl_check
            log("checking with %s", platform_gl_check)
            warning = platform_gl_check()
            log("%s()=%s", platform_gl_check, warning)
            if warning:
                warnings.append(warning)

        if warnings:
            if enable_option in ("", "auto"):
                log.warn("OpenGL disabled:")
                for warning in warnings:
                    log.warn(" %s", warning)
                self.properties["info"] = "disabled: %s" % csv(warnings)
                return
            if enable_option == "probe-success":
                log.warn("OpenGL enabled, despite some warnings:")
            else:
                log.warn("OpenGL safety warning (enabled at your own risk):")
            for warning in warnings:
                log.warn(" %s", warning)
            self.properties["info"] = "enabled despite: %s" % csv(warnings)
        try:
            from xpra.opengl.window import test_gl_client_window
            # ask the concrete client for its (toolkit-specific) OpenGL window backend:
            self.properties, gl_client_window_module = self.client.get_gl_client_window_module(enable_opengl)
            if not gl_client_window_module:
                log.warn("Warning: no OpenGL backend module found")
                self.client_supports = False
                self.properties["info"] = "disabled: no module found"
                return
            if self.properties.get("nocheck"):
                log.info("OpenGL enabled, checks skipped")
                return
            log("init_opengl: found props %s", self.properties)
            self.GLClientWindowClass = gl_client_window_module.GLClientWindow
            self.client_supports = True
            # only enable opengl by default if force-enabled or if safe to do so:
            enabled_by_option = enable_option in (list(TRUE_OPTIONS) + ["auto", "nocheck"])
            self.enabled = self.force or enabled_by_option or self.properties.get("safe", False)
            self.texture_size_limit = self.properties.get("texture-size-limit", 16 * 1024)
            dims = self.texture_size_limit, self.texture_size_limit
            self.max_viewport_dims = self.properties.get("max-viewport-dims", dims)
            renderer = self.properties.get("renderer", "unknown")
            parts = renderer.split("(")
            if len(parts) > 1 and len(parts[0]) > 10:
                renderer = parts[0].strip()
            driver_info = renderer or self.properties.get("vendor") or "unknown card"

            from xpra.opengl.check import MIN_SIZE
            if min(self.max_viewport_dims) < MIN_SIZE:
                self.glinit_warn("the maximum viewport size is too low: %s" % (self.max_viewport_dims,))
            if self.texture_size_limit < MIN_SIZE:
                self.glinit_warn("the texture size limit is too low: %s" % (self.texture_size_limit,))
            if driver_info.startswith("SVGA3D") and os.environ.get("WAYLAND_DISPLAY"):
                self.glinit_warn("SVGA3D driver is buggy under Wayland")
            # `max_window_size`/`pixel_depth` are owned by the `window` subsystem:
            window = self.get_subsystem("window")
            max_window_size = window.max_window_size if window else (0, 0)
            pixel_depth = window.pixel_depth if window else 0
            self.GLClientWindowClass.MAX_VIEWPORT_DIMS = self.max_viewport_dims
            self.GLClientWindowClass.MAX_BACKING_DIMS = self.texture_size_limit, self.texture_size_limit
            log("OpenGL: enabled=%s, texture-size-limit=%s, max-window-size=%s",
                self.enabled, self.texture_size_limit, max_window_size)

            if self.enabled:
                self.validate_texture_size()
            if self.enabled and enable_opengl != "probe-success" and not self.force:
                draw_result = test_gl_client_window(self.GLClientWindowClass,
                                                    max_window_size=max_window_size,
                                                    pixel_depth=pixel_depth)
                if not draw_result.get("success", False):
                    self.glinit_error("OpenGL test rendering failed:",
                                      draw_result.get("message", "") or "unknown error")
                    return
                log(f"OpenGL test rendering succeeded: {draw_result}")
            if self.enabled:
                glvstr = ".".join(str(v) for v in self.properties.get("opengl", ()))
                log.info(f"OpenGL {glvstr} enabled on {driver_info!r}")
                module = self.properties.get("module", "unknown")
                backend = self.properties.get("backend", "unknown")
                log.info(f" using {module} {backend} backend")
                log.info(" zerocopy is %s", ["not available", "available"][self.properties.get("zerocopy", 0)])
                # don't try to handle video dimensions bigger than this
                # (`video_max_size` is owned by the `encoding` subsystem):
                mvs = min(8192, self.texture_size_limit)
                if enc := self.get_subsystem("encoding"):
                    enc.video_max_size = (mvs, mvs)
            elif self.client_supports:
                log(f"OpenGL supported on {driver_info!r}, but not enabled")
            self.properties["enabled"] = self.enabled
            if self.enabled and not warnings and OSX:
                # non-opengl is slow on MacOS:
                self.force = True
        except ImportError as e:
            log(f"init_opengl({enable_opengl})", exc_info=True)
            self.glinit_error("OpenGL accelerated rendering is not available:", e)
        except RuntimeError as e:
            log(f"init_opengl({enable_opengl})", exc_info=True)
            self.glinit_error("OpenGL support could not be enabled on this hardware:", e)
        except Exception as e:
            log(f"init_opengl({enable_opengl})", exc_info=True)
            self.glinit_error("Error loading OpenGL support:", e)

    def glinit_error(self, msg: str, err) -> None:
        log("OpenGL initialization error", exc_info=True)
        self.GLClientWindowClass = None
        self.client_supports = False
        log.error("%s", msg)
        for x in str(err).split("\n"):
            log.error(" %s", x)
        self.properties["info"] = str(err)
        self.properties["enabled"] = False
        self.opengl_setup_failure(body=str(err))

    def glinit_warn(self, warning: str) -> None:
        if self.enabled and not self.force:
            self.enabled = False
            log.warn("Warning: OpenGL is disabled:")
        log.warn(" %s", warning)

    def validate_texture_size(self) -> None:
        if self.do_validate_texture_size():
            return
        limit = self.texture_size_limit
        # log at warn level if the limit is low:
        # (if we're likely to hit it - if the screen is as big or bigger)
        display = self.get_subsystem("display")
        w, h = display.get_root_size() if display else (0, 0)
        log_fn = log.info
        if w * 2 <= limit and h * 2 <= limit:
            log_fn = log.debug
        if w >= limit or h >= limit:
            log_fn = log.warn
        log_fn("Warning: OpenGL windows will be clamped to the maximum texture size %ix%i", limit, limit)
        glver = pver(self.properties.get("opengl", ""))
        renderer = self.properties.get("renderer", "unknown")
        log_fn(f" for OpenGL {glver} renderer {renderer!r}")

    def do_validate_texture_size(self) -> bool:
        window = self.get_subsystem("window")
        mww, mwh = window.max_window_size if window else (0, 0)
        lim = self.texture_size_limit
        if lim >= 16 * 1024:
            return True
        if mww > 0 and mww > lim:
            return False
        if mwh > 0 and mwh > lim:
            return False
        return True

    def opengl_setup_failure(self, summary="Xpra OpenGL GPU Acceleration Failure", body="") -> None:
        OK = "0"
        DISABLE = "1"

        def notify_callback(event, nid, action_id, *args):
            log("notify_callback(%s, %s, %s, %s)", event, nid, action_id, args)
            if event == "notification-close":
                return
            if event != "notification-action":
                log.warn(f"Warning: unexpected event {event}")
                return
            if nid != NotificationID.OPENGL:
                log.warn(f"Warning: unexpected notification id {nid}")
                return
            if action_id == DISABLE:
                from xpra.platform.paths import get_user_conf_dirs
                dirs = get_user_conf_dirs()
                for d in dirs:
                    conf_file = osexpand(os.path.join(d, "xpra.conf"))
                    try:
                        with open(conf_file, "a", encoding="latin1") as f:
                            f.write("\n")
                            f.write("# user chose to disable the opengl warning:\n")
                            f.write("opengl=nowarn\n")
                        log.info("OpenGL warning will be silenced from now on,")
                        log.info(" '%s' has been updated", conf_file)
                        break
                    except OSError:
                        log("failed to create / append to config file '%s'", conf_file, exc_info=True)

        def delayed_notify() -> None:
            if self.client.exit_code is not None:
                return
            if OSX:
                # don't bother logging an error on MacOS,
                # OpenGL is being deprecated
                log.info(summary)
                log.info(body)
                return
            actions = (OK, "OK", DISABLE, "Don't show this warning again")
            may_notify_client(self.client, NotificationID.OPENGL, summary, body, actions,
                              icon_name="opengl", callback=notify_callback)

        # wait for the main loop to run:
        self.timeout_add(2 * 1000, delayed_notify)
