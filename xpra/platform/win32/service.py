#!/usr/bin/env python3
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


PIPE_NAME = "xpra-service"


def get_commonappdata_dir() -> str:
    CSIDL_COMMON_APPDATA = 35
    try:
        from ctypes import (
            create_unicode_buffer, wintypes,
            WinDLL,  # @UnresolvedImport
        )
        buf = create_unicode_buffer(wintypes.MAX_PATH)
        shell32 = WinDLL("shell32", use_last_error=True)
        SHGetFolderPath = shell32.SHGetFolderPathW
        SHGetFolderPath(0, CSIDL_COMMON_APPDATA, None, 0, buf)
        return buf.value
    except Exception:
        return ""


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] != "start":
        if argv[1] != "stop":
            raise ValueError(f"unsupported subcommand {argv[1]!r}")
        return run_mode("stop", argv[:1] + ["stop", f"named-pipe://{PIPE_NAME}"])

    from multiprocessing import freeze_support
    freeze_support()

    os.environ["XPRA_REDIRECT_OUTPUT"] = "1"
    os.environ["XPRA_LOG_FILENAME"] = "System-Proxy.log"
    # os.environ["XPRA_ALL_DEBUG"] = "1"

    args = argv[:1] + [
        "proxy",
        "--bind-tcp=0.0.0.0:14500,auth=sys,client-username=true,verify-username=true",
        "--tray=no",
        # "-d", "win32,proxy",
        # "--mdns=no",
    ]
    SYSTEM_USER = os.environ.get("SYSTEM_USER", "1")
    if SYSTEM_USER == "1":
        # only SYSTEM can access this named pipe:
        # (so no need for auth)
        os.environ["XPRA_NAMED_PIPE_UNRESTRICTED"] = "0"
        args.append(f"--bind={PIPE_NAME}")
    else:
        # public named pipe (needs auth):
        os.environ["XPRA_NAMED_PIPE_UNRESTRICTED"] = "1"
        args.append(f"--bind={PIPE_NAME},auth=sys")
    commonappdata = get_commonappdata_dir()
    if commonappdata:
        ssl_cert = os.path.join(commonappdata, "Xpra", "ssl-cert.pem")
        if os.path.exists(ssl_cert):
            args.append(f"--ssl-cert={ssl_cert}")
    return run_mode("Xpra-Proxy", args)


def run_mode(name: str, args: list[str]) -> int:
    from xpra.platform import init, set_default_name
    set_default_name(name)
    init()
    from xpra.scripts.main import main as xpra_main
    return int(xpra_main(args[0], args))


if __name__ == "__main__":
    import sys

    r = main(sys.argv)
    sys.exit(r)
