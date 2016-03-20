#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.scripts.config import python_platform
#only imported to make sure we can get hold of a reference to the real "platform" module
assert python_platform
from xpra.version_util import get_version_info, get_platform_info, get_host_info
from xpra.util import print_nested_dict


def main():
    from xpra.platform import program_context
    with program_context("Version-Info", "Version Info"):
        print("Build:")
        print_nested_dict(get_version_info())
        print("")
        print("Platform:")
        pi = get_platform_info()
        #ugly workaround for the fact that "sys.platform" has no key..
        if "" in pi:
            pi["sys"] = pi[""]
            del pi[""]
        print_nested_dict(pi)
        print("")
        print("Host:")
        d = get_host_info()
        #add os specific version info:
        try:
            from xpra.platform.info import get_version_info as pvinfo
            d.update(pvinfo())
        except:
            pass
        print_nested_dict(d)


if __name__ == "__main__":
    main()
