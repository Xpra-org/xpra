#!/usr/bin/env python

# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import glob
from distutils.core import setup
from distutils.extension import Extension
import py2app    #@UnresolvedImport
assert py2app is not None
import subprocess, sys, traceback
import os.path
import stat

setup_options = {}
setup_options["name"] = "Xpra"
setup_options["author"] = "Antoine Martin"
setup_options["author_email"] = "antoine@nagafix.co.uk"
setup_options["version"] = "0.8.0"
setup_options["url"] = "http://xpra.org/"
setup_options["download_url"] = "http://xpra.org/src/"
setup_options["description"] = """'screen for X' -- a tool to detach/reattach running X programs"""

data_files = []
setup_options["data_files"] = data_files
packages = ["osxxpra"]
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
            "hashlib", "Image"]
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

print("")
print("py2app setup_options:")
for k,v in py2app_options.items():
    print("%s : %s" % (k,v))
print("")

setup_options["options"] = {"py2app": py2app_options}
xpra_src = "../src/"
data_files += [
                ("share/man/man1", [xpra_src+"man/xpra.1", xpra_src+"man/xpra_launcher.1"]),
                ("share/xpra", [xpra_src+"xpra.README", xpra_src+"COPYING"]),
                ("share/wimpiggy", [xpra_src+"wimpiggy.README"]),
                ("share/xpra/icons", glob.glob(xpra_src+"icons/*")),
                ("share/applications", [xpra_src+"xpra_launcher.desktop"]),
                ("share/icons", [xpra_src+"xpra.png"])
              ]
data_files.append(('share/xpra/webm', [xpra_src+"xpra/webm/LICENSE"]))

setup(**setup_options)
