# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cursor_names = {}
from wimpiggy.gobject_compat import import_gdk, is_gtk3
gdk = import_gdk()
#we could also directly lookup the attribute name
#on the gtk.gdk class, but this could cause problems
#as there are other non-cursor functions and attributes
#defined in that class. This is quick and easy.
if not is_gtk3():
    cursor_names["X_CURSOR"] = gdk.X_CURSOR
    cursor_names["ARROW"] = gdk.ARROW
    cursor_names["BASED_ARROW_DOWN"] = gdk.BASED_ARROW_DOWN
    cursor_names["BASED_ARROW_UP"] = gdk.BASED_ARROW_UP
    cursor_names["BOAT"] = gdk.BOAT
    cursor_names["BOGOSITY"] = gdk.BOGOSITY
    cursor_names["BOTTOM_LEFT_CORNER"] = gdk.BOTTOM_LEFT_CORNER
    cursor_names["BOTTOM_RIGHT_CORNER"] = gdk.BOTTOM_RIGHT_CORNER
    cursor_names["BOTTOM_SIDE"] = gdk.BOTTOM_SIDE
    cursor_names["BOTTOM_TEE"] = gdk.BOTTOM_TEE
    cursor_names["BOX_SPIRAL"] = gdk.BOX_SPIRAL
    cursor_names["CENTER_PTR"] = gdk.CENTER_PTR
    cursor_names["CIRCLE"] = gdk.CIRCLE
    cursor_names["CLOCK"] = gdk.CLOCK
    cursor_names["COFFEE_MUG"] = gdk.COFFEE_MUG
    cursor_names["CROSS"] = gdk.CROSS
    cursor_names["CROSS_REVERSE"] = gdk.CROSS_REVERSE
    cursor_names["CROSSHAIR"] = gdk.CROSSHAIR
    cursor_names["DIAMOND_CROSS"] = gdk.DIAMOND_CROSS
    cursor_names["DOT"] = gdk.DOT
    cursor_names["DOTBOX"] = gdk.DOTBOX
    cursor_names["DOUBLE_ARROW"] = gdk.DOUBLE_ARROW
    cursor_names["DRAFT_LARGE"] = gdk.DRAFT_LARGE
    cursor_names["DRAFT_SMALL"] = gdk.DRAFT_SMALL
    cursor_names["DRAPED_BOX"] = gdk.DRAPED_BOX
    cursor_names["EXCHANGE"] = gdk.EXCHANGE
    cursor_names["FLEUR"] = gdk.FLEUR
    cursor_names["GOBBLER"] = gdk.GOBBLER
    cursor_names["GUMBY"] = gdk.GUMBY
    cursor_names["HAND1"] = gdk.HAND1
    cursor_names["HAND2"] = gdk.HAND2
    cursor_names["HEART"] = gdk.HEART
    cursor_names["ICON"] = gdk.ICON
    cursor_names["IRON_CROSS"] = gdk.IRON_CROSS
    cursor_names["LEFT_PTR"] = gdk.LEFT_PTR
    cursor_names["LEFT_SIDE"] = gdk.LEFT_SIDE
    cursor_names["LEFT_TEE"] = gdk.LEFT_TEE
    cursor_names["LEFTBUTTON"] = gdk.LEFTBUTTON
    cursor_names["LL_ANGLE"] = gdk.LL_ANGLE
    cursor_names["LR_ANGLE"] = gdk.LR_ANGLE
    cursor_names["MAN"] = gdk.MAN
    cursor_names["MIDDLEBUTTON"] = gdk.MIDDLEBUTTON
    cursor_names["MOUSE"] = gdk.MOUSE
    cursor_names["PENCIL"] = gdk.PENCIL
    cursor_names["PIRATE"] = gdk.PIRATE
    cursor_names["PLUS"] = gdk.PLUS
    cursor_names["QUESTION_ARROW"] = gdk.QUESTION_ARROW
    cursor_names["RIGHT_PTR"] = gdk.RIGHT_PTR
    cursor_names["RIGHT_SIDE"] = gdk.RIGHT_SIDE
    cursor_names["RIGHT_TEE"] = gdk.RIGHT_TEE
    cursor_names["RIGHTBUTTON"] = gdk.RIGHTBUTTON
    cursor_names["RTL_LOGO"] = gdk.RTL_LOGO
    cursor_names["SAILBOAT"] = gdk.SAILBOAT
    cursor_names["SB_DOWN_ARROW"] = gdk.SB_DOWN_ARROW
    cursor_names["SB_H_DOUBLE_ARROW"] = gdk.SB_H_DOUBLE_ARROW
    cursor_names["SB_LEFT_ARROW"] = gdk.SB_LEFT_ARROW
    cursor_names["SB_RIGHT_ARROW"] = gdk.SB_RIGHT_ARROW
    cursor_names["SB_UP_ARROW"] = gdk.SB_UP_ARROW
    cursor_names["SB_V_DOUBLE_ARROW"] = gdk.SB_V_DOUBLE_ARROW
    cursor_names["SHUTTLE"] = gdk.SHUTTLE
    cursor_names["SIZING"] = gdk.SIZING
    cursor_names["SPIDER"] = gdk.SPIDER
    cursor_names["SPRAYCAN"] = gdk.SPRAYCAN
    cursor_names["STAR"] = gdk.STAR
    cursor_names["TARGET"] = gdk.TARGET
    cursor_names["TCROSS"] = gdk.TCROSS
    cursor_names["TOP_LEFT_ARROW"] = gdk.TOP_LEFT_ARROW
    cursor_names["TOP_LEFT_CORNER"] = gdk.TOP_LEFT_CORNER
    cursor_names["TOP_RIGHT_CORNER"] = gdk.TOP_RIGHT_CORNER
    cursor_names["TOP_SIDE"] = gdk.TOP_SIDE
    cursor_names["TOP_TEE"] = gdk.TOP_TEE
    cursor_names["TREK"] = gdk.TREK
    cursor_names["UL_ANGLE"] = gdk.UL_ANGLE
    cursor_names["UMBRELLA"] = gdk.UMBRELLA
    cursor_names["UR_ANGLE"] = gdk.UR_ANGLE
    cursor_names["WATCH"] = gdk.WATCH
    cursor_names["XTERM"] = gdk.XTERM
