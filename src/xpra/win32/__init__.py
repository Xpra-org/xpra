# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.

XPRA_LOCAL_SERVERS_SUPPORTED = False
import os
os.environ["PLINK_PROTOCOL"] = "ssh"
DEFAULT_SSH_CMD = "plink"
GOT_PASSWORD_PROMPT_SUGGESTION = \
   'Perhaps you need to set up Pageant, or (less secure) use --ssh="plink -pw YOUR-PASSWORD"?\n'

def add_client_options(parser):
    parser.add_option("--tray-icon", action="store",
                          dest="tray_icon", default=None,
                          help="Path to the image which will be used as icon for the system tray")
