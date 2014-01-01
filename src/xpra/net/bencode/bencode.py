# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.

# Original version written by Petru Paler

__version__ = ("Python", 0, 11)

import sys
if sys.version > '3':
    long = int              #@ReservedAssignment

unicode_support = False
def set_unicode_support(us):
    global unicode_support
    unicode_support = us


def decode_int(x, f):
    f += 1
    newf = x.index('e', f)
    try:
        n = int(x[f:newf])
    except (OverflowError, ValueError):
        n = long(x[f:newf])
    if x[f] == '-':
        if x[f + 1] == '0':
            raise ValueError
    elif x[f] == '0' and newf != f+1:
        raise ValueError
    return (n, newf+1)

def decode_string(x, f):
    colon = x.index(':', f)
    assert colon>=0
    try:
        n = int(x[f:colon])
    except (OverflowError, ValueError):
        n = long(x[f:colon])
    if x[f] == '0' and colon != f+1:
        raise ValueError
    colon += 1
    return (x[colon:colon+n], colon+n)

def decode_unicode(x, f):
    xs, fs = decode_string(x, f+1)
    return (xs.decode("utf8"), fs)

def decode_list(x, f):
    r, f = [], f+1
    while x[f] != 'e':
        fn = decode_func.get(x[f])
        if not fn:
            raise ValueError("invalid list entry: %s" % (x[f:]))
        v, f = fn(x, f)
        r.append(v)
    return (r, f + 1)

def decode_dict(x, f):
    r, f = {}, f+1
    #lastkey = None
    while x[f] != 'e':
        fn = decode_func.get(x[f])
        if not fn:
            raise ValueError("invalid dict key: %s" % (x[f:]))
        k, f = fn(x, f)
        #if lastkey is not None and lastkey >= k:
        #    raise ValueError("keys are not in ascending order!")
        #lastkey = k
        fn = decode_func.get(x[f])
        if not fn:
            raise ValueError("invalid dict value: %s" % (x[f:]))
        r[k], f = fn(x, f)
    return (r, f + 1)

decode_func = {}
decode_func['l'] = decode_list
decode_func['d'] = decode_dict
decode_func['i'] = decode_int
for c in '0123456789':
    decode_func[c] = decode_string
decode_func['u'] = decode_unicode
#now as byte values:
for k,v in dict(decode_func).items():
    decode_func[ord(k)] = lambda x,f : v(str(x), f)

def bdecode(x):
    try:
        fn = decode_func.get(x[0])
        if not fn:
            raise ValueError("invalid type identifier: %s" % (x[0]))
        r, l = fn(x, 0)
    except (IndexError, KeyError):
        import traceback
        traceback.print_exc()
        raise ValueError
    return r, l

def encode_int(x, r):
    # Explicit cast, because bool.__str__ is annoying.
    r.extend(('i', str(long(x)), 'e'))

def encode_string(x, r):
    r.extend((str(len(x)), ':', x))

def encode_unicode(x, r):
    global unicode_support
    x = x.encode("utf8")
    if unicode_support:
        r.extend(('u', str(len(x)), ':', x))
    else:
        encode_string(x, r)

def encode_list(x, r):
    r.append('l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append('e')

def encode_dict(x,r):
    r.append('d')
    for k, v in x.items():
        encode_func[type(k)](k, r)
        encode_func[type(v)](v, r)
    r.append('e')


encode_func = {}
if sys.version < '3':
    from types import (StringType, UnicodeType, IntType, LongType, DictType, ListType,
                       TupleType, BooleanType)
    encode_func[IntType] = encode_int
    encode_func[LongType] = encode_int
    encode_func[StringType] = encode_string
    encode_func[UnicodeType] = encode_unicode
    encode_func[ListType] = encode_list
    encode_func[TupleType] = encode_list
    encode_func[DictType] = encode_dict
    encode_func[BooleanType] = encode_int
else:
    encode_func[int] = encode_int
    encode_func[str] = encode_string
    encode_func[list] = encode_list
    encode_func[tuple] = encode_list
    encode_func[dict] = encode_dict
    encode_func[bool] = encode_int
    def encode_bytes(x, r):
        encode_string(x.decode(), r)
    encode_func[bytes] = encode_bytes

def bencode(x):
    r = []
    encode_func[type(x)](x, r)
    return ''.join(r)
