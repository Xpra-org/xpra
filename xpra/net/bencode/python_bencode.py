# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.

# Original version written by Petru Paler

__version__ = (b"Python", 5, 0)

import codecs
from typing import Union, Callable, Dict, List, Any

# idiotic Python 3 unicode mess makes us reinvent the wheel again:
def strindex(s : bytes, char : str, start : int):
    i = start
    while s[i] != ord(char):
        i += 1
        if i>=len(s):
            return -1
    return i
#the values end up being ints..
def b(x) -> bytes:
    if isinstance(x, bytes):
        return x
    return codecs.latin_1_encode(x)[0]


def decode_int(x, f):
    f += 1
    newf = strindex(x, 'e', f)
    assert newf>f
    n = int(x[f:newf])
    if x[f] == ord('-'):
        if x[f + 1] == ord('0'):
            raise ValueError
    elif x[f] == ord('0') and newf != f+1:
        raise ValueError
    return (n, newf+1)

def decode_string(x, f):
    colon = strindex(x, ':', f)
    assert colon>=f
    n = int(x[f:colon])
    if x[f] == ord('0') and colon != f+1:
        raise ValueError
    colon += 1
    return (x[colon:colon+n], colon+n)

def decode_unicode(x, f):
    xs, fs = decode_string(x, f+1)
    return (xs.decode("utf8"), fs)

def decode_list(x, f):
    r, f = [], f+1
    while x[f] != ord('e'):
        fn = decode_func.get(x[f])
        if not fn:
            raise ValueError("invalid list entry: %s" % (x[f:]))
        v, f = fn(x, f)
        r.append(v)
    return (r, f + 1)

def decode_dict(x, f):
    r, f = {}, f+1
    #lastkey = None
    while x[f] != ord('e'):
        fn = decode_func.get(x[f])
        if not fn:
            raise ValueError("invalid dict key: %s" % (x[f:]))
        k, f = fn(x, f)
        fn = decode_func.get(x[f])
        if not fn:
            raise ValueError("invalid dict value: %s" % (x[f:]))
        r[k], f = fn(x, f)
    return (r, f + 1)


decode_func : Dict[Union[int, str],Callable]= {}
def add_decode(c:str, fn:Callable):
    decode_func[c] = fn
    decode_func[ord(c)] = fn
add_decode('l', decode_list)
add_decode('d', decode_dict)
add_decode('i', decode_int)
for digit in '0123456789':
    add_decode(digit, decode_string)
add_decode('u', decode_unicode)


def bdecode(x):
    try:
        xs = b(x)
        fn = decode_func.get(xs[0])
        if not fn:
            raise ValueError("invalid type identifier: %s" % (xs[0]))
        r, l = fn(xs, 0)
    except (IndexError, KeyError) as e:
        raise ValueError from e
    return r, l

def encode_int(x, r) -> None:
    # Explicit cast, because bool.__str__ is annoying.
    r.extend(('i', str(int(x)), 'e'))

def encode_memoryview(x, r) -> None:
    encode_string(x.tobytes(), r)

def encode_string(x, r) -> None:
    r.extend((str(len(x)), ':', x))

def encode_unicode(x, r) -> None:
    x = x.encode("utf8")
    encode_string(x, r)

def encode_list(x, r) -> None:
    r.append('l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append('e')

def encode_dict(x,r) -> None:
    r.append('d')
    for k in x.keys():
        v = x[k]
        encode_func[type(k)](k, r)
        encode_func[type(v)](v, r)
    r.append('e')


encode_func : Dict[type, Callable] = {
    int     : encode_int,
    str     : encode_unicode,
    list    : encode_list,
    tuple   : encode_list,
    dict    : encode_dict,
    bool    : encode_int,
    bytes   : encode_string,
    memoryview : encode_memoryview,
    }

def bencode(x) -> bytes:
    r : List[Any] = []
    encode_func[type(x)](x, r)
    return b''.join(b(v) for v in r)
