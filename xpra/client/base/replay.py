# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import glob
import json
import os.path
from time import monotonic
from collections.abc import Callable, Sequence
from typing import Any, NoReturn

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.common import noop
from xpra.exit_codes import ExitValue, ExitCode
from xpra.platform.paths import initial_cwd
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.util.parsing import TRUE_OPTIONS
from xpra.util.str_fn import csv, sorted_nicely, print_nested_dict, Ellipsizer
from xpra.net import common as net_common
from xpra.log import Logger

log = Logger("client")

net_common.BACKWARDS_COMPATIBLE = False

CACHE = True


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        data = f.read()
    return json.loads(data)


def load_events_placeholders(directory: str) -> dict[int, dict]:
    """
    Creates dictionaries for all the json event files found,
    the only thing recorded in the dictionary is the filename,
    so that we can actually load the data when needed.
    """
    events: dict[int, dict] = {}
    if not os.path.exists(directory):
        log.warn("Warning: event directory %r not found!", directory)
        return {}
    log("load_events_placeholders(%r)", directory)
    for json_filename in sorted_nicely(glob.glob(f"{directory}/*.json")):
        try:
            # ie: "/some/path/to/record/40000c/0.json" -> 0
            base = os.path.basename(json_filename)
            sequence = int(os.path.splitext(base)[0])
        except ValueError:
            log.warn("Warning: invalid json event filename %r in %r", json_filename, directory)
            continue
        event = {
            "filename": json_filename,
        }
        events[sequence] = event
    log.info(f"loaded %i events from {directory!r}", len(events))
    return events


def may_load(event: dict) -> None:
    """
    given an event dictionary,
    ensure that it is fully loaded from file.
    """
    if len(event) > 1:
        # already loaded
        return
    # this is a placeholder, load the real data:
    filename = event.get("filename", "")
    if not filename:
        raise RuntimeError("missing filename from event %r" % event)
    event.update(load_json(filename))


def may_load_blob(event: dict, ext="", warn=True) -> bytes:
    data = event.get("data", b"")
    if data:
        # we already have the data
        return data
    # this data should have been saved separately,
    # re-construct the filename from this event's filename:
    filename = event["filename"]
    blob_path = os.path.splitext(filename)[0] + f".{ext}"
    if not os.path.exists(blob_path):
        fn = log.warn if warn else log
        fn("Warning: %s blob %r not found!", event.strget("event"), blob_path)
        return b""
    return load_binary_file(blob_path)


def free_event(event: dict) -> None:
    """
    forgets all the other keys to save memory,
    only the `filename` is kept so we can call `may_load()` on it again.
    """
    keys_to_remove = tuple(key for key in event if key != "filename")
    for key in keys_to_remove:
        event.pop(key, None)


def to_cursor_data(event: typedict) -> tuple:
    if not event:
        return ()
    encoding = event.strget("encoding", "")
    if encoding != "png":
        log.warn("Warning: cursor data encoding %r is not supported", encoding)
        return ()
    w = event.intget("w", 0)
    h = event.intget("h", 0)
    xhot = event.intget("xhot", 0)
    yhot = event.intget("yhot", 0)
    serial = event.intget("serial", 0)
    name = event.strget("name", "")
    pixels = event.bytesget("pixels")
    if not pixels:
        cpixels = may_load_blob(event, ext=encoding)
        from xpra.client.subsystem.cursor import decompress_cursor_data
        pixels = decompress_cursor_data(encoding, cpixels, serial)
    return "raw", 0, 0, w, h, xhot, yhot, serial, pixels, name


class WindowReplay:

    def __init__(self, client, wid: int, directory: str):
        self.client = client
        self.wid = wid
        self.directory = directory
        self.events: dict[int, dict] = {}
        self.group_index = 0
        self.event_index = 0
        self.cursor: tuple[str, int ,int, int, int, int, int, int, bytes, str] | tuple = ()
        self.sync_index: Sequence[tuple[int, int]] = []
        self.all_timestamps: Sequence[int] = []
        self.window = None

    def load(self):
        self.events: dict[int, dict] = load_events_placeholders(self.directory)
        self.ensure_sync_index()

    def ensure_sync_index(self) -> None:
        """
        Walk every event once to record (timestamp, event_index) for sync
        events and to collect all timestamps.
        Results are cached.
        """
        sync: list[tuple[int, int]] = []
        all_ts: list[int] = []
        for idx in sorted(self.events.keys()):
            ev = typedict(self.events[idx])
            may_load(ev)
            ts = ev.intget("timestamp", -1)
            if ts >= 0:
                all_ts.append(ts)
            if ev.strget("event", "") in ("sync", "new"):
                sync.append((ts, idx))
            if not CACHE:
                free_event(ev)
        self.sync_index: list[tuple[int, int]] = sync
        self.all_timestamps: list[int] = all_ts

    def get_all_timestamps(self) -> Sequence[int]:
        return self.all_timestamps

    def get_sync_timestamps(self) -> Sequence[int]:
        return tuple(set(ts for ts, _ in self.sync_index))

    def get_event(self) -> dict:
        if self.event_index >= len(self.events):
            return {}
        event = self.events[self.event_index]
        may_load(event)
        return event

    def count(self) -> int:
        return len(self.events)

    def first_event(self) -> dict:
        event = self.events[0]
        may_load(event)
        return event

    def last_event(self) -> dict:
        last_id: int = max(self.events.keys())
        event = self.events.get(last_id, {})
        may_load(event)
        return event

    def next_event(self) -> dict:
        if self.event_index < len(self.events):
            self.event_index += 1
            while self.event_index not in self.events and self.event_index < len(self.events):
                log.warn("Warning: event %i missing!", self.event_index)
                self.event_index += 1
        return self.get_event()

    def event_info(self, etype: str, msg: str):
        self.client.notable_event_cb(etype, msg)

    def process_event(self) -> None:
        event = typedict(self.get_event())
        try:
            self.do_process_event(event)
        except Exception:
            log.error("Error processing event, trying to continue", exc_info=True)
            print_nested_dict(event, prefix=" ", print_fn=log.error)
        self.next_event()

    def do_process_event(self, event: typedict) -> None:
        etype = event.strget("event", "")
        log("%-8i wid=%6x - %4i : %s", event.get("timestamp", 0), self.wid, event.get("index", 0), etype)
        if etype in ("pointer-button", "key-event", "key"):
            # Input state must still be updated when its source window has gone.
            self.client.process_input_event(event)
        if etype in ("grab", "ungrab"):
            # handled before the `window is gone` check below,
            # so that a grab release can never be lost:
            grab = etype == "grab"
            self.client.set_grabbed(self.wid if grab else 0, event.intget("timestamp", 0))
            self.event_info(etype, "pointer grabbed" if grab else "pointer released")
            return
        if not self.window and etype not in ("new", "sync"):
            log.warn("Warning: event %r received, but window %#x is gone!", etype, self.wid)
            return

        def event_info(msg: str) -> None:
            self.event_info(etype, msg)
        if etype == "new":
            geom: tuple[int, int, int, int] = event.inttupleget("geometry", (0, 0, 1, 1))
            metadata = typedict(event.dictget("metadata"))
            if self.window:
                self.window.update_metadata(metadata)
                self.window.move_resize(*geom)
            else:
                self.window = self.client.make_client_window(self.wid, geom, metadata)
            log("new-window: %s", self.window)
            self.window.show()
            self.may_focus(event)
            self.may_grab(event)
        elif etype == "destroy":
            self.window.destroy()
            self.window = None
        elif etype == "draw":
            # ie: encoding="png"
            encoding = event.get("encoding", "")
            data = event.bytesget("data") or may_load_blob(event, ext=encoding)
            if CACHE:
                event["data"] = data        # cache it for next time
            x, y, width, height = event.inttupleget("geometry", (0, 0, 1, 1))
            coding = event.strget("encoding", "")
            rowstride = event.intget("rowstride", 0)
            options = typedict(event.dictget("options"))
            self.window.draw_region(x, y, width, height, coding, data, rowstride, options, [])
        elif etype == "cursor-default":
            self.window.set_cursor_data(())
        elif etype == "cursor-data":
            cursor_data = to_cursor_data(event)
            log("cursor-data: %s", Ellipsizer(cursor_data))
            self.window.set_cursor_data(cursor_data)
        elif etype in ("pointer-position", "pointer-motion"):
            position = event.inttupleget("position", ())
            if len(position) >= 4:
                log("pointer motion: %s", position)
                rx, ry = position[2:4]
                self.window.motion_cancels_pointer_overlay = False
                self.window.show_pointer_overlay((rx, ry, 10, monotonic()))
        elif etype == "pointer-button":
            pressed = event.boolget("pressed")
            button = event.intget("button", 0)
            if button:
                event_info(f"button {button} {'pressed' if pressed else 'released'}")
        elif etype == "pointer-wheel":
            button = event.intget("button", 0)
            distance = event.intget("distance", 0)
            if button and distance:
                event_info(f"button {button} moved {distance}")
        elif etype in ("key-event", "key"):
            name = event.dictget("key").get("name", "")
            event_info("key: %r" % name)
        elif etype == "clipboard":
            log("clipboard: %s", event.get("data"))
            # only "clipboard-contents" packets generate this file:
            contents = may_load_blob(event, "contents", False)
            if contents:
                event_info("contents: %s" % (contents,))
        elif etype == "sync":
            log("sync point")
            geometry = event.inttupleget("geometry", (0, 0, 1, 1))
            metadata = typedict(event.dictget("metadata"))
            if not self.window:
                # a seek can land on a sync point without ever replaying the `new` event
                # which created the window - but a sync point is a complete snapshot,
                # so we can create the window from it:
                log("creating window %#x from a sync point", self.wid)
                self.window = self.client.make_client_window(self.wid, geometry, metadata)
                self.window.show()
            cursor = event.get("cursor-data")
            if isinstance(cursor, dict):
                self.window.set_cursor_data(to_cursor_data(typedict(cursor)))
            else:
                self.window.set_cursor_data(())
            self.window.update_metadata(metadata)
            self.window.move_resize(*geometry)
            self.may_focus(event)
            self.may_grab(event)
        elif etype == "metadata":
            metadata = typedict(event.dictget("metadata"))
            log("metadata: %s", metadata)
            self.window.update_metadata(metadata)
        elif etype == "resize":
            size = event.inttupleget("size", (0, 0))
            log("resize: %s", size)
            if size != (0, 0):
                self.window.resize(*size)
        elif etype == "move-resize":
            geometry = event.inttupleget("geometry", (0, 0, 0, 0))
            log("move-resize: %s", geometry)
            if max(geometry) > 0:
                self.window.move_resize(*geometry)
        else:
            log.warn("%r not handled yet!", etype)

    def may_focus(self, event: typedict) -> None:
        """
        `new` and `sync` events carry the focus state of the window.
        Only the window that had the focus is of interest: the others
        simply don't claim it.
        """
        if event.boolget("focused"):
            self.client.set_focused(self.wid, event.intget("timestamp", 0))

    def may_grab(self, event: typedict) -> None:
        """
        `new` and `sync` events carry the grab state of the window.
        Unlike the focus, the usual case is that no window holds the grab,
        so a window must be able to release it - but only the window
        which actually held it can do so.
        """
        timestamp = event.intget("timestamp", 0)
        if event.boolget("grabbed"):
            self.client.set_grabbed(self.wid, timestamp)
        elif self.client.grabbed == self.wid:
            self.client.set_grabbed(0, timestamp)

    def find_sync_index(self, target_ts: int) -> int:
        """
        The index of the last sync point at or before `target_ts`,
        or -1 if the window did not exist yet.
        """
        sync_idx: int = -1
        for ts, idx in self.sync_index:
            if ts <= target_ts:
                sync_idx = idx
            else:
                break
        return sync_idx

    def seek(self, target_ms: int, current_ms: int = -1) -> None:
        sync_idx = self.find_sync_index(target_ms)
        incremental = 0 <= current_ms <= target_ms and self.find_sync_index(current_ms) == sync_idx
        if not incremental:
            if sync_idx < 0:
                # no sync point at or before the target: the window did not exist yet
                if self.wid > 0 and self.window:
                    self.window.destroy()
                    self.window = None
                sync_idx = 0
            # Rewinds and forward seeks across sync points jump directly to
            # the latest snapshot at or before the target.
            self.event_index = sync_idx
        # Fast-replay from the current position or selected sync point.
        while self.event_index < len(self.events):
            ev = self.events.get(self.event_index)
            if not ev:
                break
            may_load(ev)
            if typedict(ev).intget("timestamp", 0) > target_ms:
                break
            self.process_event()


class WindowModel:
    """
    This fake window class doesn't do anything with the requests.
    """

    def __init__(self, wid: int, *_args):
        self.wid = wid
        self.show = self.draw_region = self.set_cursor_data = self.show_pointer_overlay = noop
        self.resize = self.move_resize = self.update_metadata = self.present = noop
        self.destroy = noop


def log_notable_event(etype: str, msg: str) -> None:
    log.info("%s: %s", etype, msg)


class Replay(GObjectClientAdapter):

    def __init__(self, options):
        GObjectClientAdapter.__init__(self)
        self.client_type = "replay"
        self.record_directory = os.path.join(initial_cwd, "record")
        self.sequence = 0
        self.window_replay: dict[int, WindowReplay] = {}
        # all times are in milliseconds:
        self.event_timer = 0
        self.time_index = 0
        self.last_timestamp = 0
        self.is_playing = True
        rate = options.refresh_rate.lower()
        self.rate = 1.0 if (rate in TRUE_OPTIONS or rate == "auto") else 1/float(rate)
        self._wall_start: float = 0.0    # monotonic seconds when play last (re)started
        self._replay_start: int = 0      # time_index value at that moment
        self.notable_event_cb = log_notable_event
        # the window which had the focus, and the timestamp it was claimed at:
        self.focused = 0
        self.focus_timestamp = 0
        # the window which held the pointer grab, and the timestamp it was claimed at:
        self.grabbed = 0
        self.grab_timestamp = 0
        # Input state is global rather than tied to a window.  Keep it here so
        # the replay controls can visualize it without synthesizing real input.
        self.pressed_pointer_buttons: set[int] = set()
        self.pressed_keys: dict[int | str, tuple[str, bool]] = {}
        self.input_events: list[dict] = []
        self.input_state_cb: Callable[[tuple[int, ...], tuple[tuple[str, bool], ...]], Any] = noop
        self._seeking = False

    def __repr__(self):
        return "Replay"

    def send(self, packet_type:str, *args, **kwargs) -> None:
        log("ignoring request to send %r", packet_type)

    def make_client_window(self, wid: int, geometry: tuple[int, int, int, int], metadata: typedict):
        return WindowModel(wid)

    def set_focused(self, wid: int, timestamp: int = 0) -> None:
        """
        For now, we don't replay the focus itself:
        we just ensure that the window which had it ends up on top.
        Sync points are replayed in window order rather than in chronological
        order, so the most recent claim wins.
        """
        if timestamp < self.focus_timestamp:
            return
        self.focus_timestamp = timestamp
        self.focused = wid
        wr = self.window_replay.get(wid)
        window = wr.window if wr else None
        log("set_focused(%#x, %i) window=%s", wid, timestamp, window)
        if window:
            window.present()

    def set_grabbed(self, wid: int, timestamp: int = 0) -> None:
        """
        The pointer grab is never replayed for real: taking a grab here would
        confiscate the pointer and keyboard of whoever is watching the replay,
        and nothing guarantees that we would ever get to release it.
        We just show which window was holding it.
        Sync points are replayed in window order rather than in chronological
        order, so the most recent claim wins.
        """
        if timestamp < self.grab_timestamp:
            return
        self.grab_timestamp = timestamp
        wr = self.window_replay.get(wid)
        window = wr.window if wr else None
        if wid and not window:
            # the window is gone, and so is its grab:
            # the X11 server releases it when the window is destroyed
            wid = 0
        if self.grabbed == wid:
            return
        self.grabbed = wid
        log("set_grabbed(%#x, %i) window=%s", wid, timestamp, window)
        if window:
            window.present()

    def set_input_state_callback(
            self, callback: Callable[[tuple[int, ...], tuple[tuple[str, bool], ...]], Any]) -> None:
        self.input_state_cb = callback
        self.notify_input_state()

    def notify_input_state(self) -> None:
        buttons = tuple(sorted(self.pressed_pointer_buttons))
        keys = tuple(self.pressed_keys.values())
        self.input_state_cb(buttons, keys)

    @staticmethod
    def _key_id(key: typedict) -> int | str:
        keycode = key.intget("keycode", -1)
        if keycode >= 0:
            return keycode
        return key.strget("name", "")

    def process_input_event(self, event: typedict, notify: bool = True) -> None:
        etype = event.strget("event", "")
        if etype == "pointer-button":
            button = event.intget("button", 0)
            if button:
                if event.boolget("pressed"):
                    self.pressed_pointer_buttons.add(button)
                else:
                    self.pressed_pointer_buttons.discard(button)
        elif etype in ("key-event", "key"):
            key = typedict(event.dictget("key"))
            name = key.strget("name", "")
            key_id = self._key_id(key)
            if name and key.boolget("press"):
                self.pressed_keys[key_id] = (name, key.boolget("is-modifier"))
            else:
                self.pressed_keys.pop(key_id, None)
        else:
            return
        if notify and not self._seeking:
            self.notify_input_state()

    def rebuild_input_state(self, target_ms: int) -> None:
        """Reconstruct global input state after a timeline seek."""
        self.pressed_pointer_buttons.clear()
        self.pressed_keys.clear()
        for event in self.input_events:
            if event.get("timestamp", 0) > target_ms:
                break
            self.process_input_event(typedict(event), notify=False)
        self.notify_input_state()

    def get_modifier_keys(self) -> tuple[str, ...]:
        modifiers: list[str] = []
        for event in self.input_events:
            key = typedict(typedict(event).dictget("key"))
            name = key.strget("name", "")
            if key.boolget("is-modifier") and name and name not in modifiers:
                modifiers.append(name)
        return tuple(modifiers)

    def load(self) -> None:
        windows = os.listdir(self.record_directory)
        for wid_str in windows:
            wid = int(wid_str, 16)
            directory = os.path.join(self.record_directory, wid_str)
            wr = WindowReplay(self, wid, directory)
            wr.load()
            self.window_replay[wid] = wr
            self.last_timestamp = max(self.last_timestamp, wr.last_event().get("timestamp", 0))
            for event in wr.events.values():
                may_load(event)
                if event.get("event") in ("pointer-button", "key-event", "key"):
                    self.input_events.append(dict(event))
        self.input_events.sort(key=lambda event: (event.get("timestamp", 0),
                                                  event.get("index", 0), event.get("wid", 0)))

    def run(self) -> ExitValue:
        if not os.path.exists(self.record_directory):
            return ExitCode.FILE_NOT_FOUND
        log.info("%s replaying record for %i windows: %s",
                 self, len(self.window_replay), csv(hex(wid) for wid in self.window_replay.keys()))
        log.info(" using rate=%f", self.rate)
        log.info(" found %i events", sum(wr.count() for wr in self.window_replay.values()))
        log.info(" total time: %i seconds", self.last_timestamp // 1000)
        self._anchor()
        self.schedule_next_event()
        return super().run()

    @staticmethod
    def get_root_size() -> tuple[int, int]:
        from xpra.gtk.util import get_root_size
        return get_root_size()

    def _anchor(self) -> None:
        """Record the wall-clock / replay-time pair used by visual_time."""
        self._wall_start = monotonic()
        self._replay_start = self.time_index

    @property
    def visual_time(self) -> int:
        """Continuously interpolated playhead position (ms), smooth between events."""
        if not self.is_playing or not self._wall_start:
            return self.time_index
        elapsed_ms = (monotonic() - self._wall_start) * 1000
        return min(self.last_timestamp, int(self._replay_start + elapsed_ms * self.rate))

    def set_rate(self, rate: float) -> None:
        """Change playback rate, re-anchoring so visual_time stays continuous."""
        if self.is_playing:
            self.time_index = self.visual_time
            self._anchor()
        self.rate = rate

    def toggle_play_pause(self) -> None:
        if self.is_playing:
            self.time_index = self.visual_time
            self.is_playing = False
            self.cancel_event_timer()
        else:
            self.is_playing = True
            self._anchor()
            self.schedule_next_event()

    def seek(self, target_ms: int) -> None:
        """
        Seek every window to *target_ms*.
        Forward seeks within the current sync interval replay incrementally.
        Rewinds and forward seeks across sync points jump to the latest sync
        point at or before the target.
        """
        was_playing = self.is_playing
        self.is_playing = False
        self.cancel_event_timer()

        current_ms = self.time_index
        self.time_index = target_ms
        if target_ms < current_ms:
            # Older sync points must be allowed to reclaim focus and grab.
            self.focus_timestamp = 0
            self.grabbed = 0
            self.grab_timestamp = 0
        self._seeking = True
        try:
            for wr in self.window_replay.values():
                wr.seek(target_ms, current_ms)
            # Window streams are replayed one at a time above.  Input is global,
            # so rebuild it in timestamp order to handle a press and release
            # which happened over different windows.
            self.rebuild_input_state(target_ms)
        finally:
            self._seeking = False

        self.is_playing = was_playing
        if self.is_playing:
            self._anchor()
            self.schedule_next_event()

    def schedule_next_event(self) -> None:
        event = self.find_next_event()
        if not event:
            self.end_of_replay()
            return
        timestamp = event.get("timestamp", -1)
        if timestamp < 0:
            log.warn("Warning: event %r does not have a valid timestamp", event)
            return
        # timestamp is in milliseconds:
        delay = max(0, round((timestamp - self.time_index) / self.rate))
        log("schedule_next_event: in %ims, %s", delay, event.get("filename", ""))
        self.event_timer = self.timeout_add(delay, self.process_next_event, event)

    def end_of_replay(self):
        log.info("no more events!")
        self.quit(ExitCode.OK)

    def cancel_event_timer(self) -> None:
        if et := self.event_timer:
            self.event_timer = 0
            self.source_remove(et)

    def find_next_event(self) -> dict:
        """
        find the nearest event after the current time index
        """
        candidates: dict[int, dict] = {}
        for model in self.window_replay.values():
            event = model.get_event()
            if not event:
                continue
            timestamp = event.get("timestamp", -1)
            if timestamp < self.time_index:
                continue
            candidates[timestamp] = event
        if not candidates:
            return {}
        next_due = min(candidates.keys())
        return candidates[next_due]

    def process_next_event(self, event: dict) -> None:
        self.event_timer = 0
        assert event
        # log("process_next_event: %s", Ellipsizer(event, limit=200))
        log("process_next_event: %s", event.get("event", ""))
        model = self.window_replay[event["wid"]]
        model.process_event()
        # move time forward to this event:
        self.time_index = max(self.time_index, event.get("timestamp", 0))
        self.schedule_next_event()

    def cleanup(self):
        self.cancel_event_timer()

    def exit(self) -> NoReturn:
        sys.exit(int(self.exit_code or ExitCode.OK))

    @staticmethod
    def force_quit(exit_code: ExitValue = ExitCode.FAILURE) -> NoReturn:
        from xpra import os_util
        os_util.force_quit(int(exit_code))

    def client_toolkit(self) -> str:
        return "replay"


def do_main(config) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Replay"):
        replay = Replay(config)
        replay.load()
        return int(replay.run())


def main() -> int:
    from xpra.scripts.config import make_defaults_struct
    return do_main(make_defaults_struct())


if __name__ == "__main__":
    main()
