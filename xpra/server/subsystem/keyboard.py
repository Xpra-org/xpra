# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
import threading
from typing import Any
from time import monotonic
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.system import is_X11
from xpra.util.io import which
from xpra.util.str_fn import bytestostr, Ellipsizer
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.common import noop, noerr
from xpra.net.common import Packet
from xpra.scripts.main import load_pid
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("keyboard")
ibuslog = Logger("keyboard", "ibus")

IBUS_DAEMON_COMMAND = os.environ.get("XPRA_IBUS_DAEMON_COMMAND",
                                     "ibus-daemon --xim --verbose --replace --panel=disable --desktop=xpra --daemonize")
EXPOSE_IBUS_LAYOUTS = envbool("XPRA_EXPOSE_IBUS_LAYOUTS", True)


def configure_imsettings_env(input_method: str) -> str:
    im = input_method.lower()
    if im in ("none", "no"):
        # the default: set DISABLE_IMSETTINGS=1, fallback to xim
        # that's because the 'ibus' 'immodule' breaks keyboard handling
        # unless its daemon is also running - and we don't know if it is..
        imsettings_env(True, "xim", "xim", "xim", "none", "@im=none")
    elif im == "keep":
        # do nothing and keep whatever is already set, hoping for the best
        pass
    elif im in ("xim", "ibus", "scim", "uim"):
        # ie: (False, "ibus", "ibus", "IBus", "@im=ibus")
        imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=" + im.lower())
    else:
        v = imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=" + im.lower())
        ibuslog.warn(f"using input method settings: {v}")
        ibuslog.warn(f"unknown input method specified: {input_method}")
        ibuslog.warn(" if it is correct, you may want to file a bug to get it recognized")
    return im


def imsettings_env(disabled, gtk_im_module, qt_im_module, clutter_im_module,
                   imsettings_module, xmodifiers) -> dict[str, str]:
    # for more information, see imsettings:
    # https://code.google.com/p/imsettings/source/browse/trunk/README
    if disabled is True:
        os.environ["DISABLE_IMSETTINGS"] = "1"  # this should override any XSETTINGS too
    elif disabled is False and ("DISABLE_IMSETTINGS" in os.environ):
        del os.environ["DISABLE_IMSETTINGS"]
    v = {
        "GTK_IM_MODULE": gtk_im_module,  # or "gtk-im-context-simple"?
        "QT_IM_MODULE": qt_im_module,  # or "simple"?
        "QT4_IM_MODULE": qt_im_module,
        "CLUTTER_IM_MODULE": clutter_im_module,
        "IMSETTINGS_MODULE": imsettings_module,  # or "xim"?
        "XMODIFIERS": xmodifiers,
        # not really sure what to do with those:
        # "IMSETTINGS_DISABLE_DESKTOP_CHECK"    : "true",
        # "IMSETTINGS_INTEGRATE_DESKTOP"        : "no"           #we're not a real desktop
    }
    os.environ.update(v)
    return v


def may_start_ibus(start_command: Callable):
    # maybe we are inheriting one from a dead session?
    session_dir = os.environ["XPRA_SESSION_DIR"]
    pidfile = os.path.join(session_dir, "ibus-daemon.pid")
    ibus_daemon_pid = load_pid(pidfile)
    # weak dependency on command subsystem:
    if not ibus_daemon_pid or not os.path.exists("/proc") or not os.path.exists(f"/proc/{ibus_daemon_pid}"):
        # start it late:
        def late_start():
            ibuslog(f"starting ibus: {IBUS_DAEMON_COMMAND!r}")
            proc = start_command("ibus", IBUS_DAEMON_COMMAND, True)
            if proc and proc.pid > 0:
                from xpra.util.pid import write_pid
                write_pid(pidfile, proc.pid)

        GLib.idle_add(late_start)


class KeyboardServer(StubServerMixin):
    """
    Mixin for servers that handle keyboards
    """

    def __init__(self):
        self.keymap_options: dict[str, Any] = {}
        self.mod_meanings = {}
        self.keyboard_config = None
        self.keymap_changing_timer = 0  # to ignore events when we know we are changing the configuration
        self.key_repeat = None
        # ugly: we're duplicating the value pair from "key_repeat" here:
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        # store list of currently pressed keys
        # (using a dict only so we can display their names in debug messages)
        self.keys_pressed: dict[int, str] = {}
        self.keys_timedout: dict[int, float] = {}
        # timers for cancelling key repeat when we get jitter
        self.key_repeat_timer = 0

        self.input_method = "keep"
        self.ibus_layouts: dict[str, Any] = {}

    def init(self, opts) -> None:
        for option in ("sync", "layout", "layouts", "variant", "variants", "options"):
            v = getattr(opts, f"keyboard_{option}", None)
            if v is not None:
                self.keymap_options[option] = v

        im = opts.input_method.lower()
        if im == "auto":
            ibus_daemon = which(IBUS_DAEMON_COMMAND.split(" ")[0])      # ie: "ibus-daemon"
            if ibus_daemon:
                im = "ibus"
            else:
                im = "none"
        self.input_method = im

    def setup(self) -> None:
        if is_X11():
            from xpra.gtk.error import xlog
            from xpra.x11.xkbhelper import clean_keyboard_state
            with xlog:
                clean_keyboard_state()
            with xlog:
                from xpra.x11.bindings.test import XTestBindings
                from xpra.x11.bindings.keyboard import X11KeyboardBindings
                XTest = XTestBindings()
                X11Keyboard = X11KeyboardBindings()
                if not XTest.hasXTest():
                    log.error("Error: keyboard and mouse disabled without XTest support")
                elif not X11Keyboard.hasXkb():
                    log.error("Error: limited keyboard support without XKB")
            self.input_method = configure_imsettings_env(self.input_method)
            if self.input_method == "ibus":
                start_command: Callable = getattr(self, "start_command", noop)
                may_start_ibus(start_command)

        ibuslog(f"input.setup() {EXPOSE_IBUS_LAYOUTS=}")
        self.watch_keymap_changes()
        self.keyboard_config = self.get_keyboard_config({"keymap": self.keymap_options})
        if EXPOSE_IBUS_LAYOUTS:
            # wait for ibus to be ready to query the layouts:
            from xpra.keyboard.ibus import with_ibus_ready
            with_ibus_ready(self.query_ibus_layouts)

    def query_ibus_layouts(self) -> None:
        try:
            from xpra.keyboard.ibus import query_ibus
        except ImportError as e:
            ibuslog(f"no ibus module: {e}")
        else:
            self.ibus_layouts = dict((k, v) for k, v in query_ibus().items() if k.startswith("engine"))
            ibuslog("loaded ibus layouts from %s: %s", threading.current_thread(),
                    Ellipsizer(self.ibus_layouts))

    def cleanup(self) -> None:
        noerr(self.clear_keys_pressed)
        self.keyboard_config = None
        if is_X11():
            from xpra.gtk.error import xswallow
            from xpra.x11.xkbhelper import clean_keyboard_state
            with xswallow:
                clean_keyboard_state()

    def reset_focus(self) -> None:
        self.clear_keys_pressed()

    def last_client_exited(self) -> None:
        self.clear_keys_pressed()

    def get_info(self, _proto) -> dict[str, Any]:
        return {"keyboard": self.get_keyboard_info()}

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {}

    def get_caps(self, _source) -> dict[str, Any]:
        if not self.key_repeat:
            return {}
        return {
            "key_repeat": self.key_repeat,
            "key_repeat_modifiers": True,
        }

    def parse_hello(self, ss, caps: typedict, send_ui: bool) -> None:
        if send_ui:
            self.parse_hello_ui_keyboard(ss, caps)

    def send_initial_data(self, ss, caps, send_ui: bool, share_count: int) -> None:
        if send_ui:
            self.send_ibus_layouts(ss)

    def send_ibus_layouts(self, ss):
        send_ibus_layouts = getattr(ss, "send_ibus_layouts", noop)
        ibuslog(f"{send_ibus_layouts=}")
        if send_ibus_layouts == noop:
            return

        # wait for ibus, so we will have the layouts if they exist
        def ibus_is_ready() -> None:
            send_ibus_layouts(self.ibus_layouts)
        from xpra.keyboard.ibus import with_ibus_ready
        with_ibus_ready(ibus_is_ready)

    def watch_keymap_changes(self) -> None:
        """ GTK servers will start listening for the 'keys-changed' signal """

    def parse_hello_ui_keyboard(self, ss, c: typedict) -> None:
        other_ui_clients: list[str] = [s.uuid for s in self._server_sources.values() if s != ss and s.ui_client]
        kb_client = hasattr(ss, "keyboard_config")
        if not kb_client:
            return
        ss.keyboard_config = self.get_keyboard_config(c)  # pylint: disable=assignment-from-none

        if not other_ui_clients:
            # so only activate this feature afterwards:
            self.key_repeat = c.intpair("key_repeat") or (0, 0)
            self.set_keyboard_repeat(self.key_repeat)
            # always clear modifiers before setting a new keymap
            ss.make_keymask_match(c.strtupleget("modifiers"))
        else:
            self.set_keyboard_repeat(None)
            self.key_repeat = (0, 0)
        self.key_repeat_delay, self.key_repeat_interval = self.key_repeat
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
        if EXPOSE_IBUS_LAYOUTS and self.ibus_layouts:
            info["ibus"] = self.ibus_layouts
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
        if backend == "ibus" and name:
            from xpra.keyboard.ibus import set_engine, get_engine_layout_spec
            if set_engine(name):
                ibuslog(f"ibus set engine to {name!r}")
                layout, variant, options = get_engine_layout_spec()
                ibuslog(f"ibus layout: {layout} {variant=}, {options=}")
        if ss.set_layout(layout, variant, options):
            self.set_keymap(ss, force=True)

    def _process_keymap_changed(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        props = typedict(packet.get_dict(1))
        ss = self.get_server_source(proto)
        if ss is None:
            return
        log("received new keymap from client: %s", Ellipsizer(packet))
        other_ui_clients = [s.uuid for s in self._server_sources.values() if s != ss and s.ui_client]
        if other_ui_clients:
            log.warn("Warning: ignoring keymap change as there are %i other clients", len(other_ui_clients))
            return
        kc = getattr(ss, "keyboard_config", None)
        if kc and kc.enabled:
            kc.parse_options(props)
            self.set_keymap(ss, True)
            modifiers = props.get("modifiers", [])
            ss.make_keymask_match(modifiers)

    def set_keyboard_layout_group(self, grp: int) -> None:
        # only actually implemented in X11ServerBase
        pass

    def _process_key_action(self, proto, packet: Packet) -> None:
        if self.readonly:
            return
        wid = packet.get_wid()
        keyname = packet.get_str(2)
        pressed = packet.get_bool(3)
        modifiers = packet.get_strs(4)
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
        ss.user_event()

    def get_keycode(self, ss, client_keycode: int, keyname: str,
                    pressed: bool, modifiers: list, keyval: int, keystr: str, group: int):
        return ss.get_keycode(client_keycode, keyname, pressed, modifiers, keyval, keystr, group)

    def fake_key(self, keycode, press):
        log("fake_key%s is not implemented", (keycode, press))

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
        ss.user_event()

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
        log("clear_keys_pressed() is not implemented")

    def get_keyboard_config(self, props=None) -> Any | None:
        log("get_keyboard_config(%s) is not implemented", props)
        return None

    def set_keyboard_repeat(self, key_repeat) -> None:
        log("set_keyboard_repeat(%s)", key_repeat)

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
