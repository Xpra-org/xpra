# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys


def main():
    from xpra.platform import program_context
    with program_context("Print-Atoms", "Print Atoms"):
        from xpra.x11.gtk import gdk_display_source  # @UnresolvedImport, @Reimport

        gdk_display_source.init_gdk_display_source()  # @UndefinedVariable

        from xpra.x11.bindings.core import X11CoreBindings  # @UnresolvedImport

        X11Core = X11CoreBindings()

        for s in sys.argv[1:]:
            if s.lower().startswith("0x"):
                v = int(s, 16)
            else:
                v = int(s)
            print("%s : %s" % (s, X11Core.get_atom_name(v)))


if __name__ == "__main__":
    main()
