#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.packet_encoding import yaml_encode,yaml_decode

def test():
    d = [12, {'pycrypto.version': '2.6.1', 'window.resize-counter': True, 'build.version': '0.14.0'}]
    v = yaml_encode(d)
    d2 = yaml_decode(v)
    print("yaml_encode(%s)=%s" % (d, v))
    print("yaml_decode(%s)=%s" % (v, d2))
    assert d2


def main():
    test()


if __name__ == "__main__":
    main()
