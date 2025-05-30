# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from struct import Struct
from enum import IntEnum

# merge header and packet if packet is smaller than:
PIXEL_FORMAT: bytes = b"BBBBHHHBBBBBB"
CLIENT_INIT: bytes = b"!HH" + PIXEL_FORMAT + b"I"


class RFBClientMessage(IntEnum):
    """ client to server messages """
    SetPixelFormat = 0
    SetEncodings = 2
    FramebufferUpdateRequest = 3
    KeyEvent = 4
    PointerEvent = 5
    ClientCutText = 6
    # optional:
    FileTransfer = 7
    SetScale = 8
    SetServerInput = 9
    SetSW = 10
    TextChat = 11
    KeyFrameRequest = 12
    KeepAlive = 13
    SetScaleFactor = 15
    RequestSession = 20
    SetSession = 21
    NotifyPluginStreaming = 80
    VMWare = 127
    CarConnectivity = 128
    EnableContinuousUpdates = 150
    ClientFence = 248
    OliveCallControl = 249
    XVPClientMessage = 250
    SetDesktopSize = 251
    Tight = 252
    GIIClientMessage = 253
    # VMWARE = 254
    QEMUClientMessage = 255


CLIENT_PACKET_TYPE_STR: dict[int, str] = {}
for cm in RFBClientMessage:
    CLIENT_PACKET_TYPE_STR[cm.value] = cm.name

PACKET_STRUCT: dict[int, Struct] = {}
for msg, fmt in {
    RFBClientMessage.SetPixelFormat: b"!BBBB" + PIXEL_FORMAT,
    RFBClientMessage.SetEncodings: b"!BBH",
    RFBClientMessage.FramebufferUpdateRequest: b"!BBHHHH",
    RFBClientMessage.KeyEvent: b"!BBBBi",
    RFBClientMessage.PointerEvent: b"!BBHH",
    RFBClientMessage.ClientCutText: b"!BBBBi",
}.items():
    PACKET_STRUCT[msg] = Struct(fmt)


class RFBServerMessage(IntEnum):
    # server to client messages:
    FRAMEBUFFERUPDATE = 0
    SETCOLORMAPENTRIES = 1
    BELL = 2
    SERVERCUTTEXT = 3
    # optional:
    RESIZEFRAMEBUFFER1 = 4
    KEYFRAMEUPDATE = 4
    FILETRANSFER = 7
    TEXTCHAT = 11
    KEEPALIVE = 13
    RESIZEFRAMEBUFFER2 = 15
    VMWARE1 = 127
    CARCONNECTIVITY = 128
    ENDOFCONTINOUSUPDATES = 150
    SERVERSTATE = 173
    SERVERFENCE = 248
    OLIVECALLCONTROL = 249
    XVPSERVERMESSAGE = 250
    TIGHT = 252
    GIISERVERMESSAGE = 253
    VMWARE2 = 254
    QEMUSERVERMESSAGE = 255


SERVER_PACKET_TYPE_STR: dict[int, str] = {}
for sm in RFBServerMessage:
    SERVER_PACKET_TYPE_STR[sm.value] = sm.name


class RFBEncoding(IntEnum):
    RAW = 0
    COPYRECT = 1
    RRE = 2
    CORRE = 4
    HEXTILE = 5
    ZLIB = 6
    TIGHT = 7
    ZLIBHEX = 8
    TRLE = 15
    ZRLE = 16
    H264 = 20
    JPEG = 21
    JRLE = 22
    VAH264 = 23
    ZRLE2 = 24
    HITACHI_ZYWRLE = 17
    DESKTOPSIZE = -223
    LASTRECT = -224
    CURSOR = -239
    XCURSOR = -240
    QEMU_POINTER = -257
    QEMU_KEY = -258
    QEMU_AUDIO = -259
    TIGHT_PNG = -260
    GII = -305
    DESKTOPNAME = -307
    EXTENDEDDESKTOPSIZE = -308
    XVP = -309
    FENCE = -312
    CONTINUOUSUPDATES = -313
    CURSORWITHALPHA = -314
    VA_H264 = 0x48323634

    # -23 to -32    JPEG Quality Level Pseudo-encoding
    # -247 to -256    Compression Level Pseudo-encoding
    # -412 to -512    JPEG Fine-Grained Quality Level Pseudo-encoding
    # -763 to -768    JPEG Subsampling Level Pseudo-encoding


ENCODING_STR: dict[int, str] = {}
for e in RFBEncoding:
    ENCODING_STR[e.value] = e.name


class RFBAuth(IntEnum):
    INVALID = 0
    NONE = 1
    VNC = 2
    TIGHT = 16
    VeNCrypt = 19


AUTH_STR: dict[int, str] = {
    RFBAuth.INVALID: "Invalid",
    RFBAuth.NONE: "None",
    RFBAuth.VNC: "VNC",
    RFBAuth.TIGHT: "Tight",
    5: "RA2",
    6: "RA2ne",
    17: "Ultra",
    18: "TLS",
    RFBAuth.VeNCrypt: "VeNCrypt",
    20: "SASL",
    21: "MD5",
    22: "xvp",
}
for i in (3, 4):
    AUTH_STR[i] = "RealVNC"
for i in range(7, 16):
    AUTH_STR[i] = "RealVNC"
for i in range(128, 255):
    AUTH_STR[i] = "RealVNC"
for i in range(30, 35):
    AUTH_STR[i] = "Apple"

RFB_KEYNAMES: dict[int, str] = {
    0xff08: "BackSpace",
    0xff09: "Tab",
    0xff0d: "Return",
    0xff1b: "Escape",
    0xff63: "Insert",
    0xffff: "Delete",
    0xff50: "Home",
    0xff57: "End",
    0xff55: "PageUp",
    0xff56: "PageDown",
    0xff51: "Left",
    0xff52: "Up",
    0xff53: "Right",
    0xff54: "Down",
    0xffe1: "Shift_L",
    0xffe2: "Shift_R",
    0xffe3: "Control_L",
    0xffe4: "Control_R",
    0xffe7: "Meta_L",
    0xffe8: "Meta_R",
    0xffe9: "Alt_L",
    0xffea: "Alt_R",
    0x20: "space",
    0x60: "grave",
    0x2d: "minus",
    0x3d: "equal",
    0x2b: "plus",
    0x5f: "underscore",
    0xac: "notsign",
    0x21: "exclam",
    0x22: "quotedbl",
    0x24: "dollar",
    0x5e: "asciicircum",
    0x26: "ampersand",
    0x2a: "asterisk",
    0x28: "parenleft",
    0x29: "parenright",
    0x5c: "backslash",
    0x7c: "bar",
    0x5b: "bracketleft",
    0x5d: "bracketright",
    0x7b: "braceleft",
    0x7d: "braceright",
    0x3b: "semicolon",
    0x27: "apostrophe",
    0x23: "numbersign",
    0x3a: "colon",
    0x40: "at",
    0x7e: "asciitilde",
    0x2c: "comma",
    0x2e: "period",
    0x2f: "slash",
    0x3c: "less",
    0x3e: "greater",
    0x3f: "question",
    0xffb0: "KP_0",
    0xffb1: "KP_1",
    0xffb2: "KP_2",
    0xffb3: "KP_3",
    0xffb4: "KP_4",
    0xffb5: "KP_5",
    0xffb6: "KP_6",
    0xffb7: "KP_7",
    0xffb8: "KP_8",
    0xffb9: "KP_9",
    0xffae: "KP_Decimal",
    0xffaf: "KP_Divide",
    0xffaa: "KP_Multiply",
    0xffad: "KP_Subtract",
    0xffab: "KP_Add",
    0xff8d: "KP_Enter",
    0xff7f: "Num_Lock",
    0xff9f: "KP_Delete",
    0xff9e: "KP_Insert",
    0xff9c: "KP_End",
    0xff9b: "KP_Down",
    # 0xffb3      : "KP_Next",
    0xff96: "KP_Left",
    0xff9d: "KP_Begin",
    0xff98: "KP_Right",
    0xff95: "KP_Home",
    0xff97: "KP_Up",
    0xff9a: "KP_Prior",
    0xff14: "Scroll_Lock",
    0xff13: "Pause",
    0x1008ff26: "XF86Back",
    0x1008ff27: "XF86Forward",
    0x1008ff18: "XF86HomePage",
}

for i in range(1, 13):
    RFB_KEYNAMES[0xffbe + (i - 1)] = "F%i" % i

RFB_KEYS: dict[str, int] = {}
for keysym, name in RFB_KEYNAMES.items():
    RFB_KEYS[name.lower()] = keysym
