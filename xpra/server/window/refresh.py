# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Pending refresh regions and scheduling, independent of the display and GLib."""

from __future__ import annotations

from collections.abc import Callable, Container, Mapping
from dataclasses import dataclass
from math import sqrt
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xpra.util.objects import Scheduler
    from xpra.util.rectangle import rectangle


@dataclass(frozen=True, slots=True)
class RefreshSettings:
    """Window dimensions, delays in milliseconds, and the congestion estimate."""

    width: int
    height: int
    base_delay: int
    min_delay: int = 50
    batch_delay: float = 0
    congestion: float = 0


def classify_refresh(encoding: str, image_depth: int, client_options: Mapping[str, Any], *,
                     refresh_quality: int, true_lossless: bool, lossy_formats: Container[str]) -> tuple[int, bool]:
    if encoding.startswith("png"):
        return 100, image_depth > 32 or image_depth == 30
    if encoding.startswith("rgb") or encoding == "mmap":
        return 100, False
    quality = client_options.get("quality", 0)
    lossy = any((quality < refresh_quality, client_options.get("csc") in lossy_formats,
                 client_options.get("scaled_size") is not None))
    return quality, lossy or (encoding == "jpeg" and true_lossless)


def get_refresh_delay(settings: RefreshSettings, percent: int, *, initial: bool = False) -> int | float:
    if initial:
        multiplier = sqrt(percent * (1+settings.congestion))//10
        delay = int(settings.base_delay * multiplier)
    else:
        delay = int(settings.base_delay * percent // 100)
    return max(settings.batch_delay*5, settings.min_delay, delay)


class RefreshController:
    """Updates may arrive from the encode thread; timer callbacks run in the UI thread.

    The clock and stored timestamps use seconds; scheduler delays use milliseconds.
    """

    def __init__(self, scheduler: Scheduler, clock: Callable[[], float], *,
                 can_refresh: Callable[[], bool], on_refresh: Callable[[], Any],
                 add_region: Callable[[rectangle], int] | None = None,
                 remove_region: Callable[[rectangle], None] | None = None):
        self.scheduler = scheduler
        self.clock = clock
        self.can_refresh = can_refresh
        self.on_refresh = on_refresh
        self._add_region = add_region or self.add_region
        self._remove_region = remove_region or self.remove_region
        self.regions: list[rectangle] = []
        self.timer: int = 0
        self.event_time: float = 0
        self.target_time: float = 0
        self.last_message: tuple[float, str] | None = None

    def add_region(self, region: rectangle) -> int:
        from xpra.util.rectangle import add_rectangle
        return add_rectangle(self.regions, region)

    def remove_region(self, region: rectangle) -> None:
        from xpra.util.rectangle import remove_rectangle
        remove_rectangle(self.regions, region)

    def clear_regions(self) -> list[rectangle]:
        regions = self.regions
        self.regions = []
        return regions

    def take_regions(self) -> tuple[float, list[rectangle]]:
        event_time = self.event_time
        self.event_time = 0
        return event_time, self.clear_regions()

    def cancel(self) -> None:
        if timer := self.timer:
            self.timer = 0
            self.scheduler.source_remove(timer)
            self.event_time = 0
            self.target_time = 0

    def _record(self, now: float, message: str) -> str:
        self.last_message = now, message
        return message

    def update(self, region: rectangle, settings: RefreshSettings | None = None, *, lossy: bool,
               auto_refresh: bool = False, exclude: rectangle | None = None) -> str:
        now = self.clock()
        if not lossy or auto_refresh:
            self._remove_region(region)
            if not self.timer:
                return self._record(now, "lossless - nothing to do")
            if not self.regions:
                self.cancel()
                return self._record(now, "covered all regions that needed a refresh, cancelling refresh timer")
            return self._record(now, "removed rectangle from regions, keeping existing refresh timer")
        assert settings is not None, "lossy updates require refresh settings"
        if settings.width <= 0 or settings.height <= 0:
            self.cancel()
            return self._record(now, "cancelling refresh - window cleaned up?")
        window_pixels = settings.width*settings.height
        region_pixels = region.width*region.height
        if exclude:
            window_pixels -= exclude.width*exclude.height
            if intersection := region.intersection_rect(exclude):
                region_pixels -= intersection.width*intersection.height
        # The source's hook can split this between normal and video refreshes.
        added_pixels = self._add_region(region)
        percent = 100 if window_pixels <= 0 else 100*region_pixels//window_pixels
        if percent == 100:
            self.cancel()
        if not self.timer:
            if region_pixels <= 0 or not self.regions:
                return self._record(now, "nothing to refresh")
            self.event_time = now
            delay = get_refresh_delay(settings, percent, initial=True)
            self.target_time = now + delay/1000.0
            self.timer = self.scheduler.timeout_add(delay, self._timeout)
            return self._record(now, f"scheduling refresh in {delay}ms (pct={percent}, batch={settings.batch_delay})")
        due_pixels = sum(rect.width*rect.height for rect in self.regions)
        if added_pixels >= due_pixels//2:
            percent = 100*due_pixels//window_pixels
        delay = get_refresh_delay(settings, percent)
        max_time = self.event_time + 5*settings.base_delay/1000.0
        target_time = self.target_time
        self.target_time = min(max_time, max(target_time, now + delay/1000.0))
        added_ms = int(1000*(self.target_time-target_time))
        due_ms = int(1000*(self.target_time-now))
        if self.target_time == target_time:
            return self._record(now, f"unchanged refresh: due in {due_ms}ms, pct={percent}")
        return self._record(now, "re-scheduling refresh: due in %ims, %ims added - sched_delay=%s, pct=%i, batch=%i)" % (
            due_ms, added_ms, delay, percent, settings.batch_delay))

    def postpone_for_damage(self, settings: RefreshSettings, now: float) -> None:
        if not self.timer or not self.regions:
            return
        pixels = sum(rect.width*rect.height for rect in tuple(self.regions))
        if pixels > 0:
            percent = int(min(100, 100*pixels//(settings.width*settings.height)) * (1+settings.congestion))
            delay = max(settings.min_delay, int(settings.base_delay * percent // 100))
            self.target_time = max(self.target_time, now + delay/1000.0)

    def postpone(self, seconds: float, now: float) -> None:
        if self.target_time:
            self.target_time = max(self.target_time, now+seconds)

    def _timeout(self) -> bool:
        # Called by the scheduler in the UI thread. Never repeat this source;
        # install a new timer if an update moved the target time.
        self.timer = 0
        if not self.can_refresh():
            self.event_time = 0
            return False
        if self.event_time == 0:
            return False
        delta = self.target_time - self.clock()
        if delta < 0.050:
            self.on_refresh()
        else:
            self.timer = self.scheduler.timeout_add(int(delta*1000), self._timeout)
        return False
