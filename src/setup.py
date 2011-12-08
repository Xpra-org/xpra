#!/usr/bin/env python

# This file is part of Parti.
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
    NEEDED_CYTHON = (0, 9, 7)
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
try:
    import getpass
    import socket
    import platform
    from datetime import date
    props = {"BUILT_BY":getpass.getuser(),
            "BUILT_ON":socket.gethostname(),
            "BUILD_DATE":date.today().isoformat(),
            "BUILD_CPU":(platform.uname()[5] or "unknown"),
            "BUILD_BIT": platform.architecture()[0]
            }
    #find revision:
    rev = None
    proc = subprocess.Popen("svnversion -n", stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    (out, err) = proc.communicate()
    if out:
        pos = out.find(":")
        if pos>=0:
            out = out[pos+1:]
        rev_str = ""
        for c in out:
            if c in "0123456789":
                rev_str += c
        rev = int(rev_str)
        props["REVISION"] = rev
        #find number of local files modified:
        changes = 0
        proc = subprocess.Popen("svn status", stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
        for line in out.splitlines():
            if sys.platform.startswith("win") and line.find("\\wcw"):
                """ windows is easily confused, symlinks for example - ignore them """
                continue
            if line.startswith("M") and line.find("build_info.py")<0:
                changes += 1
                print("WARNING: found modified file: %s" % line)
        props["LOCAL_MODIFICATIONS"] = changes
    #append to build_info.py:
    f = open("./xpra/build_info.py", 'a')
    for name,value in props.items():
        f.write("%s='%s'\n" % (name,value))
    f.close()
    print("updated build_info.py with %s" % props)
except:
    traceback.print_exc()
    raise Exception("failed to update build_info")


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

setup(
    name="parti-all",
    author="Antoine Martin",
    author_email="antoine@nagafix.co.uk",
    version=parti.__version__,
    url="http://xpra.org/",
    description="A window manager library, a window manager, and a 'screen for X' utility",
    long_description=full_desc,
    download_url="http://xpra.org/src/",
    packages=["wimpiggy", "wimpiggy.lowlevel",
              "parti", "parti.trays", "parti.addons", "parti.scripts",
              "xpra", "xpra.scripts", "xpra.platform",
              "xpra.xposix", "xpra.win32", "xpra.darwin",
              ],
    scripts=["scripts/parti", "scripts/parti-repl",
             "scripts/xpra",
             ],
    data_files=[
                ("share/man/man1", ["xpra.1", "parti.1"]),
                ("share/parti", ["README", "README.parti"]),
                ("share/xpra", ["README.xpra"]),
                ("share/wimpiggy", ["README.wimpiggy"]),
                ("share/xpra/icons", glob.glob("icons/*")),
                ],
    ext_modules=ext_modules,
    cmdclass=cmdclass,
    )
