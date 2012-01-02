# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')

__version__ = "0.0.7.33"
import wimpiggy
assert wimpiggy.__version__ == __version__
svn_revision="unknown"
