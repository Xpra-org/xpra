# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def test_add(w, h):
    from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
    init_gdk_display_source()
    from xpra.x11.bindings.randr_bindings import RandRBindings, log  #@UnresolvedImport
    log.enable_debug()
    RandR = RandRBindings()
    screen_sizes = RandR.get_xrr_screen_sizes()
    print("screen_sizes=%s" % (screen_sizes,))
    if (w, h) in screen_sizes:
        print("resolution %s is already present!" % ((w, h),))
        return
    from xpra.gtk_common.error import xsync
    with xsync:
        r = RandR.add_screen_size(w, h)
        print("add_screen_size(%i, %i)=%s" % (w, h, r))
    import time
    time.sleep(2)
    screen_sizes = RandR.get_xrr_screen_sizes()
    print("updated screen_sizes=%s" % (screen_sizes,))

def main():
    import sys
    args = sys.argv[1:]
    if len(args)!=2:
        print("invalid number of arguments")
        print("usage: %s W H" % (sys.argv[0],))
        sys.exit(1)
    test_add(int(sys.argv[1]), int(sys.argv[2]))

if __name__ == "__main__":
    main()
