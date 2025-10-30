#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import logging
from typing import Any
from collections.abc import Sequence

from xpra.util.str_fn import csv, print_nested_dict
from xpra.util.env import envint, envbool, numpy_import_context
from xpra.log import Logger, CaptureHandler, consume_verbose_argv
from xpra.opengl.drivers import GL_MATCH_LIST, WHITELIST, GREYLIST, BLOCKLIST, OpenGLFatalError

log = Logger("opengl")

required_extensions: Sequence[str] = ("GL_ARB_texture_rectangle", "GL_ARB_vertex_program")

GL_ALPHA_SUPPORTED: bool = envbool("XPRA_ALPHA", True)
DOUBLE_BUFFERED: bool = envbool("XPRA_OPENGL_DOUBLE_BUFFERED", True)

MIN_SIZE = envint("XPRA_OPENGL_MIN_SIZE", 4 * 1024)

CRASH: bool = envbool("XPRA_OPENGL_FORCE_CRASH", False)
TIMEOUT: int = envint("XPRA_OPENGL_FORCE_TIMEOUT", 0)


# by default, we raise an ImportError as soon as we find something missing:
def raise_error(msg) -> None:
    raise ImportError(msg)


def raise_fatal_error(msg) -> None:
    raise OpenGLFatalError(msg)


gl_check_error = raise_error
gl_fatal_error = raise_fatal_error


def parse_pyopengl_version(vstr: str) -> tuple[int, ...]:
    def numv(s):
        try:
            return int(s)
        except ValueError:
            return 0

    return tuple(numv(x) for x in vstr.split("."))


_version_warning_shown = False


def get_max_texture_size() -> int:
    # pylint: disable=import-outside-toplevel
    from OpenGL.GL import glGetInteger, GL_MAX_TEXTURE_SIZE
    texture_size = glGetInteger(GL_MAX_TEXTURE_SIZE)
    log("GL_MAX_TEXTURE_SIZE=%s", texture_size)
    # this one may be missing?
    rect_texture_size = texture_size
    try:
        from OpenGL.GL import GL_MAX_RECTANGLE_TEXTURE_SIZE
        rect_texture_size = glGetInteger(GL_MAX_RECTANGLE_TEXTURE_SIZE)
    except ImportError as e:
        log("OpenGL: %s", e)
        log("using GL_MAX_TEXTURE_SIZE=%s as default", texture_size)
    except Exception as e:
        log("failed to query GL_MAX_RECTANGLE_TEXTURE_SIZE: %s", e)
    else:
        log("Texture size GL_MAX_RECTANGLE_TEXTURE_SIZE=%s", rect_texture_size)
    return int(min(rect_texture_size, texture_size))


def get_array_handlers() -> Sequence[str]:
    from OpenGL.arrays.arraydatatype import ArrayDatatype
    try:
        return tuple(getattr(atype, "__name__", str(atype)) for atype in set(ArrayDatatype.getRegistry().values()))
    except Exception:
        pass
    return ()


def get_max_viewport_dims() -> tuple[int, int]:
    from OpenGL.GL import glGetIntegerv, GL_MAX_VIEWPORT_DIMS
    v = glGetIntegerv(GL_MAX_VIEWPORT_DIMS)
    max_viewport_dims = int(v[0]), int(v[1])
    log("GL_MAX_VIEWPORT_DIMS=%s", max_viewport_dims)
    return max_viewport_dims


def get_extensions() -> list[str]:
    extensions: list[str] = _get_gl_enums("extensions", "GL_NUM_EXTENSIONS", "GL_EXTENSIONS")
    if not extensions:
        # try legacy mode:
        from OpenGL.error import GLError
        try:
            from OpenGL.GL import glGetString, GL_EXTENSIONS
            extensions = glGetString(GL_EXTENSIONS).decode().split(" ")
        except GLError as e:
            log(f"error querying extensions using glGetString(GL_EXTENSIONS): {e}")
    log("OpenGL extensions found: %s", csv(extensions))
    return extensions


def _get_gl_enums(name: str, num_const: str, values_const: str) -> list[str]:
    values: list[str] = []
    from OpenGL.error import GLError
    from OpenGL import GL
    from OpenGL.GL import glGetStringi, glGetIntegerv
    num_enum = getattr(GL, num_const, None)
    values_enum = getattr(GL, values_const, None)
    if num_enum is None or values_enum is None:
        log(f"cannot query {name} using {num_const} / {values_const}: constants not found!")
        return values
    try:
        num = glGetIntegerv(num_enum)
        for i in range(num):
            values.append(glGetStringi(values_enum, i).decode("latin1"))
        log(f"OpenGL {name} found: " + csv(values))
    except GLError as e:
        log(f"error querying {name} using {num_const} / {values_const}: {e}")
    return values


def get_shader_binary_formats() -> list[str]:
    return _get_gl_enums("shader binary formats", "GL_NUM_SHADER_BINARY_FORMATS", "GL_SHADER_BINARY_FORMATS")


def get_program_binary_formats() -> list[str]:
    return _get_gl_enums("program binary formats", "GL_NUM_PROGRAM_BINARY_FORMATS", "GL_PROGRAM_BINARY_FORMATS")


def fixstring(v) -> str:
    try:
        return str(v).strip()
    except Exception:
        return str(v)


def get_vendor_info() -> dict[str, str]:
    from OpenGL.GL import GL_RENDERER, GL_VENDOR, GL_SHADING_LANGUAGE_VERSION
    from OpenGL.GL import glGetString
    info: dict[str, str] = {}
    for d, s, fatal in (
            ("vendor", GL_VENDOR, True),
            ("renderer", GL_RENDERER, True),
            ("shading-language-version", GL_SHADING_LANGUAGE_VERSION, False)
    ):
        try:
            v = glGetString(s)
            v = fixstring(v.decode())
            log("%s: %s", d, v)
            info[d] = v
        except Exception:
            if fatal:
                raise RuntimeError(f"OpenGL property {d!r} is missing")
            log(f"OpenGL property {d!r} is missing")
    return info


def get_GLU_info() -> dict[str, str]:
    props: dict[str, str] = {}
    from OpenGL.GLU import gluGetString, GLU_VERSION, GLU_EXTENSIONS
    # maybe we can continue without?
    if not bool(gluGetString):
        return props
    for d, s in {
        "GLU": GLU_VERSION,
        "GLU.extensions": GLU_EXTENSIONS,
    }.items():
        v = gluGetString(s)
        v = fixstring(v.decode())
        log("%s: %s", d, v)
        if v:
            props[d] = v
    return props


def get_context_info() -> dict[str, Any]:
    with numpy_import_context("OpenGL: context info", True):
        from OpenGL.GL import glGetIntegerv
        from OpenGL.GL import (
            GL_CONTEXT_PROFILE_MASK, GL_CONTEXT_CORE_PROFILE_BIT,
            GL_CONTEXT_FLAGS,
            GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT,
            GL_CONTEXT_FLAG_ROBUST_ACCESS_BIT,
            GL_CONTEXT_FLAG_DEBUG_BIT,
            GL_CONTEXT_FLAG_NO_ERROR_BIT,
        )
        flags = glGetIntegerv(GL_CONTEXT_FLAGS)
        return {
            "core-profile": bool(glGetIntegerv(GL_CONTEXT_PROFILE_MASK) & GL_CONTEXT_CORE_PROFILE_BIT),
            "flags": tuple(k for k, v in {
                "forward-compatible": GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT,
                "debug": GL_CONTEXT_FLAG_DEBUG_BIT,
                "robust-access": GL_CONTEXT_FLAG_ROBUST_ACCESS_BIT,
                "no-error": GL_CONTEXT_FLAG_NO_ERROR_BIT,
            }.items() if flags & v),
        }


def check_available(*functions) -> str:
    missing = []
    available = []
    for x in functions:
        try:
            name = x.__name__
        except AttributeError:
            name = str(x)
        if not bool(x):
            missing.append(name)
        else:
            available.append(name)
    if missing:
        log("some functions are missing: %s", csv(missing))
        return "missing functions: " + csv(missing)
    else:
        log("All the required OpenGL functions are available: %s " % csv(available))
    return ""


def check_base_functions() -> str:
    # check for specific functions we need:
    from OpenGL.GL import (
        glActiveTexture, glTexSubImage2D, glTexCoord2i,
        glViewport, glMatrixMode, glLoadIdentity, glOrtho,
        glEnableClientState, glGenTextures, glDisable,
        glBindTexture, glPixelStorei, glEnable, glFlush,
        glTexParameteri, glTexEnvi, glHint, glBlendFunc, glLineStipple,
        glTexImage2D,
        glMultiTexCoord2i,
        glVertex2i,
    )
    return check_available(
        glActiveTexture, glTexSubImage2D, glTexCoord2i,
        glViewport, glMatrixMode, glLoadIdentity, glOrtho,
        glEnableClientState, glGenTextures, glDisable,
        glBindTexture, glPixelStorei, glEnable, glFlush,
        glTexParameteri, glTexEnvi, glHint, glBlendFunc, glLineStipple,
        glTexImage2D,
        glMultiTexCoord2i,
        glVertex2i,
    )


def check_framebuffer_functions() -> str:
    # check for framebuffer functions we need:
    from OpenGL.GL.ARB.framebuffer_object import (
        GL_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
        GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1,
        glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D,
    )
    return check_available(
        GL_FRAMEBUFFER, GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER,
        GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1,
        glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D,
    )


def check_shader_functions() -> str:
    from OpenGL.GL import (
        glCreateShader, glDeleteShader,
        glShaderSource, glCompileShader, glGetShaderiv, glGetShaderInfoLog,
        glDeleteProgram,
        GL_FRAGMENT_SHADER, GL_COMPILE_STATUS,
    )
    # don't check GL_FALSE, which is zero!
    return check_available(
        glCreateShader, glDeleteShader,
        glShaderSource, glCompileShader, glGetShaderiv, glGetShaderInfoLog,
        glDeleteProgram,
        GL_FRAGMENT_SHADER, GL_COMPILE_STATUS,
    )


def check_texture_functions() -> str:
    from OpenGL.GL.ARB.texture_rectangle import glInitTextureRectangleARB
    return check_available(glInitTextureRectangleARB)


def match_list(props: dict[str, Any], thelist: GL_MATCH_LIST, listname: str) -> tuple[str, str] | None:
    for k, values in thelist.items():
        prop = str(props.get(k))
        if prop and any(True for x in values if prop.find(x) >= 0):
            log("%s '%s' found in %s: %s", k, prop, listname, values)
            return k, prop
        log("%s '%s' not found in %s: %s", k, prop, listname, values)
    return None


def check_lists(props: dict[str, Any], force_enable=False) -> bool:
    blocklisted = match_list(props, BLOCKLIST, "blocklist")
    greylisted = match_list(props, GREYLIST, "greylist")
    whitelisted = match_list(props, WHITELIST, "whitelist")
    if blocklisted:
        if whitelisted:
            log.info("%s '%s' enabled (found in both blocklist and whitelist)", *whitelisted)
        elif force_enable:
            log.info("OpenGL %s '%s' is blocklisted!", *blocklisted)
            log.info(" force enabled by option")
        else:
            log.info("OpenGL %s '%s' is blocklisted!", *blocklisted)
            raise_fatal_error("%s '%s' is blocklisted!" % blocklisted)
    if greylisted and not whitelisted:
        log.info("OpenGL %s '%s' is greylisted,", *greylisted)
        log.info(" you may want to turn off OpenGL if you encounter bugs")
    return bool(whitelisted) or not bool(blocklisted)


def check_PyOpenGL_support(force_enable: bool) -> dict[str, Any]:
    redirected_loggers: dict[str, tuple[Logger, list, bool]] = {}
    try:
        if CRASH:
            from xpra.os_util import crash
            crash()
            raise RuntimeError("should have crashed!")
        if TIMEOUT > 0:
            import time
            time.sleep(TIMEOUT)

        # log redirection:
        for name in ("formathandler", "extensions", "acceleratesupport", "arrays", "converters", "plugins"):
            logger = logging.getLogger(f"OpenGL.{name}")
            redirected_loggers[name] = (logger, list(logger.handlers), logger.propagate)
            logger.handlers = [CaptureHandler()]
            logger.propagate = False
        log(f"{redirected_loggers=}")

        with numpy_import_context("OpenGL: check", True):
            return do_check_PyOpenGL_support(force_enable)

    finally:
        def recs(rname) -> list[str]:
            rlog = redirected_loggers.get(rname)
            if not rlog:
                return []
            records = rlog[0].handlers[0].records
            return list(rec.getMessage() for rec in records)

        for msg in recs("acceleratesupport"):
            # strip default message prefix:
            msg = msg.replace("No OpenGL_accelerate module loaded: ", "")
            if msg == "No module named OpenGL_accelerate":
                msg = "missing accelerate module"
            if msg == "OpenGL_accelerate module loaded":
                log.info(msg)
            else:
                log.warn("PyOpenGL warning: %s", msg)

        # format handler messages:
        strip_log_message = "Unable to load registered array format handler "
        missing_handlers = []
        for msg in recs("formathandler"):
            log.info(f"msg formathandler={msg}")
            p = msg.find(strip_log_message)
            if p < 0:
                # unknown message, log it:
                log.info(msg)
                continue
            format_handler = msg[p + len(strip_log_message):]
            p = format_handler.find(":")
            if p > 0:
                format_handler = format_handler[:p]
                missing_handlers.append(format_handler)
        if missing_handlers:
            log.warn("PyOpenGL warning: missing array format handlers: %s", csv(missing_handlers))

        for msg in recs("extensions"):
            # hide extension messages:
            if msg.startswith("GL Extension ") or msg.endswith("available"):
                log(msg)
            else:
                log.info(msg)

        missing_accelerators = []
        strip_ar_head = "Unable to load"
        strip_ar_tail = "from OpenGL_accelerate"
        for msg in recs("arrays") + recs("converters"):
            if msg.startswith(strip_ar_head) and msg.endswith(strip_ar_tail):
                m = msg[len(strip_ar_head):-len(strip_ar_tail)].strip()
                m = m.replace("accelerators", "").replace("accelerator", "").strip()
                missing_accelerators.append(m)
                continue
            if msg.startswith("Using accelerated"):
                log(msg)
            else:
                log.info(msg)
        if missing_accelerators:
            missing_str = csv(missing_accelerators)
            if missing_str == "numpy_formathandler":
                log_fn = log.debug
            else:
                log_fn = log.info
            log_fn(f"OpenGL accelerate missing: {missing_str}")

        for msg in recs("plugins"):
            log(f"plugins msg={msg}")

        for logger, handlers, propagate in redirected_loggers.values():
            logger.handlers = handlers
            logger.propagate = propagate


def do_check_PyOpenGL_support(force_enable) -> dict[str, Any]:
    props: dict[str, Any] = {
        "platform": sys.platform,
    }
    try:
        from OpenGL import platform
        props["backend"] = platform.PLATFORM.__module__.split(".")[-1]
    except (AttributeError, IndexError):
        pass

    def unsafe(warning: str):
        log(f"unsafe: {warning}")
        props["safe"] = False
        warnings = props.get("warning", [])
        warnings.append(warning)
        props["warning"] = warnings

    import OpenGL
    props["pyopengl"] = OpenGL.__version__  # @UndefinedVariable
    from OpenGL.GL import GL_VERSION, glGetString
    gl_version_str = (glGetString(GL_VERSION) or b"").decode("latin1")
    if not gl_version_str and not force_enable:
        raise_fatal_error("OpenGL version is missing - cannot continue")
        return props
    # '4.6.0 NVIDIA 440.59' -> ['4', '6', '0 NVIDIA...']
    log("GL_VERSION=%s", gl_version_str)
    vparts = gl_version_str.split(" ", 1)[0].split(".")
    try:
        gl_major = int(vparts[0])
        gl_minor = int(vparts[1])
    except (IndexError, ValueError) as e:
        msg = "failed to parse gl version '%s': %s" % (gl_version_str, e)
        unsafe(msg)
        log(" assuming this is at least 1.1 to continue")
    else:
        props["opengl"] = gl_major, gl_minor
        min_version = (1, 1)
        if (gl_major, gl_minor) < min_version:
            req_vstr = ".".join([str(x) for x in min_version])
            msg = f"OpenGL output requires version {req_vstr} or greater, not {gl_major}.{gl_minor}"
            unsafe(msg)
        else:
            log(f"found valid OpenGL version: {gl_major}.{gl_minor}")

    from OpenGL import version as opengl_version
    pyopengl_version = opengl_version.__version__
    try:
        import OpenGL_accelerate
        accel_version = OpenGL_accelerate.__version__
        props["accelerate"] = accel_version
        log(f"OpenGL_accelerate version {accel_version}")
    except ImportError:
        log("OpenGL_accelerate not found")
        accel_version = ""

    if accel_version and pyopengl_version != accel_version:
        global _version_warning_shown
        if not _version_warning_shown:
            log.warn("Warning: version mismatch between PyOpenGL and PyOpenGL-accelerate")
            log.warn(" %s vs %s", pyopengl_version, accel_version)
            log.warn(" this may cause crashes")
            _version_warning_shown = True
            gl_check_error(f"PyOpenGL vs accelerate version mismatch: {pyopengl_version} vs {accel_version}")
    vernum = parse_pyopengl_version(pyopengl_version)
    # we now require PyOpenGL 3.1.4 or later
    # 3.1.4 was released in 2019
    if vernum < (3, 1, 4):
        msg = f"PyOpenGL version {pyopengl_version} is too old and buggy"
        unsafe(msg)
        if not force_enable:
            raise_fatal_error(msg)
            return props
    props["zerocopy"] = bool(accel_version and pyopengl_version == accel_version)

    props.update(get_vendor_info())
    props.update(get_GLU_info())
    props.update({
        "extensions": get_extensions(),
        "array-handlers": get_array_handlers(),
        "texture-size-limit": get_max_texture_size(),
        "max-viewport-dims": get_max_viewport_dims(),
    })
    # props["shader-binary-formats"] = get_shader_binary_formats()
    # props["program-binary-formats"] = get_program_binary_formats()

    for check_fn in (
            check_base_functions,
            check_framebuffer_functions,
            check_texture_functions,
            check_shader_functions,
    ):
        msg = check_fn()
        if msg:
            unsafe(msg)

    safe = check_lists(props, force_enable)
    if "safe" not in props:
        props["safe"] = safe
    if safe and match_list(props, GREYLIST, "greylist"):
        props["enable"] = False
        props["message"] = "driver found in greylist"
    try:
        props.update(get_context_info())
    except Exception as e:
        unsafe(f"error querying context flags: {e}")
    return props


def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    from xpra.log import enable_color
    with program_context("OpenGL-Check"):
        gui_init()
        enable_color()
        consume_verbose_argv(sys.argv, "opengl")
        from xpra.gtk.util import init_display_source
        init_display_source()
        force_enable = "-f" in sys.argv or "--force" in sys.argv
        from xpra.platform.gl_context import GLContext
        if not GLContext:
            log.warn("No OpenGL context implementation found")
            return 1
        log("testing %s", GLContext)
        gl_context = GLContext()  # pylint: disable=not-callable
        log("GLContext=%s", gl_context)
        # replace ImportError with a log message:
        global gl_check_error, gl_fatal_error
        errors = []

        def log_error(msg):
            log.error("ERROR: %s", msg)
            errors.append(msg)

        gl_check_error = log_error
        gl_fatal_error = log_error
        try:
            props = gl_context.check_support(force_enable)
        except Exception as e:
            props = {}
            log("check_support", exc_info=True)
            errors.append(e)
        log.info("")
        if errors:
            log.info("OpenGL errors:")
            for err in errors:
                log.info("  %s", err)
        if props:
            log.info("")
            log.info("OpenGL properties:")
            print_nested_dict(props)
        return len(errors)


if __name__ == "__main__":
    sys.exit(main())
