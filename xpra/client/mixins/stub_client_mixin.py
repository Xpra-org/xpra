# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time

from xpra.util import typedict


class StubClientMixin(object):

    __signals__ = {}
    def __init__(self):
        self.exit_code = None
        self.start_time = int(time.time())
        self.server_capabilities = typedict()

    """
    Initialize this instance with the options given.
    Options are usually obtained by parsing the command line,
    or using a default configuration object.
    """
    def init(self, _opts, _extra_args=()):
        pass

    """
    Dummy method, actual client implementations will run the main loop.
    """
    def run(self):
        pass

    """
    Terminate the client with the given exit code.
    (the exit code is ignored if we already have one)
    """
    def quit(self, exit_code):
        self.exit_code = exit_code
        sys.exit(exit_code)

    """
    Free up any resources.
    """
    def cleanup(self):
        pass

    """
    Send a packet to the server, dummy implementation.
    """
    def send(self, *_args, **_kwargs):
        pass

    """
    Send a packet to the server,
    this takes precedence over packets sent via send().
    """
    def send_now(self, *parts):
        pass

    """
    Emit a signal, dummy implementation overriden by gobject.
    """
    def emit(self, *_args, **_kwargs):
        pass

    """
    Prepare to run using this connection to the server.
    """
    def setup_connection(self, _conn):
        pass

    """
    Return the capabilities provided by this mixin.
    """
    def get_caps(self):
        return {}

    """
    Parse server attributes specified in the hello capabilities.
    This runs in a non-UI thread.
    """
    def parse_server_capabilities(self):
        return True

    """
    Parse server attributes specified in the hello capabilities.
    This runs in the UI thread.
    """
    def process_ui_capabilities(self):
        pass

    """
    Dummy utility method for compressing data.
    Actual client implementations will provide compression
    based on the client and server capabilities (lz4, lzo, zlib).
    """
    def compressed_wrapper(self, datatype, data, level=5):
        #sub-classes should override this
        assert level>=0
        from xpra.net.compression import Compressed
        return Compressed("raw %s" % datatype, data, can_inline=True)

    """
    Register the packet types that this mixin can handle.
    """
    def init_authenticated_packet_handlers(self):
        pass

    def add_packet_handler(self, packet_type, handler, main_thread=True):
        raise NotImplementedError()

    def add_packet_handlers(self, defs, main_thread=True):
        raise NotImplementedError()
