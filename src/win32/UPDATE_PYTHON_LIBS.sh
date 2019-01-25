#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#using easy-install for python libraries which are not packaged by mingw:
# currently disabled, build from patched source only: websockify
for x in lz4 nvidia-ml-py; do
    easy_install-2.7 -U -Z $x
    easy_install-3.7 -U -Z $x
done
#broken updates:
#PyOpenGL PyOpenGL_accelerate
