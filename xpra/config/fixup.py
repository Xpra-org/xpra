#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Normalization of parsed options before client or server initialization."""

import os
import warnings
from collections.abc import Sequence
from xpra import config
from xpra.config import InitExit, InitInfo
from xpra.config.types import remove_dupes
from xpra.config.validation import parse_landlock_option
from xpra.exit_codes import ExitCode
from xpra.os_util import WIN32, OSX
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS, str_to_bool
from xpra.util.str_fn import csv
from xpra.util.io import which


def fixup_debug_option(value: str) -> str:
    """ backwards compatible parsing of the debug option, which used to be a boolean """
    if not value:
        return ""
    value = str(value)
    if value.strip().lower() in ("yes", "true", "on", "1"):
        return "all"
    if value.strip().lower() in ("no", "false", "off", "0"):
        return ""
    # if we're here, the value should be a CSV list of categories
    return value


def csvstr(value) -> str:
    if isinstance(value, (list, tuple, set, dict)):
        return ",".join(str(x).strip() for x in value if x)
    if isinstance(value, str):
        return value.strip()
    raise ValueError(f"don't know how to convert {type(value)} to a csv list!")


def csvstrl(value) -> str:
    return csvstr(value).lower()


def nodupes(s) -> list[str]:
    return remove_dupes(x.strip().lower() for x in s.split(","))


def fixup_socketdirs(options) -> None:
    for option_name in ("socket_dirs", "client_socket_dirs"):
        value = getattr(options, option_name)
        if isinstance(value, str):
            value = value.split(os.path.pathsep)
        else:
            assert isinstance(getattr(options, option_name), (list, tuple))
            value = [v for x in value for v in x.split(os.path.pathsep)]
        setattr(options, option_name, value)
    if socket_dir := getattr(options, "socket_dir", ""):
        warnings.warn(
            "the 'socket-dir' option is deprecated, use 'socket-dirs' instead",
            DeprecationWarning,
            stacklevel=3,
        )
        options.socket_dirs = [x for x in options.socket_dirs if x != socket_dir]
        options.socket_dirs.insert(0, socket_dir)


def fixup_pings(options) -> None:
    # pings used to be a boolean, True mapped to "5"
    if isinstance(options.pings, int):
        return
    try:
        pings = str(options.pings).lower()
        if pings in TRUE_OPTIONS:
            options.pings = 5
        elif pings in FALSE_OPTIONS:
            options.pings = 0
        else:
            options.pings = int(options.pings)
    except ValueError:
        options.pings = 5


def fixup_encodings(options) -> None:
    from xpra.codecs.constants import PREFERRED_ENCODING_ORDER
    estr = csvstr(options.encodings)
    RENAME = {
        "jpg"   : "jpeg",
        "png/l" : "png/L",
        "pngl"  : "png/L",
        "png/p" : "png/P",
        "pngp"  : "png/P",
    }
    options.encoding = RENAME.get(options.encoding, options.encoding)
    encodings = [RENAME.get(x, x) for x in nodupes(estr)]
    while True:
        try:
            i = encodings.index("all")
        except ValueError:
            break
        else:
            # replace 'all' with the actual value:
            encodings = encodings[:i]+list(PREFERRED_ENCODING_ORDER)+encodings[i+1:]
    # if the list only has items to exclude (ie: '-scroll,-jpeg')
    # then 'all' is implied:

    def isneg(enc: str) -> bool:
        return enc.startswith("-") or enc.startswith("no-")

    def stripneg(enc) -> str:
        if enc.startswith("-"):
            return enc[1:]
        if enc.startswith("no-"):
            return enc[3:]
        return enc

    if not any(True for e in encodings if not isneg(e)):
        encodings = list(PREFERRED_ENCODING_ORDER)+encodings
    if "rgb" in encodings:
        if "rgb24" not in encodings:
            encodings.append("rgb24")
        if "rgb32" not in encodings:
            encodings.append("rgb32")
    encodings = remove_dupes(encodings)
    if invalid := [stripneg(e) for e in encodings if stripneg(e) not in PREFERRED_ENCODING_ORDER]:
        raise InitExit(ExitCode.UNSUPPORTED, "invalid encodings specified: " + csv(invalid))
    # remove the negated encodings:
    for rm in tuple(stripneg(e) for e in encodings if isneg(e)):
        while True:
            try:
                encodings.remove(rm)
            except ValueError:
                break
    options.encodings = tuple(encodings)
    if not options.video:
        options.csc_modules = ["none"]
        options.video_encoders = ["none"]
        options.video_decoders = ["none"]
    else:
        from xpra.codecs.video import ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS, ALL_VIDEO_DECODER_OPTIONS
        for name, all_list in (
            ("csc-modules", ALL_CSC_MODULE_OPTIONS),
            ("video-encoders", ALL_VIDEO_ENCODER_OPTIONS),
            ("video-decoders", ALL_VIDEO_DECODER_OPTIONS),
        ):
            # ensure value is always a sequence:
            attr_name = name.replace("-", "_")
            value = getattr(options, attr_name)
            if not isinstance(value, Sequence):
                value = [x for x in csvstrl(value).split(",") if x.strip()]
                setattr(options, attr_name, value)
            if "help" in value:
                raise InitInfo(f"the following {name} are defined: {csv(all_list)}")


def fixup_compression(options) -> None:
    from xpra.net import compression
    cstr = csvstrl(options.compressors)
    if cstr == "all":
        compressors = compression.PERFORMANCE_ORDER
    elif cstr == "none":
        compressors = ()
    else:
        compressors = nodupes(cstr)
        if unknown := tuple(x for x in compressors if x and x not in compression.ALL_COMPRESSORS):
            config.warn("Warning: invalid compressor(s) specified: " + csv(unknown))
        # keep only valid ones
        # (ignores `lzo` and `zlib` which have been removed but may still exist in config files)
        compressors = [x for x in compressors if x in compression.VALID_COMPRESSORS]
    options.compressors = list(compressors)


def fixup_packetencoding(options) -> None:
    from xpra.net import packet_encoding
    pestr = csvstrl(options.packet_encoders)
    if pestr == "all":
        packet_encoders = packet_encoding.PERFORMANCE_ORDER
    else:
        packet_encoders = nodupes(pestr)
        if unknown := [x for x in packet_encoders if x and x not in packet_encoding.ALL_ENCODERS]:
            config.warn("Warning: invalid packet encoder(s) specified: " + csv(unknown))
        # keep only valid ones
        # (ignores `rencode`, `bencode` and `yaml` which have been removed but may still exist in config files)
        packet_encoders = [x for x in packet_encoders if x in packet_encoding.VALID_ENCODERS]
    options.packet_encoders = packet_encoders


def fixup_keyboard(options) -> None:
    # variants and layouts can be specified as CSV, convert them to lists:
    def p(v) -> list[str]:
        try:
            if isinstance(v, str):
                # `str` is also a `Sequence`, and iterating one yields characters:
                seq = v.split(",")
            elif isinstance(v, Sequence):
                seq = v
            else:
                seq = str(v).split(",")
            r = remove_dupes(x.strip() for x in seq)
            # remove empty string if that's the only value:
            if r and len(r) == 1 and r[0] == "":
                r = []
            return r
        except Exception:
            return []

    options.keyboard_backend = "" if options.keyboard_backend == "auto" else options.keyboard_backend
    options.keyboard_layouts = p(options.keyboard_layouts)
    options.keyboard_variants = p(options.keyboard_variants)
    options.keyboard_raw = str_to_bool(options.keyboard_raw)


def fixup_backend(options) -> None:
    # 'native' is an alias for the platform specific backend:
    if options.backend.lower() in ("auto", "native") and WIN32:
        options.backend = "win32"


def fixup_clipboard(options) -> None:
    if options.clipboard.lower() == "auto" and (WIN32 or OSX):
        options.clipboard = "all"
    cd = options.clipboard_direction.lower().replace("-", "")
    if cd == "toserver":
        options.clipboard_direction = "to-server"
    elif cd == "toclient":
        options.clipboard_direction = "to-client"
    elif cd == "both":
        options.clipboard_direction = "both"
    elif cd in ("disabled", "none"):
        options.clipboard_direction = "disabled"
    else:
        config.warn(f"Warning: invalid value for clipboard-direction: {options.clipboard_direction!r}")
        config.warn(" specify 'to-server', 'to-client' or 'both'")
        options.clipboard_direction = "disabled"


def abs_paths(options) -> None:
    if ew := options.exec_wrapper:
        import shlex
        ewp = shlex.split(ew)
        if ewp and not os.path.isabs(ewp[0]):
            if abscmd := which(ewp[0]):
                ewp[0] = abscmd
                options.exec_wrapper = shlex.join(ewp)
    # convert to absolute paths before we daemonize
    for k in ("clipboard-filter-file",
              "tcp-encryption-keyfile", "encryption-keyfile",
              "log-dir",
              "download-path", "exec-wrapper",
              "ssl-key", "ssl-cert", "ssl-ca-certs"):
        f = k.replace("-", "_")
        v = getattr(options, f)
        if v and (k != "ssl-ca-certs" or v != "default"):
            if os.path.isabs(v) or v == "auto":
                continue
            if v.startswith("~") or v.startswith("$"):
                continue
            setattr(options, f, os.path.abspath(v))


def fixup_options(options) -> None:
    options.landlock = parse_landlock_option(options.landlock)
    fixup_encodings(options)
    fixup_pings(options)
    fixup_compression(options)
    fixup_packetencoding(options)
    fixup_socketdirs(options)
    fixup_clipboard(options)
    fixup_keyboard(options)
    fixup_backend(options)
    abs_paths(options)
    # remote-xpra is meant to be a list, but the user can specify a string using the command line,
    # in which case we replace all the default values with this single entry:
    if not isinstance(options.remote_xpra, (list, tuple)):
        options.remote_xpra = [options.remote_xpra]
