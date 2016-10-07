#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>

#need to find a generic way to discover tests
#that works with python2.6 without introducing more dependencies
#until then... this hack will do
#runs all the files in "unit/" that end in "test.py"

import sys


def main():
    import os.path
    import subprocess
    if len(sys.argv)==2:
        p = os.path.abspath(sys.argv[1])
    else:
        p = os.path.abspath(os.path.dirname(__file__))
    #ie: p=~/Xpra/trunk/src/tests/unit
    root = os.path.dirname(p)
    #ie: d=~/Xpra/trunk/src/tests
    sys.path.append(root)
    #now look for tests to run
    def write(msg):
        sys.stdout.write("%s\n" % msg)
        sys.stdout.flush()
    def run_file(p):
        #ie: "~/projects/Xpra/trunk/src/tests/unit/version_util_test.py"
        assert p.startswith(root) and p.endswith("test.py")
        #ie: "unit.version_util_test"
        name = p[len(root)+1:-3].replace(os.path.sep, ".")
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
    write("running all the tests in %s" % p)
    return add_recursive(p)

if __name__ == '__main__':
    v = main()
    sys.exit(v)
