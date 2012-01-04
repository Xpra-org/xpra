# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import pygtk
pygtk.require("2.0")
import gtk
_display = gtk.gdk.get_display()
assert _display, "cannot open the display with GTK, is DISPLAY set?"
_root = gtk.gdk.get_default_root_window()


from wimpiggy.keys import grok_modifier_map
from wimpiggy.lowlevel import get_modifier_map, set_xmodmap     #@UnresolvedImport

from wimpiggy.log import Logger
log = Logger()
import logging
logging.root.setLevel(logging.INFO)
logging.root.addHandler(logging.StreamHandler(sys.stderr))


def main():
    log("main")
    modmap = get_modifier_map(_root)
    log.info("modifier map=%s", modmap)
    grokked = grok_modifier_map(_root)
    log.info("grokked modifier map=%s", grokked)
    xmodmap_data = get_xmodmap()
    failed = set_xmodmap(_root, xmodmap_data.splitlines())
    log.info("unset xmodmap: %s", failed)



def get_xmodmap():
    return """clear Lock
clear Ctrl
clear mod1
clear mod4
clear shift
""" + get_raw_xmodmap() + """
add Ctrl = Control_L Control_R
add mod1 = Alt_L Alt_R
add mod4 = Super_L Super_R
add shift = Shift_L Shift_R
"""

def get_raw_xmodmap():
    return """
keycode   8 = Mode_switch NoSymbol Mode_switch
keycode   9 = Escape NoSymbol Escape
keycode  10 = 1 exclam 1 exclam onesuperior exclamdown
keycode  11 = 2 quotedbl 2 quotedbl twosuperior oneeighth
keycode  12 = 3 sterling 3 sterling threesuperior sterling
keycode  13 = 4 dollar 4 dollar EuroSign onequarter
keycode  14 = 5 percent 5 percent onehalf threeeighths
keycode  15 = 6 asciicircum 6 asciicircum threequarters fiveeighths
keycode  16 = 7 ampersand 7 ampersand braceleft seveneighths
keycode  17 = 8 asterisk 8 asterisk bracketleft trademark
keycode  18 = 9 parenleft 9 parenleft bracketright plusminus
keycode  19 = 0 parenright 0 parenright braceright degree
keycode  20 = minus underscore minus underscore backslash questiondown
keycode  21 = equal plus equal plus dead_cedilla dead_ogonek
keycode  22 = BackSpace NoSymbol BackSpace
keycode  23 = Tab ISO_Left_Tab Tab ISO_Left_Tab
keycode  24 = q Q q Q at Greek_OMEGA
keycode  25 = w W w W lstroke Lstroke
keycode  26 = e E e E e E
keycode  27 = r R r R paragraph registered
keycode  28 = t T t T tslash Tslash
keycode  29 = y Y y Y leftarrow yen
keycode  30 = u U u U downarrow uparrow
keycode  31 = i I i I rightarrow idotless
keycode  32 = o O o O oslash Oslash
keycode  33 = p P p P thorn THORN
keycode  34 = bracketleft braceleft bracketleft braceleft dead_diaeresis dead_abovering
keycode  35 = bracketright braceright bracketright braceright dead_tilde dead_macron
keycode  36 = Return NoSymbol Return
keycode  37 = Control_L NoSymbol Control_L
keycode  38 = a A a A ae AE
keycode  39 = s S s S ssharp section
keycode  40 = d D d D eth ETH
keycode  41 = f F f F dstroke ordfeminine
keycode  42 = g G g G eng ENG
keycode  43 = h H h H hstroke Hstroke
keycode  44 = j J j J j J
keycode  45 = k K k K kra ampersand
keycode  46 = l L l L lstroke Lstroke
keycode  47 = semicolon colon semicolon colon dead_acute dead_doubleacute
keycode  48 = apostrophe at apostrophe at dead_circumflex dead_caron
keycode  49 = grave notsign grave notsign bar bar
keycode  50 = Shift_L NoSymbol Shift_L
keycode  51 = numbersign asciitilde numbersign asciitilde dead_grave dead_breve
keycode  52 = z Z z Z guillemotleft less
keycode  53 = x X x X guillemotright greater
keycode  54 = c C c C cent copyright
keycode  55 = v V v V leftdoublequotemark leftsinglequotemark
keycode  56 = b B b B rightdoublequotemark rightsinglequotemark
keycode  57 = n N n N n N
keycode  58 = m M m M mu masculine
keycode  59 = comma less comma less horizconnector multiply
keycode  60 = period greater period greater periodcentered division
keycode  61 = slash question slash question dead_belowdot dead_abovedot
keycode  62 = Shift_R NoSymbol Shift_R
keycode  63 = KP_Multiply XF86ClearGrab KP_Multiply XF86ClearGrab
keycode  64 = Alt_L Meta_L Alt_L Meta_L
keycode  65 = space NoSymbol space
keycode  66 = Caps_Lock NoSymbol Caps_Lock
keycode  67 = F1 XF86Switch_VT_1 F1 XF86Switch_VT_1
keycode  68 = F2 XF86Switch_VT_2 F2 XF86Switch_VT_2
keycode  69 = F3 XF86Switch_VT_3 F3 XF86Switch_VT_3
keycode  70 = F4 XF86Switch_VT_4 F4 XF86Switch_VT_4
keycode  71 = F5 XF86Switch_VT_5 F5 XF86Switch_VT_5
keycode  72 = F6 XF86Switch_VT_6 F6 XF86Switch_VT_6
keycode  73 = F7 XF86Switch_VT_7 F7 XF86Switch_VT_7
keycode  74 = F8 XF86Switch_VT_8 F8 XF86Switch_VT_8
keycode  75 = F9 XF86Switch_VT_9 F9 XF86Switch_VT_9
keycode  76 = F10 XF86Switch_VT_10 F10 XF86Switch_VT_10
keycode  77 = Num_Lock NoSymbol Num_Lock
keycode  78 = Scroll_Lock NoSymbol Scroll_Lock
keycode  79 = KP_Home KP_7 KP_Home KP_7
keycode  80 = KP_Up KP_8 KP_Up KP_8
keycode  81 = KP_Prior KP_9 KP_Prior KP_9
keycode  82 = KP_Subtract XF86Prev_VMode KP_Subtract XF86Prev_VMode
keycode  83 = KP_Left KP_4 KP_Left KP_4
keycode  84 = KP_Begin KP_5 KP_Begin KP_5
keycode  85 = KP_Right KP_6 KP_Right KP_6
keycode  86 = KP_Add XF86Next_VMode KP_Add XF86Next_VMode
keycode  87 = KP_End KP_1 KP_End KP_1
keycode  88 = KP_Down KP_2 KP_Down KP_2
keycode  89 = KP_Next KP_3 KP_Next KP_3
keycode  90 = KP_Insert KP_0 KP_Insert KP_0
keycode  91 = KP_Delete KP_Decimal KP_Delete KP_Decimal
keycode  92 =
keycode  93 =
keycode  94 = backslash bar backslash bar bar brokenbar
keycode  95 = F11 XF86Switch_VT_11 F11 XF86Switch_VT_11
keycode  96 = F12 XF86Switch_VT_12 F12 XF86Switch_VT_12
keycode  97 = Home NoSymbol Home
keycode  98 = Up NoSymbol Up
keycode  99 = Prior NoSymbol Prior
keycode 100 = Left NoSymbol Left
keycode 101 =
keycode 102 = Right NoSymbol Right
keycode 103 = End NoSymbol End
keycode 104 = Down NoSymbol Down
keycode 105 = Next NoSymbol Next
keycode 106 = Insert NoSymbol Insert
keycode 107 = Delete NoSymbol Delete
keycode 108 = KP_Enter NoSymbol KP_Enter
keycode 109 = Control_R NoSymbol Control_R
keycode 110 = Pause Break Pause Break
keycode 111 = Print Sys_Req Print Sys_Req
keycode 112 = KP_Divide XF86Ungrab KP_Divide XF86Ungrab
keycode 113 = ISO_Level3_Shift Multi_key ISO_Level3_Shift Multi_key
keycode 114 =
keycode 115 = Super_L NoSymbol Super_L
keycode 116 = Super_R NoSymbol Super_R
keycode 117 = Menu NoSymbol Menu
keycode 118 =
keycode 119 =
keycode 120 =
keycode 121 =
keycode 122 =
keycode 123 =
keycode 124 = ISO_Level3_Shift NoSymbol ISO_Level3_Shift
keycode 125 = NoSymbol Alt_L NoSymbol Alt_L
keycode 126 = KP_Equal NoSymbol KP_Equal
keycode 127 = NoSymbol Super_L NoSymbol Super_L
keycode 128 = NoSymbol Hyper_L NoSymbol Hyper_L
keycode 129 = XF86AudioMedia NoSymbol XF86AudioMedia
keycode 130 =
keycode 131 =
keycode 132 =
keycode 133 =
keycode 134 = KP_Decimal KP_Decimal KP_Decimal KP_Decimal
keycode 135 =
keycode 136 =
keycode 137 =
keycode 138 =
keycode 139 =
keycode 140 =
keycode 141 =
keycode 142 =
keycode 143 =
keycode 144 = XF86AudioPrev NoSymbol XF86AudioPrev
keycode 145 =
keycode 146 =
keycode 147 =
keycode 148 =
keycode 149 =
keycode 150 = XF86Sleep NoSymbol XF86Sleep
keycode 151 =
keycode 152 =
keycode 153 = XF86AudioNext NoSymbol XF86AudioNext
keycode 154 =
keycode 155 =
keycode 156 = NoSymbol Meta_L NoSymbol Meta_L
keycode 157 =
keycode 158 =
keycode 159 =
keycode 160 = XF86AudioMute NoSymbol XF86AudioMute
keycode 161 = XF86Calculator NoSymbol XF86Calculator
keycode 162 = XF86AudioPlay XF86AudioPause XF86AudioPlay XF86AudioPause
keycode 163 =
keycode 164 = XF86AudioStop XF86Eject XF86AudioStop XF86Eject
keycode 165 =
keycode 166 =
keycode 167 =
keycode 168 =
keycode 169 =
keycode 170 = XF86Eject NoSymbol XF86Eject
keycode 171 =
keycode 172 =
keycode 173 =
keycode 174 = XF86AudioLowerVolume NoSymbol XF86AudioLowerVolume
keycode 175 =
keycode 176 = XF86AudioRaiseVolume NoSymbol XF86AudioRaiseVolume
keycode 177 =
keycode 178 = XF86WWW NoSymbol XF86WWW
keycode 179 =
keycode 180 =
keycode 181 =
keycode 182 =
keycode 183 =
keycode 184 =
keycode 185 =
keycode 186 =
keycode 187 =
keycode 188 =
keycode 189 =
keycode 190 =
keycode 191 =
keycode 192 =
keycode 193 =
keycode 194 =
keycode 195 =
keycode 196 =
keycode 197 =
keycode 198 =
keycode 199 =
keycode 200 =
keycode 201 =
keycode 202 =
keycode 203 =
keycode 204 = XF86Eject NoSymbol XF86Eject
keycode 205 =
keycode 206 =
keycode 207 =
keycode 208 =
keycode 209 =
keycode 210 =
keycode 211 =
keycode 212 =
keycode 213 =
keycode 214 = XF86Display NoSymbol XF86Display
keycode 215 = XF86KbdLightOnOff NoSymbol XF86KbdLightOnOff
keycode 216 = XF86KbdBrightnessDown NoSymbol XF86KbdBrightnessDown
keycode 217 = XF86KbdBrightnessUp NoSymbol XF86KbdBrightnessUp
keycode 218 =
keycode 219 =
keycode 220 =
keycode 221 =
keycode 222 = XF86PowerOff NoSymbol XF86PowerOff
keycode 223 = XF86Standby NoSymbol XF86Standby
keycode 224 =
keycode 225 =
keycode 226 =
keycode 227 = XF86WakeUp NoSymbol XF86WakeUp
keycode 228 =
keycode 229 = XF86Search NoSymbol XF86Search
keycode 230 = XF86Favorites NoSymbol XF86Favorites
keycode 231 = XF86Reload NoSymbol XF86Reload
keycode 232 = XF86Stop NoSymbol XF86Stop
keycode 233 = XF86Forward NoSymbol XF86Forward
keycode 234 = XF86Back NoSymbol XF86Back
keycode 235 = XF86MyComputer NoSymbol XF86MyComputer
keycode 236 = XF86Mail NoSymbol XF86Mail
keycode 237 = XF86AudioMedia NoSymbol XF86AudioMedia
keycode 238 =
keycode 239 =
keycode 240 =
keycode 241 =
keycode 242 =
keycode 243 =
keycode 244 = XF86Battery NoSymbol XF86Battery
keycode 245 =
keycode 246 = XF86WLAN NoSymbol XF86WLAN
keycode 247 =
keycode 248 =
keycode 249 =
keycode 250 =
keycode 251 =
keycode 252 =
keycode 253 =
keycode 254 =
keycode 255 =
"""


if __name__ == "__main__":
    main()
