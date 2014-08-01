# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

def debug(*msg):
    """ delay import of logger to prevent cycles """
    from xpra.log import Logger
    log = Logger("util")
    log.debug(*msg)
    return None


def get_resources_dir():
    rsc = None
    try:
        import gtkosx_application        #@UnresolvedImport
        try:
            rsc = gtkosx_application.gtkosx_application_get_resource_path()
            debug("get_resources_dir() gtkosx_application_get_resource_path=%s", rsc)
            if rsc:
                RESOURCES = "/Resources/"
                i = rsc.rfind(RESOURCES)
                if i>0:
                    rsc = rsc[:i+len(RESOURCES)]
        except:
            #maybe we're not running from an app bundle?
            pass
    except:
        print("ERROR: gtkosx_application module is missing - trying to continue anyway")
    if not rsc:
        from xpra.platform.paths import default_get_app_dir
        rsc = default_get_app_dir()
        debug("get_resources_dir() default_get_app_dir()=%s", rsc)
    if rsc:
        #when we run from a jhbuild installation,
        #~/gtk/inst/bin/xpra is the binary
        #so rsc=~/gtk/inst/bin
        #and we want to find ~/gtk/inst/share with get_icon_dir()
        #so let's try to look for that
        #(there is no /bin/ in the regular application bundle path)
        head, tail = os.path.split(rsc)
        debug("get_resources_dir() split: %s / %s", head, tail)
        if tail=="bin":
            rsc = head
    debug("get_resources_dir()=%s", rsc)
    return rsc

def get_app_dir():
    rsc = get_resources_dir()
    CONTENTS = "/Contents/"
    i = rsc.rfind(CONTENTS)
    if i>0:
        rsc = rsc[:i+len(CONTENTS)]
    debug("get_app_dir()=%s", rsc)
    return rsc  #hope for the best..

def get_icon_dir():
    rsc = get_resources_dir()
    i = os.path.join(rsc, "share", "xpra", "icons")
    debug("get_icon_dir()=%s", i)
    return i
