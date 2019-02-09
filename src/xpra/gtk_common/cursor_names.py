# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gdk, is_gtk3

cursor_names = {}
cursor_types = {}
gdk = import_gdk()
if is_gtk3():
    base = gdk.CursorType
else:
    base = gdk

for x in (
    "X_CURSOR", "ARROW", "BASED_ARROW_DOWN", "BASED_ARROW_UP", "BOAT", "BOGOSITY", "BOTTOM_LEFT_CORNER",
    "BOTTOM_RIGHT_CORNER", "BOTTOM_SIDE", "BOTTOM_TEE", "BOX_SPIRAL", "CENTER_PTR", "CIRCLE", "CLOCK",
    "COFFEE_MUG", "CROSS", "CROSS_REVERSE", "CROSSHAIR", "DIAMOND_CROSS", "DOT", "DOTBOX", "DOUBLE_ARROW",
    "DRAFT_LARGE", "DRAFT_SMALL", "DRAPED_BOX", "EXCHANGE", "FLEUR", "GOBBLER", "GUMBY", "HAND1", "HAND2",
    "HEART", "ICON", "IRON_CROSS", "LEFT_PTR", "LEFT_SIDE", "LEFT_TEE", "LEFTBUTTON", "LL_ANGLE", "LR_ANGLE",
    "MAN", "MIDDLEBUTTON", "MOUSE", "PENCIL", "PIRATE", "PLUS", "QUESTION_ARROW", "RIGHT_PTR", "RIGHT_SIDE",
    "RIGHT_TEE", "RIGHTBUTTON", "RTL_LOGO", "SAILBOAT", "SB_DOWN_ARROW", "SB_H_DOUBLE_ARROW", "SB_LEFT_ARROW",
    "SB_RIGHT_ARROW", "SB_UP_ARROW", "SB_V_DOUBLE_ARROW", "SHUTTLE", "SIZING", "SPIDER", "SPRAYCAN", "STAR",
    "TARGET", "TCROSS", "TOP_LEFT_ARROW", "TOP_LEFT_CORNER", "TOP_RIGHT_CORNER", "TOP_SIDE", "TOP_TEE", "TREK",
    "UL_ANGLE", "UMBRELLA", "UR_ANGLE", "WATCH", "XTERM",
    ):
    if hasattr(base, x):
        v = getattr(base, x)
        cursor_names[v] = x
        cursor_types[x] = v
    else:
        print("cannot find %s in %s" % (x, base))
