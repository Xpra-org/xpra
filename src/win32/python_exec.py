#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# simple wrapper script so we can execute python commands with the same python interpreter
# and environment which is used by the xpra.exe / xpra_cmd.exe process.

import sys
from xpra.platform import program_context


with program_context("xpra-python-exec", "Xpra Python Exec"):
    if len(sys.argv)<2:
        print("you must specify python commands to run!")
        sys.exit(1)

    for arg in sys.argv[1:]:
        exec(arg)

sys.exit(0)
