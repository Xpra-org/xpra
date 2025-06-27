# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from OpenGL.GL import glEnable, GL_DONT_CARE, GL_TRUE

from xpra.util.env import envbool
from xpra.util.str_fn import strtobytes
from xpra.common import noop
from xpra.log import Logger

log = Logger("opengl")

OPENGL_DEBUG = envbool("XPRA_OPENGL_DEBUG", False)

GREMEDY_DEBUG = OPENGL_DEBUG
KHR_DEBUG = OPENGL_DEBUG

GL_DEBUG_OUTPUT: int = 0
GL_DEBUG_OUTPUT_SYNCHRONOUS: int = 0
gl_debug_callback: Callable = noop
glInitStringMarkerGREMEDY: Callable = noop
glStringMarkerGREMEDY: Callable = noop
glInitFrameTerminatorGREMEDY: Callable = noop
glFrameTerminatorGREMEDY: Callable = noop

if OPENGL_DEBUG:
    try:
        # pylint: disable=ungrouped-imports
        from OpenGL.GL import KHR

        GL_DEBUG_OUTPUT = int(KHR.debug.GL_DEBUG_OUTPUT)  # @UndefinedVariable
        GL_DEBUG_OUTPUT_SYNCHRONOUS = int(KHR.debug.GL_DEBUG_OUTPUT_SYNCHRONOUS)
        from OpenGL.GL.KHR.debug import glDebugMessageControl, glDebugMessageCallback, glInitDebugKHR
    except ImportError:
        log("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
        KHR_DEBUG = False
    try:
        from OpenGL.GL.GREMEDY import string_marker, frame_terminator

        glInitStringMarkerGREMEDY = string_marker.glInitStringMarkerGREMEDY
        glStringMarkerGREMEDY = string_marker.glStringMarkerGREMEDY
        glInitFrameTerminatorGREMEDY = frame_terminator.glInitFrameTerminatorGREMEDY
        glFrameTerminatorGREMEDY = frame_terminator.glFrameTerminatorGREMEDY
        from OpenGL.GL import GLDEBUGPROC

        def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param) -> None:
            log.error("src %x type %x id %x severity %x length %d message %s, param=%s",
                      source, error_type, error_id, severity, length, message, param)

        gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
        GREMEDY_DEBUG = all(bool(x) for x in (
            glInitStringMarkerGREMEDY,
            glStringMarkerGREMEDY,
            glInitFrameTerminatorGREMEDY,
            glFrameTerminatorGREMEDY,
        ))
    except ImportError:
        # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
        GREMEDY_DEBUG = False
        log("Unable to import GREMEDY OpenGL extension. Debug output will be more limited.")
log("OpenGL debugging settings:")
log(f" {GREMEDY_DEBUG=}")
log(f" {GL_DEBUG_OUTPUT=}, {GL_DEBUG_OUTPUT_SYNCHRONOUS}")
log(f" {gl_debug_callback=}")
log(f" {glInitStringMarkerGREMEDY=}, {glStringMarkerGREMEDY=}")
log(f" {glInitFrameTerminatorGREMEDY=}, {glFrameTerminatorGREMEDY=}")


def context_init_debug() -> None:
    global GREMEDY_DEBUG, KHR_DEBUG
    # Ask GL to send us all debug messages
    if KHR_DEBUG:
        if GL_DEBUG_OUTPUT and gl_debug_callback != noop and glInitDebugKHR():
            glEnable(GL_DEBUG_OUTPUT)
            glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS)
            glDebugMessageCallback(gl_debug_callback, None)
            glDebugMessageControl(GL_DONT_CARE, GL_DONT_CARE, GL_DONT_CARE, 0, None, GL_TRUE)
        else:
            KHR_DEBUG = False
    # Initialize string_marker GL debugging extension if available
    if GREMEDY_DEBUG:
        if glInitStringMarkerGREMEDY():
            log.info("Extension GL_GREMEDY_string_marker available.")
            log.info(" Will output detailed information about each frame.")
        else:
            # General case - running without debugger, extension not available
            # don't bother trying again for another window:
            GREMEDY_DEBUG = False
        # Initialize frame_terminator GL debugging extension if available
        if glInitFrameTerminatorGREMEDY():
            log.info("Enabling GL frame terminator debugging.")


def gl_marker(*msg) -> None:
    log(*msg)
    if not GREMEDY_DEBUG:
        return
    try:
        s = strtobytes(msg[0] % msg[1:])
    except TypeError:
        s = strtobytes(msg)
    from ctypes import c_char_p  # pylint: disable=import-outside-toplevel
    c_string = c_char_p(s)
    glStringMarkerGREMEDY(0, c_string)


def gl_frame_terminator() -> None:
    # Mark the end of the frame
    # This makes the debug output more readable especially when doing single-buffered rendering
    if not GREMEDY_DEBUG:
        return
    log("glFrameTerminatorGREMEDY()")
    glFrameTerminatorGREMEDY()
