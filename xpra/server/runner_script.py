# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.os_util import OSX, POSIX
from xpra.util.env import osexpand
from xpra.util.io import umask_context
from xpra.log import Logger


def sh_quotemeta(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def xpra_env_shell_script(socket_dir: str, env: dict[str, str]) -> str:
    script = ["#!/bin/sh", ""]
    for var, value in env.items():
        if var in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH"):
            # prevent those paths from accumulating the same values multiple times,
            # only keep the first one:
            pathsep = os.pathsep
            pval = value.split(pathsep)  # ie: ["/usr/bin", "/usr/local/bin", "/usr/bin"]
            seen = set()
            value = pathsep.join(x for x in pval if not (x in seen or seen.add(x)))  # type: ignore[func-returns-value]
            qval = sh_quotemeta(value) + f':"${var}"'
        elif var in (
                # whitelist:
                "XDG_MENU_PREFIX", "XDG_RUNTIME_DIR",
                "XAUTHORITY",
                "HOSTNAME", "HOME", "USERNAME", "USER",
                "SSH_ASKPASS",
        ):
            qval = sh_quotemeta(value)
        else:
            continue
        script.append(f"{var}={qval}; export {var}")
    # XPRA_SOCKET_DIR is a special case, we want to honour it
    # when it is specified, but the client may override it:
    if socket_dir:
        script.append('if [ -z "${XPRA_SOCKET_DIR}" ]; then')
        qdir = sh_quotemeta(os.path.expanduser(socket_dir))
        script.append(f'    XPRA_SOCKET_DIR="{qdir}"; export XPRA_SOCKET_DIR')
        script.append('fi')
    script.append("")
    return "\n".join(script)


def xpra_runner_shell_script(xpra_file: str, starting_dir: str) -> str:
    # We ignore failures in cd'ing, b/c it's entirely possible that we were
    # started from some temporary directory and all paths are absolute.
    qdir = sh_quotemeta(starting_dir)
    script = [
        "",
        f"cd {qdir}"]
    if OSX:
        # OSX contortions:
        # The executable is the python interpreter,
        # which is execed by a shell script, which we have to find..
        sexec = sys.executable
        bini = sexec.rfind("Resources/bin/")
        if bini > 0:
            sexec = os.path.join(sexec[:bini], "Resources", "MacOS", "Xpra")
        script.append(f"_XPRA_SCRIPT={sh_quotemeta(sexec)}\n")
        script.append("""
if command -v "$_XPRA_SCRIPT" > /dev/null; then
    # Happypath:
    exec "$_XPRA_SCRIPT" "$@"
else
    # Hope for the best:
    exec Xpra "$@"
fi
""")
    else:
        script.append("_XPRA_PYTHON=%s" % (sh_quotemeta(sys.executable),))
        script.append("_XPRA_SCRIPT=%s" % (sh_quotemeta(xpra_file),))
        script.append("""
if command -v "$_XPRA_PYTHON" > /dev/null && [ -e "$_XPRA_SCRIPT" ]; then
    # Happypath:
    exec "$_XPRA_PYTHON" "$_XPRA_SCRIPT" "$@"
else
    cat >&2 <<END
    Could not find one or both of '$_XPRA_PYTHON' and '$_XPRA_SCRIPT'
    Perhaps your environment has changed since the xpra server was started?
    I'll just try executing 'xpra' with current PATH, and hope...
END
    exec xpra "$@"
fi
""")
    return "\n".join(script)


def write_runner_shell_scripts(contents: str, overwrite: bool = True) -> None:
    assert POSIX and BACKWARDS_COMPATIBLE
    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    log = Logger("server")
    MODE = 0o700
    from xpra.platform.paths import get_script_bin_dirs
    for d in get_script_bin_dirs():
        scriptdir = osexpand(d)
        if not os.path.exists(scriptdir):
            try:
                os.mkdir(scriptdir, MODE)
            except Exception as e:
                log("os.mkdir(%s, %s)", scriptdir, oct(MODE), exc_info=True)
                log.warn("Warning: failed to create script directory '%s':", scriptdir)
                log.warn(" %s", e)
                if scriptdir.startswith("/var/run/user") or scriptdir.startswith("/run/user"):
                    log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
                continue
        scriptpath = os.path.join(scriptdir, "run-xpra")
        if os.path.exists(scriptpath) and not overwrite:
            continue
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        try:
            with umask_context(0o022):
                h = os.open(scriptpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MODE)
                try:
                    os.write(h, contents.encode())
                finally:
                    os.close(h)
        except Exception as e:
            log("writing to %s", scriptpath, exc_info=True)
            log.error("Error: failed to write script file '%s':", scriptpath)
            log.error(" %s\n", e)
