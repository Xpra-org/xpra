# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Shared helpers for the oneVPL encoder and decoder Cython wrappers.
# ABOUTME: Sets LIBVA_MESSAGING_LEVEL at import time and routes C-side log
# ABOUTME: messages into the Python "vpl" logger.

from xpra.codecs.vacommon import config_libva_logging
from xpra.log import Logger

log = Logger("vpl")

config_libva_logging()

cdef void vpl_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))
