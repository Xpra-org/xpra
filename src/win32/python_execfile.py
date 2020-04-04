#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# simple wrapper script so we can launch a script file with the same python interpreter
# and environment which is used by the xpra.exe / xpra_cmd.exe process.

import os.path
import sys
from xpra.platform import init, clean
init("Xpra-Python-Exec")

def ret(v):
    clean()
    sys.exit(v)

if len(sys.argv)<2:
    print("you must specify a python script file to run!")
    ret(1)
filename = sys.argv[1]
if not os.path.exists(filename):
    print("script file '%s' not found" % filename)
    ret(1)

cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)
fdata = open(filename, 'rb').read()
if filename.endswith(".pyc"):
    from importlib.util import MAGIC_NUMBER
    assert fdata.startswith(MAGIC_NUMBER), "not a python compiled file, or version mismatch"
    import marshal
    #16 is the magic value for python 3.8:
    fdata = marshal.loads(fdata[16:])
exec(fdata)
ret(0)
