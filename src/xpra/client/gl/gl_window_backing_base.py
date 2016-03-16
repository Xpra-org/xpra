# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time, math

from xpra.log import Logger
log = Logger("opengl", "paint")
fpslog = Logger("opengl", "fps")
OPENGL_DEBUG = os.environ.get("XPRA_OPENGL_DEBUG", "0")=="1"
OPENGL_PAINT_BOX = int(os.environ.get("XPRA_OPENGL_PAINT_BOX", "0"))

from xpra.gtk_common.gtk_util import color_parse, is_realized


_DEFAULT_BOX_COLORS = {
              "png"     : "yellow",
              "h264"    : "blue",
              "vp8"     : "green",
              "rgb24"   : "orange",
              "rgb32"   : "red",
              "webp"    : "pink",
              "jpeg"    : "purple",
              "png/P"   : "indigo",
              "png/L"   : "teal",
              "h265"    : "khaki",
              "vp9"     : "lavender",
              "mpeg4"   : "black",
              }

def get_fcolor(encoding):
    color_name = os.environ.get("XPRA_BOX_COLOR_%s" % encoding.upper(), _DEFAULT_BOX_COLORS.get(encoding))
    try:
        c = color_parse(color_name)
    except:
        c = color_parse("black")
    #try and hope this works:
    try:
        return c.red/65536.0, c.green/65536.0, c.blue/65536.0, 0.3
    except:
        pass
    try:
        #it seems that in some GDK versions, we get a return value
        #made of (boolean, GDK.Color), we only want the color..
        c = c[1]
    except:
        log.warn("failed to parse color %s", color_name)
        return 0, 0, 0
    return c.red/65536.0, c.green/65536.0, c.blue/65536.0, 0.3
_DEFAULT_BOX_COLOR = get_fcolor("black")
BOX_COLORS = {}
for x in _DEFAULT_BOX_COLORS.keys():
    BOX_COLORS[x] = get_fcolor(x)


from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.gtk_common.gtk_util import POINTER_MOTION_MASK, POINTER_MOTION_HINT_MASK
from xpra.gtk_common.gtk_spinner import cv
from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking
from xpra.client.gl.gtk_compat import Config_new_by_mode, MODE_DOUBLE, GLContextManager, GLDrawingArea
from xpra.client.gl.gl_check import get_DISPLAY_MODE, GL_ALPHA_SUPPORTED, CAN_DOUBLE_BUFFER, is_pyopengl_memoryview_safe
from xpra.client.gl.gl_colorspace_conversions import YUV2RGB_shader, RGBP2RGB_shader
from OpenGL import version as OpenGL_version
from OpenGL.error import GLError
from OpenGL.GL import \
    GL_PROJECTION, GL_MODELVIEW, \
    GL_UNPACK_ROW_LENGTH, GL_UNPACK_ALIGNMENT, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, GL_POLYGON, GL_LINE_LOOP, GL_COLOR_BUFFER_BIT, \
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER, \
    GL_DONT_CARE, GL_TRUE, GL_DEPTH_TEST, GL_SCISSOR_TEST, GL_LIGHTING, GL_DITHER, \
    GL_RGB, GL_RGBA, GL_BGR, GL_BGRA, \
    GL_BLEND, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, \
    GL_TEXTURE_MAX_LEVEL, GL_TEXTURE_BASE_LEVEL, \
    GL_PERSPECTIVE_CORRECTION_HINT, GL_FASTEST, \
    glLineStipple, GL_LINE_STIPPLE, \
    glTexEnvi, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE, \
    glHint, \
    glBlendFunc, \
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glEnablei, glBegin, glFlush, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, \
    glTexCoord2i, glVertex2i, glEnd, \
    glClear, glClearColor, glLineWidth, glColor4f
from OpenGL.GL.ARB.texture_rectangle import GL_TEXTURE_RECTANGLE_ARB
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, \
    glBindProgramARB, glProgramStringARB, GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB
from OpenGL.GL.ARB.fragment_program import GL_FRAGMENT_PROGRAM_ARB
from OpenGL.GL.ARB.framebuffer_object import GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D

from ctypes import c_uint

PIXEL_FORMAT_TO_CONSTANT = {
                       "BGR"    : GL_BGR,
                       "RGB"    : GL_RGB,
                       "BGRA"   : GL_BGRA,
                       "BGRX"   : GL_BGRA,
                       "RGBA"   : GL_RGBA,
                       "RGBX"   : GL_RGBA,
                       }
CONSTANT_TO_PIXEL_FORMAT = {
                       GL_BGR   : "BGR",
                       GL_RGB   : "RGB",
                       GL_BGRA  : "BGRA",
                       GL_RGBA  : "RGBA",
                       }


#debugging variables:
GL_DEBUG_OUTPUT = None
GL_DEBUG_OUTPUT_SYNCHRONOUS = None
gl_debug_callback = None
glInitStringMarkerGREMEDY = None
glStringMarkerGREMEDY = None
glInitFrameTerminatorGREMEDY = None
glFrameTerminatorGREMEDY = None
if OPENGL_DEBUG:
    try:
        from OpenGL.GL.KHR.debug import GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS, glDebugMessageControl, glDebugMessageCallback, glInitDebugKHR
    except ImportError:
        log("Unable to import GL_KHR_debug OpenGL extension. Debug output will be more limited.")
    try:
        from OpenGL.GL.GREMEDY.string_marker import glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
        from OpenGL.GL.GREMEDY.frame_terminator import glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
        from OpenGL.GL import GLDEBUGPROC #@UnresolvedImport
        def py_gl_debug_callback(source, error_type, error_id, severity, length, message, param):
            log.error("src %x type %x id %x severity %x length %d message %s", source, error_type, error_id, severity, length, message)
        gl_debug_callback = GLDEBUGPROC(py_gl_debug_callback)
    except ImportError:
        # This is normal- GREMEDY_string_marker is only available with OpenGL debuggers
        log("Unable to import GREMEDY OpenGL extension. Debug output will be more limited.")
    log("OpenGL debugging settings: "+
          "GL_DEBUG_OUTPUT=%s, GL_DEBUG_OUTPUT_SYNCHRONOUS=%s"+
          "gl_debug_callback=%s, "+
          "glInitStringMarkerGREMEDY=%s, glStringMarkerGREMEDY=%s, glInitFrameTerminatorGREMEDY=%s, glFrameTerminatorGREMEDY=%s",
            GL_DEBUG_OUTPUT, GL_DEBUG_OUTPUT_SYNCHRONOUS,
            gl_debug_callback, glInitStringMarkerGREMEDY, glStringMarkerGREMEDY,
            glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY)
from ctypes import c_char_p

try:
    import OpenGL_accelerate            #@UnresolvedImport
except:
    OpenGL_accelerate = None
zerocopy_upload = bool(OpenGL_accelerate) and os.environ.get("XPRA_ZEROCOPY_OPENGL_UPLOAD", "1")=="1" and is_pyopengl_memoryview_safe(OpenGL_version.__version__, OpenGL_accelerate.__version__)
try:
    memoryview_type = memoryview
except:
    memoryview_type = None
try:
    buffer_type = buffer
except:
    #not defined in py3k..
    buffer_type = None


# Texture number assignment
# The first four are used to update the FBO,
# the FBO is what is painted on screen.
TEX_Y = 0
TEX_U = 1
TEX_V = 2
TEX_RGB = 3
TEX_FBO = 4         #FBO texture (guaranteed up-to-date window contents)

# Shader number assignment
YUV2RGB_SHADER = 0
RGBP2RGB_SHADER = 1

"""
The logic is as follows:

We create an OpenGL framebuffer object, which will be always up-to-date with the latest windows contents.
This framebuffer object is updated with YUV painting and RGB painting. It is presented on screen by drawing a
textured quad when requested, that is: after each YUV or RGB painting operation, and upon receiving an expose event.
The use of a intermediate framebuffer object is the only way to guarantee that the client keeps an always fully up-to-date
window image, which is critical because of backbuffer content losses upon buffer swaps or offscreen window movement.
"""
class GLWindowBackingBase(GTKWindowBacking):

    RGB_MODES = ["YUV420P", "YUV422P", "YUV444P", "GBRP", "BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR"]
    HAS_ALPHA = GL_ALPHA_SUPPORTED

    def __init__(self, wid, window_alpha):
        self.wid = wid
        self.size = 0, 0
        self.render_size = 0, 0
        self.texture_pixel_format = None
        #this is the pixel format we are currently updating the fbo with
        #can be: "YUV420P", "YUV422P", "YUV444P", "GBRP" or None when not initialized yet.
        self.pixel_format = None
        self.textures = None # OpenGL texture IDs
        self.shaders = None
        self.texture_size = 0, 0
        self.gl_setup = False
        self.debug_setup = False
        self.border = None
        self.paint_screen = False
        self.paint_spinner = False
        self.draw_needs_refresh = False
        self.offscreen_fbo = None
        self.pending_fbo_paint = []
        self.default_paint_box_line_width = OPENGL_PAINT_BOX or 1
        self.paint_box_line_width = OPENGL_PAINT_BOX

        GTKWindowBacking.__init__(self, wid, window_alpha)
        self.init_gl_config(window_alpha)
        self.init_backing()
        #this is how many bpp we keep in the texture
        #(pixels are always stored in 32bpp - but this makes it clearer when we do/don't support alpha)
        if self._alpha_enabled:
            self.texture_pixel_format = GL_RGBA
        else:
            self.texture_pixel_format = GL_RGB
        self._backing.show()

    def init_gl_config(self, window_alpha):
        #setup gl config:
        alpha = GL_ALPHA_SUPPORTED and window_alpha
        display_mode = get_DISPLAY_MODE(want_alpha=alpha)
        self.glconfig = Config_new_by_mode(display_mode)
        if self.glconfig is None and CAN_DOUBLE_BUFFER:
            log("trying to toggle double-buffering")
            display_mode &= ~MODE_DOUBLE
            self.glconfig = Config_new_by_mode(display_mode)
        if not self.glconfig:
            raise Exception("cannot setup an OpenGL context")

    def init_backing(self):
        self._backing = GLDrawingArea(self.glconfig)
        #must be overriden in subclasses to setup self._backing
        assert self._backing
        if self._alpha_enabled:
            assert GL_ALPHA_SUPPORTED, "BUG: cannot enable alpha if GL backing does not support it!"
            screen = self._backing.get_screen()
            rgba = screen.get_rgba_colormap()
            display = screen.get_display()
            if not display.supports_composite():
                log.warn("display %s does not support compositing, transparency disabled", display.get_name())
                self._alpha_enabled = False
            elif rgba:
                log("%s.__init__() using rgba colormap %s", self, rgba)
                self._backing.set_colormap(rgba)
            else:
                log.warn("failed to enable transparency on screen %s", screen)
                self._alpha_enabled = False
        self._backing.set_events(self._backing.get_events() | POINTER_MOTION_MASK | POINTER_MOTION_HINT_MASK)


    def __repr__(self):
        return "GLWindowBacking(%s, %s, %s)" % (self.wid, self.size, self.pixel_format)

    def init(self, ww, wh, bw, bh):
        #re-init gl projection with new dimensions
        #(see gl_init)
        if self.size!=(bw, bh):
            self.gl_setup = False
            self.size = bw, bh
        self.render_size = ww, wh

    def gl_marker(self, *msg):
        log(*msg)
        if not bool(glStringMarkerGREMEDY):
            return
        try:
            s = "%s" % msg
        except:
            s = str(msg)
        c_string = c_char_p(s)
        glStringMarkerGREMEDY(0, c_string)

    def gl_frame_terminator(self):
        log("%s.gl_frame_terminator()", self)
        # Mark the end of the frame
        # This makes the debug output more readable especially when doing single-buffered rendering
        if not bool(glFrameTerminatorGREMEDY):
            return
        glFrameTerminatorGREMEDY()

    def gl_init_debug(self):
        #ensure python knows which scope we're talking about:
        global glInitStringMarkerGREMEDY, glStringMarkerGREMEDY
        global glInitFrameTerminatorGREMEDY, glFrameTerminatorGREMEDY
        # Ask GL to send us all debug messages
        if GL_DEBUG_OUTPUT and gl_debug_callback and glInitDebugKHR() == True:
            glEnable(GL_DEBUG_OUTPUT)
            glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS)
            glDebugMessageCallback(gl_debug_callback, None)
            glDebugMessageControl(GL_DONT_CARE, GL_DONT_CARE, GL_DONT_CARE, 0, None, GL_TRUE)
        # Initialize string_marker GL debugging extension if available
        if glInitStringMarkerGREMEDY and glInitStringMarkerGREMEDY() == True:
            log.info("Extension GL_GREMEDY_string_marker available. Will output detailed information about each frame.")
        else:
            # General case - running without debugger, extension not available
            glStringMarkerGREMEDY = None
            #don't bother trying again for another window:
            glInitStringMarkerGREMEDY = None
        # Initialize frame_terminator GL debugging extension if available
        if glInitFrameTerminatorGREMEDY and glInitFrameTerminatorGREMEDY() == True:
            log.info("Enabling GL frame terminator debugging.")
        else:
            glFrameTerminatorGREMEDY = None
            #don't bother trying again for another window:
            glInitFrameTerminatorGREMEDY = None

    def gl_init_textures(self):
        assert self.offscreen_fbo is None
        assert self.shaders is None
        self.textures = glGenTextures(5)
        if hasattr(glGenFramebuffers, "pyConverters") and len(glGenFramebuffers.pyConverters)==1:
            #single argument syntax:
            self.offscreen_fbo = glGenFramebuffers(1)
        else:
            self.offscreen_fbo = c_uint(1)
            glGenFramebuffers(1, self.offscreen_fbo)
        log("%s.gl_init_textures() textures: %s, offscreen fbo: %s", self, self.textures, self.offscreen_fbo)

    def gl_init_shaders(self):
        assert self.shaders is None
        # Create and assign fragment programs
        self.shaders = [ 1, 2 ]
        glGenProgramsARB(2, self.shaders)
        for name, progid, progstr in (("YUV2RGB", YUV2RGB_SHADER, YUV2RGB_shader), ("RGBP2RGB", RGBP2RGB_SHADER, RGBP2RGB_shader)):
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[progid])
            glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(progstr), progstr)
            err = glGetString(GL_PROGRAM_ERROR_STRING_ARB)
            if err:
                #FIXME: maybe we should do something else here?
                log.error("OpenGL shader %s failed:", name)
                log.error(" %s", err)
                raise Exception("OpenGL shader %s setup failure: %s" % (name, err))
            else:
                log("%s shader initialized", name)

    def gl_context(self):
        if not self._backing:
            log("Error: no OpenGL backing")
            return None
        if not is_realized(self._backing):
            log.error("Error: OpenGL backing is not realized")
            return None
        w, h = self.size
        if w<=0 or h<=0:
            log.error("Error: invalid OpenGL backing size: %ix%i", w, h)
            return None
        context = GLContextManager(self._backing)
        log("%s.gl_context() GL Pixmap backing size: %d x %d, context=%s", self, w, h, context)
        return context

    def gl_init(self):
        #must be called within a context!
        #performs init if needed
        if not self.debug_setup:
            self.debug_setup = True
            self.gl_init_debug()

        if not self.gl_setup:
            w, h = self.size
            self.gl_marker("Initializing GL context for window size %s, backing size %s", self.render_size, self.size)
            # Initialize viewport and matrices for 2D rendering
            glViewport(0, 0, w, h)
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
            glMatrixMode(GL_MODELVIEW)
            # Mesa docs claim: this hint can improve the speed of texturing
            #when perspective-correct texture coordinate interpolation isn't needed,
            #such as when using a glOrtho() projection:
            glHint(GL_PERSPECTIVE_CORRECTION_HINT, GL_FASTEST)
            # Could be more optimal to use vertex arrays:
            # glEnableClientState(GL_VERTEX_ARRAY)
            # glEnableClientState(GL_TEXTURE_COORD_ARRAY)

            # Clear background to transparent black
            glClearColor(0.0, 0.0, 0.0, 0.0)

            # we don't use the depth (2D only):
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_SCISSOR_TEST)
            glDisable(GL_LIGHTING)
            glDisable(GL_DITHER)
            # only do alpha blending in present_fbo:
            glDisable(GL_BLEND)

            # Default state is good for YUV painting:
            #  - fragment program enabled
            #  - YUV fragment program bound
            #  - render to offscreen FBO
            if self.textures is None:
                self.gl_init_textures()

            # Define empty FBO texture and set rendering to FBO
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])
            # nvidia needs this even though we don't use mipmaps (repeated through this file):
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_BASE_LEVEL, 0)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAX_LEVEL, 0)
            try:
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, self.texture_pixel_format, w, h, 0, self.texture_pixel_format, GL_UNSIGNED_BYTE, None)
            except Exception as e:
                log.error("Error: cannot initialize %ix%i %s texture", w, h, CONSTANT_TO_PIXEL_FORMAT.get(self.texture_pixel_format, self.texture_pixel_format))
                log.error(" %r", e)
                log("%s", self.gl_init, exc_info=True)
                raise Exception("cannot initialize %ix%i %s texture: %r" % (w, h, CONSTANT_TO_PIXEL_FORMAT.get(self.texture_pixel_format, self.texture_pixel_format), e))
            glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO], 0)
            glClear(GL_COLOR_BUFFER_BIT)

            # Create and assign fragment programs
            if not self.shaders:
                self.gl_init_shaders()

            # Bind program 0 for YUV painting by default
            glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])
            self.gl_setup = True

    def close(self):
        #This seems to cause problems, so we rely
        #on destroying the context to clear textures and fbos...
        #if self.offscreen_fbo is not None:
        #    glDeleteFramebuffers(1, [self.offscreen_fbo])
        #    self.offscreen_fbo = None
        #if self.textures is not None:
        #    glDeleteTextures(self.textures)
        #    self.textures = None
        b = self._backing
        if b:
            self._backing = None
            b.destroy()
        self.glconfig = None

    def set_rgb_paint_state(self):
        # Set GL state for RGB painting:
        #    no fragment program
        #    only tex unit #0 active
        self.gl_marker("Switching to RGB paint state")
        glDisable(GL_FRAGMENT_PROGRAM_ARB);
        for texture in (GL_TEXTURE1, GL_TEXTURE2):
            glActiveTexture(texture)
            glDisable(GL_TEXTURE_RECTANGLE_ARB)
        glActiveTexture(GL_TEXTURE0);
        glEnable(GL_TEXTURE_RECTANGLE_ARB)

    def unset_rgb_paint_state(self):
        # Reset state to our default
        self.gl_marker("Switching back to YUV paint state")
        glEnable(GL_FRAGMENT_PROGRAM_ARB)

    def set_rgbP_paint_state(self):
        # Set GL state for planar RGB:
        #   change fragment program
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[RGBP2RGB_SHADER])

    def unset_rgbP_paint_state(self):
        # Reset state to our default (YUV painting):
        #   change fragment program
        glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.shaders[YUV2RGB_SHADER])

    def present_fbo(self, x, y, w, h, flush=0):
        log("present_fbo: adding %s to pending paint list (size=%i), flush=%s, paint_screen=%s", (x, y, w, h), len(self.pending_fbo_paint), flush, self.paint_screen)
        self.pending_fbo_paint.append((x, y, w, h))
        if not self.paint_screen:
            return
        #flush>0 means we should wait for the final flush=0 paint
        if flush==0:
            self.do_present_fbo()

    def do_present_fbo(self):
        self.gl_marker("Presenting FBO on screen")
        # Change state to target screen instead of our FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        if self._alpha_enabled:
            # transparent background:
            glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            # plain white no alpha:
            glClearColor(1.0, 1.0, 1.0, 1.0)

        # Draw FBO texture on screen
        self.set_rgb_paint_state()
        bw, bh = self.size
        ww, wh = self.render_size

        if self.glconfig.is_double_buffered() or bw!=ww or bh!=wh:
            #refresh the whole window:
            rectangles = ((0, 0, bw, bh), )
        else:
            #paint just the rectangles we have accumulated:
            rectangles = self.pending_fbo_paint
        self.pending_fbo_paint = []
        log("do_present_fbo: painting %s", rectangles)

        glEnable(GL_TEXTURE_RECTANGLE_ARB)
        glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_FBO])
        if self._alpha_enabled:
            # support alpha channel if present:
            glEnablei(GL_BLEND, self.textures[TEX_FBO])
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)

        #viewport for painting to window:
        glViewport(0, 0, ww, wh)
        if ww!=bw or wh!=bh:
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_LINEAR)

        glBegin(GL_QUADS)
        for x,y,w,h in rectangles:
            #note how we invert coordinates..
            tx1, ty1, tx2, ty2 = x, bh-y,  x+w, bh-y-h
            vx1, vy1, vx2, vy2 = x, y,     x+w, y+h
            glTexCoord2i(tx1, ty1)
            glVertex2i(vx1, vy1)        #top-left of window viewport
            glTexCoord2i(tx1, ty2)
            glVertex2i(vx1, vy2)        #bottom-left of window viewport
            glTexCoord2i(tx2, ty2)
            glVertex2i(vx2, vy2)        #bottom-right of window viewport
            glTexCoord2i(tx2, ty1)
            glVertex2i(vx2, vy1)        #top-right of window viewport
        glEnd()
        glDisable(GL_TEXTURE_RECTANGLE_ARB)

        if self.paint_spinner:
            #add spinner:
            dim = min(bw/3.0, bh/3.0)
            t = time.time()
            count = int(t*4.0)
            bx = bw//2
            by = bh//2
            for i in range(8):      #8 lines
                glBegin(GL_POLYGON)
                c = cv.trs[count%8][i]
                glColor4f(c, c, c, 1)
                mi1 = math.pi*i/4-math.pi/16
                mi2 = math.pi*i/4+math.pi/16
                glVertex2i(int(bx+math.sin(mi1)*10), int(by+math.cos(mi1)*10))
                glVertex2i(int(bx+math.sin(mi1)*dim), int(by+math.cos(mi1)*dim))
                glVertex2i(int(bx+math.sin(mi2)*dim), int(by+math.cos(mi2)*dim))
                glVertex2i(int(bx+math.sin(mi2)*10), int(by+math.cos(mi2)*10))
                glEnd()

        #if desired, paint window border
        if self.border and self.border.shown:
            #double size since half the line will be off-screen
            glLineWidth(self.border.size*2)
            glBegin(GL_LINE_LOOP)
            glColor4f(self.border.red, self.border.green, self.border.blue, self.border.alpha)
            for px,py in ((0, 0), (bw, 0), (bw, bh), (0, bh)):
                glVertex2i(px, py)
            glEnd()

        # Show the backbuffer on screen
        self.gl_show()
        self.gl_frame_terminator()

        #restore pbo viewport
        glViewport(0, 0, bw, bh)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)

        self.unset_rgb_paint_state()
        log("%s(%s, %s)", glBindFramebuffer, GL_FRAMEBUFFER, self.offscreen_fbo)
        glBindFramebuffer(GL_FRAMEBUFFER, self.offscreen_fbo)
        log("%s.do_present_fbo() done", self)

    def gl_show(self):
        start = time.time()
        if self.glconfig.is_double_buffered():
            # Show the backbuffer on screen
            log("%s.gl_show() swapping buffers now", self)
            gldrawable = self.get_gl_drawable()
            gldrawable.swap_buffers()
        else:
            #just ensure stuff gets painted:
            log("%s.gl_show() flushing", self)
            glFlush()
        end = time.time()
        fpslog("gl_show took %ims", (end-start)*1000)


    def paint_box(self, encoding, is_delta, x, y, w, h):
        #show region being painted if debug paint box is enabled only:
        if self.paint_box_line_width<=0:
            return
        glDisable(GL_TEXTURE_RECTANGLE_ARB)
        glDisable(GL_FRAGMENT_PROGRAM_ARB)
        glLineWidth(self.paint_box_line_width+0.5)
        if is_delta:
            glLineStipple(1, 0xaaaa)
            glEnable(GL_LINE_STIPPLE)
        glBegin(GL_LINE_LOOP)
        color = BOX_COLORS.get(encoding, _DEFAULT_BOX_COLOR)
        log("Painting colored box around %s screen update using: %s (delta=%s)", encoding, color, is_delta)
        glColor4f(*color)
        for px,py in ((x, y), (x+w, y), (x+w, y+h), (x, y+h)):
            glVertex2i(px, py)
        glEnd()
        if is_delta:
            glDisable(GL_LINE_STIPPLE)


    def pixels_for_upload(self, img_data):
        #prepare the pixel buffer for upload:
        t = type(img_data)
        if t==memoryview_type:
            if not zerocopy_upload:
                #not safe, make a copy :(
                return "copy:memoryview.tobytes", img_data.tobytes()
            return "zerocopy:memoryview", img_data
        elif t in (str, buffer_type) and zerocopy_upload:
            #we can zerocopy if we wrap it:
            return "zerocopy:buffer-as-memoryview", memoryview_type(img_data)
        elif t!=str:
            if hasattr(img_data, "raw"):
                return "zerocopy:mmap", img_data.raw
            #everything else.. copy to bytes (aka str):
            return "copy:str(%s)" % t, str(img_data)
        else:
            #str already
            return  "copy:str", img_data


    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options):
        return self._do_paint_rgb(32, img_data, x, y, width, height, rowstride, options)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options):
        return self._do_paint_rgb(24, img_data, x, y, width, height, rowstride, options)

    def _do_paint_rgb(self, bpp, img_data, x, y, width, height, rowstride, options):
        log("%s._do_paint_rgb(%s, %s bytes, x=%d, y=%d, width=%d, height=%d, rowstride=%d, options=%s)", self, bpp, len(img_data), x, y, width, height, rowstride, options)
        context = self.gl_context()
        if not context:
            log("%s._do_paint_rgb(..) no context!", self)
            return False

        #TODO: move this code up to the decode thread section
        upload, img_data = self.pixels_for_upload(img_data)

        with context:
            self.gl_init()
            self.set_rgb_paint_state()

            rgb_format = options.get(b"rgb_format")
            if not rgb_format:
                #Older servers may not tell us the pixel format, so we must infer it:
                if bpp==24:
                    rgb_format = "RGB"
                else:
                    assert bpp==32
                    rgb_format = "RGBA"
            else:
                rgb_format = rgb_format.decode()
            #convert it to a GL constant:
            pformat = PIXEL_FORMAT_TO_CONSTANT.get(rgb_format)
            assert pformat is not None, "could not find pixel format for %s (bpp=%s)" % (rgb_format, bpp)

            bytes_per_pixel = len(rgb_format)       #ie: BGRX -> 4
            # Compute alignment and row length
            row_length = 0
            alignment = 1
            for a in [2, 4, 8]:
                # Check if we are a-aligned - ! (var & 0x1) means 2-aligned or better, 0x3 - 4-aligned and so on
                if (rowstride & a-1) == 0:
                    alignment = a
            # If number of extra bytes is greater than the alignment value,
            # then we also have to set row_length
            # Otherwise it remains at 0 (= width implicitely)
            if (rowstride - width * bytes_per_pixel) >= alignment:
                row_length = width + (rowstride - width * bytes_per_pixel) // bytes_per_pixel

            self.gl_marker("%s %sbpp update at (%d,%d) size %dx%d (%s bytes), stride=%d, row length %d, alignment %d, using GL %s format=%s",
                           rgb_format, bpp, x, y, width, height, len(img_data), rowstride, row_length, alignment, upload, CONSTANT_TO_PIXEL_FORMAT.get(pformat))

            # Upload data as temporary RGB texture
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[TEX_RGB])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, row_length)
            glPixelStorei(GL_UNPACK_ALIGNMENT, alignment)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_BASE_LEVEL, 0)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAX_LEVEL, 0)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
            glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, self.texture_pixel_format, width, height, 0, pformat, GL_UNSIGNED_BYTE, img_data)

            # Draw textured RGB quad at the right coordinates
            glBegin(GL_QUADS)
            glTexCoord2i(0, 0)
            glVertex2i(x, y)
            glTexCoord2i(0, height)
            glVertex2i(x, y+height)
            glTexCoord2i(width, height)
            glVertex2i(x+width, y+height)
            glTexCoord2i(width, 0)
            glVertex2i(x+width, y)
            glEnd()

            self.paint_box(options.get("encoding"), options.get("delta", -1)>=0, x, y, width, height)

            # Present update to screen
            self.present_fbo(x, y, width, height, options.get("flush", 0))
            # present_fbo has reset state already
        return True

    def do_video_paint(self, img, x, y, enc_width, enc_height, width, height, options, callbacks):
        #copy so the data will be usable (usually a str)
        img.clone_pixel_data()
        self.idle_add(self.gl_paint_planar, options.get("flush", 0), options.get("encoding"), img, x, y, enc_width, enc_height, width, height, callbacks)

    def gl_paint_planar(self, flush, encoding, img, x, y, enc_width, enc_height, width, height, callbacks):
        #this function runs in the UI thread, no video_decoder lock held
        log("gl_paint_planar%s", (flush, encoding, img, x, y, enc_width, enc_height, width, height, callbacks))
        try:
            pixel_format = img.get_pixel_format()
            assert pixel_format in ("YUV420P", "YUV422P", "YUV444P", "GBRP"), "sorry the GL backing does not handle pixel format '%s' yet!" % (pixel_format)

            context = self.gl_context()
            if not context:
                log("%s._do_paint_rgb(..) no context!", self)
                fire_paint_callbacks(callbacks, False, "failed to get a gl context")
                return
            with context:
                self.gl_init()
                self.update_planar_textures(x, y, enc_width, enc_height, img, pixel_format, scaling=(enc_width!=width or enc_height!=height))
                img.free()

                # Update FBO texture
                x_scale, y_scale = 1, 1
                if width!=enc_width or height!=enc_height:
                    x_scale = float(width)/enc_width
                    y_scale = float(height)/enc_height
                self.render_planar_update(x, y, enc_width, enc_height, x_scale, y_scale)
                self.paint_box(encoding, False, x, y, width, height)
                # Present it on screen
                self.present_fbo(x, y, width, height, flush)
            fire_paint_callbacks(callbacks, True)
            return
        except GLError as e:
            message = "gl_paint_planar error: %r" % e
        except Exception as e:
            message = "gl_paint_planar error: %s" % e
        log.error("%s.gl_paint_planar(..) error: %s", self, e, exc_info=True)
        fire_paint_callbacks(callbacks, False, message)

    def update_planar_textures(self, x, y, width, height, img, pixel_format, scaling=False):
        assert self.textures is not None, "no OpenGL textures!"
        log("%s.update_planar_textures%s", self, (x, y, width, height, img, pixel_format))

        divs = get_subsampling_divs(pixel_format)
        if self.pixel_format is None or self.pixel_format!=pixel_format or self.texture_size!=(width, height):
            self.pixel_format = pixel_format
            self.texture_size = (width, height)
            self.gl_marker("Creating new planar textures, pixel format %s", pixel_format)
            # Create textures of the same size as the window's
            glEnable(GL_TEXTURE_RECTANGLE_ARB)

            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glActiveTexture(texture)
                glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
                glEnable(GL_TEXTURE_RECTANGLE_ARB)
                mag_filter = GL_NEAREST
                if scaling or (div_w > 1 or div_h > 1):
                    mag_filter = GL_LINEAR
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_BASE_LEVEL, 0)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAX_LEVEL, 0)
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, width//div_w, height//div_h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, None)

        self.gl_marker("updating planar textures: %sx%s %s", width, height, pixel_format)
        rowstrides = img.get_rowstride()
        img_data = img.get_pixels()
        assert len(rowstrides)==3 and len(img_data)==3
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            (div_w, div_h) = divs[index]
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[index])
            upload, pixel_data = self.pixels_for_upload(img_data[index])
            log("texture %s: div=%s, rowstride=%s, %sx%s, data=%s bytes, upload=%s", index, divs[index], rowstrides[index], width//div_w, height//div_h, len(pixel_data), upload)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_BASE_LEVEL, 0)
            glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAX_LEVEL, 0)
            glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, 0, 0, width//div_w, height//div_h, GL_LUMINANCE, GL_UNSIGNED_BYTE, pixel_data)

    def render_planar_update(self, rx, ry, rw, rh, x_scale=1, y_scale=1):
        log("%s.render_planar_update%s pixel_format=%s", self, (rx, ry, rw, rh, x_scale, y_scale), self.pixel_format)
        if self.pixel_format not in ("YUV420P", "YUV422P", "YUV444P", "GBRP"):
            #not ready to render yet
            return
        if self.pixel_format == "GBRP":
            self.set_rgbP_paint_state()
        self.gl_marker("painting planar update, format %s", self.pixel_format)
        divs = get_subsampling_divs(self.pixel_format)
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])

        tw, th = self.texture_size
        log("%s.render_planar_update(..) texture_size=%s, size=%s", self, self.texture_size, self.size)
        glBegin(GL_QUADS)
        for x,y in ((0, 0), (0, rh), (rw, rh), (rw, 0)):
            ax = min(tw, x)
            ay = min(th, y)
            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                (div_w, div_h) = divs[index]
                glMultiTexCoord2i(texture, ax//div_w, ay//div_h)
            glVertex2i(int(rx+ax*x_scale), int(ry+ay*y_scale))
        glEnd()
        if self.pixel_format == "GBRP":
            self.unset_rgbP_paint_state()
