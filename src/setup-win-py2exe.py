# This file is part of Parti.
# Copyright (C) 2010-2011 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from distutils.core import setup
import py2exe
import glob

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
DLLs="Z:\\"

setup(
    name = 'Xpra',
    description = 'screen for X',
    version = '0.0.7.23',

    windows = [
                  {
                      'script': 'xpra/scripts/client_launcher.py',
                      'icon_resources': [(1, "xpra.ico")],
					  "dest_base": "Xpra-Launcher",
                  },
              ],

    console = [
                  {
                      'script': 'xpra/scripts/main.py',
                      'icon_resources': [(1, "xpra.ico")],
					  "dest_base": "Xpra",
                  }
              ],

    options = {
                  'py2exe': {
                      'packages':'encodings',
                      'includes': 'cairo, pango, pangocairo, atk, glib, gobject, gio',
                      'dll_excludes': 'w9xpopen.exe'
                  }
              },

    data_files=[
                   ('COPYING'),
                   ('README.xpra'),
                   ('website.url'),
                   ('icons', glob.glob('icons\\*.*')),
                   ('Microsoft.VC90.CRT', glob.glob('%s\\Microsoft.VC90.CRT\\*.*' % DLLs)),
                   ('Microsoft.VC90.MFC', glob.glob('%s\\Microsoft.VC90.MFC\\*.*' % DLLs)),
               ]
)
