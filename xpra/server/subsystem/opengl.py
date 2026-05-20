# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.util.objects import typedict
from xpra.util.str_fn import bytestostr
from xpra.util.thread import start_thread
from xpra.util.version import parse_version, dict_version_trim
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.net.common import FULL_INFO
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("opengl")


def run_opengl_probe(cmd: list[str], env: dict[str, str], display_name: str):
    props: dict[str, Any] = {}
    try:
        # pylint: disable=import-outside-toplevel
        from subprocess import Popen, PIPE
        # we want the output so we can parse it:
        env["XPRA_REDIRECT_OUTPUT"] = "0"
        env["XPRA_OPENGL_ZEROCOPY_UPLOAD_WARNING"] = "0"
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
                    error = x.removeprefix("RuntimeError: ")
                    break
                if x.startswith("ImportError: "):
                    error = x.removeprefix("ImportError: ")
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


def probe_opengl_module() -> dict[str, Any]:
    """Check that `OpenGL` and `xpra.opengl` are installable, *without*
    importing them. Importing PyOpenGL would drag in the IntConstant
    tables, baseplatform.py and the wrapper machinery (~6 MB and
    thousands of objects) — none of which the parent server process
    needs, since the actual probe runs in an `xpra opengl` subprocess.
    """
    from importlib.util import find_spec
    try:
        if find_spec("OpenGL") is None:
            return {"error": "OpenGL is not available: PyOpenGL not installed", "success": False}
        if find_spec("xpra.opengl") is None:
            return {"error": "`xpra.opengl` is not available", "success": False}
    except (ImportError, ValueError) as e:
        return {"error": f"OpenGL is not available: {e}", "success": False}
    return {}


class OpenGLInfo(StubSubsystem):
    PREFIX = "opengl"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.display = os.environ.get("DISPLAY", "")
        self.option = "no"
        self.props: dict[str, Any] = {}

    def init(self, opts) -> None:
        self.option = opts.opengl

    def setup(self) -> None:
        if self.option.lower() == "noprobe" or self.option.lower() in FALSE_OPTIONS:
            log("setup() query_opengl skipped because opengl=%s", self.option)
            return

        def query() -> None:
            self.props = self.query_opengl()
        start_thread(query, "query-opengl", daemon=True)

    def query_opengl(self) -> dict[str, Any]:
        """
        Run an `xpra opengl --opengl=force` subprocess to probe the OpenGL
        capabilities, so the parent server never pays the ~6 MB /
        thousands-of-objects PyOpenGL import cost.

        Note on child-command plumbing: `ChildCommandServer` (when present)
        provides an *enhanced* `get_full_child_command` that prepends the
        configured `exec_wrapper`; we route through it via `get_subsystem`
        so the wrapper is honoured here too. The environment is gathered
        from the server's `get_child_env`, which on `ServerBase` aggregates
        contributions from every subsystem.
        """
        err = probe_opengl_module()
        if err:
            return err
        from xpra.platform.paths import get_xpra_command
        cmd = get_xpra_command() + ["opengl", "--opengl=force"]
        cmd_helper = self.get_subsystem("command") or self
        cmd = cmd_helper.get_full_child_command(cmd)
        return run_opengl_probe(cmd, self.server.get_child_env(), self.display)

    def get_caps(self, source) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if FULL_INFO and self.props:
            caps[OpenGLInfo.PREFIX] = dict_version_trim(self.props)
        return caps

    def get_info(self, _proto) -> dict[str, Any]:
        info: dict[str, Any] = {}
        if self.props:
            info = dict(self.props)
        return {OpenGLInfo.PREFIX: info}
