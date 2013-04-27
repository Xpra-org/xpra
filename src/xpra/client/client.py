# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gobject, is_gtk3
gobject = import_gobject()

if is_gtk3():
    from xpra.client.gtk3.client import XpraClient      #@UnusedImport
else:
    from xpra.client.gtk2.client import XpraClient      #@UnusedImport @Reimport
assert XpraClient is not None