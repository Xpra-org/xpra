#!/usr/bin/env python

# for running xpra in Windows via py2exe and avoid the warnings/errors
# we redirect stdout and stderr to a logfile (which we create if needed)

import sys
import datetime
import os.path

logfile = "Xpra.log"
if sys.platform.startswith("win"):
	path = os.environ.get("APPDATA")
	if not os.path.exists(path):
		os.mkdir(path)
	path = os.path.join(path, "Xpra")
	if not os.path.exists(path):
		os.mkdir(path)
	logfile = os.path.join(path, logfile)

sys.stdout = open(logfile, "a", 0)
sys.stderr = sys.stdout

sys.stdout.write("xpra %s\n" % str(sys.argv))
sys.stdout.write("starting at %s\n" % datetime.datetime.now().strftime("%Y/%d/%m %H:%M:%S "))
sys.stdout.write("before try\n")

code = 0
try:
	sys.stdout.write("importing xpra.scripts.main\n")
	import xpra.scripts.main
	sys.stdout.write("calling main\n")
	xpra.scripts.main.main("xpra", sys.argv)
	sys.stdout.write("xpra terminated cleanly\n")
except Exception, e:
	sys.stdout.write("error: %s\n" % e)
	code = 1
finally:
	sys.stdout.write("in finally\n")
sys.exit(code)
