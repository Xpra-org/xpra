#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


"""Validation of supplied configuration values, without default discovery."""

from typing import Any
from xpra import config
from xpra.config import InitException
from xpra.util.str_fn import csv
from xpra.config.types import OPTION_TYPES, OPTIONS_VALIDATION, DISCARD_OPTIONS, LEGACY_OPTIONS
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS, parse_bool_or, parse_bool_or_number, parse_number


def validate_config(d=None, discard=DISCARD_OPTIONS, extras_types=None, extras_validation=None) -> dict[str,Any]:
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
            if k not in LEGACY_OPTIONS:
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


SECCOMP_THREADS: tuple[str, ...] = ("decode", "parse", "rfb", "menu")
SECCOMP_ACTIONS: tuple[str, ...] = (
    "kill", "kill_thread", "kill-thread", "kill_process", "kill-process", "errno", "log", "allow",
)


def parse_seccomp_option(value: str) -> dict[str, str]:
    """
    Convert a `--seccomp=...` option value into the environment variables
    that gate the per-thread seccomp filters (decode / parse / rfb / menu).
    Returns an empty dict for an empty / "auto" value (leave the environment untouched).
    Raises `ValueError` for invalid values.
    """
    value = (value or "").strip().lower()
    if value in ("", "auto"):
        return {}
    env: dict[str, str] = {}
    if value in FALSE_OPTIONS:
        # force everything off (including the global fallback flag):
        env["XPRA_SECCOMP"] = "0"
        for thread in SECCOMP_THREADS:
            env[f"XPRA_SECCOMP_{thread.upper()}"] = "0"
        return env
    if value in ("default", "strict"):
        # enable all the filters, `default` is non-fatal (errno), `strict` kills the process:
        action = "errno" if value == "default" else "kill_process"
        for thread in SECCOMP_THREADS:
            env[f"XPRA_SECCOMP_{thread.upper()}"] = "1"
            env[f"XPRA_SECCOMP_{thread.upper()}_ACTION"] = action
        return env
    # explicit list of threads, ie: "decode,parse" or "decode:errno,parse:kill":
    actions: dict[str, str] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        thread, _, action = part.partition(":")
        thread = thread.strip()
        action = action.strip()
        if thread not in SECCOMP_THREADS:
            raise ValueError(f"invalid seccomp thread {thread!r}, must be one of: {csv(SECCOMP_THREADS)} or 'default', 'strict'")
        if action and action not in SECCOMP_ACTIONS:
            raise ValueError(f"invalid seccomp action {action!r}, must be one of: {csv(SECCOMP_ACTIONS)}")
        actions[thread] = action
    if not actions:
        raise ValueError(f"no valid seccomp threads found in {value!r}")
    # deliberately do not set the global `XPRA_SECCOMP` flag here:
    # the decode filter reads it as its primary gate, so setting it would override
    # the per-thread flags below. Enable / disable each thread explicitly instead:
    for thread in SECCOMP_THREADS:
        var = f"XPRA_SECCOMP_{thread.upper()}"
        if thread in actions:
            env[var] = "1"
            if actions[thread]:
                env[f"{var}_ACTION"] = actions[thread]
        else:
            env[var] = "0"
    return env
