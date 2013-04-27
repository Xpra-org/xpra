# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.

import os.path
import sys

LOG_FILENAME = "Xpra.log"
REDIRECT_OUTPUT = True
def set_redirect_output(on):
    global REDIRECT_OUTPUT
    REDIRECT_OUTPUT = on
def set_log_filename(filename):
    global LOG_FILENAME
    LOG_FILENAME = filename

def do_init():
    if not REDIRECT_OUTPUT:
        return
    global LOG_FILENAME
    from paths import _get_data_dir
    d = _get_data_dir()
    log_file = os.path.join(d, LOG_FILENAME)
    sys.stdout = open(log_file, "a")
    sys.stderr = sys.stdout
