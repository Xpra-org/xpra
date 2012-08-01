# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra import __version__ as local_version
import sys

from wimpiggy.log import Logger
log = Logger()

def version_as_numbers(version):
    return [int(x) for x in version.split(".")]

def is_compatible_with(remote_version):
    rv = version_as_numbers(remote_version)
    lv = version_as_numbers(local_version)
    if rv==lv:
        log("identical remote version: %s", remote_version)
        return True
    if rv[:2]<[0, 3]:
        log("remote version %s is too old, sorry", remote_version)
        return  False
    if rv[0]==0:
        log("local version %s should be compatible with newer remote version: %s", local_version, remote_version)
        return True
    log.error("local version %s is not compatible with remote version %s", local_version, remote_version)

def add_version_info(props):
    props["version"] = local_version
    props["python_version"] = sys.version_info[:3]
    try:
        from xpra.build_info import LOCAL_MODIFICATIONS, BUILD_DATE, BUILT_BY, BUILT_ON, BUILD_BIT, BUILD_CPU, REVISION
        props["local_modifications"] = LOCAL_MODIFICATIONS
        props["build_date"] = BUILD_DATE
        props["built_by"] = BUILT_BY
        props["built_on"] = BUILT_ON
        props["build_bit"] = BUILD_BIT
        props["build_cpu"] = BUILD_CPU
        props["revision"] = REVISION
    except:
        pass

def add_gtk_version_info(props, gtk):
        if hasattr(gtk, "pygtk_version"):
            props["pygtk_version"] = gtk.pygtk_version
        if hasattr(gtk, "gtk_version"):
            props["gtk_version"] = gtk.gtk_version

def main():
    d = {}
    add_version_info(d)
    print("version_info=%s" % d)

if __name__ == "__main__":
    main()
