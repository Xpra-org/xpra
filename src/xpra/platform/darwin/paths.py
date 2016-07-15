# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

def debug(*msg):
    """ delay import of logger to prevent cycles """
    from xpra.log import Logger
    log = Logger("util")
    log(*msg)
    return None


def do_get_resources_dir():
    rsc = None
    RESOURCES = "/Resources/"
    #FUGLY warning: importing gtkosx_application causes the dock to appear,
    #and in some cases we don't want that.. so use the env var XPRA_SKIP_UI as workaround for such cases:
    if os.environ.get("XPRA_SKIP_UI", "0")=="0":
        try:
            import gtkosx_application        #@UnresolvedImport
            try:
                rsc = gtkosx_application.gtkosx_application_get_resource_path()
                debug("get_resources_dir() gtkosx_application_get_resource_path=%s", rsc)
            except:
                #maybe we're not running from an app bundle?
                pass
        except:
            #delayed import to prevent cycles:
            from xpra.log import Logger
            log = Logger("util")
            log.error("ERROR: gtkosx_application module is missing - trying to continue anyway")
    else:
        debug("XPRA_SKIP_UI is set, not importing gtkosx_application")
    if rsc is None:
        #try using the path to this file to find the resource path:
        rsc = __file__
    i = rsc.rfind(RESOURCES)
    if i<=0:
        #last fallback: try the default app dir
        from xpra.platform.paths import default_get_app_dir
        rsc = default_get_app_dir()
        debug("get_resources_dir() default_get_app_dir()=%s", rsc)
    i = rsc.rfind(RESOURCES)
    if i>0:
        rsc = rsc[:i+len(RESOURCES)]
    debug("get_resources_dir()=%s", rsc)
    return rsc

def do_get_app_dir():
    from xpra.platform.paths import get_resources_dir
    rsc = get_resources_dir()
    CONTENTS = "/Contents/"
    i = rsc.rfind(CONTENTS)
    if i>0:
        rsc = rsc[:i+len(CONTENTS)]
    debug("get_app_dir()=%s", rsc)
    return rsc  #hope for the best..

def do_get_icon_dir():
    from xpra.platform.paths import get_resources_dir
    i = os.path.join(get_resources_dir(), "share", "xpra", "icons")
    debug("get_icon_dir()=%s", i)
    return i


def do_get_default_conf_dirs():
    #the default config file we install into the Resources folder:
    #ie: /Volumes/Xpra/Xpra.app/Contents/Resources/etc
    from xpra.platform.paths import get_resources_dir
    return [os.path.join(get_resources_dir(), "etc", "xpra")]

def do_get_system_conf_dirs():
    #the system wide configuration directory
    try:
        from Foundation import  NSSearchPathForDirectoriesInDomains, NSApplicationSupportDirectory, NSLocalDomainMask, NSSystemDomainMask  #@UnresolvedImport
        dirs = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSLocalDomainMask|NSSystemDomainMask, False)
        return list(dirs)
    except:
        pass
    #fallback to hardcoded:
    default_conf_dir = "/Library/Application Support/Xpra"
    return [os.environ.get("XPRA_SYSCONF_DIR", default_conf_dir)]

def do_get_user_conf_dirs():
    #the system wide configuration directory
    try:
        #when running sandboxed, it may look like this:
        #~/Library/Containers/<bundle_id>/Data/Library/Application Support/
        from Foundation import  NSSearchPathForDirectoriesInDomains, NSApplicationSupportDirectory, NSUserDomainMask    #@UnresolvedImport
        dirs = list(NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, False))
    except:
        #fallback to hardcoded:
        dirs = ["/Library/Application Support/Xpra"]
    dirs.append("~/.xpra")
    return dirs

def do_get_default_log_dir():
    try:
        from Foundation import  NSSearchPathForDirectoriesInDomains, NSLibraryDirectory, NSUserDomainMask    #@UnresolvedImport
        dirs = NSSearchPathForDirectoriesInDomains(NSLibraryDirectory, NSUserDomainMask, False)
        #ie: ~/Library/
        library_dir = dirs[0]
        return os.path.join(library_dir, "Xpra")
    except:
        pass
    return "~/Library/Logs"

def do_get_socket_dirs():
    return ["/var/tmp/%s-Xpra" % os.getuid(), "~/.xpra"]


def do_get_download_dir():
    d = "~/Downloads"
    try:
        from Foundation import  NSSearchPathForDirectoriesInDomains, NSDownloadsDirectory, NSUserDomainMask     #@UnresolvedImport
        d = NSSearchPathForDirectoriesInDomains(NSDownloadsDirectory, NSUserDomainMask, False)[0]
        #(should be "~/Downloads")
    except:
        pass
    if not os.path.exists(os.path.expanduser(d)):
        return "~"
    return d


def do_get_sound_command():
    #try to use the subapp:
    from xpra.platform.paths import get_app_dir
    base = get_app_dir()
    subapp = os.path.join(base, "Xpra_NoDock.app", "Contents")
    if os.path.exists(subapp) and os.path.isdir(subapp):
        base = subapp
    helper = os.path.join(subapp, "MacOS", "Xpra")
    return [helper]
