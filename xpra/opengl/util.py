# This file is part of Xpra.
# Copyright (C) 2013 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from OpenGL import GL

from xpra.common import StrEnum
from xpra.util.env import envbool
from xpra.util.str_fn import strtobytes
from xpra.buffers.membuf import get_membuf  # @UnresolvedImport pylint: disable=import-outside-toplevel
from xpra.log import Logger

log = Logger("opengl", "paint")

SAVE_BUFFERS = os.environ.get("XPRA_OPENGL_SAVE_BUFFERS", "")
if SAVE_BUFFERS not in ("png", "jpeg", ""):
    log.warn("Warning: invalid value for XPRA_OPENGL_SAVE_BUFFERS: must be 'png' or 'jpeg'")
    SAVE_BUFFERS = ""
pillow_major = 0
if SAVE_BUFFERS:
    from PIL import Image, ImageOps, __version__ as pil_version
    try:
        pillow_major = int(pil_version.split(".")[0])
    except ValueError:
        pass

zerocopy_upload = False
if envbool("XPRA_OPENGL_ZEROCOPY_UPLOAD", True):
    try:
        import OpenGL_accelerate  # @UnresolvedImport

        assert OpenGL_accelerate
    except ImportError:
        pass
    else:
        from OpenGL import version

        zerocopy_upload = version.__version__ == OpenGL_accelerate.__version__
    if not zerocopy_upload:
        log.warn("Warning: zerocopy upload is not available")


class UploadMode(StrEnum):
    ZEROCOPY_MEMORYVIEW = "zerocopy:memoryview"
    COPY_MEMORYVIEW_TO_BYTES = "copy:memoryview.tobytes"
    ZEROCOPY_BYTES = "zerocopy:bytes-as-memoryview"
    COPY_BYTES = "copy:bytes"
    ZEROCOPY_MMAP = "zerocopy:mmap"
    COPY_TOBYTES = "copy:tobytes"


def pixels_for_upload(img_data) -> tuple[UploadMode, memoryview | bytes]:
    # prepare the pixel buffer for upload:
    if isinstance(img_data, memoryview):
        if zerocopy_upload:
            return UploadMode.ZEROCOPY_MEMORYVIEW, img_data.toreadonly()
        # not safe, make a copy :(
        return UploadMode.COPY_MEMORYVIEW_TO_BYTES, img_data.tobytes()
    if isinstance(img_data, bytes):
        if zerocopy_upload:
            # we can zerocopy if we wrap it:
            return UploadMode.ZEROCOPY_BYTES, memoryview(img_data).toreadonly()
        return UploadMode.COPY_BYTES, img_data
    if hasattr(img_data, "raw"):
        return UploadMode.ZEROCOPY_MMAP, img_data.raw
    # everything else: copy to bytes:
    return UploadMode.COPY_TOBYTES, strtobytes(img_data)


def set_alignment(width: int, rowstride: int, pixel_format: str) -> None:
    bytes_per_pixel = len(pixel_format)  # ie: BGRX -> 4, Y -> 1, YY -> 2
    # Compute alignment and row length
    row_length = 0
    alignment = 1
    for a in (2, 4, 8):
        # Check if we are a-aligned - ! (var & 0x1) means 2-aligned or better, 0x3 - 4-aligned and so on
        if (rowstride & a - 1) == 0:
            alignment = a
    # If number of extra bytes is greater than the alignment value,
    # then we also have to set row_length
    # Otherwise it remains at 0 (= width implicitly)
    if (rowstride - width * bytes_per_pixel) >= alignment:
        row_length = width + (rowstride - width * bytes_per_pixel) // bytes_per_pixel
    GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, row_length)
    GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, alignment)
    # self.gl_marker("set_alignment%s GL_UNPACK_ROW_LENGTH=%i, GL_UNPACK_ALIGNMENT=%i",
    #               (width, rowstride, pixel_format), row_length, alignment)


def upload_rgba_texture(texture: int, width: int, height: int, pixels) -> None:
    upload, pixel_data = pixels_for_upload(pixels)
    rgb_format = "RGBA"
    target = GL.GL_TEXTURE_RECTANGLE
    GL.glBindTexture(target, texture)
    set_alignment(width, width * 4, rgb_format)
    GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
    GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
    GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_BORDER)
    GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_BORDER)
    GL.glTexImage2D(target, 0, GL.GL_RGBA8, width, height, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixel_data)
    log("upload_rgba_texture %ix%i uploaded %i bytes of %s pixel data using %s",
        width, height, len(pixels), rgb_format, upload)
    GL.glBindTexture(target, 0)


def save_fbo(wid: int, fbo, texture, width: int, height: int, alpha=False, prefix="W", suffix="") -> None:
    target = GL.GL_TEXTURE_RECTANGLE
    GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, fbo)
    GL.glBindTexture(target, texture)
    GL.glFramebufferTexture2D(GL.GL_READ_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, target, texture, 0)
    GL.glReadBuffer(GL.GL_COLOR_ATTACHMENT0)
    GL.glViewport(0, 0, width, height)
    size = width * height * 4
    membuf = get_membuf(size)
    GL.glGetTexImage(target, 0, GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, membuf.get_mem_ptr())
    if pillow_major < 10:
        pixels = memoryview(membuf)
    else:
        pixels = memoryview(membuf).tobytes()
    img = Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", width * 4)
    img = ImageOps.flip(img)
    kwargs = {}
    if alpha or SAVE_BUFFERS == "jpeg":
        img = img.convert("RGB")
    if SAVE_BUFFERS == "jpeg":
        kwargs = {
            "quality": 20,
            "optimize": False,
        }
    t = time.time()
    tstr = time.strftime("%H-%M-%S", time.localtime(t))
    millis = (t * 1000) % 1000
    filename = f"./{prefix}{wid:#x}-FBO-{tstr}.{millis:03}{suffix}.{SAVE_BUFFERS}"
    log("save_fbo: saving %4ix%-4i pixels, %7i bytes to %s", width, height, size, filename)
    img.save(filename, SAVE_BUFFERS, **kwargs)
    GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, 0)
    GL.glBindTexture(target, 0)
