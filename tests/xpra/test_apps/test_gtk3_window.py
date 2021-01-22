#!/usr/bin/env python

from cairo import ImageSurface, Context, FORMAT_ARGB32, OPERATOR_CLEAR, OPERATOR_SOURCE
from PIL import Image
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk #pylint: disable=wrong-import-position

W = 480
H = 500

class TestGTK3Window(Gtk.Window):

    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)
        self.set_size_request(W, H)
        self.connect("delete_event", Gtk.main_quit)
        self.set_decorated(True)
        self.set_app_paintable(True)
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.connect("draw", self.widget_draw)
        self.add(self.drawing_area)
        self.show_all()
        self.backing = ImageSurface(FORMAT_ARGB32, W, H)
        rgb_data = b"\120"*W*H*4
        self.paint_rgb(rgb_data, W, H)
        img = Image.open("./icons/xpra.png")
        w, h = img.size
        self.paint_image(img, 0, 0, w, h)

    def paint_rgb(self, rgb_data, w, h):
        img = Image.frombytes("RGBA", (w, h), rgb_data, "raw", "RGBA", w*4, 1)
        self.paint_image(img, 0, 0, w, h)

    def paint_image(self, img, x, y, w, h):
        #roundtrip via png (yuk)
        from io import BytesIO
        png = BytesIO()
        img.save(png, format="PNG")
        reader = BytesIO(png.getvalue())
        png.close()
        img = ImageSurface.create_from_png(reader)
        gc = Context(self.backing)
        gc.rectangle(x, y, w, h)
        gc.clip()
        gc.set_operator(OPERATOR_CLEAR)
        gc.rectangle(x, y, w, h)
        gc.fill()
        gc.set_operator(OPERATOR_SOURCE)
        gc.translate(x, y)
        gc.rectangle(0, 0, w, h)
        gc.set_source_surface(img, x, y)
        gc.paint()

    def widget_draw(self, widget, context, *_args):
        print("do_draw(%s, %s)" % (widget, context,))
        #Gtk.Window.do_draw(self, context)
        context.set_source_surface(self.backing, 0, 0)
        context.paint()

def main():
    TestGTK3Window()
    Gtk.main()
    return 0


if __name__ == "__main__":
    main()
