# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.log import Logger

log = Logger("ibus")


def noemptyvalues(d: dict) -> dict:
    return dict((k, v) for k, v in d.items() if v)


def query_engine(e) -> dict[str, Any]:
    return noemptyvalues({
        "description": e.get_description(),
        "language": e.get_language(),
        "layout": e.get_layout(),
        "option": e.get_layout_option(),
        "variant": e.get_layout_variant(),
        "long-name": e.get_longname(),
        "name": e.get_name(),
        "symbol": e.get_symbol(),
        "version": e.get_version(),
        "rank": e.get_rank(),
    })


def query_ibus() -> dict[str, Any]:
    try:
        from xpra.os_util import gi_import
        IBus = gi_import("IBus")
    except ImportError:
        return {}
    bus = IBus.Bus()
    info = {
        "address": IBus.get_address(),
        "machine-id": IBus.get_local_machine_id(),
        "socket": IBus.get_socket_path(),
        "connected": bus.is_connected(),
    }
    if bus.is_connected():
        ge = bus.get_global_engine()
        if ge:
            info["engine"] = query_engine(ge)
        engines = bus.list_engines()
        if engines:
            info["engines"] = tuple(query_engine(engine) for engine in engines)
    log(f"query_ibus()={info}")
    return info


def set_engine(name: str) -> bool:
    log(f"ibus.set_engine({name!r})")
    try:
        from xpra.os_util import gi_import
        IBus = gi_import("IBus")
    except ImportError as e:
        log(f"failed to import ibus: {e}")
        return False
    bus = IBus.Bus()
    if not bus.is_connected():
        log(f"bus {bus} is not connected")
        return False
    return bus.set_global_engine(name)


def main(_argv) -> int:  # pragma: no cover
    from xpra.util.str_fn import print_nested_dict
    info = query_ibus()
    engines = info.pop("engines", ())
    print_nested_dict(info)
    print_nested_dict({"engines": dict(enumerate(engines))})


if __name__ == "__main__":
    import sys
    main(sys.argv)
