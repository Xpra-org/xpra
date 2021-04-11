# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
if sys.version_info[0]==2:
    from xpra.x11.gtk2 import gdk_display_source    #@UnresolvedImport, @UnusedImport
    from xpra.x11.gtk2.gdk_display_util import verify_gdk_display       #@UnusedImport
else:
    from xpra.x11.gtk3 import gdk_display_source    #@UnresolvedImport, @Reimport
    from xpra.x11.gtk3.gdk_display_util import verify_gdk_display       #@Reimport @UnusedImport

init_gdk_display_source     = gdk_display_source.init_gdk_display_source
close_gdk_display_source    = gdk_display_source.close_gdk_display_source
