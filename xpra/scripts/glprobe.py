# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# OpenGL probe and check utilities.
# Separated from xpra/scripts/main.py to allow unit testing without pulling in
# the full main module (GTK, GLib, server/client startup logic, etc.).

import sys
import signal
import logging
from time import monotonic
from subprocess import Popen, PIPE, TimeoutExpired
from importlib.util import find_spec
from typing import Any, NoReturn

from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import POSIX, OSX, force_quit
from xpra.util.env import OSEnvContext, get_exec_env, envint
from xpra.util.io import stderr_print, use_tty
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, pver
from xpra.util.system import is_Wayland, SIGNAMES
from xpra.log import Logger, is_debug_enabled

# pylint: disable=import-outside-toplevel

OPENGL_PROBE_TIMEOUT: int = envint("XPRA_OPENGL_PROBE_TIMEOUT", 5)


def run_opengl_probe() -> tuple[str, dict]:
    log = Logger("opengl")
    if not find_spec("OpenGL"):
        log("OpenGL module not found!")
        error = "missing OpenGL module"
        return f"error:{error}", {
            "error": error,
            "success": False,
        }
    from xpra.platform.paths import get_nodock_command
    from xpra.net.subprocess_wrapper import exec_kwargs
    cmd = get_nodock_command() + ["opengl"]
    env = get_exec_env()
    if is_debug_enabled("opengl"):
        cmd += ["-d", "opengl"]
    else:
        env["NOTTY"] = "1"
    env["XPRA_HIDE_DOCK"] = "1"
    env["XPRA_REDIRECT_OUTPUT"] = "0"
    start = monotonic()
    kwargs = exec_kwargs(stderr=PIPE)
    log(f"run_opengl_probe() using cmd={cmd} with env={env=} and {kwargs=}")
    try:
        proc = Popen(cmd, stdout=PIPE, env=env, universal_newlines=True, **kwargs)
    except Exception as e:
        log.warn("Warning: failed to execute OpenGL probe command")
        log.warn(" %s", e)
        return "failed", {"message": str(e).replace("\n", " ")}
    try:
        stdout, stderr = proc.communicate(timeout=OPENGL_PROBE_TIMEOUT)
        r = proc.returncode
    except TimeoutExpired:
        log("opengl probe command timed out")
        proc.kill()
        stdout, stderr = proc.communicate()
        r = None
    log("xpra opengl stdout:")
    for line in stdout.splitlines():
        log(" %s", line)
    log("xpra opengl stderr:")
    for line in stderr.splitlines():
        log(" %s", line)
    log("OpenGL probe command returned %s for command=%s", r, cmd)
    end = monotonic()
    log("probe took %ims", 1000 * (end - start))
    props = {}
    for line in stdout.splitlines():
        parts = line.split("=", 1)
        if len(parts) == 2:
            key = parts[0]
            value = parts[1]
            if key.find("-size") > 0:
                try:
                    value = int(value)
                except ValueError:
                    pass
            if key.endswith("-dims"):
                try:
                    value = tuple(int(item.strip(" ")) for item in value.split(","))
                except ValueError:
                    pass
            elif value in ("True", "False"):
                value = value == "True"
            props[key] = value
    log("parsed OpenGL properties=%s", props)

    def probe_message() -> str:
        tdprops = typedict(props)
        err = tdprops.strget("error")
        msg = tdprops.strget("message")
        warning = tdprops.strget("warning").split(":")[0]
        if err:
            return f"error:{err}"
        if r == 1:
            return "crash"
        if r is None:
            return "timeout"
        if r > 128:
            return "failed:%s" % SIGNAMES.get(r - 128)
        if r != 0:
            return "failed:%s" % SIGNAMES.get(0 - r, 0 - r)
        if not tdprops.boolget("success", False):
            return "error:%s" % (err or msg or warning)
        if not tdprops.boolget("safe", False):
            return "warning:%s" % (err or msg)
        if not tdprops.boolget("enable", True):
            return f"disabled:{msg}"
        return "success"

    message = probe_message()
    log(f"probe_message()={message!r}")
    return message, props


def run_glprobe(opts, show=False) -> ExitValue:
    if show:
        from xpra.platform.gui import init, set_default_icon
        set_default_icon("opengl.png")
        init()

    def signal_handler(signum, _frame) -> NoReturn:
        force_quit(128 - signum)

    for name in ("ABRT", "BUS", "FPE", "HUP", "ILL", "INT", "PIPE", "SEGV", "TERM"):
        value = getattr(signal, f"SIG{name}", 0)
        if value:
            signal.signal(value, signal_handler)

    props = do_run_glcheck(opts, show)
    if not props.get("success", False):
        return ExitCode.FAILURE
    if not props.get("safe", False):
        return ExitCode.OPENGL_UNSAFE
    return ExitCode.OK


def do_run_glcheck(opts, show=False) -> dict[str, Any]:
    # suspend all logging:
    saved_level = None
    log = Logger("opengl")
    log(f"do_run_glcheck(.., {show})")
    if not is_debug_enabled("opengl") or not use_tty():
        saved_level = logging.root.getEffectiveLevel()
        logging.root.setLevel(logging.WARN)
    try:
        from xpra.opengl.window import get_gl_client_window_module, test_gl_client_window
        opengl_str = (opts.opengl or "").lower()
        opengl_props, gl_client_window_module = get_gl_client_window_module(opengl_str)
        log("do_run_glcheck() opengl_props=%s, gl_client_window_module=%s", opengl_props, gl_client_window_module)
        if gl_client_window_module and (opengl_props.get("safe", False) or opengl_str.startswith("force")):
            gl_client_window_class = gl_client_window_module.GLClientWindow
            pixel_depth = int(opts.pixel_depth)
            log("do_run_glcheck() gl_client_window_class=%s, pixel_depth=%s", gl_client_window_class, pixel_depth)
            if pixel_depth not in (0, 16, 24, 30) and pixel_depth < 32:
                pixel_depth = 0
            draw_result = test_gl_client_window(gl_client_window_class, pixel_depth=pixel_depth, show=show)
            log(f"draw result={draw_result}")
            opengl_props.update(draw_result)
            if not draw_result.get("success", False):
                opengl_props["safe"] = False
        log("do_run_glcheck(.., %s)=%s", show, opengl_props)
        return opengl_props
    except Exception as e:
        if is_debug_enabled("opengl"):
            log("do_run_glcheck(..)", exc_info=True)
        if use_tty():
            stderr_print(f"error={e!r}")
        return {
            "success": False,
            "message": str(e).replace("\n", " "),
        }
    finally:
        if saved_level is not None:
            logging.root.setLevel(saved_level)


def run_glcheck(opts) -> ExitValue:
    # cheap easy check first:
    log = Logger("opengl")
    if not find_spec("OpenGL"):
        log("OpenGL module not found!")
        props = {
            "error": "missing OpenGL module",
            "success": False,
        }
    else:
        from xpra.scripts.main import check_gtk_client
        check_gtk_client()
        if POSIX and not OSX and not is_Wayland():
            log("forcing x11 Gdk backend")
            with OSEnvContext(GDK_BACKEND="x11", PYOPENGL_BACKEND="x11"):
                try:
                    from xpra.x11.gtk.display_source import init_gdk_display_source
                    init_gdk_display_source()
                except ImportError as e:
                    log(f"no bindings x11 bindings: {e}")
                except Exception:
                    log("error initializing gdk display source", exc_info=True)
        try:
            props = do_run_glcheck(opts)
        except Exception as e:
            props = {
                "error": str(e).replace("\n", " "),
                "success": False,
            }
    log("run_glcheck(..) props=%s", props)
    for k in sorted(props.keys()):
        v = props[k]
        # skip not human readable:
        if k not in ("extensions", "glconfig", "GLU.extensions",):
            vstr = str(v)
            try:
                if k.endswith("dims"):
                    vstr = csv(v)
                else:
                    vstr = pver(v)
            except ValueError:
                pass
            sys.stdout.write("%s=%s\n" % (k, vstr))
    sys.stdout.flush()
    return 0


def run_glsaveprobe() -> ExitValue:
    probe_info = run_opengl_probe()[1]
    glinfo = typedict(probe_info)
    safe = glinfo.boolget("safe", False)
    save_opengl_probe(safe)
    print(f"saved opengl={safe} in ")
    return 0


def save_opengl_probe(result: bool) -> None:
    from xpra.util.config import save_user_config_file, CONFIGURE_TOOL_CONFIG
    save_user_config_file({"opengl": result}, filename=CONFIGURE_TOOL_CONFIG)
