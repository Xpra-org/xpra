#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>

#runs all the files in "unit/" that end in "test.py"

import sys
import time
import shutil
import os.path
import subprocess
from argparse import ArgumentParser

TEST_COVERAGE = os.environ.get("XPRA_TEST_COVERAGE", "1") == "1"
COVERAGE = os.environ.get("COVERAGE", shutil.which("coverage") or shutil.which("python3-coverage"))


def getargs() -> ArgumentParser:
    P = ArgumentParser()
    P.add_argument('--skip-fail', action='append', default=[])
    P.add_argument('--skip-slow', action='append', default=[])
    P.add_argument('-T', '--test', action='append')
    P.add_argument('test', nargs='*', default=[])
    return P


def main(args) -> int:
    if TEST_COVERAGE:
        # pylint: disable=import-outside-toplevel
        #only include xpra in the report,
        #and to do that, we need the path to the module (weird):
        import xpra
        xpra_mod_dir = os.environ.get("XPRA_MODULE_DIR") or os.path.dirname(xpra.__file__)
        run_cmd = [COVERAGE, "run", "--parallel-mode", "--include=%s/*" % xpra_mod_dir]
        #make sure we continue to use coverage to run sub-commands:
        xpra_cmd = os.environ.get("XPRA_COMMAND", shutil.which("xpra")) or "xpra"
        if xpra_cmd.find("coverage") < 0:
            os.environ["XPRA_COMMAND"] = " ".join(run_cmd + [xpra_cmd])
    else:
        run_cmd = [os.environ.get("PYTHON", "python3")]

    #ie: unit_dir = "/path/to/Xpra/trunk/src/unittests/unit"
    unit_dir = os.path.abspath(os.path.dirname(__file__))
    paths = args.test or [unit_dir]
    skip_fail = set(args.skip_fail)
    skip_slow = set(args.skip_slow)

    #ie: unittests_dir = "/path/to/Xpra/trunk/src/unittests"
    unittests_dir = os.path.dirname(unit_dir)
    sys.path.append(unittests_dir)

    #now look for tests to run
    def write(msg) -> None:
        sys.stdout.write(f"{msg}\n")
        sys.stdout.flush()

    def run_file(p: str) -> int:
        #ie: "~/projects/Xpra/trunk/src/tests/unit/version_util_test.py"
        tfile = os.path.join(unittests_dir, p)
        if not (os.path.isfile(tfile) and tfile.startswith(unittests_dir) and tfile.endswith("test.py")):
            write(f"invalid file skipped: {p}  Expect {unittests_dir}/.../*test.py")
            return 0
        #ie: "unit.version_util_test"
        name = p[len(unittests_dir) + 1:-3].replace(os.path.sep, ".")
        if p in skip_slow or name in skip_slow:
            write(f"skipped slow test as requested: {p}")
            return 0
        write(f"running {name}\n")
        cmd = run_cmd + [p]
        T0 = time.monotonic()
        try:
            with subprocess.Popen(cmd) as proc:
                v = proc.wait()
        except OSError as e:
            write(f"failed to execute {p} using {cmd}: {e}")
            v = 1
        if v != 0 and (p in skip_fail or name in skip_fail):
            write(f"ignore failure {v} as requested: {p}")
            v = 0
        elif v != 0:
            write(f"failure on {name}, exit code={v}")
        # else: pass
        T1 = time.monotonic()
        write(f"ran {name} in {T1 - T0:.2f} seconds\n")
        return v

    def add_recursive(d: str) -> int:
        paths = os.listdir(d)
        ret = 0
        for path in paths:
            p = os.path.join(d, path)
            v = 0
            if os.path.isfile(p) and p.endswith("test.py"):
                v = run_file(p)
            elif os.path.isdir(p):
                fp = os.path.join(d, p)
                v = add_recursive(fp)
            if v != 0:
                ret = v
        return ret

    write("************************************************************")
    write(f"running all the tests in {paths}")
    ret = 0
    for x in paths:
        if os.path.isdir(x):
            r = add_recursive(x)
        else:
            r = run_file(x)
        if r != 0:
            ret = r
    return ret


if __name__ == '__main__':
    sys.exit(main(getargs().parse_args()))
