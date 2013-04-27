# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def add_notray_option(parser, extra_text=""):
    parser.add_option("--no-tray", action="store_true",
                          dest="no_tray", default=False,
                          help="Disables the system tray%s" % extra_text)

def add_delaytray_option(parser, extra_text=""):
    parser.add_option("--delay-tray", action="store_true",
                          dest="delay_tray", default=False,
                          help="Waits for the first events before showing the system tray")
