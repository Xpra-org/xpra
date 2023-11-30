#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
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
from typing import Type, Tuple, List, Dict, Any, Optional, Generator as generator       #@UnresolvedImport, @UnusedImport

from xpra.util import envbool, first_time
from xpra.os_util import DummyContextManager, OSEnvContext, get_saved_env
from xpra.codecs import icon_util
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("exec", "menu")

LOAD_FROM_RESOURCES : bool = envbool("XPRA_XDG_LOAD_FROM_RESOURCES", True)
LOAD_FROM_PIXMAPS : bool = envbool("XPRA_XDG_LOAD_FROM_PIXMAPS", True)
LOAD_FROM_THEME : bool = envbool("XPRA_XDG_LOAD_FROM_THEME", True)
LOAD_GLOB : bool = envbool("XPRA_XDG_LOAD_GLOB", False)

EXPORT_ICONS : bool = envbool("XPRA_XDG_EXPORT_ICONS", True)
DEBUG_COMMANDS : List[str] = os.environ.get("XPRA_XDG_DEBUG_COMMANDS", "").split(",")
EXPORT_TERMINAL_APPLICATIONS : bool = envbool("XPRA_XDG_EXPORT_TERMINAL_APPLICATIONS", False)
EXPORT_SELF : bool = envbool("XPRA_XDG_EXPORT_SELF", False)
LOAD_APPLICATIONS : List[str] = os.environ.get("XPRA_MENU_LOAD_APPLICATIONS", f"{sys.prefix}/share/applications").split(":")


def isvalidtype(v) -> bool:
    if isinstance(v, (list, tuple, generator)):
        if not v:
            return True
        return all(isvalidtype(x) for x in v)
    return isinstance(v, (bytes, str, bool, int))

def export(entry, properties : Tuple[str, ...]) -> Dict[str,Any]:
    name = entry.getName()
    props : Dict[str,Any] = {}
    if any(x and name.lower().find(x.lower())>=0 for x in DEBUG_COMMANDS):
        l = log.info
    else:
        l = log
    for prop in properties:
        fn_name = f"get{prop}"
        try:
            fn = getattr(entry, fn_name, None)
            if fn:
                v = fn()
                if isinstance(v, (list, tuple, generator)):
                    l(f"{prop}={v} (%s)", type(x for x in v))
                else:
                    l(f"{prop}={v} ({type(v)})")
                if not isvalidtype(v):
                    log.warn(f"Warning: found invalid type for {v}: {type(v)}")
                else:
                    props[prop] = v
        except Exception as e:
            l("error on %s", entry, exc_info=True)
            log.error(f"Error parsing {prop!r}: {e}")
    l(f"properties({name})={props}")
    load_entry_icon(props)
    return props


MAX_THEMES : int = 8
IconTheme : Optional[Type] = None
Config : Optional[Type] = None
themes : Dict[str,Any] = {}
IconLoadingContext : Type = DummyContextManager
if LOAD_FROM_THEME:
    try:
        from xdg import IconTheme as IT, Config as C
        IconTheme = IT
        Config = C
    except (ImportError, AttributeError):
        log("python xdg is missing", exc_info=True)
    else:
        class KeepCacheLoadingContext():
            __slots__ = ("cache_time", )
            def __enter__(self):
                self.cache_time : int = Config.cache_time
                Config.cache_time = 9999
            def __exit__(self, *_args):
                if self.cache_time!=9999:
                    Config.cache_time = self.cache_time
            def __repr__(self):
                return "KeepCacheLoadingContext"
        IconLoadingContext = KeepCacheLoadingContext
        def init_themes():
            get_themes = getattr(IconTheme, "__get_themes", None)
            if not callable(get_themes):
                return
            global themes
            themes = {}
            def addtheme(name):
                if not name or name in themes or len(themes)>=MAX_THEMES:
                    return
                for theme in get_themes(name):  #pylint: disable=not-callable
                    if theme and theme.name not in themes:
                        themes[theme.name] = theme
            addtheme(Config.icon_theme)
            addtheme(get_saved_env().get("XDG_MENU_PREFIX"))
            addtheme(get_saved_env().get("XDG_SESSION_DESKTOP"))
            if len(themes)<MAX_THEMES:
                for x in glob.glob(f"{sys.prefix}/share/icons/*/index.theme"):
                    parts = x.split(os.path.sep)
                    name = parts[-2]
                    addtheme(name)
                    if len(themes)>MAX_THEMES:
                        break
            log(f"icon themes={themes}")
        init_themes()

EXTENSIONS : Tuple[str, ...] = ("png", "svg", "xpm")


def check_xdg() -> bool:
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


def load_entry_icon(props:Dict):
    #load icon binary data
    names = []
    for x in ("Icon", "Name", "GenericName"):
        name = props.get(x)
        if name and name not in names:
            names.append(name)
    for x in ("Exec", "TryExec"):
        cmd = props.get(x)
        if cmd and not cmd.endswith(os.path.sep):
            cmd = os.path.basename(cmd)
            if cmd not in names:
                names.append(cmd)
    filename = find_icon(*names)
    icondata = None
    if filename:
        icondata = icon_util.load_icon_from_file(filename)
        if icondata:
            bdata, ext = icondata
            props["IconData"] = bdata
            props["IconType"] = ext
    if not icondata:
        log(f"no icon found for {names} from {props}")
    return props


def find_icon(*names):
    if not EXPORT_ICONS:
        return None
    return find_resources_icon(*names) or \
        find_pixmap_icon(*names) or \
        find_theme_icon(*names) or \
        find_glob_icon("apps", *names)

def find_resources_icon(*names):
    if not LOAD_FROM_RESOURCES:
        return None
    #loads the icon from our own list of icons:
    for name in names:
        fn = get_icon_filename(name)
        if fn and os.path.exists(fn):
            return fn
    return None

def find_pixmap_icon(*names):
    if not LOAD_FROM_PIXMAPS:
        return None
    pixmaps_dirs = [d + '/icons' for d in os.environ.get("XDG_DATA_DIRS", "").split(":") if d]
    pixmaps_dir = f"{sys.prefix}/share/pixmaps"
    pixmaps_dirs += [pixmaps_dir, os.path.join(pixmaps_dir, "comps")]
    for d in pixmaps_dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            continue
        for name in names:
            for ext in EXTENSIONS:
                fn = os.path.join(d, f"{name}.{ext}")
                if fn and os.path.exists(fn):
                    return fn
    return None

def find_theme_icon(*names):
    if not LOAD_FROM_THEME:
        return None
    if not (IconTheme and Config and themes):
        return None
    size = Config.icon_size or 32
    #log.info("IconTheme.LookupIcon%s", (icon_name, size, themes.keys(), ("png", "svg", "xpm")))
    for name in names:
        for theme in themes.values():
            fn = IconTheme.LookupIcon(name, size, theme=theme, extensions=EXTENSIONS)
            if fn and os.path.exists(fn):
                return fn
    return None

def find_glob_icon(*names, category:str="categories"):
    if not LOAD_GLOB:
        return None
    icondirs = getattr(IconTheme, "icondirs", [])
    if not icondirs:
        return None
    dirnames = (category, )
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
                    return v
    return None


def noicondata(d:Dict) -> Dict:
    return dict((k,v) for k,v in d.items() if k and v and k!="IconData")


def load_xdg_entry(de) -> Dict[str,Any]:
    # not exposed:
    # * `MimeType` is a `re`
    # * `Version` is a `float`
    props : Dict[str,Any] = export(de, (
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
        except Exception:
            command = de.getTryExec()
    else:
        command = de.getExec()
    if not command:
        #this command is not executable!
        return {}
    props["command"] = command
    if not EXPORT_SELF and command and command.find("xpra")>=0:
        return {}
    if not EXPORT_TERMINAL_APPLICATIONS and props.get("Terminal", False):
        return {}
    icondata = props.get("IconData")
    if not icondata:
        #try harder:
        icondata = find_glob_icon(de, category="apps")
        if icondata:
            bdata, ext = icondata
            props["IconData"] = bdata
            props["IconType"] = ext
    return props

def load_xdg_menu(submenu) -> Dict[str,Any]:
    #log.info("submenu %s: %s, %s", name, submenu, dir(submenu))
    submenu_data : Dict[str,Any] = export(submenu, (
        "Name", "GenericName", "Comment",
        "Path", "Icon",
        ))
    icondata = submenu_data.get("IconData")
    if not icondata:
        #try harder:
        icondata = find_glob_icon(submenu_data, category="categories")
        if icondata:
            bdata, ext = icondata
            submenu_data["IconData"] = bdata
            submenu_data["IconType"] = ext
    entries_data = submenu_data.setdefault("Entries", {})
    from xdg.Menu import Menu, MenuEntry  # pylint: disable=import-outside-toplevel
    def add_entries(entries):
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
                    log.error(f"Error loading desktop entry {name!r}:")
                    log.estr(e)
            elif isinstance(entry, Menu):
                #merge up:
                add_entries(entry.Entries)
    add_entries(submenu.getEntries())
    if not entries_data:
        return {}
    return submenu_data

def remove_icons(menu_data):
    filt = {}
    for category, cdef in menu_data.items():
        fcdef = dict(cdef)
        entries = dict(fcdef.get("Entries", {}))
        for entry, edef in tuple(entries.items()):
            nd = noicondata(edef)
            if entry and nd:
                entries[entry] = nd
        fcdef["Entries"] = entries
        filt[category] = fcdef
    return filt

def load_menu():
    if not check_xdg():
        return {}
    icon_util.large_icons.clear()
    start = monotonic()
    with IconLoadingContext():
        xdg_menu_data = load_xdg_menu_data()
    end = monotonic()
    if xdg_menu_data:
        l = sum(len(x) for x in xdg_menu_data.values())
        submenus = len(xdg_menu_data)
        elapsed = end-start
        log.info(f"loaded {l} start menu entries from "+
                 f"{submenus} sub-menus in {elapsed:.1f} seconds")
    n_large = len(icon_util.large_icons)
    if n_large:
        log.warn(f"Warning: found {n_large} large icons:")
        for filename, size in icon_util.large_icons:
            log.warn(f" {filename!r} ({size//1024} KB)")
        log.warn(" more bandwidth will be used by the start menu data")
    return xdg_menu_data

def load_xdg_menu_data():
    try:
        from xdg.Menu import parse, Menu  #pylint: disable=import-outside-toplevel
    except ImportError:
        log("load_xdg_menu_data()", exc_info=True)
        if first_time("no-python-xdg"):
            log.warn("Warning: cannot use application menu data:")
            log.warn(" no python-xdg module")
        return None
    menu = None
    error = None
    #see ticket #2340,
    #invalid values for XDG_CONFIG_DIRS can cause problems,
    #so try unsetting it if we can't load the menus with it:
    default_xdg = f"{sys.prefix}/etc/xdg".replace("/usr/etc", "/etc")
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    for cd in (False, True):
        with OSEnvContext():
            if cd is True and not os.environ.pop("XDG_CONFIG_DIRS", ""):
                #was already unset
                continue
            # see ticket #2174,
            # things may break if the prefix is not set,
            # and it isn't set when logging in via ssh,
            # so we have to guess!
            config_dirs = []
            #XDG_CONFIG_HOME takes precedence so add it first:
            if xdg_home:
                config_dirs.append(f"{xdg_home}/xdg")
            for d in os.environ.get("XDG_CONFIG_DIRS", default_xdg).split(":"):
                if d not in config_dirs:
                    config_dirs.append(d)
            prefixes = [None, ""]
            #we sanitize the environment,
            #but perhaps the value from the existing environment was useful:
            prefix = get_saved_env().get("XDG_MENU_PREFIX")
            if prefix:
                prefixes.append(prefix)
            desktop = os.environ.get("XDG_SESSION_DESKTOP", "")
            if desktop:
                prefixes.append(f"{desktop}-")      #ie: "gnome-"
            for d in config_dirs:
                for path in glob.glob(f"{d}/menus/*applications.menu"):
                    filename = os.path.basename(path)               #ie: "gnome-applications.menu"
                    prefix = filename[:-len("applications.menu")]   #ie: "gnome-"
                    if prefix not in prefixes:
                        prefixes.append(prefix)
            log(f"load_xdg_menu_data() will try prefixes {prefixes} from config directories {config_dirs}")
            for prefix in prefixes:
                if prefix is not None:
                    os.environ["XDG_MENU_PREFIX"] = prefix
                try:
                    log("parsing xdg menu data for prefix %r with XDG_CONFIG_DIRS=%s and XDG_MENU_PREFIX=%s",
                        prefix, os.environ.get("XDG_CONFIG_DIRS"), os.environ.get("XDG_MENU_PREFIX"))
                    menu = parse()
                    break
                except Exception as e:
                    log("load_xdg_menu_data()", exc_info=True)
                    error = e
                    menu = None
        if menu:
            break
    if menu is None:
        if error and first_time("xdg-menu-error"):
            log.error("Error parsing xdg menu data:")
            log.estr(error)
            log.error(" this is either a bug in python-xdg,")
            log.error(" or an invalid system menu configuration")
            log.error(" for more information, please see:")
            log.error(" https://github.com/Xpra-org/xpra/issues/2174")
        return None
    menu_data = {}
    entries = tuple(menu.getEntries())
    log(f"{menu}.getEntries()={entries}")
    if len(entries)==1 and entries[0].Submenus:
        entries = entries[0].Submenus
        log(f"using submenus {entries}")
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
        #add an 'Applications' menu if we don't have one:
        app_menu = menu_data.get("Applications")
        if app_menu:
            app_menu.setdefault("Entries", {}).update(entries)
        else:
            menu_data["Applications"] = {
                "Name" : "Applications",
                "Entries" : entries,
                }
    return menu_data

def load_applications(menu_data=None):
    entries : Dict[str,Any] = {}
    if not LOAD_APPLICATIONS:
        return entries
    def already_has_name(name):
        if not menu_data:
            return False
        for menu_category in menu_data.values():
            if name in menu_category.get("Entries", {}):
                return True
        return False
    from xdg.Menu import MenuEntry  # pylint: disable=import-outside-toplevel
    for d in LOAD_APPLICATIONS:
        if not os.path.exists(d):
            continue
        for f in os.listdir(d):
            if not f.endswith(".desktop"):
                continue
            try:
                me = MenuEntry(f, d)
            except Exception:
                log(f"failed to load {f!r} from {d!r}", f, d, exc_info=True)
            else:
                ed = load_xdg_entry(me.DesktopEntry)
                if not ed:
                    continue
                name = ed.get("Name")
                if name and not already_has_name(name):
                    entries[name] = ed
    log("entries(%s)=%s", LOAD_APPLICATIONS, remove_icons(entries))
    return entries


def load_desktop_sessions() -> Dict[str,Any]:
    xsessions : Dict[str,Any] = {}
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
                    icon_filename = find_icon(*names)
                    if icon_filename:
                        icondata = icon_util.load_icon_from_file(icon_filename)
                        if icondata:
                            entry["IconData"] = icondata[0]
                            entry["IconType"] = icondata[1]
                xsessions[name] = entry
            except Exception as e:
                log("load_desktop_sessions(%s)", remove_icons, exc_info=True)
                log.error(f"Error loading desktop entry {filename!r}:")
                log.estr(e)
    return xsessions


def get_icon_names_for_session(name:str) -> List[str]:
    ALIASES = {
        "deepin"    : ["deepin-launcher", "deepin-show-desktop"],
        "xfce"      : ["org.xfce.xfdesktop", ]
        }
    names = [name]+ALIASES.get(name, [])
    for split in (" on ", " session", "-session", " classic"):
        if name.find(split)>0:     #ie: "gnome on xorg"
            short_name = name.split(split)[0]
            names += [
                short_name,
                f"{short_name}-session",
                f"{short_name}-desktop",
                ] + ALIASES.get(short_name, [])   # -> "gnome"
    return names
