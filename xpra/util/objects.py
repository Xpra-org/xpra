# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.str_fn import strtobytes, bytestostr
from xpra.util.io import get_util_logger


class AtomicInteger:
    __slots__ = ("counter", "lock")

    def __init__(self, integer: int = 0):
        self.counter: int = integer
        from threading import RLock
        self.lock: RLock = RLock()

    def increase(self, inc: int = 1) -> int:
        with self.lock:
            self.counter = self.counter + inc
            return self.counter

    def decrease(self, dec: int = 1) -> int:
        with self.lock:
            self.counter = self.counter - dec
            return self.counter

    def get(self) -> int:
        return self.counter

    def set(self, value: int):
        with self.lock:
            self.counter = value

    def __str__(self) -> str:
        return str(self.counter)

    def __repr__(self) -> str:
        return f"AtomicInteger({self.counter})"

    def __int__(self) -> int:
        return self.counter

    def __eq__(self, other) -> bool:
        try:
            return self.counter == int(other)
        except ValueError:
            return False

    def __cmp__(self, other) -> int:
        try:
            return self.counter - int(other)
        except ValueError:
            return -1


class MutableInteger:
    __slots__ = ("counter",)

    def __init__(self, integer: int = 0):
        self.counter: int = integer

    def increase(self, inc: int = 1) -> int:
        self.counter = self.counter + inc
        return self.counter

    def decrease(self, dec: int = 1) -> int:
        self.counter = self.counter - dec
        return self.counter

    def get(self) -> int:
        return self.counter

    def __str__(self) -> str:
        return str(self.counter)

    def __repr__(self) -> str:
        return f"MutableInteger({self.counter})"

    def __int__(self) -> int:
        return self.counter

    def __eq__(self, other) -> bool:
        return self.counter == int(other)

    def __ne__(self, other) -> bool:
        return self.counter != int(other)

    def __lt__(self, other) -> bool:
        return self.counter < int(other)

    def __le__(self, other) -> bool:
        return self.counter <= int(other)

    def __gt__(self, other) -> bool:
        return self.counter > int(other)

    def __ge__(self, other) -> bool:
        return self.counter >= int(other)

    def __cmp__(self, other) -> int:
        return self.counter - int(other)


# noinspection PyPep8Naming
class typedict(dict):
    __slots__ = ("warn",)  # no __dict__ - that would be redundant

    def __init__(self, mapping=(), **kwargs):
        super().__init__(mapping, **kwargs)
        self.warn = self._warn

    def get(self, k: str, default=None):
        if k in self:
            return super().get(k, default)
        # try to locate this value in a nested dictionary:
        if k.find(".") > 0:
            prefix, k = k.split(".", 1)
            if prefix in self:
                v = super().get(prefix)
                if isinstance(v, dict):
                    return typedict(v).get(k, default)
        return default

    def setdefault(self, k: str, default=None):
        return super().setdefault(k, default)

    def __repr__(self):
        return f'{type(self).__name__}({super().__repr__()})'

    def _warn(self, msg: str, *args):
        from xpra.log import Logger
        Logger("util").warn(msg, *args)

    def conv_get(self, key: str | int, default=None, conv=None):
        if key in self or not isinstance(key, str):
            v = super().get(key)
        else:
            # try harder by recursing:
            d = self
            while key.find(".") > 0:
                prefix, k = key.split(".", 1)
                if prefix not in d:
                    return default
                v = d[prefix]
                if not isinstance(v, dict):
                    return default
                d = v
                key = k
            if key not in d:
                return default
            v = dict.get(d, key)
        if isinstance(v, dict) and conv and conv in (bytestostr, strtobytes, int, bool):
            d = typedict(v)
            if "" in d:
                v = d[""]
        try:
            return conv(v)
        except (TypeError, ValueError, AssertionError) as e:
            self._warn(f"Warning: failed to convert {key!r}")
            self._warn(f" from {type(v)} using {conv}: {e}")
            return default

    def strget(self, k: str, default: str = "") -> str:
        return self.conv_get(k, default, bytestostr)

    def bytesget(self, k: str, default: bytes = b"") -> bytes:
        return self.conv_get(k, default, strtobytes)

    def intget(self, k: str, default: int = 0) -> int:
        return self.conv_get(k, default, int)

    def floatget(self, k: str, default: float = 0.0) -> float:
        return self.conv_get(k, default, float)

    def boolget(self, k: str, default: bool = False) -> bool:
        return self.conv_get(k, default, bool)

    def dictget(self, k: str | int, default: dict | None = None) -> dict:
        return self.conv_get(k, default, checkdict)

    def intpair(self, k: str, default_value: tuple[int, int] | None = None) -> tuple[int, int] | None:
        v = self.inttupleget(k, default_value)
        if v is None:
            return default_value
        if len(v) != 2:
            # "%s is not a pair of numbers: %s" % (k, len(v))
            return default_value
        try:
            return int(v[0]), int(v[1])
        except ValueError:
            return default_value

    def strtupleget(self, k: str, default_value=(),
                    min_items: int | None = None, max_items: int | None = None) -> tuple[str, ...]:
        return self.tupleget(k, default_value, str, min_items, max_items)

    def inttupleget(self, k: str, default_value=(),
                    min_items: int | None = None, max_items: int | None = None) -> tuple[int, ...]:
        return self.tupleget(k, default_value, int, min_items, max_items)

    def tupleget(self, k: str, default_value=(), item_type=None,
                 min_items: int | None = None, max_items: int | None = None) -> tuple[Any, ...]:
        v = self._listget(k, default_value, item_type, min_items, max_items)
        return tuple(v or ())

    def _listget(self, k: str, default_value, item_type=None,
                 min_items: int | None = None, max_items: int | None = None) -> list[Any] | tuple[Any, ...]:
        v = self.get(k)
        if v is None:
            return default_value
        if isinstance(v, dict) and "" in v:
            v = v.get("")
        if not isinstance(v, (list, tuple)):
            self._warn("listget%s", (k, default_value, item_type, max_items))
            self._warn("expected a list or tuple value for %s but got %s: %s", k, type(v), v)
            return default_value
        if min_items is not None and len(v) < min_items:
            self._warn("too few items in %s %s: minimum %s allowed, but got %s", type(v), k, max_items, len(v))
            return default_value
        if max_items is not None and len(v) > max_items:
            self._warn("too many items in %s %s: maximum %s allowed, but got %s", type(v), k, max_items, len(v))
            return default_value
        aslist = list(v)
        if item_type:
            for i, x in enumerate(aslist):
                if isinstance(x, bytes) and item_type is str:
                    x = bytestostr(x)
                    aslist[i] = x
                elif isinstance(x, str) and item_type is str:
                    x = str(x)
                    aslist[i] = x
                if not isinstance(x, item_type):
                    if callable(item_type):
                        try:
                            return item_type(x)
                        except Exception:
                            self._warn("invalid item type for %s %s: %s cannot be used with %s",
                                       type(v), k, item_type, type(x))
                            return default_value
                    self._warn("invalid item type for %s %s: expected %s but got %s",
                               type(v), k, item_type, type(x))
                    return default_value
        return aslist


# A simple little class whose instances we can stick random bags of attributes on.
class AdHocStruct:
    def __repr__(self):
        return ("<%s object, contents: %r>"
                % (type(self).__name__, self.__dict__))


def checkdict(v) -> dict:
    if isinstance(v, typedict):
        return dict(v)
    if not isinstance(v, dict):
        raise ValueError(f"expected a dict but got a {type(v)}")
    return v


def notypedict(d: dict, path="") -> dict:
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, typedict):
            log = get_util_logger()
            log.warn(f"Warning: found `typedict` at {path}.{k}")
            d[k] = notypedict(dict(v), f"{path}.{k}".strip("."))
        elif isinstance(v, dict):
            d[k] = notypedict(v, f"{path}.{k}".strip("."))
    return d


def make_instance(class_options, *args):
    log = get_util_logger()
    log("make_instance%s", tuple([class_options] + list(args)))
    for c in class_options:
        if c is None:
            continue
        try:
            v = c(*args)
            log(f"make_instance(..) {c}()={v}")
            if v:
                return v
        except Exception as e:
            log("make_instance(%s, %s)", class_options, args, exc_info=True)
            log.error("Error: cannot instantiate %s:", c)
            log.estr(e)
    return None


def reverse_dict(d: dict) -> dict:
    reversed_d = {}
    for k, v in d.items():
        reversed_d[v] = k
    return reversed_d


def merge_dicts(a: dict[str, Any], b: dict[str, Any], path: list[str] | None = None) -> dict[str, Any]:
    """ merges b into a """
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dicts(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass  # same leaf value
            else:
                pathstr = ".".join(repr(v) for v in (path + [key]))
                # print(f"merged_dicts({a!r}, {b!r}, {path!r}) {key=!r}")
                raise ValueError(f"Conflict at {pathstr}: existing value is {a[key]}, new value is {b[key]}")
        else:
            a[key] = b[key]
    return a
