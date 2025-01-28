# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import re
from enum import Enum
from typing import Iterable
from collections.abc import Callable, Mapping

from xpra.util.env import envbool


def std(v, extras="-+,./: ") -> str:
    def f(c):
        return str.isalnum(c) or c in extras

    return "".join(filter(f, bytestostr(v or "")))


def alnum(v: str | bytes) -> str:
    s = bytestostr(v)
    # noinspection PyTypeChecker
    return "".join(filter(str.isalnum, s))


def nonl(x) -> str:
    if not x:
        return ""
    return str(x).replace("\n", "\\n").replace("\r", "\\r")


def obsc(v) -> str:
    OBSCURE_PASSWORDS = envbool("XPRA_OBSCURE_PASSWORDS", True)
    if OBSCURE_PASSWORDS:
        return "".join("*" for _ in (bytestostr(v) or ""))
    return v


def convert(text: str) -> float | str:
    return float(text) if text.isdigit() else text


def alphanum(key: str) -> list:
    return [convert(c) for c in re.split(r'([-+]?\d+\.?\d*)', key)]


def sort_human(lst: list[str]) -> list:
    lst.sort(key=alphanum)
    return lst


def sorted_nicely(items: Iterable) -> Iterable[str]:
    """ Sort the given iterable in the way that humans expect."""

    def alphanum_key(key) -> list:
        return [convert(c) for c in re.split(r"(\d+)", bytestostr(key))]

    return sorted(items, key=alphanum_key)


def csv(v: Iterable) -> str:
    try:
        return ", ".join(str(x) for x in v)
    except TypeError:
        return str(v)


def is_valid_hostname(hostname: str) -> bool:
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        hostname = hostname[:-1]  # strip exactly one dot from the right, if present
    allowed = re.compile(r"(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))


class Ellipsizer:
    __slots__ = ("obj", "limit")

    def __init__(self, obj, limit=100):
        self.obj = obj
        self.limit = limit

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        if self.obj is None:
            return "None"
        return repr_ellipsized(self.obj, self.limit)


def repr_ellipsized(obj, limit=100) -> str:
    if isinstance(obj, str):
        s = repr(obj)
        if len(s) > limit > 6:
            return s[:limit // 2 - 2] + " .. " + s[2 - limit // 2:]
        return s
    if isinstance(obj, memoryview):
        obj = obj.tobytes()
    if isinstance(obj, bytes):
        try:
            s = repr(obj)
        except TypeError:
            s = binascii.hexlify(obj).decode()
        if len(s) > limit > 6:
            return s[:limit // 2 - 2] + " .. " + s[2 - limit // 2:]
        return s
    return repr_ellipsized(repr(obj), limit)


def print_nested_dict(d: Mapping, prefix: str = "", lchar: str = "*", pad: int = 32,
                      vformat=None, print_fn: Callable | None = None,
                      version_keys=("version", "revision"), hex_keys=("data",)) -> None:
    # "smart" value formatting function:
    def sprint(arg) -> None:
        if print_fn:
            print_fn(arg)
        else:
            print(arg)

    def vf(k, v) -> str:
        if vformat:
            fmt = vformat
            if isinstance(vformat, dict):
                fmt = vformat.get(k)
            if fmt is not None:
                return nonl(fmt(v))
        if isinstance(k, str):
            try:
                if any(k.find(x) >= 0 for x in version_keys):
                    return nonl(pver(v)).lstrip("v")
                if any(k.find(x) >= 0 for x in hex_keys):
                    return binascii.hexlify(v).decode("latin1")
            except TypeError:
                pass
        return nonl(pver(v, ", ", ", "))

    indent = pad - len(prefix) - len(lchar)
    for k in sorted_nicely(d.keys()):
        v = d[k]
        if isinstance(v, dict):
            nokey = v.get("", (v.get(None)))
            if nokey is not None:
                sprint("%s%s %s : %s" % (prefix, lchar, bytestostr(k).ljust(indent), vf(k, nokey)))
                for x in ("", None):
                    v.pop(x, None)
            else:
                sprint("%s%s %s" % (prefix, lchar, bytestostr(k)))
            print_nested_dict(v, prefix + "  ", "-", vformat=vformat, print_fn=print_fn,
                              version_keys=version_keys, hex_keys=hex_keys)
        else:
            sprint("%s%s %s : %s" % (prefix, lchar, bytestostr(k).ljust(indent), vf(k, v)))


def nicestr(obj) -> str:
    """ Python 3.10 and older don't give us a nice string representation for enums """
    if isinstance(obj, Enum):
        return str(obj.value)
    return str(obj)


def strtobytes(x) -> bytes:
    if isinstance(x, bytes):
        return x
    try:
        return str(x).encode("latin1")
    except UnicodeEncodeError:
        return str(x).encode("utf8")


def bytestostr(x) -> str:
    if isinstance(x, (bytes, bytearray)):
        return x.decode("latin1")
    return str(x)


def hexstr(v) -> str:
    return bytestostr(binascii.hexlify(memoryview_to_bytes(v)))


def decode_str(x, try_encoding="utf8") -> str:
    """
    When we want to decode something (usually a byte string) no matter what.
    Try with utf8 first then fallback to just bytestostr().
    """
    try:
        return x.decode(try_encoding)
    except (AttributeError, UnicodeDecodeError):
        return bytestostr(x)


def pver(v, numsep: str = ".", strsep: str = ", ") -> str:
    # print for lists with version numbers, or CSV strings
    if isinstance(v, (list, tuple)):
        types = list(set(type(x) for x in v))
        if len(types) == 1:
            if types[0] is int:
                return numsep.join(str(x) for x in v)
            if types[0] is str:
                return strsep.join(str(x) for x in v)
            if types[0] is bytes:
                def s(x) -> str:
                    try:
                        return x.decode("utf8")
                    except UnicodeDecodeError:
                        return bytestostr(x)

                return strsep.join(s(x) for x in v)
    return bytestostr(v)


def memoryview_to_bytes(v) -> bytes:
    if isinstance(v, bytes):
        return v
    if isinstance(v, memoryview):
        return v.tobytes()
    if isinstance(v, bytearray):
        return bytes(v)
    return strtobytes(v)
