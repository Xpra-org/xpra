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

import wimpiggy
import parti
import xpra
assert wimpiggy.__version__ == parti.__version__ == xpra.__version__


packages = ["wimpiggy", "wimpiggy.lowlevel",
          "parti", "parti.trays", "parti.addons", "parti.scripts",
          "xpra", "xpra.scripts", "xpra.platform",
          "xpra.xposix", "xpra.win32", "xpra.darwin",
          ]

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
    # The Microsoft C library DLLs:
    # Unfortunately, these files cannot be re-distributed legally :(
    # So here is the md5sum so you can find the right version:
    # (you can find them in various packages, including Visual Studio 2008,
    # pywin32, etc...)
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
    C_DLLs="E:\\"
    # The x264 DLLs which you can grab from here:
    # http://ffmpeg.zeranoe.com/builds/
    # beware that some builds work, others crash.. here is one that is known to work ok:
    # ffmpeg-git-4082198-win32-dev
    # This is where I keep them, you will obviously need to change this value:
    ffmpeg_path="E:\\ffmpeg-win32-shared"
    ffmpeg_include_dir = "%s\\include" % ffmpeg_path
    ffmpeg_lib_dir = "%s\\lib" % ffmpeg_path
    ffmpeg_bin_dir = "%s\\bin" % ffmpeg_path
    # Same for vpx:
    # http://code.google.com/p/webm/downloads/list
    vpx_PATH="E:\\vpx-vp8-debug-src-x86-win32mt-vs9-v1.1.0"
    vpx_include_dir = "%s\\include" % vpx_PATH
    vpx_lib_dir = "%s\\lib\\Win32" % vpx_PATH

    def pkgconfig(*args):
        def add_to_PATH(bindir):
            import os
            if os.environ['PATH'].find(bindir)<0:
                os.environ['PATH'] = bindir + ';' + os.environ['PATH']
            if bindir not in sys.path:
                sys.path.append(bindir)
        if args[0]=="x264":
            add_to_PATH(ffmpeg_bin_dir)
            return {'include_dirs': ["xpra/x264/win32", ffmpeg_include_dir],
                    'library_dirs': ["xpra/x264/win32", ffmpeg_lib_dir],
                    'libraries':    ["x264lib", "swscale", "avcodec", "avutil"]}
        elif args[0]=="vpx":
            add_to_PATH(ffmpeg_bin_dir)
            return {'include_dirs': ["xpra/vpx/win32", vpx_include_dir, ffmpeg_include_dir],
                    'library_dirs': ["xpra/vpx/win32", vpx_lib_dir, ffmpeg_lib_dir],
                    'libraries':    ["vpxmt", "vpxmtd", "swscale", "avcodec", "avutil"]}
        else:
            raise Exception("unknown package config: %s" % str(args))

    import py2exe    #@UnresolvedImport
    assert py2exe is not None
    windows = [
                    {'script': 'win32/xpra_silent.py',                  'icon_resources': [(1, "win32/xpra.ico")],      "dest_base": "Xpra",},
                    {'script': 'xpra/gtk_view_keyboard.py',             'icon_resources': [(1, "win32/keyboard.ico")],  "dest_base": "GTK_Keyboard_Test",},
                    {'script': 'xpra/scripts/client_launcher.py',       'icon_resources': [(1, "xpra.ico")],            "dest_base": "Xpra-Launcher",},
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
                               'packages': packages,
                               'includes': includes,
                               'dll_excludes': 'w9xpopen.exe'
                            }
              }
    data_files=[
                   ('', ['COPYING']),
                   ('', ['README.xpra']),
                   ('', ['website.url']),
                   ('icons', glob.glob('icons\\*.*')),
                   ('Microsoft.VC90.CRT', glob.glob('%s\\Microsoft.VC90.CRT\\*.*' % C_DLLs)),
                   ('Microsoft.VC90.MFC', glob.glob('%s\\Microsoft.VC90.MFC\\*.*' % C_DLLs)),
                   ('', glob.glob('%s\\bin\\*.dll' % ffmpeg_path)),
               ]

    extra_options = dict(
        windows = windows,
        console = console,
        options = options,
        data_files = data_files,
        description = "Screen for X utility, allows you to connect to remote seamless sessions",
    )
else:
    # Tweaked from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/502261
    def pkgconfig(*packages, **ekw):
        flag_map = {'-I': 'include_dirs',
                    '-L': 'library_dirs',
                    '-l': 'libraries'}
        cmd = ["pkg-config", "--libs", "--cflags", "%s" % (" ".join(packages),)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output, _) = proc.communicate()
        status = proc.wait()
        if status!=0 and not ('clean' in sys.argv or 'sdist' in sys.argv):
            raise Exception("call to pkg-config ('%s') failed" % (cmd,))
        kw = dict(ekw)
        if sys.version>='3':
            output = output.decode('utf-8')
        for token in output.split():
            if token[:2] in flag_map:
                kw.setdefault(flag_map.get(token[:2]), []).append(token[2:])
            else: # throw others to extra_link_args
                kw.setdefault('extra_link_args', []).append(token)
            for k, v in kw.items(): # remove duplicates
                kw[k] = list(set(v))
        print("pkgconfig(%s,%s)=%s" % (packages, ekw, kw))
        return kw

    scripts=["scripts/parti", "scripts/parti-repl",
             "scripts/xpra", "scripts/xpra_launcher",
             ]
    data_files=[
                ("share/man/man1", ["xpra.1", "xpra_launcher.1", "parti.1"]),
                ("share/parti", ["README", "README.parti"]),
                ("share/xpra", ["README.xpra", "COPYING"]),
                ("share/wimpiggy", ["README.wimpiggy"]),
                ("share/xpra/icons", glob.glob("icons/*")),
                ("share/applications", ["xpra_launcher.desktop"]),
                ("share/icons/xpra.png", ["xpra.png"])
                ]
    extra_options = dict(
        packages = packages,
        scripts = scripts,
        data_files = data_files,
        description = "A window manager library, a window manager, and a 'screen for X' utility",
    )



ext_modules = []
cmdclass = {}
def cython_version_check():
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
def cython_add(extension):
    global ext_modules, cmdclass
    cython_version_check()
    from Cython.Distutils import build_ext
    ext_modules.append(extension)
    cmdclass = {'build_ext': build_ext}

from xpra.platform import XPRA_LOCAL_SERVERS_SUPPORTED
if XPRA_LOCAL_SERVERS_SUPPORTED:
    cython_add(Extension("wimpiggy.lowlevel.bindings",
                ["wimpiggy/lowlevel/bindings.pyx"],
                **pkgconfig("pygobject-2.0", "gdk-x11-2.0", "gtk+-x11-2.0",
                            "xtst", "xfixes", "xcomposite", "xdamage", "xrandr")
                ))
    cython_add(Extension("xpra.wait_for_x_server",
                ["xpra/wait_for_x_server.pyx"],
                **pkgconfig("x11")
                ))
x264_ENABLED = True



vpx_ENABLED = True
filtered_args = []
for arg in sys.argv:
    if arg == "--without-x264":
        x264_ENABLED = False
    elif arg == "--without-vpx":
        vpx_ENABLED = False
    else:
        filtered_args.append(arg)
sys.argv = filtered_args

if x264_ENABLED:
    packages.append("xpra.x264")
    cython_add(Extension("xpra.x264.codec",
                ["xpra/x264/codec.pyx", "xpra/x264/x264lib.c"],
                **pkgconfig("x264", "libswscale", "libavcodec")
                ))
if vpx_ENABLED:
    packages.append("xpra.vpx")
    cython_add(Extension("xpra.vpx.codec",
                ["xpra/vpx/codec.pyx", "xpra/vpx/vpxlib.c"],
                **pkgconfig("vpx", "libswscale", "libavcodec")
                ))






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
