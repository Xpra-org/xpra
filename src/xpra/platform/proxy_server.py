# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import platform_import

from xpra.server.proxy.proxy_server import ProxyServer
assert ProxyServer

platform_import(globals(), "proxy_server", False, "ProxyServer")
