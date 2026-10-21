# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Mapping
from typing import Any

from xpra.log import Logger
from xpra.scripts.config import InitExit
from xpra.util.objects import merge_dicts

log = Logger("subsystems")


def call(subsystems: Mapping[str, Any], method: str, *args, reverse: bool = False) -> None:
    """Call each subsystem in order, letting fatal initialization errors propagate."""
    subs = list(subsystems.values())
    if reverse:
        subs.reverse()
    for sub in subs:
        fn = getattr(sub, method, None)
        if not callable(fn):
            log.warn("Warning: no %r callable on %s", method, sub)
            continue
        try:
            fn(*args)
        except InitExit:
            raise
        except Exception:
            log.warn(f"Error: in {sub}.{method}", exc_info=True)


def merge(subsystems: Mapping[str, Any], method: str, *args) -> dict:
    """Merge subsystem dictionaries, propagating InitExit and merge conflicts."""
    info: dict = {}
    for sub in subsystems.values():
        fn = getattr(sub, method, None)
        try:
            d = fn(*args)
            log("dispatch-merge: %s()=%s", fn, d)
        except InitExit:
            raise
        except Exception:
            log.warn(f"Error: in {sub}.{method}", exc_info=True)
            continue
        if d:
            merge_dicts(info, d)
    return info


def first_truthy(subsystems: Mapping[str, Any], method: str, *args) -> Any:
    """Return the first truthy result; exceptions from subsystem methods propagate."""
    for sub in subsystems.values():
        fn = getattr(sub, method, None)
        if not callable(fn):
            continue
        if result := fn(*args):
            return result
    return None
