# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

def set_prgname(name):
    try:
        import glib
        glib.set_prgname(name)
    except:
        pass


NAME_SET = False
def set_application_name(name):
    global NAME_SET
    if NAME_SET:
        return
    NAME_SET = True
    from xpra.log import Logger
    log = Logger()
    if sys.version_info[:2]<(2,5):
        log.warn("Python %s is too old!", sys.version_info)
        return
    try:
        import glib
        glib.set_application_name(name or "Xpra")
    except ImportError, e:
        log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)


try:
    if os.environ.get("XPRA_TEST_UUID_WRAPPER", "0")=="1":
        raise ImportError("testing uuidgen codepath")
    import uuid

    def get_hex_uuid():
        return uuid.uuid4().hex

    def get_int_uuid():
        return uuid.uuid4().int

except ImportError:
    #fallback to using the 'uuidgen' command:
    def get_hex_uuid():
        from commands import getstatusoutput
        s, o = getstatusoutput('uuidgen')
        if s!=0:
            raise Exception("no uuid module and 'uuidgen' failed!")
        return o.replace("-", "")

    def get_int_uuid():
        hex_uuid = get_hex_uuid()
        return int(hex_uuid, 16)


def get_machine_id():
    v = u""
    for filename in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        if os.path.exists(filename) and os.path.isfile(filename):
            f = None
            try:
                try:
                    f = open(filename, 'rb', 'utf-8')
                    v = f.read()
                    break
                finally:
                    if f:
                        f.close()
            except:
                pass
    return  v
