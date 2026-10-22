#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


"""Validation of supplied configuration values, without default discovery."""

from typing import Any
from xpra import config
from xpra.config import InitException
from xpra.config.types import OPTION_TYPES, OPTIONS_VALIDATION, NO_FILE_OPTIONS
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS, parse_bool_or, parse_bool_or_number, parse_number


def validate_config(d=None, discard=NO_FILE_OPTIONS, extras_types=None, extras_validation=None) -> dict[str,Any]:
    return do_validate_config(d or {}, discard, extras_types or {}, extras_validation or {})


def do_validate_config(d:dict, discard, extras_types:dict, extras_validation:dict) -> dict[str, Any]:
    """
        Validates all the options given in a dict with fields as keys and
        strings or arrays of strings as values.
        Each option is strongly typed and invalid value are discarded.
        We get the required datatype from OPTION_TYPES
    """
    validations = OPTIONS_VALIDATION.copy()
    validations.update(extras_validation)
    option_types = OPTION_TYPES.copy()
    option_types.update(extras_types)
    nd: dict[str, Any] = {}
    for k, v in d.items():
        if k in discard:
            config.warn(f"Warning: option {k!r} is not allowed in configuration files")
            continue
        vt = option_types.get(k)
        if vt is None:
            config.warn(f"Warning: invalid option: {k!r}")
            continue
        if vt is str:
            if not isinstance(v, str):
                config.warn(f"invalid value for {k!r}: {type(v)} (string required)")
                continue
        elif vt is int:
            v = parse_bool_or_number(int, k, v)
        elif vt is float:
            v = parse_number(float, k, v)
        elif vt is bool:
            v = parse_bool_or(k, v)
            if v is None:
                continue
        elif vt is list:
            if isinstance(v, str):
                # could just be that we specified it only once..
                v = [v]
            elif isinstance(v, list) or v is None:
                # ok so far..
                pass
            else:
                config.warn(f"Warning: invalid value for {k!r}: {type(v)} (a string or list of strings is required)")
                continue
        else:
            config.warn(f"Error: unknown option type for {k!r}: {vt}")
        validation = validations.get(k)
        if validation and v is not None:
            if msg := validation(v):
                config.warn(f"Warning: invalid value for {k!r}: {v}, {msg}")
                continue
        nd[k] = v
    return nd


def split_landlock_option(value: str | bool) -> tuple[str, bool]:
    """
        Parses a landlock option value, ie: "strict+gpu",
        and returns the mode and whether the GPU devices are accessible.
    """
    mode, plus, flag = str(value or "no").strip().lower().partition("+")
    mode = mode.strip()
    if mode in FALSE_OPTIONS:
        mode = "no"
    elif mode in TRUE_OPTIONS:
        mode = "default"
    if mode not in ("no", "default", "strict"):
        raise InitException(f"invalid landlock option {value!r}, must be 'no', 'default' or 'strict'")
    gpu = False
    if plus:
        if flag.strip() != "gpu" or mode == "no":
            raise InitException(f"invalid landlock option {value!r}, only 'default+gpu' and 'strict+gpu' are supported")
        gpu = True
    return mode, gpu


def parse_landlock_option(value: str | bool) -> str:
    mode, gpu = split_landlock_option(value)
    return f"{mode}+gpu" if gpu else mode
