#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
from xpra.gtk_common.graph import make_graph_pixmap

def main():
    window = gtk.Window()
    box = gtk.VBox(False)
    window.add(box)

    if True:
        data = [[7, 7, 7, 7, 7, 7, 7, 7, 12, 10, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7], [4, 7, 10, 4, 7, 7, 7, 10, 12, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7], [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]
        graph = make_graph_pixmap(data, ['recv x10B/s', 'sent x10B/s', ' pixels/s'], 360, 165, "Bandwidth", True, False, None, rounding=100)
        image = gtk.Image()
        image.set_from_pixmap(graph, None)
        box.add(image)

    if True:
        data = [[6.761074066162109, 7.436990737915039, 5.215167999267578, 6.270885467529297, 5.424976348876953, 6.54292106628418, 2.619028091430664, 5.944013595581055, 5.134105682373047, 5.10096549987793, 5.944967269897461, 5.656957626342773, 8.015155792236328, 5.669116973876953, 4.487037658691406, 5.110979080200195, 5.182027816772461, 5.619049072265625, 4.729032516479492, 5.012035369873047], [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 2.0, 2.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0, 2.0, 2.0, 3.0, 3.0]]
        graph = make_graph_pixmap(data, ['server', 'client'], 360, 165, "Latency (ms)", True, False, 10, rounding=10)
        image = gtk.Image()
        image.set_from_pixmap(graph, None)
        box.add(image)

    window.connect("destroy", gtk.main_quit)
    window.show_all()
    gtk.main()


if __name__ == "__main__":
    main()
