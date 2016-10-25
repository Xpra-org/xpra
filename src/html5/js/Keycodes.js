/*
 * This file is part of Xpra.
 * Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
 * Licensed under MPL 2.0, see:
 * http://www.mozilla.org/MPL/2.0/
 *
 */


/**
 * Maps web keycodes to the X11 keysym so we can generate a matching X11 keymap.
 *
 * TODO: some values are missing..
 */
CHARCODE_TO_NAME = {
	8	: "BackSpace",
	9	: "Tab",
	12	: "KP_Begin",
	13	: "Return",
	16	: "Shift_L",
	17	: "Control_L",
	18	: "Alt_L",
	19	: "Pause",			//pause/break
	20	: "Caps_Lock",
	27	: "Escape",
	31	: "Mode_switch",
	32	: "space",
	33	: "Prior",			//Page Up
	34	: "Next",			//Page Down
	35	: "End",
	36	: "Home",
	37	: "Left",
	38	: "Up",
	39	: "Right",
	40	: "Down",
	42	: "Print",
	45	: "Insert",
	46	: "Delete",
	58	: "colon",
	59	: "semicolon",
	60	: "less",
	61	: "equal",
	62	: "greater",
	63	: "question",
	64	: "at",
	91	: "Menu",			//Left Window Key
	92	: "Menu",			//Right Window Key
	93	: "KP_Enter",		//"select key"?
	106	: "KP_Multiply",
	107	: "KP_Add",
	109	: "KP_Subtract",
	110	: "KP_Delete",
	111	: "KP_Divide",
	144	: "Num_Lock",
	145	: "Scroll_Lock",
	160	: "dead_circumflex",
	167 : "underscore",
	161	: "exclam",
	162	: "quotedbl",
	163	: "numbersign",
	164	: "dollar",
	165	: "percent",
	166	: "ampersand",
	167	: "underscore",
	168 : "parenleft",
	169 : "parenright",
	170 : "asterisk",
	171	: "plus",
	172	: "bar",
	173	: "minus",
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
	219	: "bracketleft",
	220	: "backslash",
	221	: "bracketright",
	222	: "apostrophe",
}
for (var i=0; i<26; i++) {
	CHARCODE_TO_NAME[65+i] = "abcdefghijklmnopqrstuvwxyz"[i];
}
for (i=0; i<10; i++) {
	CHARCODE_TO_NAME[48+i] = ""+i;
	CHARCODE_TO_NAME[96+i] = ""+i;
	//fix for OSX numpad?
	//CHARCODE_TO_NAME[96+i] = "KP_"+i;
}
for (i=1; i<=24; i++) {
	CHARCODE_TO_NAME[111+i] = "F"+i;
}


/**
 * Converts an event into a list of modifiers.
 *
 * @param event
 * @returns {Array} of strings
 */
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
