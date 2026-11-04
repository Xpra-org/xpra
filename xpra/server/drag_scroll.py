# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from collections.abc import Callable, Sequence

from xpra.util.env import envbool, envint
from xpra.log import Logger

log = Logger("pointer")

# Drag-as-scroll heuristic: when button-1 is held on a window and the pointer
# moves vertically, treat the motion as a scroll event for downstream consumers
# (chiefly image filters that want temporal stability across scrolls, beyond
# wheel events).  Two complementary signals are used to separate scrollbar-thumb drags
# from text-selection and other button-1 drags:
#   (a) press-X close to the right edge of the window (scrollbar zone), and
#   (b) the drag motion remains near-vertical (low |dx|:|dy| ratio).
# (a) is the strong signal when window geometry is available.  (b) is the
# fallback when geometry can't be resolved.  Either signal classifying the
# drag as 'not a scrollbar drag' suppresses emits for the rest of that drag.
#
#   XPRA_DRAG_SCROLL_ENABLED                  master switch
#   XPRA_DRAG_SCROLL_MIN_DY_PX                cumulative |dy| (px) before emit
#   XPRA_DRAG_SCROLL_EMIT_INTERVAL_MS         minimum gap between emits per drag
#   XPRA_DRAG_SCROLLBAR_ZONE_PX               width (px) of the right-edge zone
#                                             treated as the scrollbar (~chromium
#                                             default scrollbar width + margin)
#   XPRA_DRAG_SCROLL_SELECTION_PROBE_DY_PX    accumulated |dy| at which the dx/dy
#                                             ratio is first evaluated; below this
#                                             motion is considered too short to
#                                             classify reliably
#   XPRA_DRAG_SCROLL_SELECTION_DX_PCT         % of |dy| that |dx| may reach before
#                                             the drag is latched as selection-like
#                                             (only consulted when zone is unknown)
DRAG_SCROLL_ENABLED = envbool("XPRA_DRAG_SCROLL_ENABLED", False)
DRAG_SCROLL_MIN_DY_PX = envint("XPRA_DRAG_SCROLL_MIN_DY_PX", 4)
DRAG_SCROLL_EMIT_INTERVAL_MS = envint("XPRA_DRAG_SCROLL_EMIT_INTERVAL_MS", 50)
DRAG_SCROLLBAR_ZONE_PX = envint("XPRA_DRAG_SCROLLBAR_ZONE_PX", 20)
DRAG_SCROLL_SELECTION_PROBE_DY_PX = envint("XPRA_DRAG_SCROLL_SELECTION_PROBE_DY_PX", 6)
DRAG_SCROLL_SELECTION_DX_PCT = envint("XPRA_DRAG_SCROLL_SELECTION_DX_PCT", 40)


class DragScrollTracker:
    """Track button-1 drags and record likely scrollbar motion on window sources."""

    __slots__ = ("window_sub", "get_pointer_window_position", "_button1_drag")

    def __init__(self, window_sub, get_pointer_window_position: Callable[[Sequence[int], dict], tuple[int, int] | None]):
        self.window_sub = window_sub
        self.get_pointer_window_position = get_pointer_window_position
        # Keyed by wid rather than device_id: legacy v4 protocol paths use
        # different device_id defaults for press (0) and motion (-1).
        # Populated on button-1 press, consumed on motion, cleared on release.
        self._button1_drag: dict[int, dict] = {}

    def clear(self) -> None:
        self._button1_drag.clear()

    def record_button(self, wid: int, button: int, pressed: bool, pointer: Sequence[int], props: dict) -> None:
        if not DRAG_SCROLL_ENABLED or button != 1 or not wid:
            return
        if pressed:
            self._button1_drag[wid] = self._make_button1_drag_state(wid, pointer, props)
        else:
            self._button1_drag.pop(wid, None)

    def _make_button1_drag_state(self, wid: int, pointer: Sequence[int], props: dict) -> dict:
        """Classify the press using its window-relative X and the window width."""
        try:
            press_x = int(pointer[0]) if pointer and len(pointer) >= 1 else 0
            press_y = int(pointer[1]) if pointer and len(pointer) >= 2 else 0
        except (TypeError, ValueError):
            press_x, press_y = 0, 0
        in_zone: bool | None = None
        window_position = self.get_pointer_window_position(pointer, props)
        window_width = self._lookup_window_width(wid)
        if window_position is not None and window_width:
            in_zone = (window_width - window_position[0]) <= DRAG_SCROLLBAR_ZONE_PX
        return {
            "last_x": press_x,
            "last_y": press_y,
            "accum_dx_abs": 0,
            "accum_dy_abs": 0,
            "in_scrollbar_zone": in_zone,
            "looks_like_selection": False,
            "last_emit_t_ms": 0.0,
        }

    def _lookup_window_width(self, wid: int) -> int | None:
        """Return the window width when its model and geometry are available."""
        if not (ws := self.window_sub):
            return None
        if not (model := ws.get_window(wid)):
            return None
        geom = model.get_geometry()
        if not geom or len(geom) < 4:
            return None
        return int(geom[2])

    def maybe_record_drag_scroll(self, wid: int, pdata: Sequence[int]) -> None:
        """Treat sustained button-1 + near-vertical motion as a scroll event.

        Distinguishes scrollbar-thumb drags from text-selection drags using
        two complementary signals: (a) press inside the window's right-edge
        scrollbar zone (strong, used when window geometry is reachable) and
        (b) accumulated |dx| vs |dy| ratio (fallback, used when geometry is
        unknown). Rejected drags suppress scroll events for their remaining lifetime.

        Keyed on ``wid`` (not ``device_id``) because the legacy v4 protocol
        paths used by the bundled HTML5 client deliver press with
        ``device_id=0`` and motion with ``device_id=-1``; keying on wid
        sidesteps that mismatch.  Otherwise rate-limited per drag via
        ``DRAG_SCROLL_MIN_DY_PX`` and ``DRAG_SCROLL_EMIT_INTERVAL_MS``.
        """
        if not DRAG_SCROLL_ENABLED or not wid:
            return
        drag = self._button1_drag.get(wid)
        if not drag or len(pdata) < 2:
            return
        try:
            cur_x = int(pdata[0])
            cur_y = int(pdata[1])
        except (TypeError, ValueError):
            return
        drag["accum_dx_abs"] += abs(cur_x - drag["last_x"])
        drag["accum_dy_abs"] += abs(cur_y - drag["last_y"])
        drag["last_x"] = cur_x
        drag["last_y"] = cur_y
        # Strong reject: press was clearly not on the scrollbar.
        if drag["in_scrollbar_zone"] is False:
            return
        # Fallback signal (only when zone is unknown): motion-direction.
        # Once the ratio crosses the threshold we latch the drag as
        # selection-like so a later returns-to-vertical micro-movement
        # doesn't reopen the emit gate.
        if drag["in_scrollbar_zone"] is None and not drag["looks_like_selection"]:
            if (drag["accum_dy_abs"] >= DRAG_SCROLL_SELECTION_PROBE_DY_PX
                    and drag["accum_dx_abs"] * 100 >= DRAG_SCROLL_SELECTION_DX_PCT * drag["accum_dy_abs"]):
                drag["looks_like_selection"] = True
                log("drag-as-scroll: wid=%i classified as selection-like (unknown zone, dx=%i dy=%i)",
                    wid, drag["accum_dx_abs"], drag["accum_dy_abs"])
        if drag["looks_like_selection"]:
            return
        # Pixel threshold + rate limit.
        if drag["accum_dy_abs"] < DRAG_SCROLL_MIN_DY_PX:
            return
        now_ms = monotonic() * 1000.0
        if (now_ms - drag["last_emit_t_ms"]) < DRAG_SCROLL_EMIT_INTERVAL_MS:
            return
        drag["last_emit_t_ms"] = now_ms
        drag["accum_dx_abs"] = 0
        drag["accum_dy_abs"] = 0
        log("drag-as-scroll: wid=%i y=%i zone=%s",
            wid, cur_y, drag["in_scrollbar_zone"])
        if window_sub := self.window_sub:
            for ss in window_sub.window_sources():
                ss.record_scroll_event(wid)
