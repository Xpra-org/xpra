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
TEXT_TARGETS: Sequence[str] = tuple(
    os.environ.get("XPRA_CLIPBOARD_TEXT_TARGETS",
                   "UTF8_STRING,TEXT,STRING,text/plain;charset=utf-8,text/plain,text/html").split(",")
)
HTML_TARGETS: Sequence[str] = tuple(
    os.environ.get("XPRA_CLIPBOARD_HTML_TARGETS", "text/html").split(",")
)
URI_TARGETS: Sequence[str] = tuple(
    os.environ.get("XPRA_CLIPBOARD_URI_TARGETS", "text/uri-list").split(",")
)
PLAIN_TEXT_TARGETS: Sequence[str] = tuple(
    target for target in TEXT_TARGETS if target not in HTML_TARGETS and target not in URI_TARGETS
)
EAGER_TARGETS: Sequence[str] = tuple(
    os.environ.get(
        "XPRA_CLIPBOARD_EAGER_TARGETS",
        "UTF8_STRING,text/plain;charset=utf-8,text/plain,text/html,text/uri-list,TEXT,STRING,image/png,image/jpeg",
    ).split(",")
)


def choose_eager_targets(targets: Iterable[str], preferred_targets: Iterable[str] = ()) -> Sequence[str]:
    available = tuple(dict.fromkeys(bytestostr(target) for target in targets))
    preferred = tuple(dict.fromkeys(bytestostr(target) for target in preferred_targets))
    supported = set(preferred or available)
    eager = tuple(target for target in EAGER_TARGETS if target in available and target in supported)
    if eager:
        return eager
    common = tuple(target for target in preferred if target in available)
    return common[:1] or available[:1]
