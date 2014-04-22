# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("keyboard", "win32")

import win32con         #@UnresolvedImport
import win32api         #@UnresolvedImport
from xpra.server.keyboard_config_base import KeyboardConfigBase


class KeyboardConfig(KeyboardConfigBase):

    def __init__(self):
        KeyboardConfigBase.__init__(self)

    def __repr__(self):
        return "win32.KeyboardConfig"

    def get_info(self):
        info = KeyboardConfigBase.get_info(self)
        return info


    def parse_options(self, props):
        return KeyboardConfigBase.parse_options(self, props)

    def get_keycode(self, client_keycode, keyname, modifiers):
        keycode = KEYCODES.get(keyname, -1)
        log("get_keycode%s=%s", (client_keycode, keyname, modifiers), keycode)
        return keycode

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        log("make_keymask_match%s", (modifier_list, ignored_modifier_keycode, ignored_modifier_keynames))
        mods = self.get_modifiers_state()
        log("modifiers_state=%s", mods)
        log("GetKeyboardState=%s", [int(x!=0) for x in win32api.GetKeyboardState()])


    def get_modifiers_state(self):
        mods = set()
        for vk, mod in MOD_KEYS.items():
            if win32api.GetAsyncKeyState(vk)!=0:
                mods.add(mod)
        return list(mods)

MOD_KEYS = {
    win32con.VK_LSHIFT      : "shift",
    win32con.VK_RSHIFT      : "shift",
    win32con.VK_LCONTROL    : "control",
    win32con.VK_RCONTROL    : "control",
    win32con.VK_CAPITAL     : "lock",
}

#we currently assume that all key events are sent using X11 names,
#so we need to translate them to win32 VK constants
#even when the client and server are both win32...
#FIXME: support native untranslated win32 values,
# either using a special capability,
# or by adding a new argument to keypress packets
VIRTUAL_KEYS = {
    #"Mappable" codes
    "EXECUTE"               : "Execute",
    "EXSEL"                 : "Ex",
    #no useful mapping:
    "ICO_CLEAR"             : "IcoClr",
    "ICO_HELP"              : "Help",
    "MULTIPLY"              : "KP_Multiply",
    "NONAME"                : "NoSymbol",
    "NUMPAD0"               : "KP_0",
    "NUMPAD1"               : "KP_1",
    "NUMPAD2"               : "KP_2",
    "NUMPAD3"               : "KP_3",
    "NUMPAD4"               : "KP_4",
    "NUMPAD5"               : "KP_5",
    "NUMPAD6"               : "KP_6",
    "NUMPAD7"               : "KP_7",
    "NUMPAD8"               : "KP_8",
    "NUMPAD9"               : "KP_9",
    "OEM_1"                 : "OEM_1",
    "OEM_102"               : "OEM_102",
    "OEM_2"                 : "OEM_2",
    "OEM_3"                 : "OEM_3",
    "OEM_4"                 : "OEM_4",
    "OEM_5"                 : "OEM_5",
    "OEM_6"                 : "OEM_6",
    "OEM_7"                 : "OEM_7",
    "OEM_8"                 : "OEM_8",
    "OEM_ATTN"              : "Oem",
    "OEM_AUTO"              : "Auto",
    "OEM_AX"                : "Ax",
    "OEM_BACKTAB"           : "BackSpace",
    "OEM_CLEAR"             : "OemClr",
    "OEM_COMMA"             : "OEM_COMMA",
    "OEM_COPY"              : "Copy",
    "OEM_CUSEL"             : "Cu",
    "OEM_ENLW"              : "Enlw",
    "OEM_FINISH"            : "Finish",
    "OEM_FJ_LOYA"           : "Loya",
    "OEM_FJ_MASSHOU"        : "Mashu",
    "OEM_FJ_ROYA"           : "Roya",
    "OEM_FJ_TOUROKU"        : "Touroku",
    "OEM_JUMP"              : "Jump",
    "OEM_MINUS"             : "OEM_MINUS",
    "OEM_PA1"               : "OemPa1",
    "OEM_PA2"               : "OemPa2",
    "OEM_PA3"               : "OemPa3",
    "OEM_PERIOD"            : "period",
    "OEM_PLUS"              : "plus",
    "OEM_RESET"             : "Reset",
    "OEM_WSCTRL"            : "WsCtrl",
    "PA1"                   : "Pa1",
    #missing:?
    #"PACKET"                : "Packet",
    "PLAY"                  : "Play",
    "PROCESSKEY"            : "Process",
    "RETURN"                : "Return",
    "SELECT"                : "Select",
    "SEPARATOR"             : "Separator",
    "SPACE"                 : "Space",
    "SUBTRACT"              : "minus",
    "TAB"                   : "Tab",
    "ZOOM"                  : "Zoom",
    #"Non-mappable" codes
    "BROWSER_FAVORITES"     : "XF86Favorites",
    "BROWSER_FORWARD"       : "XF86Forward",
    "BROWSER_HOME"          : "XF86HomePage",
    "BROWSER_REFRESH"       : "XF86Reload",
    "BROWSER_SEARCH"        : "XF86Search",
    "BROWSER_STOP"          : "XF86Suspend",
    "CAPITAL"               : "Caps_Lock",
    "CONVERT"               : "Convert",
    "DELETE"                : "Delete",
    "DOWN"                  : "Down",
    "END"                   : "End",
    "F1"                    : "F1",
    "F10"                   : "F10",
    "F11"                   : "F11",
    "F12"                   : "F12",
    "F13"                   : "F13",
    "F14"                   : "F14",
    "F15"                   : "F15",
    "F16"                   : "F16",
    "F17"                   : "F17",
    "F18"                   : "F18",
    "F19"                   : "F19",
    "F2"                    : "F2",
    "F20"                   : "F20",
    "F21"                   : "F21",
    "F22"                   : "F22",
    "F23"                   : "F23",
    "F24"                   : "F24",
    "F3"                    : "F3",
    "F4"                    : "F4",
    "F5"                    : "F5",
    "F6"                    : "F6",
    "F7"                    : "F7",
    "F8"                    : "F8",
    "F9"                    : "F9",
    "FINAL"                 : "Final",
    "HELP"                  : "Help",
    "HOME"                  : "Home",
    "ICO_00"                : "Ico00",
    "INSERT"                : "Insert",
    "JUNJA"                 : "Junja",
    "KANA"                  : "Kana",
    "KANJI"                 : "Kanji",
    "LAUNCH_APP1"           : "XF86LaunchA",
    "LAUNCH_APP2"           : "XF86LaunchB",
    "LAUNCH_MAIL"           : "XF86Mail",
    "LAUNCH_MEDIA_SELECT"   : "XF86AudioMedia",
    "LBUTTON"               : "Left",
    "LCONTROL"              : "Left",
    "LEFT"                  : "Left",
    "LMENU"                 : "Left",
    "LSHIFT"                : "Shift_L",
    "LWIN"                  : "Left",
    "MBUTTON"               : "Middle",
    "MEDIA_NEXT_TRACK"      : "Next",
    "MEDIA_PLAY_PAUSE"      : "Play",
    "MEDIA_PREV_TRACK"      : "Previous",
    "MEDIA_STOP"            : "Stop",
    "MODECHANGE"            : "Mode",
    "NEXT"                  : "Page",
    "NONCONVERT"            : "Non",
    "NUMLOCK"               : "Num",
    "OEM_FJ_JISHO"          : "Jisho",
    "PAUSE"                 : "Pause",
    "PRINT"                 : "Print",
    "PRIOR"                 : "Page",
    "RBUTTON"               : "Right",
    "RCONTROL"              : "Right",
    "RIGHT"                 : "Right",
    "RMENU"                 : "Menu",
    "RSHIFT"                : "Shift_R",
    "RWIN"                  : "Right",
    "SCROLL"                : "Scroll_Lock",
    "SLEEP"                 : "XF86Sleep",
    "SNAPSHOT"              : "Print",
    "UP"                    : "Up",
    "VOLUME_DOWN"           : "XF86AudioLowerVolume",
    "VOLUME_MUTE"           : "XF86AudioMute",
    "VOLUME_UP"             : "XF86AudioRaiseVolume",
    "XBUTTON1"              : "X1",
    "XBUTTON2"              : "X2",
}

#these aren't defined in win32con...
DEFS = {
    "SLEEP"                 : 0x5F,
    "OEM_FJ_JISHO"          : 0x92,
    "OEM_FJ_MASSHOU"        : 0x93,
    "OEM_FJ_TOUROKU"        : 0x94,
    "OEM_FJ_LOYA"           : 0x95,
    "OEM_FJ_ROYA"           : 0x96,
    "BROWSER_SEARCH"        : 0xAA,
    "BROWSER_REFRESH"       : 0xA8,
    "BROWSER_STOP"          : 0xA9,
    "BROWSER_FAVORITES"     : 0xAB,
    "BROWSER_HOME"          : 0xAC,
    "MEDIA_STOP"            : 0xB2,
    "LAUNCH_MAIL"           : 0xB4,
    "LAUNCH_MEDIA_SELECT"   : 0xB5,
    "LAUNCH_APP1"           : 0xB6,
    "LAUNCH_APP2"           : 0xB7,
    "OEM_PLUS"              : 0xBB,
    "OEM_COMMA"             : 0xBC,
    "OEM_MINUS"             : 0xBD,
    "OEM_PERIOD"            : 0xBE,
    "OEM_1"                 : 0xBA,
    "OEM_2"                 : 0xBF,
    "OEM_3"                 : 0xC0,
    "OEM_4"                 : 0xDB,
    "OEM_5"                 : 0xDC,
    "OEM_6"                 : 0xDD,
    "OEM_7"                 : 0xDE,
    "OEM_8"                 : 0xDF,
    "OEM_AUTO"              : 0xF3,
    "OEM_COPY"              : 0xF2,
    "OEM_AX"                : 0xE1,
    "OEM_102"               : 0xE2,
    "ICO_HELP"              : 0xE3,
    "ICO_00"                : 0xE4,
    "ICO_CLEAR"             : 0xE6,
    "OEM_RESET"             : 0xE9,
    "OEM_JUMP"              : 0xEA,
    "OEM_PA1"               : 0xEB,
    "OEM_PA2"               : 0xEC,
    "OEM_PA3"               : 0xED,
    "OEM_WSCTRL"            : 0xEE,
    "OEM_CUSEL"             : 0xEF,
    "OEM_ATTN"              : 0xF0,
    "OEM_FINISH"            : 0xF1,
    "OEM_ENLW"              : 0xF4,
    "OEM_BACKTAB"           : 0xF5,
}

#lookup the constants:
KEYCODES = {}
for vk, name in VIRTUAL_KEYS.items():
    vk_name = "VK_%s" % vk
    if hasattr(win32con, vk_name):
        KEYCODES[name] = getattr(win32con, vk_name)
    elif vk in DEFS:
        #fallback to our hardcoded definitions:
        KEYCODES[name] = DEFS[vk]
    else:
        log.warn("missing key constant: %s", vk_name)
for c in "abcdefghijklmnopqrstuvwxyz":
    KEYCODES[c] = ord(c)
    KEYCODES[c.upper()] = ord(c.upper())
for c in "0123456789":
    KEYCODES[c] = ord(c)
log("KEYCODES: %s", KEYCODES)
