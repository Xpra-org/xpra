# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from typing import Iterable, Sequence

from xpra.util.str_fn import bytestostr, csv
from xpra.log import Logger

log = Logger("clipboard")


def _filter_targets(targets: Iterable[str]) -> Sequence[str]:
    targets_strs = tuple(bytestostr(x) for x in targets)
    f = tuple(target for target in targets_strs if not (must_discard(target) or must_discard_extra(target)))
    log("_filter_targets(%s)=%s", csv(targets_strs), f)
    return f


def must_discard_extra(target: str) -> bool:
    return any(x for x in DISCARD_EXTRA_TARGETS if x.match(target))


def must_discard(target: str) -> bool:
    return any(x for x in DISCARD_TARGETS if x.match(target))


TRANSLATED_TARGETS: dict[str, str] = {
    "application/x-moz-nativehtml": "UTF8_STRING",
}


def get_discard_targets(envname: str = "DISCARD", default_value: Iterable[str] = ()) -> Iterable[str]:
    _discard_target_strs_ = os.environ.get("XPRA_%s_TARGETS" % envname)
    if _discard_target_strs_ is None:
        return default_value
    return _discard_target_strs_.split(",")


DISCARD_EXTRA_TARGETS = tuple(re.compile(dt) for dt in get_discard_targets(
    "DISCARD_EXTRA", (
        r"^SAVE_TARGETS$",
        r"^COMPOUND_TEXT",
        r"GTK_TEXT_BUFFER_CONTENTS",
    )
))
DISCARD_TARGETS = tuple(re.compile(dt) for dt in get_discard_targets(
    "DISCARD", (
        r"^NeXT",
        r"^com\.apple\.",
        r"^CorePasteboardFlavorType",
        r"^dyn\.",
        r"^resource-transfer-format",  # eclipse
        r"^x-special/",  # ie: gnome file copy
        r"^application/vnd.portal.",  # portal uses dbus, which is not forwarded
    )
))
UTF8_TEXT_FALLBACK_TARGETS: Sequence[str] = tuple(
    os.environ.get(
        "XPRA_CLIPBOARD_UTF8_TEXT_FALLBACK_TARGETS",
        "text/csv,text/tab-separated-values,text/markdown",
    ).split(",")
)
UTF8_TEXT_FALLBACK_TARGET_NAMES = frozenset(
    target.lower().replace(" ", "") for target in UTF8_TEXT_FALLBACK_TARGETS
)
DEFAULT_TEXT_TARGETS = (
    "UTF8_STRING,TEXT,STRING,"
    "text/plain;charset=utf-8,text/plain;charset=UTF-8,"
    "text/plain;charset=utf8,text/plain;charset=UTF8,"
    "text/plain; charset=utf-8,text/plain; charset=UTF-8,text/plain,"
    "text/html,text/html;charset=utf-8,text/html;charset=UTF-8,"
    "text/html; charset=utf-8,text/html; charset=UTF-8,"
    f"{','.join(UTF8_TEXT_FALLBACK_TARGETS)}"
)
TEXT_TARGETS: Sequence[str] = tuple(
    os.environ.get(
        "XPRA_CLIPBOARD_TEXT_TARGETS",
        DEFAULT_TEXT_TARGETS,
    ).split(",")
)
HTML_TARGETS: Sequence[str] = tuple(
    os.environ.get(
        "XPRA_CLIPBOARD_HTML_TARGETS",
        "text/html,text/html;charset=utf-8,text/html;charset=UTF-8,"
        "text/html; charset=utf-8,text/html; charset=UTF-8",
    ).split(",")
)
URI_TARGETS: Sequence[str] = tuple(
    os.environ.get("XPRA_CLIPBOARD_URI_TARGETS", "text/uri-list").split(",")
)
PLAIN_TEXT_TARGETS: Sequence[str] = tuple(
    target for target in TEXT_TARGETS if target not in HTML_TARGETS and target not in URI_TARGETS
)
RTF_TARGETS: Sequence[str] = tuple(
    os.environ.get("XPRA_CLIPBOARD_RTF_TARGETS", "text/rtf,application/rtf").split(",")
)
PDF_TARGETS: Sequence[str] = tuple(
    os.environ.get("XPRA_CLIPBOARD_PDF_TARGETS", "application/pdf").split(",")
)
IMAGE_TARGETS: Sequence[str] = tuple(
    os.environ.get(
        "XPRA_CLIPBOARD_IMAGE_TARGETS",
        "image/png,image/jpeg,image/tiff,image/webp,image/bmp",
    ).split(",")
)
DEFAULT_EAGER_TARGETS = (
    "UTF8_STRING,text/plain;charset=utf-8,text/plain;charset=UTF-8,"
    "text/plain;charset=utf8,text/plain;charset=UTF8,"
    "text/plain; charset=utf-8,text/plain; charset=UTF-8,text/plain,"
    "text/html,text/html;charset=utf-8,text/html;charset=UTF-8,"
    "text/html; charset=utf-8,text/html; charset=UTF-8,text/uri-list,TEXT,STRING,"
    f"{','.join(UTF8_TEXT_FALLBACK_TARGETS)},"
    f"{','.join(RTF_TARGETS)},image/png,image/jpeg,image/webp,image/bmp,application/pdf"
)
# the targets we send with the clipboard token to greedy clients,
# in the order in which they are collected:
# the cheap ones come first, so that they always fit within the token size limit
EAGER_TARGETS: Sequence[str] = tuple(
    os.environ.get(
        "XPRA_CLIPBOARD_EAGER_TARGETS",
        DEFAULT_EAGER_TARGETS,
    ).split(",")
)


def is_utf8_target(target: str) -> bool:
    """Return whether a text target carries UTF-8 encoded data."""
    name = bytestostr(target).lower().replace(" ", "")
    return any((
        name == "utf8_string",
        "charset=utf-8" in name,
        "charset=utf8" in name,
        name == "public.utf8-plain-text",
        name in UTF8_TEXT_FALLBACK_TARGET_NAMES,
    ))


def choose_eager_targets(targets: Iterable[str], preferred_targets: Iterable[str] = ()) -> Sequence[str]:
    available = tuple(dict.fromkeys(bytestostr(target) for target in targets))
    preferred = tuple(dict.fromkeys(bytestostr(target) for target in preferred_targets))
    supported = set(preferred or available)
    eager = tuple(target for target in EAGER_TARGETS if target in available and target in supported)
    if eager:
        return eager
    common = tuple(target for target in preferred if target in available)
    return common[:1] or available[:1]
