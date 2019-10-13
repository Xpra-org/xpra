# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject

from xpra.x11.common import Unmanageable
from xpra.x11.models.base import BaseWindowModel
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport

X11Window = X11WindowBindings()


class OverrideRedirectWindowModel(BaseWindowModel):
    __gsignals__ = dict(BaseWindowModel.__common_signals__)
    __gproperties__ = dict(BaseWindowModel.__common_properties__)
    __gproperties__.update({
        "override-redirect": (GObject.TYPE_BOOLEAN,
                       "Is the window of type override-redirect", "",
                       True,
                       GObject.ParamFlags.READABLE),
                        })
    _property_names = BaseWindowModel._property_names + ["override-redirect"]
    _MODELTYPE = "OR-Window"

    def __init__(self, client_window):
        super().__init__(client_window)
        self._updateprop("override-redirect", True)

    def setup(self):
        super().setup()
        # So now if the window becomes unmapped in the future then we will
        # notice... but it might be unmapped already, and any event
        # already generated, and our request for that event is too late!
        # So double check now, *after* putting in our request:
        if not X11Window.is_mapped(self.xid):
            raise Unmanageable("window already unmapped")
        ch = self._composite.get_contents_handle()
        if ch is None:
            raise Unmanageable("failed to get damage handle")

GObject.type_register(OverrideRedirectWindowModel)
