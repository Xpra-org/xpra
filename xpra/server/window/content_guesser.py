# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os.path
from typing import Any, TypeAlias
from collections.abc import Callable, Iterable, Sequence

from xpra.util.str_fn import Ellipsizer
from xpra.util.env import envbool
from xpra.os_util import getuid, OSX, POSIX
from xpra.util.io import get_proc_cmdline
from xpra.platform.paths import get_user_conf_dirs, get_system_conf_dirs
from xpra.log import Logger

log = Logger("window", "util")

GUESS_CONTENT = envbool("XPRA_GUESS_CONTENT", True)
DEFAULT_CONTENT_TYPE = os.environ.get("XPRA_DEFAULT_CONTENT_TYPE", "")
CONTENT_TYPE_DEFS = os.environ.get("XPRA_CONTENT_TYPE_DEFS", "")

ConfDict: TypeAlias = dict[str, Any]
ConfParser: TypeAlias = Callable[[Sequence[str]], ConfDict]


def getprop(window, prop: str):
    with log.trap_error("Error querying %r on %r", prop, window):
        if prop not in window.get_property_names():
            log("no '%s' property on window %s", prop, window)
            return None
        return window.get_property(prop)


################################################################
# generic file parsing functions
################################################################


def _load_dict_file(filename: str, parser: ConfParser) -> ConfDict:
    # filter out comments and remove line endings
    lines = []
    with open(filename, encoding="utf8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if line.startswith("#") or not line.strip():
                continue
            lines.append(line)
    log("_load_dict_file(%s)=%s", filename, Ellipsizer(lines))
    return parser(lines)


def _load_dict_dir(d: str, parser: ConfParser) -> ConfDict:
    # load all the .conf files from the directory
    if not os.path.exists(d) or not os.path.isdir(d):
        log("load_content_categories_dir(%s) directory not found", d)
        return {}
    v = {}
    for f in sorted(os.listdir(d)):
        if f.endswith(".conf"):
            cc_file = os.path.join(d, f)
            if os.path.isfile(cc_file):
                try:
                    v.update(_load_dict_file(cc_file, parser))
                except Exception as e:
                    log("_load_dict_dir(%s)", cc_file, exc_info=True)
                    log.error("Error loading file data from '%s'", cc_file)
                    log.estr(e)
    log("_load_dict_dir(%s)=%s", d, v)
    return v


def _load_dict_dirs(dirname: str, parser: ConfParser) -> ConfDict:
    if not GUESS_CONTENT:
        return {}
    # finds all the ".conf" files from the dirname specified
    # and calls `load` on them.
    # looks for system and user conf dirs
    values = {}
    for d in get_system_conf_dirs():
        v = _load_dict_dir(os.path.join(d, dirname), parser)
        values.update(v)
    if not POSIX or getuid() > 0:
        for d in get_user_conf_dirs():
            v = _load_dict_dir(os.path.join(d, dirname), parser)
            values.update(v)
    return values


################################################################
# `content-type` mapping:
################################################################

content_type_defs: ConfDict | None = None


def load_content_type_defs() -> ConfDict:
    global content_type_defs
    if content_type_defs is None:
        content_type_defs = _load_dict_dirs("content-type", parse_content_types)
        if GUESS_CONTENT:
            # add env defs:
            content_type_defs.update(parse_content_types(CONTENT_TYPE_DEFS.split(",")))
    return content_type_defs


def parse_content_types(lines) -> dict[str, dict[Any, tuple[str, str]]]:
    defs: dict[str, dict[Any, tuple[str, str]]] = {}
    for line in lines:
        if not line:
            continue
        parts = line.rsplit("=", 1)
        # ie: "title:helloworld=text   #some comments here" -> "title:helloworld", "text   #some comments here"
        if len(parts) != 2:
            log.warn("Warning: invalid content-type definition")
            log.warn(f" {line!r} is missing a '='")
            continue
        match_str, content_type = parts
        parts = match_str.split(":", 1)
        # ie: "title:helloworld" -> "title", "helloworld"
        if len(parts) != 2:
            log.warn("Warning: invalid content-type definition")
            log.warn(f" match string {match_str!r} is missing a ':'")
            continue
        # ignore comments:
        # "text    #some comments here" > "text"
        content_type = content_type.split(":")[0].strip()
        prop_name, regex = parts
        try:
            c = re.compile(regex)
        except Exception as e:
            log.warn("Warning: invalid regular expression")
            log.warn(f" match string {regex!r}:")
            log.warn(f" {e}")
            continue
        else:
            defs.setdefault(prop_name, {})[c] = (regex, content_type)
            log("%16s matching '%s' is %s", prop_name, regex, content_type)
    return defs


def get_content_type_properties() -> Iterable[str]:
    """ returns the list of window properties which can be used
        to guess the content-type.
    """
    return load_content_type_defs().keys()


def guess_content_type_from_defs(window) -> str:
    load_content_type_defs()
    assert content_type_defs is not None
    for prop_name, defs in content_type_defs.items():
        if prop_name not in window.get_property_names():
            continue
        prop_value = window.get_property(prop_name)
        # some properties return lists of values,
        # in which case we try to match any of them:
        log("guess_content_type_from_defs(%s) prop(%s)=%s", window, prop_name, prop_value)
        if isinstance(prop_value, (list, tuple)):
            values = prop_value
        else:
            values = [prop_value]
        for value in values:
            for regex, match_data in defs.items():
                if regex.search(str(value)):
                    regex_str, content_type = match_data
                    log("guess_content_type(%s) found match: property=%s, regex=%s, content-type=%s",
                        window, prop_name, regex_str, content_type)
                    return content_type
    return ""


################################################################
# `content-categories` mapping:
################################################################


def parse_content_categories_file(lines) -> ConfDict:
    d: dict[str, str] = {}
    for line in lines:
        parts = line.rsplit(":", 1)
        # ie: "title:helloworld=text   #some comments here" -> "title:helloworld", "text   #some comments here"
        if len(parts) != 2:
            log.warn("Warning: invalid content-type definition")
            log.warn(" %r is missing a '='", line)
            continue
        category, content_type = parts
        d[category.strip("\t ").lower()] = content_type.strip("\t ")
    log("parse_content_categories_file(%s)=%s", lines, d)
    return d


def load_categories_to_type() -> ConfDict:
    return _load_dict_dirs("content-categories", parse_content_categories_file)


################################################################
# command mapping: using menu data
################################################################

command_to_type: dict[str, str] | None = None


def load_command_to_type() -> dict[str, str]:
    if not GUESS_CONTENT:
        return {}
    global command_to_type
    if command_to_type is not None:
        return command_to_type
    command_to_type = {}
    from xpra.server.menu_provider import get_menu_provider
    xdg_menu = get_menu_provider().get_menu_data(remove_icons=True)
    categories_to_type = load_categories_to_type()
    log("load_command_to_type() xdg_menu=%s, categories_to_type=%s", xdg_menu, categories_to_type)
    if xdg_menu and categories_to_type:
        for category, category_props in xdg_menu.items():
            log("category %s: %s", category, Ellipsizer(category_props))
            entries = category_props.get("Entries", {})
            for name, props in entries.items():
                command = str(props.get("TryExec") or props.get("Exec") or "")
                categories = props.get("Categories")
                log("Entry '%s': command=%s, categories=%s", name, command, categories)
                if command and categories:
                    for c in categories:
                        ctype = categories_to_type.get(c.lower())
                        if not ctype:
                            # try a more fuzzy match:
                            for category_name, ct in categories_to_type.items():
                                if c.lower().find(category_name) >= 0:
                                    ctype = ct
                                    break
                        if ctype:
                            cmd = os.path.basename(command.split(" ")[0])
                            if cmd:
                                command_to_type[cmd] = str(ctype)
                                break
    log("load_command_to_type()=%s", command_to_type)
    return command_to_type


def guess_content_type_from_command(window) -> str:
    if POSIX and not OSX:
        command = getprop(window, "command") or ""
        log(f"guess_content_type_from_command({window}) command={command}")
        if command:
            ctt = load_command_to_type()
            commands = [command]
            for x in command.split("\0"):
                if x and x not in commands:
                    commands.append(x)
            for x in command.split(" "):
                if x and x not in commands:
                    commands.append(x)
            for x in commands:
                cmd = os.path.basename(x)
                ctype = ctt.get(cmd)
                log("content-type(%s)=%s", cmd, ctype)
                if ctype:
                    return ctype
    return ""


################################################################
# `content-parent` mapping:
################################################################

def parse_content_parent(lines) -> dict[str, str]:
    v = {}
    for line in lines:
        parts = line.split(":", 1)
        if len(parts) == 2:
            v[parts[0].strip()] = parts[1].strip()
    return v


parent_to_type = None


def get_parent_to_type() -> dict[str, Any]:
    global parent_to_type
    if parent_to_type is None:
        parent_to_type = _load_dict_dirs("content-parent", parse_content_parent)
    return parent_to_type


def guess_content_type_from_parent(window) -> str:
    ppid = getprop(window, "ppid")
    if not ppid:
        return ""
    return guess_content_from_parent_pid(ppid)


def guess_content_from_parent_pid(ppid: int) -> str:
    parent_command = get_proc_cmdline(ppid)
    if not parent_command:
        return ""
    executable = os.path.basename(parent_command[0])
    pt = get_parent_to_type()
    return pt.get(executable, "")


def guess_content_type(window) -> str:
    if not GUESS_CONTENT:
        return DEFAULT_CONTENT_TYPE
    return guess_content_type_from_defs(window) or \
        guess_content_type_from_command(window) or \
        guess_content_type_from_parent(window) or \
        DEFAULT_CONTENT_TYPE


def main():
    # pylint: disable=import-outside-toplevel
    import sys
    args = sys.argv[1:]
    while "-v" in args:
        args.remove("-v")
        log.enable_debug()
    if not args:
        print("usage: %s pids" % sys.argv[0])
        return
    for ppid in args:
        c = guess_content_from_parent_pid(int(ppid))
        print(f"guess_content_from_parent_pid({ppid})={c}")


if __name__ == "__main__":  # pragma: no cover
    main()
