# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.log import Logger
from xpra.util.gobject import AutoPropGObjectMixin, PROPERTIES_DEBUG
from xpra.util.str_fn import Ellipsizer

log = Logger("x11", "window", "metadata")

GObject = gi_import("GObject")


class WindowModelStub(AutoPropGObjectMixin, GObject.GObject):
    """
        Stub for all window models
    """

    # things that we expose:
    _property_names: list[str] = []
    # exposed and changing (should be watched for notify signals):
    _dynamic_property_names: list[str] = []
    _internal_property_names: list[str] = []
    _MODELTYPE: str = "Stub"

    def __init__(self):
        AutoPropGObjectMixin.__init__(self)
        GObject.GObject.__init__(self)
        self._setup_done: bool = False  # so we can ignore notify() events during setup
        self._managed: bool = False
        self._managed_handlers: list[int] = []

    #########################################
    # Setup and teardown
    #########################################

    def is_managed(self) -> bool:
        return self._managed

    def unmanage(self, _exiting=False) -> None:
        self.managed_disconnect()

    #########################################
    # Connect to signals in a "managed" way
    #########################################

    def managed_connect(self, detailed_signal, handler, *args) -> int:
        """ connects a signal handler and makes sure we will clean it up on unmanage() """
        handler_id: int = self.connect(detailed_signal, handler, *args)
        self._managed_handlers.append(handler_id)
        return handler_id

    def managed_disconnect(self) -> None:
        for handler_id in self._managed_handlers:
            self.disconnect(handler_id)
        self._managed_handlers = []

    ################################
    # Property reading
    ################################

    def get_dimensions(self):
        return NotImplementedError()

    #########################################
    # Properties we choose to expose
    #########################################

    def get_property_names(self) -> list[str]:
        """ The properties that should be exposed to clients """
        return self._property_names

    def get_dynamic_property_names(self) -> list[str]:
        """ The properties that may change over time """
        return self._dynamic_property_names

    def get_internal_property_names(self) -> list[str]:
        """ The properties that should not be exposed to the client """
        return self._internal_property_names

    @staticmethod
    def get_logger(property_name) -> Callable:
        if property_name in PROPERTIES_DEBUG:
            return log.info
        return log.debug

    def _updateprop(self, name: str, value) -> bool:
        """ Updates the property and fires notify(),
            but only if the value has changed
            and if the window has finished setting up, and it is still managed.
            Can only be used for AutoPropGObjectMixin properties.
        """
        logger = self.get_logger(name)
        cur = self._gproperties.get(name, None)
        if name not in self._gproperties or cur != value:
            logger("updateprop(%s, %s) previous value=%s", name, Ellipsizer(value), Ellipsizer(cur))
            self._gproperties[name] = value
            if self._setup_done and self._managed:
                self.notify(name)
            else:
                logger("not sending notify(%s) (setup done=%s, managed=%s)", name, self._setup_done, self._managed)
            return True
        logger("updateprop(%s, %s) unchanged", name, value)
        return False

    def get(self, name: str, default_value=None) -> object:
        """ Allows us to avoid defining all the attributes we may ever query,
            returns the default value if the property does not exist.
        """
        logger = self.get_logger(name)
        if name in set(self._property_names + self._dynamic_property_names + self._internal_property_names):
            v = self.get_property(name)
            logger("get(%s, %s) using get_property=%s", name, default_value, v)
        else:
            v = default_value
            if name not in ("override-redirect", "tray"):
                logger("get(%s, %s) not a property of %s, returning default value=%s", name, default_value, type(self), v)
        return v

    def show(self) -> None:
        """
        implemented for real windows only,
        trays and OR windows are always "shown" somewhere
        """

    # temporary? / convenience access methods:
    def is_OR(self) -> bool:
        """ Is this an override-redirect window? """
        return bool(self.get("override-redirect", False))

    def is_tray(self) -> bool:
        """ Is this a tray window? """
        return bool(self.get("tray", False))

    def is_shadow(self) -> bool:
        """ Is this a shadow instead of a real window? """
        return False

    def has_alpha(self) -> bool:
        """ Does the pixel data have an alpha channel? """
        return bool(self.get("has-alpha", False))

    def uses_xshm(self) -> bool:
        return False
