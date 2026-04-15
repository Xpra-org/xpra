# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from collections.abc import Callable


def do_init() -> None:
    for x in list(sys.argv):
        if x.startswith("-psn_"):
            sys.argv.remove(x)
    if os.environ.get("XPRA_HIDE_DOCK", "") == "1":
        from AppKit import NSApp
        # NSApplicationActivationPolicyAccessory = 1
        NSApp.setActivationPolicy_(1)


def do_init_env() -> None:
    from xpra.platform import init_env_common
    init_env_common()
    if os.environ.get("CRYPTOGRAPHY_OPENSSL_NO_LEGACY") is None:
        os.environ["CRYPTOGRAPHY_OPENSSL_NO_LEGACY"] = "1"
    setup_app_bundle_env()


def setup_app_bundle_env() -> None:
    bundle_contents = os.environ.get("XPRA_BUNDLE_CONTENTS", "")
    if not bundle_contents:
        return
    bundle_res = f"{bundle_contents}/Resources"
    bundle_frameworks = f"{bundle_contents}/Frameworks"
    bundle_lib = f"{bundle_res}/lib"
    bundle_share = f"{bundle_res}/share"
    bundle_etc = f"{bundle_res}/etc"

    os.environ.update({
        "GST_BUNDLE_CONTENTS": bundle_contents,
        "GST_PLUGIN_PATH": f"{bundle_lib}/gstreamer-1.0",
        "GST_PLUGIN_SCANNER": f"{bundle_contents}/Helpers/gst-plugin-scanner",
        "XDG_CONFIG_DIRS": f"{bundle_etc}/xdg",
        "XDG_DATA_DIRS": bundle_share,
        "GTK_DATA_PREFIX": bundle_res,
        "GTK_EXE_PREFIX": bundle_res,
        "GTK_PATH": bundle_res,
        "GTK_THEME": "Adwaita",
        "GTK_IM_MODULE_FILE": f"{bundle_lib}/gtk-3.0/3.0.0/gtk.immodules",
        "GDK_PIXBUF_MODULE_FILE": f"{bundle_lib}/gdk-pixbuf-2.0/2.10.0/loaders.cache",
        "GI_TYPELIB_PATH": f"{bundle_lib}/girepository-1.0",
        "CAIRO_MODULE_DIR": f"{bundle_frameworks}/cairo",
        "PANGO_RC_FILE": f"{bundle_etc}/pango/pangorc",
        "PANGO_LIBDIR": f"{bundle_lib}",
        "PANGO_SYSCONFDIR": f"{bundle_etc}",
        "GSETTINGS_SCHEMA_DIR": f"{bundle_share}/glib-2.0/schemas/",
    })
    x11_dir = f"{bundle_frameworks}/X11"
    if os.path.exists(x11_dir) and os.path.isdir(x11_dir):
        def addpath(key: str, path: str) -> None:
            os.environ[key] = os.pathsep.join([path] + os.environ.get(key, "").split(os.pathsep))
        addpath("PATH", f"{x11_dir}/bin")
        addpath("DYLD_LIBRARY_PATH", f"{x11_dir}/lib")


def default_gtk_main_exit() -> None:
    from xpra.os_util import gi_import
    gtk = gi_import("Gtk")
    gtk.main_quit()


exit_cb: Callable = default_gtk_main_exit


def quit_handler(*_args):
    exit_cb()
    return True


def set_exit_cb(ecb: Callable):
    global exit_cb
    assert ecb is not None
    exit_cb = ecb


macapp = None


def get_OSXApplication():
    global macapp
    if macapp is None:
        from xpra.os_util import gi_import
        osxapp = gi_import("GtkosxApplication")
        macapp = osxapp.Application()
        macapp.connect("NSApplicationWillTerminate", quit_handler)
    return macapp


def is_app_bundle() -> bool:
    # we cannot call UNUserNotificationCenter.currentNotificationCenter()
    # if we're not in a proper app bundle, otherwise it will crash hard!
    from Foundation import NSBundle
    bundle = NSBundle.mainBundle()
    bundle_url = bundle.bundleURL().path()
    bundle_id = bundle.bundleIdentifier()
    info = dict(bundle.infoDictionary() or {})
    app = ""
    path = bundle_url
    while path and path != "/":
        if path.endswith(".app"):
            app = os.path.splitext(os.path.basename(path))[0]
            break
        path = os.path.dirname(path)

    is_app = app.startswith("Xpra") and bundle_id is not None
    from xpra.log import Logger
    log = Logger("macos")
    log("darwin bundle=%s, url=%r, id=%r, app=%r, info=%r, is_app=%r",
        bundle, bundle_url, bundle_id, app, info, is_app)
    return is_app


# workaround for Big Sur dylib cache mess:
# https://stackoverflow.com/a/65599706/428751
def patch_find_library() -> None:
    from ctypes import util  # pylint: disable=import-outside-toplevel
    orig_util_find_library = util.find_library

    def new_util_find_library(name):
        res = orig_util_find_library(name)
        if res:
            return res
        return '/System/Library/Frameworks/' + name + '.framework/' + name

    util.find_library = new_util_find_library


if os.environ.get("XPRA_OSX_PATCH_FIND_LIBRARY", "1") == "1":
    patch_find_library()
