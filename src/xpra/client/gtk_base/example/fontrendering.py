#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.gtk_common.gobject_compat import import_gtk, import_glib, import_pango, import_pangocairo, is_gtk3
gtk = import_gtk()
gLib = import_glib()
pango = import_pango()
pangocairo = import_pangocairo()
from xpra.gtk_common.gtk_util import WIN_POS_CENTER

FONT = "Serif 27"
PATTERN = "%f"

from collections import OrderedDict
ANTIALIAS = OrderedDict()
ANTIALIAS[cairo.ANTIALIAS_NONE]     = "NONE"
ANTIALIAS[cairo.ANTIALIAS_DEFAULT]  = "DEFAULT"
ANTIALIAS[cairo.ANTIALIAS_GRAY]     = "GRAY"
ANTIALIAS[cairo.ANTIALIAS_SUBPIXEL] = "SUBPIXEL"

WHITE = (1, 1, 1)
BLACK = (0, 0, 0)


class FontWindow(gtk.Window):

    def __init__(self):
        super(FontWindow, self).__init__()
        self.set_position(WIN_POS_CENTER)
        self.set_default_size(1600, 1200)
        self.set_app_paintable(True)
        if is_gtk3():
            self.connect("draw", self.area_draw)
        else:
            self.connect("expose-event", self.do_expose_event)
        self.connect("destroy", gtk.main_quit)
        self.show_all()

    def do_expose_event(self, *_args):
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

    def area_draw(self, widget, cr):
        if is_gtk3():
            layout = pangocairo.create_layout(cr)
            pctx = layout.get_context()
        else:
            pctx = pangocairo.CairoContext(cr)
        print("PangoContext: %s (%s)" % (pctx, type(pctx)))
        print("PangoContext: %s" % dir(pctx))
        if is_gtk3():
            print(" font map=%s" % pctx.get_font_map())
            print(" families=%s" % pctx.list_families())
            print(" font description=%s" % pctx.get_font_description())
            print(" language=%s" % pctx.get_language())
            print(" get_base_dir=%s" % pctx.get_base_dir())
        else:
            for x in ("get_antialias", "get_font_face", "get_font_matrix", "get_scaled_font"):
                fn = getattr(pctx, x, None)
                if fn:
                    print("PangoContext.%s: %s" % (x, fn()))
            fo = pctx.get_font_options()
            for x in ("get_antialias", "get_hint_metrics", "get_hint_style", "get_subpixel_order"):
                fn = getattr(fo, x, None)
                if fn:
                    print("FontOptions.%s: %s" % (x, fn()))
            pctx.set_antialias(cairo.ANTIALIAS_SUBPIXEL)

        for y in range(2):
            for x in range(2):
                cr.save()
                antialias = ANTIALIAS.keys()[y*2+x]
                label = ANTIALIAS[antialias]
                self.paint_pattern(cr, x, y,     antialias, label, BLACK, WHITE)
                self.paint_pattern(cr, x, y+2,   antialias, label, WHITE, BLACK)
                cr.restore()

        w, h = widget.get_size()
        bw = w//4
        bh = h//4
        #copy ANTIALIAS_NONE to right hand side,
        #then substract each image
        for background, foreground, yoffset in (
            (BLACK, WHITE, 0),
            (WHITE, BLACK, 2),
            ):
            for y in range(2):
                for x in range(2):
                    def paint_to_image(antialias=cairo.ANTIALIAS_NONE):
                        img = cairo.ImageSurface(cairo.FORMAT_RGB24, bw, bh)
                        icr = cairo.Context(img)
                        self.paint_pattern(icr, 0, 0, antialias, None, background, foreground)
                        img.flush()
                        return img

                    cr.save()
                    #paint antialias value:
                    antialias = ANTIALIAS.keys()[y*2+x]
                    v = paint_to_image(antialias)
                    none = paint_to_image()
                    #xor the buffers
                    vdata = v.get_data()
                    ndata = none.get_data()
                    for i in range(len(vdata)):
                        vdata[i] = chr(ord(vdata[i]) ^ ord(ndata[i]))
                    #paint the resulting image:
                    cr.set_operator(cairo.OPERATOR_SOURCE)
                    cr.set_source_surface(v, (x+2)*bw, (y+yoffset)*bh)
                    cr.rectangle((x+2)*bw, (y+yoffset)*bh, bw, bh)
                    cr.clip()
                    cr.paint()
                    cr.restore()


        #layout = pangocairo.create_layout(cr)
        #layout.set_text("Text", -1)
        #desc = pango.font_description_from_string(FONT)
        #layout.set_font_description( desc)

    def paint_pattern(self, cr, x, y, antialias, label="", background=WHITE, foreground=BLACK):
        w, h = self.get_size()
        bw = w//4
        bh = h//4
        FONT_SIZE = w//8

        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgb(*background)
        cr.rectangle(x*bw, y*bh, bw, bh)
        cr.fill()

        fo = cairo.FontOptions()
        fo.set_antialias(antialias)
        cr.set_font_options(fo)
        cr.set_antialias(antialias)
        cr.set_source_rgb(*foreground)

        cr.set_font_size(FONT_SIZE)
        cr.move_to(x*bw+bw//2-FONT_SIZE//2, y*bh+bh//2+FONT_SIZE//3)
        cr.show_text(PATTERN)
        cr.stroke()

        if label:
            cr.set_font_size(15)
            cr.move_to(x*bw+bw//2-FONT_SIZE//2, y*bh+bh*3//4+FONT_SIZE//3)
            cr.show_text(ANTIALIAS[antialias])
            cr.stroke()


def main():
    import signal
    signal.signal(signal.SIGINT, lambda x,y : gtk.main_quit)
    FontWindow()
    gtk.main()


if __name__ == "__main__":
    main()
