# -*- coding: utf-8 -*-
#
# timetest.py
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

from rencode import _rencode as rencode
from rencode import rencode_orig

import sys
# Hack to deal with python 2 and 3 differences with unicode literals.
if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    unicode = str           #@ReservedAssignment
    def u(x):
        return x

# Encode functions

def test_encode_fixed_pos_int():
    rencode.dumps(40)

def test_encode_fixed_pos_int_orig():
    rencode_orig.dumps(40)

def test_encode_fixed_neg_int():
    rencode.dumps(-29)

def test_encode_fixed_neg_int_orig():
    rencode_orig.dumps(-29)

def test_encode_int_char_size():
    rencode.dumps(100)
    rencode.dumps(-100)

def test_encode_int_char_size_orig():
    rencode_orig.dumps(100)
    rencode_orig.dumps(-100)

def test_encode_int_short_size():
    rencode.dumps(27123)
    rencode.dumps(-27123)

def test_encode_int_short_size_orig():
    rencode_orig.dumps(27123)
    rencode_orig.dumps(-27123)

def test_encode_int_int_size():
    rencode.dumps(7483648)
    rencode.dumps(-7483648)

def test_encode_int_int_size_orig():
    rencode_orig.dumps(7483648)
    rencode_orig.dumps(-7483648)

def test_encode_int_long_long_size():
    rencode.dumps(8223372036854775808)
    rencode.dumps(-8223372036854775808)

def test_encode_int_long_long_size_orig():
    rencode_orig.dumps(8223372036854775808)
    rencode_orig.dumps(-8223372036854775808)

bn = int("9"*62)
def test_encode_int_big_number():
    rencode.dumps(bn)

def test_encode_int_big_number_orig():
    rencode_orig.dumps(bn)

def test_encode_float_32bit():
    rencode.dumps(1234.56)

def test_encode_float_32bit_orig():
    rencode_orig.dumps(1234.56)

def test_encode_float_64bit():
    rencode.dumps(1234.56, 64)

def test_encode_float_64bit_orig():
    rencode_orig.dumps(1234.56, 64)

def test_encode_fixed_str():
    rencode.dumps(b"foobarbaz")

def test_encode_fixed_str_orig():
    rencode_orig.dumps(b"foobarbaz")

s = b"f"*255
def test_encode_str():
    rencode.dumps(s)

def test_encode_str_orig():
    rencode_orig.dumps(s)

def test_encode_none():
    rencode.dumps(None)

def test_encode_none_orig():
    rencode_orig.dumps(None)

def test_encode_bool():
    rencode.dumps(True)

def test_encode_bool_orig():
    rencode_orig.dumps(True)

l = [None, None, None, None]
def test_encode_fixed_list():
    rencode.dumps(l)

def test_encode_fixed_list_orig():
    rencode_orig.dumps(l)

ll = [None]*80
def test_encode_list():
    rencode.dumps(ll)

def test_encode_list_orig():
    rencode_orig.dumps(ll)

keys = b"abcdefghijk"
d = dict(zip(keys, [None]*len(keys)))

def test_encode_fixed_dict():
    rencode.dumps(d)

def test_encode_fixed_dict_orig():
    rencode_orig.dumps(d)

keys2 = b"abcdefghijklmnopqrstuvwxyz1234567890"
d2 = dict(zip(keys2, [None]*len(keys2)))

def test_encode_dict():
    rencode.dumps(d2)

def test_encode_dict_orig():
    rencode_orig.dumps(d2)


# Decode functions

def test_decode_fixed_pos_int():
    rencode.loads(b'(')

def test_decode_fixed_pos_int_orig():
    rencode_orig.loads(b'(')

def test_decode_fixed_neg_int():
    rencode.loads(b'b')

def test_decode_fixed_neg_int_orig():
    rencode_orig.loads(b'b')

def test_decode_int_char_size():
    rencode.loads(b'>d')
    rencode.loads(b'>\x9c')

def test_decode_int_char_size_orig():
    rencode_orig.loads(b'>d')
    rencode_orig.loads(b'>\x9c')

def test_decode_int_short_size():
    rencode.loads(b'?i\xf3')
    rencode.loads(b'?\x96\r')

def test_decode_int_short_size_orig():
    rencode_orig.loads(b'?i\xf3')
    rencode_orig.loads(b'?\x96\r')

def test_decode_int_int_size():
    rencode.loads(b'@\x00r1\x00')
    rencode.loads(b'@\xff\x8d\xcf\x00')

def test_decode_int_int_size_orig():
    rencode_orig.loads(b'@\x00r1\x00')
    rencode_orig.loads(b'@\xff\x8d\xcf\x00')

def test_decode_int_long_long_size():
    rencode.loads(b'Ar\x1fILX\x9c\x00\x00')
    rencode.loads(b'A\x8d\xe0\xb6\xb3\xa7d\x00\x00')

def test_decode_int_long_long_size_orig():
    rencode_orig.loads(b'Ar\x1fILX\x9c\x00\x00')
    rencode_orig.loads(b'A\x8d\xe0\xb6\xb3\xa7d\x00\x00')

def test_decode_int_big_number():
    rencode.loads(b'=99999999999999999999999999999999999999999999999999999999999999\x7f')

def test_decode_int_big_number_orig():
    rencode_orig.loads(b'=99999999999999999999999999999999999999999999999999999999999999\x7f')

def test_decode_float_32bit():
    rencode.loads(b'BD\x9aQ\xec')

def test_decode_float_32bit_orig():
    rencode_orig.loads(b'BD\x9aQ\xec')

def test_decode_float_64bit():
    rencode.loads(b',@\x93J=p\xa3\xd7\n')

def test_decode_float_64bit_orig():
    rencode_orig.loads(b',@\x93J=p\xa3\xd7\n')

def test_decode_fixed_str():
    rencode.loads(b'\x89foobarbaz')

def test_decode_fixed_str_orig():
    rencode_orig.loads(b'\x89foobarbaz')

def test_decode_str():
    rencode.loads(b'255:fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff')

def test_decode_str_orig():
    rencode_orig.loads(b'255:fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff')

def test_decode_none():
    rencode.loads(b'E')

def test_decode_none_orig():
    rencode_orig.loads(b'E')

def test_decode_bool():
    rencode.loads(b'C')

def test_decode_bool_orig():
    rencode_orig.loads(b'C')

def test_decode_fixed_list():
    rencode.loads(b'\xc4EEEE')

def test_decode_fixed_list_orig():
    rencode_orig.loads(b'\xc4EEEE')

def test_decode_list():
    rencode.loads(b';EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE\x7f')

def test_decode_list_orig():
    rencode_orig.loads(b';EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE\x7f')

def test_decode_fixed_dict():
    rencode.loads(b'q\x81aE\x81cE\x81bE\x81eE\x81dE\x81gE\x81fE\x81iE\x81hE\x81kE\x81jE')

def test_decode_fixed_dict_orig():
    rencode_orig.loads(b'q\x81aE\x81cE\x81bE\x81eE\x81dE\x81gE\x81fE\x81iE\x81hE\x81kE\x81jE')

def test_decode_dict():
    rencode.loads(b'<\x811E\x810E\x813E\x812E\x815E\x814E\x817E\x816E\x819E\x818E\x81aE\x81cE\x81bE\x81eE\x81dE\x81gE\x81fE\x81iE\x81hE\x81kE\x81jE\x81mE\x81lE\x81oE\x81nE\x81qE\x81pE\x81sE\x81rE\x81uE\x81tE\x81wE\x81vE\x81yE\x81xE\x81zE\x7f')

def test_decode_dict_orig():
    rencode_orig.loads(b'<\x811E\x810E\x813E\x812E\x815E\x814E\x817E\x816E\x819E\x818E\x81aE\x81cE\x81bE\x81eE\x81dE\x81gE\x81fE\x81iE\x81hE\x81kE\x81jE\x81mE\x81lE\x81oE\x81nE\x81qE\x81pE\x81sE\x81rE\x81uE\x81tE\x81wE\x81vE\x81yE\x81xE\x81zE\x7f')


overall = [
    b"5ce750f0954ce1537676c7a5fe38b0de30ba7eb65ce750f0954ce1537676c7a5fe38b0de30ba7eb6",
    b"fixedlength",
    u("unicodestring"),
    u("5ce750f0954ce1537676c7a5fe38b0de30ba7eb65ce750f0954ce1537676c7a5fe38b0de30ba7eb6"),
    -10,
    10,
    120,
    15600,
    -15600,
    7483648,
    -7483648,
    8223372036854775808,
    -8223372036854775808,
    int("9"*62),
    1227688834.643409,
    None,
    True
]

def test_overall_encode():
    rencode.dumps(overall)

def test_overall_encode_orig():
    rencode_orig.dumps(overall)

overall_decode_str = rencode_orig.dumps(overall)

def test_overall_decode():
    rencode.loads(overall_decode_str)

def test_overall_decode_orig():
    rencode_orig.loads(overall_decode_str)


if __name__ == "__main__":
    import timeit

    iterations = 10000
    # ANSI escape codes
    CSI="\x1B["
    reset=CSI+"m"

    def do_test(func):
        print("%s:" % func)
        new_time = timeit.Timer("%s()" % func, "from __main__ import %s" % func).timeit(iterations)
        orig_time = timeit.Timer("%s_orig()" % func, "from __main__ import %s_orig" % func).timeit(iterations)
        if new_time > orig_time:
            new = CSI + "31m%.3fs%s" % (new_time, reset)
            orig = CSI + "32m%.3fs%s (%s34m+%.3fs%s) %.2f%%" % (orig_time, reset, CSI, new_time-orig_time, reset, (new_time/orig_time)*100)
        else:
            new = CSI + "32m%.3fs%s (%s34m+%.3fs%s) %.2f%%" % (new_time, reset, CSI, orig_time-new_time, reset, (orig_time/new_time)*100)
            orig = CSI + "31m%.3fs%s" % (orig_time, reset)

        print("\trencode.pyx: %s" % new)
        print("\trencode.py:  %s" % orig)
        print("")
        return (new_time, orig_time)

    if len(sys.argv) == 1:
        loc = list(locals().keys())

        for t in ("encode", "decode", "overall"):
            print("*" * 79)
            print("%s functions:" % (t.title()))
            print("*" * 79)
            print("")

            total_new = 0.0
            total_orig = 0.0
            for func in loc:
                if func.startswith("test_%s" % t) and not func.endswith("_orig"):
                    n, o = do_test(func)
                    total_new += n
                    total_orig += o

            print("%s functions totals:" % (t.title()))
            if total_new > total_orig:
                new = CSI + "31m%.3fs%s" % (total_new, reset)
                orig = "%s32m%.3fs%s (%s34m+%.3fs%s) %.2f%%" % (CSI, total_orig, reset, CSI, total_new-total_orig, reset, (total_new/total_orig)*100)
            else:
                new = "%s32m%.3fs%s (%s34m+%.3fs%s) %.2f%%" % (CSI, total_new, reset, CSI, total_orig-total_new, reset, (total_orig/total_new)*100)
                orig = CSI + "31m%.3fs%s" % (total_orig, reset)

            print("\trencode.pyx: %s" % new)
            print("\trencode.py:  %s" % orig)
            print("")
    else:
        for f in sys.argv[1:]:
            do_test(f)
