# This file is part of Parti.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Mac OS X.
# This is to support a native build without server support
# Although it is possible to build the xpra server on OS X, it is particularly
# useful. So if you want to do that, use xposix instead.

XPRA_LOCAL_SERVERS_SUPPORTED = False
XPRA_SHADOW_SUPPORTED = False
DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"

import os.path


def add_client_options(parser):
    pass

def get_machine_id():
    return  u""


def do_init():
    from wimpiggy.util import gtk_main_quit_really
    def quit_launcher(*args):
        gtk_main_quit_really()
    from xpra.darwin.gui import get_OSXApplication, setup_menubar, osx_ready
    from xpra.platform import get_icon
    setup_menubar(quit_launcher)
    osxapp = get_OSXApplication()
    icon = get_icon("xpra.png")
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    osx_ready()


def get_resources_dir():
    try:
        import gtkosx_application        #@UnresolvedImport
        rsc = gtkosx_application.gtkosx_application_get_resource_path()
        if rsc:
            RESOURCES = "/Resources/"
            i = rsc.rfind(RESOURCES)
            if i>0:
                rsc = rsc[:i+len(RESOURCES)]
            return rsc
    except Exception, e:
        from wimpiggy.log import Logger
        log = Logger()
        log.error("error looking up bundle path: %s", e)
    from xpra.platform import default_get_app_dir
    return default_get_app_dir()

def get_app_dir():
    rsc = get_resources_dir()
    CONTENTS = "/Contents/"
    i = rsc.rfind(CONTENTS)
    if i>0:
        return rsc[:i+len(CONTENTS)]
    return rsc  #hope for the best..

def get_icon_dir():
    rsc = get_resources_dir()
    return os.path.join(rsc, "share", "xpra", "icons")
