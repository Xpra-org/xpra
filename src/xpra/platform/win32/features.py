# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.
import os

SHADOW_SUPPORTED = True
os.environ["PLINK_PROTOCOL"] = "ssh"
DEFAULT_SSH_CMD = "plink"
GOT_PASSWORD_PROMPT_SUGGESTION = \
   'Perhaps you need to set up Pageant, or (less secure) use --ssh="plink -pw YOUR-PASSWORD"?\n'
CLIPBOARDS=["CLIPBOARD"]
CLIPBOARD_GREEDY = True
