# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


def sh_quotemeta(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def xpra_env_shell_script(socket_dirs: list[str] | tuple[str, ...], env: dict[str, str]) -> str:
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
    socket_dir = socket_dirs[0] if socket_dirs else ""
    if socket_dir:
        script.append('if [ -z "${XPRA_SOCKET_DIR}" ]; then')
        qdir = sh_quotemeta(os.path.expanduser(socket_dir))
        script.append(f'    XPRA_SOCKET_DIR={qdir}; export XPRA_SOCKET_DIR')
        script.append('fi')
    script.append("")
    return "\n".join(script)
