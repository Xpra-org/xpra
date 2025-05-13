# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.
# Original version written by Petru Paler


__version__ = ("Cython", 5, 0)


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS


import codecs
def b(x):
    if type(x)==bytes:
        return x
    return codecs.latin_1_encode(x)[0]


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
    cdef int newf = find(x, b'e', f, l)
    cdef object n
    assert newf>(<int> f), "end of int not found"
    cdef unsigned int unewf = newf
    try:
        n = int(x[f:unewf])
    except (OverflowError, ValueError):
        n = int(x[f:unewf])
    if x[f] == b'-':
        if x[f + 1] == b'0':
            raise ValueError("-0 is not a valid number")
    elif x[f] == b'0' and unewf != f+1:
        raise ValueError("leading zeroes are not allowed")
    return (n, unewf+1)

cdef decode_string(const unsigned char *x, unsigned int f, int l):
    cdef int colon = find(x, b':', f, l)
    cdef int slen
    assert colon>=(<int> f), "colon not found in string size header"
    lenstr = x[f:colon]
    cdef unsigned int ucolon = colon
    try:
        slen = int(lenstr)
    except (OverflowError, ValueError):
        try:
            slen = int(lenstr)
        except:
            raise ValueError("cannot parse length '%s' (f=%s, colon=%s, string=%s)" % (lenstr, f, ucolon, x)) from None
    if x[f] == b'0' and ucolon != f+1:
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
    while x[f] != b'e':
        v, f = decode(x, f, l, "list item")
        r.append(v)
    return (r, f + 1)

cdef decode_dict(const unsigned char *x, unsigned int f, int l):
    cdef object r = {}
    cdef object k
    cdef object v               #dict value
    f += 1
    while x[f] != b'e':
        k, f = decode(x, f, l, "dictionary key")
        v, f = decode(x, f, l, "dictionary value")
        try:
            r[k] = v
        except TypeError as e:
            raise ValueError("failed to set dictionary key %s: %s" % (k, e)) from None
    return (r, f + 1)


#cdef const char *DIGITS = '0123456789'
cdef decode(const unsigned char *x, unsigned int f, size_t l, unsigned char *what):
    if f>=l:
        raise IndexError("cannot decode past the end of the string!")
    cdef char c = x[f]
    if c==b'l':
        return decode_list(x, f, l)
    elif c==b'd':
        return decode_dict(x, f, l)
    elif c==b'i':
        return decode_int(x, f, l)
    elif c in (b'0', b'1', b'2', b'3', b'4', b'5', b'6', b'7', b'8', b'9'):
        return decode_string(x, f, l)
    elif c==b'u':
        return decode_unicode(x, f, l)
    else:
        raise ValueError("invalid %s type identifier: %s at position %s" % (what, c, f))

def bdecode(x):
    xs = b(x)
    cdef unsigned int f = 0
    cdef Py_buffer py_buf
    if PyObject_GetBuffer(xs, &py_buf, PyBUF_ANY_CONTIGUOUS):
        raise ValueError("failed to access buffer of %s" % type(xs))
    try:
        return decode(<const unsigned char*> py_buf.buf, f, py_buf.len, "bencoded string")
    except (IndexError, KeyError):
        raise ValueError(f"cannot decode string {xs!r}") from None
    finally:
        PyBuffer_Release(&py_buf)

# Encoding functions:

cdef int encode_int(x, r) except -1:
    r.extend((b'i', str(x), b'e'))
    return 0

cdef int encode_string(x, r) except -1:
    r.extend((str(len(x)), b':', x))
    return 0

cdef int encode_unicode(x, r) except -1:
    x = x.encode("utf8")
    return encode_string(x, r)

cdef int encode_list(object x, r) except -1:
    r.append(b'l')
    for i in x:
        assert encode(i, r)==0
    r.append(b'e')
    return 0

cdef int encode_dict(object x, r) except -1:
    r.append(b'd')
    for k in x.keys():
        v = x[k]
        assert encode(k, r)==0
        assert encode(v, r)==0
    r.append(b'e')
    return 0


cdef int encode(object v, r) except -1:
    cdef object t = type(v)
    if t==int:
        return encode_int(v, r)
    elif t==bytes:
        return encode_string(v, r)
    elif t==memoryview:
        return encode_string(v.tobytes(), r)
    elif t==str:
        return encode_unicode(v, r)
    elif t==list:
        return encode_list(v, r)
    elif t==tuple:
        return encode_list(v, r)
    elif t==dict:
        return encode_dict(v, r)
    elif t==bool:
        return encode_int(int(v), r)
    elif v==None:
        raise ValueError("found None value!")
    else:
        raise ValueError("unsupported type: %s, value=%s" % (t, v))

def bencode(x) -> bytes:
    r = []
    try:
        assert encode(x, r)==0
        return b''.join(b(v) for v in r)
    except Exception as e:
        raise ValueError("cannot encode '%s': %s" % (x, e)) from None
