# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

def do_init():
    for x in list(sys.argv):
        if x.startswith("-psn_"):
            sys.argv.remove(x)

def do_clean():
    pass
