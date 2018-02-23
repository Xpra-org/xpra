# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.scripts.config import parse_bool
from xpra.server.mixins.stub_server_mixin import StubServerMixin


"""
Mixin for servers that can handle mmap transfers
"""
class MMAP_Server(StubServerMixin):

    def __init__(self):
        self.supports_mmap = False
        self.mmap_filename = None
        self.min_mmap_size = 64*1024*1024

    def init(self, opts):
        if opts.mmap and os.path.isabs(opts.mmap):
            self.supports_mmap = True
            self.mmap_filename = opts.mmap
        else:
            self.supports_mmap = bool(parse_bool("mmap", opts.mmap.lower()))


    def get_info(self, _proto=None):
        return {
            "mmap" : {
                "supported"     : self.supports_mmap,
                "filename"      : self.mmap_filename or "",
                },
            }
