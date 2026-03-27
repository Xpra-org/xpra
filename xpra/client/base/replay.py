# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import glob
import json
import os.path
from typing import NoReturn

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.exit_codes import ExitValue, ExitCode
from xpra.util.io import load_binary_file
from xpra.util.str_fn import csv, sorted_nicely, Ellipsizer
from xpra.log import Logger

log = Logger("client")


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


def may_load_draw(event: dict) -> None:
    if event.get("event", "") != "draw":
        # wrong event type
        return
    if event.get("data", b""):
        # we already have the data
        return
    encoding = event.get("encoding", "")
    if not encoding:
        log.warn("Warning: draw packet without encoding!")
        return
    # pixel data should have been saved separately:
    filename = event["filename"]
    image_path = os.path.splitext(filename)[0] + f".{encoding}"
    if not os.path.exists(image_path):
        log.warn("Warning: draw image %r not found!", image_path)
        return
    event["data"] = load_binary_file(image_path)


def free_event(event: dict) -> None:
    """
    forgets all the other keys to save memory,
    only the `filename` is kept so we can call `may_load()` on it again.
    """
    keys_to_remove = tuple(key for key in event if key != "filename")
    for key in keys_to_remove:
        event.pop(key, None)


class WindowReplay:

    def __init__(self, wid: int, directory: str):
        self.wid = wid
        self.directory = directory
        self.events: dict[int, dict] = load_events_placeholders(self.directory)
        self.group_index = 0
        self.event_index = 0

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
        return self.get_event()


class Replay(GObjectClientAdapter):

    def __init__(self):
        GObjectClientAdapter.__init__(self)
        self.client_type = "replay"
        self.record_directory = os.path.join(os.path.abspath(os.getcwd()), "record")
        self.sequence = 0
        self.window_replay: dict[int, WindowReplay] = {}
        # all times are in milliseconds:
        self.event_timer = 0
        self.time_index = 0
        self.last_timestamp = 0

    def run(self) -> ExitValue:
        if not os.path.exists(self.record_directory):
            return ExitCode.FILE_NOT_FOUND
        windows = os.listdir(self.record_directory)
        for wid_str in windows:
            wid = int(wid_str, 16)
            directory = os.path.join(self.record_directory, wid_str)
            wr = WindowReplay(wid, directory)
            self.window_replay[wid] = wr
            self.last_timestamp = max(self.last_timestamp, wr.last_event().get("timestamp", 0))
        log.info("replaying record for %i windows: %s",
                 len(self.window_replay), csv(hex(wid) for wid in self.window_replay.keys()))
        log.info(" found %i events", sum(wr.count() for wr in self.window_replay.values()))
        log.info(" total time: %i seconds", self.last_timestamp // 1000)
        self.schedule_next_event()
        return super().run()

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
        delay = max(0, timestamp - self.time_index)
        log("schedule_next_event: in %ims: %s", delay, Ellipsizer(event))
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
        # move time forward to this event:
        self.time_index = max(self.time_index, event.get("timestamp", 0))
        model = self.window_replay[event["wid"]]
        model.next_event()
        self.schedule_next_event()

    def cleanup(self):
        self.cancel_event_timer()

    def exit(self) -> NoReturn:
        sys.exit(int(self.exit_code or ExitCode.OK))

    def force_quit(exit_code: ExitValue = ExitCode.FAILURE) -> NoReturn:
        from xpra import os_util
        os_util.force_quit(int(exit_code))

    def client_toolkit(self) -> str:
        raise "replay"


def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Replay"):
        return int(Replay().run())


if __name__ == "__main__":
    main()
