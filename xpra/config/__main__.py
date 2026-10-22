#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Inspect configuration with python -m xpra.config."""

import os
import sys
from xpra import config
from xpra.config.defaults import make_defaults_struct, dict_to_validated_config
from xpra.config.io import read_config
from xpra.config.types import OPTION_TYPES, name_to_field
from xpra.util.str_fn import csv


def main(argv=()):
    from xpra.util.str_fn import nonl

    def print_options(o):
        for k, ot in sorted(OPTION_TYPES.items()):
            v = getattr(o, name_to_field(k), "")
            if ot in (bool, str) and v is None:
                v = "Auto"
            if isinstance(v, list):
                v = csv(str(x) for x in v)
            print("* %-32s : %s" % (k, nonl(v)))
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Config-Info", "Config Info"):
        enable_color()
        if consume_verbose_argv(argv, "all"):

            def print_debug(*args):
                print(args[0] % args[1:])
            config.debug = print_debug

        if len(argv) > 1:
            for filename in argv[1:]:
                print("")
                print(f"Configuration file {filename!r}")
                if not os.path.exists(filename):
                    print(" Error: file not found")
                    continue
                d = read_config(filename)
                options = dict_to_validated_config(d)
                print_options(options)
        else:
            print("Default Configuration:")
            print_options(make_defaults_struct())


if __name__ == "__main__":
    main(sys.argv)
