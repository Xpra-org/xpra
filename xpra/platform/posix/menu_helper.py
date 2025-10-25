#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Utility functions for loading xdg menus
using python-xdg
"""

import os
import sys
import glob
from time import monotonic
from contextlib import nullcontext
from threading import RLock
from typing import Any
from collections.abc import Generator, Sequence

from xpra.util.env import envbool, OSEnvContext, first_time, IgnoreWarningsContext, get_saved_env
from xpra.codecs import icon_util
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("menu")

ENABLED: bool = envbool("XPRA_XDG", True)

LOAD_FROM_RESOURCES: bool = envbool("XPRA_XDG_LOAD_FROM_RESOURCES", ENABLED)
LOAD_FROM_PIXMAPS: bool = envbool("XPRA_XDG_LOAD_FROM_PIXMAPS", ENABLED)
LOAD_FROM_THEME: bool = envbool("XPRA_XDG_LOAD_FROM_THEME", ENABLED)
LOAD_GLOB: bool = envbool("XPRA_XDG_LOAD_GLOB", False)
LOAD_FROM_MENU: bool = envbool("XPRA_XDG_LOAD_FROM_MENU", True)

EXPORT_ICONS: bool = envbool("XPRA_XDG_EXPORT_ICONS", True)
DEBUG_COMMANDS: list[str] = os.environ.get("XPRA_XDG_DEBUG_COMMANDS", "").split(",")
EXPORT_TERMINAL_APPLICATIONS: bool = envbool("XPRA_XDG_EXPORT_TERMINAL_APPLICATIONS", False)
EXPORT_SELF: bool = envbool("XPRA_XDG_EXPORT_SELF", False)
LOAD_APPLICATIONS: list[str] = os.environ.get(
    "XPRA_MENU_LOAD_APPLICATIONS",
    f"{sys.prefix}/share/applications"
).split(":")

log("menu helper settings:")
log(f" {LOAD_FROM_RESOURCES=}")
log(f" {LOAD_FROM_PIXMAPS=}")
log(f" {LOAD_FROM_THEME=}")
log(f" {LOAD_GLOB=}")
log(f" {EXPORT_ICONS=}")
log(f" {DEBUG_COMMANDS=}")
log(f" {EXPORT_TERMINAL_APPLICATIONS=}")
log(f" {EXPORT_SELF=}")
log(f" {LOAD_APPLICATIONS=}")


load_lock = RLock()


def isvalidtype(v) -> bool:
    if isinstance(v, (list, tuple, Generator)):
        if not v:
            return True
        return all(isvalidtype(x) for x in v)
    return isinstance(v, (bytes, str, bool, int))


def export(entry, properties: Sequence[str]) -> dict[str, Any]:
    name = entry.getName()
    props: dict[str, Any] = {}
    if any(x and name.lower().find(x.lower()) >= 0 for x in DEBUG_COMMANDS):
        log_fn = log.info
    else:
        log_fn = log.debug
    for prop in properties:
        fn_name = f"get{prop}"
        try:
            fn = getattr(entry, fn_name, None)
            if fn:
                v = fn()
                if isinstance(v, (list, tuple, Generator)):
                    log_fn(f"{prop}={v} (%s)", type(x for x in v))
                else:
                    log_fn(f"{prop}={v} ({type(v)})")
                if not isvalidtype(v):
                    log.warn(f"Warning: found invalid type for {v}: {type(v)}")
                else:
                    props[prop] = v
        except Exception as e:
            log_fn("error on %s", entry, exc_info=True)
            log.error(f"Error parsing {prop!r}: {e}")
    log_fn(f"properties({name})={props}")
    load_entry_icon(props)
    return props


MAX_THEMES: int = 8
IconTheme: type | None = None
Config: type | None = None
themes: dict[str, Any] = {}
IconLoadingContext: type = nullcontext
if LOAD_FROM_THEME:
    try:
        # noinspection PyPep8Naming
        from xdg import IconTheme as IT, Config as C

        IconTheme = IT
        Config = C
    except (ImportError, AttributeError):
        log("python xdg is missing", exc_info=True)
    else:
        class KeepCacheLoadingContext:
            __slots__ = ("cache_time",)

            def __enter__(self):
                self.cache_time: int = Config.cache_time
                Config.cache_time = 9999

            def __exit__(self, *_args):
                if self.cache_time != 9999:
                    Config.cache_time = self.cache_time

            def __repr__(self):
                return "KeepCacheLoadingContext"

        IconLoadingContext = KeepCacheLoadingContext

        def init_themes() -> None:
            get_themes = getattr(IconTheme, "__get_themes", None)
            if not callable(get_themes):
                return
            global themes
            themes = {}

            def addtheme(name: str) -> None:
                if not name or name in themes or len(themes) >= MAX_THEMES:
                    return
                for theme in get_themes(name):  # pylint: disable=not-callable
                    if theme and theme.name not in themes:
                        themes[theme.name] = theme

            addtheme(Config.icon_theme)
            addtheme(get_saved_env().get("XDG_MENU_PREFIX", ""))
            addtheme(get_saved_env().get("XDG_SESSION_DESKTOP", ""))
            if len(themes) < MAX_THEMES:
                for x in glob.glob(f"{sys.prefix}/share/icons/*/index.theme"):
                    parts = x.split(os.path.sep)
                    addtheme(parts[-2])
                    if len(themes) > MAX_THEMES:
                        break
            log(f"icon themes={themes}")

        init_themes()

EXTENSIONS: Sequence[str] = ("png", "svg", "xpm")


def check_xdg() -> bool:
    if not ENABLED:
        return False
    try:
        # pylint: disable=import-outside-toplevel
        from xdg.Menu import Menu, MenuEntry
        assert Menu and MenuEntry
        return True
    except ImportError as e:
        if first_time("load-xdg"):
            log.warn("Warning: cannot load menu data")
            log.warn(f" {e}")
        return False


def clear_cache() -> None:
    log(f"clear_cache() IconTheme={IconTheme}")
    if not IconTheme:
        return
    IconTheme.themes = []
    IconTheme.theme_cache = {}
    IconTheme.dir_cache = {}
    IconTheme.icon_cache = {}


def load_entry_icon(props: dict):
    names = []
    for x in ("Icon", "Name", "GenericName"):
        name = props.get(x)
        if name and name not in names:
            names.append(name)
    for x in ("Exec", "TryExec"):
        cmd = props.get(x, "")
        if cmd and not cmd.endswith(os.path.sep):
            cmd = os.path.basename(cmd).split(" ")[0]
            if cmd not in names:
                names.append(cmd)
    filename = _find_icon(*names)
    icondata = None
    if filename:
        icondata = icon_util.load_icon_from_file(filename)
        if icondata:
            bdata, ext = icondata
            props["IconData"] = bdata
            props["IconType"] = ext
            props["IconFile"] = filename
    if not icondata:
        log(f"no icon found for {names} from {props}")
    return props


def _find_icon(*names: str) -> str:
    if not EXPORT_ICONS:
        return ""
    return find_resources_icon(*names) or \
        find_pixmap_icon(*names) or \
        find_theme_icon(*names) or \
        find_glob_icon(*names, category="apps")


def find_icon(*names: str) -> str:
    """ this function must not be called when loading the menus """
    return _find_icon(*names) or find_menu_icon(*names)


def find_resources_icon(*names: str) -> str:
    if not LOAD_FROM_RESOURCES:
        return ""
    # loads the icon from our own list of icons:
    for name in names:
        fn = get_icon_filename(name)
        if fn and os.path.exists(fn):
            return fn
    return ""


def find_pixmap_icon(*names: str) -> str:
    if not LOAD_FROM_PIXMAPS:
        return ""
    pixmaps_dirs = [d + '/icons' for d in os.environ.get("XDG_DATA_DIRS", "").split(":") if d]
    pixmaps_dir = f"{sys.prefix}/share/pixmaps"
    icons_dir = f"{sys.prefix}/share/icons"
    pixmaps_dirs += [pixmaps_dir, os.path.join(pixmaps_dir, "comps"), icons_dir]
    for d in pixmaps_dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            continue
        for name in names:
            for ext in EXTENSIONS:
                fn = os.path.join(d, f"{name}.{ext}")
                if fn and os.path.exists(fn):
                    return fn
    return ""


ic_lock = RLock()


def find_theme_icon(*names: str) -> str:
    if not LOAD_FROM_THEME:
        return ""
    if not (IconTheme and Config and themes):
        return ""
    size = Config.icon_size or 32
    for name in names:
        for theme in themes.values():
            with ic_lock:
                try:
                    fn = IconTheme.LookupIcon(name, size, theme=theme, extensions=EXTENSIONS)
                    if fn and os.path.exists(fn):
                        return fn
                except TypeError as e:
                    log(f"find_theme_icon({names}) error on {name=}, {size=}", exc_info=True)
                    if first_time("xdg-icon-lookup"):
                        log.warn(f"Warning: icon loop failure for {name} in {theme}")
                        log.warn(f" {e}")
                        log.warn(" this is likely to be this bug in pyxdg:")
                        log.warn(" https://github.com/takluyver/pyxdg/pull/20")
    return ""


def add_entry_icon(entry_props: dict[str, Any], category: str):
    """ adds 'IconData' and 'IconType' to `entry_props` if we find a matching icon """
    if not entry_props:
        return
    names = []
    for prop in ("Name", "GenericName", "Exec", "TryExec"):
        value = entry_props.get(prop, "")
        if value:
            names.append(str(value))
    eicon = find_glob_icon(*names, category)
    if not eicon:
        return
    bdata, ext = eicon
    entry_props["IconData"] = bdata
    entry_props["IconType"] = ext


def find_glob_icon(*names: str, category: str = "categories") -> str:
    if not LOAD_GLOB:
        return ""
    icondirs = getattr(IconTheme, "icondirs", [])
    if not icondirs:
        return ""
    dirnames = (category,)
    pathnames = []
    for name in names:
        for dn in dirnames:
            for d in icondirs:
                for ext in EXTENSIONS:
                    pathnames += [
                        os.path.join(d, "*", "*", dn, f"{name}.{ext}"),
                        os.path.join(d, "*", dn, "*", f"{name}.{ext}"),
                    ]
    for pathname in pathnames:
        filenames = glob.glob(pathname)
        log("glob(%s) matches %i filenames", pathname, len(filenames))
        if filenames:
            for f in filenames:
                v = icon_util.load_icon_from_file(f)
                if v:
                    log(f"found icon for {names} with glob {pathname!r}: {f}")
                    return f
    return ""


def find_menu_icon(*names: str) -> str:
    """
    find a menu entry matching the name,
    then search using the icon name from this menu entry
    """
    if not LOAD_FROM_MENU or not menu_cache:
        return ""
    for category, cdata in menu_cache.items():
        entries = cdata.get("Entries", ())
        for name, edata in entries.items():
            cmd = os.path.basename(edata.get("Exec", "")).split(" ")[0]
            filename = edata.get("IconFile", "")
            if not filename:
                continue
            if (name and name in names) or (cmd and cmd in names):
                return filename
    return ""


def noicondata(d: dict) -> dict:
    return {k: v for k, v in d.items() if k and v and k != "IconData"}


def load_xdg_entry(de) -> dict[str, Any]:
    # not exposed:
    # * `MimeType` is a `re`
    # * `Version` is a `float`
    props: dict[str, Any] = export(de, (
        "Type", "VersionString", "Name", "GenericName", "NoDisplay",
        "Comment", "Icon", "Hidden", "OnlyShowIn", "NotShowIn",
        "Exec", "TryExec", "Path", "Terminal", "MimeTypes",
        "Categories", "StartupNotify", "StartupWMClass", "URL",
    ))
    if props.get("NoDisplay", False) or props.get("Hidden", False):
        return {}
    if de.getTryExec():
        try:
            command = de.findTryExec()
        except (AttributeError, OSError):
            command = de.getTryExec()
    else:
        command = de.getExec()
    if not command:
        # this command is not executable!
        return {}
    props["command"] = command
    if not EXPORT_SELF and command and command.find("xpra") >= 0:
        return {}
    if not EXPORT_TERMINAL_APPLICATIONS and props.get("Terminal", False):
        return {}
    icondata = props.get("IconData")
    if not icondata:
        add_entry_icon(props, category="apps")
    return props


def load_xdg_menu(submenu) -> dict[str, Any]:
    submenu_data: dict[str, Any] = export(submenu, (
        "Name", "GenericName", "Comment",
        "Path", "Icon",
    ))
    icondata = submenu_data.get("IconData")
    if not icondata:
        add_entry_icon(submenu_data, category="categories")
    entries_data = submenu_data.setdefault("Entries", {})
    from xdg.Menu import Menu, MenuEntry  # pylint: disable=import-outside-toplevel

    def add_entries(entries) -> None:
        for i, entry in enumerate(entries):
            if isinstance(entry, MenuEntry):
                de = entry.DesktopEntry
                name = de.getName()
                log("  - %-3i %s", i, name)
                try:
                    ed = load_xdg_entry(de)
                    if name and ed:
                        entries_data[name] = ed
                except Exception as e:
                    log("load_xdg_menu(%s)", submenu, exc_info=True)
                    log.error(f"Error loading desktop menu entry {name!r}:")
                    log.error(f" {type(e)}: {e}")
            elif isinstance(entry, Menu):
                # merge up:
                add_entries(entry.Entries)

    add_entries(submenu.getEntries())
    if not entries_data:
        return {}
    return submenu_data


def remove_icons(menu_data: dict) -> dict:
    filt = {}
    for category, cdef in menu_data.items():
        fcdef: dict[str, Any] = dict(cdef)
        entries = dict(fcdef.get("Entries", {}))
        for entry, edef in tuple(entries.items()):
            nd = noicondata(edef)
            if entry and nd:
                entries[entry] = nd
        fcdef["Entries"] = entries
        filt[category] = fcdef
    return filt


menu_cache: dict[str, dict[str, Any]] = {}


def load_menu(force_reload=False) -> dict[str, dict[str, Any]]:
    global menu_cache
    if not check_xdg():
        return menu_cache
    if menu_cache and not force_reload:
        return menu_cache
    with load_lock:
        icon_util.large_icons.clear()
        start = monotonic()
        with IconLoadingContext():
            menu_cache = load_xdg_menu_data()
        end = monotonic()
        if menu_cache:
            count = sum(len(x) for x in menu_cache.values())
            submenus = len(menu_cache)
            elapsed = end - start
            log.info(f"loaded {count} start menu entries from {submenus} sub-menus in {elapsed:.1f} seconds")
        n_large = len(icon_util.large_icons)
        if n_large:
            log.warn(f"Warning: found {n_large} large icons:")
            for filename, size in icon_util.large_icons:
                log.warn(f" {filename!r} ({size // 1024} KB)")
            log.warn(" more bandwidth will be used by the start menu data")
    return menu_cache


def load_xdg_menu_data() -> dict:
    if not check_xdg():
        return {}
    menu = do_load_xdg_menu_data()
    if not menu:
        return {}
    entries = tuple(menu.getEntries())
    log(f"{menu}.getEntries()={entries}")
    if len(entries) == 1 and entries[0].Submenus:
        entries = entries[0].Submenus
        log(f"using submenus {entries}")
    menu_data = {}
    from xdg.Menu import Menu  # pylint: disable=import-outside-toplevel
    for i, submenu in enumerate(entries):
        if not isinstance(submenu, Menu):
            log(f"entry {submenu!r} is not a submenu")
            continue
        name = submenu.getName()
        log("* %-3i %s", i, name)
        if not submenu.Visible:
            log(f" submenu {name!r} is not visible")
            continue
        try:
            md = load_xdg_menu(submenu)
            if md:
                menu_data[name] = md
            else:
                log(" no menu data for %s", name)
        except Exception as e:
            log("load_xdg_menu_data()", exc_info=True)
            log.error("Error loading submenu '%s':", name)
            log.estr(e)
    entries = load_applications(menu_data)
    if entries:
        # add an 'Applications' menu if we don't have one:
        app_menu = menu_data.get("Applications")
        if app_menu:
            app_menu.setdefault("Entries", {}).update(entries)
        else:
            menu_data["Applications"] = {
                "Name": "Applications",
                "Entries": entries,
            }
    return menu_data


def do_load_xdg_menu_data():
    error = None
    from xdg.Menu import parse
    # see ticket #2340,
    # invalid values for XDG_CONFIG_DIRS can cause problems,
    # so try unsetting it if we can't load the menus with it:
    default_xdg = f"{sys.prefix}/etc/xdg".replace("/usr/etc", "/etc")
    xdg_home = os.environ.get("XDG_CONFIG_HOME", "")
    for cd in (False, True):
        with OSEnvContext():
            if cd is True and not os.environ.pop("XDG_CONFIG_DIRS", ""):
                # was already unset
                continue
            # see ticket #2174,
            # things may break if the prefix is not set,
            # and it isn't set when logging in via ssh,
            # so we have to guess!
            config_dirs = []
            # XDG_CONFIG_HOME takes precedence so add it first:
            if xdg_home:
                config_dirs.append(f"{xdg_home}/xdg")
            for d in os.environ.get("XDG_CONFIG_DIRS", default_xdg).split(":"):
                if d not in config_dirs:
                    config_dirs.append(d)
            prefixes = [None, ""]
            # we sanitize the environment,
            # but perhaps the value from the existing environment was useful:
            prefix = get_saved_env().get("XDG_MENU_PREFIX")
            if prefix:
                prefixes.append(prefix)
            desktop = os.environ.get("XDG_SESSION_DESKTOP", "")
            if desktop:
                prefixes.append(f"{desktop}-")  # ie: "gnome-"
            for d in config_dirs:
                for path in glob.glob(f"{d}/menus/*applications.menu"):
                    filename = os.path.basename(path)  # ie: "gnome-applications.menu"
                    prefix = filename[:-len("applications.menu")]  # ie: "gnome-"
                    if prefix not in prefixes:
                        prefixes.append(prefix)
            log(f"load_xdg_menu_data() will try prefixes {prefixes} from config directories {config_dirs}")
            for prefix in prefixes:
                if prefix is not None:
                    os.environ["XDG_MENU_PREFIX"] = prefix
                try:
                    log("parsing xdg menu data for prefix %r with XDG_CONFIG_DIRS=%s and XDG_MENU_PREFIX=%s",
                        prefix, os.environ.get("XDG_CONFIG_DIRS"), os.environ.get("XDG_MENU_PREFIX"))
                    with IgnoreWarningsContext():
                        return parse()
                except Exception as e:
                    log("load_xdg_menu_data()", exc_info=True)
                    error = e
    assert error
    if not os.path.exists("/etc/xdg/menus"):
        log.warn("Warning: failed to parse menu data")
        log.warn(" '/etc/xdg/menus' is missing")
    elif first_time("xdg-menu-error"):
        log.error("Error parsing xdg menu data:")
        log.estr(error)
        log.error(" this is either a bug in python-xdg,")
        log.error(" or an invalid system menu configuration")
        log.error(" for more information, please see:")
        log.error(" https://github.com/Xpra-org/xpra/issues/2174")
    return {}


def load_applications(menu_data=None):
    entries: dict[str, Any] = {}
    if not LOAD_APPLICATIONS or not check_xdg():
        return entries

    def already_has_name(name: str) -> bool:
        if not menu_data or not name:
            return False
        for menu_category in menu_data.values():
            if name in menu_category.get("Entries", {}):
                return True
        return False

    from xdg.Menu import MenuEntry  # pylint: disable=import-outside-toplevel
    from xdg.Exceptions import ParsingError
    for d in LOAD_APPLICATIONS:
        if not os.path.exists(d):
            continue
        for f in os.listdir(d):
            if not f.endswith(".desktop"):
                continue
            try:
                me = MenuEntry(f, d)
            except ParsingError:
                log(f"failed to load {f!r} from {d!r}", f, d, exc_info=True)
            else:
                ed = load_xdg_entry(me.DesktopEntry)
                if not ed:
                    continue
                app_name = ed.get("Name", "")
                if app_name and not already_has_name(app_name):
                    entries[app_name] = ed
    log("entries(%s)=%s", LOAD_APPLICATIONS, remove_icons(entries))
    return entries


def load_desktop_sessions() -> dict[str, Any]:
    xsessions: dict[str, Any] = {}
    if not check_xdg():
        return xsessions
    xsessions_dir = f"{sys.prefix}/share/xsessions"
    if not os.path.exists(xsessions_dir) or not os.path.isdir(xsessions_dir):
        return xsessions
    with IconLoadingContext():
        from xdg.DesktopEntry import DesktopEntry  # pylint: disable=import-outside-toplevel
        for f in os.listdir(xsessions_dir):
            filename = os.path.join(xsessions_dir, f)
            de = DesktopEntry(filename)
            try:
                entry = load_xdg_entry(de)
                if not entry:
                    continue
                name = de.getName()
                if not entry.get("IconData"):
                    names = get_icon_names_for_session(name.lower())
                    icon_filename = _find_icon(*names)
                    if icon_filename:
                        icondata = icon_util.load_icon_from_file(icon_filename)
                        if icondata:
                            entry["IconData"] = icondata[0]
                            entry["IconType"] = icondata[1]
                            entry["IconFile"] = icon_filename
                xsessions[name] = entry
            except Exception as e:
                log("load_desktop_sessions(%s)", remove_icons, exc_info=True)
                log.error(f"Error loading desktop session entry {filename!r}:")
                log.error(f" {type(e)}: {e}")
    return xsessions


def get_icon_names_for_session(name: str) -> list[str]:
    aliases = {
        "deepin": ["deepin-launcher", "deepin-show-desktop"],
        "xfce": ["org.xfce.xfdesktop", ]
    }
    names = [name] + aliases.get(name, [])
    for split in (" on ", " session", "-session", " classic"):
        if name.find(split) > 0:  # ie: "gnome on xorg"
            short_name = name.split(split)[0]
            names += [
                short_name,
                f"{short_name}-session",
                f"{short_name}-desktop",
            ] + aliases.get(short_name, [])  # -> "gnome"
    return names
