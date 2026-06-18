# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Lightweight gettext initialization.

GUI modules that want translatable strings simply do::

    from xpra.util.i18n import _
    ...
    label = _("Disconnect")

Importing this module binds the ``messages`` gettext domain to the catalogs
installed under ``<resources-dir>/locales`` and re-exports ``_`` (which is
literally ``gettext.gettext``).

This module only depends on the standard library ``gettext`` module and on
``xpra.platform.paths`` (which pulls in no GUI toolkit), so it is safe to
import from standalone dialogs without dragging in heavy dependencies.

The language is selected by gettext from the ``LANGUAGE``/``LC_ALL``/
``LC_MESSAGES``/``LANG`` environment variables, and falls back to the
(English) msgids when no matching catalog is found.  On MS Windows, when
none of those environment variables are set, the user's default UI language
is used.
"""

import os
from collections.abc import Callable

from xpra.log import Logger

log = Logger("i18n")

LANGUAGE_ENV_KEYS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def notranslate(value: str) -> str:
    return value


def get_win32_language() -> str:
    try:
        import locale
        from xpra.platform.win32.common import GetUserDefaultUILanguage
        return locale.windows_locale.get(int(GetUserDefaultUILanguage()), "")
    except Exception:
        log("get_win32_language()", exc_info=True)
        return ""


def init_win32_language() -> None:
    if any(os.environ.get(key) for key in LANGUAGE_ENV_KEYS):
        return
    if language := get_win32_language():
        log("init_win32_language() using %r", language)
        os.environ["LANGUAGE"] = language


def init() -> Callable[[str], str]:
    for k in LANGUAGE_ENV_KEYS:
        log("%s=%r", k, os.environ.get(k))
    from xpra.os_util import WIN32
    if WIN32:
        init_win32_language()
    DOMAIN = "messages"
    try:
        import gettext
        from xpra.platform.paths import get_resources_dir
        localedir = os.path.join(get_resources_dir(), "locales")
        gettext.bindtextdomain(DOMAIN, localedir)
        gettext.textdomain(DOMAIN)

        def translate(value: str) -> str:
            ret = gettext.gettext(value)
            log("translate(%r)=%r", value, ret)
            return ret

        return translate
    except Exception:
        log("init()", exc_info=True)
        # never let a missing/broken catalog directory break the GUI:
        # gettext.gettext then simply returns the untranslated msgids
        return notranslate


_ = init()
