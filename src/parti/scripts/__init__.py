# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import parti
from optparse import OptionParser

def PartiOptionParser(**kwargs):
    parser = OptionParser(version="Parti v%s" % parti.__version__, **kwargs)
    return parser
