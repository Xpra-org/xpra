# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra import __version__ as local_version
import sys

from xpra.log import Logger
log = Logger()

def version_as_numbers(version):
    return [int(x) for x in version.split(".")]

def is_compatible_with(remote_version):
    rv = version_as_numbers(remote_version)
    lv = version_as_numbers(local_version)
    if rv==lv:
        log("identical remote version: %s", remote_version)
        return True
    if rv[:2]<=[0, 2]:
        #0.3 is the oldest version we support
        log("remote version %s is too old, sorry", remote_version)
        return  False
    if rv[0]>0:
        log("newer version %s may work, we'll see..", remote_version)
        return  True
    if (rv[1]==3 and rv[2]<8) or (rv[1]==4 and rv[2]<5) or (rv[1]==5 and rv[2]<3):
        #versions before 0.3.8, 0.4.5 and 0.5.3 have a nasty problem:
        log("remote version %s is old and broken, use the latest stable version", remote_version)
    log("local version %s should be compatible with newer remote version: %s", local_version, remote_version)
    return True

def add_version_info(props, version_prefix=""):
    props[version_prefix+"version"] = local_version
    props["python.version"] = sys.version_info[:3]
    try:
        from xpra.build_info import LOCAL_MODIFICATIONS, BUILD_DATE, BUILT_BY, BUILT_ON, BUILD_BIT, BUILD_CPU, REVISION
        props["build.local_modifications"] = LOCAL_MODIFICATIONS
        props["build.date"] = BUILD_DATE
        props["build.by"] = BUILT_BY
        props["build.on"] = BUILT_ON
        props["build.bit"] = BUILD_BIT
        props["build.cpu"] = BUILD_CPU
        props["build.revision"] = REVISION
    except:
        pass

def main():
    d = {}
    add_version_info(d)
    print("version_info=%s" % d)


if __name__ == "__main__":
    main()
