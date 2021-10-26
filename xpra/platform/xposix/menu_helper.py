#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
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
from typing import Generator as generator       #@UnresolvedImport, @UnusedImport

from xpra.util import envbool, first_time, engs
from xpra.os_util import DummyContextManager, OSEnvContext, get_saved_env
from xpra.codecs import icon_util
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("exec", "menu")

LOAD_FROM_RESOURCES = envbool("XPRA_XDG_LOAD_FROM_RESOURCES", True)
LOAD_FROM_PIXMAPS = envbool("XPRA_XDG_LOAD_FROM_PIXMAPS", True)
LOAD_FROM_THEME = envbool("XPRA_XDG_LOAD_FROM_THEME", True)
LOAD_GLOB = envbool("XPRA_XDG_LOAD_GLOB", False)

EXPORT_ICONS = envbool("XPRA_XDG_EXPORT_ICONS", True)
DEBUG_COMMANDS = os.environ.get("XPRA_XDG_DEBUG_COMMANDS", "").split(",")
EXPORT_TERMINAL_APPLICATIONS = envbool("XPRA_XDG_EXPORT_TERMINAL_APPLICATIONS", False)
EXPORT_SELF = envbool("XPRA_XDG_EXPORT_SELF", False)
LOAD_APPLICATIONS = os.environ.get("XPRA_MENU_LOAD_APPLICATIONS", "%s/share/applications" % sys.prefix).split(":")


def isvalidtype(v):
    if isinstance(v, (list, tuple, generator)):
        if not v:
            return True
        return all(isvalidtype(x) for x in v)
    return isinstance(v, (bytes, str, bool, int))

def export(entry, properties):
    name = entry.getName()
    props = {}
    if any(x and name.lower().find(x.lower())>=0 for x in DEBUG_COMMANDS):
        l = log.info
    else:
        l = log
    for prop in properties:
        fn_name = "get%s" % prop
        try:
            fn = getattr(entry, fn_name, None)
            if fn:
                v = fn()
                if isinstance(v, (list, tuple, generator)):
                    l("%s=%s (%s)", prop, v, type(x for x in v))
                else:
                    l("%s=%s (%s)", prop, v, type(v))
                if not isvalidtype(v):
                    log.warn("Warning: found invalid type for '%s': %s", v, type(v))
                else:
                    props[prop] = v
        except Exception as e:
            l("error on %s", entry, exc_info=True)
            log.error("Error parsing '%s': %s", prop, e)
    l("properties(%s)=%s", name, props)
    load_entry_icon(props)
    return props


MAX_THEMES = 2
IconTheme = Config = themes = None
IconLoadingContext = DummyContextManager
if LOAD_FROM_THEME:
    try:
        from xdg import IconTheme, Config
    except ImportError:
        log("python xdg is missing", exc_info=True)
    else:
        class KeepCacheLoadingContext():
            __slots__ = ("cache_time", )
            def __enter__(self):
                self.cache_time = Config.cache_time
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
            if len(themes)>MAX_THEMES:
                for x in glob.glob("%s/share/icons/*/index.theme" % sys.prefix):
                    parts = x.split(os.path.sep)
                    name = parts[-2]
                    addtheme(name)
                    if len(themes)>MAX_THEMES:
                        break
            log("icon themes=%s", themes)
        init_themes()

EXTENSIONS = ("png", "svg", "xpm")


def clear_cache():
    log("clear_cache() IconTheme=%s", IconTheme)
    if not IconTheme:
        return
    IconTheme.themes = []
    IconTheme.theme_cache = {}
    IconTheme.dir_cache = {}
    IconTheme.icon_cache = {}


def load_entry_icon(props):
    #load icon binary data
    names = []
    for x in ("Icon", "Name", "GenericName"):
        name = props.get(x)
        if name and name not in names:
            names.append(name)
            continue
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
        log("no icon found for %s from %s", names, props)
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
    pixmaps_dir = "%s/share/pixmaps" % sys.prefix
    pixmaps_dirs = (pixmaps_dir, os.path.join(pixmaps_dir, "comps"))
    for d in pixmaps_dirs:
        if not os.path.exists(d) or not os.path.isdir(d):
            return None
        for name in names:
            for ext in EXTENSIONS:
                fn = os.path.join(d, "%s.%s" % (name, ext))
                if fn and os.path.exists(fn):
                    return fn
    return None

def find_theme_icon(*names):
    if not LOAD_FROM_THEME:
        return None
    global IconTheme, Config, themes
    if not (IconTheme and Config and themes):
        return None
    size = Config.icon_size
    #log.info("IconTheme.LookupIcon%s", (icon_name, size, themes.keys(), ("png", "svg", "xpm")))
    for name in names:
        for theme in themes.values():
            fn = IconTheme.LookupIcon(name, size, theme=theme, extensions=EXTENSIONS)
            if fn and os.path.exists(fn):
                return fn
    return None

def find_glob_icon(*names, category="categories"):
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
                        os.path.join(d, "*", "*", dn, "%s.%s" % (name, ext)),
                        os.path.join(d, "*", dn, "*", "%s.%s" % (name, ext)),
                        ]
    for pathname in pathnames:
        filenames = glob.glob(pathname)
        log("glob(%s) matches %i filenames", pathname, len(filenames))
        if filenames:
            for f in filenames:
                v = icon_util.load_icon_from_file(f)
                if v:
                    log("found icon for %s with glob '%s': %s", names, pathname, f)
                    return v
    return None


def load_xdg_entry(de):
    #not exposed:
    #"MimeType" is an re
    #"Version" is a float
    props = export(de, (
        "Type", "VersionString", "Name", "GenericName", "NoDisplay",
        "Comment", "Icon", "Hidden", "OnlyShowIn", "NotShowIn",
        "Exec", "TryExec", "Path", "Terminal", "MimeTypes",
        "Categories", "StartupNotify", "StartupWMClass", "URL",
        ))
    if props.get("NoDisplay", False) or props.get("Hidden", False):
        return None
    if de.getTryExec():
        try:
            command = de.findTryExec()
        except Exception:
            command = de.getTryExec()
    else:
        command = de.getExec()
    if not command:
        #this command is not executable!
        return None
    props["command"] = command
    if not EXPORT_SELF and command and command.find("xpra")>=0:
        return None
    if not EXPORT_TERMINAL_APPLICATIONS and props.get("Terminal", False):
        return None
    icondata = props.get("IconData")
    if not icondata:
        #try harder:
        icondata = find_glob_icon(de, category="apps")
        if icondata:
            bdata, ext = icondata
            props["IconData"] = bdata
            props["IconType"] = ext
    return props

def load_xdg_menu(submenu):
    #log.info("submenu %s: %s, %s", name, submenu, dir(submenu))
    submenu_data = export(submenu, [
        "Name", "GenericName", "Comment",
        "Path", "Icon",
        ])
    icondata = submenu_data.get("IconData")
    if not icondata:
        #try harder:
        icondata = find_glob_icon(submenu_data, category="categories")
        if icondata:
            bdata, ext = icondata
            submenu_data["IconData"] = bdata
            submenu_data["IconType"] = ext
    entries_data = submenu_data.setdefault("Entries", {})
    from xdg.Menu import Menu, MenuEntry
    def add_entries(entries):
        for i, entry in enumerate(entries):
            if isinstance(entry, MenuEntry):
                de = entry.DesktopEntry
                name = de.getName()
                log("  - %-3i %s", i, name)
                try:
                    ed = load_xdg_entry(de)
                    if ed:
                        entries_data[name] = ed
                except Exception as e:
                    log("load_xdg_menu(%s)", submenu, exc_info=True)
                    log.error("Error loading desktop entry '%s':", name)
                    log.error(" %s", e)
            elif isinstance(entry, Menu):
                #merge up:
                add_entries(entry.Entries)
    add_entries(submenu.getEntries())
    if not entries_data:
        return None
    return submenu_data

def remove_icons(menu_data):
    def noicondata(d):
        return dict((k,v) for k,v in d.items() if k!="IconData")
    filt = {}
    for category, cdef in menu_data.items():
        fcdef = dict(cdef)
        entries = dict(fcdef.get("Entries", {}))
        for entry, edef in tuple(entries.items()):
            entries[entry] = noicondata(edef)
        fcdef["Entries"] = entries
        filt[category] = fcdef
    return filt

def load_menu():
    icon_util.large_icons.clear()
    start = monotonic()
    with IconLoadingContext():
        xdg_menu_data = load_xdg_menu_data()
    end = monotonic()
    if xdg_menu_data:
        l = sum(len(x) for x in xdg_menu_data.values())
        log.info("loaded %i start menu entries from %i sub-menus in %.1f seconds",
                 l, len(xdg_menu_data), end-start)
    if icon_util.large_icons:
        log.warn("Warning: found %i large icon%s:", len(icon_util.large_icons), engs(icon_util.large_icons))
        for filename, size in icon_util.large_icons:
            log.warn(" '%s' (%i KB)", filename, size//1024)
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
    for cd in (False, True):
        with OSEnvContext():
            if cd:
                if not os.environ.pop("XDG_CONFIG_DIRS", ""):
                    #was already unset
                    continue
            #see ticket #2174,
            #things may break if the prefix is not set,
            #and it isn't set when logging in via ssh
            for prefix in (None, "", "gnome-", "kde-"):
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
        if error:
            log.error("Error parsing xdg menu data:")
            log.error(" %s", error)
            log.error(" this is either a bug in python-xdg,")
            log.error(" or an invalid system menu configuration")
        return None
    menu_data = {}
    entries = tuple(menu.getEntries())
    log("%s.getEntries()=%s", menu, entries)
    if len(entries)==1 and entries[0].Submenus:
        entries = entries[0].Submenus
        log("using submenus %s", entries)
    for i, submenu in enumerate(entries):
        if not isinstance(submenu, Menu):
            log("entry '%s' is not a submenu", submenu)
            continue
        name = submenu.getName()
        log("* %-3i %s", i, name)
        if not submenu.Visible:
            log(" submenu '%s' is not visible", name)
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
            log.error(" %s", e)
    if LOAD_APPLICATIONS:
        from xdg.Menu import MenuEntry
        entries = {}
        for d in LOAD_APPLICATIONS:
            for f in os.listdir(d):
                if not f.endswith(".desktop"):
                    continue
                try:
                    me = MenuEntry(f, d)
                except Exception:
                    log("failed to load %s from %s", f, d, exc_info=True)
                else:
                    ed = load_xdg_entry(me.DesktopEntry)
                    if not ed:
                        continue
                    name = ed.get("Name")
                    #ensure we don't already have it in another submenu:
                    for menu_category in menu_data.values():
                        if name in menu_category.get("Entries", {}):
                            ed = None
                            break
                    if ed:
                        entries[name] = ed
        log("entries(%s)=%s", LOAD_APPLICATIONS, remove_icons(entries))
        if entries:
            #add an 'Applications' menu if we don't have one:
            md = menu_data.get("Applications")
            if not md:
                md = {
                    "Name" : "Applications",
                    }
                menu_data["Applications"] = md
            md.setdefault("Entries", {}).update(entries)
    return menu_data


def load_desktop_sessions():
    xsessions_dir = "%s/share/xsessions" % sys.prefix
    if not os.path.exists(xsessions_dir) or not os.path.isdir(xsessions_dir):
        return {}
    xsessions = {}
    with IconLoadingContext():
        from xdg.DesktopEntry import DesktopEntry
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
                    v = find_icon(*names)
                    if v:
                        entry["IconData"] = v[0]
                        entry["IconType"] = v[1]
                xsessions[name] = entry
            except Exception as e:
                log("load_desktop_sessions(%s)", remove_icons, exc_info=True)
                log.error("Error loading desktop entry '%s':", filename)
                log.error(" %s", e)
    return xsessions


def get_icon_names_for_session(name):
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
                "%s-session" % short_name,
                "%s-desktop" % short_name,
                ] + ALIASES.get(short_name, [])   # -> "gnome"
    return names
