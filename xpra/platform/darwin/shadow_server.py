# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

import Quartz.CoreGraphics as CG

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.str_fn import memoryview_to_bytes
from xpra.scripts.config import InitExit
from xpra.scripts.main import check_display
from xpra.exit_codes import ExitCode
from xpra.codecs.image import ImageWrapper
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.platform.darwin.keyboard_config import KeyboardConfig
from xpra.platform.darwin.pointer import click, move_pointer
from xpra.platform.darwin.gui import get_CG_imagewrapper, take_screenshot
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("shadow", "osx")

USE_TIMER = envbool("XPRA_OSX_SHADOW_USE_TIMER", False)
GSTREAMER = envbool("XPRA_SHADOW_GSTREAMER", True)

GSTREAMER_CAPTURE_ELEMENTS: Sequence[str] = ("avfvideosrc", )


def check_gstreamer() -> bool:
    if not GSTREAMER:
        return False
    from xpra.gstreamer.common import has_plugins, import_gst
    import_gst()
    return has_plugins("avfvideosrc")


SHADOW_OPTIONS = {
    "auto": lambda: True,
    "gstreamer": check_gstreamer,
}

ALPHA: dict[int, str] = {
    CG.kCGImageAlphaNone: "AlphaNone",
    CG.kCGImageAlphaPremultipliedLast: "PremultipliedLast",
    CG.kCGImageAlphaPremultipliedFirst: "PremultipliedFirst",
    CG.kCGImageAlphaLast: "Last",
    CG.kCGImageAlphaFirst: "First",
    CG.kCGImageAlphaNoneSkipLast: "SkipLast",
    CG.kCGImageAlphaNoneSkipFirst: "SkipFirst",
}

BTYPES = tuple((str, bytes, memoryview, bytearray))


# ensure that picture_encode can deal with pixels as NSCFData:
def patch_pixels_to_bytes() -> None:
    from CoreFoundation import CFDataGetBytes, CFDataGetLength

    def pixels_to_bytes(v):
        if isinstance(v, BTYPES):
            return memoryview_to_bytes(v)
        size = CFDataGetLength(v)
        return CFDataGetBytes(v, (0, size), None)

    from xpra.codecs import rgb_transform
    rgb_transform.pixels_to_bytes = pixels_to_bytes


class OSXRootCapture:

    def __repr__(self):
        return "OSXRootCapture"

    @staticmethod
    def get_type() -> str:
        return "CoreGraphics"

    @staticmethod
    def refresh() -> bool:
        return True

    def clean(self) -> None:
        """ nothing specific to do here on MacOS """

    @staticmethod
    def get_image(x, y, width, height) -> ImageWrapper:
        rect = (x, y, width, height)
        return get_CG_imagewrapper(rect)

    @staticmethod
    def get_info() -> dict[str, Any]:
        return {
            "type": "CoreGraphics",
        }

    @staticmethod
    def take_screenshot() -> tuple[int, int, str, int, bytes]:
        log("grabbing screenshot")
        return take_screenshot()


class ShadowServer(GTKShadowServerBase):

    def __init__(self, display: str, attrs: dict[str, str]):
        super().__init__(attrs)
        # sanity check:
        check_display()
        image = CG.CGWindowListCreateImage(CG.CGRectInfinite,
                                           CG.kCGWindowListOptionOnScreenOnly,
                                           CG.kCGNullWindowID,
                                           CG.kCGWindowImageDefault)
        if image is None:
            log("cannot grab test screenshot - maybe you need to run this command whilst logged in via the UI")
            raise InitExit(ExitCode.FAILURE,
                           "cannot grab pixels from the screen, make sure this command is launched from a GUI session")
        patch_pixels_to_bytes()
        self.refresh_count = 0
        self.refresh_rectangle_count = 0
        self.refresh_registered = False
        super().__init__(attrs)

    def init(self, opts) -> None:
        super().init(opts)
        # printing fails silently on OSX
        self.printing = False

    @staticmethod
    def get_keyboard_config(_props=None) -> KeyboardConfig:
        return KeyboardConfig()

    def make_tray_widget(self):
        from xpra.gtk.statusicon_tray import GTKStatusIconTray
        return GTKStatusIconTray(self, 0, self.tray, "Xpra Shadow Server",
                                 click_cb=self.tray_click_callback, mouseover_cb=None, exit_cb=self.tray_exit_callback)

    def setup_capture(self) -> OSXRootCapture:
        return OSXRootCapture()

    def screen_refresh_callback(self, count, rects, info) -> None:
        log("screen_refresh_callback%s mapped=%s", (count, rects, info), self.mapped)
        self.refresh_count += 1
        rlist = []
        for r in rects:
            if not isinstance(r, CG.CGRect):
                log.error("Error: invalid rectangle in refresh list: %s", r)
                continue
            self.refresh_rectangle_count += 1
            rlist.append((int(r.origin.x), int(r.origin.y), int(r.size.width), int(r.size.height)))
        # return quickly, and process the list copy via idle add:
        GLib.idle_add(self.do_screen_refresh, rlist)

    def do_screen_refresh(self, rlist: list) -> None:
        # TODO: improve damage method to handle lists directly:
        from xpra.util.rectangle import rectangle
        model_rects = {}
        for model in self._id_to_window.values():
            model_rects[model] = rectangle(*model.geometry)
        for x, y, w, h in rlist:
            for model, rect in model_rects.items():
                mrect = rect.intersection(x, y, w, h)
                # log("screen refresh intersection of %s and %24s: %s", model, (x, y, w, h), mrect)
                if mrect:
                    rx = mrect.x - rect.x
                    ry = mrect.y - rect.y
                    self.refresh_window_area(model, rx, ry, mrect.width, mrect.height, {"damage": True})

    def start_refresh(self, wid: int) -> None:
        # don't use the timer, get damage notifications:
        if wid not in self.mapped:
            self.mapped.append(wid)
        if self.refresh_registered:
            return
        if not USE_TIMER:
            err = CG.CGRegisterScreenRefreshCallback(self.screen_refresh_callback, None)
            log("CGRegisterScreenRefreshCallback(%s)=%s", self.screen_refresh_callback, err)
            if err == 0:
                self.refresh_registered = True
                return
            log.warn("Warning: CGRegisterScreenRefreshCallback failed with error %i", err)
            log.warn(" using fallback timer method")
        super().start_refresh(wid)

    def stop_refresh(self, wid: int) -> None:
        log("stop_refresh(%i) mapped=%s, timer=%s", wid, self.mapped, self.refresh_timer)
        # may stop the timer fallback:
        super().stop_refresh(wid)
        if self.refresh_registered and not self.mapped:
            try:
                err = CG.CGUnregisterScreenRefreshCallback(self.screen_refresh_callback, None)
                log("CGUnregisterScreenRefreshCallback(%s)=%s", self.screen_refresh_callback, err)
                if err:
                    log.warn(" unregistering the existing one returned %s", {0: "OK"}.get(err, err))
            except ValueError as e:
                log.warn("Error unregistering screen refresh callback:")
                log.warn(" %s", e)
            self.refresh_registered = False

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        if proto not in self._server_sources:
            return False
        assert wid in self._id_to_window
        x, y = pointer[:2]
        move_pointer(x, y)
        return True

    def do_process_button_action(self, proto, device_id: int, wid: int, button: int, pressed: bool, pointer, props):
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        pointer = self.process_mouse_common(proto, device_id, wid, pointer)
        if pointer:
            self.button_action(device_id, wid, pointer, button, pressed, props)

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        x, y = pos[:2]
        move_pointer(x, y)

    def button_action(self, device_id: int, wid: int, pointer, button: int, pressed: bool, props):
        x, y = pointer[:2]
        click(x, y, button, pressed)

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/MacOS-Shadow"
        return capabilities

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_threaded_info(proto, **kwargs)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/gtk2/osx-shadow"
        info.setdefault("damage", {}).update({
            "use-timer": USE_TIMER,
            "notifications": self.refresh_registered,
            "count": self.refresh_count,
            "rectangles": self.refresh_rectangle_count,
        })
        return info


def main() -> None:
    import sys
    from xpra.platform import program_context
    with program_context("MacOS Shadow Capture"):
        log.enable_debug()
        c = OSXRootCapture()
        x, y, w, h = list(int(sys.argv[x]) for x in range(1, 5))
        img = c.get_image(x, y, w, h)
        from PIL import Image
        i = Image.frombuffer("RGBA", (w, h), img.get_pixels(), "raw", "BGRA", img.get_rowstride())
        import time
        t = time.time()
        tstr = time.strftime("%H-%M-%S", time.localtime(t))
        filename = "./Capture-{}-{}.png".format((x, y, w, h), tstr)
        i.save(filename, "png")
        print("saved to {}".format(filename))


if __name__ == "__main__":
    main()
