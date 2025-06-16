# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from datetime import datetime
from typing import Any
from collections.abc import Sequence, Callable

from xpra.os_util import gi_import
from xpra.scripts.config import make_defaults_struct
from xpra.util.env import osexpand
from xpra.util.parsing import parse_simple_dict
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("util")

OLD_CONFIGURE_TOOL_CONFIG = "99_configure_tool.conf"
CONFIGURE_TOOL_CONFIG = "90_configure_tool.conf"


def get_system_conf_file(dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> str:
    from xpra.platform.paths import get_system_conf_dirs
    return osexpand(os.path.join(get_system_conf_dirs()[0], dirname, filename))


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
        try:
            os.makedirs(conf_dir, mode=0o755)
        except OSError as e:
            log(f"os.makedirs({conf_dir!r}, 0o755)", exc_info=True)
            log.error(f"Error creating configuration directory {conf_dir!r}:")
            log.estr(e)
            return
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
    update_config_attributes({attribute: value}, dirname, filename)


def update_config_attributes(attributes: dict[str, str | int | float | list],
                             dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    config = parse_user_config_file(dirname, filename)
    for attribute, value in attributes.items():
        value_str = str(value)
        if isinstance(value, bool):
            value_str = "yes" if bool(value) else "no"
        config[attribute] = value_str
        log(f"update config: {attribute}={value_str}")
    save_user_config_file(config, dirname, filename)


def unset_config_attribute(attribute: str, dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    unset_config_attributes((attribute, ), dirname, filename)


def unset_config_attributes(attributes: Sequence[str], dirname="conf.d", filename=CONFIGURE_TOOL_CONFIG) -> None:
    config = parse_user_config_file(dirname, filename)
    modified = False
    for attribute in attributes:
        modified |= config.pop(attribute, None) is not None
    if modified:
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


def with_config(cb: Callable[[Any], bool]) -> None:
    # load config in a thread as this involves IO,
    # then run the callback in the UI thread
    def load_config() -> None:
        defaults = make_defaults_struct()
        GLib = gi_import("GLib")
        GLib.idle_add(cb, defaults)

    start_thread(load_config, "load-config", daemon=True)


def may_migrate() -> None:
    from xpra.platform.paths import get_user_conf_dirs
    for user_conf_dir in get_user_conf_dirs():
        old_config = osexpand(os.path.join(user_conf_dir, "conf.d", OLD_CONFIGURE_TOOL_CONFIG))
        if not os.path.exists(old_config):
            continue
        new_config = osexpand(os.path.join(user_conf_dir, "conf.d", CONFIGURE_TOOL_CONFIG))
        if os.path.exists(new_config):
            continue
        try:
            os.rename(old_config, new_config)
        except OSError:
            pass


may_migrate()
