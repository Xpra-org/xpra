# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr
from xpra.util.env import OSEnvContext
from xpra.util.version import parse_version, dict_version_trim
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.common import FULL_INFO
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("opengl")


def run_opengl_probe(cmd: list[str], env: dict[str, str], display_name: str):
    props: dict[str, Any] = {}
    try:
        # pylint: disable=import-outside-toplevel
        from subprocess import Popen, PIPE
        # we want the output so we can parse it:
        env["XPRA_REDIRECT_OUTPUT"] = "0"
        log(f"query_opengl() using {cmd=}, {env=}")
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, env=env)
        out, err = proc.communicate()
        log("out(%s)=%s", cmd, out)
        log("err(%s)=%s", cmd, err)
        if proc.returncode == 0:
            # parse output:
            for line in out.splitlines():
                parts = bytestostr(line).split("=")
                if len(parts) != 2:
                    continue
                k = parts[0].strip()
                v = parts[1].strip()
                if k in ("GLX", "GLU.version", "opengl", "pyopengl", "accelerate", "shading-language-version"):
                    props[k] = parse_version(v)
                else:
                    props[k] = v
            log("opengl props=%s", props)
            if props:
                glprops = typedict(props)
                if glprops.strget("success").lower() in TRUE_OPTIONS:
                    log.info(f"OpenGL is supported on display {display_name!r}")
                    renderer = glprops.strget("renderer").split(";")[0]
                    if renderer:
                        log.info(f" using {renderer!r} renderer")
                else:
                    log.info("OpenGL is not supported on this display")
                    probe_err = glprops.strget("error")
                    if probe_err:
                        log.info(f" {probe_err}")
            else:
                log.info("No OpenGL information available")
        else:
            error = bytestostr(err).strip("\n\r")
            for x in str(err).splitlines():
                if x.startswith("RuntimeError: "):
                    error = x[len("RuntimeError: "):]
                    break
                if x.startswith("ImportError: "):
                    error = x[len("ImportError: "):]
                    break
            props["error"] = error
            log.warn("Warning: OpenGL support check failed:")
            log.warn(f" {error}")
    except Exception as e:
        log("query_opengl()", exc_info=True)
        log.error("Error: OpenGL support check failed")
        log.error(f" {e!r}")
        props["error"] = str(e)
    log("OpenGL: %s", props)
    return props


def load_opengl() -> dict[str, Any]:
    with OSEnvContext(XPRA_VERIFY_MAIN_THREAD="0"):
        try:
            # import OpenGL directly
            import OpenGL
            assert OpenGL
            log("found pyopengl version %s", OpenGL.__version__)
            # this may trigger an `AttributeError` if libGLX / libOpenGL are not installed:
            from OpenGL import GL
            assert GL
            log("loaded `GL` bindings: %s", GL)
        except (ImportError, AttributeError) as e:
            return {
                'error': f'OpenGL is not available: {e}',
                'success': False,
            }
        try:
            from xpra.opengl import backing
            assert backing
        except ImportError:
            return {
                'error': '`xpra.opengl` is not available',
                'success': False,
            }
    return {}


class OpenGLInfo(StubServerMixin):
    PREFIX = "opengl"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.display = os.environ.get("DISPLAY", "")
        self.opengl = "no"
        self.opengl_props: dict[str, Any] = {}

    def init(self, opts) -> None:
        self.opengl = opts.opengl

    def threaded_setup(self) -> None:
        self.opengl_props = self.query_opengl()

    def query_opengl(self) -> dict[str, Any]:
        props: dict[str, Any] = {}
        if self.opengl.lower() == "noprobe" or self.opengl.lower() in FALSE_OPTIONS:
            log("query_opengl() skipped because opengl=%s", self.opengl)
            return props
        err = load_opengl()
        if err:
            return err
        from xpra.platform.paths import get_xpra_command
        cmd = self.get_full_child_command(get_xpra_command() + ["opengl", "--opengl=force"])
        return run_opengl_probe(cmd, self.get_child_env(), self.display)

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if FULL_INFO and self.opengl_props:
            caps[OpenGLInfo.PREFIX] = dict_version_trim(self.opengl_props)
        return caps

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[str, Any] = {}
        if self.opengl_props:
            info = dict(self.opengl_props)
        return {OpenGLInfo.PREFIX: info}
