# This file is part of Xpra.
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

def do_init():
    for x in list(sys.argv):
        if x.startswith("-psn_"):
            sys.argv.remove(x)

def do_clean():
    pass

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
