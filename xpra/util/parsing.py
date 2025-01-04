# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
import binascii
import os

from xpra.util.env import envfloat
from xpra.scripts.config import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.log import Logger

MIN_SCALING = envfloat("XPRA_MIN_SCALING", 0.1)
MAX_SCALING = envfloat("XPRA_MAX_SCALING", 8)
SCALING_OPTIONS = [float(x) for x in
                   os.environ.get("XPRA_TRAY_SCALING_OPTIONS",
                                  "0.25,0.5,0.666,1,1.25,1.5,2.0,3.0,4.0,5.0").split(",")
                   if MAX_SCALING >= float(x) >= MIN_SCALING]
SCALING_EMBARGO_TIME = int(os.environ.get("XPRA_SCALING_EMBARGO_TIME", "1000")) / 1000


def r4cmp(v, rounding=1000.0):  # ignore small differences in floats for scale values
    return round(v * rounding)


def fequ(v1, v2) -> bool:
    return r4cmp(v1) == r4cmp(v2)


def scaleup_value(scaling) -> tuple[float, ...]:
    return tuple(v for v in SCALING_OPTIONS if r4cmp(v, 10) > r4cmp(scaling, 10))


def scaledown_value(scaling) -> tuple[float, ...]:
    return tuple(v for v in SCALING_OPTIONS if r4cmp(v, 10) < r4cmp(scaling, 10))


def parse_scaling(desktop_scaling: str, root_w: int, root_h: int,
                  min_scaling=MIN_SCALING, max_scaling=MAX_SCALING) -> tuple[float, float]:
    log = Logger("util", "scaling")
    log("parse_scaling(%s)", (desktop_scaling, root_w, root_h, min_scaling, max_scaling))
    if desktop_scaling in TRUE_OPTIONS or desktop_scaling in FALSE_OPTIONS:
        return 1, 1
    if desktop_scaling.startswith("auto"):
        # figure out if the command line includes settings to use for auto mode:
        # here are our defaults:
        limits: list[tuple[int, int, float, float]] = [
            (3960, 2160, 1.0, 1.0),  # 100% no auto scaling up to 4k
            (7680, 4320, 1.25, 1.25),  # 125%
            (8192, 8192, 1.5, 1.5),  # 150%
            (16384, 16384, 5.0 / 3, 5.0 / 3),  # 166%
            (32768, 32768, 2, 2),
            (65536, 65536, 4, 4),
        ]  # 200% if higher (who has this anyway?)
        if desktop_scaling.startswith("auto:"):
            limstr = desktop_scaling[5:]  # ie: '1920x1080:1,2560x1600:1.5,...
            limp = limstr.split(",")
            limits = []
            for l in limp:
                try:
                    ldef = l.split(":")
                    assert len(ldef) == 2, "could not find 2 parts separated by ':' in '%s'" % ldef
                    dims = ldef[0].split("x")
                    assert len(dims) == 2, "could not find 2 dimensions separated by 'x' in '%s'" % ldef[0]
                    x, y = int(dims[0]), int(dims[1])
                    scaleparts = ldef[1].replace("*", "x").replace("/", "x").split("x")
                    assert len(scaleparts) <= 2, "found more than 2 scaling dimensions!"
                    if len(scaleparts) == 1:
                        sx = sy = float(scaleparts[0])
                    else:
                        sx = float(scaleparts[0])
                        sy = float(scaleparts[1])
                    limits.append((x, y, sx, sy))
                    log("parsed desktop-scaling auto limits: %s", limits)
                except Exception as e:
                    log.warn("Warning: failed to parse limit string '%s':", l)
                    log.warn(" %s", e)
                    log.warn(" should use the format WIDTHxHEIGTH:SCALINGVALUE")
        elif desktop_scaling != "auto":
            log.warn(f"Warning: invalid 'auto' scaling value {desktop_scaling}")
        sx, sy = 1.0, 1.0
        matched = False
        for mx, my, tsx, tsy in limits:
            if root_w * root_h <= mx * my:
                sx, sy = tsx, tsy
                matched = True
                break
        log("matched=%s : %sx%s with limits %s: %sx%s", matched, root_w, root_h, limits, sx, sy)
        return sx, sy

    def parse_item(v) -> float:
        div = 1
        try:
            if v.endswith("%"):
                div = 100
                v = v[:-1]
        except ValueError:
            pass
        if div == 1:
            try:
                return int(v)  # ie: desktop-scaling=2
            except ValueError:
                pass
        try:
            return float(v) / div  # ie: desktop-scaling=1.5
        except (ValueError, ZeroDivisionError):
            pass
        # ie: desktop-scaling=3/2, or desktop-scaling=3:2
        pair = v.replace(":", "/").split("/", 1)
        try:
            return float(pair[0]) / float(pair[1])
        except (ValueError, ZeroDivisionError):
            pass
        log.warn("Warning: failed to parse scaling value '%s'", v)
        return 0

    if desktop_scaling.find("x") > 0 and desktop_scaling.find(":") > 0:
        log.warn("Warning: found both 'x' and ':' in desktop-scaling fixed value")
        log.warn(" maybe the 'auto:' prefix is missing?")
        return 1, 1
    # split if we have two dimensions: "1600x1200" -> ["1600", "1200"], if not: "2" -> ["2"]
    values = desktop_scaling.replace(",", "x").split("x", 1)
    sx = parse_item(values[0])
    if not sx:
        return 1, 1
    if len(values) == 1:
        # just one value: use the same for X and Y
        sy = sx
    else:
        sy = parse_item(values[1])
        if sy is None:
            return 1, 1
    log("parse_scaling(%s) parsed items=%s", desktop_scaling, (sx, sy))
    # normalize absolute values into floats:
    if sx > max_scaling or sy > max_scaling:
        log(" normalizing dimensions to a ratio of %ix%i", root_w, root_h)
        sx /= root_w
        sy /= root_h
    if sx < min_scaling or sy < min_scaling or sx > max_scaling or sy > max_scaling:
        log.warn("Warning: scaling values %sx%s are out of range", sx, sy)
        return 1, 1
    log("parse_scaling(%s)=%s", desktop_scaling, (sx, sy))
    return sx, sy


def parse_simple_dict(s: str, sep: str = ",") -> dict[str, str | list[str] | dict[str, str]]:
    # parse the options string and add the pairs:
    d: dict[str, str | list[str] | dict[str, str]] = {}
    for el in s.split(sep):
        if not el:
            continue
        if el.startswith("#") or el.find("=") < 0:
            continue
        try:
            k, v = el.split("=", 1)
            k = k.strip()
            v = v.strip()

            def may_add() -> str | list[str] | dict[str, str]:
                cur = d.get(k)
                vparts = v.split("=", 1)
                if cur is None:
                    # first time we see this key 'k'
                    if len(vparts) == 2:
                        # looks like a nested dictionary
                        return {vparts[0]: vparts[1]}
                    # first value found for this key,
                    # keep it as a string - for now
                    return v
                if isinstance(cur, dict):
                    if len(vparts) != 2:
                        raise ValueError(f"cannot add {v} to dictionary {k}")
                    cur[vparts[0]] = vparts[1]
                    return cur
                if not isinstance(cur, list):
                    cur = [cur]
                cur.append(v)
                return cur

            d[k] = may_add()
        except Exception as e:
            log = Logger("util")
            log.warn("Warning: failed to parse dictionary option '%s':", s)
            log.warn(" %s", e)
    return d


def parse_str_dict(s: str, sep: str = ",") -> dict[str, str]:
    # parse the options string and add the pairs:
    d: dict[str, str] = {}
    for el in s.split(sep):
        if not el or el.find("=") < 0:
            continue
        k, v = el.split("=", 1)
        d[k.strip()] = v.strip()
    return d


def parse_scaling_value(v) -> tuple[int, int] | None:
    if not v:
        return None
    if v.endswith("%"):
        num = int(v[:-1])
        denom = 100
        for div in (2, 5):
            while (num % div) == 0 and (denom % div) == 0:
                num = num // div
                denom = denom // div
        return num, denom
    values = v.replace("/", ":").replace(",", ":").split(":", 1)
    values = [int(x) for x in values]
    for x in values:
        assert x > 0, f"invalid scaling value {x}"
    if len(values) == 1:
        ret = 1, values[0]
    else:
        assert values[0] <= values[1], "cannot upscale"
        ret = values[0], values[1]
    return ret


def from0to100(v):
    return intrangevalidator(v, 0, 100)


def intrangevalidator(v, min_value=None, max_value=None):
    v = int(v)
    if min_value is not None and v < min_value:
        raise ValueError(f"value must be greater than {min_value}")
    if max_value is not None and v > max_value:
        raise ValueError(f"value must be lower than {max_value}")
    return v


def parse_encoded_bin_data(data: str) -> bytes:
    if not data:
        return b""
    header = data.lower()[:10]
    if header.startswith("0x"):
        return binascii.unhexlify(data[2:])
    import base64
    if header.startswith("b64:"):
        return base64.b64decode(data[4:])
    if header.startswith("base64:"):
        return base64.b64decode(data[7:])
    try:
        return binascii.unhexlify(data)
    except (TypeError, binascii.Error):
        try:
            return base64.b64decode(data)
        except Exception:
            pass
    return b""
