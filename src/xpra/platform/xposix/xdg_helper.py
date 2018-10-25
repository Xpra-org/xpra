# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util import envbool
from xpra.os_util import load_binary_file
from xpra.log import Logger
log = Logger("exec", "util")

LOAD_GLOB = envbool("XPRA_XDG_LOAD_GLOB", True)
EXPORT_ICONS = envbool("XPRA_XDG_EXPORT_ICONS", True)
DEBUG_COMMANDS = os.environ.get("XPRA_XDG_DEBUG_COMMANDS", "").split(",")
if sys.version_info[0] >= 3:
    unicode = str           #@ReservedAssignment
    from typing import Generator as generator       #@UnresolvedImport, @UnusedImport
else:
    from types import GeneratorType as generator    #@Reimport


def isvalidtype(v):
    if isinstance(v, (list, tuple, generator)):
        if len(v)==0:
            return True
        return all(isvalidtype(x) for x in v)
    return isinstance(v, (bytes, str, unicode, bool, int))

def export(entry, properties=[]):
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
    if EXPORT_ICONS:
        #load icon binary data:
        icon = props.get("Icon")
        icondata = load_icon_from_theme(icon)
        if icondata:
            props["IconData"] = icondata
    l("properties(%s)=%s", name, props)
    return props

def load_icon_from_theme(icon_name, theme=None):
    if not EXPORT_ICONS or not icon_name:
        return None
    from xdg import IconTheme
    filename = IconTheme.getIconPath(icon_name, theme=theme)
    if not filename:
        return None
    icondata = load_binary_file(filename)
    if not icondata:
        return None
    log("'%s': got icon data from '%s': %i bytes", icon_name, filename, len(icondata))
    return icondata

def load_glob_icon(submenu_data, main_dirname="categories"):
    if not LOAD_GLOB:
        return None
    #doesn't work with IconTheme.getIconPath,
    #so do it the hard way:
    import glob
    from xdg import IconTheme
    icondirs = getattr(IconTheme, "icondirs", [])
    if not icondirs:
        return None
    extensions = ["png", "svg", "xpm"]
    for x in ("Icon", "Name", "GenericName"):
        v = submenu_data.get(x)
        if not v:
            continue
        for dn in [main_dirname, "*"]:
            for d in icondirs:
                for ext in extensions:
                    pathnames = [
                        os.path.join(d, "*", "*", dn, "%s.%s" % (v, ext)),
                        os.path.join(d, "*", dn, "*", "%s.%s" % (v, ext)),
                        ]
                    for pathname in pathnames:
                        filenames = glob.glob(pathname)
                        if filenames:
                            for f in filenames:
                                icondata = load_binary_file(f)
                                if icondata:
                                    log("found icon for '%s' with glob '%s': %s", v, pathname, f)
                                    return icondata
    return None


xdg_menu_data = None
def load_xdg_menu_data():
    global xdg_menu_data
    if not xdg_menu_data:
        try:
            from xdg.Menu import parse, Menu, MenuEntry
        except ImportError:
            log("load_xdg_menu_data()", exc_info=True)
            log.warn("Warning: no xdg module, cannot use application menu data")
        else:
            xdg_menu_data = {}
            try:
                menu = parse()
                for submenu in menu.getEntries():
                    if isinstance(submenu, Menu) and submenu.Visible:
                        name = submenu.getName()
                        #log.info("submenu %s: %s, %s", name, submenu, dir(submenu))
                        submenu_data = export(submenu, [
                            "Name", "GenericName", "Comment",
                            "Path", "Icon",
                            ])
                        xdg_menu_data[name] = submenu_data
                        icondata = submenu_data.get("IconData")
                        if not icondata:
                            #try harder:
                            icondata = load_glob_icon(submenu_data, "categories")
                            if icondata:
                                submenu_data["IconData"] = icondata
                        entries_data = submenu_data.setdefault("Entries", {})
                        for entry in submenu.getEntries():
                            #TODO: can we have more than 2 levels of submenus?
                            if isinstance(entry, MenuEntry):
                                de = entry.DesktopEntry
                                name = de.getName()
                                #not exposed:
                                #"MimeType" is an re
                                #"Version" is a float
                                props = export(de, (
                                    "Type", "VersionString", "Name", "GenericName", "NoDisplay",
                                    "Comment", "Icon", "Hidden", "OnlyShowIn", "NotShowIn",
                                    "Exec", "TryExec", "Path", "Terminal", "MimeTypes",
                                    "Categories", "StartupNotify", "StartupWMClass", "URL",
                                    ))
                                if de.getTryExec():
                                    try:
                                        command = de.findTryExec()
                                    except:
                                        command = de.getTryExec()
                                else:
                                    command = de.getExec()
                                props["command"] = command
                                icondata = props.get("IconData")
                                if not icondata:
                                    #try harder:
                                    icondata = load_glob_icon(de, "apps")
                                    if icondata:
                                        props["IconData"] = icondata
                                entries_data[name] = props
            except Exception as e:
                log("load_xdg_menu_data()", exc_info=True)
                log.error("Error loading xdg menu data:")
                log.error(" %s", e)
    return xdg_menu_data
