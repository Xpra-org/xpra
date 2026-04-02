# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
import cairo
from xpra.os_util import gi_import
from xpra.common import DEFAULT_DPI

PangoCairo = gi_import("PangoCairo")
Pango = gi_import("Pango")

DEFAULT_COLOURS = ((0.8, 0, 0), (0, 0, 0.8), (0.1, 0.65, 0.1), (0, 0.6, 0.6), (0.1, 0.1, 0.1))


def round_up_unit(i: int, rounding=10) -> int:
    v = 1
    while v * rounding < i:
        v = v * rounding
    for x in range(10):
        if v * x > i:
            return v * x
    return v * rounding


def _text_size(layout, text: str) -> tuple[int, int]:
    layout.set_text(text, -1)
    _, logical = layout.get_pixel_extents()
    return logical.width, logical.height


def _y_label(scale_y: int | float, i: int) -> str:
    if scale_y < 10:
        return str(int(scale_y * i) / 10.0)
    return str(int(scale_y * i / 10))


def make_graph_imagesurface(data, labels=None, width=320, height=200, title=None,
                            show_y_scale=True, show_x_scale=False,
                            min_y_scale=None, rounding=10,
                            start_x_offset=0.0,
                            colours=DEFAULT_COLOURS, dots=False, curves=True,
                            scale=1) -> cairo.ImageSurface:
    # print("make_graph_pixmap(%s, %s, %s, %s, %s, %s, %s, %s, %s)" % (data, labels, width, height, title,
    #                  show_y_scale, show_x_scale, min_y_scale, colours))
    surface = cairo.ImageSurface(cairo.Format.RGB24, width, height)  # pylint: disable=no-member
    context = cairo.Context(surface)  # pylint: disable=no-member

    # set up Pango for DPI-aware text rendering
    layout = PangoCairo.create_layout(context)
    pctx = layout.get_context()
    PangoCairo.context_set_resolution(pctx, DEFAULT_DPI * scale)

    axis_font = Pango.FontDescription("Sans 9")
    title_font = Pango.FontDescription("Serif 10")
    legend_font = Pango.FontDescription("Serif 9")

    # find data ranges first so we can measure actual labels
    max_y = 0
    max_x = 0
    for line_data in data:
        x = 0
        for y in line_data:
            if y is not None:
                max_y = max(max_y, y)
            x += 1
            max_x = max(max_x, x)
    scale_x = max_x
    if min_y_scale is not None:
        max_y = max(max_y, min_y_scale)
    scale_y = round_up_unit(max_y, rounding)

    # compute margins from actual text metrics
    layout.set_font_description(axis_font)
    # measure the widest Y label for left margin
    max_label_w = 0
    for i in range(0, 11):
        lw, _ = _text_size(layout, _y_label(scale_y, i))
        max_label_w = max(max_label_w, lw)
    _, label_h = _text_size(layout, "0")
    x_offset = max_label_w + 6

    layout.set_font_description(title_font)
    _, title_h = _text_size(layout, "Ag")
    y_offset = title_h + 4

    over = 2
    radius = 2
    # inner dimensions (used for graph only)
    w = width - x_offset
    h = height - y_offset * 2

    # skip Y labels that would overlap
    grid_spacing = h / 10
    layout.set_font_description(axis_font)
    y_label_step = max(1, math.ceil(label_h * 1.3 / grid_spacing))

    # fill with white:
    context.rectangle(0, 0, width, height)
    context.set_source_rgb(1, 1, 1)
    context.fill()
    # use black:
    context.set_source_rgb(0, 0, 0)
    # border:
    context.move_to(0, 0)
    context.line_to(width, 0)
    context.line_to(width, height)
    context.line_to(0, height)
    context.line_to(0, 0)
    context.stroke()
    # show vertical line:
    context.move_to(x_offset, y_offset - over)
    context.line_to(x_offset, height - y_offset + over)
    # show horizontal line:
    context.move_to(x_offset - over, height - y_offset)
    context.line_to(width, height - y_offset)
    # scales
    layout.set_font_description(axis_font)
    for i in range(0, 11):
        if show_y_scale:
            # vertical:
            y = height - y_offset - h * i / 10
            # tick mark
            context.set_source_rgb(0, 0, 0)
            context.set_line_width(1)
            context.move_to(x_offset - over, y)
            context.line_to(x_offset + over, y)
            context.stroke()
            # grid line
            context.move_to(x_offset + over, y)
            context.set_source_rgb(0.5, 0.5, 0.5)
            context.set_line_width(0.5)
            context.set_dash([3.0, 3.0])
            context.line_to(width, y)
            context.stroke()
            context.set_dash([])
            # label (skip if it would overlap)
            if i % y_label_step == 0:
                unit = _y_label(scale_y, i)
                uw, uh = _text_size(layout, unit)
                context.set_source_rgb(0, 0, 0)
                context.move_to(x_offset - uw - 2, y - uh / 2)
                PangoCairo.show_layout(context, layout)
        if show_x_scale:
            context.set_source_rgb(0, 0, 0)
            context.set_line_width(1)
            # horizontal:
            x = x_offset + w * i / 10
            # text
            unit = str(int(scale_x * i / 10))
            uw, uh = _text_size(layout, unit)
            context.move_to(x - uw / 2, height - uh - 1)
            PangoCairo.show_layout(context, layout)
            # line indicator
            context.move_to(x, height - y_offset - over)
            context.line_to(x, height - y_offset + over)
            context.stroke()
    # title:
    if title:
        context.set_source_rgb(0.2, 0.2, 0.2)
        layout.set_font_description(title_font)
        tw, th = _text_size(layout, title)
        context.move_to(x_offset + (w - tw) / 2, 1)
        PangoCairo.show_layout(context, layout)
        context.stroke()
    # now draw the actual data, clipped to the graph region:
    context.save()
    context.new_path()
    context.set_line_width(0.0)
    context.rectangle(x_offset, y_offset, x_offset + w, y_offset + h)
    context.clip()
    context.set_line_width(1.5)
    for i, line_data in enumerate(data):
        colour = colours[i % len(colours)]
        context.set_source_rgb(*colour)
        j = 0
        last_v = (-1, -1, -1)
        for v in line_data:
            x = x_offset + w * (j - start_x_offset) / (max(1, max_x - 2))
            if v is not None:
                if max_y > 0:
                    y = height - y_offset - h * v / scale_y
                else:
                    y = 0
                if last_v != (-1, -1, -1):
                    lx, ly = last_v[1:3]
                    if curves:
                        x1 = (lx * 2 + x) / 3
                        y1 = ly
                        x2 = (lx + x * 2) / 3
                        y2 = y
                        context.curve_to(x1, y1, x2, y2, x, y)
                        context.stroke()
                    else:
                        context.line_to(x, y)
                        context.stroke()
                if dots:
                    context.arc(x, y, radius, 0, 2 * math.pi)
                    context.fill()
                    context.stroke()
                    context.move_to(x, y)
                else:
                    context.move_to(x, y)
                last_v = v, x, y
            j += 1
        context.stroke()
    context.restore()
    # legend:
    layout.set_font_description(legend_font)
    for i, line_data in enumerate(data):
        if labels and len(labels) > i:
            label = labels[i]
            colour = colours[i % len(colours)]
            context.set_source_rgb(*colour)
            lw, lh = _text_size(layout, label)
            context.move_to(x_offset / 2 + (width - x_offset) * i / len(labels), height - lh - 1)
            PangoCairo.show_layout(context, layout)
            context.stroke()
    return surface
