#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
import unittest
import binascii

from xpra.util import AdHocStruct
from xpra.os_util import OSEnvContext, hexstr


class XSettingsTest(unittest.TestCase):

    def test_xsettings(self):
        from xpra.x11.xsettings_prop import (
            get_settings, set_settings,
            get_local_byteorder,
            XSettingsTypeInteger, XSettingsTypeString, XSettingsTypeColor,
            )
        disp = AdHocStruct()
        for DEBUG_XSETTINGS in (True, False):
            with OSEnvContext():
                os.environ["XPRA_XSETTINGS_DEBUG"] = str(int(DEBUG_XSETTINGS))
                serial = 1
                data = b""
                l = len(data)
                v = struct.pack(b"=BBBBII", get_local_byteorder(), 0, 0, 0, serial, l)+data+b"\0"
                v1 = get_settings(disp, v)
                assert v
                #get from cache:
                v2 = get_settings(disp, v)
                assert v1==v2

                #test all types, set then get:
                #setting_type, prop_name, value, last_change_serial = setting
                settings = (
                    (XSettingsTypeInteger, "int1", 1, 0),
                    (XSettingsTypeString, "str1", "1", 0),
                    (XSettingsTypeColor, "color1", (128, 128, 64, 32), 0),
                    )
                serial = 2
                data = set_settings(disp, (serial, settings))
                assert data
                #parse it back:
                v = get_settings(disp, data)
                rserial, rsettings = v
                assert rserial==serial
                assert len(rsettings)==len(settings)
        #test error handling:
        for settings in (
            (
                #invalid color causes exception
                (XSettingsTypeColor, "bad-color", (128, ), 0),
            ),
            (
                #invalid setting type is skipped with an error message:
                (255, "invalid-setting-type", 0, 0),
            ),
            ):
            serial = 3
            data = set_settings(disp, (serial, settings))
            assert data
            v = get_settings(disp, data)
            rserial, rsettings = v
            assert rserial==serial
            assert len(rsettings)==0
        #parsing an invalid data type (9) should fail:
        hexdata = b"000000000200000001000000090004007374723100000000010000003100000000"
        data = binascii.unhexlify(hexdata)
        v = get_settings(disp, data)
        rserial, rsettings = v
        assert len(rsettings)==0


def main():
    #can only work with an X11 server
    from xpra.os_util import OSX, POSIX
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
