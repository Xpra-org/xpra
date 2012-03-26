# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This is a little script that uses D-Bus to request the running Parti spawn a
# REPL window.

import os
from parti.scripts import PartiOptionParser
import parti.bus

def main(cmdline):
    parser = PartiOptionParser()
    parser.parse_args(cmdline[1:])

    # This means, if an exception propagates to the gtk mainloop, then pass it
    # on outwards.  Or at least it did at one time; dunno if it actually does
    # anything these days.
    os.environ["PYGTK_FATAL_EXCEPTIONS"] = "1"

    try:
        proxy = parti.bus.get_parti_proxy()
        print("Using D-Bus to request running Parti spawn a REPL window")
        proxy.SpawnReplWindow()
        print("Done")
    except:
        if "_PARTI_PDB" in os.environ:
            import sys, pdb
            pdb.post_mortem(sys.exc_info()[2])
        raise
