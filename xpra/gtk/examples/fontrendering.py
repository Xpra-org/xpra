#!/usr/bin/env python3
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

from cairo import Operator, ImageSurface, Context, FontOptions, Format, Antialias   # pylint: disable=no-name-in-module

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
PangoCairo = gi_import("PangoCairo")

FONT = "Serif 27"
PATTERN = "%f"

ANTIALIAS = {
    Antialias.NONE: "NONE",
    Antialias.DEFAULT: "DEFAULT",
    Antialias.GRAY: "GRAY",
    Antialias.SUBPIXEL: "SUBPIXEL",
}

WHITE = (1, 1, 1)
BLACK = (0, 0, 0)


class FontWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(800, 600)
        self.set_app_paintable(True)
        self.set_title("Font Rendering")
        icon = get_icon_pixbuf("font.png")
        if icon:
            self.set_icon(icon)
        drawing_area = Gtk.DrawingArea()
        drawing_area.connect("draw", self.area_draw)
        self.add(drawing_area)
        self.connect("destroy", Gtk.main_quit)

    def show_with_focus(self) -> None:
        force_focus()
        self.show_all()
        super().present()

    def do_expose_event(self, *_args) -> None:
        self.area_draw()

    def area_draw(self, *_args) -> None:
        cr = self.get_window().cairo_create()
        layout = PangoCairo.create_layout(cr)
        pctx = layout.get_context()
        if envbool("XPRA_LOG_PANGO", False):
            print("PangoContext: %s (%s)" % (pctx, type(pctx)))
            # print("PangoContext: %s" % dir(pctx))
            print(" font map=%s" % pctx.get_font_map())
            # print(" families=%s" % pctx.list_families())
            print(" font description=%s" % pctx.get_font_description())
            print(" language=%s" % pctx.get_language())
            print(" get_base_dir=%s" % pctx.get_base_dir())

        for y in range(2):
            for x in range(2):
                cr.save()
                antialias = tuple(ANTIALIAS.keys())[y * 2 + x]
                label = ANTIALIAS[antialias]
                self.paint_pattern(cr, x, y, antialias, label, BLACK, WHITE)
                self.paint_pattern(cr, x, y + 2, antialias, label, WHITE, BLACK)
                cr.restore()

        alloc = self.get_allocated_size()[0]
        w, h = alloc.width, alloc.height
        bw = w // 4
        bh = h // 4
        # copy ANTIALIAS_NONE to right hand side,
        # then subtract each image
        for background, foreground, yoffset in (
                (BLACK, WHITE, 0),
                (WHITE, BLACK, 2),
        ):
            for y in range(2):
                for x in range(2):
                    cr.save()
                    # paint antialias value:
                    antialias = tuple(ANTIALIAS.keys())[y * 2 + x]
                    v = self.paint_to_image(bw, bh, background, foreground, antialias)
                    none = self.paint_to_image(bw, bh, background, foreground)
                    # xor the buffers
                    vdata = v.get_data()
                    ndata = none.get_data()
                    for i in range(len(vdata)):
                        vdata[i] = vdata[i] ^ ndata[i]
                    # paint the resulting image:
                    cr.set_operator(Operator.SOURCE)
                    cr.set_source_surface(v, (x + 2) * bw, (y + yoffset) * bh)
                    cr.rectangle((x + 2) * bw, (y + yoffset) * bh, bw, bh)
                    cr.clip()
                    cr.paint()
                    cr.restore()

    def paint_to_image(self, bw: int, bh: int, background, foreground, antialias=Antialias.NONE) -> ImageSurface:
        img = ImageSurface(Format.RGB24, bw, bh)
        icr = Context(img)
        self.paint_pattern(icr, 0, 0, antialias, "", background, foreground)
        img.flush()
        return img

        # layout = pangocairo.create_layout(cr)
        # layout.set_text("Text", -1)
        # desc = pango.font_description_from_string(FONT)
        # layout.set_font_description( desc)

    def paint_pattern(self, cr, x, y, antialias, label="", background=WHITE, foreground=BLACK) -> None:
        w, h = self.get_size()
        bw = w // 4
        bh = h // 4
        FONT_SIZE = w // 8

        cr.set_operator(Operator.SOURCE)
        cr.set_source_rgb(*background)
        cr.rectangle(x * bw, y * bh, bw, bh)
        cr.fill()

        fo = FontOptions()
        fo.set_antialias(antialias)
        cr.set_font_options(fo)
        cr.set_antialias(antialias)
        cr.set_source_rgb(*foreground)

        cr.set_font_size(FONT_SIZE)
        cr.move_to(x * bw + bw // 2 - FONT_SIZE // 2, y * bh + bh // 2 + FONT_SIZE // 3)
        cr.show_text(PATTERN)
        cr.stroke()

        if label:
            cr.set_font_size(15)
            cr.move_to(x * bw + bw // 2 - FONT_SIZE // 2, y * bh + bh * 3 // 4 + FONT_SIZE // 3)
            cr.show_text(ANTIALIAS[antialias])
            cr.stroke()


def main() -> None:
    with program_context("font-rendering", "Font Rendering"):
        from xpra.gtk.signals import quit_on_signals
        quit_on_signals("font test window")
        w = FontWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
