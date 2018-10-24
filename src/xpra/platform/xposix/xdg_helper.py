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

XDG_EXPORT_ICONS = envbool("XPRA_XDG_EXPORT_ICONS", True)
XDG_DEBUG_COMMANDS = os.environ.get("XPRA_XDG_DEBUG_COMMANDS", "").split(",")
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
    #not exposed:
    #"MimeType" is an re
    #"Version" is a float
    if any(x and name.lower().find(x.lower())>=0 for x in XDG_DEBUG_COMMANDS):
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
    if XDG_EXPORT_ICONS:
        #load icon binary data:
        icon = props.get("Icon")
        if icon:
            from xdg import IconTheme
            filename = IconTheme.getIconPath(icon)
            if filename:
                icondata = load_binary_file(filename)
                if icondata:
                    log("'%s': got icon data from '%s': %i bytes", name, filename, len(icondata))
                    props["IconData"] = icondata
    l("properties(%s)=%s", name, props)
    return props


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
                            entries_data[name] = props
    return xdg_menu_data
