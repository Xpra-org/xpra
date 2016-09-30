#!/usr/bin/env python
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

try:
    from xpra.server.region import rectangle        #@UnresolvedImport

    R1 = rectangle(0, 0, 20, 20)
    R2 = rectangle(0, 0, 20, 20)
    R3 = rectangle(0, 0, 40, 40)
    R4 = rectangle(10, 10, 50, 50)
    R5 = rectangle(100, 100, 100, 100)
except:
    rectangle, R1, R2, R3, R4, R5 = None, None, None, None, None, None


class TestRegion(unittest.TestCase):

    def test_eq(self):
        assert R1==R2
        assert R1!=R3
        assert R2!=R3

    def test_intersection(self):
        r1 = rectangle(0, 0, 100, 100)
        r2 = rectangle(50, 50, 200, 200)
        i = r1.intersection_rect(r2)
        assert i.x==50 and i.y==50 and i.width==50 and i.height==50
        i2 = r2.intersection_rect(r1)
        assert i2==i
        r3 = rectangle(100, 100, 50, 50)
        i = r2.intersection_rect(r3)
        assert i==r3
        r4 = rectangle(0, 0, 10, 10)
        i = r3.intersection_rect(r4)
        assert i is None

    def test_contains(self):
        assert R1.contains_rect(R2)
        assert not R1.contains_rect(R3)
        assert R3.contains_rect(R1)
        assert not R1.contains_rect(R4)
        assert not R1.contains_rect(R5)

    def test_substract(self):
        #  ##########          ##########
        #  #        #          ##########
        #  #        #          ##########
        #  #        #          ##########
        #  #   ##   #    ->                + ####  +  ####  +
        #  #   ##   #                        ####     ####
        #  #        #                                          ##########
        #  #        #                                          ##########
        #  #        #                                          ##########
        #  ##########                                          ##########
        r = rectangle(0, 0, 100, 100)
        sub = rectangle(40, 40, 20, 20)
        l = r.substract_rect(sub)
        assert len(l)==4
        #verify total area has not changed:
        total = r.width*r.height
        assert total == sum([r.width*r.height for r in (l+[sub])])
        assert rectangle(0, 0, 100, 40) in l
        assert rectangle(0, 40, 40, 20) in l
        assert rectangle(0, 40, 40, 20) in l
        # at (0,0)
        # ##########
        # #        #
        # #        #
        # #        #
        # #        #         at (50, 50)
        # #        #         ##########
        # #        #         #        #
        # #        #    -    #        #
        # #        #         #        #
        # ##########         #        #
        #                    #        #
        #                    #        #
        #                    #        #
        #                    #        #
        #                    ##########
        r = rectangle(0, 0, 100, 100)
        sub = rectangle(50, 50, 100, 100)
        l = r.substract_rect(sub)
        assert len(l)==2
        assert rectangle(0, 0, 100, 50) in l
        assert rectangle(0, 50, 50, 50) in l
        assert rectangle(200, 200, 0, 0) not in l


def main():
    #skip test if import failed (ie: not a server build)
    if rectangle is not None:
        unittest.main()

if __name__ == '__main__':
    main()
