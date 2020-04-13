# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#X11 constants we use for gravity:
NorthWestGravity = 1
NorthGravity     = 2
NorthEastGravity = 3
WestGravity      = 4
CenterGravity    = 5
EastGravity      = 6
SouthWestGravity = 7
SouthGravity     = 8
SouthEastGravity = 9
StaticGravity    = 10

GRAVITY_STR = {
    NorthWestGravity : "NorthWest",
    NorthGravity     : "North",
    NorthEastGravity : "NorthEast",
    WestGravity      : "West",
    CenterGravity    : "Center",
    EastGravity      : "East",
    SouthWestGravity : "SouthWest",
    SouthGravity     : "South",
    SouthEastGravity : "SouthEast",
    StaticGravity    : "South",
    }

CLOBBER_UPGRADE = 0x1
CLOBBER_USE_DISPLAY = 0x2

#if you want to use a virtual screen bigger than this
#you will need to change those values, but some broken toolkits
#will then misbehave (they use signed shorts instead of signed ints..)
MAX_WINDOW_SIZE = 2**15-2**13
