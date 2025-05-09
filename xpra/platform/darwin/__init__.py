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
    # GStreamer's paths:
    bundle_contents = os.environ.get("GST_BUNDLE_CONTENTS", "")
    if bundle_contents:
        rsc_dir = os.path.join(bundle_contents, "Resources")
        if "GST_PLUGIN_PATH" not in os.environ:
            os.environ["GST_PLUGIN_PATH"] = os.path.join(rsc_dir, "lib", "gstreamer-1.0")
        if "GST_PLUGIN_SCANNER" not in os.environ:
            os.environ["GST_PLUGIN_SCANNER"] = os.path.join(rsc_dir, "libexec", "gstreamer-1.0", "gst-plugin-scanner")


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
