# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Shared scaffolding for the terminal client tests:
parsers for the kitty graphics escape streams the client emits,
and the fake client / subsystem stand-ins used across the test files.
"""

from xpra.util.objects import typedict

APC = b"\x1b_G"         # application program command, kitty graphics introducer
ST = b"\x1b\\"          # string terminator
DECSC = b"\x1b7"        # save cursor position
DECRC = b"\x1b8"        # restore cursor position

# the terminal geometry the tests pretend to run in: (columns, rows, width, height)
TERMINAL_SIZE = (100, 30, 1000, 600)


def split_escapes(data: bytes) -> list:
    """ split a stream of kitty graphics escape sequences into (control, payload) pairs """
    escapes = []
    pos = 0
    while pos < len(data):
        if data[pos:pos + len(APC)] != APC:
            raise ValueError(f"unexpected data at offset {pos}: {data[pos:pos + 8]!r}")
        end = data.index(ST, pos)
        body = data[pos + len(APC):end]
        if b";" in body:
            control, payload = body.split(b";", 1)
        else:
            control, payload = body, b""
        escapes.append((control.decode("ascii"), payload))
        pos = end + len(ST)
    return escapes


def parse_output(data: bytes) -> list:
    """
    Decode a terminal byte stream into commands:
    `("graphics", {key: value}, payload)`, `("cup", (row, col))`, `("save",)`, `("restore",)`
    """
    commands = []
    pos = 0
    while pos < len(data):
        if data[pos] != 0x1b:
            raise ValueError(f"unexpected data at offset {pos}: {data[pos:pos + 8]!r}")
        if data[pos:pos + len(APC)] == APC:
            end = data.index(ST, pos)
            control, _, payload = data[pos + len(APC):end].partition(b";")
            keys = {}
            for kv in control.decode("ascii").split(","):
                if kv:
                    key, _, value = kv.partition("=")
                    keys[key] = value
            commands.append(("graphics", keys, payload))
            pos = end + len(ST)
        elif data[pos:pos + 2] == b"\x1b[":
            end = pos + 2
            while end < len(data) and not 0x40 <= data[end] <= 0x7E:
                end += 1
            body = data[pos + 2:end].decode("ascii")
            if chr(data[end]) == "H":
                row, _, col = body.partition(";")
                commands.append(("cup", (int(row), int(col))))
            pos = end + 1
        elif data[pos:pos + 2] == DECSC:
            commands.append(("save",))
            pos += 2
        elif data[pos:pos + 2] == DECRC:
            commands.append(("restore",))
            pos += 2
        else:
            raise ValueError(f"unexpected escape sequence at offset {pos}: {data[pos:pos + 8]!r}")
    return commands


def actions(commands) -> list:
    return [cmd[1].get("a") for cmd in commands if cmd[0] == "graphics"]


def graphics_keys(commands, action: str) -> list:
    return [cmd[1] for cmd in commands if cmd[0] == "graphics" and cmd[1].get("a") == action]


def placements(data: bytes) -> list[tuple[int, int]]:
    """ the `(image id, z index)` of every placement in a terminal byte stream, in order """
    found: list[tuple[int, int]] = []
    pos = 0
    while True:
        pos = data.find(APC, pos)
        if pos < 0:
            return found
        end = data.index(ST, pos)
        keys: dict[str, str] = {}
        control = data[pos + len(APC):end].partition(b";")[0]
        for kv in control.decode("ascii").split(","):
            key, _, value = kv.partition("=")
            keys[key] = value
        if keys.get("a") == "p":
            found.append((int(keys["i"]), int(keys["z"])))
        pos = end + len(ST)


class FakeWindow:
    """ the little of a `ClientWindow` that the client's input routing looks at """

    def __init__(self, wid: int, pos=(0, 0), size=(100, 100), override_redirect=False):
        self.wid = wid
        self._pos = pos
        self._size = size
        self._mapped = True
        self._metadata = typedict()
        self._transient_for = 0
        self._override_redirect = override_redirect
        self.placements = 0

    def is_OR(self) -> bool:
        return self._override_redirect

    def refresh_placement(self) -> None:
        self.placements += 1


class FakeWindowSubsystem:
    """ replaces the composed `window` subsystem, recording what the client sends it """

    def __init__(self):
        # the real subsystem exposes the registry under this name:
        self.windows: dict[int, FakeWindow] = {}
        self._id_to_window = self.windows
        self.focus_events: list[tuple] = []
        self.refreshes: list[int] = []
        self._window_with_grab = 0

    def cleanup(self) -> None:
        """ the client cleans up every subsystem """

    def get_window(self, wid: int):
        return self.windows.get(wid)

    def update_focus(self, wid: int, gotit: bool) -> None:
        self.focus_events.append((wid, gotit))

    def send_refresh(self, wid: int) -> None:
        self.refreshes.append(wid)


class FakePointerSubsystem:
    def __init__(self):
        self.positions: list[tuple] = []
        self.buttons: list[tuple] = []
        self.wheels: list[tuple] = []

    def cleanup(self) -> None:
        """ the client cleans up every subsystem """

    def send_mouse_position(self, device_id, wid, pos, modifiers=None, buttons=None, props=None) -> None:
        self.positions.append((device_id, wid, pos, tuple(modifiers or ()), tuple(buttons or ())))

    def send_button(self, device_id, wid, button, pressed, pointer, modifiers, buttons, props) -> None:
        self.buttons.append((device_id, wid, button, pressed, pointer, tuple(modifiers), tuple(buttons)))

    def wheel_event(self, device_id, wid, deltax, deltay, pointer) -> None:
        self.wheels.append((device_id, wid, deltax, deltay, pointer))


class FakeDisplaySubsystem:
    def __init__(self):
        self.screen_changes = 0

    def cleanup(self) -> None:
        """ the client cleans up every subsystem """

    def screen_size_changed(self) -> None:
        self.screen_changes += 1


class FakeKeyboardSubsystem:
    def __init__(self):
        self.actions: list[tuple] = []

    def cleanup(self) -> None:
        """ the client cleans up every subsystem """

    def handle_key_action(self, window, key_event) -> bool:
        self.actions.append((window, key_event.keyname, key_event.pressed, tuple(key_event.modifiers)))
        return False
