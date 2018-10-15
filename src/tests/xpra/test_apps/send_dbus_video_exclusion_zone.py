#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def test_dbus(display, wid=1, zones=[[100,100,20,20],]):
    import dbus     #@UnresolvedImport
    bus = dbus.SessionBus()
    server = 'org.xpra.Server%i' % display
    service = bus.get_object(server, "/org/xpra/Server")
    SetVideoRegionExclusionZones = service.get_dbus_method('SetVideoRegionExclusionZones', 'org.xpra.Server')
    print("calling %s.SetVideoRegionExclusionZones(%i, %s)" % (server, wid, zones))
    SetVideoRegionExclusionZones(wid, zones)

def main():
    import sys
    try:
        DISPLAY = int(sys.argv[1])
    except:
        DISPLAY = 100
    try:
        wid = int(sys.argv[2])
    except:
        wid = 1
    try:
        zones = []
        for arg in sys.argv[3:]:
            zones.append([int(x.strip()) for x in arg.split(",")])
    except:
        zones = []
    test_dbus(DISPLAY, wid, zones)

if __name__ == "__main__":
    main()
