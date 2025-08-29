# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from importlib import import_module

from xpra.os_util import is_admin
from xpra.platform import program_context
from xpra.util.config import get_user_config_file, get_system_conf_file
from xpra.scripts.config import InitExit
from xpra.exit_codes import ExitCode, ExitValue


def main(args=()) -> ExitValue:
    with program_context("Configure", "Configure"):
        if is_admin():
            conf = get_system_conf_file()
        else:
            conf = get_user_config_file()
        subcommand = args[0] if args else "home"
        if subcommand == "reset":
            import datetime
            now = datetime.datetime.now()
            with open(conf, "w", encoding="utf8") as f:
                f.write("# this file was reset on "+now.strftime("%Y-%m-%d %H:%M:%S"))
            return ExitCode.OK
        elif subcommand == "backup":
            if not os.path.exists(conf):
                print(f"# {conf!r} does not exist yet")
                return ExitCode.FILE_NOT_FOUND
            bak = conf[-5:]+".bak"
            with open(conf, "r", encoding="utf8") as read:
                with open(bak, "w", encoding="utf8") as write:
                    write.write(read.read())
            return ExitCode.OK
        elif subcommand == "show":
            if not os.path.exists(conf):
                print(f"# {conf!r} does not exist yet")
            else:
                with open(conf, "r", encoding="utf8") as f:
                    print(f.read())
            return ExitCode.OK
        else:
            if any(not str.isalnum(x) for x in subcommand):
                raise ValueError("invalid characters found in subcommand")
            try:
                mod = import_module(f"xpra.gtk.configure.{subcommand}")
            except ImportError:
                mod = None
            if not mod:
                raise InitExit(ExitCode.FILE_NOT_FOUND, f"unknown configure subcommand {subcommand!r}")
            return mod.main(args[1:])


if __name__ == "__main__":
    import sys
    sys.exit(int(main(sys.argv[1:])))
