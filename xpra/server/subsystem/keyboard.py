# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any
from time import monotonic

from xpra.os_util import gi_import
from xpra.util.str_fn import bytestostr, Ellipsizer
from xpra.util.objects import typedict
from xpra.keyboard.common import DELAY_KEYBOARD_DATA
from xpra.common import noerr, BACKWARDS_COMPATIBLE
from xpra.net.common import Packet
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("keyboard")


class KeyboardServer(StubServerMixin):
    """
    Mixin for servers that handle keyboards
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        self.keymap_options: dict[str, Any] = {}
        self.mod_meanings = {}
        self.keyboard_device = None
        self.keyboard_config = None
        self.keymap_changing_timer = 0  # to ignore events when we know we are changing the configuration
        # ugly: we're duplicating the value pair from "key_repeat" here:
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        # store list of currently pressed keys
        # (using a dict only so we can display their names in debug messages)
        self.keys_pressed: dict[int, str] = {}
        self.keys_timedout: dict[int, float] = {}
        # timers for cancelling key repeat when we get jitter
        self.key_repeat_timer = 0
        self.keys_pressed: dict[int, Any] = {}

    def init(self, opts) -> None:
        for option in ("sync", "layout", "layouts", "variant", "variants", "options"):
            v = getattr(opts, f"keyboard_{option}", None)
            if v is not None:
                self.keymap_options[option] = v

    def setup(self) -> None:
        self.keyboard_device = self.make_keyboard_device()
        if not self.keyboard_device:
            log.warn("Warning: keyboard device not available, using NoKeyboardDevice")
            from xpra.keyboard.nokeyboard import NoKeyboardDevice
            self.keyboard_device = NoKeyboardDevice()
        log("keyboard_device=%s", self.keyboard_device)

        self.watch_keymap_changes()
        self.keyboard_config = self.get_keyboard_config({"keymap": self.keymap_options})

    def make_keyboard_device(self):
        from xpra.platform.keyboard import get_keyboard_device
        return get_keyboard_device()

    def cleanup(self) -> None:
        self.stop_keymap_timer()
        noerr(self.clear_keys_pressed)
        self.keyboard_config = None

    def keymap_changed(self, *_args) -> None:
        if self.keymap_changing_timer:
            return
        self.keymap_changing_timer = GLib.timeout_add(500, self.do_keymap_changed)

    def do_keymap_changed(self) -> None:
        self.keymap_changing_timer = 0
        self._keys_changed()

    def stop_keymap_timer(self) -> None:
        kct = self.keymap_changing_timer
        if kct:
            self.keymap_changing_timer = 0
            GLib.source_remove(kct)

    def last_client_exited(self) -> None:
        self.clear_keys_pressed()

    def get_ui_info(self, _proto, **kwargs) -> dict[str, Any]:
        info = self.get_keyboard_info()
        device = self.keyboard_device
        if not self.readonly and device:
            info["state"] = {
                "keys_pressed": tuple(self.keys_pressed.keys()),
                "keycodes-down": device.get_keycodes_down(),
                "layout-group": device.get_layout_group(),
                "key-repeat": {
                    "delay": self.key_repeat_delay,
                    "interval": self.key_repeat_interval,
                }
            }
        return {"keyboard": info}

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {}

    def get_caps(self, _source) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "key_repeat": (self.key_repeat_delay, self.key_repeat_interval),
        }
        if BACKWARDS_COMPATIBLE:
            caps["key_repeat_modifiers"] = True
            caps["keyboard.fast-switching"] = True
        return caps

    def parse_hello(self, ss, caps: typedict, send_ui: bool) -> None:
        if send_ui:
            self.parse_hello_ui_keyboard(ss, caps)

    def watch_keymap_changes(self) -> None:
        """ GTK servers will start listening for the 'keys-changed' signal """

    def parse_hello_ui_keyboard(self, ss, c: typedict) -> None:
        other_ui_clients: list[str] = [s.uuid for s in self._server_sources.values() if s != ss and s.ui_client]
        kb_client = hasattr(ss, "keyboard_config")
        if not kb_client:
            return
        ss.keyboard_config = self.get_keyboard_config(c)  # pylint: disable=assignment-from-none

        delay, interval = (500, 30)
        if not other_ui_clients:
            # so only activate this feature afterwards:
            delay, interval = c.intpair("key_repeat") or (500, 30)
            # always clear modifiers before setting a new keymap
            ss.make_keymask_match(c.strtupleget("modifiers"))
        self.set_keyboard_repeat(delay, interval)
        if not DELAY_KEYBOARD_DATA:
            self.set_keymap(ss)

    def get_keyboard_info(self) -> dict[str, Any]:
        start = monotonic()
        info = {
            "repeat": {
                "delay": self.key_repeat_delay,
                "interval": self.key_repeat_interval,
            },
            "keys_pressed": tuple(self.keys_pressed.values()),
            "modifiers": self.mod_meanings,
        }
        kc = self.keyboard_config
        if kc:
            info.update(kc.get_info())
        log("get_keyboard_info took %ims", (monotonic() - start) * 1000)
        return info

    def _process_layout_changed(self, proto, packet: Packet) -> None:
        log(f"layout-changed: {packet}")
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            return
        layout = packet.get_str(1)
        variant = packet.get_str(2)
        options = backend = name = ""
        if len(packet) >= 4:
            options = packet.get_str(3)
        if len(packet) >= 6:
            backend = packet.get_str(4)
            name = packet.get_str(5)
        self.set_backend(backend, name)
        if ss.set_layout(layout, variant, options):
            self.set_keymap(ss, force=True)

    def set_backend(self, backend: str, name: str) -> None:
        """ overriden in X11 keyboard module """

    def _process_keymap_changed(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        props = typedict(packet.get_dict(1))
        force = True
        if len(packet) > 2:
            force = packet.get_bool(2)
        ss = self.get_server_source(proto)
        if ss is None:
            return
        log("received new keymap from client: %s", Ellipsizer(packet))
        kc = getattr(ss, "keyboard_config", None)
        if kc and kc.enabled:
            kc.parse_options(props)
            ss.make_keymask_match([])
            self.set_keymap(ss, force)
            if "modifiers" in props:
                modifiers = props.get("modifiers", [])
                ss.make_keymask_match(modifiers)

    def _process_key_action(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        wid = packet.get_wid()
        keyname = packet.get_str(2)
        pressed = packet.get_bool(3)
        # `get_keycode` may have to change modifiers to match the key, so we need a mutable list:
        modifiers = list(packet.get_strs(4))
        keyval = packet.get_u32(5)
        keystr = packet.get_str(6)
        client_keycode = packet.get_u32(7)
        group = packet.get_u8(8)
        ss = self.get_server_source(proto)
        if not hasattr(ss, "keyboard_config"):
            return
        keyname = str(keyname)
        keystr = str(keystr)
        modifiers = list(str(x) for x in modifiers)
        self.set_ui_driver(ss)
        keycode, group = self.get_keycode(ss, client_keycode, keyname, pressed, modifiers, keyval, keystr, group)
        log("process_key_action(%s) server keycode=%s, group=%i", packet, keycode, group)
        if group >= 0 and keycode >= 0:
            self.set_keyboard_layout_group(group)
        # currently unused: (group, is_modifier) = packet[8:10]
        self._focus(ss, wid, None)
        ss.make_keymask_match(modifiers, keycode, ignored_modifier_keynames=[keyname])
        # negative keycodes are used for key events without a real keypress/unpress
        # for example, used by win32 to send Caps_Lock/Num_Lock changes
        if keycode >= 0:
            try:
                is_mod = ss.is_modifier(keyname, keycode)
                self._handle_key(wid, pressed, keyname, keyval, keycode, modifiers, is_mod, ss.keyboard_config.sync)
            except Exception as e:
                log("process_key_action%s", (proto, packet), exc_info=True)
                log.error("Error: failed to %s key", ["unpress", "press"][pressed])
                log.estr(e)
                log.error(" for keyname=%s, keyval=%i, keycode=%i", keyname, keyval, keycode)
        ss.emit("user-event", "key-action")

    def get_keycode(self, ss, client_keycode: int, keyname: str,
                    pressed: bool, modifiers: list[str], keyval: int, keystr: str, group: int):
        return ss.get_keycode(client_keycode, keyname, pressed, modifiers, keyval, keystr, group)

    def fake_key(self, keycode: int, press: bool) -> None:
        log("fake_key(%s, %s)", keycode, press)
        if self.keyboard_device:
            self.keyboard_device.press_key(keycode, press)

    def _handle_key(self, wid: int, pressed: bool, name: str, keyval: int, keycode: int,
                    modifiers: list, is_mod: bool = False, sync: bool = True):
        """
            Does the actual press/unpress for keys
            Either from a packet (_process_key_action) or timeout (_key_repeat_timeout)
        """
        log("handle_key(%s)", (wid, pressed, name, keyval, keycode, modifiers, is_mod, sync))
        if pressed and wid and wid not in self._id_to_window:
            log("window %s is gone, ignoring key press", wid)
            return
        if keycode < 0:
            log.warn("ignoring invalid keycode=%s", keycode)
            return
        if keycode in self.keys_timedout:
            del self.keys_timedout[keycode]

        def press() -> None:
            log("handle keycode pressing   %3i: key '%s'", keycode, name)
            self.keys_pressed[keycode] = name
            self.fake_key(keycode, True)

        def unpress() -> None:
            log("handle keycode unpressing %3i: key '%s'", keycode, name)
            if keycode in self.keys_pressed:
                del self.keys_pressed[keycode]
            self.fake_key(keycode, False)

        if pressed:
            if keycode not in self.keys_pressed:
                press()
                if not sync and not is_mod:
                    # keyboard is not synced: client manages repeat so unpress
                    # it immediately unless this is a modifier key
                    # (as modifiers are synced via many packets: key, focus and mouse events)
                    unpress()
            else:
                log("handle keycode %s: key %s was already pressed, ignoring", keycode, name)
        else:
            if keycode in self.keys_pressed:
                unpress()
            else:
                log("handle keycode %s: key %s was already unpressed, ignoring", keycode, name)
        if not is_mod and sync and self.key_repeat_delay > 0 and self.key_repeat_interval > 0:
            self._key_repeat(wid, pressed, name, keyval, keycode, modifiers, is_mod, self.key_repeat_delay)

    def cancel_key_repeat_timer(self) -> None:
        krt = self.key_repeat_timer
        if krt:
            self.key_repeat_timer = 0
            GLib.source_remove(krt)

    def _key_repeat(self, wid: int, pressed: bool, keyname: str, keyval: int, keycode: int,
                    modifiers: list, is_mod: bool, delay_ms: int = 0) -> None:
        """ Schedules/cancels the key repeat timeouts """
        self.cancel_key_repeat_timer()
        if pressed:
            delay_ms = min(1500, max(250, delay_ms))
            log("scheduling key repeat timer with delay %s for %s / %s", delay_ms, keyname, keycode)
            now = monotonic()
            self.key_repeat_timer = GLib.timeout_add(delay_ms, self._key_repeat_timeout,
                                                     now, delay_ms, wid, keyname, keyval, keycode, modifiers, is_mod)

    def _key_repeat_timeout(self, when, delay_ms: int, wid: int, keyname: str, keyval: int, keycode: int,
                            modifiers: list, is_mod: bool) -> None:
        self.key_repeat_timer = 0
        now = monotonic()
        log("key repeat timeout for %s / '%s' - clearing it, now=%s, scheduled at %s with delay=%s",
            keyname, keycode, now, when, delay_ms)
        self._handle_key(wid, False, keyname, keyval, keycode, modifiers, is_mod, True)
        self.keys_timedout[keycode] = now

    def _process_key_repeat(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "keyboard_config"):
            return
        wid = packet.get_wid()
        keyname = packet.get_str(2)
        keyval = packet.get_u32(3)
        client_keycode = packet.get_u32(4)
        modifiers = packet.get_strs(5)
        keyname = bytestostr(keyname)
        modifiers = [bytestostr(x) for x in modifiers]
        group = 0
        if len(packet) >= 7:
            group = packet.get_u8(6)
        keystr = ""
        keycode, group = ss.get_keycode(client_keycode, keyname, modifiers, keyval, keystr, group)
        if group >= 0:
            self.set_keyboard_layout_group(group)
        # key repeat uses modifiers from a pointer event, so ignore mod_pointermissing:
        ss.make_keymask_match(modifiers)
        if not ss.keyboard_config.sync:
            # this check should be redundant: clients should not send key-repeat without
            # having keyboard_sync enabled
            return
        if keycode not in self.keys_pressed:
            # the key is no longer pressed, has it timed out?
            when_timedout = self.keys_timedout.get(keycode, None)
            if when_timedout:
                del self.keys_timedout[keycode]
            now = monotonic()
            if when_timedout and (now - when_timedout) < 30:
                # not so long ago, just re-press it now:
                log("key %s/%s, had timed out, re-pressing it", keycode, keyname)
                self.keys_pressed[keycode] = keyname
                self.fake_key(keycode, True)
        is_mod = ss.is_modifier(keyname, keycode)
        self._key_repeat(wid, True, keyname, keyval, keycode, modifiers, is_mod, self.key_repeat_interval)
        ss.emit("user-event", "key-repeat")

    def _process_keyboard_sync_enabled_status(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not hasattr(ss, "keyboard_config"):
            return
        kc = ss.keyboard_config
        if kc:
            kc.sync = bool(packet[1])
            log("toggled keyboard-sync to %s for %s", kc.sync, ss)

    def _keys_changed(self) -> None:
        log("input server: the keymap has been changed, keymap_changing_timer=%s", self.keymap_changing_timer)
        if not self.keymap_changing_timer:
            for ss in self._server_sources.values():
                if hasattr(ss, "keys_changed"):
                    ss.keys_changed()

    def clear_keys_pressed(self) -> None:
        log("clear_keys_pressed()")
        if self.readonly:
            return
        # make sure the timer doesn't fire and interfere:
        self.cancel_key_repeat_timer()
        keycodes = tuple(self.keys_pressed.keys())
        self.keyboard_device.clear_keys_pressed(keycodes)
        self.keys_pressed = {}

    def set_keyboard_layout_group(self, grp: int) -> None:
        """ overriden in x11 keyboard """

    def set_keyboard_repeat(self, delay: int, interval: int) -> None:
        self.key_repeat_delay = delay
        self.key_repeat_interval = interval
        device = self.keyboard_device
        if not device:
            return
        device.set_repeat_rate(delay, interval)

    def get_keyboard_config(self, props=None) -> Any | None:
        log("get_keyboard_config(%s) is not implemented", props)
        return None

    def set_keymap(self, ss, force: bool = False) -> None:
        log("set_keymap(%s, %s)", ss, force)

    def init_packet_handlers(self) -> None:
        self.add_packets(
            # keyboard:
            "key-action", "key-repeat", "layout-changed", "keymap-changed",
            main_thread=True
        )
        # legacy:
        self.add_packet_handler("set-keyboard-sync-enabled", self._process_keyboard_sync_enabled_status, True)
