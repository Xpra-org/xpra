# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import monotonic_time


class StubClientMixin(object):

    __signals__ = {}
    def __init__(self):
        self.exit_code = None
        self.start_time = int(monotonic_time())

    def init(self, _opts):
        pass

    def run(self):
        pass

    def quit(self, exit_code):
        self.exit_code = exit_code
        sys.exit(exit_code)

    def cleanup(self):
        pass

    def send(self, *_args, **_kwargs):
        pass

    def emit(self, *_args, **_kwargs):
        pass

    def setup_connection(self, _conn):
        pass

    def get_caps(self):
        return {}

    def parse_server_capabilities(self):
        return True

    def process_ui_capabilities(self):
        pass

    def compressed_wrapper(self, datatype, data, level=5):
        #sub-classes should override this
        assert level>=0
        from xpra.net.compression import Compressed
        return Compressed("raw %s" % datatype, data, can_inline=True)


    def init_authenticated_packet_handlers(self):
        pass
