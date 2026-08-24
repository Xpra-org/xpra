#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from dbus.types import UInt32, Int32

from xpra.os_util import gi_import
from xpra.dbus.helper import native_to_dbus
from xpra.keyboard.nokeyboard import NoKeyboardDevice
from xpra.platform.posix.fd_portal import REMOTEDESKTOP_IFACE, AvailableDeviceTypes
from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.server.shadow.keyboard import ShadowKeyboardManager
from xpra.log import Logger

# we only use `Gdk` for its keysym tables:
# `keyval_from_name` and `unicode_to_keyval` are pure lookups
# which do not require a display connection
Gdk = gi_import("Gdk")

log = Logger("shadow", "keyboard")

# `state` values for `NotifyKeyboardKeycode` and `NotifyKeyboardKeysym`:
RELEASED = 0
PRESSED = 1

VOID_KEYSYM = 0xffffff      # `Gdk.KEY_VoidSymbol`


def unicode_keysym(codepoint: int) -> int:
    """ the X11 keysym for a unicode codepoint, ie: `€` is `0x20ac` """
    keysym = int(Gdk.unicode_to_keyval(codepoint))
    return 0 if keysym == VOID_KEYSYM else keysym


def parse_keysym(keyname: str) -> int:
    """
    Convert an X11 keysym name into its keysym value,
    ie: `BackSpace` is `0xff08`.
    """
    if not keyname or keyname in ("NoSymbol", "VoidSymbol"):
        return 0
    # unicode keysym names: `U20AC`, `U+20AC` or `0x20ac`
    # (see `xpra.keyboard.keysyms.keysym_name`)
    hexstr = ""
    if keyname[0] in "Uu" and len(keyname) >= 5:
        hexstr = keyname[2:] if keyname[1] == "+" else keyname[1:]
    elif keyname[:2].lower() == "0x":
        hexstr = keyname[2:]
    if hexstr:
        try:
            return unicode_keysym(int(hexstr, 16))
        except ValueError:
            log("parse_keysym(%r) not a unicode keysym name", keyname)
    keysym = int(Gdk.keyval_from_name(keyname))
    return 0 if keysym == VOID_KEYSYM else keysym


class RemoteDesktopKeyboardDevice(NoKeyboardDevice):
    """
    Injects key events using the `RemoteDesktop` portal interface.
    """
    __slots__ = ("server", )

    def __init__(self, server):
        self.server = server

    def __repr__(self):
        return "RemoteDesktopKeyboardDevice"

    def _notify(self, method: str, *args) -> None:
        server = self.server
        options = native_to_dbus([], "{sv}")
        getattr(server.portal_interface, method)(
            server.session_handle,
            options,
            *args,
            dbus_interface=REMOTEDESKTOP_IFACE)

    def press_keysym(self, keysym: int, press: bool) -> None:
        log("press_keysym(%#x, %s)", keysym, press)
        self._notify("NotifyKeyboardKeysym", Int32(keysym), UInt32(PRESSED if press else RELEASED))

    def press_key(self, keycode: int, press: bool) -> None:
        # the portal expects evdev keycodes, X11 keycodes are offset by 8:
        log("press_key(%i, %s)", keycode, press)
        self._notify("NotifyKeyboardKeycode", Int32(keycode - 8), UInt32(PRESSED if press else RELEASED))

    def clear_keys_pressed(self, keysyms) -> None:
        # the keys we keep track of are keysyms, see `RemoteDesktopKeyboardManager`:
        for keysym in keysyms:
            self.press_keysym(keysym, False)


class RemoteDesktopKeyboardManager(ShadowKeyboardManager):
    """
    Keyboard subsystem for the `RemoteDesktop` portal.

    The portal does not expose the compositor's keymap,
    so the keycodes found in the client's key events - which come from a foreign keymap -
    cannot be translated into keycodes the compositor would understand.
    What we can do is tell the portal which X11 keysym the user pressed
    and let the compositor figure out how to generate it.
    So `get_keycode` returns keysyms rather than keycodes,
    and `fake_key` sends them using `NotifyKeyboardKeysym`.
    """
    BACKEND = "remote-desktop"
    # to only warn once if we have no keyboard device:
    warned = False

    def make_keyboard_device(self) -> RemoteDesktopKeyboardDevice:
        return RemoteDesktopKeyboardDevice(self.server)

    def get_keyboard_config(self, _props=None) -> KeyboardConfigBase:
        # the base class is enough: we don't translate keycodes ourselves
        return KeyboardConfigBase()

    def set_keymap(self, server_source, force=False) -> None:
        # the compositor maps the keysyms we send using its own keymap,
        # so there is nothing for us to configure here:
        log("set_keymap%s", (server_source, force))
        self.set_current_config(server_source.set_default_keymap())

    def has_keyboard_device(self) -> bool:
        # the `Start` response tells us which device types the portal has granted us,
        # as a bitmask of `AvailableDeviceTypes`:
        if self.server.input_devices_count & AvailableDeviceTypes.KEYBOARD:
            return True
        if not self.warned:
            self.warned = True
            log.warn("Warning: the portal has not granted us a keyboard device")
            log.warn(" key events will be ignored")
        return False

    def do_process_keyboard_event(self, proto, wid: int, keyname: str, pressed: bool, kattrs: dict) -> None:
        if not self.has_keyboard_device():
            return
        super().do_process_keyboard_event(proto, wid, keyname, pressed, kattrs)

    def get_keycode(self, ss, client_keycode: int, keyname: str,
                    pressed: bool, modifiers: list, keyval: int, keystr: str, group: int) -> tuple[int, int]:
        # the keyname is the only field we can rely on:
        # it is an X11 keysym name with every client backend,
        # whereas `keyval` is only a keysym with some of them
        # (the win32 client sends a scancode there)
        keysym = parse_keysym(keyname)
        if not keysym and keystr:
            # last resort: use the character the client says this key produces
            keysym = unicode_keysym(ord(keystr[0]))
        log("get_keycode: keyname=%r, keystr=%r, client_keycode=%i, keyval=%i -> keysym=%#x",
            keyname, keystr, client_keycode, keyval, keysym)
        if not keysym:
            log.warn("Warning: no keysym found for key %r", keyname)
            return -1, group
        return keysym, group

    def fake_key(self, keysym: int, press: bool) -> None:
        # note: this is called with a keysym and not a keycode,
        # see this class's docstring
        if self.device and keysym > 0:
            self.device.press_keysym(keysym, press)


class ScreenCastKeyboardManager(ShadowKeyboardManager):
    """
    The `ScreenCast` portal interface has no input devices.
    """

    def make_keyboard_device(self) -> NoKeyboardDevice:
        return NoKeyboardDevice()

    def set_keymap(self, server_source, force=False) -> None:
        """ no input devices """
