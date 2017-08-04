# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.
# Original version written by Petru Paler
from __future__ import absolute_import


__version__ = ("Cython", 0, 13)

from xpra.buffers.membuf cimport object_as_buffer

import sys
if sys.version_info[0]>=3:
    StringType  = bytes
    UnicodeType = str
    IntType     = int
    LongType    = int
    DictType    = dict
    ListType    = list
    TupleType   = tuple
    BooleanType = bool
    import codecs
    def b(x):
        if type(x)==bytes:
            return x
        return codecs.latin_1_encode(x)[0]
else:
    from types import (StringType, UnicodeType, IntType, LongType, DictType, ListType,
                       TupleType, BooleanType)
    def b(x):               #@DuplicatedSignature
        return x


cdef int find(const unsigned char *p, char c, unsigned int start, size_t len):
    cdef unsigned int pos = start
    while pos<len:
        if p[pos]==c:
            return pos
        pos += 1
    return -1


# Decoding functions

cdef decode_int(const unsigned char *x, unsigned int f, int l):
    f += 1
    cdef int newf = find(x, 'e', f, l)
    cdef object n
    assert newf>=0, "end of int not found"
    cdef unsigned int unewf = newf
    try:
        n = int(x[f:unewf])
    except (OverflowError, ValueError):
        n = long(x[f:unewf])
    if x[f] == '-':
        if x[f + 1] == '0':
            raise ValueError("-0 is not a valid number")
    elif x[f] == '0' and unewf != f+1:
        raise ValueError("leading zeroes are not allowed")
    return (n, unewf+1)

cdef decode_string(const unsigned char *x, unsigned int f, int l):
    cdef int colon = find(x, ':', f, l)
    cdef int slen
    assert colon>=0, "colon not found in string size header"
    lenstr = x[f:colon]
    cdef unsigned int ucolon = colon
    try:
        slen = IntType(lenstr)
    except (OverflowError, ValueError):
        try:
            slen = LongType(lenstr)
        except:
            raise ValueError("cannot parse length '%s' (f=%s, colon=%s, string=%s)" % (lenstr, f, ucolon, x))
    if x[f] == '0' and ucolon != f+1:
        raise ValueError("leading zeroes are not allowed (found in string length)")
    ucolon += 1
    return (x[ucolon:ucolon+slen], ucolon+slen)

cdef decode_unicode(const unsigned char *x, unsigned int f, int l):
    xs, fs = decode_string(x, f+1, l)
    return (xs.decode("utf8"), fs)

cdef decode_list(const unsigned char *x, unsigned int f, int l):
    cdef object r = []
    f += 1
    cdef object v
    while x[f] != 'e':
        v, f = decode(x, f, l, "list item")
        r.append(v)
    return (r, f + 1)

cdef decode_dict(const unsigned char *x, unsigned int f, int l):
    cdef object r = {}
    cdef object k
    cdef object v               #dict value
    f += 1
    while x[f] != 'e':
        k, f = decode(x, f, l, "dictionary key")
        v, f = decode(x, f, l, "dictionary value")
        try:
            r[k] = v
        except TypeError as e:
            raise ValueError("failed to set dictionary key %s: %s" % (k, e))
    return (r, f + 1)


#cdef const char *DIGITS = '0123456789'
cdef decode(const unsigned char *x, unsigned int f, size_t l, unsigned char *what):
    assert f<l, "cannot decode past the end of the string!"
    cdef char c = x[f]
    if c=='l':
        return decode_list(x, f, l)
    elif c=='d':
        return decode_dict(x, f, l)
    elif c=='i':
        return decode_int(x, f, l)
    elif c in ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'):
        return decode_string(x, f, l)
    elif c=='u':
        return decode_unicode(x, f, l)
    else:
        raise ValueError("invalid %s type identifier: %s at position %s" % (what, c, f))

def bdecode(x):
    xs = b(x)
    cdef const unsigned char *s = NULL
    cdef Py_ssize_t l = 0
    assert object_as_buffer(xs, <const void **> &s, &l)==0, "failed to convert %s to a buffer" % type(x)
    cdef unsigned int f = 0
    try:
        return decode(s, f, l, "bencoded string")
    except (IndexError, KeyError):
        import traceback
        traceback.print_exc()
        raise ValueError

# Encoding functions:

cdef int encode_int(x, r) except -1:
    r.extend(('i', str(x), 'e'))
    return 0

cdef int encode_string(x, r) except -1:
    r.extend((str(len(x)), ':', x))
    return 0

cdef int encode_unicode(x, r) except -1:
    x = x.encode("utf8")
    return encode_string(x, r)

cdef int encode_list(object x, r) except -1:
    r.append('l')
    for i in x:
        assert encode(i, r)==0
    r.append('e')
    return 0

cdef int encode_dict(object x, r) except -1:
    r.append('d')
    for k in sorted(x.keys()):
        v = x[k]
        assert encode(k, r)==0
        assert encode(v, r)==0
    r.append('e')
    return 0


cdef int encode(object v, r) except -1:
    cdef object t = type(v)
    if t==IntType:
        return encode_int(v, r)
    elif t==LongType:
        return encode_int(v, r)
    elif t==StringType:
        return encode_string(v, r)
    elif t==UnicodeType:
        return encode_unicode(v, r)
    elif t==ListType:
        return encode_list(v, r)
    elif t==TupleType:
        return encode_list(v, r)
    elif t==DictType:
        return encode_dict(v, r)
    elif t==BooleanType:
        return encode_int(long(v), r)
    elif v==None:
        raise ValueError("found None value!")
    else:
        raise ValueError("unsupported type: %s" % t)

def bencode(x):
    r = []
    try:
        assert encode(x, r)==0
        return b''.join(b(v) for v in r)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise ValueError("cannot encode '%s': %s" % (x, e))
