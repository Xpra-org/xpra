#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>

#need to find a generic way to discover tests
#that works with python2.6 without introducing more dependencies
#until then... this hack will do
#runs all the files in "unit/" that end in "test.py"

import sys
import os.path
import subprocess


def main():
    paths = []
    #ie: unit_dir = "/path/to/Xpra/trunk/src/unittests/unit"
    unit_dir = os.path.abspath(os.path.dirname(__file__))
    if len(sys.argv)>1:
        for x in sys.argv[1:]:
            paths.append(os.path.abspath(x))
    else:
        paths.append(unit_dir)
    #ie: unittests_dir = "/path/to/Xpra/trunk/src/unittests"
    unittests_dir = os.path.dirname(unit_dir)
    sys.path.append(unittests_dir)
    #now look for tests to run
    def write(msg):
        sys.stdout.write("%s\n" % msg)
        sys.stdout.flush()
    def run_file(p):
        #ie: "~/projects/Xpra/trunk/src/tests/unit/version_util_test.py"
        if not (p.startswith(unittests_dir) and p.endswith("test.py")):
            write("invalid file skipped: %s" % p)
            return 0
        #ie: "unit.version_util_test"
        name = p[len(unittests_dir)+1:-3].replace(os.path.sep, ".")
        write("running %s\n" % name)
        cmd = ["python%s" % sys.version_info[0], p]
        try:
            proc = subprocess.Popen(cmd)
        except:
            write("failed to execute %s" % p)
            return 1
        v = proc.wait()
        if v!=0:
            write("failure on %s, exit code=%s" % (name, v))
            return v
        return 0
    def add_recursive(d):
        paths = os.listdir(d)
        for path in paths:
            p = os.path.join(d, path)
            v = 0
            if os.path.isfile(p) and p.endswith("test.py"):
                v = run_file(p)
            elif os.path.isdir(p):
                fp = os.path.join(d, p)
                v = add_recursive(fp)
            if v !=0:
                return v
        return 0
    write("************************************************************")
    write("running all the tests in %s" % paths)
    for x in paths:
        if os.path.isdir(x):
            r = add_recursive(x)
            if r!=0:
                return r
        else:
            run_file(x)

if __name__ == '__main__':
    v = main()
    sys.exit(v)
