# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("shadow", "osx")

from xpra.util import envbool
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.platform.darwin.keyboard_config import KeyboardConfig
from xpra.platform.darwin.gui import get_CG_imagewrapper, take_screenshot

import Quartz.CoreGraphics as CG    #@UnresolvedImport


USE_TIMER = envbool("XPRA_OSX_SHADOW_USE_TIMER", False)

ALPHA = {
         CG.kCGImageAlphaNone                  : "AlphaNone",
         CG.kCGImageAlphaPremultipliedLast     : "PremultipliedLast",
         CG.kCGImageAlphaPremultipliedFirst    : "PremultipliedFirst",
         CG.kCGImageAlphaLast                  : "Last",
         CG.kCGImageAlphaFirst                 : "First",
         CG.kCGImageAlphaNoneSkipLast          : "SkipLast",
         CG.kCGImageAlphaNoneSkipFirst         : "SkipFirst",
   }

#ensure that picture_encode can deal with pixels as NSCFData:
def patch_picture_encode():
    from CoreFoundation import CFDataGetBytes, CFDataGetLength  #@UnresolvedImport
    from xpra.os_util import memoryview_to_bytes, _buffer
    btypes = [x for x in (str, bytes, memoryview, _buffer, bytearray) if x is not None]
    def pixels_to_bytes(v):
        if type(v) in btypes:
            return memoryview_to_bytes(v)
        l = CFDataGetLength(v)
        return CFDataGetBytes(v, (0, l), None)
    from xpra.server import picture_encode
    picture_encode.pixels_to_bytes = pixels_to_bytes


class OSXRootCapture(object):

    def __repr__(self):
        return "OSXRootCapture"

    def refresh(self):
        return True

    def clean(self):
        pass

    def get_image(self, x, y, width, height):
        rect = (x, y, width, height)
        return get_CG_imagewrapper(rect)

    def get_info(self):
        return {}

    def take_screenshot(self):
        log("grabbing screenshot")
        return take_screenshot()


class ShadowServer(GTKShadowServerBase):

    def __init__(self):
        #sanity check:
        image = CG.CGWindowListCreateImage(CG.CGRectInfinite,
                    CG.kCGWindowListOptionOnScreenOnly,
                    CG.kCGNullWindowID,
                    CG.kCGWindowImageDefault)
        if image is None:
            from xpra.scripts.config import InitExit
            log("cannot grab test screenshot - maybe you need to run this command whilst logged in via the UI")
            raise InitExit(1, "cannot grab pixels from the screen, make sure this command is launched from a GUI session")
        patch_picture_encode()
        self.refresh_count = 0
        self.refresh_rectangle_count = 0
        self.refresh_registered = False
        GTKShadowServerBase.__init__(self)

    def init(self, opts):
        GTKShadowServerBase.init(self, opts)
        self.keycodes = {}
        #printing fails silently on OSX
        self.printing = False

    def get_keyboard_config(self, props):
        return KeyboardConfig()

    def make_tray_widget(self):
        from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray
        return GTKStatusIconTray(self, 0, self.tray, "Xpra Shadow Server", None, None, self.tray_click_callback, mouseover_cb=None, exit_cb=self.tray_exit_callback)


    def setup_capture(self):
        return OSXRootCapture()

    def screen_refresh_callback(self, count, rects, info):
        log("screen_refresh_callback%s mapped=%s", (count, rects, info), self.mapped)
        self.refresh_count += 1
        rlist = []
        for r in rects:
            if not isinstance(r, CG.CGRect):
                log.error("Error: invalid rectangle in refresh list: %s", r)
                continue
            self.refresh_rectangle_count += 1
            rlist.append((int(r.origin.x), int(r.origin.y), int(r.size.width), int(r.size.height)))
        #return quickly, and process the list copy via idle add:
        self.idle_add(self.do_screen_refresh, rlist)

    def do_screen_refresh(self, rlist):
        #TODO: improve damage method to handle lists directly:
        from xpra.server.window.region import rectangle     #@UnresolvedImport
        model_rects = {}
        for model in self._id_to_window.values():
            model_rects[model] = rectangle(*model.geometry)
        for x, y, w, h in rlist:
            for model, rect in model_rects.items():
                mrect = rect.intersection(x, y, w, h)
                #log("screen refresh intersection of %s and %24s: %s", model, (x, y, w, h), mrect)
                if mrect:
                    self._damage(model, mrect.x-rect.x, mrect.y-rect.y, mrect.width, mrect.height)

    def start_refresh(self, wid):
        #don't use the timer, get damage notifications:
        if wid not in self.mapped:
            self.mapped.append(wid)
        if self.refresh_registered:
            return
        if not USE_TIMER:
            err = CG.CGRegisterScreenRefreshCallback(self.screen_refresh_callback, None)
            log("CGRegisterScreenRefreshCallback(%s)=%s", self.screen_refresh_callback, err)
            if err==0:
                self.refresh_registered = True
                return
            else:
                log.warn("Warning: CGRegisterScreenRefreshCallback failed with error %i", err)
                log.warn(" using fallback timer method")
        GTKShadowServerBase.start_refresh(self, wid)

    def stop_refresh(self, wid):
        log("stop_refresh(%i) mapped=%s, timer=%s", wid, self.mapped, self.refresh_timer)
        #may stop the timer fallback:
        GTKShadowServerBase.stop_refresh(self, wid)
        if self.refresh_registered and not self.mapped:
            try:
                err = CG.CGUnregisterScreenRefreshCallback(self.screen_refresh_callback, None)
                log("CGUnregisterScreenRefreshCallback(%s)=%s", self.screen_refresh_callback, err)
                if err:
                    log.warn(" unregistering the existing one returned %s", {0 : "OK"}.get(err, err))
            except ValueError as e:
                log.warn("Error unregistering screen refresh callback:")
                log.warn(" %s", e)
            self.refresh_registered = False


    def do_process_mouse_common(self, proto, wid, pointer, *args):
        assert proto in self._server_sources
        assert wid in self._id_to_window
        CG.CGWarpMouseCursorPosition(pointer)
        return pointer

    def fake_key(self, keycode, press):
        e = CG.CGEventCreateKeyboardEvent(None, keycode, press)
        log("fake_key(%s, %s)", keycode, press)
        #CGEventSetFlags(keyPress, modifierFlags)
        #modifierFlags: kCGEventFlagMaskShift, ...
        CG.CGEventPost(CG.kCGSessionEventTap, e)
        #this causes crashes, don't do it!
        #CG.CFRelease(e)

    def do_process_button_action(self, proto, wid, button, pressed, pointer, modifiers, *args):
        self._update_modifiers(proto, wid, modifiers)
        pointer = self._process_mouse_common(proto, wid, pointer)
        if pointer:
            self.button_action(pointer, button, pressed, -1, *args)

    def button_action(self, pointer, button, pressed, _deviceid=-1, *args):
        if button<=3:
            #we should be using CGEventCreateMouseEvent
            #instead we clear previous clicks when a "higher" button is pressed... oh well
            args = []
            for i in range(button):
                args.append(i==(button-1) and pressed)
            log("CG.CGPostMouseEvent(%s, %s, %s, %s)", pointer, 1, button, args)
            CG.CGPostMouseEvent(pointer, 1, button, *args)
        else:
            if not pressed:
                #we don't simulate press/unpress
                #so just ignore unpressed events
                return
            wheel = (button-2)//2
            direction = 1-(((button-2) % 2)*2)
            args = []
            for i in range(wheel):
                if i!=(wheel-1):
                    args.append(0)
                else:
                    args.append(direction)
            log("CG.CGPostScrollWheelEvent(%s, %s)", wheel, args)
            CG.CGPostScrollWheelEvent(wheel, *args)

    def make_hello(self, source):
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/osx-shadow"
        return capabilities

    def get_info(self, proto, *_args):
        info = GTKServerBase.get_info(self, proto)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {})["type"] = "Python/gtk2/osx-shadow"
        info.setdefault("damage", {}).update({
                                              "use-timer"       : USE_TIMER,
                                              "notifications"   : self.refresh_registered,
                                              "count"           : self.refresh_count,
                                              "rectangles"      : self.refresh_rectangle_count,
                                              })
        return info


def main():
    import sys
    from xpra.platform import program_context
    with program_context("MacOS Shadow Capture"):
        log.enable_debug()
        c = OSXRootCapture()
        x, y, w, h = list(int(sys.argv[x]) for x in range(1,5))
        img = c.get_image(x, y, w, h)
        from PIL import Image
        i = Image.frombuffer("RGBA", (w, h), img.get_pixels(), "raw", "BGRA", img.get_rowstride())
        import time
        t = time.time()
        tstr = time.strftime("%H-%M-%S", time.localtime(t))
        filename = "./Capture-%s-%s.png" % ((x, y, w, h),tstr,)
        i.save(filename, "png")
        print("saved to %s" % (filename,))
        

if __name__ == "__main__":
    main()
