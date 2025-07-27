# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import

GObject = gi_import("GObject")


def n_arg_signal(n: int) -> tuple:
    return GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_PYOBJECT,) * n


no_arg_signal = n_arg_signal(0)
one_arg_signal = n_arg_signal(1)
