# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Override-redirect window model for unmanaged (OR) X11 windows.

from xpra.os_util import gi_import
from xpra.x11.common import Unmanageable
from xpra.x11.error import xsync, xswallow
from xpra.x11.models.base import BaseWindowModel
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import X11WindowBindings

X11Window = X11WindowBindings()

CWBorderWidth: int = constants["CWBorderWidth"]

GObject = gi_import("GObject")


class OverrideRedirectWindowModel(BaseWindowModel):
    __gsignals__ = dict(BaseWindowModel.__common_signals__)
    __gproperties__ = dict(BaseWindowModel.__common_properties__)
    __gproperties__ |= {
        "override-redirect": (
            GObject.TYPE_BOOLEAN,
            "Is the window of type override-redirect", "",
            True,
            GObject.ParamFlags.READABLE,
        ),
    }
    _property_names = BaseWindowModel._property_names + ["override-redirect"]
    _MODELTYPE = "OR-Window"

    def __init__(self, xid: int):
        super().__init__(xid)
        # Squash the X11 border to 0 before compositing is set up.
        # The composite pixmap returned by `XCompositeNameWindowPixmap` includes the
        # border, so a non-zero border_width offsets the inner content within the
        # pixmap. CompositeHelper.do_x11_damage_event shifts damage coords by
        # border_width to read from the right pixmap origin, but the same coords end
        # up as the client-side draw target — producing a `border_width`-pixel black
        # gap at the top-left of the OR window (e.g. xterm popups with border_width=2).
        # Managed windows already have this squashed via the `configure()` helper.
        with xswallow:
            with xsync:
                X11Window.ConfigureWindow(xid, 0, 0, 0, 0, border=0, value_mask=CWBorderWidth)
        self._updateprop("override-redirect", True)

    def setup(self) -> None:
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
        # Re-read geometry now that StructureNotifyMask is set (from super().setup()).
        # The window may have resized between __init__ reading the initial geometry
        # and setup() subscribing to events — any ConfigureNotify from that gap is lost.
        self._recheck_geometry()

    def _recheck_geometry(self) -> None:
        try:
            actual = X11Window.getGeometry(self.xid)
        except Exception:
            return
        if not actual:
            return
        actual_geom = actual[:4]
        model_geom = self._gproperties.get("geometry")
        if model_geom and model_geom != actual_geom:
            from xpra.log import Logger
            geomlog = Logger("x11", "window", "geometry")
            geomlog.info("OR window %#x geometry changed during setup: %s -> %s",
                         self.xid, model_geom, actual_geom)
            self._updateprop("geometry", actual_geom)


GObject.type_register(OverrideRedirectWindowModel)
