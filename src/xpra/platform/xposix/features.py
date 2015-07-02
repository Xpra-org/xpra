# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#don't bother trying to forward system tray with Ubuntu's "unity":
from xpra.util import is_unity
SYSTEM_TRAY_SUPPORTED = not is_unity()
DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"
CLIPBOARDS=["CLIPBOARD", "PRIMARY", "SECONDARY"]
