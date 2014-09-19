# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.scripts.main import do_legacy_bool_parse, enabled_str

def add_notray_option(cmdline, parser, defaults, extra_text=""):
    do_legacy_bool_parse(cmdline, "tray")
    parser.add_option("--tray", action="store", metavar="yes|no",
                          dest="tray", default=defaults.tray,
                          help="Enable Xpra's own system tray applet%s. Default: %s" % (extra_text, enabled_str(defaults.tray)))

def add_delaytray_option(cmdline, parser, defaults, extra_text=""):
    do_legacy_bool_parse(cmdline, "delay-tray")
    parser.add_option("--delay-tray", action="store", metavar="yes|no",
                          dest="delay_tray", default=defaults.delay_tray,
                          help="Waits for the first events before showing the system tray%s. Default: %s" % (extra_text, enabled_str(defaults.delay_tray)))
