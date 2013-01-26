# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections import deque

class mdeque(deque):
    """
        Simple wrapper around deque so append() and appendleft()
        honour the maxlen.
        Nothing else, this is not a full implementation of maxlen!
    """
    def __init__(self, maxlen):
        deque.__init__(self)
        self._maxlen = maxlen

    def append(self, item):
        while len(self)>self._maxlen:
            self.popleft()
        deque.append(self, item)

    def appendleft(self, item):
        while len(self)>self._maxlen:
            self.pop()
        deque.appendleft(self, item)

def maxdeque(maxlen):
    if sys.version_info < (2, 6):
        return mdeque(maxlen)
    else:
        return deque(maxlen=maxlen)
