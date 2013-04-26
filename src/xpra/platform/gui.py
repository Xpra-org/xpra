# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

### NOTE: this must be kept in sync with the version in
###    xpra/platform/__init__.py
#@PydevCodeAnalysisIgnore
import os as _os
import sys as _sys
if _os.name == "nt":
    from win32.gui import *
elif _sys.platform.startswith("darwin"):
    from darwin.gui import *
elif _os.name == "posix":
    from xposix.gui import *
else:
    raise OSError("Unknown OS %s" % (_os.name))
