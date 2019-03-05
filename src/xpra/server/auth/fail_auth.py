# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def init(_opts):
    pass

class Authenticator(object):
    def __init__(self, username="", **kwargs):
        raise Exception("failing")

    def __repr__(self):
        return "fail"
