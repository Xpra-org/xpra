# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

class quic_socket:
    def __init__(self, host, port, ssl_cert, ssl_key, retry=False):
        self.host = host
        self.port = port
        self.ssl_cert = ssl_cert
        self.ssl_key = ssl_key
        self.retry = retry

    def __repr__(self):
        return f"quic_socket({self.host}:{self.port})"

    def accept(self):
        pass

    def settimeout(self):
        pass

    def close(self):
        pass
