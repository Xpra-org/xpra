# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3


from xpra.wayland.wlroots cimport (
    wl_listener, wl_signal_add, wl_signal, wl_notify_func_t,
)
