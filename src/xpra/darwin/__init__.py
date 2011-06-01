# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Mac OS X.
# This is to support a native build without server support
# Although it is possible to build the xpra server on OS X, it is particularly
# useful. So if you want to do that, use xposix instead.

XPRA_LOCAL_SERVERS_SUPPORTED = False
DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"

def add_client_options(parser):
    parser.add_option("--dock-icon", action="store",
                          dest="dock_icon", default=None,
                          help="Path to the image which will be used as icon for the dock")
