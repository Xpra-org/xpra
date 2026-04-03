# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import glob
import json
import os.path
from collections.abc import Sequence
from typing import NoReturn

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.exit_codes import ExitValue, ExitCode
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.util.parsing import TRUE_OPTIONS
from xpra.util.str_fn import csv, sorted_nicely, print_nested_dict
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
            if ev.strget("event", "") == "sync":
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
        log.info("%4i event=%s", event.get("index", 0), etype)
        if not self.window and etype != "new":
            log.warn("Warning: event %r received, but window %#x is gone!", etype, self.wid)
            return
        if etype == "new":
            geom: tuple[int, int, int, int] = event.inttupleget("geometry", (0, 0, 1, 1))
            metadata = typedict(event.dictget("metadata", {}))
            self.window = self.client.make_client_window(self.wid, geom, metadata)
            log("new-window: %s", self.window)
            self.window.show()
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
            options = typedict(event.dictget("options", {}))
            self.window.draw_region(x, y, width, height, coding, data, rowstride, options, [])
        elif etype == "cursor-default":
            # set_cursor_data(self, cursor_data: Sequence) -> None:
            self.window.set_cursor_data(())
        elif etype == "cursor-data":
            encoding = event.strget("encoding", "")
            if encoding != "png":
                log.warn("Warning: cursor data encoding %r is not supported", encoding)
                return
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
            cursor_data = ("raw", 0, 0, w, h, xhot, yhot, serial, name, pixels)
            self.window.set_cursor_data(cursor_data)
        elif etype == "pointer-position":
            position = event.inttupleget("position", (0, 0, 1, 1))
            if len(position) >= 4:
                self.window.motion_cancels_pointer_overlay = False
                self.window.show_pointer_overlay(position)
        elif etype in ("key-event", "key"):
            log("key-event: %s", event)
            log.info("key: %r", event.dictget("key", {}).get("name", ""))
        elif etype == "clipboard":
            log("clipboard: %s", event.get("data"))
            # only "clipboard-contents" packets generate this file:
            contents = may_load_blob(event, "contents", False)
            if contents:
                log.info("clipboard contents: %s", contents)
        elif etype == "sync":
            log("sync point")
            geometry = event.inttupleget("geometry", (0, 0, 1, 1))
            self.window.move_resize(*geometry)
            metadata = typedict(event.dictget("metadata", {}))
            self.window.update_metadata(metadata)
        elif etype == "metadata":
            metadata = typedict(event.dictget("metadata", {}))
            log("metadata: %s", metadata)
            self.window.update_metadata(metadata)
        elif etype == "resize":
            size = event.inttupleget("size", (0, 0))
            log.warn("resize: %s", size)
            if size != (0, 0):
                self.window.resize(*size)
        elif etype == "move-resize":
            geometry = event.inttupleget("geometry", (0, 0, 0, 0))
            log.warn("move-resize: %s", geometry)
            if max(geometry) > 0:
                self.window.move_resize(*geometry)
        else:
            log.warn("%r not handled yet!", etype)

    def find_sync_index(self, target_ts: int):
        sync_idx: int = -1
        for ts, idx in self.sync_index:
            if ts <= target_ts:
                sync_idx = idx
            else:
                break
        return sync_idx

    def seek_to(self, target_ms: int) -> None:
        sync_idx = self.find_sync_index(target_ms)
        if sync_idx < 0:
            log.warn("Warning: no sync point at or before %dms for wid 0x%x – seek skipped",
                     target_ms, self.wid)
            return

        # start at previous sync point:
        self.event_index = sync_idx
        # fast-replay any events between the sync point and target_ms
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

    def __init__(self, wid: int, *args):
        self.wid = wid

    def show(self):
        pass

    def draw_region(self, x, y, width, height, coding, data, rowstride, options, callbacks):
        pass

    def set_cursor_data(self, data):
        pass

    def show_pointer_overlay(self, position):
        pass

    def resize(self, *size):
        pass

    def move_resize(self, *geometry):
        pass

    def update_metadata(self, metadata):
        pass


class Replay(GObjectClientAdapter):

    def __init__(self, options):
        GObjectClientAdapter.__init__(self)
        self.client_type = "replay"
        self.record_directory = os.path.join(os.path.abspath(os.getcwd()), "record")
        self.sequence = 0
        self.window_replay: dict[int, WindowReplay] = {}
        # all times are in milliseconds:
        self.event_timer = 0
        self.time_index = 0
        self.last_timestamp = 0
        rate = options.refresh_rate.lower()
        self.rate = 1.0 if (rate in TRUE_OPTIONS or rate == "auto") else 1/float(rate)

    def __repr__(self):
        return "Replay"

    def send(self, packet_type:str, *args, **kwargs) -> None:
        log("ignoring request to send %r", packet_type)

    def make_client_window(self, wid: int, geometry: tuple[int, int, int, int], metadata: typedict):
        return WindowModel(wid)

    def load(self) -> None:
        windows = os.listdir(self.record_directory)
        for wid_str in windows:
            wid = int(wid_str, 16)
            directory = os.path.join(self.record_directory, wid_str)
            wr = WindowReplay(self, wid, directory)
            wr.load()
            self.window_replay[wid] = wr
            self.last_timestamp = max(self.last_timestamp, wr.last_event().get("timestamp", 0))

    def run(self) -> ExitValue:
        if not os.path.exists(self.record_directory):
            return ExitCode.FILE_NOT_FOUND
        self.load()
        log.info("%s replaying record for %i windows: %s",
                 self, len(self.window_replay), csv(hex(wid) for wid in self.window_replay.keys()))
        log.info(" using rate=%f", self.rate)
        log.info(" found %i events", sum(wr.count() for wr in self.window_replay.values()))
        log.info(" total time: %i seconds", self.last_timestamp // 1000)
        self.schedule_next_event()
        return super().run()

    @staticmethod
    def get_root_size() -> tuple[int, int]:
        from xpra.gtk.util import get_root_size
        return get_root_size()

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
        delay = max(0, round((timestamp - self.time_index) * self.rate))
        log("schedule_next_event: in %ims, %s", delay, event.get("filename", ""))
        self.event_timer = self.timeout_add(delay, self.process_next_event, event)

    def end_of_replay(self):
        log.info("no more events!")
        self.quit(ExitCode.OK)

    def cancel_event_timer(self) -> None:
        et = self.event_timer
        if et:
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
        raise "replay"


def do_main(config) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Replay"):
        replay = Replay(config)
        return int(replay.run())


def main() -> int:
    from xpra.scripts.config import make_defaults_struct
    return do_main(make_defaults_struct())


if __name__ == "__main__":
    main()
