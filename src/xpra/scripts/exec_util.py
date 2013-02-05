# This file is part of Parti.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import subprocess

from wimpiggy.log import Logger
log = Logger()

#the list of signals for which we will suspend the handler for the duration of the Popen call
PROTECTED_SIGNALS = []

def safe_exec(cmd, stdin=None, log_errors=True):
    """ this is a bit of a hack,
    the problem is that we won't catch SIGCHLD at all while this command is running! """
    import signal
    saved_signal_handlers = {}
    try:
        for sig in PROTECTED_SIGNALS:
            oldhandler = signal.signal(sig, signal.SIG_DFL)
            saved_signal_handlers[sig] = oldhandler
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate(stdin)
        code = process.poll()
        l=log.debug
        if code!=0 and log_errors:
            l=log.error
        l("signal_safe_exec(%s,%s) stdout='%s'", cmd, stdin, out)
        l("signal_safe_exec(%s,%s) stderr='%s'", cmd, stdin, err)
        return  code, out, err
    finally:
        for sig, handler in saved_signal_handlers.items():
            signal.signal(sig, handler)
