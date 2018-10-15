# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import WinDLL, Structure, c_void_p, c_int, c_ushort, c_ulong, c_ubyte, c_char
from ctypes.wintypes import HANDLE, HDC, HWND, LPCSTR, BOOL, RECT

HGLRC = HANDLE

opengl32 = WinDLL("opengl32", use_last_error=True)

wglCreateContext = opengl32.wglCreateContext
wglCreateContext.argtypes = [HDC]
wglCreateContext.restype = HGLRC

wglMakeCurrent = opengl32.wglMakeCurrent
wglMakeCurrent.argtypes = [HDC, HANDLE]
wglMakeCurrent.restype = BOOL

wglDeleteContext = opengl32.wglDeleteContext
wglDeleteContext.argtypes = [HGLRC]
wglDeleteContext.restype = BOOL


PFD_TYPE_RGBA               = 0
PFD_TYPE_COLORINDEX         = 1
PFD_MAIN_PLANE              = 0
PFD_OVERLAY_PLANE           = 1
PFD_UNDERLAY_PLANE          = -1
PFD_DOUBLEBUFFER            = 0x00000001
PFD_STEREO                  = 0x00000002
PFD_DRAW_TO_WINDOW          = 0x00000004
PFD_DRAW_TO_BITMAP          = 0x00000008
PFD_SUPPORT_GDI             = 0x00000010
PFD_SUPPORT_OPENGL          = 0x00000020
PFD_GENERIC_FORMAT          = 0x00000040
PFD_NEED_PALETTE            = 0x00000080
PFD_NEED_SYSTEM_PALETTE     = 0x00000100
PFD_SWAP_EXCHANGE           = 0x00000200
PFD_SWAP_COPY               = 0x00000400
PFD_SWAP_LAYER_BUFFERS      = 0x00000800
PFD_GENERIC_ACCELERATED     = 0x00001000
PFD_SUPPORT_COMPOSITION     = 0x00008000
PFD_DEPTH_DONTCARE          = 0x20000000
PFD_DOUBLEBUFFER_DONTCARE   = 0x40000000
PFD_STEREO_DONTCARE         = 0x80000000


class CREATESTRUCT(Structure):
    _fields_ = [
        ('lpCreateParams',  c_void_p),
        ('hInstance',       HANDLE),
        ('hMenu',           HANDLE),
        ('hwndParent',      HWND),
        ('cy',              c_int),
        ('cx',              c_int),
        ('y',               c_int),
        ('x',               c_int),
        ('style',           c_int),
        ('lpszName',        LPCSTR),
        ('lpszClass',       LPCSTR),
        ('dwExStyle',       c_int)
        ]

class PIXELFORMATDESCRIPTOR(Structure):
    _fields_ = [
        ('nSize',           c_ushort),
        ('nVersion',        c_ushort),
        ('dwFlags',         c_ulong),
        ('iPixelType',      c_ubyte),
        ('cColorBits',      c_ubyte),
        ('cRedBits',        c_ubyte),
        ('cRedShift',       c_ubyte),
        ('cGreenBits',      c_ubyte),
        ('cGreenShift',     c_ubyte),
        ('cBlueBits',       c_ubyte),
        ('cBlueShift',      c_ubyte),
        ('cAlphaBits',      c_ubyte),
        ('cAlphaShift',     c_ubyte),
        ('cAccumBits',      c_ubyte),
        ('cAccumRedBits',   c_ubyte),
        ('cAccumGreenBits', c_ubyte),
        ('cAccumBlueBits',  c_ubyte),
        ('cAccumAlphaBits', c_ubyte),
        ('cDepthBits',      c_ubyte),
        ('cStencilBits',    c_ubyte),
        ('cAuxBuffers',     c_ubyte),
        ('iLayerType',      c_ubyte),
        ('bReserved',       c_ubyte),
        ('dwLayerMask',     c_ulong),
        ('dwVisibleMask',   c_ulong),
        ('dwDamageMask',    c_ulong),
        ]

class PAINTSTRUCT(Structure):
    _fields_ = [
        ('hdc',             HDC),
        ('fErase',          BOOL),
        ('rcPaint',         RECT),
        ('fRestore',        BOOL),
        ('fIncUpdate',      BOOL),
        ('rgbReserved',     c_char * 32),
        ]
