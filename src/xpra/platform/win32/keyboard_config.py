# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("keyboard", "win32")

from xpra.platform.win32 import constants as win32con
from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.platform.win32.common import MapVirtualKeyW, GetAsyncKeyState, VkKeyScanW, keybd_event


MAPVK_VK_TO_VSC = 0
def fake_key(keycode, press):
    if keycode<=0:
        log.warn("no keycode found for %s", keycode)
        return
    #KEYEVENTF_SILENT = 0X4
    flags = 0
    if not press:
        flags |= win32con.KEYEVENTF_KEYUP
    #get the scancode:
    scancode = MapVirtualKeyW(keycode, MAPVK_VK_TO_VSC)
    #see: http://msdn.microsoft.com/en-us/library/windows/desktop/ms646304(v=vs.85).aspx
    log("fake_key(%s, %s) calling keybd_event(%s, %s, %s, 0)", keycode, press, keycode, scancode, flags)
    keybd_event(keycode, scancode, flags, 0)


class KeyboardConfig(KeyboardConfigBase):

    def __init__(self):
        KeyboardConfigBase.__init__(self)

    def __repr__(self):
        return "win32.KeyboardConfig"


    def get_keycode(self, client_keycode, keyname, modifiers):
        keycode = KEYCODES.get(keyname, -1)
        log("get_keycode%s=%s", (client_keycode, keyname, modifiers), keycode)
        return keycode

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        log("make_keymask_match%s", (modifier_list, ignored_modifier_keycode, ignored_modifier_keynames))
        log("keys pressed=%s", ",".join(str(VK_NAMES.get(i, i)) for i in range(256) if GetAsyncKeyState(i)>0))
        current = set(self.get_current_mask())
        wanted = set(modifier_list or [])
        log("make_keymask_match: current mask=%s, wanted=%s, ignoring=%s/%s", current, wanted, ignored_modifier_keycode, ignored_modifier_keynames)
        if current==wanted:
            return
        def is_ignored(modifier):
            if not ignored_modifier_keynames:
                return False
            for keyname in ignored_modifier_keynames:       #ie: ["Control_R"]
                keycode = KEYCODES.get(keyname, 0)          #ie: "Control_R" -> VK_RCONTROL
                if keycode>0:
                    key_mod = MOD_KEYS.get(keycode)         #ie: "control"
                    if key_mod==modifier:
                        return True
            return False    #not found

        def change_mask(modifiers, press, info):
            for modifier in modifiers:
                if is_ignored(modifier):
                    log("change_mask: ignoring %s", modifier)
                    continue
                #find the keycode:
                for k,v in MOD_KEYS.items():
                    if ignored_modifier_keycode and ignored_modifier_keycode==k:
                        log("change_mask: ignoring %s / %s", VK_NAMES.get(k, k), v)
                        continue
                    if v==modifier:
                        #figure out if this is the one that needs toggling:
                        is_pressed = GetAsyncKeyState(k)
                        log("make_keymask_match: %s pressed=%s", k, is_pressed)
                        if bool(is_pressed)!=press:
                            log("make_keymask_match: using %s to %s %s", VK_NAMES.get(k, k), info, modifier)
                            fake_key(k, press)
                            break
        change_mask(current.difference(wanted), False,  "remove")
        change_mask(wanted.difference(current), True,   "add")

    def get_current_mask(self):
        mods = set()
        for vk, mod in MOD_KEYS.items():
            if GetAsyncKeyState(vk)!=0:
                mods.add(mod)
        return list(mods)


MOD_KEYS = {
    win32con.VK_LSHIFT      : "shift",
    win32con.VK_RSHIFT      : "shift",
    win32con.VK_LCONTROL    : "control",
    win32con.VK_RCONTROL    : "control",
    win32con.VK_CAPITAL     : "lock",
    win32con.VK_LMENU       : "mod1",       #Alt_L
    win32con.VK_RMENU       : "mod1",       #Alt_R
    win32con.VK_CAPITAL     : "lock",
    win32con.VK_NUMLOCK     : "num",
}

#we currently assume that all key events are sent using X11 names,
#so we need to translate them to win32 VK constants
#even when the client and server are both win32...
#FIXME: support native untranslated win32 values,
# either using a special capability,
# or by adding a new argument to keypress packets
VIRTUAL_KEYS = [
    #"Mappable" codes
    ("EXECUTE",                 "Execute"),
    ("EXSEL",                   "Ex"),
    #no useful mapping:
    ("ICO_CLEAR",               "IcoClr"),
    ("ICO_HELP",                "Help"),
    ("DIVIDE",                  "KP_Divide"),
    ("MULTIPLY",                "KP_Multiply"),
    ("SUBTRACT",                "KP_Subtract"),
    ("ADD",                     "KP_Add"),
    ("NONAME",                  "NoSymbol"),
    ("RETURN",                  "KP_Enter"),
    ("NUMPAD0",                 "KP_0"),
    ("NUMPAD1",                 "KP_1"),
    ("NUMPAD2",                 "KP_2"),
    ("NUMPAD3",                 "KP_3"),
    ("NUMPAD4",                 "KP_4"),
    ("NUMPAD5",                 "KP_5"),
    ("NUMPAD6",                 "KP_6"),
    ("NUMPAD7",                 "KP_7"),
    ("NUMPAD8",                 "KP_8"),
    ("NUMPAD9",                 "KP_9"),
    ("OEM_PERIOD",              "KP_Decimal"),
    ("OEM_1",                   "OEM_1"),
    ("OEM_102",                 "OEM_102"),
    ("OEM_2",                   "OEM_2"),
    ("OEM_3",                   "OEM_3"),
    ("OEM_4",                   "OEM_4"),
    ("OEM_5",                   "OEM_5"),
    ("OEM_6",                   "OEM_6"),
    ("OEM_7",                   "OEM_7"),
    ("OEM_8",                   "OEM_8"),
    ("OEM_ATTN",                "Oem"),
    ("OEM_AUTO",                "Auto"),
    ("OEM_AX",                  "Ax"),
    #("OEM_BACKTAB",             "BackSpace"),
    ("BACK",                    "BackSpace"),
    ("ESCAPE",                  "Escape"),
    ("OEM_CLEAR",               "OemClr"),
    ("OEM_COMMA",               "OEM_COMMA"),
    ("OEM_COPY",                "Copy"),
    ("OEM_CUSEL",               "Cu"),
    ("OEM_ENLW",                "Enlw"),
    ("OEM_FINISH",              "Finish"),
    ("OEM_FJ_LOYA",             "Loya"),
    ("OEM_FJ_MASSHOU",          "Mashu"),
    ("OEM_FJ_ROYA",             "Roya"),
    ("OEM_FJ_TOUROKU",          "Touroku"),
    ("OEM_JUMP",                "Jump"),
    ("OEM_MINUS",               "OEM_MINUS"),
    ("OEM_PA1",                 "OemPa1"),
    ("OEM_PA2",                 "OemPa2"),
    ("OEM_PA3",                 "OemPa3"),
    #("OEM_PLUS"              : "equal"),
    ("OEM_RESET",               "Reset"),
    ("OEM_WSCTRL",              "WsCtrl"),
    ("PA1",                     "Pa1"),
    #("OEM_102"               : "backslash"),
    #missing:?
    #("PACKET"                : "Packet"),
    ("PLAY",                    "Play"),
    ("PROCESSKEY",              "Process"),
    ("RETURN",                  "Return"),
    ("SELECT",                  "Select"),
    ("SEPARATOR",               "Separator"),
    ("SPACE",                   "Space"),
    ("SPACE",                   "space"),
    ("SUBTRACT",                "minus"),
    ("TAB",                     "Tab"),
    ("ZOOM",                    "Zoom"),
    #"Non-mappable" codes
    ("BROWSER_FAVORITES",       "XF86Favorites"),
    ("BROWSER_FORWARD",         "XF86Forward"),
    ("BROWSER_HOME",            "XF86HomePage"),
    ("BROWSER_REFRESH",         "XF86Reload"),
    ("BROWSER_SEARCH",          "XF86Search"),
    ("BROWSER_STOP",            "XF86Suspend"),
    ("CAPITAL",                 "Caps_Lock"),
    ("CONVERT",                 "Convert"),
    ("DELETE",                  "Delete"),
    ("DOWN",                    "Down"),
    ("END",                     "End"),
    ("F1",                      "F1"),
    ("F10",                     "F10"),
    ("F11",                     "F11"),
    ("F12",                     "F12"),
    ("F13",                     "F13"),
    ("F14",                     "F14"),
    ("F15",                     "F15"),
    ("F16",                     "F16"),
    ("F17",                     "F17"),
    ("F18",                     "F18"),
    ("F19",                     "F19"),
    ("F2",                      "F2"),
    ("F20",                     "F20"),
    ("F21",                     "F21"),
    ("F22",                     "F22"),
    ("F23",                     "F23"),
    ("F24",                     "F24"),
    ("F3",                      "F3"),
    ("F4",                      "F4"),
    ("F5",                      "F5"),
    ("F6",                      "F6"),
    ("F7",                      "F7"),
    ("F8",                      "F8"),
    ("F9",                      "F9"),
    ("FINAL",                   "Final"),
    ("HELP",                    "Help"),
    ("HOME",                    "Home"),
    ("ICO_00",                  "Ico00"),
    ("INSERT",                  "Insert"),
    ("JUNJA",                   "Junja"),
    ("KANA",                    "Kana"),
    ("KANJI",                   "Kanji"),
    ("LAUNCH_APP1",             "XF86LaunchA"),
    ("LAUNCH_APP2",             "XF86LaunchB"),
    ("LAUNCH_MAIL",             "XF86Mail"),
    ("LAUNCH_MEDIA_SELECT",     "XF86AudioMedia"),
    ("LCONTROL",                "Control_L"),
    ("LEFT",                    "Left"),
    ("LMENU",                   "Alt_L"),
    ("LSHIFT",                  "Shift_L"),
    ("LWIN",                    "Super_L"),
    ("MBUTTON",                 "Middle"),
    ("MEDIA_NEXT_TRACK",        "Next"),
    ("MEDIA_PLAY_PAUSE",        "Play"),
    ("MEDIA_PREV_TRACK",        "Previous"),
    ("MEDIA_STOP",              "Stop"),
    ("MODECHANGE",              "Mode"),
    ("NEXT",                    "Page"),
    ("NONCONVERT",              "Non"),
    ("NUMLOCK",                 "Num"),
    ("OEM_FJ_JISHO",            "Jisho"),
    ("PAUSE",                   "Pause"),
    ("PRINT",                   "Print"),
    ("PRIOR",                   "Page"),
    ("RCONTROL",                "Control_R"),
    ("RIGHT",                   "Right"),
    ("RMENU",                   "Alt_R"),
    ("RSHIFT",                  "Shift_R"),
    ("RWIN",                    "Super_R"),
    ("SCROLL",                  "Scroll_Lock"),
    ("SLEEP",                   "XF86Sleep"),
    ("SNAPSHOT",                "Print"),
    ("UP",                      "Up"),
    ("VOLUME_DOWN",             "XF86AudioLowerVolume"),
    ("VOLUME_MUTE",             "XF86AudioMute"),
    ("VOLUME_UP",               "XF86AudioRaiseVolume"),
    ("XBUTTON1",                "X1"),
    ("XBUTTON2",                "X2"),
    ]

KEYSYM_DEFS = {
               "bracketleft"        : u"[",
               "bracketright"       : u"]",
               "grave"              : u"`",
               "braceleft"          : u"{",
               "braceright"         : u"}",
               "colon"              : u":",
               "semicolon"          : u";",
               "apostrophe"         : u"'",
               "at"                 : u"@",
               "numbersign"         : u"#",
               "comma"              : u",",
               "less"               : u"<",
               "equal"              : u"=",
               "greater"            : u">",
               "period"             : u".",
               "slash"              : u"/",
               "question"           : u"?",
               "bar"                : u"|",
               "exclam"             : u"!",
               "quotedbl"           : u'"',
               "sterling"           : u"£",
               "dollar"             : u"$",
               "percent"            : u"%",
               "asciicircum"        : u"^",
               "ampersand"          : u"&",
               "asterisk"           : u"*",
               "parenleft"          : u"(",
               "parenright"         : u")",
               "underscore"         : u"_",
               "backslash"          : u"\\",
               "asciitilde"         : u"~",
               "notsign"            : u"¬",
               "plus"               : u"+",
               "eacute"             : u"é",
               "onesuperior"        : u"¹",
               "twosuperior"        : u"²",
               "egrave"             : u"è",
               "ccedilla"           : u"ç",
               "agrave"             : u"à",
               "dead_circumflex"    : u"^",
               "ugrave"             : u"ù",
               "mu"                 : u"µ",
               "section"            : u"§",
               "currency"           : u"¤",
               "exclamdown"         : u"¡",
               "oneeighth"          : u"⅛",
               "threeeighths"       : u"⅜",
               "fiveeighths"        : u"⅝",
               "seveneighths"       : u"⅞",
               "trademark"          : u"™",
               "plusminus"          : u"±",
               "degree"             : u"°",
               "questiondown"       : u"¿",
               "dead_ogonek"        : u"˛",
               "dead_macron"        : u"¯",
               "dead_abovering"     : u"°",
               "dead_breve"         : u"˘",
               "dead_caron"         : u"ˇ",
               "masculine"          : u"º",
               "dead_abovedot"      : u"˙",
               "division"           : u"÷",
               "multiply"           : u"×",
               "brokenbar"          : u"¦",
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

VK_NAMES = {}
for name in (x for x in dir(win32con) if x.startswith("VK_")):
    VK_NAMES[getattr(win32con, name)] = name
for name, val in DEFS.items():
    VK_NAMES[val] = "VK_"+name
log("VK_NAMES=%s", VK_NAMES)

#lookup the constants:
KEYCODES = {}
for vk, name in VIRTUAL_KEYS:
    vk_name = "VK_%s" % vk
    if hasattr(win32con, vk_name):
        val = getattr(win32con, vk_name)
        KEYCODES[name] = val
        log("KEYCODES[%s]=win32con.%s=%s", name, vk_name, val)
    elif vk in DEFS:
        #fallback to our hardcoded definitions:
        val = DEFS[vk]
        KEYCODES[name] = val
        log("KEYCODES[%s]=%s=%s", name, vk, val)
    else:
        log.warn("missing key constant: %s", vk_name)

for name, char in KEYSYM_DEFS.items():
    try:
        bchar = char.encode("latin1")
    except:
        continue
    if len(char)!=1:
        log.warn("invalid character '%s' : '%s' (len=%i)", name, char, len(char))
        continue
    v = VkKeyScanW(char)
    vk_code = v & 0xff
    if vk_code>0 and vk_code!=0xff:
        log("KEYCODE[%s]=%i (%s)", char, vk_code, name)
        KEYCODES[name] = vk_code

KEYCODES.update({
    "Shift_L"       : win32con.VK_LSHIFT,
    "Shift_R"       : win32con.VK_RSHIFT,
    "Control_L"     : win32con.VK_LCONTROL,
    "Control_R"     : win32con.VK_RCONTROL,
    "Caps_Lock"     : win32con.VK_CAPITAL,
    "Num_Lock"      : win32con.VK_NUMLOCK,
    "Scroll_Lock"   : win32con.VK_SCROLL,
    })

for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEYCODES[c] = ord(c)
    KEYCODES[c.lower()] = ord(c)
for c in "0123456789":
    KEYCODES[c] = ord(c)
log("KEYCODES: %s", KEYCODES)
