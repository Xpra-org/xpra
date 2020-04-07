#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (c) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys


def get_commonappdata_dir():
    CSIDL_COMMON_APPDATA = 35
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        SHGetFolderPath = shell32.SHGetFolderPathW
        SHGetFolderPath(0, CSIDL_COMMON_APPDATA, None, 0, buf)
        return buf.value
    except:
        return None

def main():
    from multiprocessing import freeze_support #@UnresolvedImport
    freeze_support()

    os.environ["XPRA_REDIRECT_OUTPUT"] = "1"
    #os.environ["XPRA_LOG_FILENAME"] = "E:\\Shadow.log"
    #os.environ["XPRA_ALL_DEBUG"] = "1"
    #os.environ["XPRA_NAMED_PIPE_UNRESTRICTED"] = "1"
    from xpra.platform import init, set_default_name
    set_default_name("Xpra-Shadow")
    init()

    from xpra.scripts.main import main
    args = sys.argv[:1] + [
        "shadow",
        ] + sys.argv[1:]
    commonappdata = get_commonappdata_dir()
    if commonappdata:
        ssl_cert = os.path.join(commonappdata, "Xpra", "ssl-cert.pem")
        if os.path.exists(ssl_cert):
            args.append("--ssl-cert=%s" % ssl_cert)
    sys.exit(main(sys.argv[0], args))

if __name__ == "__main__":
    main()
