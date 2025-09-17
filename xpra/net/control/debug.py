# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import (
    Logger,
    add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for, get_all_loggers,
    add_backtrace, remove_backtrace,
)
from xpra.net.control.common import ArgsControlCommand
from xpra.util.env import envint
from xpra.util.str_fn import csv

log = Logger("util", "command")

CONTROL_DEBUG = envint("XPRA_CONTROL_DEBUG", 1)


class DebugControl(ArgsControlCommand):
    def __init__(self):
        subcommands = csv(f"'debug {subc}'" for subc in (
            "enable category", "disable category", "status", "mark", "add-backtrace", "remove-backtrace",
        ))
        super().__init__("debug", f"usage: {subcommands}", min_args=1)

    def run(self, *args):
        if not args:
            return "debug subcommands: mark, add-backtrace, remove-backtrace, enable, disable"
        if len(args) == 1 and args[0] == "status":
            return "logging is enabled for: " + csv(str(x) for x in get_all_loggers() if x.is_debug_enabled())
        log_cmd = args[0]
        if log_cmd == "mark":
            for _ in range(10):
                log.info("*" * 80)
            if len(args) > 1:
                log.info("mark: %s", " ".join(args[1:]))
            else:
                log.info("mark")
            for _ in range(10):
                log.info("*" * 80)
            return "mark inserted into logfile"
        if CONTROL_DEBUG <= 0:
            return "debug control functions are restricted"
        if len(args) < 2:
            self.raise_error("not enough arguments")
        if log_cmd == "add-backtrace":
            expressions = args[1:]
            add_backtrace(*expressions)
            return f"added backtrace expressions {expressions}"
        if log_cmd == "remove-backtrace":
            expressions = args[1:]
            remove_backtrace(*expressions)
            return f"removed backtrace expressions {expressions}"
        if log_cmd not in ("enable", "disable"):
            self.raise_error("only 'enable' and 'disable' verbs are supported")
        # each argument is a group
        loggers = []
        groups = args[1:]
        for group in groups:
            # and each group is a list of categories
            # preferably separated by "+",
            # but we support "," for backwards compatibility:
            categories = [v.strip() for v in group.replace("+", ",").split(",")]
            if log_cmd == "enable":
                if CONTROL_DEBUG < 2:
                    RESTRICTED_DEBUG_CATEGORIES = ("verbose", "network", "crypto", "auth", )
                    restricted = tuple(cat for cat in RESTRICTED_DEBUG_CATEGORIES if cat in categories)
                    if restricted:
                        warning = "Warning: enabling debug logging is restricted for: %s" % csv(repr(cat) for cat in restricted)
                        log.warn(warning)
                        return warning
                add_debug_category(*categories)
                loggers += enable_debug_for(*categories)
            elif log_cmd == "disable":
                add_disabled_category(*categories)
                loggers += disable_debug_for(*categories)
            else:
                raise ValueError(f"invalid log command {log_cmd}")
        if not loggers:
            log.info("%s debugging, no new loggers matching: %s", log_cmd, csv(groups))
        else:
            log.info("%sd debugging for:", log_cmd)
            for logger in loggers:
                log.info(" - %s", logger)
        return f"logging {log_cmd}d for " + (csv(loggers) or "<no match found>")
