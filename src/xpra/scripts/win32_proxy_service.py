#!/usr/bin/env python

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
    os.environ["XPRA_REDIRECT_OUTPUT"] = "1"
    #os.environ["XPRA_LOG_FILENAME"] = "E:\\Proxy.log"
    #os.environ["XPRA_ALL_DEBUG"] = "1"

    from xpra.platform import init, set_default_name
    set_default_name("Xpra-Proxy")
    init()

    from xpra.scripts.main import main
    args = sys.argv[:1] + [
        "proxy",
        "--bind=xpra-proxy",
        "--bind-tcp=0.0.0.0:14500",
        "--tcp-auth=sys",
        "-d", "win32,proxy",
        ] + sys.argv[1:]
    commonappdata = get_commonappdata_dir()
    if commonappdata:
        ssl_cert = os.path.join(commonappdata, "Xpra", "ssl-cert.pem")
        if os.path.exists(ssl_cert):
            args.append("--ssl-cert=%s" % ssl_cert)
    sys.exit(main(sys.argv[0], args))

if __name__ == "__main__":
    main()
