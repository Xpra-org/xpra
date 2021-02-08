#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct


class TestDBUSHelper(unittest.TestCase):

    def test_struct(self):
        from xpra.dbus.helper import dbus_to_native
        import dbus
        thestring = "foo"
        struct = dbus.Struct((dbus.String(thestring),), signature=None)
        v = dbus_to_native(struct)
        assert v and isinstance(v, list)
        assert v[0] == thestring

    def test_standard_types(self):
        from xpra.dbus.helper import dbus_to_native, native_to_dbus
        for v in (
            None,
            1, 10,
            {},
            {1 : 2, 3 : 4},
            {True : 1, False : 0},
            {1.5 : 1, 2.5 : 10},
            {"a" : 1, "b" : 2},
            "foo",
            1.5, 5.0,
            [4, 5, 6],
            [True, False, True],
            [1.1, 1.2, 1.3],
            ["a", "b", "c"],
            #(1, 2, 3),
            #[1, "a", 2.5],
            [],
            ):
            dbus_value = native_to_dbus(v)
            assert v is None or dbus_value is not None, "native_to_dbus(%s) is None!" % (v,)
            assert v is None or type(dbus_value)!=type(v), "native_to_dbus(%s) is the same type: %s" % (v, type(v))
            r = dbus_to_native(dbus_value)
            assert v is None or r is not None, "dbus_to_native(%s) is None!" % (r,)
            assert r==v, "value=%s (%s), got back %s (%s)" % (v, type(v), r, type(r))

    def test_unhandled_types(self):
        from xpra.dbus.helper import dbus_to_native, native_to_dbus
        o = AdHocStruct()
        r = dbus_to_native(o)
        assert r==o and type(r)==type(o), "%s (%s) got converted to %s (%s)" % (o, type(o), r, type(r))
        r = native_to_dbus(o)
        #we don't know what else to do,
        #so we convert to a string:
        assert r==str(o)


def main():
    from xpra.os_util import WIN32
    if not WIN32:
        unittest.main()

if __name__ == '__main__':
    main()
