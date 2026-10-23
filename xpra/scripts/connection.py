# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Connection address grammar, independent of transport discovery and configuration files."""

import os.path
import uuid
from collections.abc import Callable, Sequence
from typing import Any
from urllib import parse

from xpra.config import InitException
from xpra.config.types import OPTION_TYPES, URL_SAFE_OPTIONS
from xpra.config.validation import validate_config
from xpra.net.constants import IP_SOCKTYPES, SOCKET_TYPES, URL_MODES
from xpra.util.io import warn


def parse_URL(url: str, attach_urls="yes", *, warn: Callable = warn) -> tuple[str, dict]:
    if attach_urls not in ("yes", "no", "strict"):
        raise InitException(f"invalid value for `attach-urls`: {attach_urls!r} (must be `yes`, `no` or `strict`)")
    if attach_urls == "no":
        raise InitException(f"URLs are not allowed: {url!r} (see the `attach-urls` option)")
    from urllib.parse import urlparse, parse_qs
    up = urlparse(url)
    address = str(up.netloc)
    qpos = url.find("?")
    options = {}
    if qpos > 0:
        params_str = url[qpos + 1:]
        params = parse_qs(params_str, keep_blank_values=True)
        f_params: dict[str, Any] = {}
        for k, v in params.items():
            # URLs are untrusted: only allow a safe subset of options,
            # never commands, environment, file paths, auth or encryption settings:
            # with `attach-urls=strict`, no options at all are allowed,
            # only the address part of the URL is used:
            if attach_urls == "strict" or k not in URL_SAFE_OPTIONS:
                warn(f"Warning: option {k!r} is not allowed in URLs and will be ignored")
                continue
            t = OPTION_TYPES.get(k)
            if t is not None and t not in (list, tuple):
                f_params[k] = v[0]
            else:
                f_params[k] = v
        options = validate_config(f_params)
    scheme = up.scheme
    if scheme.startswith("xpra+"):
        scheme = scheme.removeprefix("xpra+")
    if scheme in IP_SOCKTYPES:
        address = f"{scheme}://{address}"
    if up.path:
        address += "/"+up.path
    return address, options


def _sep_pos(display_name) -> int:
    # split the display name on ":" or "/"
    scpos = display_name.find(":")
    slpos = display_name.find("/")
    if scpos < 0:
        return slpos
    if slpos < 0:
        return scpos
    return min(scpos, slpos)


def normalize_display_name(display_name: str, *, posix: bool, windows: bool, osx: bool, pipe_prefix: str = "") -> str:
    if not display_name:
        raise ValueError("no display name specified")
    if display_name.startswith("@"):
        return display_name
    if posix and display_name.startswith("/"):
        return "socket://" + display_name
    # URL mode aliases (ie: "xpra+tcp://host:port")
    for alias, prefix in URL_MODES.items():
        falias = f"{alias}:"
        parts = display_name.split(falias, 1)
        if len(parts) == 2:
            display_name = prefix + ":" + parts[1]
            break
    if display_name.startswith("socket://"):
        # if the URL uses the form:
        # "socket://username:password/somepath/dfsdff/fd/fd")
        # instead of:
        # "socket://username:password@/somepath/dfsdff/fd/fd")
        # then the username and password aren't parsed properly!
        pass

    # workaround missing [] around IPv6 addresses:
    try:
        netloc = parse.urlparse(display_name).netloc
        if netloc.find("@") > 0:
            netloc = netloc.split("@", 1)[1]
        if not netloc.startswith("[") and not netloc.endswith("]"):
            pos = display_name.find(netloc)
            parts = netloc.split(":")
            if pos > 0 and len(parts) > 2:
                newnetloc = "[" + (":".join(parts[:-1])) + "]:" + parts[-1]
                display_name = display_name[:pos] + newnetloc + display_name[pos + len(netloc):]
    except (ValueError, AttributeError, TypeError):
        pass
    # workaround for vsock 'VMADDR_PORT_ANY':
    # "any" or "auto" is not a valid port number
    if posix and not osx and display_name.startswith("vsock://") and len(display_name) > len("vsock://"):
        # hackish pre-parsing:
        # extract location: "vsock://10:any/foo?arg=20" -> "10:any"
        parts = display_name.removeprefix("vsock://").split("/", 1)
        netloc = parts[0]
        extra = parts[1] if len(parts) > 1 else ""
        for s in ("any", "auto"):
            if netloc.lower().endswith(s):
                # use "0" for auto
                # ie: "vsock://10:0/foo?arg=20"
                return "vsock://" + netloc[:-len(s)] + "0/" + extra
        return display_name
    # maybe this is just the display number without the ":" prefix?
    # (the "." allows for a screen number: "10.0")
    # only do this if the whole string is numeric, so that a session name
    # which happens to start with a digit can still be looked up by name
    if display_name and display_name.replace(".", "").isnumeric() and posix:
        return ":" + display_name
    if windows and display_name[0].isalpha() and display_name.find(":") < 0:
        return f"named-pipe://{pipe_prefix}{display_name}"
    return display_name


def parse_connection_url(display_name: str) -> parse.ParseResult:
    """Parse Xpra schemes consistently even before urllib's scheme registration."""
    parsed = parse.urlparse(display_name)
    if parsed.scheme in SOCKET_TYPES and parsed.scheme not in parse.uses_params:
        # urllib only separates path parameters for schemes in uses_params.
        path = parsed.path
        start = path.rfind("/") + 1
        pos = path.find(";", start)
        if pos >= 0:
            parsed = parsed._replace(path=path[:pos], params=path[pos + 1:])
    return parsed


def get_host_port(parsed: parse.ParseResult, default_port: int) -> dict[str, Any]:
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or default_port
    fields = {"host": host, "local": is_local(host)}
    if port:
        fields["port"] = port
    return fields


def add_query(desc: dict[str, Any], parsed: parse.ParseResult, query: str, *, strict: bool, warn: Callable) -> None:
    for key, values in parse.parse_qs(query).items():
        if key in desc:
            warn(f"ignoring {key} override from query string")
            continue
        if strict and key not in URL_SAFE_OPTIONS:
            warn(f"Warning: option {key!r} is not allowed in connection strings and will be ignored")
            continue
        desc[key] = values[0] if len(values) == 1 else values
    if parsed.params:
        desc["params"] = parsed.params
    if parsed.fragment:
        desc["fragment"] = parsed.fragment


def add_path(desc: dict[str, Any], path: str, process_query: Callable[[str], None]) -> None:
    if path:
        path = path.lstrip("/")
        if path.find(",") > 0:
            path, extra = path.split(",", 1)
            process_query(extra)
        elif path.find("=") > 0:
            process_query(path)
            return
        # Split the option separators before decoding a session name's %2C / %3D.
        desc["display"] = parse.unquote(path)


def get_local_display_attributes(display_name: str, parsed: parse.ParseResult, socket_dirs: Sequence[str]) -> dict[str, Any]:
    fields = {"type": "socket", "local": True}
    if display_name.startswith("@"):
        fields["display"] = parsed.path[1:]
        fields["socket_path"] = parsed.path
    else:
        fields["display"] = parsed.path.lstrip(":")
        if socket_dirs:
            fields["socket_dirs"] = socket_dirs
    return fields


def get_socket_path_attributes(parsed: parse.ParseResult, socket_dirs: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "socket", "local": True, "socket_dir": os.path.basename(parsed.path),
        "socket_dirs": socket_dirs, "socket_path": parsed.path,
    }


def get_named_pipe_attributes(parsed: parse.ParseResult, pipe_prefix: str, pipe_root: str) -> dict[str, Any]:
    raw_path = parsed.path or ""
    combined = parsed.netloc + raw_path

    def with_prefix(name: str) -> str:
        return name if name.startswith(pipe_prefix) else f"{pipe_prefix}{name}"

    # An explicit host uses SMB / IPC$, including localhost addresses.
    if "\\pipe\\" in combined.lower() or combined.startswith("\\"):
        unc = combined.lstrip("\\")
        named_pipe = pipe_root + unc
        host = unc.split("\\", 1)[0] if unc else "."
        local = host in ("", ".")
    elif parsed.netloc and raw_path.strip("/"):
        host = parsed.netloc
        pipe_name = with_prefix(raw_path.strip("/"))
        local = host in ("", ".")
        named_pipe = pipe_name if local else f"{pipe_root}{host}\\pipe\\{pipe_name}"
    else:
        host = ""
        local = True
        named_pipe = with_prefix(parsed.netloc)
    fields = {"local": local, "display": "DISPLAY", "named-pipe": named_pipe}
    if host and not local:
        fields["host"] = host
    return fields


def get_ssh_display_args(desc: dict[str, Any], protocol: str) -> list[str]:
    display = desc.get("display", "")
    args = desc.setdefault("display_as_args", [display] if display else [])
    if protocol == "vnc+ssh" and display:
        vnc_uri = "vnc://localhost"
        try:
            vnc_port = 5900 + int(display)
            desc["remote_port"] = vnc_port
            vnc_uri += f":{vnc_port}/"
        except ValueError:
            vnc_uri += "/"
        args.append(vnc_uri)
    return args


def parse_uuid(name: str, value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as e:
        raise ValueError(f"{name} {value!r} is not a valid uuid: {e}") from None


def parse_hyperv_serviceid(serviceid: str | int) -> str:
    # we support plain port numbers,
    # as used with linux servers vsock style interfaces
    # or uuid strings for hyper-v native addresses
    if isinstance(serviceid, int) or len(serviceid) < 6:
        # ie: "20000"
        try:
            port = int(serviceid)
        except ValueError:
            raise ValueError(f"short serviceid {serviceid!r} is not numeric") from None
        if port < 0 or port > 65535:
            raise ValueError(f"short serviceid {port} is out of range")
        # assume that this is a Linux vsock port:
        return f"{port:08x}-facb-11e6-bd58-64006a7986d3"
    return parse_uuid("serviceid", serviceid)


def is_local(host: str) -> bool:
    return host.lower() in ("localhost", "127.0.0.1", "::1")
