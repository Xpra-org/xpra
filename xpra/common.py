# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Protocol, Any
from collections.abc import Callable, Sized, Iterable, Sequence

from xpra.constants import NotificationID, Gravity

try:
    # Python 3.11 and later:
    from typing import Self
except ImportError:     # pragma: no cover
    Self = Any

try:
    # Python 3.12 and later:
    from collections.abc import Buffer

    class SizedBuffer(Buffer, Sized, Protocol):
        pass
except ImportError:
    class SizedBuffer(Sized, Protocol):
        def __buffer__(self):
            raise NotImplementedError()


def gravity_str(v) -> str:
    try:
        return Gravity(v).name
    except ValueError:
        return str(v)


def noop(*_args, **_kwargs) -> None:
    """ do nothing """


def noerr(fn: Callable, *args):
    # noinspection PyBroadException
    try:
        return fn(*args)
    except Exception:
        return None


def is_covered_by_opaque_region(opaque_region: Sequence[tuple], w: int, h: int) -> bool:
    """Check if any opaque-region rectangle fully covers a window of size w x h.

    Windows with 32-bit depth (ARGB) may declare themselves effectively opaque
    via _NET_WM_OPAQUE_REGION. Each entry is (ox, oy, ow, oh); if any single
    rectangle encloses the entire window area (0, 0, w, h), the window is opaque.
    """
    return any(
        ox <= 0 and oy <= 0 and ox + ow >= w and oy + oh >= h
        for ox, oy, ow, oh in opaque_region
    )


def roundup(n: int, m: int) -> int:
    return (n + m - 1) & ~(m - 1)


def uniq(seq: Iterable) -> list:
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def skipkeys(d: dict, *keys) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def subsystem_name(c: type) -> str:
    return c.__name__.replace("Server", "").rstrip("_").lower()


def may_show_progress(obj, pct: int, text="") -> None:
    show_progress = getattr(obj, "show_progress", noop)
    show_progress(pct, text)


def may_notify_client(obj, nid : NotificationID | int, summary, body, *args, **kwargs) -> None:
    notify_client = getattr(obj, "notify_client", notify_to_log)
    notify_client(nid, summary, body, *args, **kwargs)
    # hide splash progress:
    may_show_progress(obj, 100, f"notification: {summary}")


def notify_to_log(nid : NotificationID | int, summary, body, *args, **kwargs) -> None:
    from xpra.log import Logger
    notifylog = Logger("notify")
    notifylog("may_notify_client(%s, %s, %s, %s, %s)", nid, summary, body, args, kwargs)
    notifylog.info("%s", summary)
    if body:
        for x in body.splitlines():
            notifylog.info(" %s", x)


def force_size_constraint(width: int, height: int) -> dict[str, dict[str, Any]]:
    size = width, height
    return {
        "size-constraints": {
            "maximum-size": size,
            "minimum-size": size,
            "base-size": size,
        },
    }
