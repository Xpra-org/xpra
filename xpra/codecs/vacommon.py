# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


def config_libva_logging(force=False) -> None:
    from xpra.log import is_debug_enabled

    # Silence libva's stderr chatter on Linux unless the user has explicitly
    # asked for it (or set LIBVA_MESSAGING_LEVEL themselves).
    # Lifted to debug verbosity when xpra debug is enabled.
    if force or "LIBVA_MESSAGING_LEVEL" not in os.environ:
        level = 1
        if is_debug_enabled("libva"):
            level = 3
        elif is_debug_enabled("codec") or is_debug_enabled("video"):
            level = 2
        os.environ["LIBVA_MESSAGING_LEVEL"] = str(level)
