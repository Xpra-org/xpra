#!/usr/bin/env python

# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# NOTE (FIXME): This setup.py file will not work on its own; you have to run
#   $ python make-constants-pxi.py wimpiggy/lowlevel/constants.txt wimpiggy/lowlevel/constants.pxi
# before using this setup.py, and again if you change
# wimpiggy/lowlevel/constants.txt.

# FIXME: Cython.Distutils.build_ext leaves crud in the source directory.  (So
# does the make-constants-pxi.py hack.)

import glob
from distutils.core import setup
from distutils.extension import Extension
import subprocess, sys, traceback

# Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
def pkgconfig(*packages, **kw):
    flag_map = {'-I': 'include_dirs',
                '-L': 'library_dirs',
                '-l': 'libraries'}
    cmd = ["pkg-config", "--libs", "--cflags", "%s" % (" ".join(packages),)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, _) = proc.communicate()
    status = proc.wait()
    if status!=0 and not ('clean' in sys.argv):
        raise Exception("call to pkg-config ('%s') failed" % (cmd,))
    for token in output.split():
        if flag_map.has_key(token[:2]):
            kw.setdefault(flag_map.get(token[:2]), []).append(token[2:])
        else: # throw others to extra_link_args
            kw.setdefault('extra_link_args', []).append(token)
        for k, v in kw.iteritems(): # remove duplicates
            kw[k] = list(set(v))
    return kw

from xpra.platform import XPRA_LOCAL_SERVERS_SUPPORTED
if XPRA_LOCAL_SERVERS_SUPPORTED:
    from Cython.Distutils import build_ext
    from Cython.Compiler.Version import version as cython_version_string
    cython_version = [int(part) for part in cython_version_string.split(".")]
    # This was when the 'for 0 < i < 10:' syntax as added, bump upwards as
    # necessary:
    NEEDED_CYTHON = (0, 14, 0)
    if tuple(cython_version) < NEEDED_CYTHON:
        sys.exit("ERROR: Your version of Cython is too old to build this package\n"
                 "You have version %s\n"
                 "Please upgrade to Cython %s or better"
                 % (cython_version_string,
                    ".".join([str(part) for part in NEEDED_CYTHON])))

    ext_modules = [
      Extension("wimpiggy.lowlevel.bindings",
                ["wimpiggy/lowlevel/bindings.pyx"],
                **pkgconfig("pygobject-2.0", "gdk-x11-2.0", "gtk+-x11-2.0",
                            "xtst", "xfixes", "xcomposite", "xdamage", "xrandr")
                ),
      Extension("xpra.wait_for_x_server",
                ["xpra/wait_for_x_server.pyx"],
                **pkgconfig("x11")
                ),
      ]

    cmdclass = {'build_ext': build_ext}
else:
    ext_modules = []
    cmdclass = {}

import wimpiggy
import parti
import xpra
assert wimpiggy.__version__ == parti.__version__ == xpra.__version__

# Add build info to build_info.py file:
import add_build_info
try:
    add_build_info.main()
except:
    traceback.print_exc()
    print("failed to update build_info")


wimpiggy_desc = "A library for writing window managers, using GTK+"
parti_desc = "A tabbing/tiling window manager using GTK+"
xpra_desc = "'screen for X' -- a tool to detach/reattach running X programs"

full_desc = """This package contains several sub-projects:
  wimpiggy:
    %s
  parti:
    %s
  xpra:
    %s""" % (wimpiggy_desc, parti_desc, xpra_desc)




extra_options = {}
if sys.platform.startswith("win"):
    # These files cannot be re-distributed legally :(
    # So here is the md5sum so you can find the right version:
    # 6fda4c0ef8715eead5b8cec66512d3c8  Microsoft.VC90.CRT/Microsoft.VC90.CRT.manifest
    # 4a8bc195abdc93f0db5dab7f5093c52f  Microsoft.VC90.CRT/msvcm90.dll
    # 6de5c66e434a9c1729575763d891c6c2  Microsoft.VC90.CRT/msvcp90.dll
    # e7d91d008fe76423962b91c43c88e4eb  Microsoft.VC90.CRT/msvcr90.dll
    # f6a85f3b0e30c96c993c69da6da6079e  Microsoft.VC90.CRT/vcomp90.dll
    # 17683bda76942b55361049b226324be9  Microsoft.VC90.MFC/Microsoft.VC90.MFC.manifest
    # 462ddcc5eb88f34aed991416f8e354b2  Microsoft.VC90.MFC/mfc90.dll
    # b9030d821e099c79de1c9125b790e2da  Microsoft.VC90.MFC/mfc90u.dll
    # d4e7c1546cf3131b7d84b39f8da9e321  Microsoft.VC90.MFC/mfcm90.dll
    # 371226b8346f29011137c7aa9e93f2f6  Microsoft.VC90.MFC/mfcm90u.dll
    #
    # This is where I keep them, you will obviously need to change this value:
    DLLs="Z:\\"
    import py2exe    #@UnresolvedImport
    assert py2exe is not None
    windows = [
                    {'script': 'win32/xpra_silent.py',                  'icon_resources': [(1, "win32/xpra.ico")],      "dest_base": "Xpra",},
                    {'script': 'xpra/gtk_view_keyboard.py',             'icon_resources': [(1, "win32/keyboard.ico")],  "dest_base": "GTK_Keyboard_Test",},
                    {'script': 'xpra/scripts/client_launcher.py',       'icon_resources': [(1, "xpra.ico")],            "dest_base": "Xpra-Launcher",
                  },
              ]
    console = [
                    {'script': 'xpra/scripts/main.py',                  'icon_resources': [(1, "xpra.ico")],            "dest_base": "Xpra_cmd",}
              ]
    includes = ['cairo', 'pango', 'pangocairo', 'atk', 'glib', 'gobject', 'gio', 'gtk.keysyms',
                "Crypto", "Crypto.Cipher",
                "hashlib",
                "PIL",
                "win32con", "win32gui", "win32process", "win32api"]
    options = {
                    'py2exe': {
                               'unbuffered': True,
                               'packages':'encodings',
                               'includes': includes,
                               'dll_excludes': 'w9xpopen.exe'
                            }
              }
    data_files=[
                   ('', ['COPYING']),
                   ('', ['README.xpra']),
                   ('', ['website.url']),
                   ('icons', glob.glob('icons\\*.*')),
                   ('Microsoft.VC90.CRT', glob.glob('%s\\Microsoft.VC90.CRT\\*.*' % DLLs)),
                   ('Microsoft.VC90.MFC', glob.glob('%s\\Microsoft.VC90.MFC\\*.*' % DLLs)),
               ]
    extra_options = dict(
        windows = windows,
        console = console,
        options = options,
        data_files = data_files,
        description = "Screen for X utility, allows you to connect to remote seamless sessions",
    )
else:
    packages=["wimpiggy", "wimpiggy.lowlevel",
              "parti", "parti.trays", "parti.addons", "parti.scripts",
              "xpra", "xpra.scripts", "xpra.platform",
              "xpra.xposix", "xpra.win32", "xpra.darwin",
              ]
    scripts=["scripts/parti", "scripts/parti-repl",
             "scripts/xpra",
             ]
    data_files=[
                ("share/man/man1", ["xpra.1", "parti.1"]),
                ("share/parti", ["README", "README.parti"]),
                ("share/xpra", ["README.xpra", "COPYING"]),
                ("share/wimpiggy", ["README.wimpiggy"]),
                ("share/xpra/icons", glob.glob("icons/*")),
                ]
    extra_options = dict(
        packages = packages,
        scripts = scripts,
        data_files = data_files,
        description = "A window manager library, a window manager, and a 'screen for X' utility",
    )

setup(
    name="parti-all",
    author="Antoine Martin",
    author_email="antoine@nagafix.co.uk",
    version=parti.__version__,
    url="http://xpra.org/",
    long_description=full_desc,
    download_url="http://xpra.org/src/",
    ext_modules=ext_modules,
    cmdclass=cmdclass,
    **extra_options
    )
