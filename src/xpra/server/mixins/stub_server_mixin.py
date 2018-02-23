# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class StubServerMixin(object):

    def init(self, _opts):
        pass

    def cleanup(self):
        pass

    def setup(self, _opts):
        pass

    def threaded_setup(self):
        pass

    def get_caps(self):
        return {}

    def get_server_features(self, _source):
        return {}

    def get_info(self, _proto):
        return {}

    def init_packet_handlers(self):
        pass
