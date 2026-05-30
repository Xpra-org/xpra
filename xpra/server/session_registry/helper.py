# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from importlib import import_module

from xpra.util.parsing import parse_simple_dict
from xpra.scripts.config import InitException
from xpra.server.session_registry import SessionRegistry
from xpra.log import Logger

log = Logger("auth")


def parse_session_registry_string(value: str) -> tuple[str, dict]:
    """Parse `NAME` or `NAME(opt=val,...)` or `NAME:opt=val,...`."""
    bracket = value.find("(")
    if bracket > 0 and value.endswith(")"):
        name = value[:bracket]
        options = parse_simple_dict(value[bracket + 1:-1])
    else:
        scpos = value.find(":")
        cpos = value.find(",")
        if cpos < 0 or 0 <= scpos < cpos:
            parts = value.split(":", 1)
        else:
            parts = value.split(",", 1)
        name = parts[0]
        options = parse_simple_dict(parts[1]) if len(parts) > 1 else {}
    if name.endswith("base") or name.endswith("helper"):
        raise ValueError(f"invalid session registry name {name!r}")
    return name, options


def load_session_registry(value: str, cwd: str = "") -> SessionRegistry:
    name, options = parse_session_registry_string(value or "auth")
    options["exec_cwd"] = cwd or os.getcwd()
    modname = name.replace("-", "_")
    try:
        module = import_module("xpra.server.session_registry." + modname)
    except ImportError as e:
        log("cannot load %s session registry", name, exc_info=True)
        raise InitException(f"cannot load session registry {name!r}: {e}") from None
    cls = getattr(module, "Registry", None)
    if cls is None:
        raise InitException(f"session registry module {name!r} has no Registry class")
    try:
        return cls(**options)
    except Exception as e:
        log("cannot instantiate session registry %s", name, exc_info=True)
        raise InitException(f"session registry {name!r} setup error: {e}") from None
