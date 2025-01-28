# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from datetime import datetime
from typing import Callable

from xpra.os_util import gi_import
from xpra.scripts.config import make_defaults_struct
from xpra.util.env import osexpand
from xpra.util.parsing import parse_simple_dict
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("util")


CONFIGURE_TOOL_CONFIG = "99_configure_tool.conf"


def get_user_config_file(dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> str:
    from xpra.platform.paths import get_user_conf_dirs
    return osexpand(os.path.join(get_user_conf_dirs()[0], dirname, filename))


def parse_user_config_file(dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> dict[str, str | list[str] | dict[str, str]]:
    filename = get_user_config_file(dirname, filename)
    if not os.path.exists(filename):
        return {}
    with open(filename, "r", encoding="utf8") as f:
        data = f.read().replace("\r", "\n")
        return parse_simple_dict(data, sep="\n")


def save_user_config_file(options: dict,
                          dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    filename = get_user_config_file(dirname, filename)
    conf_dir = os.path.dirname(filename)
    log(f"save_user_config_file({options}, {dirname!r}, {filename!r}) {conf_dir=!r}")
    if not os.path.exists(conf_dir):
        os.mkdir(conf_dir, mode=0o755)
    with open(filename, "w", encoding="utf8") as f:
        f.write("# generated on " + datetime.now().strftime("%c")+"\n\n")
        for k, v in options.items():
            if isinstance(v, dict):
                for dk, dv in v.items():
                    f.write(f"{k} = {dk}={dv}\n")
                continue
            if not isinstance(v, (list, tuple)):
                v = [v]
            for item in v:
                f.write(f"{k} = {item}\n")


def update_config_attribute(attribute: str, value: str | int | float | list,
                            dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    config = parse_user_config_file(dirname, filename)
    value_str = str(value)
    if isinstance(value, bool):
        value_str = "yes" if bool(value) else "no"
    config[attribute] = value_str
    log(f"update config: {attribute}={value_str}")
    save_user_config_file(config, dirname, filename)


def unset_config_attribute(attribute: str, dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    config = parse_user_config_file(dirname, filename)
    if config.pop(attribute, None) is not None:
        save_user_config_file(config, dirname, filename)


def update_config_env(attribute: str, value,
                      dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    # there can be many env attributes
    log(f"update config env: {attribute}={value}")
    config = parse_user_config_file(dirname, filename)
    env = config.get("env")
    if not isinstance(env, dict):
        log.warn(f"Warning: env option was using invalid type {type(env)}")
        config["env"] = env = {}
    env[attribute] = str(value)
    save_user_config_file(config, dirname, filename)


def get_config_env(var_name: str,
                   dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> str:
    config = parse_user_config_file(dirname, filename)
    env = config.get("env", {})
    if not isinstance(env, dict):
        log.warn(f"Warning: env option was using invalid type {type(env)}")
        return ""
    return env.get(var_name, "")


def with_config(cb: Callable) -> None:
    # load config in a thread as this involves IO,
    # then run the callback in the UI thread
    def load_config():
        defaults = make_defaults_struct()
        GLib = gi_import("GLib")
        GLib.idle_add(cb, defaults)

    start_thread(load_config, "load-config", daemon=True)