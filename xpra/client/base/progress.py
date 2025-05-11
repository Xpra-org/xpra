# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.base.stub import StubClientMixin
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("client")

SPLASH_LOG = envbool("XPRA_SPLASH_LOG", False)


class ProgressClient(StubClientMixin):
    """
    Encapsulates functions for managing the splash screen
    """

    def __init__(self):
        self.progress_process = None

    def show_progress(self, pct: int, text="") -> None:
        pp = self.progress_process
        log(f"progress({pct}, {text!r}) progress process={pp}")
        if SPLASH_LOG:
            log.info(f"{pct:3} {text}")
        if pp:
            pp.progress(pct, text)

    def stop_progress_process(self, reason="closing") -> None:
        pp = self.progress_process
        if not pp:
            return
        self.show_progress(100, reason)
        self.progress_process = None
        if pp.poll() is not None:
            return
        from subprocess import TimeoutExpired
        try:
            if pp.wait(0.1) is not None:
                return
        except TimeoutExpired:
            pass
        try:
            pp.terminate()
        except OSError:
            pass

    def cleanup(self) -> None:
        self.stop_progress_process()
