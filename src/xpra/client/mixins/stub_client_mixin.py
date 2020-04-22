# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time

from xpra.util import typedict


class StubClientMixin:

    __signals__ = {}
    def __init__(self):
        self.exit_code = None
        self.start_time = int(time.time())

    def init(self, _opts, _extra_args=()):
        """
        Initialize this instance with the options given.
        Options are usually obtained by parsing the command line,
        or using a default configuration object.
        """

    def run(self):
        """
        run the main loop.
        """

    def quit(self, exit_code):  # pragma: no cover
        """
        Terminate the client with the given exit code.
        (the exit code is ignored if we already have one)
        """
        self.exit_code = exit_code
        sys.exit(exit_code)

    def cleanup(self):
        """
        Free up any resources.
        """

    def send(self, *_args, **_kwargs):
        """
        Send a packet to the server, dummy implementation.
        """

    def send_now(self, *parts):
        """
        Send a packet to the server,
        this takes precedence over packets sent via send().
        """

    def emit(self, *_args, **_kwargs):
        """
        Emit a signal, dummy implementation overriden by gobject.
        """

    def setup_connection(self, _conn):
        """
        Prepare to run using this connection to the server.
        """

    def get_caps(self) -> dict:
        """
        Return the capabilities provided by this mixin.
        """
        return {}

    def get_info(self) -> dict:
        """
        Information contained in this mixin
        """
        return {}

    def parse_server_capabilities(self, caps : typedict) -> bool:
        """
        Parse server attributes specified in the hello capabilities.
        This runs in a non-UI thread.
        """
        return True

    def process_ui_capabilities(self, caps : typedict):
        """
        Parse server attributes specified in the hello capabilities.
        This runs in the UI thread.
        """

    def compressed_wrapper(self, datatype, data, level=5):
        """
        Dummy utility method for compressing data.
        Actual client implementations will provide compression
        based on the client and server capabilities (lz4, lzo, zlib).
        """
        #sub-classes should override this
        assert level>=0
        from xpra.net.compression import Compressed
        return Compressed("raw %s" % datatype, data, can_inline=True)

    def init_authenticated_packet_handlers(self):
        """
        Register the packet types that this mixin can handle.
        """

    def add_packet_handler(self, packet_type : str, handler : callable, main_thread=True):  # pragma: no cover
        raise NotImplementedError()

    def add_packet_handlers(self, defs, main_thread=True):  # pragma: no cover
        raise NotImplementedError()
