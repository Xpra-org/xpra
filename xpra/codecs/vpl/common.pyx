# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Shared helpers for the oneVPL encoder and decoder Cython wrappers.
# ABOUTME: Sets LIBVA_MESSAGING_LEVEL at import time and routes C-side log
# ABOUTME: messages into the Python "vpl" logger.

import os

from xpra.log import Logger, is_debug_enabled

# Silence libva's stderr chatter on Linux unless the user has explicitly
# asked for it (or set LIBVA_MESSAGING_LEVEL themselves). Lifted to debug
# verbosity when xpra debug categories that cover VPL are enabled. See #4886.
if "LIBVA_MESSAGING_LEVEL" not in os.environ:
    level = 1
    if is_debug_enabled("vpl"):
        level = 3
    elif is_debug_enabled("codec") or is_debug_enabled("video"):
        level = 2
    os.environ["LIBVA_MESSAGING_LEVEL"] = str(level)

log = Logger("vpl")


cdef void vpl_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))
