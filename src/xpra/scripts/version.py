# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.scripts.config import python_platform
#only imported to make sure we can get hold of a reference to the real "platform" module
assert python_platform 
from xpra.version_util import get_version_info, get_platform_info, get_host_info
from xpra.util import nonl


def main():
    def print_dict(d):
        for k in sorted(d.keys()):
            v = d[k]
            if type(v) in (list, tuple):
                v = " ".join([str(x) for x in v])
            print("* %s : %s" % (k.ljust(32), nonl(str(v))))
    from xpra.platform import init, clean
    try:
        init("Version-Info", "Version Info")
        print("Build:")
        print_dict(get_version_info())
        print("")
        print("Platform:")
        pi = get_platform_info()
        #ugly workaround for the fact that "sys.platform" has no key..
        if "" in pi:
            pi["sys"] = pi[""]
            del pi[""]
        print_dict(pi)
        print("")
        print("Host:")
        print_dict(get_host_info())
    finally:
        clean()


if __name__ == "__main__":
    main()
