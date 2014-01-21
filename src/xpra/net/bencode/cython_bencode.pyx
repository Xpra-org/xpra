# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.

# Original version written by Petru Paler

__version__ = ("Cython", 0, 11)

import sys
assert sys.version < '3', "not ported to py3k yet"

from types import (StringType, UnicodeType, IntType, LongType, DictType, ListType,
                   TupleType, BooleanType)

cdef int unicode_support = 0
def set_unicode_support(us):
    global unicode_support
    unicode_support = bool(us)


cdef int find(const char *p, char c, int start, size_t len):
    cdef int pos = start
    while pos<len:
        if p[pos]==c:
            return pos
        pos += 1
    return -1


# Decoding functions

cdef decode_int(const char *x, int f, int l):
    f += 1
    cdef int newf = find(x, 'e', f, l)
    cdef object n
    assert newf>=0, "end of int not found"
    try:
        n = int(x[f:newf])
    except (OverflowError, ValueError):
        n = long(x[f:newf])
    if x[f] == '-':
        if x[f + 1] == '0':
            raise ValueError("-0 is not a valid number")
    elif x[f] == '0' and newf != f+1:
        raise ValueError("leading zeroes are not allowed")
    return (n, newf+1)

cdef decode_string(const char *x, int f, int l):
    cdef int colon = find(x, ':', f, l)
    cdef int slen
    assert colon>=0, "colon not found in string size header"
    try:
        slen = int(x[f:colon])
    except (OverflowError, ValueError):
        slen = long(x[f:colon])
    if x[f] == '0' and colon != f+1:
        raise ValueError("leading zeroes are not allowed (found in string length)")
    colon += 1
    return (x[colon:colon+slen], colon+slen)

cdef decode_unicode(const char *x, int f, int l):
    xs, fs = decode_string(x, f+1, l)
    return (xs.decode("utf8"), fs)

cdef decode_list(const char *x, int f, int l):
    cdef object r = []
    f += 1
    cdef object v
    while x[f] != 'e':
        v, f = decode(x, f, l, "list item")
        r.append(v)
    return (r, f + 1)

cdef decode_dict(const char *x, int f, int l):
    cdef object r = {}
    cdef object k
    cdef object v               #dict value
    f += 1
    while x[f] != 'e':
        k, f = decode(x, f, l, "dictionary key")
        v, f = decode(x, f, l, "dictionary value")
        try:
            r[k] = v
        except TypeError, e:
            raise ValueError("failed to set dictionary key %s: %s" % (k, e))
    return (r, f + 1)


#cdef const char *DIGITS = '0123456789'
cdef decode(const char *x, int f, size_t l, char *what):
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
    cdef const char *s = x
    cdef int f = 0
    cdef size_t l = len(x)
    try:
        return decode(s, f, l, "bencoded string")
    except (IndexError, KeyError):
        import traceback
        traceback.print_exc()
        raise ValueError

# Encoding functions:

cdef void encode_int(x, r) except *:
    r.extend(('i', str(x), 'e'))

cdef void encode_string(x, r) except *:
    r.extend((str(len(x)), ':', x))

cdef void encode_unicode(x, r) except *:
    global unicode_support
    x = x.encode("utf8")
    if unicode_support:
        r.extend(('u', str(len(x)), ':', x))
    else:
        encode_string(x, r)

cdef void encode_list(object x, r) except *:
    r.append('l')
    for i in x:
        encode(i, r)
    r.append('e')

cdef void encode_dict(object x, r) except *:
    r.append('d')
    for k in sorted(x.keys()):
        v = x[k]
        encode(k, r)
        encode(v, r)
    r.append('e')


cdef void encode(object v, r) except *:
    cdef object t = type(v)
    if t==IntType:
        encode_int(v, r)
    elif t==LongType:
        encode_int(v, r)
    elif t==StringType:
        encode_string(v, r)
    elif t==UnicodeType:
        encode_unicode(v, r)
    elif t==ListType:
        encode_list(v, r)
    elif t==TupleType:
        encode_list(v, r)
    elif t==DictType:
        encode_dict(v, r)
    elif t==BooleanType:
        encode_int(long(v), r)
    elif v==None:
        raise ValueError("found None value!")
    else:
        raise ValueError("unsupported type: %s" % t)

def bencode(x):
    r = []
    try:
        encode(x, r)
        return ''.join(r)
    except Exception:
        import traceback
        traceback.print_exc()
        raise ValueError("cannot encode '%s'" % x)
