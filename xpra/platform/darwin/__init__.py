# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Optional, Callable

def do_init():
    for x in list(sys.argv):
        if x.startswith("-psn_"):
            sys.argv.remove(x)
    if os.environ.get("XPRA_HIDE_DOCK", "")=="1":
        from AppKit import NSApp    #@UnresolvedImport
        #NSApplicationActivationPolicyAccessory = 1
        NSApp.setActivationPolicy_(1)

def do_init_env():
    from xpra.platform import init_env_common
    init_env_common()
    os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")
    # GStreamer's paths:
    bundle_contents = os.environ.get("GST_BUNDLE_CONTENTS")
    if bundle_contents:
        rsc_dir = os.path.join(bundle_contents, "Resources")
        os.environ["GST_PLUGIN_PATH"]       = os.path.join(rsc_dir, "lib", "gstreamer-1.0")
        os.environ["GST_PLUGIN_SCANNER"]    = os.path.join(rsc_dir, "bin", "gst-plugin-scanner")
    setup_debug_logging()


def is_launchd_launched() -> bool:
    # macOS spawns GUI-launched processes (Finder, Dock, Spotlight, or even
    # `open` from a shell) as direct children of launchd (pid 1). Running
    # the bundle's binary directly from a shell - or exec'ing it from
    # another process - makes that shell/process the parent instead.
    return os.getppid() == 1


def setup_debug_logging() -> None:
    """Honor ~/.xpra/debug and XPRA_LOG_TO_FILE for app bundle launches."""
    if os.environ.get("GST_BUNDLE_CONTENTS", "") == "":
        return
    if not is_launchd_launched() and os.environ.get("XPRA_LOG_TO_FILE", "0") != "1":
        return
    debug_file = os.path.join(os.path.expanduser("~"), ".xpra", "debug")
    debug_arg = ""
    try:
        with open(debug_file, "r", encoding="utf-8") as f:
            debug_arg = f.read().strip()
    except OSError:
        pass
    if debug_arg:
        sys.argv.append(f"--debug={debug_arg}")
    log_filename = os.environ.get("XPRA_LOG_FILENAME", "")
    if not log_filename:
        log_filename = os.path.join(os.path.expanduser("~"), ".xpra", f"debug-{os.getpid()}.log")
        os.environ["XPRA_LOG_FILENAME"] = log_filename
    try:
        os.makedirs(os.path.dirname(log_filename), exist_ok=True)
        log_fd = open(log_filename, "a", buffering=1, encoding="utf-8")
    except OSError:
        return
    log_fd.write(f"xpra debug output (pid={os.getpid()})\n")
    log_fd.write("env:\n")
    for key in sorted(os.environ):
        log_fd.write(f"  {key}={os.environ[key]}\n")
    log_fd.write(f"\nargv={sys.argv}\n\n")
    sys.stdout = log_fd
    sys.stderr = log_fd


exit_cb : Optional[Callable] = None
def quit_handler(*_args):
    global exit_cb
    if exit_cb:
        exit_cb()
    else:
        import gi
        gi.require_version('Gtk', '3.0')  # @UndefinedVariable
        from gi.repository import Gtk  # @UnresolvedImport
        Gtk.main_quit()
    return True

def set_exit_cb(ecb : Optional[Callable]):
    global exit_cb
    exit_cb = ecb

macapp = None
def get_OSXApplication():
    global macapp
    if macapp is None:
        import gi
        gi.require_version('GtkosxApplication', '1.0')  # @UndefinedVariable
        from gi.repository import GtkosxApplication     # @UnresolvedImport
        macapp = GtkosxApplication.Application()
        macapp.connect("NSApplicationWillTerminate", quit_handler)
    return macapp


#workaround for Big Sur dylib cache mess:
#https://stackoverflow.com/a/65599706/428751
def patch_find_library():
    from ctypes import util  #pylint: disable=import-outside-toplevel
    orig_util_find_library = util.find_library
    def new_util_find_library(name):
        res = orig_util_find_library(name)
        if res:
            return res
        return '/System/Library/Frameworks/'+name+'.framework/'+name
    util.find_library = new_util_find_library
if os.environ.get("XPRA_OSX_PATCH_FIND_LIBRARY", "1")=="1":
    patch_find_library()
