/*
 * This file is part of Xpra.
 * Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
 * Licensed under MPL 2.0, see:
 * http://www.mozilla.org/MPL/2.0/
 *
 * Maps web keycodes to the X11 keysym so we can generate a matching X11 keymap.
 * TODO: some values are missing..
 */

CHARCODE_TO_NAME = {
	8	: "BackSpace",
	9	: "Tab",
	13	: "Return",
	16	: "Shift_L",
	17	: "Control_L",
	18	: "Alt_L",
	19	: "Pause",			//pause/break
	20	: "Caps_Lock",
	27	: "Escape",
	33	: "Prior",			//Page Up
	34	: "Next",			//Page Down
	35	: "End",
	36	: "Home",
	37	: "Left",
	38	: "Up",
	39	: "Right",
	40	: "Down",
	45	: "Insert",
	46	: "Delete",
	91	: "Menu",			//Left Window Key
	92	: "Menu",			//Right Window Key
	93	: "KP_Enter",		//"select key"?
	96	: "KP_0",
	97	: "KP_1",
	98	: "KP_2",
	99	: "KP_3",
	100	: "KP_4",
	101	: "KP_5",
	102	: "KP_6",
	103	: "KP_7",
	104	: "KP_8",
	105	: "KP_9",
	106	: "KP_Multiply",
	107	: "KP_Add",
	109	: "KP_Subtract",
	110	: "KP_Delete",
	111	: "KP_Divide",
	112	: "F1",
	113	: "F2",
	114	: "F3",
	115	: "F4",
	116	: "F5",
	117	: "F6",
	118	: "F7",
	119	: "F8",
	120	: "F9",
	121	: "F10",
	122	: "F11",
	123	: "F12",
	144	: "Num_Lock",
	145	: "Scroll_Lock",
	167 : "underscore",
	168 : "parenleft",
	169 : "parenright",
	170 : "asterisk",
	172	: "pipe",
	174 : "braceleft",
	175 : "braceright",
	176 : "asciitilde",
	186	: "semicolon",
	187	: "equal",
	188	: "comma",
	189	: "minus",
	190	: "period",
	191	: "slash",
	192	: "grave",
	219	: "bracketright",
	220	: "backslash",
	221	: "bracketleft",
	222	: "apostrophe",
}
for (var i=0; i<26; i++) {
	CHARCODE_TO_NAME[65+i] = "abcdefghijklmnopqrstuvwxyz"[i];
}


function get_event_modifiers(event) {
	var modifiers = [];
	if (event.modifiers) {
		if (event.modifiers & Event.ALT_MASK)
			modifiers.push("alt");
		if (event.modifiers & Event.CONTROL_MASK)
			modifiers.push("control");
		if (event.modifiers & Event.SHIFT_MASK)
			modifiers.push("shift");
		if (event.modifiers & Event.META_MASK)
			modifiers.push("meta");
    } else {
		if (event.altKey)
			modifiers.push("alt");
		if (event.ctrlKey)
			modifiers.push("control");
		if (event.metaKey)
			modifiers.push("meta");
		if (event.shiftKey)
			modifiers.push("shift");
	}
	return modifiers;
}
