# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
import cairo

DEFAULT_COLOURS = ((0.8, 0, 0), (0, 0, 0.8), (0.1, 0.65, 0.1), (0, 0.6, 0.6), (0.1, 0.1, 0.1))


def round_up_unit(i, rounding=10):
    v = 1
    while v*rounding<i:
        v = v*rounding
    for x in range(10):
        if v*x>i:
            return v*x
    return v * rounding

def make_graph_imagesurface(data, labels=None, width=320, height=200, title=None,
                      show_y_scale=True, show_x_scale=False,
                      min_y_scale=None, rounding=10,
                      start_x_offset = 0.0,
                      colours=DEFAULT_COLOURS, dots=False, curves=True):
    #print("make_graph_pixmap(%s, %s, %s, %s, %s, %s, %s, %s, %s)" % (data, labels, width, height, title,
    #                  show_y_scale, show_x_scale, min_y_scale, colours))
    try:
        fmt = cairo.Format.RGB24
    except AttributeError:
        fmt = cairo.FORMAT_RGB24
    surface = cairo.ImageSurface(fmt, width, height)
    y_label_chars = 4
    x_offset = y_label_chars*8
    y_offset = 20
    over = 2
    radius = 2
    #inner dimensions (used for graph only)
    w = width - x_offset
    h = height - y_offset*2
    context = cairo.Context(surface)
    #fill with white:
    context.rectangle(0, 0, width, height)
    context.set_source_rgb(1, 1, 1)
    context.fill()
    #find ranges:
    max_y = 0
    max_x = 0
    for line_data in data:
        x = 0
        for y in line_data:
            if y is not None:
                max_y = max(max_y, y)
            x += 1
            max_x = max(max_x, x)
    #round up the scales:
    scale_x = max_x
    if min_y_scale is not None:
        max_y = max(max_y, min_y_scale)
    scale_y = round_up_unit(max_y, rounding)
    #use black:
    context.set_source_rgb(0, 0, 0)
    #border:
    context.move_to(0, 0)
    context.line_to(width, 0)
    context.line_to(width, height)
    context.line_to(0, height)
    context.line_to(0, 0)
    context.stroke()
    #show vertical line:
    context.move_to(x_offset, y_offset-over)
    context.line_to(x_offset, height-y_offset+over)
    #show horizontal line:
    context.move_to(x_offset-over, height-y_offset)
    context.line_to(width, height-y_offset)
    #units:
    context.select_font_face('Sans')
    context.set_font_size(10)
    #scales
    for i in range(0, 11):
        if show_y_scale:
            context.set_source_rgb(0, 0, 0)
            context.set_line_width(1)
            #vertical:
            y = height-y_offset-h*i/10
            #text
            if scale_y<10:
                unit = str(int(scale_y*i)/10.0)
            else:
                unit = str(int(scale_y*i/10))
            context.move_to(x_offset-3-(x_offset-6)/y_label_chars*min(y_label_chars, len(unit)), y+3)
            context.show_text(unit)
            #line indicator
            context.move_to(x_offset-over, y)
            context.line_to(x_offset+over, y)
            context.stroke()
            context.move_to(x_offset+over, y)
            context.set_source_rgb(0.5, 0.5, 0.5)
            context.set_line_width(0.5)
            context.set_dash([3.0, 3.0])
            context.line_to(width, y)
            context.stroke()
            context.set_dash([])
        if show_x_scale:
            context.set_source_rgb(0, 0, 0)
            context.set_line_width(1)
            #horizontal:
            x = x_offset+w*i/10
            #text
            context.move_to(x-2, height-2)
            unit = str(int(scale_x*i/10))
            context.show_text(unit)
            #line indicator
            context.move_to(x, height-y_offset-over)
            context.line_to(x, height-y_offset+over)
            context.stroke()
    #title:
    if title:
        context.set_source_rgb(0.2, 0.2, 0.2)
        context.select_font_face('Serif')
        context.set_font_size(14)
        context.move_to(x_offset+w/2-len(title)*14/2, 14)
        context.show_text(title)
        context.stroke()
    #now draw the actual data, clipped to the graph region:
    context.save()
    context.new_path()
    context.set_line_width(0.0)
    context.rectangle(x_offset, y_offset, x_offset+w, y_offset+h)
    context.clip()
    context.set_line_width(1.5)
    for i, line_data in enumerate(data):
        colour = colours[i % len(colours)]
        context.set_source_rgb(*colour)
        j = 0
        last_v = (-1, -1, -1)
        for v in line_data:
            x = x_offset + w*(j - start_x_offset)/(max(1, max_x-2))
            if v is not None:
                if max_y>0:
                    y = height-y_offset - h*v/scale_y
                else:
                    y = 0
                if last_v!=(-1, -1, -1):
                    lx, ly = last_v[1:3]
                    if curves:
                        x1 = (lx*2+x)/3
                        y1 = ly
                        x2 = (lx+x*2)/3
                        y2 = y
                        context.curve_to(x1, y1, x2, y2, x, y)
                        context.stroke()
                    else:
                        context.line_to(x, y)
                        context.stroke()
                if dots:
                    context.arc(x, y, radius, 0, 2*math.pi)
                    context.fill()
                    context.stroke()
                    context.move_to(x, y)
                else:
                    context.move_to(x, y)
                last_v = v, x, y
            j += 1
        context.stroke()
    context.restore()
    for i, line_data in enumerate(data):
        #show label:
        if labels and len(labels)>i:
            label = labels[i]
            colour = colours[i % len(colours)]
            context.set_source_rgb(*colour)
            context.select_font_face('Serif')
            context.set_font_size(12)
            context.move_to(x_offset/2+(width-x_offset)*i/len(labels), height-4)
            context.show_text(label)
            context.stroke()
    return surface
