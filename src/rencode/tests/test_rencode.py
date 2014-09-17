# -*- coding: utf-8 -*-
#
# test_rencode.py
#
# Copyright (C) 2010 Andrew Resch <andrewresch@gmail.com>
#
# Deluge is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
#     The Free Software Foundation, Inc.,
#     51 Franklin Street, Fifth Floor
#     Boston, MA  02110-1301, USA.
#

import sys

import unittest
from rencode import _rencode as rencode
from rencode import rencode_orig


# Hack to deal with python 2 and 3 differences with unicode literals.
if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    unicode = str           #@ReservedAssignment
    def u(x):
        return x


class TestRencode(unittest.TestCase):
    def test_encode_fixed_pos_int(self):
        self.assertEqual(rencode.dumps(1), rencode_orig.dumps(1))
        self.assertEqual(rencode.dumps(40), rencode_orig.dumps(40))

    def test_encode_fixed_neg_int(self):
        self.assertEqual(rencode.dumps(-10), rencode_orig.dumps(-10))
        self.assertEqual(rencode.dumps(-29), rencode_orig.dumps(-29))

    def test_encode_int_char_size(self):
        self.assertEqual(rencode.dumps(100), rencode_orig.dumps(100))
        self.assertEqual(rencode.dumps(-100), rencode_orig.dumps(-100))

    def test_encode_int_short_size(self):
        self.assertEqual(rencode.dumps(27123), rencode_orig.dumps(27123))
        self.assertEqual(rencode.dumps(-27123), rencode_orig.dumps(-27123))

    def test_encode_int_int_size(self):
        self.assertEqual(rencode.dumps(7483648), rencode_orig.dumps(7483648))
        self.assertEqual(rencode.dumps(-7483648), rencode_orig.dumps(-7483648))

    def test_encode_int_long_long_size(self):
        self.assertEqual(rencode.dumps(8223372036854775808), rencode_orig.dumps(8223372036854775808))
        self.assertEqual(rencode.dumps(-8223372036854775808), rencode_orig.dumps(-8223372036854775808))

    def test_encode_int_big_number(self):
        n = int("9"*62)
        self.assertEqual(rencode.dumps(n), rencode_orig.dumps(n))
        self.assertRaises(ValueError, rencode.dumps, int("9"*65))

    def test_encode_float_32bit(self):
        self.assertEqual(rencode.dumps(1234.56), rencode_orig.dumps(1234.56))

    def test_encode_float_64bit(self):
        self.assertEqual(rencode.dumps(1234.56, 64), rencode_orig.dumps(1234.56, 64))

    def test_encode_float_invalid_size(self):
        self.assertRaises(ValueError, rencode.dumps, 1234.56, 36)

    def test_encode_fixed_str(self):
        self.assertEqual(rencode.dumps(b"foobarbaz"), rencode_orig.dumps(b"foobarbaz"))

    def test_encode_str(self):
        self.assertEqual(rencode.dumps(b"f"*255), rencode_orig.dumps(b"f"*255))
        self.assertEqual(rencode.dumps(b"\0"), rencode_orig.dumps(b"\0"))

    def test_encode_unicode(self):
        self.assertEqual(rencode.dumps(u("fööbar")), rencode_orig.dumps(u("fööbar")))

    def test_encode_none(self):
        self.assertEqual(rencode.dumps(None), rencode_orig.dumps(None))

    def test_encode_bool(self):
        self.assertEqual(rencode.dumps(True), rencode_orig.dumps(True))
        self.assertEqual(rencode.dumps(False), rencode_orig.dumps(False))

    def test_encode_fixed_list(self):
        l = [100, -234.01, b"foobar", u("bäz")]*4
        self.assertEqual(rencode.dumps(l), rencode_orig.dumps(l))

    def test_encode_list(self):
        l = [100, -234.01, b"foobar", u("bäz")]*80
        self.assertEqual(rencode.dumps(l), rencode_orig.dumps(l))

    def test_encode_fixed_dict(self):
        s = b"abcdefghijk"
        d = dict(zip(s, [1234]*len(s)))
        self.assertEqual(rencode.dumps(d), rencode_orig.dumps(d))

    def test_encode_dict(self):
        s = b"abcdefghijklmnopqrstuvwxyz1234567890"
        d = dict(zip(s, [1234]*len(s)))
        self.assertEqual(rencode.dumps(d), rencode_orig.dumps(d))

    def test_decode_fixed_pos_int(self):
        self.assertEqual(rencode.loads(rencode.dumps(10)), 10)

    def test_decode_fixed_neg_int(self):
        self.assertEqual(rencode.loads(rencode.dumps(-10)), -10)

    def test_decode_char(self):
        self.assertEqual(rencode.loads(rencode.dumps(100)), 100)
        self.assertEqual(rencode.loads(rencode.dumps(-100)), -100)

    def test_decode_short(self):
        self.assertEqual(rencode.loads(rencode.dumps(27123)), 27123)
        self.assertEqual(rencode.loads(rencode.dumps(-27123)), -27123)

    def test_decode_int(self):
        self.assertEqual(rencode.loads(rencode.dumps(7483648)), 7483648)
        self.assertEqual(rencode.loads(rencode.dumps(-7483648)), -7483648)

    def test_decode_long_long(self):
        self.assertEqual(rencode.loads(rencode.dumps(8223372036854775808)), 8223372036854775808)
        self.assertEqual(rencode.loads(rencode.dumps(-8223372036854775808)), -8223372036854775808)

    def test_decode_int_big_number(self):
        n = int(b"9"*62)
        self.assertEqual(rencode.loads(rencode.dumps(n)), n)

    def test_decode_float_32bit(self):
        f = rencode.dumps(1234.56)
        self.assertEqual(rencode.loads(f), rencode_orig.loads(f))

    def test_decode_float_64bit(self):
        f = rencode.dumps(1234.56, 64)
        self.assertEqual(rencode.loads(f), rencode_orig.loads(f))

    def test_decode_fixed_str(self):
        self.assertEqual(rencode.loads(rencode.dumps(b"foobarbaz")), b"foobarbaz")

    def test_decode_str(self):
        self.assertEqual(rencode.loads(rencode.dumps(b"f"*255)), b"f"*255)

    def test_decode_unicode(self):
        self.assertEqual(rencode.loads(rencode.dumps(u("fööbar"))), u("fööbar").encode("utf8"))

    def test_decode_none(self):
        self.assertEqual(rencode.loads(rencode.dumps(None)), None)

    def test_decode_bool(self):
        self.assertEqual(rencode.loads(rencode.dumps(True)), True)
        self.assertEqual(rencode.loads(rencode.dumps(False)), False)

    def test_decode_fixed_list(self):
        l = [100, False, b"foobar", u("bäz").encode("utf8")]*4
        self.assertEqual(rencode.loads(rencode.dumps(l)), tuple(l))

    def test_decode_list(self):
        l = [100, False, b"foobar", u("bäz").encode("utf8")]*80
        self.assertEqual(rencode.loads(rencode.dumps(l)), tuple(l))

    def test_decode_fixed_dict(self):
        s = b"abcdefghijk"
        d = dict(zip(s, [1234]*len(s)))
        self.assertEqual(rencode.loads(rencode.dumps(d)), d)

    def test_decode_dict(self):
        s = b"abcdefghijklmnopqrstuvwxyz1234567890"
        d = dict(zip(s, [b"foo"*120]*len(s)))
        d2 = {b"foo": d, b"bar": d, b"baz": d}
        self.assertEqual(rencode.loads(rencode.dumps(d2)), d2)

    def test_decode_str_bytes(self):
        b = [202, 132, 100, 114, 97, 119, 1, 0, 0, 63, 1, 242, 63]
        d = bytes(bytearray(b))
        self.assertEqual(rencode.loads(rencode.dumps(d)), d)

    def test_decode_str_nullbytes(self):
        b = (202, 132, 100, 114, 97, 119, 1, 0, 0, 63, 1, 242, 63, 1, 60, 132, 120, 50, 54, 52, 49, 51, 48, 58, 0, 0, 0, 1, 65, 154, 35, 215, 48, 204, 4, 35, 242, 3, 122, 218, 67, 192, 127, 40, 241, 127, 2, 86, 240, 63, 135, 177, 23, 119, 63, 31, 226, 248, 19, 13, 192, 111, 74, 126, 2, 15, 240, 31, 239, 48, 85, 238, 159, 155, 197, 241, 23, 119, 63, 2, 23, 245, 63, 24, 240, 86, 36, 176, 15, 187, 185, 248, 242, 255, 0, 126, 123, 141, 206, 60, 188, 1, 27, 254, 141, 169, 132, 93, 220, 252, 121, 184, 8, 31, 224, 63, 244, 226, 75, 224, 119, 135, 229, 248, 3, 243, 248, 220, 227, 203, 193, 3, 224, 127, 47, 134, 59, 5, 99, 249, 254, 35, 196, 127, 17, 252, 71, 136, 254, 35, 196, 112, 4, 177, 3, 63, 5, 220)
        d = bytes(bytearray(b))
        self.assertEqual(rencode.loads(rencode.dumps(d)), d)

    def test_decode_utf8(self):
        s = b"foobarbaz"
        #no assertIsInstance with python2.6
        d = rencode.loads(rencode.dumps(s), decode_utf8=True)
        if not isinstance(d, unicode):
            self.fail('%s is not an instance of %r' % (repr(d), unicode))
        s = rencode.dumps(b"\x56\xe4foo\xc3")
        self.assertRaises(UnicodeDecodeError, rencode.loads, s, decode_utf8=True)

    def test_version_exposed(self):
        assert rencode.__version__
        assert rencode_orig.__version__
        self.assertEqual(rencode.__version__[1:], rencode_orig.__version__[1:], "version number does not match")

if __name__ == '__main__':
    unittest.main()
