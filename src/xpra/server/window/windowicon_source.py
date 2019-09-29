# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

import os
import threading
from io import BytesIO
from PIL import Image

from xpra.os_util import monotonic_time, load_binary_file, memoryview_to_bytes
from xpra.net import compression
from xpra.util import envbool, envint, csv
from xpra.log import Logger

log = Logger("icon")

ARGB_ICONS = envbool("XPRA_ARGB_ICONS", True)
PNG_ICONS = envbool("XPRA_PNG_ICONS", True)
DEFAULT_ICONS = envbool("XPRA_DEFAULT_ICONS", True)

LOG_THEME_DEFAULT_ICONS = envbool("XPRA_LOG_THEME_DEFAULT_ICONS", False)
SAVE_WINDOW_ICONS = envbool("XPRA_SAVE_WINDOW_ICONS", False)
MAX_ARGB_PIXELS = envint("XPRA_MAX_ARGB_PIXELS", 1024)


"""
Mixin for handling the sending of window icon pixels.
"""
class WindowIconSource(object):

    fallback_window_icon = False

    def __init__(self, window_icon_encodings, icons_encoding_options):
        self.window_icon_encodings = window_icon_encodings
        self.icons_encoding_options = icons_encoding_options    #icon caps

        self.has_png = PNG_ICONS and ("png" in self.window_icon_encodings)
        self.has_default = DEFAULT_ICONS and ("default" in self.window_icon_encodings)
        log("WindowIconSource(%s, %s) has_png=%s",
            window_icon_encodings, icons_encoding_options, self.has_png)

        self.window_icon_data = None
        self.send_window_icon_timer = 0
        self.theme_default_icons = icons_encoding_options.strlistget("default.icons", [])
        self.window_icon_greedy = icons_encoding_options.boolget("greedy", False)
        self.window_icon_size = icons_encoding_options.intpair("size", (64, 64))
        self.window_icon_max_size = icons_encoding_options.intpair("max_size", self.window_icon_size)
        self.window_icon_max_size = (
            max(self.window_icon_max_size[0], 16),
            max(self.window_icon_max_size[1], 16),
            )
        self.window_icon_size = (
            min(self.window_icon_size[0], self.window_icon_max_size[0]),
            min(self.window_icon_size[1], self.window_icon_max_size[1]),
            )
        self.window_icon_size = (
            max(self.window_icon_size[0], 16),
            max(self.window_icon_size[1], 16),
            )
        log("client icon settings: size=%s, max_size=%s", self.window_icon_size, self.window_icon_max_size)
        if LOG_THEME_DEFAULT_ICONS:
            log("theme_default_icons=%s", self.theme_default_icons)

    def cleanup(self):
        self.cancel_window_icon_timer()

    def cancel_window_icon_timer(self):
        swit = self.send_window_icon_timer
        if swit:
            self.send_window_icon_timer = 0
            self.source_remove(swit)

    def get_info(self):
        idata = self.window_icon_data
        if not idata:
            return {}
        w, h, fmt, data = idata
        return {
            "icon" : {
                "width"         : w,
                "height"        : h,
                "format"        : fmt,
                "bytes"         : len(data),
                }
            }

    @staticmethod
    def get_fallback_window_icon():
        if WindowIconSource.fallback_window_icon is False:
            try:
                from xpra.platform.paths import get_icon_filename
                icon_filename = get_icon_filename("xpra.png")
                log("get_fallback_window_icon() icon filename=%s", icon_filename)
                assert os.path.exists(icon_filename), "xpra icon not found: %s" % icon_filename
                img = Image.open(icon_filename)
                icon_data = load_binary_file(icon_filename)
                icon = (img.size[0], img.size[1], "png", icon_data)
                WindowIconSource.fallback_window_icon = icon
                return icon
            except Exception as e:
                log.warn("failed to get fallback icon: %s", e)
                WindowIconSource.fallback_window_icon = False
        return WindowIconSource.fallback_window_icon

    def send_window_icon(self):
        #some of this code could be moved to the work queue half, meh
        assert self.ui_thread == threading.current_thread()
        if self.suspended:
            return
        #this runs in the UI thread
        icons = self.window.get_property("icons")
        log("send_window_icon window %s found %i icons", self.window, len(icons or ()))
        if not icons:
            #this is a bit dirty:
            #we figure out if the client is likely to have an icon for this wmclass already,
            #(assuming the window even has a 'class-instance'), and if not we send the default
            try:
                c_i = self.window.get_property("class-instance")
            except Exception:
                c_i = None
            if c_i and len(c_i)==2:
                wm_class = c_i[0].encode("utf-8")
                if wm_class in self.theme_default_icons:
                    log("%s in client theme icons already (not sending default icon)", self.theme_default_icons)
                    return
                #try to load the icon for this class-instance from the theme:
                icons = []
                done = set()
                for sizes in (self.window_icon_size, self.window_icon_max_size, (48, 64)):
                    for size in sizes:
                        if size in done:
                            continue
                        done.add(size)
                        icon = self.window.get_default_window_icon(size)
                        if icon:
                            icons.append(icon)
                log("send_window_icon window %s using default window icon", self.window)
        max_w, max_h = self.window_icon_max_size
        icon = self.choose_icon(icons, max_w, max_h)
        if not icon:
            #try again, without size restrictions:
            #(we'll downscale it)
            icon = self.choose_icon(icons)
        if not icon:
            if not self.window_icon_greedy:
                return
            #"greedy": client does not set a default icon, so we must provide one every time
            #to make sure that the window icon does get set to something
            #(our icon is at least better than the window manager's default)
            if self.has_default:
                #client will set the default itself,
                #send a mostly empty packet:
                packet = ("window-icon", self.wid, 0, 0, "default", "")
                log("queuing window icon update: %s", packet)
                #this is cheap, so don't use the encode thread,
                #and make sure we don't send another one via the timer:
                self.cancel_window_icon_timer()
                self.queue_packet(packet, wait_for_more=True)
                return
            icon = WindowIconSource.get_fallback_window_icon()
            log("using fallback window icon")
        if not icon:
            log("no suitable icon")
            return
        self.window_icon_data = icon
        if not self.send_window_icon_timer:
            #call compress via the work queue
            #and delay sending it by a bit to allow basic icon batching:
            w, h = self.window_icon_data[:2]
            delay = min(1000, max(50, w*h*self.batch_config.delay_per_megapixel//1000000))
            log("send_window_icon() window=%s, wid=%s, compression scheduled in %sms for batch delay=%i",
                self.window, self.wid, delay, self.batch_config.delay_per_megapixel)
            self.send_window_icon_timer = self.timeout_add(delay, self.call_in_encode_thread,
                                                           True, self.compress_and_send_window_icon)

    def compress_and_send_window_icon(self):
        #this runs in the work queue
        self.send_window_icon_timer = 0
        idata = self.window_icon_data
        if not idata or not self.has_png:
            return
        w, h, pixel_format, pixel_data = idata
        log("compress_and_send_window_icon() %ix%i in %s format, %i bytes for wid=%i",
            w, h, pixel_format, len(pixel_data), self.wid)
        assert pixel_format in ("BGRA", "RGBA", "png"), "invalid window icon format %s" % pixel_format
        if pixel_format=="BGRA":
            #BGRA data is always unpremultiplied
            #(that's what we get from NetWMIcons)
            from xpra.codecs.argb.argb import premultiply_argb  #@UnresolvedImport
            pixel_data = premultiply_argb(pixel_data)

        max_w, max_h = self.window_icon_max_size
        #use png if supported and if "premult_argb32" is not supported by the client (ie: html5)
        #or if we must downscale it (bigger than what the client is willing to deal with),
        #or if we want to save window icons
        must_scale = w>max_w or h>max_h
        log("compress_and_send_window_icon: %sx%s (max-size=%s, standard-size=%s), pixel_format=%s",
            w, h, self.window_icon_max_size, self.window_icon_size, pixel_format)
        must_convert = pixel_format!="png"
        log(" must convert=%s, must scale=%s", must_convert, must_scale)

        image = None
        if must_scale or must_convert or SAVE_WINDOW_ICONS:
            #we're going to need a PIL Image:
            if pixel_format=="png":
                image = Image.open(BytesIO(pixel_data))
            else:
                image = Image.frombuffer("RGBA", (w,h), memoryview_to_bytes(pixel_data), "raw", pixel_format, 0, 1)
            if must_scale:
                #scale the icon down to the size the client wants
                #(we should scale + paste to preserve the aspect ratio, meh)
                icon_w, icon_h = self.window_icon_size
                if float(w)/icon_w>=float(h)/icon_h:
                    rh = min(max_h, h*icon_w//w)
                    rw = icon_w
                else:
                    rw = min(max_w, w*icon_h//h)
                    rh = icon_h
                log("scaling window icon down to %sx%s", rw, rh)
                image = image.resize((rw, rh), Image.ANTIALIAS)
            if SAVE_WINDOW_ICONS:
                filename = "server-window-%i-icon-%i.png" % (self.wid, int(monotonic_time()))
                image.save(filename, 'PNG')
                log("server window icon saved to %s", filename)

        if image:
            #image got converted or scaled, get the new pixel data:
            output = BytesIO()
            image.save(output, "png")
            pixel_data = output.getvalue()
            output.close()
            w, h = image.size
        wrapper = compression.Compressed("png", pixel_data)
        packet = ("window-icon", self.wid, w, h, wrapper.datatype, wrapper)
        log("queuing window icon update: %s", packet)
        self.queue_packet(packet, wait_for_more=True)


    def choose_icon(self, icons, max_w=1024, max_h=1024):
        if not icons:
            return None
        log("choose_icon from: %s", csv("%ix%i %s" % icon[:3] for icon in icons))
        size_image = dict((icon[0]*icon[1], icon) for icon in icons if icon[0]<max_w and icon[1]<max_h)
        if not size_image:
            return None
        #we should choose one whose size is close to what the client wants,
        #take the biggest one for now:
        largest_size = sorted(size_image)[-1]
        icon = size_image[largest_size]
        log("choose_icon(..)=%ix%i %s", *icon[:3])
        return icon
