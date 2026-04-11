# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Config show/edit subcommand implementations extracted from xpra.scripts.main.
"""

import re

from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import POSIX, OSX, WIN32, getuid, getgid
from xpra.util.str_fn import nonl, csv
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.scripts.config import (
    OPTION_TYPES,
    InitException,
    dict_to_validated_config, fixup_options,
    get_xpra_defaults_dirs, get_defaults, read_xpra_conf,
    name_to_field,
)
from xpra.log import Logger


def get_logger() -> Logger:
    return Logger("util")


def vstr(otype: type, v) -> str:
    # just used to quote all string values
    if v is None:
        if otype is bool:
            return "auto"
        return ""
    if isinstance(v, str):
        return "'%s'" % nonl(v)
    if isinstance(v, (tuple, list)):
        return csv(vstr(otype, x) for x in v)
    return str(v)


def run_showconfig(options, args) -> ExitValue:
    log = get_logger()
    d = dict_to_validated_config({})
    fixup_options(d)
    # this one is normally only probed at build time:
    # (so probe it here again)
    if POSIX:
        try:
            from xpra.platform.pycups_printing import get_printer_definition
            for mimetype in ("pdf", "postscript"):
                pdef = get_printer_definition(mimetype)
                if pdef:
                    # ie: d.pdf_printer = "/usr/share/ppd/cupsfilters/Generic-PDF_Printer-PDF.ppd"
                    setattr(d, f"{mimetype}_printer", pdef)
        except Exception:
            pass
    VIRTUAL = ["mode"]  # no such option! (it's a virtual one for the launch by config files)
    # hide irrelevant options:
    HIDDEN = []
    if "all" not in args:
        # this logic probably belongs somewhere else:
        if OSX or WIN32:
            # these options don't make sense on win32 or osx:
            HIDDEN += ["socket-dirs", "socket-dir",
                       "wm-name", "pulseaudio-command", "pulseaudio", "xvfb", "input-method",
                       "socket-permissions", "xsettings",
                       "exit-with-children", "start-new-commands",
                       "start", "start-child",
                       "start-after-connect", "start-child-after-connect",
                       "start-on-connect", "start-child-on-connect",
                       "start-on-last-client-exit", "start-child-on-last-client-exit",
                       "use-display",
                       ]
        if WIN32:
            # "exit-ssh"?
            HIDDEN += ["lpadmin", "daemon", "mmap-group", "mdns"]
        if not OSX:
            HIDDEN += ["dock-icon", "swap-keys"]
    for opt, otype in sorted(OPTION_TYPES.items()):
        if opt in VIRTUAL:
            continue
        i = log.info
        w = log.warn
        if args:
            if ("all" not in args) and (opt not in args):
                continue
        elif opt in HIDDEN:
            i = log.debug
            w = log.debug
        k = name_to_field(opt)
        dv = getattr(d, k)
        cv = getattr(options, k, dv)
        cmpv = [dv]
        if isinstance(dv, tuple) and isinstance(cv, list):
            # defaults may have a tuple,
            # but command line parsing will create a list:
            cmpv.append(list(dv))
        if isinstance(dv, str) and dv.find("\n") > 0:
            # newline is written with a "\" continuation character,
            # so we don't read the newline back when loading the config files
            cmpv.append(re.sub("\\\\\n *", " ", dv))
        if cv not in cmpv:
            w("%-20s  (used)   = %-32s  %s", opt, vstr(otype, cv), type(cv))
            w("%-20s (default) = %-32s  %s", opt, vstr(otype, dv), type(dv))
        else:
            i("%-20s           = %s", opt, vstr(otype, cv))
    return 0


def run_showsetting(args) -> ExitValue:
    if not args:
        raise InitException("specify a setting to display")

    log = get_logger()

    settings = []
    for arg in args:
        otype = OPTION_TYPES.get(arg)
        if not otype:
            log.warn(f"{arg!r} is not a valid setting")
        else:
            settings.append(arg)

    if not settings:
        return 0

    from xpra.platform.info import get_username
    dirs = get_xpra_defaults_dirs(username=get_username(), uid=getuid(), gid=getgid())

    # default config:
    config = get_defaults()

    def show_settings() -> None:
        for setting in settings:
            value = config.get(setting)
            otype = OPTION_TYPES.get(setting, str)
            log.info("%-20s: %-40s (%s)", setting, vstr(otype, value), type(value))

    log.info("* default config:")
    show_settings()
    for d in dirs:
        config.clear()
        config.update(read_xpra_conf(d))
        log.info(f"* {d!r}:")
        show_settings()
    return 0


def run_setting(setunset: bool, args) -> ExitValue:
    from xpra.util.config import update_config_attribute, unset_config_attribute
    if not args:
        raise ValueError("missing setting argument")
    setting = args[0]
    otype = OPTION_TYPES.get(setting)
    if not otype:
        raise ValueError(f"{setting!r} is not a valid setting, see `xpra showconfig`")
    if not setunset:
        if len(args) != 1:
            raise InitException("too many arguments")
        unset_config_attribute(setting)
        return ExitCode.OK

    if len(args) < 2:
        raise InitException("specify a setting to modify and its value")
    if otype is list:
        value = args[1:]
    else:
        if len(args) > 2:
            raise ValueError(f"too many values for {setting!r} which is a {otype!r}")

        def parse_bool(value: str) -> bool:
            v = value.lower()
            if v in TRUE_OPTIONS:
                return True
            if v in FALSE_OPTIONS:
                return False
            raise ValueError("not a boolean")
        parse_fn = {
            bool: parse_bool,
        }.get(otype, otype)
        try:
            value = parse_fn(args[1])
        except (ValueError, TypeError):
            raise ValueError(f"{setting} not modified: unable to convert value {args[1]!r} to {otype!r}")
    update_config_attribute(setting, value)
    return ExitCode.OK
