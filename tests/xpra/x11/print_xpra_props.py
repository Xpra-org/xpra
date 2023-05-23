# This file is part of Xpra.
# Copyright (C) 2012-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.gtk3 import gdk_display_source    #@UnresolvedImport, @Reimport
gdk_display_source.init_gdk_display_source()  # @UndefinedVariable

from xpra.x11.bindings.window import X11WindowBindings #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.server.server_uuid import get_mode, get_uuid

print(f"mode={get_mode()}")
print(f"uuid={get_uuid()}")
