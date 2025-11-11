#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Chris Marchetti <adamnew123456@gmail.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def nopid(_pid: int) -> int:
    return 0


get_parent_pid = nopid

try:
    from xpra.platform.posix import proc_libproc
    get_parent_pid = proc_libproc.get_parent_pid
except (ImportError, AttributeError):
    try:
        from xpra.platform.posix import proc_procps
        get_parent_pid = proc_procps.get_parent_pid
    except (ImportError, AttributeError):
        pass


def main(argv) -> int:
    from xpra.platform import program_context
    with program_context("Get-Parent-Pid", "Get Parent Pid"):
        if not callable(get_parent_pid):
            print("`get_parent_pid` is not available!")
            return 1
        print(f"using `get_parent_pid`={get_parent_pid}")
        try:
            print(f"from {get_parent_pid.__module__!r} module")
        except AttributeError:  # `__module__` is CPython only?
            pass
        for pid_str in argv[1:]:
            try:
                pid = int(pid_str)
            except ValueError:
                print(f"{pid_str} is not a valid pid number")
            else:
                print(f" get_parent_pid({pid})={get_parent_pid(pid)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
