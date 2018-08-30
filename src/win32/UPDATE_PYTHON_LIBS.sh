#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#using easy-install for python libraries which are not packaged by mingw:
# currently disabled, build from patched source only: websockify
export SODIUM_INSTALL=system
for x in rencode lz4 websocket-client netifaces comtypes PyOpenGL PyOpenGL_accelerate websockify nvidia-ml-py setproctitle pyu2f python-ldap ldap3 bcrypt pynacl paramiko; do
    easy_install-2.7 -U -Z $x
    easy_install-3.7 -U -Z $x
done
#locked at 0.19.1 for python2:
easy_install-3.7 -U -Z zeroconf
