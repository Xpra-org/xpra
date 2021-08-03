#
# rencode.pyx
#
# Copyright (C) 2010 Andrew Resch <andrewresch@gmail.com>
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
#
# rencode is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# rencode is distributed in the hope that it will be useful,
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

#cython: language_level=3

from __future__ import absolute_import

import sys

from cpython cimport bool
from libc.stdlib cimport realloc, free
from libc.string cimport memcpy

__version__ = ("Cython", 1, 0, 7)

cdef bool big_endian = sys.byteorder!="little"

cdef enum:
    # Default number of bits for serialized floats, either 32 or 64 (also a parameter for dumps()).
    DEFAULT_FLOAT_BITS = 32
    # Maximum length of integer when written as base 10 string.
    MAX_INT_LENGTH = 64
    # The bencode 'typecodes' such as i, d, etc have been extended and
    # relocated on the base-256 character set.
    CHR_BIN     = 47
    CHR_LIST    = 59
    CHR_DICT    = 60
    CHR_INT     = 61
    CHR_INT1    = 62
    CHR_INT2    = 63
    CHR_INT4    = 64
    CHR_INT8    = 65
    CHR_FLOAT32 = 66
    CHR_FLOAT64 = 44
    CHR_TRUE    = 67
    CHR_FALSE   = 68
    CHR_NONE    = 69
    CHR_TERM    = 127
    # Positive integers with value embedded in typecode.
    INT_POS_FIXED_START = 0
    INT_POS_FIXED_COUNT = 44
    # Dictionaries with length embedded in typecode.
    DICT_FIXED_START = 102
    DICT_FIXED_COUNT = 25
    # Negative integers with value embedded in typecode.
    INT_NEG_FIXED_START = 70
    INT_NEG_FIXED_COUNT = 32
    # Strings with length embedded in typecode.
    STR_FIXED_START = 128
    STR_FIXED_COUNT = 64
    # Lists with length embedded in typecode.
    LIST_FIXED_START = STR_FIXED_START+STR_FIXED_COUNT
    LIST_FIXED_COUNT = 64

cdef swap_byte_order_ushort(unsigned short *s):
    s[0] = (s[0] >> 8) | (s[0] << 8)

cdef swap_byte_order_short(char *c):
    cdef short s
    cdef char *p = <char *>&s
    p[0] = c[1]
    p[1] = c[0]
    return s

cdef swap_byte_order_uint(int *i):
    i[0] = (i[0] >> 24) | ((i[0] << 8) & 0x00FF0000) | ((i[0] >> 8) & 0x0000FF00) | (i[0] << 24)

cdef swap_byte_order_int(char *c):
    cdef int i
    cdef char *p = <char *>&i
    p[0] = c[3]
    p[1] = c[2]
    p[2] = c[1]
    p[3] = c[0]
    return i

cdef swap_byte_order_ulong_long(long long *l):
    l[0] = (l[0] >> 56) | \
           ((l[0] << 40) & 0x00FF000000000000) | \
           ((l[0] << 24) & 0x0000FF0000000000) | \
           ((l[0] << 8) & 0x000000FF00000000) | \
           ((l[0] >> 8) & 0x00000000FF000000) | \
           ((l[0] >> 24) & 0x0000000000FF0000) | \
           ((l[0] >> 40) & 0x000000000000FF00) | \
           (l[0] << 56)

cdef swap_byte_order_long_long(char *c):
    cdef long long l
    cdef char *p = <char *>&l
    p[0] = c[7]
    p[1] = c[6]
    p[2] = c[5]
    p[3] = c[4]
    p[4] = c[3]
    p[5] = c[2]
    p[6] = c[1]
    p[7] = c[0]
    return l

cdef swap_byte_order_float(char *c):
    cdef float f
    cdef char *p = <char *>&f
    p[0] = c[3]
    p[1] = c[2]
    p[2] = c[1]
    p[3] = c[0]
    return f

cdef swap_byte_order_double(char *c):
    cdef double d
    cdef char *p = <char *>&d
    p[0] = c[7]
    p[1] = c[6]
    p[2] = c[5]
    p[3] = c[4]
    p[4] = c[3]
    p[5] = c[2]
    p[6] = c[1]
    p[7] = c[0]
    return d

cdef write_buffer_char(char **buf, unsigned int *pos, char c):
    buf[0] = <char*>realloc(buf[0], pos[0] + 1)
    if buf[0] == NULL:
        raise MemoryError("Error in realloc, 1 byte needed")
    memcpy(&buf[0][pos[0]], &c, 1)
    pos[0] += 1

cdef write_buffer(char **buf, unsigned int *pos, void* data, int size):
    buf[0] = <char*>realloc(buf[0], pos[0] + size)
    if buf[0] == NULL:
        raise MemoryError("Error in realloc, %d bytes needed", size)
    memcpy(&buf[0][pos[0]], data, size)
    pos[0] += size

cdef encode_char(char **buf, unsigned int *pos, signed char x):
    if 0 <= x < INT_POS_FIXED_COUNT:
        write_buffer_char(buf, pos, INT_POS_FIXED_START + x)
    elif -INT_NEG_FIXED_COUNT <= x < 0:
        write_buffer_char(buf, pos, INT_NEG_FIXED_START - 1 - x)
    elif -128 <= x < 128:
        write_buffer_char(buf, pos, CHR_INT1)
        write_buffer_char(buf, pos, x)

cdef encode_short(char **buf, unsigned int *pos, short x):
    write_buffer_char(buf, pos, CHR_INT2)
    if not big_endian:
        if x > 0:
            swap_byte_order_ushort(<unsigned short*>&x)
        else:
            x = swap_byte_order_short(<char*>&x)
    write_buffer(buf, pos, &x, sizeof(x))

cdef encode_int(char **buf, unsigned int *pos, int x):
    write_buffer_char(buf, pos, CHR_INT4)
    if not big_endian:
        if x > 0:
            swap_byte_order_uint(&x)
        else:
            x = swap_byte_order_int(<char*>&x)
    write_buffer(buf, pos, &x, sizeof(x))

cdef encode_long_long(char **buf, unsigned int *pos, long long x):
    write_buffer_char(buf, pos, CHR_INT8)
    if not big_endian:
        if x > 0:
            swap_byte_order_ulong_long(&x)
        else:
            x = swap_byte_order_long_long(<char*>&x)
    write_buffer(buf, pos, &x, sizeof(x))

cdef encode_big_number(char **buf, unsigned int *pos, char *x):
    write_buffer_char(buf, pos, CHR_INT)
    write_buffer(buf, pos, x, len(x))
    write_buffer_char(buf, pos, CHR_TERM)

#cdef encode_float32(char **buf, unsigned int *pos, float x):
#    write_buffer_char(buf, pos, CHR_FLOAT32)
#    if not big_endian:
#        x = swap_byte_order_float(<char *>&x)
#    write_buffer(buf, pos, &x, sizeof(x))

cdef encode_float64(char **buf, unsigned int *pos, double x):
    write_buffer_char(buf, pos, CHR_FLOAT64)
    if not big_endian:
        x = swap_byte_order_double(<char *>&x)
    write_buffer(buf, pos, &x, sizeof(x))

cdef encode_bytes(char **buf, unsigned int *pos, bytes x):
    cdef char *p
    cdef int lx = len(x)
    write_buffer_char(buf, pos, CHR_BIN)
    s = b"%i:" % lx
    p = s
    write_buffer(buf, pos, p, len(s))
    write_buffer(buf, pos, <char *>x, lx)

cdef encode_str(char **buf, unsigned int *pos, bytes x):
    cdef char *p
    cdef int lx = len(x)
    if lx < STR_FIXED_COUNT:
        write_buffer_char(buf, pos, STR_FIXED_START + lx)
        write_buffer(buf, pos, <char *>x, lx)
    else:
        s = b"%i:" % lx
        p = s
        write_buffer(buf, pos, p, len(s))
        write_buffer(buf, pos, <char *>x, lx)

cdef encode_none(char **buf, unsigned int *pos):
    write_buffer_char(buf, pos, CHR_NONE)

cdef encode_bool(char **buf, unsigned int *pos, bool x):
    write_buffer_char(buf, pos, CHR_TRUE if x else CHR_FALSE)

cdef encode_list(char **buf, unsigned int *pos, x):
    if len(x) < LIST_FIXED_COUNT:
        write_buffer_char(buf, pos, LIST_FIXED_START + len(x))
        for i in x:
            encode(buf, pos, i)
    else:
        write_buffer_char(buf, pos, CHR_LIST)
        for i in x:
            encode(buf, pos, i)
        write_buffer_char(buf, pos, CHR_TERM)

cdef encode_dict(char **buf, unsigned int *pos, x):
    if len(x) < DICT_FIXED_COUNT:
        write_buffer_char(buf, pos, DICT_FIXED_START + len(x))
        for k, v in x.items():
            encode(buf, pos, k)
            encode(buf, pos, v)
    else:
        write_buffer_char(buf, pos, CHR_DICT)
        for k, v in x.items():
            encode(buf, pos, k)
            encode(buf, pos, v)
        write_buffer_char(buf, pos, CHR_TERM)

cdef object MAX_SIGNED_INT = 2**31
cdef object MIN_SIGNED_INT = -MAX_SIGNED_INT
#note: negating the Python value avoids compiler problems
#(negating the "long long" constant can make it unsigned with some compilers!)
cdef object MAX_SIGNED_LONGLONG = int(2**63)
cdef object MIN_SIGNED_LONGLONG = -MAX_SIGNED_LONGLONG

cdef encode(char **buf, unsigned int *pos, data):
    t = type(data)
    if t == int:
        if -128 <= data < 128:
            encode_char(buf, pos, data)
        elif -32768 <= data < 32768:
            encode_short(buf, pos, data)
        elif MIN_SIGNED_INT <= data < MAX_SIGNED_INT:
            encode_int(buf, pos, data)
        elif MIN_SIGNED_LONGLONG <= data < MAX_SIGNED_LONGLONG:
            encode_long_long(buf, pos, data)
        else:
            s = str(data).encode("ascii")
            if len(s) >= MAX_INT_LENGTH:
                raise ValueError("Number is longer than %d characters" % MAX_INT_LENGTH)
            encode_big_number(buf, pos, s)

    elif t == float:
        #if _float_bits == 32:
        #    encode_float32(buf, pos, data)
        encode_float64(buf, pos, data)

    elif t == bytes:
        encode_bytes(buf, pos, data)

    elif t == str:
        encode_str(buf, pos, data.encode("utf8"))

    elif t == type(None):
        encode_none(buf, pos)

    elif t == bool:
        encode_bool(buf, pos, data)

    elif t == list or t == tuple:
        encode_list(buf, pos, data)

    elif t == dict:
        encode_dict(buf, pos, data)

    else:
        raise Exception("type %s not handled" % t)


def dumps(data):
    """
    Encode the object data into a string.

    :param data: the object to encode
    :type data: object
    """
    cdef char *buf = NULL
    cdef unsigned int pos = 0
    encode(&buf, &pos, data)
    ret = buf[:pos]
    free(buf)
    return ret


cdef decode_char(char *data, unsigned int *pos, long long data_length):
    cdef signed char c
    check_pos(data, pos[0]+1, data_length)
    memcpy(&c, &data[pos[0]+1], 1)
    pos[0] += 2
    return c

cdef decode_short(char *data, unsigned int *pos, long long data_length):
    cdef short s
    check_pos(data, pos[0]+2, data_length)
    memcpy(&s, &data[pos[0]+1], 2)
    pos[0] += 3
    if not big_endian:
        s = swap_byte_order_short(<char*>&s)
    return s

cdef decode_int(char *data, unsigned int *pos, long long data_length):
    cdef int i
    check_pos(data, pos[0]+4, data_length)
    memcpy(&i, &data[pos[0]+1], 4)
    pos[0] += 5
    if not big_endian:
        i = swap_byte_order_int(<char*>&i)
    return i

cdef decode_long_long(char *data, unsigned int *pos, long long data_length):
    cdef long long l
    check_pos(data, pos[0]+8, data_length)
    memcpy(&l, &data[pos[0]+1], 8)
    pos[0] += 9
    if not big_endian:
        l = swap_byte_order_long_long(<char*>&l)
    return l

cdef decode_fixed_pos_int(char *data, unsigned int *pos):
    pos[0] += 1
    return data[pos[0] - 1] - INT_POS_FIXED_START

cdef decode_fixed_neg_int(char *data, unsigned int *pos):
    pos[0] += 1
    return (data[pos[0] - 1] - INT_NEG_FIXED_START + 1)*-1

cdef decode_big_number(char *data, unsigned int *pos, long long data_length):
    pos[0] += 1
    cdef int x = 18
    check_pos(data, pos[0]+x, data_length)
    while (data[pos[0]+x] != CHR_TERM):
        x += 1
        if x >= MAX_INT_LENGTH:
            raise ValueError(
                "Number is longer than %d characters" % MAX_INT_LENGTH)
        check_pos(data, pos[0]+x, data_length)

    big_number = int(data[pos[0]:pos[0]+x])
    pos[0] += x + 1
    return big_number

cdef decode_float32(char *data, unsigned int *pos, long long data_length):
    cdef float f
    check_pos(data, pos[0]+4, data_length)
    memcpy(&f, &data[pos[0]+1], 4)
    pos[0] += 5
    if not big_endian:
        f = swap_byte_order_float(<char*>&f)
    return f

cdef decode_float64(char *data, unsigned int *pos, long long data_length):
    cdef double d
    check_pos(data, pos[0]+8, data_length)
    memcpy(&d, &data[pos[0]+1], 8)
    pos[0] += 9
    if not big_endian:
        d = swap_byte_order_double(<char*>&d)
    return d

cdef decode_fixed_str(char *data, unsigned int *pos, long long data_length):
    cdef unsigned char size = data[pos[0]] - STR_FIXED_START + 1
    check_pos(data, pos[0] + size - 1, data_length)
    s = data[pos[0]+1:pos[0] + size]
    pos[0] += size
    return s

cdef decode_str(char *data, unsigned int *pos, long long data_length):
    cdef unsigned int x = 1
    check_pos(data, pos[0]+x, data_length)
    while (data[pos[0]+x] != 58):
        x += 1
        check_pos(data, pos[0]+x, data_length)
    cdef int size = int(data[pos[0]:pos[0]+x])
    pos[0] += x + 1
    check_pos(data, pos[0] + size - 1, data_length)
    s = data[pos[0]:pos[0] + size]
    pos[0] += size
    return s

cdef decode_bytes(char *data, unsigned int *pos, long long data_length):
    cdef unsigned int x = 1
    check_pos(data, pos[0]+x, data_length)
    while (data[pos[0]+x] != 58):
        x += 1
        check_pos(data, pos[0]+x, data_length)
    cdef int size = int(data[pos[0]+1:pos[0]+x])
    pos[0] += x + 1
    check_pos(data, pos[0] + size - 1, data_length)
    s = data[pos[0]:pos[0] + size]
    pos[0] += size
    return s

cdef decode_fixed_list(char *data, unsigned int *pos, long long data_length):
    size = <unsigned char>data[pos[0]] - LIST_FIXED_START
    pos[0] += 1
    return tuple(decode(data, pos, data_length) for _ in range(size))

cdef decode_list(char *data, unsigned int *pos, long long data_length):
    l = []
    pos[0] += 1
    while data[pos[0]] != CHR_TERM:
        l.append(decode(data, pos, data_length))
    pos[0] += 1
    return tuple(l)

cdef decode_fixed_dict(char *data, unsigned int *pos, long long data_length):
    size = <unsigned char>data[pos[0]] - DICT_FIXED_START
    pos[0] += 1
    return dict((decode(data, pos, data_length), decode(data, pos, data_length)) for _ in range(size))

cdef decode_dict(char *data, unsigned int *pos, long long data_length):
    d = {}
    pos[0] += 1
    check_pos(data, pos[0], data_length)
    while data[pos[0]] != CHR_TERM:
        d[decode(data, pos, data_length)] = decode(data, pos, data_length)
    pos[0] += 1
    return d

cdef inline check_pos(char *data, unsigned int pos, long long data_length):
    if pos >= data_length:
        raise IndexError("Tried to access data[%d] but data len is: %d" % (pos, data_length))


cdef decode(char *data, unsigned int *pos, long long data_length):
    check_pos(data, pos[0], data_length)

    cdef unsigned char typecode = data[pos[0]]
    if typecode == CHR_INT1:
        return decode_char(data, pos, data_length)
    elif typecode == CHR_INT2:
        return decode_short(data, pos, data_length)
    elif typecode == CHR_INT4:
        return decode_int(data, pos, data_length)
    elif typecode == CHR_INT8:
        return decode_long_long(data, pos, data_length)
    elif INT_POS_FIXED_START <= typecode < INT_POS_FIXED_START + INT_POS_FIXED_COUNT:
        return decode_fixed_pos_int(data, pos)
    elif INT_NEG_FIXED_START <= typecode < INT_NEG_FIXED_START + INT_NEG_FIXED_COUNT:
        return decode_fixed_neg_int(data, pos)
    elif typecode == CHR_INT:
        return decode_big_number(data, pos, data_length)
    elif typecode == CHR_FLOAT32:
        return decode_float32(data, pos, data_length)
    elif typecode == CHR_FLOAT64:
        return decode_float64(data, pos, data_length)
    elif STR_FIXED_START <= typecode < STR_FIXED_START + STR_FIXED_COUNT:
        s = decode_fixed_str(data, pos, data_length)
        return s.decode("utf8")
    elif 49 <= typecode <= 57:
        s = decode_str(data, pos, data_length)
        return s.decode("utf8")
    elif typecode == CHR_NONE:
        pos[0] += 1
        return None
    elif typecode == CHR_TRUE:
        pos[0] += 1
        return True
    elif typecode == CHR_FALSE:
        pos[0] += 1
        return False
    elif LIST_FIXED_START <= typecode < LIST_FIXED_START + LIST_FIXED_COUNT:
        return decode_fixed_list(data, pos, data_length)
    elif typecode == CHR_LIST:
        return decode_list(data, pos, data_length)
    elif typecode == CHR_BIN:
        return decode_bytes(data, pos, data_length)
    elif DICT_FIXED_START <= typecode < DICT_FIXED_START + DICT_FIXED_COUNT:
        return decode_fixed_dict(data, pos, data_length)
    elif typecode == CHR_DICT:
        return decode_dict(data, pos, data_length)

def loads(data):
    """
    Decodes the string into an object

    :param data: the string to decode
    :type data: string

    """
    cdef unsigned int pos = 0
    return decode(data, &pos, len(data))
