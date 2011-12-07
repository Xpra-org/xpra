# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra import __version__ as local_version

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
    if rv[:3]==[0, 0, 7]:
        log("local version %s is compatible with remote version 0.0.7.x: %s", local_version, remote_version)
        return True
    if rv[:2]==[0, 1]:
        log("local version %s is compatible with remote version 0.1.x: %s", local_version, remote_version)
        return True
    log.error("local version %s is not compatible with remote version %s", local_version, remote_version)
    return False
