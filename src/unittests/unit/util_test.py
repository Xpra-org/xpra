#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AtomicInteger, MutableInteger, typedict, log_screen_sizes, updict, pver, std, alnum, nonl


class TestIntegerClasses(unittest.TestCase):

    def _test_IntegerClass(self, IntegerClass):
        a = IntegerClass()
        a.increase()
        a.decrease()
        self.assertEqual(int(a), 0)
        a.increase(10)
        self.assertEqual(int(a.get()), 10)
        a.decrease()        #9
        self.assertLess(int(a), 10)
        a.decrease(19)
        self.assertGreaterEqual(int(a), -10)
        self.assertEqual(int(IntegerClass(int(str(a)))), -10)

    def test_AtomicInteger(self):
        self._test_IntegerClass(AtomicInteger)

    def test_AtomicInteger_threading(self):
        a = AtomicInteger()
        N = 5000
        def increase():
            for _ in range(N):
                a.increase()
        def decrease():
            for _ in range(N):
                a.decrease()
        T = 20
        from threading import Thread
        threads = []
        for i in range(T):
            if i%2==0:
                target = increase
            else:
                target = decrease
            t = Thread(target=target, name=str(target))
            t.daemon = True
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_MutableInteger(self):
        self._test_IntegerClass(MutableInteger)


class TestTypeDict(unittest.TestCase):

    def test_typedict(self):
        d = typedict({
            b"bytekey" : b"bytevalue",
            "strkey" : "strvalue",
            1 : 1,
            "boolvalue" : True,
            "intpair" : (1, 2),
            "strtuple" : ["a", "b"],
            })
        v = d.rawget("bytekey")
        self.assertIsNotNone(v)
        #test all accessors:
        self.assertEqual(d.strget("strkey"), "strvalue")
        self.assertEqual(d.intget(1), 1)
        self.assertEqual(d.boolget("boolvalue"), True)
        self.assertEqual(d.intpair("intpair"), (1, 2))
        self.assertEqual(d.strtupleget("strtuple"), ("a", "b"))
        #now test defaults:
        self.assertEqual(d.boolget("invalidkey"), False)
        self.assertEqual(d.boolget("invalidkey", False), False)
        self.assertEqual(d.boolget("invalidkey", True), True)
        self.assertEqual(d.intget("invalidkey"), 0)
        self.assertEqual(d.intget("invalidkey", 1), 1)
        self.assertEqual(d.strget("invalidkey"), None)

    def _test_values_type(self, d, getter, value_types, values_allowed=()):
        for k in d.keys():
            v = getter(k)
            self.assertIsNotNone(v, "expected value for %s key '%s'" % (type(k), k))
            self.assertIn(type(v), value_types)
            if values_allowed:
                self.assertIn(v, values_allowed, "unexpected value for %s" % k)

    def test_strget(self):
        d = typedict({b"bytekey"    : b"bytevalue",
                      "unicodekey" : "unicodevalue"})
        self._test_values_type(d, d.strget, [str, ])

    def test_intget(self):
        d = typedict({b"bytekey"    : "1",
                      "unicodekey" : 2,
                      996           : 3.14})
        self._test_values_type(d, d.intget, [int], [1, 2, 3])

    def test_boolget(self):
        d = typedict({b"empty-string-is-false"          : b"",
                      b"False boolean stays as it is"   : False,
                      b"zero is False"                  : 0})
        self._test_values_type(d, d.boolget, [bool], [False])
        d = typedict({b"non-empty-string-is-true"       : "hello",
                      b"True boolean stays as it is"    : True,
                      b"non-zero number is True"        : -1})
        self._test_values_type(d, d.boolget, [bool], [True])

    def test_dictget(self):
        d = typedict({b"nested" : {}})
        self._test_values_type(d, d.dictget, [dict])

    #def intpair(self, k, default_value=None):
    #def strtupleget(self, k, default_value=[]):
    #def inttupleget(self, k, default_value=[]):
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
        self.assertEqual(d.get("d1.foo"), "bar")
        self.assertIsNone(d.get("d2"))
        updict(d, "d2", d2)
        self.assertEqual(d.get("d2.1"), 2)
        d3 = {
            "moo" : "cow",
            }
        updict(d, "d3", d3, "hat")
        self.assertEqual(d.get("d3.moo.hat"), "cow")


    def test_pver(self):
        self.assertEqual(pver(""), "")
        self.assertEqual(pver("any string"), "any string")
        self.assertEqual(pver((1, 2, 3)), "1.2.3")

    def test_std(self):
        self.assertEqual(std(""), "")
        self.assertEqual(std("abcd"), "abcd")
        self.assertEqual(std("r1"), "r1")
        for invalid in ("*", "\n", "\r"):
            self.assertEqual(std(invalid), "")
            self.assertEqual(std("a"+invalid+"b"), "ab")

    def test_alnum(self):
        self.assertEqual(alnum("!\"$%^&*()_+{}:@~\\<>?/*-"), "")
        self.assertEqual(alnum("aBcD123"), "aBcD123")

    def test_nonl(self):
        self.assertEqual(nonl("\n\r"), "\\n\\r")
        self.assertEqual(nonl("A\nB\rC"), "A\\nB\\rC")


def main():
    unittest.main()

if __name__ == '__main__':
    main()
