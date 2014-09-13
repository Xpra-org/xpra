#!/usr/bin/env python

# simple wrapper script so we can launch a script file with the same python interpreter
# and environment which is used by the xpra.exe / xpra_cmd.exe process.
#
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
exec(open(filename).read())
ret(0)
