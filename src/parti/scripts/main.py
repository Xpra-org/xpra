# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This is the main script that starts up Parti itself.

import os
from parti.scripts import PartiOptionParser
import parti.parti_main

def main(cmdline):
    parser = PartiOptionParser()
    parser.add_option("--replace", action="store_true",
                      dest="replace", default=False,
                      help="Replace any running window manager with Parti")
    parser.add_option("-t", "--tray",
                      dest="tray", default="CompositeTest",
                      help="Set default tray type")
    (options, args) = parser.parse_args(cmdline[1:])

    # This means, if an exception propagates to the gtk mainloop, then pass it
    # on outwards.  Or at least it did at one time; dunno if it actually does
    # anything these days.
    os.environ["PYGTK_FATAL_EXCEPTIONS"] = "1"

    try:
        p = parti.parti_main.Parti(options)
        p.main()
    except:
        if "_PARTI_PDB" in os.environ:
            import sys, pdb
            pdb.post_mortem(sys.exc_traceback)
        raise
