# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
import glob
import json
import os.path

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.exit_codes import ExitValue, ExitCode
from xpra.util.io import load_binary_file
from xpra.util.str_fn import csv, sorted_nicely
from xpra.log import Logger

log = Logger("client")


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        data = f.read()
    return json.loads(data)


class WindowReplay:

    def __init__(self, wid: int, directory: str):
        self.wid = wid
        self.directory = directory
        self.sequence = 0
        self.events: list[dict] = []

    def load(self) -> None:
        events_dir = os.path.join(self.directory, str(self.sequence))
        if not os.path.exists(events_dir):
            log.warn("Warning: event directory %r not found!", events_dir)
            return
        self.events = []
        for path in sorted_nicely(glob.glob(f"{events_dir}/*.json")):
            event_data = load_json(path)
            if event_data.get("event", "") == "draw":
                # pixel data should have been saved separately:
                encoding = event_data.get("encoding", "")
                if encoding:
                    image_path = os.path.splitext(path)[0] + f".{encoding}"
                    if os.path.exists(image_path):
                        event_data["data"] = load_binary_file(image_path)
            self.events.append(event_data)
        log.info(f"loaded %i events from {events_dir!r}")


class Replay(GObjectClientAdapter):

    def __init__(self):
        GObjectClientAdapter.__init__(self)
        self.client_type = "replay"
        self.record_directory = os.path.join(os.path.abspath(os.getcwd()), "record")
        self.sequence = 0
        self.update_timer = 0
        self.window_replay: dict[int, WindowReplay] = {}

    def run(self) -> ExitValue:
        if not os.path.exists(self.record_directory):
            return ExitCode.FILE_NOT_FOUND
        windows = os.listdir(self.record_directory)
        for wid_str in windows:
            wid = int(wid_str, 16)
            directory = os.path.join(self.record_directory, wid_str)
            wr = WindowReplay(wid, directory)
            self.window_replay[wid] = wr
            wr.load()
        log.info("replaying record for %i windows: %s",
                 len(self.window_replay), csv(hex(wid) for wid in self.window_replay.keys()))
        return super().run()

    def cleanup(self):
        self.cancel_next_update()
        super().cleanup()

    def cancel_next_update(self) -> None:
        ut = self.update_timer
        if ut:
            self.update_timer = 0
            self.source_remove(ut)

    def client_toolkit(self) -> str:
        raise "replay"
