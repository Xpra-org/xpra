#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#using easy-install for python libraries which are not packaged by mingw:
# currently disabled, build from patched source only: websockify
# currently disabled, do not update past 1.8.x: cryptography
for x in rencode xxhash enum34 enum-compat zeroconf lz4 websocket-client comtypes PyOpenGL PyOpenGL_accelerate cffi cryptography pycparser nvidia-ml-py appdirs setproctitle netifaces pyu2f;
do
    easy_install-2.7 -U -Z $x
    easy_install-3.6 -U -Z $x
done
