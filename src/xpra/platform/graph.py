# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
import math

def round_up_unit(i):
    v = 1
    while v*10<i:
        v = v*10
    for x in range(10):
        if v*x>i:
            return v*x
    return v * 10

DEFAULT_COLOURS = [(0.8, 0, 0), (0, 0, 0.8), (0.1, 0.65, 0.1), (0, 0.6, 0.6)]

def make_graph_pixmap(data, labels=None, width=320, height=200, title=None, show_y_scale=True, show_x_scale=False, colours=DEFAULT_COLOURS):
    pixmap = gtk.gdk.Pixmap(None, width, height, 24)
    offset = 20
    over = 2
    radius = 2
    #inner dimensions (used for graph only)
    w = width - offset
    h = height - offset*2
    context = pixmap.cairo_create()
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
    scale_y = round_up_unit(max_y)
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
    context.move_to(offset, offset-over)
    context.line_to(offset, height-offset+over)
    #show horizontal line:
    context.move_to(offset-over, height-offset)
    context.line_to(width, height-offset)
    #units:
    context.select_font_face('Sans')
    context.set_font_size(10)
    #scales
    for i in range(0, 11):
        if show_y_scale:
            context.set_source_rgb(0, 0, 0)
            context.set_line_width(1)
            #vertical:
            y = height-offset-h*i/10
            #text
            context.move_to(2, y+2)
            unit = str(int(scale_y*i/10))
            context.show_text(unit)
            #line indicator
            context.move_to(offset-over, y)
            context.line_to(offset+over, y)
            context.stroke()
            context.move_to(offset+over, y)
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
            x = offset+w*i/10
            #text
            context.move_to(x-2, height-2)
            unit = str(int(scale_x*i/10))
            context.show_text(unit)
            #line indicator
            context.move_to(x, height-offset-over)
            context.line_to(x, height-offset+over)
            context.stroke()
    #title:
    if title:
        context.set_source_rgb(0.2, 0.2, 0.2)
        context.select_font_face('Serif')
        context.set_font_size(14)
        context.move_to(offset+w/2-len(title)*14/2, 14)
        context.show_text(title)
        context.stroke()
    #now draw the actual data
    i = 0
    context.set_line_width(1.5)
    for line_data in data:
        colour = colours[i % len(colours)]
        context.set_source_rgb(*colour)
        j = 0
        last_v = None
        for v in line_data:
            x = offset + w*j/(max(1, max_x-1))
            if v is not None:
                if max_y>0:
                    y = height-offset - h*v/max_y
                else:
                    y = 0
                if last_v is not None:
                    context.line_to(x, y)
                    context.stroke()
                context.arc(x, y, radius, 0, 2*math.pi)
                context.fill()
                context.stroke()
                context.move_to(x, y)
            j += 1
            last_v = v
        context.stroke()
        #show label:
        if labels and len(labels)>i:
            label = labels[i]
            context.select_font_face('Serif')
            context.set_font_size(12)
            context.move_to(offset/2+(width-offset)*i/len(labels), height-4)
            context.show_text(label)
            context.stroke()
        i += 1
    return pixmap


def main():
    window = gtk.Window()
    data = [[34, 12, 39, 35, 25], [12, 20, 14, 20, 27], [None, None, 10, 12, 15]]
    graph = make_graph_pixmap(data, labels=["one", "two"], title="hello")
    image = gtk.Image()
    image.set_from_pixmap(graph, None)
    window.add(image)
    window.connect("destroy", gtk.main_quit)
    window.show_all()
    gtk.main()


if __name__ == "__main__":
    main()
