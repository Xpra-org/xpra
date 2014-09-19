# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def add_client_options(cmdline, group, defaults):
    from xpra.scripts.main import do_legacy_bool_parse, enabled_str
    do_legacy_bool_parse(cmdline, "swap-keys")
    group.add_option("--swap-keys", action="store", metavar="yes|no",
                          dest="swap_keys", default=defaults.swap_keys,
                          help="Swap the 'Command' and 'Control' keys. Default: %s" % enabled_str(defaults.swap_keys))
