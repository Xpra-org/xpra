#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import glob
from distutils.core import setup
import py2app    #@UnresolvedImport
assert py2app is not None
import imp
import os

#import settings from main setup file (ugly!):
cwd = os.getcwd()
os.chdir("../src")
add_build_info = imp.load_source('add_build_info', '../src/add_build_info.py')
main_setup = imp.load_source('', '../src/setup.py')
os.chdir(cwd)
setup_options = main_setup.setup_options
#but remove things we don't care about:
for k in ("ext_modules", "py_modules", "cmdclass", "scripts"):
    del setup_options[k]


data_files = []
packages = ["osxxpra"]

setup_options["data_files"] = data_files
setup_options["packages"] = packages


Plist = dict(CFBundleDocumentTypes=[
                dict(CFBundleTypeExtensions=["Xpra"],
                     CFBundleTypeName="Xpra Session Config File",
                     CFBundleName="Xpra",
                     CFBundleTypeRole="Viewer"),
                ]
         )
setup_options["app"]= ["osxxpra/osx_xpra_launcher.py"]
includes = ["glib", "gio", "cairo", "pango", "pangocairo", "atk", "gobject", "gtk.keysyms",
            "osxxpra",
            "hashlib", "PIL",
            "xpra.platform.darwin",
            "xpra.client.gl",
            "xpra.client.gtk2",
            "xpra.gtk_common"]


py2app_options = {
    'iconfile': './xpra.icns',
    'plist': Plist,
    'site_packages': False,
    'argv_emulation': True,
    'strip': False,
    "includes": includes,
    'packages': packages,
    "frameworks": ['CoreFoundation', 'Foundation', 'AppKit'],
    }

setup_options["options"] = {"py2app": py2app_options}
xpra_src = "../src/"
data_files += [
                ("share/man/man1", [xpra_src+"man/xpra.1", xpra_src+"man/xpra_launcher.1"]),
                ("share/xpra", [xpra_src+"README", xpra_src+"COPYING"]),
                ("share/xpra/icons", glob.glob(xpra_src+"icons/*")),
                ("share/applications", [xpra_src+"xdg/xpra_launcher.desktop"]),
                ("share/applications", [xpra_src+"xdg/xpra.desktop"]),
                ("share/icons", [xpra_src+"xdg/xpra.png"])
              ]
data_files.append(('share/xpra/webm', [xpra_src+"xpra/codecs/webm/LICENSE"]))


def main():
    print("")
    print("setup_options:")
    for k,v in setup_options.items():
        if k!="options":
            print("* %s=%s" % (k, v))
    print("")
    print("py2app options:")
    for k,v in py2app_options.items():
        print("%s : %s" % (k,v))
    print("")
    setup(**setup_options)


if __name__ == "__main__":
    main()
