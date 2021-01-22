#!/usr/bin/env python

import os


PIPE_NAME = "xpra-service"

def get_commonappdata_dir():
    CSIDL_COMMON_APPDATA = 35
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        SHGetFolderPath = shell32.SHGetFolderPathW
        SHGetFolderPath(0, CSIDL_COMMON_APPDATA, None, 0, buf)
        return buf.value
    except Exception:
        return None

def main(argv):
    if len(argv)>1:
        if argv[1]!="start":
            assert argv[1]=="stop"
            return run_mode("stop", argv[:1]+["stop", "named-pipe://%s" % PIPE_NAME])

    from multiprocessing import freeze_support #@UnresolvedImport
    freeze_support()

    os.environ["XPRA_REDIRECT_OUTPUT"] = "1"
    #os.environ["XPRA_LOG_FILENAME"] = "E:\\Proxy.log"
    #os.environ["XPRA_ALL_DEBUG"] = "1"

    args = argv[:1] + [
        "proxy",
        "--bind-tcp=0.0.0.0:14500,auth=sys",
        "--tray=no",
        #"-d", "win32,proxy",
        #"--mdns=no",
        ]
    if True:
        #only SYSTEM can access this named pipe:
        #(so no need for auth)
        os.environ["XPRA_NAMED_PIPE_UNRESTRICTED"] = "0"
        args.append("--bind=%s" % PIPE_NAME)
    else:
        #public named pipe (needs auth):
        os.environ["XPRA_NAMED_PIPE_UNRESTRICTED"] = "1"
        args.append("--bind=%s,auth=sys" % PIPE_NAME)
    commonappdata = get_commonappdata_dir()
    if commonappdata:
        ssl_cert = os.path.join(commonappdata, "Xpra", "ssl-cert.pem")
        if os.path.exists(ssl_cert):
            args.append("--ssl-cert=%s" % ssl_cert)
    return run_mode("Xpra-Proxy", args)

def run_mode(name, args):
    from xpra.platform import init, set_default_name
    set_default_name(name)
    init()
    from xpra.scripts.main import main as xpra_main
    return xpra_main(args[0], args)


if __name__ == "__main__":
    import sys
    r = main(sys.argv)
    sys.exit(r)
