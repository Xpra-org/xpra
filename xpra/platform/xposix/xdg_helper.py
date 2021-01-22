# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Utility functions for loading xdg menus
using python-xdg
"""

import os
import re
import sys
import glob
from io import BytesIO
from typing import Generator as generator       #@UnresolvedImport, @UnusedImport
from threading import Lock

from xpra.util import envbool, envint, print_nested_dict, first_time, engs, ellipsizer
from xpra.os_util import load_binary_file, monotonic_time, OSEnvContext
from xpra.log import Logger, add_debug_category

log = Logger("exec", "menu")

LOAD_GLOB = envbool("XPRA_XDG_LOAD_GLOB", True)
EXPORT_ICONS = envbool("XPRA_XDG_EXPORT_ICONS", True)
MAX_ICON_SIZE = envint("XPRA_XDG_MAX_ICON_SIZE", 65536)
DEBUG_COMMANDS = os.environ.get("XPRA_XDG_DEBUG_COMMANDS", "").split(",")

large_icons = []

INKSCAPE_RE = b'\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'

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
    #load icon binary data:
    icon = props.get("Icon")
    icondata = load_icon_from_theme(icon)
    if icondata:
        bdata, ext = icondata
        props["IconData"] = bdata
        props["IconType"] = ext
    return props

_Rsvg = None
def load_Rsvg():
    global _Rsvg
    if _Rsvg is None:
        import gi
        try:
            gi.require_version('Rsvg', '2.0')
            from gi.repository import Rsvg
            log("load_Rsvg() Rsvg=%s", Rsvg)
            _Rsvg = Rsvg
        except (ValueError, ImportError) as e:
            if first_time("no-rsvg"):
                log.warn("Warning: cannot resize svg icons,")
                log.warn(" the Rsvg bindings were not found:")
                log.warn(" %s", e)
            _Rsvg = False
    return _Rsvg


def load_icon_from_file(filename):
    log("load_icon_from_file(%s)", filename)
    if filename.endswith("xpm"):
        from PIL import Image
        try:
            img = Image.open(filename)
            buf = BytesIO()
            img.save(buf, "PNG")
            pngicondata = buf.getvalue()
            buf.close()
            return pngicondata, "png"
        except ValueError as e:
            log("Image.open(%s)", filename, exc_info=True)
        except Exception as e:
            log("Image.open(%s)", filename, exc_info=True)
            log.error("Error loading '%s':", filename)
            log.error(" %s", e)
        #fallback to PixbufLoader:
        try:
            from xpra.gtk_common.gtk_util import pixbuf_save_to_memory
            data = load_binary_file(filename)
            from gi.repository import GdkPixbuf
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            pngicondata = pixbuf_save_to_memory(pixbuf, "png")
            return pngicondata, "png"
        except Exception as e:
            log("pixbuf error loading %s", filename, exc_info=True)
            log.error("Error loading '%s':", filename)
            log.error(" %s", e)
    icondata = load_binary_file(filename)
    if not icondata:
        return None
    if filename.endswith("svg") and len(icondata)>MAX_ICON_SIZE//2:
        #try to resize it
        size = len(icondata)
        pngdata = svg_to_png(filename, icondata)
        if pngdata:
            log("reduced size of SVG icon %s, from %i bytes to %i bytes as PNG",
                     filename, size, len(pngdata))
            icondata = pngdata
            filename = filename[:-3]+"png"
    log("got icon data from '%s': %i bytes", filename, len(icondata))
    if len(icondata)>MAX_ICON_SIZE and first_time("icon-size-warning-%s" % filename):
        global large_icons
        large_icons.append((filename, len(icondata)))
    return icondata, os.path.splitext(filename)[1].lstrip(".")

def svg_to_png(filename, icondata, w=128, h=128):
    Rsvg = load_Rsvg()
    if not Rsvg:
        return None
    try:
        import cairo
        #'\sinkscape:[a-zA-Z]*=["a-zA-Z0-9]*'
        img = cairo.ImageSurface(cairo.FORMAT_ARGB32, 128, 128)
        ctx = cairo.Context(img)
        handle = Rsvg.Handle.new_from_data(icondata)
        handle.render_cairo(ctx)
        buf = BytesIO()
        img.write_to_png(buf)
        icondata = buf.getvalue()
        buf.close()
        return icondata
    except Exception:
        log("svg_to_png%s", (icondata, w, h), exc_info=True)
        if re.findall(INKSCAPE_RE, icondata):
            #try again after stripping the bogus inkscape attributes
            #as some rsvg versions can't handle that (ie: Debian Bullseye)
            icondata = re.sub(INKSCAPE_RE, b"", icondata)
            return svg_to_png(filename, icondata, w, h)
        log.error("Error: failed to convert svg icon")
        log.error(" '%s':", filename)
        log.error(" %i bytes, %s", len(icondata), ellipsizer(icondata))


def load_icon_from_theme(icon_name, theme=None):
    if not EXPORT_ICONS or not icon_name:
        return None
    from xdg import IconTheme
    filename = IconTheme.getIconPath(icon_name, theme=theme)
    if not filename:
        return None
    return load_icon_from_file(filename)

def load_glob_icon(submenu_data, main_dirname="categories"):
    if not LOAD_GLOB or not EXPORT_ICONS:
        return None
    #doesn't work with IconTheme.getIconPath,
    #so do it the hard way:
    from xdg import IconTheme
    icondirs = getattr(IconTheme, "icondirs", [])
    if not icondirs:
        return None
    for x in ("Icon", "Name", "GenericName"):
        name = submenu_data.get(x)
        if name:
            icondata = find_icon(main_dirname, icondirs, name)
            if icondata:
                return icondata
    return None

def find_icon(main_dirname, icondirs, name):
    extensions = ("png", "svg", "xpm")
    pathnames = []
    for dn in (main_dirname, "*"):
        for d in icondirs:
            for ext in extensions:
                pathnames += [
                    os.path.join(d, "*", "*", dn, "%s.%s" % (name, ext)),
                    os.path.join(d, "*", dn, "*", "%s.%s" % (name, ext)),
                    ]
    for pathname in pathnames:
        filenames = glob.glob(pathname)
        log("glob(%s) matches %i filenames", pathname, len(filenames))
        if filenames:
            for f in filenames:
                icondata = load_icon_from_file(f)
                if icondata:
                    log("found icon for '%s' with glob '%s': %s", name, pathname, f)
                    return icondata
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
    if de.getTryExec():
        try:
            command = de.findTryExec()
        except Exception:
            command = de.getTryExec()
    else:
        command = de.getExec()
    props["command"] = command
    icondata = props.get("IconData")
    if not icondata:
        #try harder:
        icondata = load_glob_icon(de, "apps")
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
        icondata = load_glob_icon(submenu_data, "categories")
        if icondata:
            bdata, ext = icondata
            submenu_data["IconData"] = bdata
            submenu_data["IconType"] = ext
    entries_data = submenu_data.setdefault("Entries", {})
    for entry in submenu.getEntries():
        #can we have more than 2 levels of submenus?
        from xdg.Menu import MenuEntry
        if isinstance(entry, MenuEntry):
            de = entry.DesktopEntry
            name = de.getName()
            try:
                entries_data[name] = load_xdg_entry(de)
            except Exception as e:
                log("load_xdg_menu(%s)", submenu, exc_info=True)
                log.error("Error loading desktop entry '%s':", name)
                log.error(" %s", e)
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


load_lock = Lock()
xdg_menu_data = None
def load_xdg_menu_data(force_reload=False):
    global xdg_menu_data, large_icons
    with load_lock:
        if not xdg_menu_data or force_reload:
            large_icons = []
            start = monotonic_time()
            xdg_menu_data = do_load_xdg_menu_data()
            end = monotonic_time()
            if xdg_menu_data:
                l = sum(len(x) for x in xdg_menu_data.values())
                log.info("%s %i start menu entries from %i sub-menus in %.1f seconds",
                         "reloaded" if force_reload else "loaded", l, len(xdg_menu_data), end-start)
            if large_icons:
                log.warn("Warning: found %i large icon%s:", len(large_icons), engs(large_icons))
                for filename, size in large_icons:
                    log.warn(" '%s' (%i KB)", filename, size//1024)
                log.warn(" more bandwidth will be used by the start menu data")
    return xdg_menu_data

def do_load_xdg_menu_data():
    try:
        from xdg.Menu import parse, Menu
    except ImportError:
        log("do_load_xdg_menu_data()", exc_info=True)
        if first_time("no-python-xdg"):
            log.warn("Warning: cannot use application menu data:")
            log.warn(" no python-xdg module")
        return None
    menu = None
    error = None
    with OSEnvContext():
        #see ticket #2340,
        #invalid values for XDG_CONFIG_DIRS can cause problems,
        #so try unsetting it if we can't load the menus with it:
        for cd in (False, True):
            if cd:
                os.environ.pop("XDG_CONFIG_DIRS", None)
            #see ticket #2174,
            #things may break if the prefix is not set,
            #and it isn't set when logging in via ssh
            for prefix in (None, "", "gnome-", "kde-"):
                if prefix is not None:
                    os.environ["XDG_MENU_PREFIX"] = prefix
                try:
                    menu = parse()
                    break
                except Exception as e:
                    log("do_load_xdg_menu_data()", exc_info=True)
                    error = e
                    menu = None
    if menu is None:
        if error:
            log.error("Error parsing xdg menu data:")
            log.error(" %s", error)
            log.error(" this is either a bug in python-xdg,")
            log.error(" or an invalid system menu configuration")
        return None
    menu_data = {}
    for submenu in menu.getEntries():
        if isinstance(submenu, Menu) and submenu.Visible:
            name = submenu.getName()
            try:
                menu_data[name] = load_xdg_menu(submenu)
            except Exception as e:
                log("load_xdg_menu_data()", exc_info=True)
                log.error("Error loading submenu '%s':", name)
                log.error(" %s", e)
    return menu_data


def main():
    from xpra.platform import program_context
    with program_context("XDG-Menu-Helper", "XDG Menu Helper"):
        for x in list(sys.argv):
            if x in ("-v", "--verbose"):
                sys.argv.remove(x)
                add_debug_category("menu")
                log.enable_debug()
        def icon_fmt(icondata):
            return "%i bytes" % len(icondata)
        if len(sys.argv)>1:
            for x in sys.argv[1:]:
                if os.path.isabs(x):
                    v = load_icon_from_file(x)
                    print("load_icon_from_file(%s)=%s" % (x, v))
        else:
            menu = load_xdg_menu_data()
            if menu:
                print_nested_dict(menu, vformat={"IconData" : icon_fmt})
            else:
                print("no menu data found")
    return 0

if __name__ == "__main__":
    r = main()
    sys.exit(r)
