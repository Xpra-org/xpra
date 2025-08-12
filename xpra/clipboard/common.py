# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import struct
from typing import TypeAlias, Callable, Any, Final, Iterable

from xpra.util.env import envint

sizeof_long: Final[int] = struct.calcsize(b'@L')
sizeof_short: Final[int] = struct.calcsize(b'=H')
assert sizeof_long in (4, 8), "struct.calcsize('@L')=%s" % sizeof_long
assert sizeof_short == 2, "struct.calcsize('=H')=%s" % sizeof_short

# CARD32 can actually be 64-bits...
CARD32_SIZE: Final[int] = sizeof_long * 8


def get_format_size(dformat: int) -> int:
    return max(8, {32: CARD32_SIZE}.get(dformat, dformat))


ClipboardCallback: TypeAlias = Callable[[str, int, Any], None]


def env_timeout(name, default: int, min_time=0, max_time=5000) -> int:
    env_name = f"XPRA_CLIPBOARD_{name}_TIMEOUT"
    value = envint(env_name, default)
    if not min_time < value <= max_time:
        from xpra.log import Logger
        log = Logger("clipboard")
        log.warn(f"Warning: invalid value for {env_name!r}")
        log.warn(f" valid range is from {min_time} to {max_time}")
        value = max(min_time, min(max_time, value))
    return value


def compile_filters(filter_res: Iterable[str]) -> list[re.Pattern]:
    filters = []
    for x in filter_res:
        if not x:
            continue
        try:
            filters.append(re.compile(x))
        except Exception as e:
            from xpra.log import Logger
            log = Logger("clipboard")
            log.error("Error: invalid clipboard filter regular expression")
            log.error(f" {x}: {e}")
    return filters
