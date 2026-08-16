# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
from xpra.util.str_fn import csv

log = Logger("auth")

# This private option is added by the authentication manager and contains only
# the names of options explicitly scoped to an authentication module.
AUTH_OPTION_KEYS = "_auth_option_keys"


def warn_unused_auth_options(authenticator, kwargs: dict) -> None:
    option_keys = kwargs.pop(AUTH_OPTION_KEYS, ())
    unused = sorted(set(option_keys).intersection(kwargs))
    if unused:
        suffix = "s" if len(unused) != 1 else ""
        log.warn(f"Warning: unused {authenticator!r} authentication option{suffix}:")
        log.warn(" %s", csv(repr(x) for x in unused))
