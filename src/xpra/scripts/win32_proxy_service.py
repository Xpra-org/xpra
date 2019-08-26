#!/usr/bin/env python

import os
import sys

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
        "--bind=xpra-proxy"
        "--bind-tcp=0.0.0.0:14500",
        "--tcp-auth=sys",
        "-d", "win32,proxy",
        #"--ssl-cert="{commonappdata}\Xpra\ssl-cert.pem"";
        ] + sys.argv[1:]
    sys.exit(main(sys.argv[0], args))

if __name__ == "__main__":
    main()
