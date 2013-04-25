# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.

# Original version written by Petru Paler

import sys
if sys.version > '3':
    long = int              #@ReservedAssignment

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

def decode_list(x, f):
    r, f = [], f+1
    while x[f] != 'e':
        v, f = decode_func[x[f]](x, f)
        r.append(v)
    return (r, f + 1)

def decode_dict(x, f):
    r, f = {}, f+1
    lastkey = None
    while x[f] != 'e':
        k, f = decode_func[x[f]](x, f)
        if lastkey is not None and lastkey >= k:
            raise ValueError
        lastkey = k
        r[k], f = decode_func[x[f]](x, f)
    return (r, f + 1)

decode_func = {}
decode_func['l'] = decode_list
decode_func['d'] = decode_dict
decode_func['i'] = decode_int
for c in '0123456789':
    decode_func[c] = decode_string
#now as byte values:
for k,v in dict(decode_func).items():
    decode_func[ord(k)] = lambda x,f : v(str(x), f)

def bdecode(x):
    try:
        r, l = decode_func[x[0]](x, 0)
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

def encode_list(x, r):
    r.append('l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append('e')

def encode_dict(x,r):
    r.append('d')
    ilist = list(x.items())
    ilist.sort()
    for k, v in ilist:
        encode_func[type(k)](k, r)
        encode_func[type(v)](v, r)
    r.append('e')


encode_func = {}
if sys.version < '3':
    from types import (StringTypes, IntType, LongType, DictType, ListType,
                       TupleType, BooleanType)
    encode_func[IntType] = encode_int
    encode_func[LongType] = encode_int
    for x in StringTypes:
        encode_func[x] = encode_string
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

def bencode(x):
    r = []
    encode_func[type(x)](x, r)
    return ''.join(r)
