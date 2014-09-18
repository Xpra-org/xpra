#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest

from xpra.util import AtomicInteger, MutableInteger, typedict, log_screen_sizes, updict, pver, std, alnum, nonl, xor

if sys.version > '3':
    unicode = str           #@ReservedAssignment


class TestIntegerClasses(unittest.TestCase):

    def _test_IntegerClass(self, IntegerClass):
        a = IntegerClass()
        a.increase()
        a.decrease()
        self.assertEquals(a, 0)
        a.increase(10)
        self.assertEquals(a.get(), 10)
        a.decrease()        #9
        self.assertLess(a, 10)
        a.decrease(19)
        self.assertGreaterEqual(a, -10)
        self.assertEquals(IntegerClass(int(str(a))), -10)

    def test_AtomicInteger(self):
        self._test_IntegerClass(AtomicInteger)
        #TODO: test lock with threading

    def test_MutableInteger(self):
        self._test_IntegerClass(MutableInteger)


class TestTypeDict(unittest.TestCase):

    def test_typedict(self):
        d = typedict({b"bytekey" : b"bytevalue"})
        v = d.capsget("bytekey")
        self.assertIsNotNone(v)
        #self.assertEquals(type(v), str)
        #TODO: more!

    def _test_values_type(self, d, getter, value_types, values_allowed=[]):
        for k in d.keys():
            v = getter(k)
            self.assertIsNotNone(v)
            self.assertIn(type(v), value_types)
            if values_allowed:
                self.assertIn(v, values_allowed)

    def test_strget(self):
        d = typedict({b"bytekey"    : b"bytevalue",
                      u"unicodekey" : u"unicodevalue"})
        self._test_values_type(d, d.strget, [str, unicode])

    def test_intget(self):
        d = typedict({b"bytekey"    : b"1",
                      u"unicodekey" : 2,
                      996           : 3.14})
        self._test_values_type(d, d.intget, [int], [1, 2, 3])

    def test_boolget(self):
        d = typedict({"empty-string-is-false"       : "",
                      "False boolean stays as it is": False,
                      "zero is False"               : 0})
        self._test_values_type(d, d.boolget, [bool], [False])
        d = typedict({"non-empty-string-is-true"    : "hello",
                      "True boolean stays as it is" : True,
                      "non-zero number is True"     : -1})
        self._test_values_type(d, d.boolget, [bool], [True])

    def test_dictget(self):
        d = typedict({"nested" : {}})
        self._test_values_type(d, d.dictget, [dict])

    #def intpair(self, k, default_value=None):
    #def strlistget(self, k, default_value=[]):
    #def intlistget(self, k, default_value=[]):
    #def listget(self, k, default_value=[], item_type=None, max_items=None):


class TestModuleFunctions(unittest.TestCase):

    def test_log_screen_sizes(self):
        #whatever you throw at it, it should continue:
        log_screen_sizes(0, 0, None)
        log_screen_sizes(None, object(), ["invalid"])

    def test_updict(self):
        d1 = {"foo"      : "bar"}
        d2 = {"hello"   : "world",
              1         : 2}
        d = {}
        updict(d, "d1", d1)
        self.assertEquals(d.get("d1.foo"), "bar")
        self.assertIsNone(d.get("d2"))
        updict(d, "d2", d2)
        self.assertEquals(d.get("d2.1"), 2)
        #TODO: test suffix stuff

    def test_pver(self):
        self.assertEquals(pver(""), "")
        self.assertEquals(pver("any string"), "any string")
        self.assertEquals(pver((1, 2, 3)), "1.2.3")

    def test_std(self):
        self.assertEquals(std(""), "")
        self.assertEquals(std("abcd"), "abcd")
        self.assertEquals(std("r1"), "r1")
        for invalid in ("*", "\n", "\r"):
            self.assertEquals(std(invalid), "")
            self.assertEquals(std("a"+invalid+"b"), "ab")

    def test_alnum(self):
        self.assertEquals(alnum("!\"$%^&*()_+{}:@~\\<>?/*-"), "")
        self.assertEquals(alnum("aBcD123"), "aBcD123")

    def test_nonl(self):
        self.assertEquals(nonl("\n\r"), "\\n\\r")
        self.assertEquals(nonl("A\nB\rC"), "A\\nB\\rC")

    def test_xor(self):
        self.assertEqual(xor("A", "a"), xor("B", "b"))


def main():
    unittest.main()

if __name__ == '__main__':
    main()
