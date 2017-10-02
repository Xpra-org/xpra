# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#these classes used to live here,
#we import them so we don't have to update the callers

from xpra.x11.common import Unmanageable, MAX_WINDOW_SIZE
from xpra.x11.gtk2.models.or_window import OverrideRedirectWindowModel
from xpra.x11.gtk2.models.systray import SystemTrayWindowModel
from xpra.x11.gtk2.models.window import WindowModel, configure_bits

assert Unmanageable and MAX_WINDOW_SIZE and OverrideRedirectWindowModel and SystemTrayWindowModel and WindowModel and configure_bits
