# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Taken from BitTorrent 3.4.2 (which is MIT-licensed), then hacked up
# further.

# Original version written by Petru Paler

__version__ = (b"Python", 4, 0)

import codecs

#idiotic py3k unicode mess makes us reinvent the wheel again:
def strindex(s, char, start):
    i = start
    while s[i] != ord(char):
        i += 1
        if i>=len(s):
            return -1
    return i
#the values end up being ints..
def b(x):
    if isinstance(x, bytes):
        return x
    return codecs.latin_1_encode(x)[0]


def decode_int(x, f):
    f += 1
    newf = strindex(x, 'e', f)
    n = int(x[f:newf])
    if x[f] == ord('-'):
        if x[f + 1] == ord('0'):
            raise ValueError
    elif x[f] == ord('0') and newf != f+1:
        raise ValueError
    return (n, newf+1)

def decode_string(x, f):
    colon = strindex(x, ':', f)
    assert colon>=0
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


decode_func = {}
decode_func['l'] = decode_list
decode_func['d'] = decode_dict
decode_func['i'] = decode_int
for c in '0123456789':
    decode_func[c] = decode_string
decode_func['u'] = decode_unicode
#now as byte values:
for dk,dv in dict(decode_func).items():
    decode_func[ord(dk)] = dv


def bdecode(x):
    try:
        xs = b(x)
        fn = decode_func.get(xs[0])
        if not fn:
            raise ValueError("invalid type identifier: %s" % (xs[0]))
        r, l = fn(xs, 0)
    except (IndexError, KeyError):
        raise ValueError
    return r, l

def encode_int(x, r):
    # Explicit cast, because bool.__str__ is annoying.
    r.extend(('i', str(int(x)), 'e'))

def encode_string(x, r):
    r.extend((str(len(x)), ':', x))

def encode_unicode(x, r):
    x = x.encode("utf8")
    encode_string(x, r)

def encode_list(x, r):
    r.append('l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append('e')

def encode_dict(x,r):
    r.append('d')
    for k in x.keys():
        v = x[k]
        encode_func[type(k)](k, r)
        encode_func[type(v)](v, r)
    r.append('e')


encode_func = {
    int     : encode_int,
    str     : encode_unicode,
    list    : encode_list,
    tuple   : encode_list,
    dict    : encode_dict,
    bool    : encode_int,
    bytes   : encode_string,
    }

def bencode(x):
    r = []
    encode_func[type(x)](x, r)
    return b''.join(b(v) for v in r)
