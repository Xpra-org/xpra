The rencode module is similar to bencode from the BitTorrent? project. For 
complex, heterogeneous data structures with many small elements, r-encodings 
take up significantly less space than b-encodings:

>>> len(rencode.dumps({'a':0, 'b':[1,2], 'c':99}))
13

>>> len(bencode.bencode({'a':0, 'b':[1,2], 'c':99}))
26

This version of rencode is a complete rewrite in Cython to attempt to increase 
the performance over the pure Python module written by Petru Paler, 
Connelly Barnes et al.

Author: Andrew Resch <andrewresch@gmail.com>
Website: http://code.google.com/p/rencode/

See COPYING for license information.
