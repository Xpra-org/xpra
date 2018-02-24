# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

class StubSourceMixin(object):

    def cleanup(self):
        pass

    def is_closed(self):
        return False

    def parse_client_caps(self, c):
        pass

    def get_caps(self):
        return {}
        
    def get_info(self):
        return {}

    def user_event(self):
        pass

    def may_notify(self, *args, **kwargs):
        pass
