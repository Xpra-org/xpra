#!/usr/bin/env python

import sys


def dump_xshape(xid):
    from xpra.x11.bindings.window_bindings import X11WindowBindings, SHAPE_KIND #@UnresolvedImport
    X11Window = X11WindowBindings()
    extents = X11Window.XShapeQueryExtents(xid)
    if not extents:
        print("read_shape for window %#x: no extents" % xid)
        return {}
    v = {}
    bextents = extents[0]
    cextents = extents[1]
    if bextents[0]==0 and cextents[0]==0:
        print("read_shape for window %#x: none enabled" % xid)
        return {}
    v["Bounding.extents"] = bextents
    v["Clip.extents"] = cextents
    for kind in SHAPE_KIND.keys():
        kind_name = SHAPE_KIND[kind]
        rectangles = X11Window.XShapeGetRectangles(xid, kind)
        v[kind_name+".rectangles"] = rectangles
    print("read_shape()=%s" % v)
    return v

def main(args):
    from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
    init_gdk_display_source()
    for wid in args[1:]:
        print("looking for window %s" % wid)
        if wid.startswith("0x"):
            dump_xshape(int(wid[2:], 16))
        else:
            dump_xshape(int(wid))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
