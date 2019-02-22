# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import WIN32
from xpra.simple_stats import std_unit
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("mmap")


class MMAP_Connection(StubSourceMixin):

    def __init__(self):
        self.supports_mmap = False
        self.mmap_filename = None
        self.min_mmap_size = 0

    def init_from(self, _protocol, server):
        self.supports_mmap = server.supports_mmap
        self.mmap_filename = server.mmap_filename
        self.min_mmap_size = server.min_mmap_size

    def init_state(self):
        self.mmap = None
        self.mmap_size = 0
        self.mmap_client_token = None                   #the token we write that the client may check
        self.mmap_client_token_index = 512
        self.mmap_client_token_bytes = 0
        self.mmap_client_namespace = False

    def cleanup(self):
        mmap = self.mmap
        if mmap:
            self.mmap = None
            self.mmap_size = 0
            mmap.close()


    def parse_client_caps(self, c):
        self.mmap_client_namespace = c.boolget("mmap.namespace", False)
        sep = "." if self.mmap_client_namespace else "_"
        def mmapattr(k):
            return "mmap%s%s" % (sep, k)
        mmap_filename = c.strget(mmapattr("file"))
        if not mmap_filename:
            return
        mmap_size = c.intget(mmapattr("size"), 0)
        log("client supplied mmap_file=%s", mmap_filename)
        mmap_token = c.intget(mmapattr("token"))
        log("mmap supported=%s, token=%s", self.supports_mmap, mmap_token)
        if self.mmap_filename:
            log("using global server specified mmap file path: '%s'", self.mmap_filename)
            mmap_filename = self.mmap_filename
        if not self.supports_mmap:
            log("client enabled mmap but mmap mode is not supported", mmap_filename)
        elif WIN32 and mmap_filename.startswith("/"):
            log("mmap_file '%s' is a unix path", mmap_filename)
        elif not os.path.exists(mmap_filename):
            log("mmap_file '%s' cannot be found!", mmap_filename)
        else:
            from xpra.net.mmap_pipe import (
                init_server_mmap,
                read_mmap_token,
                write_mmap_token,
                DEFAULT_TOKEN_INDEX, DEFAULT_TOKEN_BYTES,
                )
            self.mmap, self.mmap_size = init_server_mmap(mmap_filename, mmap_size)
            log("found client mmap area: %s, %i bytes - min mmap size=%i",
                self.mmap, self.mmap_size, self.min_mmap_size)
            if self.mmap_size>0:
                index = c.intget(mmapattr("token_index"), DEFAULT_TOKEN_INDEX)
                count = c.intget(mmapattr("token_bytes"), DEFAULT_TOKEN_BYTES)
                v = read_mmap_token(self.mmap, index, count)
                log("mmap_token=%#x, verification=%#x", mmap_token, v)
                if v!=mmap_token:
                    log.warn("Warning: mmap token verification failed, not using mmap area!")
                    log.warn(" expected '%#x', found '%#x'", mmap_token, v)
                    self.mmap.close()
                    self.mmap = None
                    self.mmap_size = 0
                elif self.mmap_size<self.min_mmap_size:
                    log.warn("Warning: client supplied mmap area is too small, discarding it")
                    log.warn(" we need at least %iMB and this area is %iMB",
                             self.min_mmap_size//1024//1024, self.mmap_size//1024//1024)
                    self.mmap.close()
                    self.mmap = None
                    self.mmap_size = 0
                else:
                    from xpra.os_util import get_int_uuid
                    self.mmap_client_token = get_int_uuid()
                    self.mmap_client_token_bytes = DEFAULT_TOKEN_BYTES
                    if c.intget("mmap_token_index"):
                        #we can write the token anywhere we want and tell the client,
                        #so write it right at the end:
                        self.mmap_client_token_index = self.mmap_size-self.mmap_client_token_bytes
                    else:
                        #use the expected default for older versions:
                        self.mmap_client_token_index = DEFAULT_TOKEN_INDEX
                    write_mmap_token(self.mmap,
                                     self.mmap_client_token,
                                     self.mmap_client_token_index,
                                     self.mmap_client_token_bytes)
        if self.mmap_size>0:
            log.info(" mmap is enabled using %sB area in %s", std_unit(self.mmap_size, unit=1024), mmap_filename)

    def get_caps(self):
        caps = {"mmap_enabled" : self.mmap_size>0}
        if self.mmap_client_token:
            sep = "." if self.mmap_client_namespace else "_"
            def mmapattr(name, value):
                caps["mmap%s%s" % (sep, name)] = value
            mmapattr("token",       self.mmap_client_token)
            mmapattr("token_index", self.mmap_client_token_index)
            mmapattr("token_bytes", self.mmap_client_token_bytes)
        return caps

    def get_info(self):
        return {
            "mmap" : {
                "supported"     : self.supports_mmap,
                "enabled"       : self.mmap is not None,
                "size"          : self.mmap_size,
                "filename"      : self.mmap_filename or "",
                },
            }
