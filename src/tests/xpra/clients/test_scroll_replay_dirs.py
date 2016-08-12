#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from cStringIO import StringIO
import sys, os
from xpra.log import Logger
log = Logger()

from xpra.util import typedict
from tests.xpra.clients.fake_gtk_client import FakeGTKClient, gtk_main
from xpra.codecs.loader import load_codecs

load_codecs(encoders=False, decoders=True, csc=False)


class WindowAnim(object):

    def __init__(self, window_class, client, wid, W=630, H=480):
        self.wid = wid
        self.window = window_class(client, None, wid, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
        self.window.show()
        self.paint_rect(0, 0, W, H, chr(255)*4*W*H)

    def paint_rect(self, x=200, y=200, w=32, h=32, img_data=None, options={}):
        assert img_data
        self.window.draw_region(x, y, w, h, "rgb32", img_data, w*4, 0, typedict(options), [])

    def paint_png(self, pngdata, x, y, w, h, flush=0):
        print("paint_png(%i bytes, %i, %i, %i, %i, %i)" % (len(pngdata), x, y, w, h, flush))
        self.window.draw_region(x, y, w, h, "png", pngdata, w*4, 0, typedict({"flush" : flush}), [])

    def scroll(self, x, y, w, h, xdelta, ydelta, flush=0):
        W, H = self.window.get_size()
        print("scroll%s" % ((x, y, w, h, xdelta, ydelta, flush), ))
        scrolls = [(x, y, w, h, xdelta, ydelta)]
        self.window.draw_region(0, 0, W, H, "scroll", scrolls, W*4, 0, typedict({"flush" : flush}), [])

    def compare_png(self, actual, x, y, w, h):
        backing = self.window._backing._backing
        from gtk import gdk
        pixbuf = gdk.Pixbuf(gdk.COLORSPACE_RGB, True, 8, w, h)
        try:
            pixbuf.get_from_drawable(backing, backing.get_colormap(), 0, 0, 0, 0, w, h)
        except Exception as e:
            print("cannot get drawable from %s: %s" % (backing, e))
            return
        from PIL import Image
        result = Image.frombytes("RGBA", (w, h), pixbuf.get_pixels(), "raw", "RGBA", pixbuf.get_rowstride()).convert("RGB")
        expected = PIL_open(actual)
        from PIL import ImageChops
        diff = ImageChops.difference(result, expected)
        #print("compare_png: %s -> %s -> %s" % (backing, pixbuf, result))
        output = StringIO()
        diff.save(output, format="png")
        contents = output.getvalue()
        output.close()
        self.paint_png(contents, x, y, w, h)


def parseintlist(v):
    v = v.strip("(").strip(")")
    return [int(i.strip(" ")) for i in v.split(",")]

def PIL_open(imagedata):
    from PIL import Image
    data = StringIO(imagedata)
    return Image.open(data)

def frame_replay(dirname, windows, index=0, done_cb=None):
    def loadbfile(filename):
        return open(os.path.join(dirname, filename)).read()
    #print("frame_replay(%s, %s)" % (dirname, show_old))
    initial_image = loadbfile("old.png")
    img = PIL_open(initial_image)
    scrolls = []
    #load scroll data:
    try:
        scroll_data = loadbfile("scrolls.txt")
        for v in scroll_data.splitlines():
            scrolls.append(parseintlist(v))
    except:
        pass
    #load paint instructions:
    paints = []
    try:
        paint_data = loadbfile("replay.txt")
        for v in paint_data.splitlines():
            filename,coords = v.split(" ", 1)
            file_data = loadbfile(filename)
            paints.append((file_data, parseintlist(coords)))
    except:
        pass
    def print_start():
        print("START OF %s" % dirname)
    actions = [(print_start, )]
    if index==0:
        for window in windows:
            actions.append([window.paint_png, initial_image, 0, 0] + list(img.size))
    flush = len(paints) + len(scrolls)
    if paints or scrolls:
        #print("loaded all replay data:")
        #print("initial image: %i bytes (%s)" % (len(initial_image), img.size))
        #print("scrolls: %s" % (scrolls, ))
        #print("paints: %s" % ([(len(v[0]), v[1]) for v in paints]))
        for v in scrolls:
            flush -= 1
            for window in windows:
                actions.append([window.scroll]+v+[flush])
        for pngdata, coords in paints:
            flush -= 1
            for window in windows:
                actions.append([window.paint_png, pngdata] + list(coords)+[flush])
    actual = loadbfile("new.png")
    for window in windows:
        actions.append([window.compare_png, actual, 0, 0] + list(img.size))
    for window in windows:
        actions.append([window.paint_png, actual, 0, 0] + list(img.size))
    def print_end():
        print("END OF %s" % dirname)
    actions.append((print_end, ))
    return actions


def main():
    dirname = sys.argv[1]
    if not os.path.exists(dirname):
        print("cannot find %s" % dirname)
        sys.exit(1)
    skip = 0
    try:
        skip = int(sys.argv[2])
    except:
        pass
    count = 999
    try:
        count = int(sys.argv[3])
    except:
        pass
    W = 1024
    H = 1200
    window_classes = []
    try:
        from xpra.client.gl.gtk2.gl_client_window import GLClientWindow
        window_classes.append(GLClientWindow)
    except Exception as e:
        print("no opengl window: %s" % e)
    try:
        from xpra.client.gtk2.border_client_window import BorderClientWindow
        window_classes.append(BorderClientWindow)
    except Exception as e:
        print("no pixmap window: %s" % e)
    client = FakeGTKClient()
    client.log_events = False
    windows = []
    for window_class in window_classes:
        windows.append(WindowAnim(window_class, client, 1, W, H))

    actions = []
    all_dirs = sorted(os.listdir(dirname))[skip:skip+count]
    print("all dirs=%s", (all_dirs,))
    for i,d in enumerate(all_dirs):
        d = os.path.join(dirname, d)
        actions += frame_replay(d, windows, i)

    actions = list(reversed(actions))
    def handle_key_action(window, event):
        if event.pressed:
            a = actions.pop()
            #print("handle_key_action: action=%s" % (a[0], ))
            a[0](*a[1:])

    #print("actions=%s" % ([x[0] for x in actions], ))
    client.handle_key_action = handle_key_action
    try:
        gtk_main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
