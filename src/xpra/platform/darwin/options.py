# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def add_client_options(parser, defaults):
    parser.add_option("--swap-keys", action="store_true",
                          dest="swap_keys", default=defaults.swap_keys,
                          help="Swaps the 'Command' and 'Control' keys (default: '%default')")
    parser.add_option("--no-swap-keys", action="store_false",
                          dest="swap_keys",
                          help="Disables the swapping of the 'Command' and 'Control' keys")
