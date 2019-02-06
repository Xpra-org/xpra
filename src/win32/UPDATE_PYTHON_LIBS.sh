#!/bin/bash
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#using easy-install for python libraries which are not yet packaged by mingw:
for x in nvidia-ml-py; do
    easy_install-2.7 -U -Z $x
    easy_install-3.7 -U -Z $x
done
