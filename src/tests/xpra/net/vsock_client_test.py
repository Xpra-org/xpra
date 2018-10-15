# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import sys
from xpra.net.vsock import connect_vsocket, CID_ANY, PORT_ANY       #@UnresolvedImport

from xpra.log import Logger
log = Logger("network")


def main(args):
    cid = CID_ANY
    port = PORT_ANY
    if len(args)>0:
        cid = int(args[0])
    if len(args)>1:
        port = int(args[1])

    vsock = connect_vsocket(cid=cid, port=port)
    log("vsock=%s", vsock)
    vsock.send(" "*1024*1024*1024)
    data = vsock.recv(1024)
    log("recv()=%s", data)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
