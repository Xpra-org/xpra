# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

from xpra.server.server_base import ServerBase
from xpra.server.shadow_server_base import ShadowServerBase, RootWindowModel
from xpra.codecs.argb.argb import argb_to_rgb   #@UnresolvedImport

import Quartz.CoreGraphics as CG    #@UnresolvedImport

ALPHA = {
         CG.kCGImageAlphaNone                  : "AlphaNone",
         CG.kCGImageAlphaPremultipliedLast     : "PremultipliedLast",
         CG.kCGImageAlphaPremultipliedFirst    : "PremultipliedFirst",
         CG.kCGImageAlphaLast                  : "Last",
         CG.kCGImageAlphaFirst                 : "First",
         CG.kCGImageAlphaNoneSkipLast          : "SkipLast",
         CG.kCGImageAlphaNoneSkipFirst         : "SkipFirst",
   }


class OSXRootWindowModel(RootWindowModel):

    def OSXRootWindowModel(self, root_window):
        RootWindowModel.__init__(root_window)

    def get_rgb_rawdata(self, x, y, width, height):
        #region = CG.CGRectMake(0, 0, 100, 100)
        region = CG.CGRectInfinite
        image = CG.CGWindowListCreateImage(region,
                    CG.kCGWindowListOptionOnScreenOnly,
                    CG.kCGNullWindowID,
                    CG.kCGWindowImageDefault)
        width = CG.CGImageGetWidth(image)
        height = CG.CGImageGetHeight(image)        
        bpc = CG.CGImageGetBitsPerComponent(image)
        bpp = CG.CGImageGetBitsPerPixel(image)
        rowstride = CG.CGImageGetBytesPerRow(image)
        alpha = CG.CGImageGetAlphaInfo(image)
        alpha_str = ALPHA.get(alpha, alpha)
        log("OSXRootWindowModel.get_rgb_rawdata(..) image size: %sx%s, bpc=%s, bpp=%s, rowstride=%s, alpha=%s", width, height, bpc, bpp, rowstride, alpha_str)
        prov = CG.CGImageGetDataProvider(image)
        argb = CG.CGDataProviderCopyData(prov)
        rgba = argb_to_rgb(argb)
        return (0, 0, width, height, rgba, width*3)


class ShadowServer(ShadowServerBase, ServerBase):

    def __init__(self):
        #sanity check:
        image = CG.CGWindowListCreateImage(CG.CGRectInfinite,
                    CG.kCGWindowListOptionOnScreenOnly,
                    CG.kCGNullWindowID,
                    CG.kCGWindowImageDefault)
        if image is None:
            raise Exception("cannot grab test screenshot - maybe you need to run this command whilst logged in via the UI")
        ShadowServerBase.__init__(self)
        ServerBase.__init__(self)

    def init(self, sockets, opts):
        ServerBase.init(self, sockets, opts)
        self.keycodes = {}

    def makeRootWindowModel(self):
        return  OSXRootWindowModel(self.root)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        CG.CGWarpMouseCursorPosition(pointer)

    def get_keycode(self, ss, client_keycode, keyname, modifiers):
        #no mapping yet...
        return client_keycode

    def fake_key(self, keycode, press):
        log.info("fake_key(%s, %s)", keycode, press)
        e = CG.CGEventCreateKeyboardEvent(None, keycode, press)
        #CGEventSetFlags(keyPress, modifierFlags)
        #modifierFlags: kCGEventFlagMaskShift, ...
        CG.CGEventPost(CG.kCGSessionEventTap, e)
        CG.CFRelease(e)

    def _process_button_action(self, proto, packet):
        wid, button, pressed, pointer, modifiers = packet[1:6]
        log("process_button_action(%s, %s)", proto, packet)
        self._process_mouse_common(proto, wid, pointer, modifiers)
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

    def make_hello(self):
        capabilities = ServerBase.make_hello(self)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/osx-shadow"
        return capabilities

    def get_info(self, proto):
        info = ServerBase.get_info(self, proto)
        info["shadow"] = True
        info["server_type"] = "Python/gtk2/osx-shadow"
        return info
