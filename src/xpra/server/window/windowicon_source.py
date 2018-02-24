# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import threading

from xpra.os_util import monotonic_time, BytesIOClass
from xpra.codecs.loader import get_codec
from xpra.net import compression
from xpra.util import envbool
from xpra.log import Logger

log = Logger("icon")


ARGB_ICONS = envbool("XPRA_ARGB_ICONS", True)
PNG_ICONS = envbool("XPRA_PNG_ICONS", True)

LOG_THEME_DEFAULT_ICONS = envbool("XPRA_LOG_THEME_DEFAULT_ICONS", False)
SAVE_WINDOW_ICONS = envbool("XPRA_SAVE_WINDOW_ICONS", False)


"""
Mixin for handling the sending of window icon pixels.
"""
class WindowIconSource(object):

    fallback_window_icon_surface = False

    def __init__(self, window_icon_encodings, icons_encoding_options):
        self.window_icon_encodings = window_icon_encodings
        self.icons_encoding_options = icons_encoding_options    #icon caps

        self.window_icon_data = None
        self.send_window_icon_timer = 0
        self.theme_default_icons = icons_encoding_options.strlistget("default.icons", [])
        self.window_icon_greedy = icons_encoding_options.boolget("greedy", False)
        self.window_icon_size = icons_encoding_options.intpair("size", (64, 64))
        self.window_icon_max_size = icons_encoding_options.intpair("max_size", self.window_icon_size)
        self.window_icon_max_size = max(self.window_icon_max_size[0], 16), max(self.window_icon_max_size[1], 16)
        self.window_icon_size = min(self.window_icon_size[0], self.window_icon_max_size[0]), min(self.window_icon_size[1], self.window_icon_max_size[1])
        self.window_icon_size = max(self.window_icon_size[0], 16), max(self.window_icon_size[1], 16)
        log("client icon settings: size=%s, max_size=%s", self.window_icon_size, self.window_icon_max_size)
        if LOG_THEME_DEFAULT_ICONS:
            log("theme_default_icons=%s", self.theme_default_icons)

    def cleanup(self):
        swit = self.send_window_icon_timer
        if swit:
            self.send_window_icon_timer = 0
            self.source_remove(swit)

    def get_info(self):
        idata = self.window_icon_data
        if not idata:
            return {}
        pixel_data, pixel_format, stride, w, h = idata
        return {
            "icon" : {
                "pixel_format"  : pixel_format,
                "width"         : w,
                "height"        : h,
                "stride"        : stride,
                "bytes"         : len(pixel_data),
                }
            }

    @staticmethod
    def get_fallback_window_icon_surface():
        if WindowIconSource.fallback_window_icon_surface is False:
            try:
                import cairo
                from xpra.platform.paths import get_icon_filename
                fn = get_icon_filename("xpra.png")
                log("get_fallback_window_icon_surface() icon filename=%s", fn)
                if os.path.exists(fn):
                    s = cairo.ImageSurface.create_from_png(fn)
            except Exception as e:
                log.warn("failed to get fallback icon: %s", e)
                s = None
            WindowIconSource.fallback_window_icon_surface = s
        return WindowIconSource.fallback_window_icon_surface

    def send_window_icon(self):
        assert self.ui_thread == threading.current_thread()
        if self.suspended:
            return
        #this runs in the UI thread
        surf = self.window.get_property("icon")
        log("send_window_icon window %s icon=%s", self.window, surf)
        if not surf:
            #FIXME: this is a bit dirty,
            #we figure out if the client is likely to have an icon for this wmclass already,
            #(assuming the window even has a 'class-instance'), and if not we send the default
            try:
                c_i = self.window.get_property("class-instance")
            except:
                c_i = None
            if c_i and len(c_i)==2:
                wm_class = c_i[0].encode("utf-8")
                if wm_class in self.theme_default_icons:
                    log("%s in client theme icons already (not sending default icon)", self.theme_default_icons)
                    return
                #try to load the icon for this class-instance from the theme:
                surf = self.window.get_default_window_icon()
                log("send_window_icon window %s using default window icon=%s", self.window, surf)
        if not surf:
            if not self.window_icon_greedy:
                return
            #"greedy": client does not set a default icon, so we must provide one every time
            #to make sure that the window icon does get set to something
            #(our icon is at least better than the window manager's default)
            if "default" in self.window_icon_encodings:
                #client will set the default itself,
                #send a mostly empty packet:
                packet = ("window-icon", self.wid, 0, 0, "default", "")
                log("queuing window icon update: %s", packet)
                #this is cheap, so don't use the encode thread:
                self.queue_packet(packet, wait_for_more=True)
                return
            surf = WindowIconSource.get_fallback_window_icon_surface()
            log("using fallback window icon")
        if surf:
            if hasattr(surf, "get_pixels"):
                #looks like a gdk.Pixbuf:
                self.window_icon_data = (surf.get_pixels(), "RGBA", surf.get_rowstride(), surf.get_width(), surf.get_height())
            else:
                #for debugging, save to a file so we can see it:
                #surf.write_to_png("S-%s-%s.png" % (self.wid, int(time.time())))
                #extract the data from the cairo surface
                import cairo
                assert surf.get_format() == cairo.FORMAT_ARGB32
                self.window_icon_data = (surf.get_data(), "BGRA", surf.get_stride(), surf.get_width(), surf.get_height())
            if not self.send_window_icon_timer:
                #call compress via the work queue
                #and delay sending it by a bit to allow basic icon batching:
                delay = max(50, int(self.batch_config.delay))
                log("send_window_icon() window=%s, wid=%s, compression scheduled in %sms", self.window, self.wid, delay)
                self.send_window_icon_timer = self.timeout_add(delay, self.call_in_encode_thread, True, self.compress_and_send_window_icon)

    def compress_and_send_window_icon(self):
        #this runs in the work queue
        self.send_window_icon_timer = 0
        idata = self.window_icon_data
        if not idata:
            return
        pixel_data, pixel_format, stride, w, h = idata
        PIL = get_codec("PIL")
        max_w, max_h = self.window_icon_max_size
        if stride!=w*4:
            #re-stride it (I don't think this ever fires?)
            pixel_data = b"".join(pixel_data[stride*y:stride*y+w*4] for y in range(h))
            stride = w*4
        #use png if supported and if "premult_argb32" is not supported by the client (ie: html5)
        #or if we must downscale it (bigger than what the client is willing to deal with),
        #or if we want to save window icons
        has_png = PIL and PNG_ICONS and ("png" in self.window_icon_encodings)
        has_premult = ARGB_ICONS and "premult_argb32" in self.window_icon_encodings
        use_png = has_png and (SAVE_WINDOW_ICONS or w>max_w or h>max_h or w*h>=1024 or (not has_premult) or (pixel_format!="BGRA"))
        log("compress_and_send_window_icon: %sx%s (max-size=%s, standard-size=%s), sending as png=%s, has_png=%s, has_premult=%s, pixel_format=%s", w, h, self.window_icon_max_size, self.window_icon_size, use_png, has_png, has_premult, pixel_format)
        if use_png:
            img = PIL.Image.frombuffer("RGBA", (w,h), pixel_data, "raw", pixel_format, 0, 1)
            if w>max_w or h>max_h:
                #scale the icon down to the size the client wants
                icon_w, icon_h = self.window_icon_size
                if float(w)/icon_w>=float(h)/icon_h:
                    h = min(max_h, h*icon_w//w)
                    w = icon_w
                else:
                    w = min(max_w, w*icon_h//h)
                    h = icon_h
                log("scaling window icon down to %sx%s", w, h)
                img = img.resize((w,h), PIL.Image.ANTIALIAS)
            output = BytesIOClass()
            img.save(output, 'PNG')
            compressed_data = output.getvalue()
            output.close()
            wrapper = compression.Compressed("png", compressed_data)
            if SAVE_WINDOW_ICONS:
                filename = "server-window-%i-icon-%i.png" % (self.wid, int(monotonic_time()))
                img.save(filename, 'PNG')
                log("server window icon saved to %s", filename)
        elif ("premult_argb32" in self.window_icon_encodings) and pixel_format=="BGRA":
            wrapper = self.compressed_wrapper("premult_argb32", str(pixel_data))
        else:
            log("cannot send window icon, supported encodings: %s", self.window_icon_encodings)
            return
        assert wrapper.datatype in ("premult_argb32", "png"), "invalid wrapper datatype %s" % wrapper.datatype
        packet = ("window-icon", self.wid, w, h, wrapper.datatype, wrapper)
        log("queuing window icon update: %s", packet)
        self.queue_packet(packet, wait_for_more=True)
