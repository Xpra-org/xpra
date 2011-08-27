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
X11_KEYMAPS = False

def add_client_options(parser):
    pass
