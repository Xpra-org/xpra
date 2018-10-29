#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.os_util import PYTHON3

from xpra.log import Logger
log = Logger("opengl", "paint")


def get_opengl_backends(option_str):
    parts = option_str.split(":")
    if len(parts)==2:
        backend_str = parts[1]
    else:
        backend_str = option_str
    if backend_str in ("native", "gtk") or backend_str.find(",")>0:
        return backend_str.split(",")
    elif PYTHON3:
        return "native",
    else:
        return "gtk", "native"

def get_gl_client_window_module(backends, force_enable=False):
    gl_client_window_module = None
    for impl in backends:
        log("attempting to load '%s' OpenGL backend", impl)
        GL_CLIENT_WINDOW_MODULE = "xpra.client.gl.gtk%s.%sgl_client_window" % (sys.version_info[0], impl)
        log("importing %s", GL_CLIENT_WINDOW_MODULE)
        try:
            gl_client_window_module = __import__(GL_CLIENT_WINDOW_MODULE, {}, {}, ["GLClientWindow", "check_support"])
        except ImportError as e:
            log("cannot import %s", GL_CLIENT_WINDOW_MODULE, exc_info=True)
            log.warn("Warning: cannot import %s OpenGL module", impl)
            log.warn(" %s", e)
            del e
            continue
        log("%s=%s", GL_CLIENT_WINDOW_MODULE, gl_client_window_module)
        opengl_props = gl_client_window_module.check_support(force_enable)
        log("check_support(%s)=%s", force_enable, opengl_props)
        if opengl_props:
            return opengl_props, gl_client_window_module
    log("get_gl_client_window_module(%s, %s) no match found", backends, force_enable)
    return {}, None
