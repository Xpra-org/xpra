#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AtomicInteger, MutableInteger, typedict
from xpra.util.screen import log_screen_sizes
from xpra.util.str_fn import (
    std, alnum, nonl, pver,
    obsc, csv, is_valid_hostname,
    ellipsize, repr_ellipsized, Ellipsizer,
    decode_str, nicestr,
    sort_human, sorted_nicely,
    parse_function_call,
    print_nested_dict,
)


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
            if i % 2 == 0:
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


class TestTypedict(unittest.TestCase):

    def test_typedict(self):
        d = typedict({
            b"bytekey" : b"bytevalue",
            "strkey" : "strvalue",
            "boolvalue" : True,
            "intpair" : (1, 2),
            "strtuple" : ["a", "b"],
        })
        #test all accessors:
        self.assertEqual(d.strget("strkey"), "strvalue")
        self.assertEqual(d.boolget("boolvalue"), True)
        self.assertEqual(d.intpair("intpair"), (1, 2))
        self.assertEqual(d.strtupleget("strtuple"), ("a", "b"))
        #now test defaults:
        self.assertEqual(d.boolget("invalidkey"), False)
        self.assertEqual(d.boolget("invalidkey", False), False)
        self.assertEqual(d.boolget("invalidkey", True), True)
        self.assertEqual(d.intget("invalidkey"), 0)
        self.assertEqual(d.intget("invalidkey", 1), 1)
        self.assertEqual(d.strget("invalidkey"), "")

    def _test_values_type(self, d, getter, value_types, values_allowed=()):
        for k in d.keys():
            v = getter(k)
            self.assertIsNotNone(v, "expected value for %s key '%s'" % (type(k), k))
            self.assertIn(type(v), value_types)
            if values_allowed:
                self.assertIn(v, values_allowed, "unexpected value for %s" % k)

    def test_strget(self):
        d = typedict({"bytekey"    : b"bytevalue",
                      "unicodekey" : "unicodevalue"})
        self._test_values_type(d, d.strget, [str, ])

    def test_intget(self):
        d = typedict({
            "strvalue": "1",
            "unicodekey": 2,
            "float-coercion": 3.14,
        })
        self._test_values_type(d, d.intget, [int], [1, 2, 3])

    def test_boolget(self):
        d = typedict({"empty-string-is-false"          : b"",
                      "False boolean stays as it is"   : False,
                      "zero is False"                  : 0})
        self._test_values_type(d, d.boolget, [bool], [False])
        d = typedict({"non-empty-string-is-true"       : "hello",
                      "True boolean stays as it is"    : True,
                      "non-zero number is True"        : -1})
        self._test_values_type(d, d.boolget, [bool], [True])

    def test_dictget(self):
        d = typedict({"nested": {}})
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


class TestObsc(unittest.TestCase):

    def test_obscured_by_default(self):
        from xpra.util.env import OSEnvContext
        import os
        with OSEnvContext():
            os.environ.pop("XPRA_OBSCURE_PASSWORDS", None)
            result = obsc("secret")
            self.assertEqual(result, "******")

    def test_length_preserved(self):
        from xpra.util.env import OSEnvContext
        import os
        with OSEnvContext():
            os.environ.pop("XPRA_OBSCURE_PASSWORDS", None)
            for s in ("", "a", "hello", "p@ssw0rd!"):
                self.assertEqual(len(obsc(s)), len(s))

    def test_unobscured_when_disabled(self):
        from xpra.util.env import OSEnvContext
        import os
        with OSEnvContext():
            os.environ["XPRA_OBSCURE_PASSWORDS"] = "0"
            self.assertEqual(obsc("secret"), "secret")


class TestCsv(unittest.TestCase):

    def test_strings(self):
        self.assertEqual(csv(["a", "b", "c"]), "a, b, c")

    def test_integers(self):
        self.assertEqual(csv([1, 2, 3]), "1, 2, 3")

    def test_empty(self):
        self.assertEqual(csv([]), "")

    def test_single(self):
        self.assertEqual(csv(["only"]), "only")

    def test_non_iterable_fallback(self):
        # TypeError from join → falls back to str()
        self.assertEqual(csv(42), "42")


class TestIsValidHostname(unittest.TestCase):

    def test_valid(self):
        for h in ("localhost", "example.com", "sub.domain.org", "xpra-server"):
            self.assertTrue(is_valid_hostname(h), f"{h!r} should be valid")

    def test_valid_trailing_dot(self):
        self.assertTrue(is_valid_hostname("example.com."))

    def test_too_long(self):
        self.assertFalse(is_valid_hostname("a" * 256))

    def test_label_starts_with_hyphen(self):
        self.assertFalse(is_valid_hostname("-bad.example.com"))

    def test_label_ends_with_hyphen(self):
        self.assertFalse(is_valid_hostname("bad-.example.com"))

    def test_empty_label(self):
        self.assertFalse(is_valid_hostname("double..dot.com"))


class TestEllipsize(unittest.TestCase):

    def test_short_unchanged(self):
        self.assertEqual(ellipsize("hello", 100), "hello")
        self.assertEqual(ellipsize("hello", 5), "hello")

    def test_truncated(self):
        s = "a" * 200
        result = ellipsize(s, 20)
        self.assertEqual(len(result), 20)
        self.assertIn(" .. ", result)

    def test_limit_too_small_no_ellipsis(self):
        # limit <= 6: no ellipsis applied
        self.assertEqual(ellipsize("abcdefgh", 6), "abcdefgh")

    def test_repr_ellipsized_bytes(self):
        b = b"x" * 200
        result = repr_ellipsized(b, 20)
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), 20)

    def test_repr_ellipsized_str(self):
        s = "hello world"
        result = repr_ellipsized(s, 100)
        self.assertIn("hello world", result)

    def test_repr_ellipsized_memoryview(self):
        mv = memoryview(b"hello")
        result = repr_ellipsized(mv, 100)
        self.assertIsInstance(result, str)


class TestEllipsizer(unittest.TestCase):

    def test_str_and_repr(self):
        e = Ellipsizer("hello", limit=100)
        self.assertIn("hello", str(e))
        self.assertIn("hello", repr(e))

    def test_none(self):
        e = Ellipsizer(None)
        self.assertEqual(repr(e), "None")

    def test_long_truncated(self):
        e = Ellipsizer("x" * 200, limit=20)
        self.assertEqual(len(str(e)), 20)


class TestDecodeStr(unittest.TestCase):

    def test_utf8_bytes(self):
        self.assertEqual(decode_str(b"hello"), "hello")

    def test_unicode_bytes(self):
        self.assertEqual(decode_str("café".encode("utf8")), "café")

    def test_plain_string_passthrough(self):
        self.assertEqual(decode_str("already a str"), "already a str")

    def test_latin1_fallback(self):
        # byte 0x80 is not valid utf8 but falls back gracefully
        result = decode_str(b"\x80")
        self.assertIsInstance(result, str)

    def test_alternate_encoding(self):
        self.assertEqual(decode_str("hello".encode("ascii"), "ascii"), "hello")


class TestNicestr(unittest.TestCase):

    def test_plain_string(self):
        self.assertEqual(nicestr("hello"), "hello")

    def test_integer(self):
        self.assertEqual(nicestr(42), "42")

    def test_enum_returns_value(self):
        from enum import Enum

        class Color(Enum):
            RED = "red"
        self.assertEqual(nicestr(Color.RED), "red")

    def test_int_enum(self):
        from enum import IntEnum

        class Status(IntEnum):
            OK = 0
        self.assertEqual(nicestr(Status.OK), "0")


class TestSortHuman(unittest.TestCase):

    def test_numeric_order(self):
        lst = ["item10", "item2", "item1"]
        result = sort_human(lst)
        self.assertEqual(result, ["item1", "item2", "item10"])

    def test_already_sorted(self):
        lst = ["a1", "a2", "a3"]
        self.assertEqual(sort_human(lst), ["a1", "a2", "a3"])

    def test_modifies_in_place(self):
        lst = ["b", "a"]
        returned = sort_human(lst)
        self.assertIs(returned, lst)
        self.assertEqual(lst, ["a", "b"])


class TestSortedNicely(unittest.TestCase):

    def test_numeric_order(self):
        items = ["file10.txt", "file2.txt", "file1.txt"]
        result = list(sorted_nicely(items))
        self.assertEqual(result, ["file1.txt", "file2.txt", "file10.txt"])

    def test_bytes_input(self):
        items = [b"z", b"a", b"m"]
        result = list(sorted_nicely(items))
        self.assertEqual(result, [b"a", b"m", b"z"])

    def test_does_not_modify_original(self):
        original = ["c", "a", "b"]
        items = list(original)
        sorted_nicely(items)
        self.assertEqual(items, original)


class TestParseFunctionCall(unittest.TestCase):

    def test_no_parens_returns_name_and_empty_dict(self):
        name, args = parse_function_call("myfunc")
        self.assertEqual(name, "myfunc")
        self.assertEqual(args, {})

    def test_no_args(self):
        name, args = parse_function_call("myfunc()")
        self.assertEqual(name, "myfunc")
        self.assertEqual(args, {})

    def test_single_int_arg(self):
        name, args = parse_function_call("fn(x=1)")
        self.assertEqual(name, "fn")
        self.assertEqual(args["x"], 1)

    def test_single_float_arg(self):
        name, args = parse_function_call("RandomInvert(p=0.5)")
        self.assertEqual(name, "RandomInvert")
        self.assertAlmostEqual(args["p"], 0.5)

    def test_multiple_args(self):
        name, args = parse_function_call("fn(a=1, b=2)")
        self.assertEqual(name, "fn")
        self.assertEqual(args["a"], 1)
        self.assertEqual(args["b"], 2)

    def test_string_arg(self):
        name, args = parse_function_call('fn(mode="fast")')
        self.assertEqual(args["mode"], "fast")

    def test_whitespace_around_name(self):
        name, args = parse_function_call("  fn  (x=1)")
        self.assertEqual(name, "fn")


class TestPrintNestedDict(unittest.TestCase):

    def test_flat_dict(self):
        output = []
        print_nested_dict({"key": "value"}, print_fn=output.append)
        self.assertTrue(any("key" in line for line in output))
        self.assertTrue(any("value" in line for line in output))

    def test_nested_dict(self):
        output = []
        print_nested_dict({"outer": {"inner": "val"}}, print_fn=output.append)
        combined = "\n".join(output)
        self.assertIn("outer", combined)
        self.assertIn("inner", combined)

    def test_version_key_formatting(self):
        output = []
        print_nested_dict({"version": (1, 2, 3)}, print_fn=output.append)
        combined = "\n".join(output)
        self.assertIn("1.2.3", combined)

    def test_empty_dict(self):
        output = []
        print_nested_dict({}, print_fn=output.append)
        self.assertEqual(output, [])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
