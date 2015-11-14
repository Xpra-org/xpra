#!/usr/bin/env python

import sys
from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source
from xpra.x11.bindings.window_bindings import X11WindowBindings, SHAPE_KIND #@UnresolvedImport
X11Window = X11WindowBindings()

def dump_xshape(xid):
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

def main(args):
    for wid in args[1:]:
        print("looking for window %s" % wid)
        if wid.startswith("0x"):
            dump_xshape(int(wid[2:], 16))
        else:
            dump_xshape(int(wid))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
