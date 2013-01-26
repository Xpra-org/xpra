# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

### NOTE: this must be kept in sync with the version in
###    xpra/platform/gui.py
#@PydevCodeAnalysisIgnore
import os as _os
import sys as _sys
if _os.name == "nt":
    from xpra.win32 import *
elif _sys.platform.startswith("darwin"):
    from xpra.darwin import *
elif _os.name == "posix":
    from xpra.xposix import *
else:
    raise OSError("Unknown OS %s" % (_os.name))

def add_notray_option(parser, extra_text=""):
    parser.add_option("--no-tray", action="store_true",
                          dest="no_tray", default=False,
                          help="Disables the system tray%s" % extra_text)

def add_delaytray_option(parser, extra_text=""):
    parser.add_option("--delay-tray", action="store_true",
                          dest="delay_tray", default=False,
                          help="Waits for the first events before showing the system tray")
