# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.log import Logger

metalog = Logger("metadata")

GObject = gi_import("GObject")

PROPERTIES_DEBUG = [x.strip() for x in os.environ.get("XPRA_WINDOW_PROPERTIES_DEBUG", "").split(",")]


def n_arg_signal(n: int) -> tuple:
    return GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_PYOBJECT,) * n


no_arg_signal = n_arg_signal(0)
one_arg_signal = n_arg_signal(1)


def to_gsignals(signals: dict[str, Any]) -> dict[str, tuple]:
    gsignals: dict[str, tuple] = {}
    for key, value in signals.items():
        if isinstance(value, tuple):
            gsignals[key] = value
        elif isinstance(value, int):
            gsignals[key] = n_arg_signal(value)
        else:
            raise ValueError("unexpected signal value: %r (%s)" % (value, type(value)))
    return gsignals


class AutoPropGObjectMixin:
    """Mixin for automagic property support in GObjects.

    Make sure this is the first entry on your parent list, so super().__init__
    will work right."""

    def __init__(self):
        self._gproperties: dict[str, Any] = {}

    def do_get_property(self, pspec):
        return self._gproperties.get(pspec.name)

    def do_set_property(self, pspec, value) -> None:
        self._internal_set_property(pspec.name, value)

    def _internal_set_property(self, name: str, value) -> None:
        if name in PROPERTIES_DEBUG:
            metalog.info("_internal_set_property(%r, %r)", name, value, backtrace=True)
        self._gproperties[name] = value
        self.notify(name)
