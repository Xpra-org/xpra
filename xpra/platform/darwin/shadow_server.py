# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

import Quartz.CoreGraphics as CG

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.str_fn import memoryview_to_bytes
from xpra.scripts.config import InitExit
from xpra.scripts.main import check_display
from xpra.exit_codes import ExitCode
from xpra.codecs.image import ImageWrapper
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.platform.darwin.gui import get_CG_imagewrapper, take_screenshot
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("shadow", "osx")

USE_TIMER = envbool("XPRA_OSX_SHADOW_USE_TIMER", False)
HIGHDPI = envbool("XPRA_AVFOUNDATION_HIGHDPI", False)
SHADOW_OPTIONS = {
    "auto": lambda: True,
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


class ShadowServer(ShadowServerBase):

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
        self.session_type = "macOS shadow"
        self.refresh_count = 0
        self.refresh_rectangle_count = 0
        self.refresh_registered = False
        # set when the AVFoundation streaming capture backend is in use
        # (push-based whole-frame capture) rather than the CoreGraphics
        # damage-callback backend:
        self._streaming = False
        self._stream_refresh_pending = False
        super().__init__(attrs)

    def get_display_subsystem_class(self) -> type:
        from xpra.platform.darwin.shadow_display import DarwinShadowDisplayManager
        return DarwinShadowDisplayManager

    def get_keyboard_subsystem_class(self) -> type:
        from xpra.platform.darwin.shadow_keyboard import DarwinShadowKeyboardManager
        return DarwinShadowKeyboardManager

    def get_pointer_subsystem_class(self) -> type:
        from xpra.platform.darwin.shadow_pointer import DarwinShadowPointerManager
        return DarwinShadowPointerManager

    def get_cursor_subsystem_class(self) -> type:
        from xpra.platform.darwin.shadow_cursor import DarwinShadowCursorManager
        return DarwinShadowCursorManager

    def init(self, opts) -> None:
        super().init(opts)
        # printing fails silently on OSX
        self.printing = False

    def make_tray_widget(self):
        from xpra.gtk.statusicon_tray import GTKStatusIconTray
        return GTKStatusIconTray(self, 0, self.tray, "Xpra Shadow Server",
                                 click_cb=self.tray_click_callback, mouseover_cb=None, exit_cb=self.tray_exit_callback)

    def setup_capture(self):
        # AVCaptureScreenInput delivers whole frames (no damage rectangles), so it
        # suits full-frame streaming; use it for "stream" encoding and for the
        # default multi-window shadow mode. Otherwise keep the CoreGraphics
        # damage-callback backend.
        encoding_subsystem = self.get_subsystem("encoding")
        encoding = getattr(encoding_subsystem, "encoding", "") if encoding_subsystem else ""
        if encoding == "stream" or self.multi_window:
            from xpra.platform.darwin.avfoundation_screen import AVFShadowCapture
            self._streaming = True
            return AVFShadowCapture(on_frame=self._screen_frame, get_fps=self._capture_fps)
        self._streaming = False
        return OSXRootCapture()

    def _capture_fps(self) -> int:
        delay = self.refresh_delay or (1000 // self.DEFAULT_REFRESH_RATE)
        return max(1, round(1000 / max(1, delay)))

    def _screen_frame(self) -> None:
        # called from the capture dispatch queue (a background thread):
        # coalesce bursts of frames into a single main-loop refresh.
        if not self._stream_refresh_pending:
            self._stream_refresh_pending = True
            GLib.idle_add(self._do_stream_refresh)

    def _do_stream_refresh(self) -> bool:
        self._stream_refresh_pending = False
        if self.mapped:
            self.refresh_windows()
        return False

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
        for model in self.subsystems["window"].models():
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
        if self._streaming:
            # push-based capture: refreshes are driven by frame delivery
            if self.capture:
                self.capture.start()
            self.start_poll_pointer()
            return
        # the CoreGraphics backend drives screen refreshes via damage callbacks,
        # but we still need to poll for the pointer position and cursor pixels:
        self.start_poll_pointer()
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
        if self._streaming:
            try:
                self.mapped.remove(wid)
            except ValueError:
                pass
            if not self.mapped:
                if self.capture:
                    self.capture.stop()
                self.cancel_poll_pointer()
            return
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

    def set_refresh_delay(self, v: int) -> None:
        super().set_refresh_delay(v)
        if self._streaming and self.capture:
            self.capture.set_fps(self._capture_fps())

    def get_shadow_monitors(self) -> list[tuple[str, int, int, int, int, int]]:
        monitors = super().get_shadow_monitors()
        if not (self._streaming and HIGHDPI):
            return monitors
        # high-dpi: the AVFoundation capture delivers native pixels, so size the
        # window models in pixels too by scaling each monitor by its backing factor:
        scaled = []
        for plug_name, x, y, width, height, scale_factor in monitors:
            sf = scale_factor or 1
            scaled.append((plug_name, round(x * sf), round(y * sf),
                           round(width * sf), round(height * sf), scale_factor))
        return scaled

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        info = super().get_threaded_info(proto, **kwargs)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("damage", {}).update({
            "streaming": self._streaming,
            "use-timer": USE_TIMER,
            "notifications": self.refresh_registered,
            "count": self.refresh_count,
            "rectangles": self.refresh_rectangle_count,
        })
        if self._streaming and self.capture:
            info["damage"]["backend"] = self.capture.get_type()
        return info


def main() -> None:
    import sys
    from xpra.platform import program_context
    from xpra.codecs.image import to_pil_encoding
    with program_context("MacOS Shadow Capture"):
        log.enable_debug()
        c = OSXRootCapture()
        x, y, w, h = list(int(sys.argv[x]) for x in range(1, 5))
        image = c.get_image(x, y, w, h)
        data = to_pil_encoding(image, "png")
        import time
        t = time.time()
        tstr = time.strftime("%H-%M-%S", time.localtime(t))
        filename = "./Capture-{}-{}.png".format((x, y, w, h), tstr)
        with open(filename, "wb") as f:
            f.write(data)
        print(f"saved to {filename!r}")


if __name__ == "__main__":
    main()
