#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014-2020 Antoine Martin <antoine@xpra.org>

#runs all the files in "unit/" that end in "test.py"

import sys
import os.path
import subprocess


COVERAGE = os.environ.get("XPRA_TEST_COVERAGE", "1")=="1"


def main():
    if COVERAGE:
        #only include xpra in the report,
        #and to do that, we need the path to the module (weird):
        import xpra
        xpra_mod_dir = os.path.dirname(xpra.__file__)
        run_cmd = ["coverage", "run", "-a", "--include=%s/*" % xpra_mod_dir]
        #make sure we continue to use coverage to run sub-commands:
        def which(command):
            from distutils.spawn import find_executable
            try:
                return find_executable(command)
            except Exception:
                return command
        xpra_cmd = os.environ.get("XPRA_COMMAND", which("xpra")) or "xpra"
        if xpra_cmd.find("coverage")<0:
            os.environ["XPRA_COMMAND"] = " ".join(run_cmd+[xpra_cmd])
    else:
        run_cmd = ["python3"]

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
        cmd = run_cmd + [p]
        try:
            proc = subprocess.Popen(cmd)
        except OSError as e:
            write("failed to execute %s using %s: %s" % (p, cmd, e))
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
        else:
            r = run_file(x)
        if r!=0:
            return r

if __name__ == '__main__':
    sys.exit(main())
