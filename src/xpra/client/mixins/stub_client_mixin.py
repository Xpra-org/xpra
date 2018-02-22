# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

class StubClientMixin(object):

    __signals__ = {}

    def init(self, opts):
        pass

    def run(self):
        pass

    def cleanup(self):
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


    def init_authenticated_packet_handlers(self):
        pass
