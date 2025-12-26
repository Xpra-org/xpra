# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import WinDLL  # @UnresolvedImport
from ctypes.wintypes import HANDLE, HDC, BOOL

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
