# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.util.io import get_util_logger
from xpra.util.env import envbool


def debug(*msg):
    """ delay import of logger to prevent cycles """
    log = get_util_logger()
    log.debug(*msg)
    return None


_gtkosx_warning_ = False


def do_get_resources_dir():
    rsc = None
    RESOURCES = "/Resources/"
    # FUGLY warning: importing gtkosx_application causes the dock to appear,
    # and in some cases we don't want that.. so use the env var XPRA_SKIP_UI as workaround for such cases:
    if not envbool("XPRA_SKIP_UI", False):
        from xpra.platform.darwin import get_OSXApplication
        macapp = get_OSXApplication()
        try:
            rsc = macapp.get_resource_path()
            debug("get_resources_dir() %s.get_resource_path=%s", macapp, rsc)
        except Exception:
            global _gtkosx_warning_
            if _gtkosx_warning_ is False:
                _gtkosx_warning_ = True
                # delayed import to prevent cycles:
                get_util_logger().error("Error: gtkosx_application module is missing - trying to continue anyway")
    else:
        debug("XPRA_SKIP_UI is set, not importing gtkosx_application")
    if rsc is None:
        # try using the path to this file to find the resource path:
        rsc = __file__
    i = rsc.rfind(RESOURCES)
    if i <= 0:
        # last fallback: try the default app dir
        from xpra.platform.paths import default_get_app_dir
        rsc = default_get_app_dir()
        debug("get_resources_dir() default_get_app_dir()=%s", rsc)
    i = rsc.rfind(RESOURCES)
    if i > 0:
        rsc = rsc[:i + len(RESOURCES)]
    debug("get_resources_dir()=%s", rsc)
    return rsc


def do_get_app_dir() -> str:
    from xpra.platform.paths import get_resources_dir
    rsc = get_resources_dir()
    CONTENTS = "/Contents/"
    i = rsc.rfind(CONTENTS)
    if i > 0:
        rsc = rsc[:i + len(CONTENTS)]
    debug("get_app_dir()=%s", rsc)
    return rsc  # hope for the best..


def do_get_image_dir() -> str:
    from xpra.platform.paths import get_resources_dir
    i = os.path.join(get_resources_dir(), "share", "xpra", "images")
    debug("get_image_dir()=%s", i)
    return i


def do_get_icon_dir() -> str:
    from xpra.platform.paths import get_resources_dir
    i = os.path.join(get_resources_dir(), "share", "xpra", "icons")
    debug("get_icon_dir()=%s", i)
    return i


def do_get_default_conf_dirs() -> list[str]:
    # the default config file we install into the Resources folder:
    # ie: /Volumes/Xpra/Xpra.app/Contents/Resources/etc
    from xpra.platform.paths import get_resources_dir
    return [os.path.join(get_resources_dir(), "etc", "xpra")]


def do_get_system_conf_dirs() -> list[str]:
    # the system-wide configuration directory
    dirs = []
    try:
        from Foundation import (
            NSSearchPathForDirectoriesInDomains,
            NSApplicationSupportDirectory,
            NSLocalDomainMask, NSSystemDomainMask
        )
        sdirs = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory,
                                                    NSLocalDomainMask | NSSystemDomainMask, False)
        for x in sdirs:
            # ie: "/Library/Application Support/Xpra"
            dirs.append(os.path.join(x, "Xpra"))
    except Exception:
        # fallback to hardcoded:
        default_conf_dir = "/Library/Application Support/Xpra"
        dirs = [os.environ.get("XPRA_SYSCONF_DIR", default_conf_dir)]
    dirs.append("/etc/xpra")
    return dirs


def do_get_ssh_conf_dirs() -> list[str]:
    return ["/private/etc", "/etc/ssh", "/usr/local/etc/ssh", "~/.ssh", "~/ssh"]


def do_get_user_conf_dirs(_uid) -> list[str]:
    # the system wide configuration directory
    dirs = []
    try:
        # when running sandboxed, it may look like this:
        # ~/Library/Containers/<bundle_id>/Data/Library/Application Support/
        from Foundation import (
            NSSearchPathForDirectoriesInDomains,
            NSApplicationSupportDirectory, NSUserDomainMask,
        )
        udirs = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, False)
        for x in udirs:
            dirs.append(os.path.join(x, "Xpra"))
    except Exception:
        # fallback to hardcoded:
        from os import getuid
        if getuid() == 0:
            dirs = ["/Library/Application Support/Xpra"]
    dirs.append("~/.xpra")
    return dirs


def do_get_default_log_dirs() -> list[str]:
    dirs = []
    try:
        from Foundation import (
            NSSearchPathForDirectoriesInDomains,
            NSLibraryDirectory, NSUserDomainMask,
        )
        udirs = NSSearchPathForDirectoriesInDomains(NSLibraryDirectory, NSUserDomainMask, False)
        for x in udirs:
            # ie: ~/Library/
            dirs.append(os.path.join(x, "Logs", "Xpra"))
    except Exception:
        dirs.append("~/Library/Logs/Xpra")
    import tempfile
    dirs.append(tempfile.gettempdir())
    return dirs


def do_get_state_dir() -> str:
    return "~/.xpra/state"


def do_get_sessions_dir() -> str:
    return "~/.xpra/sessions"


def do_get_socket_dirs() -> list[str]:
    # return ["/var/tmp/%s-Xpra" % os.getuid(), "~/.xpra"]
    import tempfile
    return [tempfile.gettempdir(), "~/.xpra"]


def do_get_client_socket_dirs() -> list[str]:
    return ["~/.xpra/clients"]


def do_get_download_dir() -> str:
    d = "~/Downloads"
    try:
        from Foundation import (
            NSSearchPathForDirectoriesInDomains, NSDownloadsDirectory, NSUserDomainMask,
        )
        d = NSSearchPathForDirectoriesInDomains(NSDownloadsDirectory, NSUserDomainMask, False)[0]
        # (should be "~/Downloads")
    except Exception:
        pass
    if not os.path.exists(os.path.expanduser(d)):
        return "~"
    return d


def do_get_desktop_background_paths() -> list[str]:
    return [
        "/System/Library/CoreServices/DefaultDesktop.jpg",
        "/Library/Desktop Pictures/*jpg",
    ]


def do_get_sshpass_command() -> str:
    from xpra.platform.paths import get_app_dir
    base = get_app_dir()
    p = os.path.join(base, "Resources", "bin", "sshpass")
    if os.path.exists(p):
        return p
    return ""


def do_get_xpra_command() -> list[str]:
    if sys.argv and sys.argv[0].lower().endswith("/xpra"):
        return [sys.argv[0]]
    # try to use the one from the app bundle:
    from xpra.platform.paths import get_app_dir
    base = get_app_dir()
    xpra_cmd = os.path.join(base, "MacOS", "Xpra")
    if os.path.exists(xpra_cmd):
        return [xpra_cmd]
    return ["xpra"]


def _get_helpers_dir() -> str:
    from xpra.platform.paths import get_app_dir
    base = get_app_dir()
    p = os.path.join(base, "Helpers")
    return p


def do_get_nodock_command() -> list[str]:
    # try to use the sub-app:
    from xpra.platform.paths import get_app_dir
    base = get_app_dir()
    subapp = os.path.join(base, "Xpra_NoDock.app", "Contents")
    if os.path.exists(subapp) and os.path.isdir(subapp):
        base = subapp
    # AppStore builds have script wrappers:
    helper = os.path.join(base, "Resources", "scripts", "Xpra")
    if not os.path.exists(helper):
        helper = os.path.join(base, "Helpers", "Xpra")
    if not os.path.exists(helper):
        # having a dock is still better than
        # trying to run a command that does not exist!
        from xpra.platform.paths import get_xpra_command
        return get_xpra_command()
    return [helper]


def do_get_audio_command() -> list[str]:
    return do_get_nodock_command()


def do_get_python_exec_command() -> list[str]:
    return [os.path.join(_get_helpers_dir(), "Python"), "-c"]


def do_get_python_execfile_command() -> list[str]:
    return [os.path.join(_get_helpers_dir(), "Python")]
