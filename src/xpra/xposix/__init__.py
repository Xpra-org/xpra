# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display.

XPRA_LOCAL_SERVERS_SUPPORTED = True
DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"

def add_client_options(parser):
    from xpra.platform import add_notray_option
    add_notray_option(parser)
