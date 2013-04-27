# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def add_client_options(parser):
    from xpra.platform.options_util import add_notray_option, add_delaytray_option
    add_notray_option(parser)
    add_delaytray_option(parser)
