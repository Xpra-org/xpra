# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2020 mjharkin
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import strtobytes


def get_headers(host, port):  #pylint: disable=unused-argument
    headers = {}
    if "XPRA_WS_COOKIE" in os.environ:
        headers[b"Cookie"] = strtobytes(os.environ['XPRA_WS_COOKIE'])
    return headers
