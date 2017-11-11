# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import envbool
from xpra.os_util import WIN32, PYTHON3

#transparency with GTK is not supported on MS Windows with PYGTK:
DEFAULT_HAS_ALPHA = not WIN32 or PYTHON3
GTK_ALPHA_SUPPORTED = envbool("XPRA_ALPHA", DEFAULT_HAS_ALPHA)
