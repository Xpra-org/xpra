# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from subprocess import Popen

from xpra.util.io import warn
from xpra.log import Logger


def start_macos_shadow(cmd, env, cwd) -> None:
    # launch the shadow server via launchctl,
    # so it can have GUI access:
    LAUNCH_AGENT = "org.xpra.Agent"
    LAUNCH_AGENT_FILE = f"/Library/LaunchAgents/{LAUNCH_AGENT}.plist"
    try:
        os.stat(LAUNCH_AGENT_FILE)
    except Exception as e:
        # ignore access denied error, launchctl runs as root
        import errno
        if e.args[0] != errno.EACCES:
            warn("Error: shadow may not start,\n"
                 f" the launch agent file {LAUNCH_AGENT_FILE!r} seems to be missing:{e}.\n")
    argfile = os.path.expanduser("~/.xpra/shadow-args")
    with open(argfile, "w", encoding="utf8") as f:
        f.write('["Xpra", "--no-daemon"')
        for x in cmd[1:]:
            f.write(f', "{x}"')
        f.write(']')
    launch_commands = [
        ["launchctl", "unload", LAUNCH_AGENT_FILE],
        ["launchctl", "load", "-S", "Aqua", LAUNCH_AGENT_FILE],
        ["launchctl", "start", LAUNCH_AGENT],
    ]
    log = Logger("server")
    log("start_macos_shadow: launch_commands=%s", launch_commands)
    for x in launch_commands:
        Popen(x, env=env, cwd=cwd).wait()
