#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Configuration text parsing, file IO, and configuration directory precedence."""

import os
from typing import Any
from collections.abc import Iterable
from xpra import config as config_log
from xpra.config.types import OPTION_TYPES, name_to_field
from xpra.util.env import osexpand


DEBUG_CONFIG_PROPERTIES: list[str] = os.environ.get("XPRA_DEBUG_CONFIG_PROPERTIES", "").split()
DEFAULT_XPRA_CONF_FILENAME: str = os.environ.get("XPRA_CONF_FILENAME", "xpra.conf")


def save_config(conf_file: str, config, keys, extras_types=None) -> None:
    with open(conf_file, "w", encoding="utf8") as f:
        option_types = OPTION_TYPES.copy()
        if extras_types:
            option_types.update(extras_types)
        saved = {}
        for key in keys:
            if key not in option_types:
                raise ValueError(f"invalid configuration key {key!r}")
            v = getattr(config, name_to_field(key))
            saved[key] = v
            f.write(f"{key}={v}{os.linesep}")
        config_log.debug(f"save_config: saved {saved} to {conf_file!r}")


def read_config(conf_file: str) -> dict[str, Any]:
    """
        Parses a config file into a dict of strings.
        If the same key is specified more than once,
        the value for this key will be an array of strings.
    """
    d: dict[str, str | list[str]] = {}
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        config_log.debug("read_config(%s) is not a file or does not exist", conf_file)
        return d
    with open(conf_file, encoding="utf8") as f:
        return parse_config_lines(f, conf_file)


def parse_config_lines(lines: Iterable[str], filename: str = "") -> dict[str, Any]:
    """Parse configuration text without reading files or discovering defaults."""
    d: dict[str, str | list[str]] = {}
    parsed_lines = []
    no = 0
    for line in lines:
        sline = line.strip().strip('\r\n').strip()
        no += 1
        if not sline:
            config_log.debug("%4s empty line", no)
            continue
        if sline[0] in ('!', '#'):
            config_log.debug("%4s skipping comments   : %s", no, sline[:16]+"..")
            continue
        config_log.debug("%4s loaded              : %s", no, sline)
        parsed_lines.append(sline)
    config_log.debug("loaded %s lines", len(parsed_lines))
    # aggregate any lines with trailing backslash
    agg_lines = []
    l = ""
    for line in parsed_lines:
        if line.endswith("\\"):
            l += line[:-1]+" "
        else:
            l += line
            agg_lines.append(l)
            l = ""
    if l:
        # last line had a trailing backslash... meh
        agg_lines.append(l)
    config_log.debug("loaded %s aggregated lines", len(agg_lines))
    # parse name=value pairs:
    for sline in agg_lines:
        if sline.find("=") <= 0:
            config_log.debug(f"skipping line which is missing an equal sign: {sline!r}")
            continue
        props = sline.split("=", 1)
        assert len(props) == 2
        name = props[0].strip()
        value = props[1].strip()
        if current_value := d.get(name):
            if isinstance(current_value, list):
                d[name] = current_value + [value]
            else:
                d[name] = [current_value, value]
            config_log.debug("added to: %s='%s'", name, d[name])
        else:
            config_log.debug("assigned (new): %s='%s'", name, value)
            d[name] = value
        if name in DEBUG_CONFIG_PROPERTIES:
            from xpra.log import Logger
            log = Logger("util")
            log.info(f"{name}={d[name]} (was {current_value}), from {filename!r}")
    return d


def conf_files(conf_dir: str, xpra_conf_filename: str = DEFAULT_XPRA_CONF_FILENAME) -> list[str]:
    """
        Returns all the config file paths found in the config directory
        ie: ["/etc/xpra/conf.d/15_features.conf", ..., "/etc/xpra/xpra.conf"]
    """
    d: list[str] = []
    cdir = os.path.expanduser(conf_dir)
    if not os.path.exists(cdir) or not os.path.isdir(cdir):
        config_log.debug(f"invalid config directory: {cdir!r}")
        return d
    # look for conf.d subdirectory:
    conf_d_dir = os.path.join(cdir, "conf.d")
    if os.path.exists(conf_d_dir) and os.path.isdir(conf_d_dir):
        for f in sorted(os.listdir(conf_d_dir)):
            if f.endswith(".conf"):
                conf_file = os.path.join(conf_d_dir, f)
                if os.path.isfile(conf_file):
                    d.append(conf_file)
    conf_file = os.path.join(cdir, xpra_conf_filename)
    if not os.path.exists(conf_file) or not os.path.isfile(conf_file):
        config_log.debug(f"config file does not exist: {conf_file!r}")
    else:
        d.append(conf_file)
    return d


def read_xpra_conf(conf_dir: str) -> dict[str, Any]:
    """
        Reads all config files from the directory,
        returns a dict with key as strings,
        values as strings or arrays of strings.
    """
    cdir = os.path.expanduser(conf_dir)
    if not os.path.exists(cdir) or not os.path.isdir(cdir):
        config_log.debug(f"invalid config directory: {cdir!r}")
        return {}
    import glob
    # `conf.d` files are sorted so that their numeric prefix defines the order
    # in which they are applied, ie: "90_configure_tool.conf" overrides "55_server_x11.conf"
    files = glob.glob(f"{cdir}/{DEFAULT_XPRA_CONF_FILENAME}") + sorted(glob.glob(f"{cdir}/conf.d/*.conf"))
    config_log.debug(f"read_xpra_conf({conf_dir}) found conf files: {files}")
    d = {}
    for f in files:
        cd = read_config(f)
        config_log.debug(f"config({f})={cd}")
        d.update(cd)
    return d


def read_xpra_defaults(username: str | None = None, uid=None, gid=None) -> dict[str, Any]:
    """
        Reads the global <xpra_conf_filename> from the <conf_dir>
        and then the user-specific one.
        (the latter overrides values from the former)
        returns a dict with values as strings and arrays of strings.
        If the <conf_dir> is not specified, we figure out its location.
    """
    dirs = get_xpra_defaults_dirs(username, uid, gid)
    defaults: dict[str, Any] = {}
    for d in dirs:
        conf_data = read_xpra_conf(d)
        defaults.update(conf_data)
        config_log.debug(f"read_xpra_defaults: updated defaults with {d!r} : {conf_data}")
    may_create_user_config()
    return defaults


def get_xpra_defaults_dirs(username: str | None = None, uid=None, gid=None) -> list[str]:
    from xpra.platform.paths import get_default_conf_dirs, get_system_conf_dirs, get_user_conf_dirs
    # load config files in this order (the later ones override earlier ones):
    # * application defaults, ie:
    #   "/Volumes/Xpra/Xpra.app/Contents/Resources/" on OSX
    #   "C:\Program Files\Xpra\" on win32
    #   None on others
    # * system defaults, ie:
    #   "/etc/xpra" on Posix - not on OSX
    #   "/Library/Application Support/Xpra" on OSX
    #   "C:\ProgramData\Xpra" with Vista onwards
    # * user config, ie:
    #   "~/.xpra/" on all Posix, including OSX
    #   "C:\Users\<user name>\AppData\Roaming" with Visa onwards
    dirs = get_default_conf_dirs() + get_system_conf_dirs() + get_user_conf_dirs(uid)
    defaults_dirs = []
    for d in dirs:
        if not d:
            continue
        ad = osexpand(d, actual_username=username, uid=uid, gid=gid)
        if not os.path.exists(ad):
            config_log.debug(f"get_xpra_defaults_dirs: skipped missing directory {ad!r}")
            continue
        defaults_dirs.append(ad)
    return defaults_dirs


def may_create_user_config(xpra_conf_filename: str = DEFAULT_XPRA_CONF_FILENAME) -> None:
    from xpra.platform.paths import get_user_conf_dirs
    # save a user config template:
    udirs = get_user_conf_dirs()
    if any(os.path.exists(osexpand(d)) for d in udirs):
        return
    config_log.debug("no user configuration file found, trying to create one")
    for d in udirs:
        ad = os.path.expanduser(d)
        conf_file = os.path.join(ad, xpra_conf_filename)
        try:
            if not os.path.exists(ad):
                os.makedirs(ad, int('700', 8))
            with open(conf_file, 'w', encoding="utf8") as f:
                f.write("""# xpra user configuration file
# place your custom settings in this file
# they will take precedence over the system default ones.

# Examples:
# speaker=off
# dpi=144

# For more information on the file format,
# see the xpra manual at:
# https://xpra-org.github.io/xpra/
""")
                f.flush()
            config_log.debug(f"created default config in {d!r}")
            return
        except Exception as e:
            config_log.debug(f"failed to create default config in {conf_file!r}: {e}")
