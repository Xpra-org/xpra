# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#default:
def add_client_options(*args):
    pass

from xpra.platform import platform_import
platform_import(globals(), "options", True,
                "add_client_options")
