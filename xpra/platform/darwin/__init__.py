# This file is part of Xpra.
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

def do_init():
    for x in list(sys.argv):
        if x.startswith("-psn_"):
            sys.argv.remove(x)
    if os.environ.get("XPRA_HIDE_DOCK", "")=="1":
        from AppKit import NSApp    #@UnresolvedImport
        #NSApplicationActivationPolicyAccessory = 1
        NSApp.setActivationPolicy_(1)



def do_clean():
    pass


exit_cb = None
def quit_handler(*_args):
    global exit_cb
    if exit_cb:
        exit_cb()
    else:
        from gi.repository import Gtk
        Gtk.main_quit()
    return True

def set_exit_cb(ecb):
    global exit_cb
    exit_cb = ecb

macapp = None
def get_OSXApplication():
    global macapp
    if macapp is None:
        import gi
        gi.require_version('GtkosxApplication', '1.0')
        from gi.repository import GtkosxApplication #@UnresolvedImport
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
